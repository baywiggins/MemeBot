"""Media operations use argument arrays, never shell interpolation."""

import hashlib
import json
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import imagehash
from PIL import Image


def command(args, *, timeout=7200):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1800:] or "Media command failed")
    return result.stdout


def probe(path):
    data = json.loads(
        command(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            timeout=60,
        )
    )
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if not video:
        raise ValueError("The file contains no video stream")
    duration = float(data.get("format", {}).get("duration", video.get("duration", 0)))
    if duration <= 0:
        raise ValueError("The video has no usable duration")
    return {
        "duration": duration,
        "width": video["width"],
        "height": video["height"],
        "fps": float(Fraction(video.get("avg_frame_rate") or "0/1")),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }


def validate_decode(path):
    """Reject damaged packets as well as malformed headers before caching footage."""
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-err_detect",
            "explode",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ]
    )


def analysis_markers(log):
    markers = []
    start = None
    for line in log.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            start = float(m[1])
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            markers.append({"kind": "silence", "start": start, "end": float(m[1])})
            start = None
        m = re.search(r"black_start:([\d.]+) black_end:([\d.]+)", line)
        if m:
            markers.append({"kind": "black", "start": float(m[1]), "end": float(m[2])})
    return sorted(markers, key=lambda m: m["start"])


def detect_scenes(path):
    from scenedetect import AdaptiveDetector, detect

    info = probe(path)
    scenes = detect(str(path), AdaptiveDetector(min_scene_len=0.7), show_progress=False)
    boundaries = [(a.get_seconds(), b.get_seconds()) for a, b in scenes]
    if not boundaries:
        boundaries = [(0, info["duration"])]
    args = ["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.15:pix_th=0.1"]
    if info["has_audio"]:
        args += ["-af", "silencedetect=noise=-35dB:d=0.25"]
    result = subprocess.run([*args, "-f", "null", "-"], capture_output=True, timeout=7200)
    if result.returncode:
        raise RuntimeError("Could not scan source audio/video markers")
    return boundaries, analysis_markers(result.stderr.decode(errors="replace"))


def fingerprint(path, start, end):
    info = probe(path)
    prefix = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(end - start)]
    visual = command(
        [
            *prefix,
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "scale=160:90,fps=15,format=rgb24",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ]
    )
    sound = (
        command(
            [
                *prefix,
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ]
        )
        if info["has_audio"]
        else b"no audio"
    )
    exact = hashlib.sha256(visual + b"\n" + sound).hexdigest()
    # Relative frame samples allow duration-tolerant comparison. Near matches are only warnings.
    raw = command(
        [
            *prefix,
            "-an",
            "-vf",
            f"fps={5 / max(end - start, 0.1)},scale=64:64,format=rgb24",
            "-frames:v",
            "5",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    size = 64 * 64 * 3
    hashes = []
    for i in range(0, len(raw) - size + 1, size):
        im = Image.frombytes("RGB", (64, 64), raw[i : i + size])
        # Uniform/blank frames do not provide useful duplicate evidence.
        import numpy as np

        if float(np.asarray(im.convert("L")).std()) > 4:
            hashes.append(str(imagehash.phash(im)))
    return exact, hashes


def similar_fingerprints(a, b):
    if len(a) < 3 or len(b) < 3:
        return False
    a = [int(v, 16) for v in a]
    b = [int(v, 16) for v in b]
    if not any(5 < x.bit_count() < 59 for x in a + b):
        return False
    pairs = list(zip(a, b))
    return sum((x ^ y).bit_count() <= 10 for x, y in pairs) / len(pairs) >= 0.8


def render_segments(clips, output, progress=None):
    if not clips:
        raise ValueError("Select at least one clip before rendering")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=output.parent) as work:
        paths = []
        for i, clip in enumerate(clips):
            if progress:
                progress(i / len(clips), f"Rendering clip {i + 1} of {len(clips)}")
            info = probe(clip["path"])
            duration = clip["end"] - clip["start"]
            if duration <= 0 or clip["start"] < 0 or clip["end"] > info["duration"] + 0.1:
                raise ValueError("A clip extends outside its source video")
            dest = Path(work) / f"{i:05}.mp4"
            paths.append(dest)
            args = [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(clip["start"]),
                "-i",
                str(clip["path"]),
            ]
            if not info["has_audio"]:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            args += [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0" if info["has_audio"] else "1:a:0",
                "-t",
                str(duration),
                "-vf",
                "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p",
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-movflags",
                "+faststart",
                str(dest),
            ]
            command(args)
        concat = Path(work) / "concat.txt"
        concat.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n" for p in paths))
        temp = output.with_name(output.stem + ".partial.mp4")
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temp),
            ]
        )
        info = probe(temp)
        if not info["has_audio"]:
            raise RuntimeError("Rendered output is missing audio")
        temp.replace(output)
    return info


def thumbnail(path, at, output):
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(at),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-q:v",
            "3",
            str(output),
        ],
        timeout=60,
    )
