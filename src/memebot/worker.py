"""One OS-locked worker; durable jobs survive UI reruns and process crashes."""

import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import date

from .config import Config
from .store import Store
from .timeutil import utcnow


@contextmanager
def worker_lock(home, *, wait=False):
    home.mkdir(parents=True, exist_ok=True)
    with (home / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def spawn_worker(config):
    env = {**os.environ, "MEMEBOT_HOME": str(config.home)}
    with (config.home / "worker.log").open("a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "memebot.cli", "worker"],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )


def queue_job(config, kind, payload):
    db = Store(config.db_path)
    jid = db.enqueue(kind, payload)
    spawn_worker(config)
    return jid


def dispatch(config, store, kind, payload, progress):
    from .episodes import Episodes
    from .pipeline import collect, render_episode

    if kind == "collect":
        return collect(store, config, date.fromisoformat(payload["date"]), progress)
    if kind == "draft":
        return Episodes(store).draft(payload["date"], config.brand)
    if kind == "render":
        return render_episode(store, config, int(payload["episode_id"]), progress)
    if kind == "research":
        from .research import refresh_sources

        return refresh_sources(store, config, date.fromisoformat(payload["as_of"]), progress)
    if kind == "connect":
        from .auth import connect
        from .publishing import Publisher

        destination = Publisher(store, connect(config)).destination()
        store.set_setting("destination", destination)
        return {"destination": destination["name"]}
    if kind in ("upload", "publish", "reconcile", "recover-upload"):
        from .auth import authorized_session
        from .publishing import Publisher

        pub = Publisher(store, authorized_session(config))
        eid = int(payload["episode_id"])
        if kind == "upload":
            return pub.upload_private(eid, progress)
        if kind == "publish":
            return pub.publish(eid)
        if kind == "recover-upload":
            return pub.recover_missing(eid, confirmed_absent=payload.get("confirmed_absent", False))
        return pub.reconcile(eid, payload["video_id"])
    raise ValueError(f"Unknown job: {kind}")


def run_worker(config=None):
    config = config or Config.load()
    store = Store(config.db_path)
    count = 0
    try:
        # A replacement must wait out the incumbent's final empty-queue check.
        # Otherwise an enqueue between that check and unlock can be stranded.
        with worker_lock(config.home, wait=True):
            store.recover_jobs()
            while job := store.claim_job():
                count += 1
                try:
                    result = dispatch(
                        config,
                        store,
                        job["kind"],
                        json.loads(job["payload"]),
                        lambda p, m: store.progress(job["id"], p, m),
                    )
                    store.progress(
                        job["id"],
                        1,
                        json.dumps(result, ensure_ascii=False)
                        if result is not None
                        else "Complete",
                    )
                    store.finish_job(job["id"])
                    print(
                        json.dumps(
                            {
                                "time": utcnow(),
                                "job": job["id"],
                                "kind": job["kind"],
                                "status": "done",
                            }
                        ),
                        flush=True,
                    )
                except Exception as exc:
                    store.finish_job(job["id"], str(exc))
                    print(
                        json.dumps(
                            {
                                "time": utcnow(),
                                "job": job["id"],
                                "kind": job["kind"],
                                "status": "failed",
                                "error": str(exc),
                            }
                        ),
                        flush=True,
                    )
    except BlockingIOError:
        pass
    return count
