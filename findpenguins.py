"""! @file findpenguins.py
@brief Scrape FindPenguins profiles into an archive of XML, GPX, media and manifests.
"""

from urllib.parse import urljoin, urlparse

import os
import re
import shutil
import xml.etree.ElementTree as ET
import requests

from findpenguins_config import BASE_URL
from findpenguins_utils import login, create_browser_page, load_page, download_image, SnapshotError
from findpenguins_parsers import parse_profile, parse_trips, parse_trip, parse_trip_insights, parse_trip_image
from common_writers import (
    build_trip_gpx,
    save_trip_route_map,
    build_user_xml,
    build_merged_xml,
)
from common_archive import write_profile, write_trip
from common_profiles import DEFAULT_SETTINGS, load_profiles as load_service_profiles
from common_utils import country_flag, download_country_flags
from output_safety import clear_folders

# ##############################################################################################
# process_profile
# ##############################################################################################

def resolve_trip_flags(trip, footprints, country_codes):
    """Resolve trip and footprint flags against the shared FlagCDN cache."""
    for entry in [*(trip.get("countries") or []), *footprints]:
        flag_url = str(entry.get("flag") or "").strip()
        match = re.search(r"/img/flags-png/([a-z]{2}(?:-[a-z0-9]+)*)\.png$",
                          urlparse(flag_url).path, re.IGNORECASE)
        code = match.group(1) if match else None
        entry["flag"] = country_flag(entry.get("name") or entry.get("country"), country_codes, code)


def process_profile(
    profile_id,
    username,
    password,
    settings,
):
    """! @brief Run end-to-end scraping workflow for one profile.
    @param profile_id Profile ID to scrape.
    @param username Username for authentication.
    @param password Password for authentication.
    @param settings Run settings (see DEFAULT_SETTINGS).
    @return Tuple containing profile data and its scraped trips.
    @exception RuntimeError Raised when requested single trip slug is not found.
    """

    output = settings["output"]
    skip = settings.get("skip", False)
    trip_slug = settings["trip"]
    map_background = settings["map_background"]
    show_footprint_bubbles = settings["footprint_bubbles"]
    country_codes = download_country_flags(output, skip=skip)

    if skip:
        session = page = playwright = browser = None
    else:
        session = login(username, password)
        playwright, browser, page = create_browser_page(session)

    output_dir = os.path.join(output, profile_id)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Parse profile
        print(f"Parsing profile [{profile_id}] ...")

        soup = load_page(page, urljoin(BASE_URL, profile_id), output_dir, skip=skip)

        user_data = parse_profile(soup)
        user_data["uid"] = profile_id
        user_data["email"] = username or ""
        profile_picture_url = str(user_data.get("picture", "")).strip()
        if profile_picture_url:
            try:
                local_picture = download_image(profile_picture_url, output_dir, prefix=f"{profile_id}_profile")
                user_data["picture"] = os.path.relpath(local_picture, output_dir)
            except SnapshotError:
                raise
            except Exception as e:
                print(f"  WARNING: profile picture download failed: {e}")

        trips = parse_trips(soup, profile_id)
        write_profile(output_dir, user_data, settings)

        if trip_slug:
            trips = [trip for trip in trips if trip["slug"] == trip_slug]
            if not trips:
                raise RuntimeError(f'Trip not found: {trip_slug}')

        # Process each trip
        print(f"Fetching {len(trips)} trip(s) ...")
        for idx, trip in enumerate(trips):
            print(f"Trip #{idx+1}: {trip['title']}")
            try:
                trip_dir = os.path.join(output_dir, trip['slug'])
                os.makedirs(trip_dir, exist_ok=True)

                soup = load_page(page, trip["url"], trip_dir, skip=skip, title=trip["title"])

                image_url = parse_trip_image(soup)
                if image_url:
                    try:
                        local_image = download_image(image_url, trip_dir, filename="cover_trip", refresh=not skip)
                        trip["image"] = os.path.relpath(local_image, output_dir)
                    except Exception as e:
                        print(f"  WARNING: trip image download failed: {e}")

                photos_dir = trip_dir
                footprints = parse_trip(page, session, soup, trip_dir, photos_dir, skip=skip)
                trip["footprints"] = footprints
                insights, insights_companions = parse_trip_insights(
                    page, trip["url"], trip_dir, skip=skip
                )
                trip.update(insights)
                resolve_trip_flags(trip, footprints, country_codes)
                if insights_companions:
                    for companion in insights_companions:
                        try:
                            # A companion is represented by its profile picture, shared by all trips.
                            local_avatar = download_image(
                                companion["avatar"],
                                os.path.join(output, companion["uid"]),
                                prefix=f"{companion['uid']}_profile",
                            )
                            companion["picture"] = os.path.relpath(local_avatar, output_dir)
                        except SnapshotError:
                            raise
                        except Exception as e:
                            print(f"  WARNING: companion picture download failed: {e}")
                    trip["companions"] = insights_companions
                trip_gpx = os.path.join(output_dir, trip["slug"] + ".gpx")
                trip["gpx"] = os.path.relpath(trip_gpx, output_dir)

                # Preserve route track points by seeding target GPX from downloaded trip GPX.
                downloaded_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if not skip and os.path.exists(downloaded_trip_gpx):
                    shutil.copyfile(downloaded_trip_gpx, trip_gpx)
                elif skip and not os.path.isfile(trip_gpx):
                    print(f"  WARNING: no saved trip GPX at {trip_gpx}; route track cannot be reused")

                build_trip_gpx(trip_gpx, user_data, trip, footprints)
                for key, filename, background, bubbles in (
                    ("route_map", "map_trip.png", map_background, show_footprint_bubbles),
                    ("satellite_map", "satellite_trip.png", "satellite", True),
                ):
                    try:
                        route_map = save_trip_route_map(
                            trip_gpx,
                            footprints,
                            os.path.join(trip_dir, filename),
                            background=background,
                            show_footprint_bubbles=bubbles,
                            footprint_bubble_size=settings.get("footprint_bubble_size", DEFAULT_SETTINGS["footprint_bubble_size"]),
                        )
                        if route_map:
                            trip[key] = os.path.relpath(route_map, output_dir)
                    except (OSError, ET.ParseError, ValueError, requests.RequestException) as exc:
                        print(f"  - WARNING: unable to create {filename} for {trip['title']}: {exc}")

                old_trip_gpx = os.path.join(trip_dir, trip["slug"] + ".gpx")
                if not skip and old_trip_gpx != trip_gpx and os.path.exists(old_trip_gpx):
                    os.remove(old_trip_gpx)

                write_trip(output, trip_dir, trip)
            except SnapshotError:
                raise
            except Exception as e:
                print(f"  ERROR: {e}")
                trip["footprints"] = []
                trip["gpx"] = os.path.relpath(os.path.join(output_dir, trip["slug"] + ".gpx"), output_dir)

            # Build and save user XML
            xml_tree = build_user_xml(user_data, trips)
            output_xml = os.path.join(output_dir, profile_id + ".xml")
            xml_tree.write(output_xml, encoding="utf-8", xml_declaration=True)

            print(f"✅ Complete! XML: {output_xml}")
        print(f"✅ User: {user_data['name']}")
        print(f"✅ Trips: {len(trips)}")

        # ET.indent(xml_tree.getroot(), space="  ", level=0)
        # print( ET.tostring(xml_tree.getroot(), encoding="unicode", method="xml" ))
        return user_data, trips
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()


