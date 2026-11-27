#!/usr/bin/env python3
"""Generate Pelican trip and footprint articles from a shared scraper archive."""

import hashlib
from pathlib import Path

from aventures_archive import read_json, read_trip
from aventures_writers import build_trip_rst
from common_archive import _write_json


def _conversion_state(profile_path, trip_path, category):
    return {
        "version": 1,
        "profile_hash": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "profile_mtime_ns": profile_path.stat().st_mtime_ns,
        "trip_hash": hashlib.sha256(trip_path.read_bytes()).hexdigest(),
        "trip_mtime_ns": trip_path.stat().st_mtime_ns,
        "category": category,
    }


def convert(output, content, trip_slug=None, category="findpenguins", update=False):
    """! @brief Regenerate Pelican RST articles from the manifests of an archive.
    @param output Archive directory containing `*/profile.json` and `*/*/trip.json`.
    @param content Pelican articles destination directory.
    @param trip_slug Optional trip slug; when given only that trip is converted.
    @param category Pelican trip category and first service tag.
    @param update Convert only changed or missing trip articles.
    @return None
    @throws ValueError When no profile manifest exists or the requested slug is not found.
    """
    root = Path(output)
    profiles = sorted(root.glob("*/profile.json"))
    if not profiles:
        raise ValueError(f"No profile manifests found in {root}; scrape again to create them")
    count = 0
    found = False
    for profile_path in profiles:
        profile = read_json(profile_path)
        for trip_path in sorted(profile_path.parent.glob("*/trip.json")):
            trip = read_trip(root, trip_path)
            if trip_slug and trip.get("slug") != trip_slug:
                continue
            found = True
            article_dir = Path(content) / str(profile["user"]["uid"]) / str(trip["slug"])
            state_path = article_dir / ".aventures-conversion.json"
            state = _conversion_state(profile_path, trip_path, category)
            if update:
                articles = [article_dir / "trip.rst"]
                articles.extend(
                    article_dir / f"footprint_{index}" / "footprint.rst"
                    for index, _ in enumerate(trip.get("footprints", []), start=1)
                )
                if state_path.is_file() and all(path.is_file() for path in articles):
                    try:
                        previous_state = read_json(state_path)
                    except (OSError, ValueError) as exc:
                        print(f"  WARNING: unable to read conversion state {state_path}: {exc}")
                    else:
                        if previous_state == state:
                            print(f"  - Unchanged trip articles: {trip.get('slug')}")
                            continue
            state_path.unlink(missing_ok=True)
            build_trip_rst(str(content), str(trip_path.parent), profile["user"], trip,
                           trip.get("footprints", []), profile["sizes"], category)
            _write_json(str(state_path), state)
            count += 1
    if trip_slug and not found:
        raise ValueError(f"No archived trip found with slug: {trip_slug}")
    print(f"Generated articles for {count} trip(s)")
