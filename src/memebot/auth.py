"""Desktop OAuth with private local credential files."""

import json
import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(temporary, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out, indent=2)
    temporary.replace(path)


def connect(config):
    path = config.home / "client_secret.json"
    if not path.exists():
        raise ValueError("Add your Google OAuth desktop client JSON in Settings first")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    credentials = flow.run_local_server(
        port=0,
        open_browser=True,
        timeout_seconds=180,
        success_message="MemeBot is connected. You can close this tab and return to the workbench.",
    )
    private_json(config.home / "token.json", json.loads(credentials.to_json()))
    return authorized_session(config)


def authorized_session(config):
    path = config.home / "token.json"
    if not path.exists():
        raise ValueError("Connect your YouTube channel in Settings first")
    credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception:
            raise ValueError("YouTube authorization expired. Reconnect in Settings.") from None
        private_json(path, json.loads(credentials.to_json()))
    if not credentials.valid:
        raise ValueError("Reconnect your YouTube channel in Settings")
    return AuthorizedSession(credentials)
