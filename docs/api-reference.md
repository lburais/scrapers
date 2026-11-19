# scrapers API reference

Functions and classes are grouped by module. Functions prefixed with `_` are
module-private helpers. Docstrings in the source provide further details.

## `scrapers.py` — CLI

| Function | Purpose |
|---|---|
| `main()` | Parse the command and its arguments, then dispatch to the selected program. |

## `findpenguins.py` — scraper

| Function | Purpose |
|---|---|
| `resolve_trip_flags(trip, footprints, country_codes)` | Resolve FindPenguins flags from the shared FlagCDN cache and store archive-relative paths. |
| `process_profile(profile_id, username, password, settings)` | End-to-end scrape of one profile: login, trips, footprints, GPX, maps, XML and manifests. |
| `load_profiles(profiles_file)` | Read the profiles JSON file and split profiles from the optional `settings` entry. |
| `scrapper(profiles_file, output, trip=None, force=False, skip=False)` | Scrape all profiles into the archive without generating Pelican articles. |

## `polarsteps.py` — Polarsteps scraper

| Function | Purpose |
|---|---|
| `login(username=None, password=None)` | Sign in automatically with credentials or interactively, returning an in-memory session cookie. |
| `_restrict_login_requests(route)` / `_remember_token(context)` | Restrict automated login to Polarsteps hosts and read the browser cookie. |
| `load_profile(path)` | Read and validate a legacy private JSON login profile; the CLI uses the shared profiles file instead. |
| `api_get(session, endpoint)` | Fetch one Polarsteps API v62 object. |
| `source_data(path, skip, fetch)` | Save an API response or load an existing snapshot. |
| `slug_for_trip(trip)` / `local_date(value, timezone_id=None)` | Prefix normalized trip slugs with their numeric ID and normalize local calendar dates. |
| `description_text(value)` | Convert HTML descriptions and links to text and references. |
| `media_url(value)` / `download_media(item, directory, stem, kind, skip)` | Resolve and archive media, with explicit thumbnail fallback for photos. |
| `_coordinates(location)` / `_track_points(source)` / `_decode_route(route)` | Read tracker locations or decode route polylines. |
| `seed_gpx(path, source)` | Create the trip GPX track before adding waypoints. |
| `_require_list(data, *names)` | Validate a required API list. |
| `weather_icon(condition)` | Convert known weather codes to icons; warn and preserve unknown values. |
| `normalize_trip(source, username, slug, profile_dir, skip, country_codes=None)` | Map a trip and its steps to the shared archive schema. |
| `scrape(username, output="output", trip_slug=None, skip=False, credentials=None, sizes=None)` | Archive a profile via the API or saved snapshots. |
| `scrape_profiles(profiles_file, output="output", trip_slug=None, skip=False, force=False)` | Archive Polarsteps accounts from a shared profiles file; force clears the archive or selected trips unless skip is enabled. |

## `common_profiles.py` — shared profile loading

| Function | Purpose |
|---|---|
| `load_profiles(path, service)` | Load accounts from service sections or legacy profiles, and shared settings. |

`DEFAULT_SETTINGS` supplies the common defaults, including image sizes.

## `aventures2rst.py` — archive to Pelican

| Function | Purpose |
|---|---|
| `convert(output, content, trip_slug=None)` | Rebuild trip and footprint RST articles from `profile.json` / `trip.json` manifests. |

## `reminder.py` / `reminders2rst.py` — Apple Reminders

| Function | Purpose |
|---|---|
| `reminder.export_reminders(output, list_name, all_reminders=False, force=False)` | Prepare the output directory and print the `rem export` command (direct invocation currently disabled). |
| `reminders2rst._metadata(value)` | Collapse whitespace so a value fits on one RST metadata line. |
| `reminders2rst.convert(output, content)` | Write one stable-named RST article per reminder from `reminders.json`. |

## `output_safety.py` — destructive-operation guards

