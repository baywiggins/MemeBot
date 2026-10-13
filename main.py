"""Compatibility entrypoint. Prefer `uv run memebot ui`."""
from memebot.cli import main

if __name__ == '__main__':
    raise SystemExit(main(['ui']))
