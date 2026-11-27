"""Orchestrate Polarsteps profile and trip archiving."""

from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests

from aventures_archive import read_json, read_trip
from common_archive import _write_json, write_profile, write_trip
from common_config import GPX_NS, XSI_NS
from common_profiles import DEFAULT_SETTINGS, load_profiles
from common_utils import country_flag, download_country_flags, gpx_tag
from common_writers import build_merged_xml, build_trip_gpx, build_user_xml, save_trip_route_map
from output_safety import clear_folders, validate_component
from polarsteps_config import API_URL, API_VERSION, MEDIA_URL, SITE_URL, WEATHER_ICONS
from polarsteps_parsers import (
    _coordinates,
    _decode_route,
    _round_integer,
    _stringify_trip_numbers,
    _track_points,
    _trip_companions,
    description_text,
    local_date,
    normalize_trip,
    seed_gpx,
    slug_for_trip,
    transport_distances_from_gpx,
    weather_icon,
)
from polarsteps_utils import (
    PlaywrightError,
    _remember_token,
    _require_list,
    _restrict_login_requests,
    api_get,
    download_media,
    load_profile,
    login,
    media_url,
    source_data,
    sync_playwright,
)


def _modified_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _archived_trip(root, profile_dir, trip_dir, slug, trip_id):
    manifest_path = trip_dir / "trip.json"
    snapshot_path = trip_dir / "api-trip.json"
    if not manifest_path.is_file() or not snapshot_path.is_file():
        return None, None
    manifest = read_json(manifest_path)
    trip = read_trip(str(root), str(manifest_path))
    if trip.get("slug") != slug:
        print(f"  WARNING: archived trip slug does not match {slug}; processing it again")
        return None, None
    timestamp = manifest.get("source_last_modified")
    if timestamp is None and snapshot_path.stat().st_mtime_ns < manifest_path.stat().st_mtime_ns:
        with snapshot_path.open(encoding="utf-8") as handle:
            snapshot = json.load(handle)
        if isinstance(snapshot, dict) and str(snapshot.get("id")) == trip_id:
            timestamp = snapshot.get("last_modified")
    paths = [profile_dir / (slug + ".gpx")]
    for key in ("image", "route_map", "satellite_map"):
        if trip.get(key):
            paths.append(profile_dir / trip[key])
    for companion in trip.get("companions") or []:
        if companion.get("picture"):
            paths.append(profile_dir / companion["picture"])
    for footprint in trip.get("footprints") or []:
        for key in ("photos", "videos", "gpx", "pdf"):
            paths.extend(Path(path) for path in footprint.get(key) or [])
    if any(not path.is_file() for path in paths):
        print(f"  WARNING: archived files are missing for {slug}; processing it again")
        return None, None
    return trip, _modified_time(timestamp)


