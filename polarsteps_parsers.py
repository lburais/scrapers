"""Normalize Polarsteps API data into the shared archive schema."""

import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from common_config import GPX_NS, XSI_NS
from common_utils import country_flag, gpx_tag
from common_writers import distance_meters
from output_safety import validate_component
from polarsteps_config import SITE_URL, WEATHER_ICONS
from polarsteps_utils import _require_list, download_media


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
    """Write a Polarsteps GPX from mode-tagged route segments or tracker points.

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
    tracks = []
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
        if not coords:
            continue

        track = ET.SubElement(root, gpx_tag("trk"))
        mode = route_segment.get("transport_mode")
        if isinstance(mode, str) and mode and mode != "none":
            extensions = ET.SubElement(track, gpx_tag("extensions"))
            ET.SubElement(extensions, gpx_tag("transport_mode")).text = mode
        segment = ET.SubElement(track, gpx_tag("trkseg"))
        for lat, lon in coords:
            ET.SubElement(segment, gpx_tag("trkpt"), lat=str(lat), lon=str(lon))
        tracks.append(track)

    if not tracks:
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
            print("  WARNING: API returned no usable GPS track; GPX contains waypoints only")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def transport_distances_from_gpx(path, transports):
    """Fill transport distances from the lengths of GPX tracks carrying each mode."""
    root = ET.parse(path).getroot()
    distances = {}
    for track in root.findall(gpx_tag("trk")):
        extensions = track.find(gpx_tag("extensions"))
        mode = extensions.findtext(gpx_tag("transport_mode")) if extensions is not None else None
        if not mode:
            continue

        total = distances.setdefault(mode, 0.0)
        for segment in track.findall(gpx_tag("trkseg")):
            previous = None
            for point in segment.findall(gpx_tag("trkpt")):
                try:
                    lat, lon = float(point.get("lat")), float(point.get("lon"))
                except (TypeError, ValueError):
                    previous = None
                    continue
                if (not isfinite(lat) or not isfinite(lon)
                        or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                    previous = None
                    continue
                current = (lat, lon)
                if previous is not None:
                    total += distance_meters(*previous, *current)
                previous = current
        distances[mode] = total

    for transport in transports:
        mode = transport.get("name")
        if mode in distances:
            transport["distance"] = _round_integer(distances[mode] / 1000)
    return transports


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


def _round_integer(value):
    return int(round(float(value)))


def _trip_companions(source, profile_dir, skip):
    """Return the trip owner followed by the trip's buddies."""
    buddies = source.get("trip_buddies") or []
    if not isinstance(buddies, list):
        raise ValueError("Invalid Polarsteps trip_buddies")

    people = []
    owner = source.get("user")
    if owner is not None:
        if not isinstance(owner, dict):
            raise ValueError("Invalid Polarsteps trip user")
        people.append(owner)
    for entry in buddies:
        if not isinstance(entry, dict) or not isinstance(entry.get("buddy"), dict):
            raise ValueError("Invalid Polarsteps trip buddy")
        people.append(entry["buddy"])

    companions = []
    seen = set()
    for person in people:
        uid = str(person.get("username") or person.get("id") or "").strip()
        if not uid:
            raise ValueError("Polarsteps trip companion has no username or ID")
        identity = str(person.get("id") or uid)
        if identity in seen:
            continue
        seen.add(identity)
        validate_component(uid)
        name = " ".join(filter(None, (person.get("first_name"), person.get("last_name")))) or uid
        companion = {"uid": uid, "name": name}
        picture = person.get("profile_image_path") or person.get("profile_image_thumb_path")
        if picture:
            avatar = download_media(
                {
                    "path": person.get("profile_image_path"),
                    "large_thumbnail_path": person.get("profile_image_thumb_path"),
                },
                profile_dir, f"companion-{uid}", "photo", skip,
            )
            companion["picture"] = os.path.relpath(avatar, profile_dir)
        companions.append(companion)
    return companions


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
        "distance": _round_integer(source["total_km"]) if source.get("total_km") is not None else "",
        "countries": [], "transports": [], "companions": [], "footprints": [],
        "gpx": slug + ".gpx",
    }
    trip["companions"] = _trip_companions(source, profile_dir, skip)
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
            "temperature": _round_integer(step["weather_temperature"])
            if step.get("weather_temperature") is not None else "",
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