| Function | Purpose |
|---|---|
| `validate_clear_directory(directory)` | Reject symlinks, filesystem root, cwd, the project directory and the home directory. |
| `validate_component(value)` | Reject empty values, `.`/`..` and anything containing path separators. |
| `clear_folders(output, profiles, trip=None)` | Clear the archive, or only the selected trip of each profile (`--force`). |

## `common_archive.py` — portable JSON manifest writing

| Function | Purpose |
|---|---|
| `_write_json(path, value)` | Atomic JSON write (temporary file then rename). |
| `write_profile(profile_dir, user, settings)` | Write `profile.json` (user and image sizes). |
| `write_trip(output, trip_dir, trip)` | Write `trip.json` with media paths relative to the archive; rejects media outside it. |

## `aventures_archive.py` — portable JSON manifest reading

| Function | Purpose |
|---|---|
| `read_json(path)` | Load a manifest and check it is a version 1 object. |
| `read_trip(output, path)` | Load `trip.json` and resolve media paths against the (possibly moved) archive root. |

## `findpenguins_config.py` and `common_config.py` — constants

`findpenguins_config.py`: `BASE_URL`, `LOGIN_PAGE`, `LOGIN_POST`, `HEADERS`.
`common_config.py`: `GPX_NS`, `XSI_NS`. No functions.

## `common_elevation.py` — elevations

| Function | Purpose |
|---|---|
| `fetch_elevations(points, source="opentopodata")` | Fill `ele` for points (batches of 100, exponential backoff on HTTP 429). |
| `smooth(points)` | Savitzky-Golay smoothing of `ele` in place (skipped under 11 points). |
| `gain_loss(points)` | Cumulative `(gain, loss)` along a track. |

The former `findpenguins_archive`, `findpenguins_writers`, and `findpenguins_elevation`
modules re-export their shared implementations for compatibility.

## `findpenguins_parsers.py` — page parsing

| Function | Purpose |
|---|---|
| `extract_expandable_text(node)` | Extract normalized text of expandable blocks. |
| `apply_gpx_coordinates(footprints, gpx_path)` | Overwrite footprint coordinates with the matching GPX waypoints. |
| `apply_day_numbers(footprints)` | Set each footprint's `day` relative to the first footprint date. |
| `click_footprint_menu(page)` | Read weather/location metadata from the footprint popup menu. |
| `parse_profile(soup)` | Parse the user profile page. |
| `parse_trips(soup, tripid)` | Parse trip cards from a profile page. |
| `parse_footprints(soup)` | Parse footprint ids and URLs from a trip page. |
| `parse_trip_insights(page, trip_url, trip_dir, skip=False)` | Parse the Insights subpage (description, countries, distance, transports). |
| `parse_trip_image(soup)` | Extract the trip cover image URL. |
| `parse_trip(page, session, soup, trip_dir, photos_dir, skip=False)` | Parse a trip in depth and collect enriched footprints and media. |

## `common_utils.py` — shared helpers

| Function | Purpose |
|---|---|
| `gpx_tag(name)` | Namespaced GPX tag name. |
| `download_country_flags(output, skip=False)` | Cache FlagCDN's name-to-code lists and 64×48 WebP flags, or use cached files in skip mode. |
| `country_flag(name, country_codes, code=None)` | Resolve a country code or an unambiguous name to an archive-relative flag path. |
| `add_text_element(parent, name, value, namespace=GPX_NS)` | Append a text child only when the value is non-empty. |
| `format_tree(tree)` | Indent an ElementTree with two spaces. |
| `clean_text(t)` | Normalize whitespace. |
| `strip_leading_flag(text)` | Remove a leading flag emoji. |
| `extract_private_references(text)` | Extract URL references from private notes. |
| `to_webp(path)` | Convert an image to lossless WebP and remove the source. |
| `variant_path(path, suffix)` | Path of a size variant (`a.webp` → `a_large.webp`). |
| `make_variant(path, suffix, max_size)` | Create a downscaled lossless WebP copy. |
| `shrink_image(path, max_size)` | Downscale a WebP in place. |

