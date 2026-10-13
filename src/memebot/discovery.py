"""YouTube upload playlist discovery and evidence-based cadence reporting."""

from collections import Counter
from datetime import date, timedelta
from statistics import median
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .store import CHANNEL_RE
from .timeutil import day_window, parse_time, utcnow


class YouTubeCatalog:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Set YOUTUBE_API_KEY in .env to collect channel uploads")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
                )
            ),
        )

    def get(self, resource, **params):
        try:
            response = self.session.get(
                f"https://www.googleapis.com/youtube/v3/{resource}",
                params={**params, "key": self.api_key},
                timeout=30,
            )
        except requests.RequestException:
            raise RuntimeError(
                "YouTube could not be reached; check your connection and retry"
            ) from None
        if not response.ok:
            # Never include the URL, API key, or raw request exceptions in errors.
            try:
                reason = response.json()["error"]["errors"][0]["reason"]
            except (ValueError, KeyError, IndexError):
                reason = "requestFailed"
            raise RuntimeError(f"YouTube returned {response.status_code}: {reason}")
        return response.json()

    def channel(self, identifier):
        identifier = identifier.strip().rstrip("/").removesuffix("/videos")
        if "/channel/" in identifier:
            identifier = identifier.split("/channel/")[-1]
        elif "/@" in identifier:
            identifier = "@" + identifier.split("/@")[-1]
        if CHANNEL_RE.fullmatch(identifier):
            params = {"id": identifier}
        elif identifier.startswith("@"):
            params = {"forHandle": identifier}
        else:
            raise ValueError("Enter a channel ID, channel URL, or @handle")
        data = self.get("channels", part="snippet,contentDetails", **params)
        if not data.get("items"):
            raise ValueError("Channel not found")
        return data["items"][0]

    def uploads(self, channel_id, start_day, end_day=None, zone="America/New_York"):
        end_day = end_day or start_day + timedelta(days=1)
        start = day_window(start_day, zone)[0]
        end = day_window(end_day, zone)[0]
        channel = self.channel(channel_id)
        playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        token = None
        seen = set()
        results = {}
        while True:
            args = {"playlistId": playlist, "part": "snippet,contentDetails", "maxResults": 50}
            if token:
                args["pageToken"] = token
            page = self.get("playlistItems", **args)
            for item in page.get("items", []):
                details = item.get("contentDetails", {})
                timestamp = details.get("videoPublishedAt")
                if not timestamp or not details.get("videoId"):
                    continue
                published = parse_time(timestamp)
                if start <= published < end:
                    vid = details["videoId"]
                    results[vid] = {
                        "id": vid,
                        "source_id": channel["id"],
                        "title": item.get("snippet", {}).get("title", "Untitled"),
                        "published_at": published.isoformat(),
                        "source_date": published.astimezone(ZoneInfo(zone)).date().isoformat(),
                    }
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen:
                raise RuntimeError("YouTube repeated a pagination token; retry collection")
            seen.add(token)
        return sorted(results.values(), key=lambda v: (v["published_at"], v["id"]))


def collect_catalog(store, catalog, day, zone="America/New_York", progress=None):
    sources = store.all("SELECT * FROM sources WHERE enabled=1 ORDER BY id")
    if not sources:
        raise ValueError("Enable at least one source channel before collecting")
    count = 0
    errors = []
    for index, source in enumerate(sources):
        if progress:
            progress(index / max(len(sources), 1), f"Checking {source['name']}")
        try:
            rows = catalog.uploads(source["id"], day, day + timedelta(days=1), zone)
            for row in rows:
                store.save_video(row)
            count += len(rows)
            store.execute(
                "UPDATE sources SET last_checked=?,error=NULL WHERE id=?", (utcnow(), source["id"])
            )
        except Exception as exc:
            errors.append({"source": source["name"], "error": str(exc)})
            store.execute(
                "UPDATE sources SET last_checked=?,error=? WHERE id=?",
                (utcnow(), str(exc), source["id"]),
            )
    return {"videos": count, "errors": errors, "sources": len(sources)}


def cadence_report(videos, as_of: date, zone="America/New_York"):
    days = [as_of - timedelta(days=n) for n in range(14, 0, -1)]
    counts = Counter()
    durations = []
    seen = set()
    for v in videos:
        if v["id"] in seen or not v.get("published_at"):
            continue
        seen.add(v["id"])
        day = parse_time(v["published_at"]).astimezone(ZoneInfo(zone)).date()
        if day in days:
            counts[day] += 1
            if v.get("duration"):
                durations.append(v["duration"])
    return {
        "as_of": as_of.isoformat(),
        "timezone": zone,
        "daily_last_7": all(counts[d] > 0 for d in days[-7:]),
        "active_days_14": sum(counts[d] > 0 for d in days),
        "uploads_per_day": {d.isoformat(): counts[d] for d in days},
        "missing_days": [d.isoformat() for d in days if not counts[d]],
        "median_duration": median(durations) if durations else None,
    }