# ##############################################################################################
# scrapper
# ##############################################################################################

def load_profiles(profiles_file):
    """! @brief Read the profiles file.
    @param profiles_file JSON file mapping names to {id, username, password}, plus optional "settings".
    @return Tuple (list of (id, username, password), settings from the "settings" entry over DEFAULT_SETTINGS).
    @exception ValueError Raised when the file has no usable profile.
    """
    profiles, settings = load_service_profiles(profiles_file, "findpenguins")
    return profiles, {**DEFAULT_SETTINGS, **settings}


def scrapper(profiles_file, output, trip=None, force=False, skip=False, update=False):
    """Scrape profiles into the archive without generating Pelican articles."""
    if skip and update:
        raise ValueError("--skip and --update cannot be used together")
    profiles, settings = load_profiles(profiles_file)
    if update:
        print("  WARNING: FindPenguins has no reliable update timestamp; scraping all selected trips")
    if force and (skip or update):
        print(f"  --{'skip' if skip else 'update'} disables --force to preserve saved snapshots")
    if force and not (skip or update):
        clear_folders(output, profiles, trip)
    settings.update(output=output, trip=trip, skip=skip)

    # Process each profile, collecting results for merged XML
    collected = []
    for idx, (profile_id, username, password) in enumerate(profiles):
        print(f"\n{'='*60}")
        print(f"Processing profile {idx + 1}/{len(profiles)}: {profile_id}")
        print(f"{'='*60}\n")

        try:
            collected.append(process_profile(profile_id, username, password, settings))
        except SnapshotError:
            raise
        except Exception as e:
            print(f"\n❌ ERROR processing profile {profile_id}: {e}\n")

    # Write merged XML when multiple profiles were processed
    if len(collected) > 1:
        print(f"\n{'='*60}")
        print("Building merged XML for all profiles...")
        print(f"{'='*60}\n")
        merged_tree = build_merged_xml(collected)
        merged_xml = os.path.join(output, "profiles.xml")
        os.makedirs(output, exist_ok=True)
        merged_tree.write(merged_xml, encoding="utf-8", xml_declaration=True)
        print(f"✅ Merged XML: {merged_xml}")

    return collected