## `findpenguins_utils.py` — scraper utilities

| Function or class | Purpose |
|---|---|
| `normalize_photo_url(img_url)` | Promote thumbnail URLs to large images. |
| `download_image(img_url, dest_folder, prefix="img", filename=None, refresh=False)` | Download an image. |
| `download_video(video_url, dest_folder, prefix="vid")` | Download a video (skipped if present). |
| `download_file(file_url, dest_folder, prefix="file", default_ext="")` | Download an attachment such as GPX or PDF. |
| `requests_cookies_to_playwright(session)` | Convert requests cookies to Playwright cookies. |
| `create_browser_page(session)` | Headless Chromium page seeded with the session cookies. |
| `click_load_more_until_done(page)` | Expand the footprint list until exhausted. |
| `login(username, password)` | Form-based FindPenguins login returning a session. |
| `SnapshotError` | Raised when a required saved HTML snapshot is missing or unusable. |
| `snapshot_path(page_url, outputdir, suffix="html")` | URL-hash-based snapshot path. |
| `_snapshot_slug(text)` | ASCII slug used to find legacy title-based snapshots. |
| `load_page(page, page_url, outputdir, skip=False, title="", footprint_id="")` | Load (or read from snapshot) a page and return BeautifulSoup. |
| `get_emoji_flag(code)` | Emoji flag for a country or subdivision code. |

## `common_writers.py` — XML, GPX and route maps

| Function | Purpose |
|---|---|
| `_add_companion(parent, companion)` | Append a `<companion>` XML element. |
| `_add_trip_details(parent, trip)` | Append countries, distance and transports elements. |
| `distance_meters(lat1, lon1, lat2, lon2)` | Great-circle distance in meters. |
| `find_closest_trackpoint(waypoint, track_points)` | Nearest track point to a waypoint. |
| `footprint_to_waypoint(footprint)` | Footprint to GPX `<wpt>` element. |
| `build_trip_gpx(gpx_path, user_data, trip, footprints, enrich_elevation=True)` | Build/update the trip GPX, optionally enriching track elevations. |
| `build_user_xml(user_data, trips)` | Build the per-profile XML index. |
| `build_merged_xml(profiles_data)` | Build the XML index merging several profiles. |
| `_mercator_coordinates(lon, lat)` | Project to Web Mercator meters. |
| `save_trip_route_map(gpx_path, footprints, output_image, background="transparent", show_footprint_bubbles=False)` | Render the 1200×800 route map. |

## `aventures_writers.py` — Pelican articles and country maps

| Function | Purpose |
|---|---|
| `_write_rst(path, content)` | Write an RST file, creating folders. |
| `_references_by_search(references)` | Case-insensitive lookup of reference labels. |
| `_encode_url(url)` | Percent-encode unsafe URL characters. |
| `_copy_media(media_paths, destination_dir)` | Copy media beside an article, returning relative paths. |
| `_copy_image(image_path, destination_dir, sizes, variants)` | Copy an image and create its variants. |
| `_load_country_boundaries()` | Load and cache Natural Earth boundaries. |
| `save_full_country_map(lat, lon, padding_ratio=0.1, output_image="map_country.png")` | Render the country/region map of a footprint. |
| `_footprint_gpx_fields(footprint, footprint_dir, sizes, trip_days="")` | Footprint fields used as Pelican metadata. |
| `_rst_text(value)` | Escape text for RST. |
| `_rst_metadata(**fields)` | Format Pelican metadata fields. |
| `_rst_heading(text, underline="=")` | Format an RST heading. |
| `_text_with_rst_references(text, references)` | Replace reference labels with RST links. |
| `_trip_date_range(footprints)` | ISO start/end dates of a trip. |
| `build_trip_rst(content_dir, trip_dir, user_data, trip, footprints, sizes)` | Generate trip and footprint RST articles. |
