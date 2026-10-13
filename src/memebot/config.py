"""Local configuration; credentials never enter the database or logs."""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    home: Path
    api_key: str = ""
    timezone: str = "America/New_York"
    brand: str = "MemeBot"

    @classmethod
    def load(cls):
        load_dotenv()
        home = Path(os.environ.get("MEMEBOT_HOME", "~/.local/share/memebot")).expanduser().resolve()
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        saved = (
            json.loads((home / "config.json").read_text())
            if (home / "config.json").exists()
            else {}
        )
        return cls(
            home,
            os.environ.get("YOUTUBE_API_KEY", os.environ.get("API_KEY", saved.get("api_key", ""))),
            os.environ.get("MEMEBOT_TIMEZONE", "America/New_York"),
            os.environ.get("MEMEBOT_BRAND", saved.get("brand", "MemeBot")),
        )

    @property
    def db_path(self):
        return self.home / "state.db"

    def health(self):
        return {
            "FFmpeg": bool(shutil.which("ffmpeg")),
            "FFprobe": bool(shutil.which("ffprobe")),
            "JavaScript runtime": bool(shutil.which("node") or shutil.which("deno")),
            "YouTube discovery key": bool(self.api_key),
            "YouTube OAuth client": (self.home / "client_secret.json").is_file(),
            "YouTube connection": (self.home / "token.json").is_file(),
        }
