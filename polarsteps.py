"""Orchestrate Polarsteps profile and trip archiving."""

import os
from pathlib import Path
from urllib.parse import quote

import requests

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


def scrape(username, output="output", trip_slug=None, skip=False, credentials=None, sizes=None):
    """Archive one Polarsteps profile and return its user and selected trips.

    `username` identifies the profile to archive; optional `credentials` is a
    login username/password pair. Without credentials, login is interactive.
    Skip mode reads snapshots and existing media without login; elevation
    enrichment may still access the network.
    `sizes` overrides the shared manifest size settings.
    """
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
        write_profile(str(profile_dir), user, {**DEFAULT_SETTINGS, **(sizes or {})})
        trips = []
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
            source = source_data(trip_dir / "api-trip.json", skip, lambda: api_get(session, "/trips/" + trip_id))
            if str(source.get("id")) != trip_id:
                raise ValueError(f"Polarsteps trip ID mismatch for {slug}")
            trip = normalize_trip(source, username, slug, profile_dir, skip, country_codes)
            gpx = profile_dir / (slug + ".gpx")
            if gpx.is_symlink():
                raise ValueError(f"Refusing symbolic-link GPX file: {gpx}")
            seed_gpx(gpx, source)
            trip["transports"] = transport_distances_from_gpx(gpx, trip["transports"])
            build_trip_gpx(
                str(gpx), user, trip, trip["footprints"],
                enrich_elevation=True, integer_elevation=True,
            )
            route_map = save_trip_route_map(str(gpx), trip["footprints"], str(trip_dir / "map_trip.png"))
            if route_map:
                trip["route_map"] = os.path.relpath(route_map, profile_dir)
            write_trip(str(root), str(trip_dir), _stringify_trip_numbers(trip))
            trips.append(trip)
        xml = profile_dir / (username + ".xml")
        if xml.is_symlink():
            raise ValueError(f"Refusing symbolic-link XML file: {xml}")
        build_user_xml(user, trips).write(xml, encoding="utf-8", xml_declaration=True)
        print(f"Archived {len(trips)} Polarsteps trip(s) for {username}")
        return user, trips
    finally:
        session.close()


def scrape_profiles(profiles_file, output="output", trip_slug=None, skip=False, force=False):
    """Archive the Polarsteps accounts from a shared profiles file.

    Force clears the output directory, or only each profile's selected trip and
    GPX when a slug is supplied. Skip overrides force. Return the collected
    (user, trips) pairs and write a merged XML index for multiple accounts.
    """
    profiles, settings = load_profiles(profiles_file, "polarsteps")
    ids = [profile_id for profile_id, _, _ in profiles]
    if len(set(ids)) != len(ids):
        raise ValueError("Polarsteps profiles have duplicate IDs")
    for profile_id in ids:
        validate_component(profile_id)
    if force and skip:
        print("  --skip disables --force to preserve saved snapshots")
    if force and not skip:
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
        collected.append(scrape(profile_id, output, trip_slug, skip, credentials, settings))
    if len(collected) > 1:
        build_merged_xml(collected).write(
            Path(output) / "profiles.xml", encoding="utf-8", xml_declaration=True
        )
    return collected
