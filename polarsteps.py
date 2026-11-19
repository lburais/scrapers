"""Archive a Polarsteps account using its browser session and REST API."""

import json
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from common_config import GPX_NS, XSI_NS
from common_profiles import DEFAULT_SETTINGS, load_profiles
from common_utils import country_flag, download_country_flags, gpx_tag
from common_archive import _write_json, write_profile, write_trip
from common_writers import build_merged_xml, build_trip_gpx, build_user_xml, save_trip_route_map
from output_safety import clear_folders, validate_component

API_URL = "https://api.polarsteps.com"
SITE_URL = "https://www.polarsteps.com"
API_VERSION = "62"
WEATHER_ICONS = {
    "clear-day": "☀️",
    "clear-night": "🌙",
    "partly-cloudy-day": "⛅",
    "partly-cloudy-night": "🌙☁️",
    "cloudy": "☁️",
    "rain": "🌧",
    "sleet": "🌨️",
    "snow": "❄️",
    "wind": "🌬",
    "fog": "🌫️",
}


def _restrict_login_requests(route):
    """Allow automated login requests only to HTTPS Polarsteps hosts."""
    url = urlsplit(route.request.url)
    host = url.hostname or ""
    if url.scheme == "https" and (host == "polarsteps.com" or host.endswith(".polarsteps.com")):
        route.continue_()
    else:
        route.abort()


def _remember_token(context):
    """Return the browser's nonempty remember token, or None if absent."""
    cookies = context.cookies([SITE_URL, API_URL])
    return next((cookie["value"] for cookie in cookies
                 if cookie["name"] == "remember_token" and cookie["value"]), None)


def login(username=None, password=None):
    """Sign in headlessly with both credentials or interactively without them.

    Return the remember token for API calls; raise RuntimeError if login fails
    or no token is obtained. The browser is closed before returning.
    """
    if (username is None) != (password is None):
        raise ValueError("Both Polarsteps login username and password are required")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=username is not None)
        try:
            context = browser.new_context()
            if username is not None:
                context.route("**/*", _restrict_login_requests)
            page = context.new_page()
            if username is None:
                page.goto(SITE_URL, wait_until="domcontentloaded")
                input("Sign in to Polarsteps in the browser, then press Enter here: ")
                token = _remember_token(context)
            else:
                try:
                    page.goto(SITE_URL + "/login", wait_until="domcontentloaded")
                    form = page.locator("form:has(input[name=password])")
                    form.locator("input[name=username]").fill(username)
                    form.locator("input[name=password]").fill(password)
                    remember = form.locator("input[type=checkbox]")
                    if not remember.is_checked():
                        form.locator("label:has(input[type=checkbox])").click()
                    if not remember.is_checked():
                        raise RuntimeError("Unable to enable Polarsteps 'Remember me'")
                    form.locator("button[type=submit]").click()
                    token = None
                    for _ in range(120):
                        token = _remember_token(context)
                        if token:
                            break
                        page.wait_for_timeout(250)
                except PlaywrightError:
                    raise RuntimeError(
                        "Polarsteps login failed; the login page may have changed or need manual verification"
                    ) from None
            if not token:
                raise RuntimeError("No Polarsteps remember_token cookie found; sign in and try again")
            return token
        finally:
            browser.close()


def load_profile(path):
    """Read credentials from a legacy single-account JSON file.

    This helper is not used by the CLI, which requires a shared profiles file.
    """
    with open(path, encoding="utf-8") as handle:
        profile = json.load(handle)
    if not isinstance(profile, dict):
        raise ValueError("Polarsteps profile must be a JSON object")
    username, password = profile.get("username"), profile.get("password")
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
        raise ValueError("Polarsteps profile must contain non-empty username and password strings")
    return username.strip(), password


