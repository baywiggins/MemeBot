import json

from memebot.cli import main


def test_status_and_doctor_work_without_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["episodes"] == [] and data["jobs"] == []
    assert main(["doctor"]) == 0
    assert "YouTube discovery key" in capsys.readouterr().out


def test_publish_requires_explicit_public_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    assert main(["publish", "--episode", "1"]) == 2


def test_collect_reports_failure_as_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    assert main(["collect", "--date", "2026-10-11"]) == 1


def test_foreground_waits_for_worker_and_reports_final_failure(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    from memebot.worker import worker_lock

    monkeypatch.setenv("MEMEBOT_HOME", str(tmp_path))
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with worker_lock(tmp_path):
        process = subprocess.Popen(
            [sys.executable, "-m", "memebot.cli", "collect", "--date", "2026-10-11"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        still_waiting = process.poll() is None
    out, err = process.communicate(timeout=10)
    assert still_waiting, "foreground exited while another worker held the queue lock"
    assert process.returncode == 1 and b"YOUTUBE_API_KEY" in err
