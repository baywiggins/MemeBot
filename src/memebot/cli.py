"""Command-line interface using the same persistent jobs as the browser."""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from .config import Config
from .store import Store
from .timeutil import yesterday


def parser():
    p = argparse.ArgumentParser(description="MemeBot daily compilation workbench")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["collect", "draft"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--date")
        cmd.add_argument("--background", action="store_true")
    for name in ["render", "upload", "publish", "approve", "reconcile", "recover-upload"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--episode", type=int, required=True)
        if name not in ["approve", "reconcile"]:
            cmd.add_argument("--background", action="store_true")
        if name == "publish":
            cmd.add_argument(
                "--public",
                action="store_true",
                help="Explicitly publish the approved private video publicly",
            )
        if name == "reconcile":
            cmd.add_argument("--video-id", required=True)
        if name == "recover-upload":
            cmd.add_argument(
                "--confirm-no-upload",
                action="store_true",
                help="You checked YouTube Studio and found no upload for this episode",
            )
    for name in ["doctor", "worker", "tick", "connect"]:
        sub.add_parser(name)
    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8501)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    research = sub.add_parser("research")
    research.add_argument("--as-of")
    legacy = sub.add_parser("import-legacy")
    legacy.add_argument("path", type=Path)
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--install", action="store_true")
    schedule.add_argument("--remove", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    config = Config.load()
    store = Store(config.db_path)
    from .research import seed_sources

    seed_sources(store)
    try:
        if args.command == "ui":
            from importlib.resources import files

            theme = json.loads(files("memebot").joinpath("data/theme.json").read_text())["colors"]
            options = [
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(args.port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
                "--theme.base",
                "light",
                "--theme.primaryColor",
                theme["primary"],
                "--theme.backgroundColor",
                theme["background"],
                "--theme.secondaryBackgroundColor",
                theme["surface"],
                "--theme.textColor",
                theme["ink"],
            ]
            return subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(Path(__file__).with_name("ui.py")),
                    *options,
                ]
            )
        if args.command == "doctor":
            for label, ready in config.health().items():
                print(f"{'OK' if ready else 'MISSING'}  {label}")
            print(f"Data directory: {config.home}")
            return 0
        if args.command == "status":
            data = {
                "sources": store.all("SELECT id,name,enabled,error FROM sources"),
                "episodes": store.all(
                    "SELECT id,source_date,revision,duration,approved_revision,upload_state,upload_id FROM episodes"
                ),
                "jobs": store.all(
                    "SELECT id,kind,status,progress,message,error FROM jobs ORDER BY id DESC LIMIT 20"
                ),
            }
            print(
                json.dumps(data, indent=2)
                if args.json
                else "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in data.items())
            )
            return 0
        if args.command == "import-legacy":
            print(f"Imported {store.import_legacy(args.path)} discovered IDs")
            return 0
        if args.command == "worker":
            from .worker import run_worker

            run_worker(config)
            return 0
        if args.command == "tick":
            from .scheduler import schedule_due
            from .worker import run_worker

            schedule_due(config)
            run_worker(config)
            return 0
        if args.command == "schedule":
            from .scheduler import launchagent

            dest = Path.home() / "Library/LaunchAgents/local.memebot.collect.plist"
            domain = f"gui/{os.getuid()}"
            if args.remove:
                subprocess.run(
                    ["launchctl", "bootout", domain, str(dest)], check=False, capture_output=True
                )
                dest.unlink(missing_ok=True)
                print("Collection schedule removed.")
                return 0
            if args.install:
                if not config.api_key:
                    raise ValueError(
                        "Save a YouTube discovery key in Settings before installing the schedule"
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(launchagent(config))
                subprocess.run(
                    ["launchctl", "bootout", domain, str(dest)], check=False, capture_output=True
                )
                subprocess.run(["launchctl", "bootstrap", domain, str(dest)], check=True)
                print(
                    "Daily collection enabled after 9 a.m. America/New_York. Publishing stays manual."
                )
                return 0
            print(launchagent(config).decode())
            return 0
        if args.command == "approve":
            from .episodes import Episodes

            episodes = Episodes(store)
            episodes.approve(args.episode, episodes.get(args.episode)["revision"])
            print("Render approved.")
            return 0
        if args.command == "publish" and not args.public:
            print(
                "Use --public only after reviewing the connected destination and approved video.",
                file=sys.stderr,
            )
            return 2
        if args.command == "recover-upload" and not args.confirm_no_upload:
            raise ValueError(
                "Check YouTube Studio first, then use --confirm-no-upload to request recovery"
            )
        kind = args.command
        if kind in ["collect", "draft"]:
            payload = {
                "date": date.fromisoformat(args.date).isoformat()
                if args.date
                else yesterday(config.timezone).isoformat()
            }
        elif kind == "research":
            payload = {
                "as_of": args.as_of or (yesterday(config.timezone) + timedelta(days=1)).isoformat()
            }
        elif kind == "connect":
            payload = {}
        else:
            payload = {"episode_id": args.episode}
            if kind == "reconcile":
                payload["video_id"] = args.video_id
            if kind == "recover-upload":
                payload["confirmed_absent"] = args.confirm_no_upload
        if kind in ("upload", "publish"):
            destination = store.setting("destination")
            if not destination:
                raise ValueError(
                    "Run memebot connect and confirm the destination channel before upload"
                )
            print(f"Destination: {destination['name']} ({destination['id']})")
        from .worker import queue_job, run_worker

        if getattr(args, "background", False):
            print(f"Queued job {queue_job(config, kind, payload)}")
            return 0
        jid = store.enqueue(kind, payload)
        run_worker(config)
        job = store.one("SELECT * FROM jobs WHERE id=?", (jid,))
        if job["status"] == "failed":
            print(job["error"], file=sys.stderr)
            return 1
        print(job["message"] or f"Job {jid}: {job['status']}")
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