def api_get(session, endpoint):
    """Fetch an API v62 endpoint and return its JSON object, raising on errors."""
    response = session.get(
        API_URL + endpoint,
        params={"polarsteps_api_version": API_VERSION},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected Polarsteps response for {endpoint}: expected an object")
    return data


def source_data(path, skip, fetch):
    """Read a saved API object in skip mode, otherwise fetch and atomically save it."""
    if skip:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid API snapshot: {path}")
        return data
    data = fetch()
    _write_json(str(path), data)
    return data


def slug_for_trip(trip):
    """Build a filesystem-safe slug prefixed by the trip's numeric ID."""
    trip_id = str(trip.get("id", ""))
    if not re.fullmatch(r"[0-9]+", trip_id):
        raise ValueError(f"Invalid Polarsteps trip ID: {trip_id!r}")
    value = str(trip.get("display_slug") or trip.get("slug") or trip.get("name") or "")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    name = re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "trip"
    slug = f"{trip_id}-{name}"
    validate_component(slug)
    return slug


def local_date(value, timezone_id=None):
    """Return an ISO date from a timestamp or ISO datetime, using its local timezone."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"Invalid Polarsteps date: {value!r}")
    if timezone_id and moment.tzinfo:
        moment = moment.astimezone(ZoneInfo(timezone_id))
    return moment.date().isoformat()


def description_text(value):
    """Return plain text and HTTP(S) link references extracted from HTML, if present."""
    text = value or ""
    if not re.search(r"</?[A-Za-z][^>]*>", text):
        return text, []
    document = BeautifulSoup(text, "html.parser")
    references = []
    for link in document.find_all("a", href=True):
        label = link.get_text(" ", strip=True)
        url = link["href"]
        if label and urlsplit(url).scheme in ("http", "https"):
            references.append((label, url))
    for tag in document.find_all("br"):
        tag.replace_with("\n")
    for tag in document.find_all(["p", "div"]):
        tag.append("\n\n")
    return document.get_text().strip(), references


def media_url(value):
    """Resolve a media path against the Polarsteps CDN and require HTTPS."""
    if not isinstance(value, str) or not value:
        return ""
    url = urljoin("https://media.prod.polarsteps.com/", value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Polarsteps media URL must be an absolute HTTPS URL")
    return url


def download_media(item, directory, stem, kind, skip):
    """Reuse or download a photo/video, warning when a photo uses a thumbnail.

    Photos are written as lossless WebP. Skip mode requires an existing file;
    unavailable videos and failed downloads raise rather than being omitted.
    """
    directory = Path(directory)
    original = item.get("path") or item.get("cdn_path")
    suffix = Path(urlsplit(original or "").path).suffix.lower()
    if kind == "photo":
        suffix = ".webp"
    elif not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    destination = directory / (stem + suffix)
    if destination.is_symlink():
        raise ValueError(f"Refusing symbolic-link media file: {destination}")
    if destination.is_file():
        return str(destination)
    if skip:
        raise FileNotFoundError(f"Missing archived media: {destination}")
    directory.mkdir(parents=True, exist_ok=True)
    candidates = []
    if not item.get("full_res_unavailable"):
        for value in (item.get("path"), item.get("cdn_path")):
            if value and all(value != candidate for candidate, _ in candidates):
                candidates.append((value, False))
    if kind == "photo":
        thumbnail = item.get("large_thumbnail_path") or item.get("small_thumbnail_path")
        if thumbnail and thumbnail != original:
            candidates.append((thumbnail, True))
    if not candidates:
        raise ValueError(f"No downloadable {kind} for {stem}")
    failure = None
    for candidate, thumbnail in candidates:
        url = media_url(candidate)
        temporary = None
        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".media-", delete=False) as handle:
                    temporary = Path(handle.name)
                    for chunk in response.iter_content(256 * 1024):
                        if chunk:
                            handle.write(chunk)
            if kind == "photo":
                with Image.open(temporary) as image:
                    image.save(destination, "WEBP", lossless=True, quality=100, method=4)
            else:
                os.replace(temporary, destination)
                temporary = None
            if thumbnail:
                print(f"  WARNING: original unavailable for {stem}; archived a thumbnail instead")
            return str(destination)
        except requests.RequestException as exc:
            failure = exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to download {kind} {stem}") from failure


def _coordinates(location):
    """Return valid numeric latitude/longitude coordinates, or None."""
    if not isinstance(location, dict):
        return None
    lat, lon = location.get("lat"), location.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _track_points(source):
    """Yield valid tracker coordinates and timestamps from Zelda steps."""
    for point in source.get("zelda_steps") or []:
        coords = _coordinates(point.get("location"))
        if coords:
            yield coords, point.get("time")


def _decode_route(route):
    """Decode a Google-format polyline into latitude/longitude pairs."""
    index = lat = lon = 0
    while index < len(route):
        changes = []
        for _ in range(2):
            value = shift = 0
            while True:
                if index >= len(route) or shift > 30:
                    raise ValueError("Invalid encoded Polarsteps route")
                code = ord(route[index]) - 63
                index += 1
                if not 0 <= code <= 63:
                    raise ValueError("Invalid encoded Polarsteps route")
                value |= (code & 31) << shift
                shift += 5
                if code < 32:
                    break
            changes.append(~(value >> 1) if value & 1 else value >> 1)
        lat += changes[0]
        lon += changes[1]
        coords = _coordinates({"lat": lat / 100000, "lon": lon / 100000})
        if coords is None:
            raise ValueError("Invalid coordinates in Polarsteps route")
        yield coords


def seed_gpx(path, source):
    """Write a Polarsteps GPX from tracker points or encoded route segments.

    Invalid or unavailable segments are skipped with a warning. Without a usable
    track, the GPX is created without track points for later waypoint generation.
    """
    root = ET.Element(gpx_tag("gpx"), {
        "version": "1.1", "creator": "Polarsteps",
        f"{{{XSI_NS}}}schemaLocation": f"{GPX_NS} {GPX_NS}/gpx.xsd",
    })
    metadata = ET.SubElement(root, gpx_tag("metadata"))
    title = source.get("name") or source.get("display_name")
    if title:
        ET.SubElement(metadata, gpx_tag("name")).text = title
    points = list(_track_points(source))
    if points:
        track = ET.SubElement(root, gpx_tag("trk"))
        segment = ET.SubElement(track, gpx_tag("trkseg"))
        for (lat, lon), timestamp in points:
            point = ET.SubElement(segment, gpx_tag("trkpt"), lat=str(lat), lon=str(lon))
            if timestamp is not None:
                if isinstance(timestamp, (int, float)):
                    time = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                else:
                    time = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).isoformat()
                ET.SubElement(point, gpx_tag("time")).text = time
    else:
        track = ET.SubElement(root, gpx_tag("trk"))
        for route_segment in source.get("route_segments") or []:
            if route_segment.get("type") == "future_directions":
                continue
            route = route_segment.get("route")
            if not route:
                continue
            if route.startswith("off_"):
                print("  WARNING: skipping an unavailable Polarsteps route segment")
                continue
            try:
                coords = list(_decode_route(route))
            except ValueError as exc:
                print(f"  WARNING: skipping invalid route segment: {exc}")
                continue
            if coords:
                segment = ET.SubElement(track, gpx_tag("trkseg"))
                for lat, lon in coords:
                    ET.SubElement(segment, gpx_tag("trkpt"), lat=str(lat), lon=str(lon))
        if not list(track):
            root.remove(track)
            print("  WARNING: API returned no usable GPS track; GPX contains waypoints only")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _require_list(data, *names):
    """Return the first present named list, or raise if it is missing or invalid."""
    for name in names:
        value = data.get(name)
        if value is not None:
            if not isinstance(value, list):
                raise ValueError(f"Invalid Polarsteps {name}: expected a list")
            return value
    raise ValueError(f"Polarsteps response is missing {' or '.join(names)}")


def weather_icon(condition):
    """Convert known Polarsteps weather codes to icons, preserving unknown values."""
    if condition is None or condition == "":
        return ""
    if isinstance(condition, str) and condition in WEATHER_ICONS:
        return WEATHER_ICONS[condition]
    print(f"  WARNING: unknown Polarsteps weather condition: {condition!r}")
    return condition


def _stringify_trip_numbers(value):
    """Convert numeric trip data to strings without changing booleans or container shape."""
    if isinstance(value, dict):
        return {key: _stringify_trip_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_trip_numbers(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_stringify_trip_numbers(item) for item in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value


def normalize_trip(source, username, slug, profile_dir, skip, country_codes=None):
    """Map API trip and type-1 step data into the shared archive schema, downloading media.

    Skip mode requires the media to have been archived already.
    """
    trip_dir = profile_dir / slug
    trip_dir.mkdir(parents=True, exist_ok=True)
    url = f"{SITE_URL}/{quote(username, safe='')}/{quote(slug, safe='-')}"
    start = local_date(source.get("start_date"), source.get("timezone_id"))
    end = local_date(source.get("end_date"), source.get("timezone_id"))
    trip = {
        "slug": slug, "title": source.get("name") or source.get("display_name") or slug,
        "description": source.get("summary") or "", "url": url,
        "period": " - ".join(date for date in (start, end) if date),
        "distance": source.get("total_km") if source.get("total_km") is not None else "",
        "countries": [], "transports": [], "companions": [], "footprints": [],
        "gpx": slug + ".gpx",
    }
    if start and end:
        trip["days"] = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
    cover = source.get("cover_photo") or {}
    if not isinstance(cover, dict):
        raise ValueError("Invalid Polarsteps cover_photo")
    if not cover and source.get("cover_photo_path"):
        cover = {"path": source["cover_photo_path"], "large_thumbnail_path": source.get("cover_photo_thumb_path")}
    if cover:
        trip["image"] = os.path.relpath(download_media(cover, trip_dir, "cover_trip", "photo", skip), profile_dir)
    countries = set()
    for step in _require_list(source, "all_steps", "steps"):
        if step.get("is_deleted") or step.get("type") != 1:
            continue
        location = step.get("location") or {}
        coords = _coordinates(location)
        day = local_date(step.get("start_time"), step.get("timezone_id") or source.get("timezone_id"))
        end_day = local_date(step.get("end_time"), step.get("timezone_id") or source.get("timezone_id"))
        country = location.get("country") or ""
        flag = country_flag(country, country_codes, location.get("country_code"))
        if country and country not in countries:
            countries.add(country)
            trip["countries"].append({"name": country, "flag": flag})
        step_id = str(step["id"])
        validate_component(step_id)
        text, references = description_text(step.get("description"))
        footprint = {
            "title": step.get("name") or step.get("display_name") or location.get("name") or f"Step {step_id}",
            "text": text, "date": day,
            "lat": coords[0] if coords else "", "lon": coords[1] if coords else "",
            "city": location.get("locality") or "", "country": country, "flag": flag,
            "weather": weather_icon(step.get("weather_condition")),
            "temperature": step.get("weather_temperature") if step.get("weather_temperature") is not None else "",
            "overnights": max(0, (datetime.fromisoformat(end_day) - datetime.fromisoformat(day)).days) if day and end_day else "",
            "photos": [], "videos": [], "gpx": [], "pdf": [], "references": references,
        }
        step_slug = step.get("display_slug") or step.get("slug")
        if step_slug:
            footprint["url"] = url + "/" + quote(step_id + "-" + str(step_slug), safe="-")
        if start and day:
            footprint["day"] = (datetime.fromisoformat(day) - datetime.fromisoformat(start)).days + 1
        for media in sorted(step.get("media") or [], key=lambda item: item.get("order") or 0):
            if media.get("is_deleted"):
                continue
            media_id = str(media.get("id") or media.get("uuid") or "")
            validate_component(media_id)
            media_type = media.get("type")
            if media_type not in (0, 1):
                raise ValueError(f"Unknown Polarsteps media type {media_type!r} in step {step_id}")
            kind = "photo" if media_type == 0 else "video"
            path = download_media(media, trip_dir, f"step-{step_id}-{media_id}", kind, skip)
            footprint["photos" if kind == "photo" else "videos"].append(path)
        trip["footprints"].append(footprint)
    modes = []
    for segment in source.get("route_segments") or []:
        mode = segment.get("transport_mode")
        if mode and mode != "none" and mode not in modes:
            modes.append(mode)
    trip["transports"] = [{"name": mode, "distance": ""} for mode in modes]
    return trip


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
            build_trip_gpx(str(gpx), user, trip, trip["footprints"], enrich_elevation=True)
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
