import subprocess

import pytest

from memebot.media import (
    analysis_markers,
    fingerprint,
    probe,
    render_segments,
    similar_fingerprints,
)


def make_video(path, color="red", audio=False, duration=1):
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=160x240:r=24:d={duration}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=600:duration={duration}"]
    args += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run([*args, str(path)], check=True, capture_output=True)


@pytest.mark.media
def test_render_portrait_silent_and_landscape_audio(tmp_path):
    a = tmp_path / "first clip.mp4"
    b = tmp_path / "second.mp4"
    out = tmp_path / "render.mp4"
    make_video(a)
    make_video(b, "blue", True)
    render_segments(
        [{"path": str(a), "start": 0, "end": 1}, {"path": str(b), "start": 0, "end": 1}], out
    )
    info = probe(out)
    assert (info["width"], info["height"]) == (1920, 1080)
    assert info["fps"] == 30 and info["has_audio"]
    assert abs(info["duration"] - 2) < 0.15
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"],
        check=True,
        capture_output=True,
    )


@pytest.mark.media
def test_exact_fingerprint_includes_audio_not_just_static_visual(tmp_path):
    a = tmp_path / "silent.mp4"
    b = tmp_path / "sound.mp4"
    make_video(a)
    make_video(b, audio=True)
    ah, ap = fingerprint(a, 0, 1)
    bh, bp = fingerprint(b, 0, 1)
    assert ah != bh
    assert fingerprint(a, 0, 1)[0] == ah


def test_near_duplicate_requires_informative_frames():
    assert not similar_fingerprints(["0000000000000000"] * 5, ["0000000000000000"] * 5)
    assert similar_fingerprints(["a4bc1098de345672"] * 5, ["a4bc1098de345673"] * 5)
    assert not similar_fingerprints(["a4bc1098de345672"] * 5, ["5b43ef6721cba98d"] * 5)


def test_silence_and_black_markers_parse():
    log = "silence_start: 2.5\nsilence_end: 4 | silence_duration: 1.5\nblack_start:6 black_end:7 black_duration:1"
    assert analysis_markers(log) == [
        {"kind": "silence", "start": 2.5, "end": 4.0},
        {"kind": "black", "start": 6.0, "end": 7.0},
    ]
