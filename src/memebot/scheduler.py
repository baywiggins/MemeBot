"""Scheduling collects footage only; publishing is never a scheduled action."""

import plistlib
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .store import Store


def schedule_due(config, now=None):
    now = now or datetime.now(ZoneInfo(config.timezone))
    local = now.astimezone(ZoneInfo(config.timezone))
    if local.hour < 9:
        return None
    day = (local.date() - timedelta(days=1)).isoformat()
    db = Store(config.db_path)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        key = f"scheduled:{day}"
        if conn.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone():
            return None
        # Insert the queue record and scheduling mark in the same transaction.
        import json

        from .timeutil import utcnow

        packed = json.dumps({"date": day}, sort_keys=True, separators=(",", ":"))
        dedup = "collect:" + packed
        existing = conn.execute(
            "SELECT id FROM jobs WHERE dedup_key=? AND status IN ('queued','running','done') ORDER BY id DESC LIMIT 1",
            (dedup,),
        ).fetchone()
        jid = (
            existing["id"]
            if existing
            else conn.execute(
                "INSERT INTO jobs(kind,payload,dedup_key,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("collect", packed, dedup, utcnow(), utcnow()),
            ).lastrowid
        )
        conn.execute("INSERT INTO settings VALUES(?,?)", (key, json.dumps(jid)))
        return jid


def launchagent(config):
    return plistlib.dumps(
        {
            "Label": "local.memebot.collect",
            "ProgramArguments": [sys.executable, "-m", "memebot.cli", "tick"],
            "StartInterval": 900,
            "RunAtLoad": True,
            "EnvironmentVariables": {
                "MEMEBOT_HOME": str(config.home),
                "MEMEBOT_TIMEZONE": config.timezone,
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            },
            "StandardOutPath": str(config.home / "scheduler.log"),
            "StandardErrorPath": str(config.home / "scheduler.log"),
        }
    )
