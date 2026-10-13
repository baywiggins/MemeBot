"""Source evidence is dated; missing metadata never becomes proof of daily posting."""

import json
from datetime import timedelta
from importlib.resources import files

from .discovery import YouTubeCatalog, cadence_report


def seed_sources(store):
    if store.setting("sources_seeded"):
        return
    data = json.loads(files("memebot").joinpath("data/sources.json").read_text())
    for source in data["sources"]:
        if not store.one("SELECT id FROM sources WHERE id=?", (source["id"],)):
            store.add_source(
                source["id"],
                source["name"],
                enabled=source.get("enabled", True),
                notes=source["notes"],
                research=source.get("research", {}),
            )
    store.set_setting("sources_seeded", True)


def refresh_sources(store, config, as_of, progress=None):
    catalog = YouTubeCatalog(config.api_key)
    sources = store.all("SELECT * FROM sources ORDER BY name")
    errors = []
    for i, source in enumerate(sources):
        if progress:
            progress(i / max(1, len(sources)), f"Checking history for {source['name']}")
        try:
            rows = catalog.uploads(source["id"], as_of - timedelta(days=14), as_of, config.timezone)
            details = {}
            for offset in range(0, len(rows), 50):
                ids = ",".join(r["id"] for r in rows[offset : offset + 50])
                data = catalog.get("videos", part="contentDetails,snippet", id=ids)
                for v in data.get("items", []):
                    import re

                    match = re.fullmatch(
                        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", v["contentDetails"]["duration"]
                    )
                    details[v["id"]] = (
                        sum(
                            int(n or 0) * factor for n, factor in zip(match.groups(), [3600, 60, 1])
                        )
                        if match
                        else 0
                    )
            # Duration/title filtering is only a preliminary fit screen, not editorial verification.
            matched = [
                dict(r, duration=details[r["id"]])
                for r in rows
                if details.get(r["id"], 0) >= 180
                and any(
                    w in r["title"].lower() for w in ("meme", "laugh", "clips", "funny", "brain")
                )
            ]
            report = cadence_report(matched, as_of, config.timezone)
            report.update(
                {
                    "evidence": "YouTube Data API playlist publication timestamps",
                    "fit": "Title/duration screen; review sample footage to confirm fit",
                    "sample_urls": [
                        f"https://www.youtube.com/watch?v={r['id']}" for r in matched[-3:]
                    ],
                }
            )
            store.execute(
                "UPDATE sources SET research=?,error=NULL WHERE id=?",
                (json.dumps(report), source["id"]),
            )
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
            store.execute("UPDATE sources SET error=? WHERE id=?", (str(exc), source["id"]))
    if errors:
        raise RuntimeError("; ".join(errors))
    return {"sources_checked": len(sources), "as_of": as_of.isoformat()}