def scrape(username, output="output", trip_slug=None, skip=False, credentials=None, sizes=None, update=False):
    """Archive one Polarsteps profile and return its user and selected trips.

    `username` identifies the profile to archive; optional `credentials` is a
    login username/password pair. Without credentials, login is interactive.
    Skip mode reads snapshots and existing media without login; elevation
    enrichment may still access the network.
    Update mode fetches live trip details and reuses safely unchanged trips.
    `sizes` overrides the shared image size and map settings.
    """
    if skip and update:
        raise ValueError("--skip and --update cannot be used together")
    validate_component(username)
    if trip_slug:
        validate_component(trip_slug)
    root = Path(output).resolve()
    profile_dir = root / username
    if profile_dir.is_symlink():
        raise ValueError(f"Refusing symbolic-link profile directory: {profile_dir}")
    if (profile_dir / "profile.json").exists() and not (profile_dir / "api-user.json").is_file():
        raise ValueError(f"Archive profile already belongs to another scraper: {profile_dir}")
    profile_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    try:
        if not skip:
            token = login(*credentials) if credentials is not None else login()
            session.cookies.set("remember_token", token, domain="api.polarsteps.com", path="/", secure=True)
        profile = source_data(
            profile_dir / "api-user.json", skip,
            lambda: api_get(session, "/users/byusername/" + quote(username, safe="")),
        )
        entries = [item for item in _require_list(profile, "alltrips", "trips") if not item.get("is_deleted")]
        slugs = [slug_for_trip(item) for item in entries]
        trip_ids = [str(item["id"]) for item in entries]
        if len(set(trip_ids)) != len(trip_ids):
            raise ValueError("Polarsteps trips have duplicate IDs; cannot safely archive them")
        selected = [(item, slug) for item, slug in zip(entries, slugs) if not trip_slug or slug == trip_slug]
        if trip_slug and not selected:
            raise ValueError(f"Trip not found: {trip_slug}")
        country_codes = download_country_flags(root, skip=skip)
        user = {
            "uid": username,
            "name": " ".join(filter(None, (profile.get("first_name"), profile.get("last_name")))) or username,
            "bio": profile.get("description") or "",
            "location": profile.get("living_location_name") or "",
            "website": f"{SITE_URL}/{quote(username, safe='')}",
        }
        picture = profile.get("profile_image_path") or profile.get("profile_image_thumb_path")
        if picture:
            avatar = download_media({"path": picture, "large_thumbnail_path": profile.get("profile_image_thumb_path")},
                                    profile_dir, f"{username}_profile", "photo", skip)
            user["picture"] = os.path.relpath(avatar, profile_dir)
        settings = {**DEFAULT_SETTINGS, **(sizes or {})}
        write_profile(str(profile_dir), user, settings, only_if_changed=update)
        trips = []
        reused = 0
        for entry, slug in selected:
            trip_id = str(entry["id"])
            if not trip_id.isdecimal():
                raise ValueError(f"Invalid Polarsteps trip ID: {trip_id!r}")
            trip_dir = profile_dir / slug
            if trip_dir.is_symlink():
                raise ValueError(f"Refusing symbolic-link trip directory: {trip_dir}")
            if (trip_dir / "trip.json").exists() and not (trip_dir / "api-trip.json").is_file():
                raise ValueError(f"Archive trip already belongs to another scraper: {trip_dir}")
            trip_dir.mkdir(parents=True, exist_ok=True)
            gpx = profile_dir / (slug + ".gpx")
            if gpx.is_symlink():
                raise ValueError(f"Refusing symbolic-link GPX file: {gpx}")
            if update:
                archived, last_loaded = _archived_trip(root, profile_dir, trip_dir, slug, trip_id)
                source = api_get(session, "/trips/" + trip_id)
            else:
                source = source_data(trip_dir / "api-trip.json", skip, lambda: api_get(session, "/trips/" + trip_id))
            if str(source.get("id")) != trip_id:
                raise ValueError(f"Polarsteps trip ID mismatch for {slug}")
            modified = _modified_time(source.get("last_modified"))
            if update:
                if modified is None:
                    print(f"  WARNING: missing or invalid last_modified for {slug}; processing it again")
                elif archived is not None and last_loaded is None:
                    print(f"  WARNING: no reliable archived last_modified for {slug}; processing it again")
                elif archived is not None and modified <= last_loaded:
                    print(f"  - Unchanged trip: {slug}")
                    trips.append(archived)
                    reused += 1
                    continue
            trip = normalize_trip(source, username, slug, profile_dir, skip, country_codes, refresh=update)
            seed_gpx(gpx, source)
            trip["transports"] = transport_distances_from_gpx(gpx, trip["transports"])
            build_trip_gpx(
                str(gpx), user, trip, trip["footprints"],
                enrich_elevation=True, integer_elevation=True, update_footprint_altitudes=True,
            )
            for key, filename, background, bubbles in (
                ("route_map", "map_trip.png", settings["map_background"], settings["footprint_bubbles"]),
                ("satellite_map", "satellite_trip.png", "satellite", True),
            ):
                try:
                    route_map = save_trip_route_map(
                        str(gpx), trip["footprints"], str(trip_dir / filename),
                        background=background, show_footprint_bubbles=bubbles,
                        footprint_bubble_size=settings["footprint_bubble_size"],
                    )
                    if route_map:
                        trip[key] = os.path.relpath(route_map, profile_dir)
                except (OSError, ET.ParseError, ValueError, requests.RequestException) as exc:
                    print(f"  - WARNING: unable to create {filename} for {trip['title']}: {exc}")
            if update:
                _write_json(str(trip_dir / "api-trip.json"), source)
            write_trip(
                str(root), str(trip_dir), _stringify_trip_numbers(trip),
                source_last_modified=source["last_modified"] if modified is not None else None,
            )
            trips.append(trip)
        xml = profile_dir / (username + ".xml")
        if xml.is_symlink():
            raise ValueError(f"Refusing symbolic-link XML file: {xml}")
        build_user_xml(user, trips).write(xml, encoding="utf-8", xml_declaration=True)
        if update:
            print(f"Archived {len(trips) - reused} and reused {reused} Polarsteps trip(s) for {username}")
        else:
            print(f"Archived {len(trips)} Polarsteps trip(s) for {username}")
        return user, trips
    finally:
        session.close()


def scrape_profiles(profiles_file, output="output", trip_slug=None, skip=False, force=False, update=False):
    """Archive the Polarsteps accounts from a shared profiles file.

    Force clears the output directory, or only each profile's selected trip and
    GPX when a slug is supplied. Skip or update overrides force. Return the collected
    (user, trips) pairs and write a merged XML index for multiple accounts.
    """
    if skip and update:
        raise ValueError("--skip and --update cannot be used together")
    profiles, settings = load_profiles(profiles_file, "polarsteps")
    ids = [profile_id for profile_id, _, _ in profiles]
    if len(set(ids)) != len(ids):
        raise ValueError("Polarsteps profiles have duplicate IDs")
    for profile_id in ids:
        validate_component(profile_id)
    if force and (skip or update):
        print(f"  --{'skip' if skip else 'update'} disables --force to preserve saved snapshots")
    if force and not (skip or update):
        if trip_slug:
            validate_component(trip_slug)
            for profile_id in ids:
                profile_dir = Path(output) / profile_id
                if profile_dir.is_symlink() or (profile_dir / trip_slug).is_symlink() or (
                    profile_dir / (trip_slug + ".gpx")
                ).is_symlink():
                    raise ValueError(f"Refusing symbolic-link archive path for profile: {profile_id}")
                if (profile_dir / "profile.json").exists() and not (profile_dir / "api-user.json").is_file():
                    raise ValueError(f"Archive profile already belongs to another scraper: {profile_dir}")
                trip_dir = profile_dir / trip_slug
                if (trip_dir / "trip.json").exists() and not (trip_dir / "api-trip.json").is_file():
                    raise ValueError(f"Archive trip already belongs to another scraper: {trip_dir}")
        clear_folders(output, profiles, trip_slug)
    collected = []
    for profile_id, username, password in profiles:
        credentials = (username, password) if password else None
        collected.append(scrape(profile_id, output, trip_slug, skip, credentials, settings, update=update))
    if len(collected) > 1:
        build_merged_xml(collected).write(
            Path(output) / "profiles.xml", encoding="utf-8", xml_declaration=True
        )
    return collected
