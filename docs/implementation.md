# scrapers Implementation Guide

This guide documents the current CLI, scraping pipeline and output behavior.

## Entry Point and CLI

The single CLI entry point is `scrapers.py`.

`scrapers aventures profiles.json [--output DIR] [--content DIR] [--force] [--skip]`
scrapes FindPenguins and then Polarsteps, then converts each archive with its
service category. It uses `findpenguins` and `polarsteps` subdirectories under
both `--output` (default `output`) and `--content` (default
`../website/content/articles`). Both services must be present in the profile file.
`--force` and `--skip` are passed to both scrapers.

After installation, use `scrapers findpenguins profiles.json [--output DIR] [-t SLUG] [--force] [--skip]`
or `scrapers polarsteps profiles.json [--output DIR] [-t SLUG] [--force] [--skip]`, followed by
`scrapers aventures2rst --output DIR [--content DIR] [-t SLUG] [--category CATEGORY]`. The
converter defaults to category and first service tag `findpenguins`; use `--category polarsteps`
for Polarsteps archives. The equivalent Python invocation is `python -m scrapers <command> ...`.
The shared file has `findpenguins` and `polarsteps` sections mapping names to accounts with `id`,
`username`, and optional `password`. Each scraper processes its own accounts. Legacy
FindPenguins entries and per-person service entries are also accepted.
`--output` (default `output`) is the archive directory for XML, GPX and downloaded media,
the converter's `--content` (default `../website/content/articles/findpenguins`) the Pelican articles directory,
`-t`/`--trip SLUG` scrapes only the matching trip slug (default: all trips). Fetched source HTML
and footprint popup data are saved by FindPenguins. `--force` clears the entire output directory,
including any other services' data (or only the selected trip's folder and GPX for each profile
when `--trip` is given). The content directory is not cleared.

For FindPenguins, `--skip` reads previously saved profile, trip, footprint and insights HTML instead of
navigating, and overrides `--force`. Run a scrape first to save snapshots;
missing required snapshots stop the run without fetching them. Current snapshots are
named by URL, with support for older title-based HTML files. Footprint popup results
are saved separately as JSON; older snapshots without them produce a warning and
empty popup fields. The existing enriched trip GPX is reused. Skip does not prevent
network access for missing media, map imagery or elevation data.

An optional `settings` entry configures the rest:

| Setting | Behavior |
|---------|----------|
| `small_size` | Max side in px of profile/companion pictures (stored in place of the original); default `128`. |
| `large_size` | Max side in px of maps, the trip cover and `_thumb` photos; default `1600`. |
| `map_background` | Main route-map background: `transparent` (default), `satellite`, or `street`. |
| `footprint_bubbles` | Draw footprint bubbles on the main route map; default `false`. |
| `footprint_bubble_size` | Bubble diameter in original map pixels; integer 1–799, default `48`. |

Image size settings are recorded in both services' profile manifests for the converter.

## FindPenguins Scraping and Serialization Flow

1. `login(username, password)` in `findpenguins_utils.py` logs in with a `requests.Session`.
2. `create_browser_page(session)` starts Playwright Chromium and transfers the session cookies.
3. `parse_profile` and `parse_trips` load profile metadata and the selected trip list.
4. For each trip, `parse_trip` loads all footprint pages and downloads route GPX and media.
   `parse_trip_insights` extracts trip description, countries, distances, transports and current
   trip companions; `parse_trip_image` finds the trip cover image. Country and footprint flags
   are resolved from the shared FlagCDN cache using codes in FindPenguins flag URLs or country names;
   the source flag images are not downloaded.
5. `build_trip_gpx` preserves the downloaded track, rebuilds coordinate-bearing waypoints, writes
   trip and footprint extensions, and enriches track-point elevations.
6. Route maps are generated after the final GPX update when it contains a valid track.
7. The profile XML index is updated with the trip and companion data.
8. Profile and per-trip JSON manifests preserve the parsed fields and archive-relative media paths.
9. `aventures2rst.py` reads these manifests and generates RST independently. Older XML/GPX-only
   archives must be scraped again or rebuilt with saved snapshots.

Trip-level errors are logged and processing continues to later trips. Elevation and route-map
failures are reported as warnings and do not invalidate an otherwise successful GPX.

## Polarsteps Scraping and Serialization Flow

1. `scrape_profiles` loads the Polarsteps accounts and shared settings. Each account's `id`
   identifies the profile to archive; `username` and a nonempty `password` are login credentials.
2. `login` uses headless Chromium with credentials, or an interactive browser if the password is
   empty. Automated login restricts requests to HTTPS Polarsteps hosts. The `remember_token`
   cookie is kept in memory for API calls; it is not saved by the scraper.
3. API v62 responses from `/users/byusername/<id>` and `/trips/<trip-id>` are saved as
   `<output>/<id>/api-user.json` and `<output>/<id>/<slug>/api-trip.json`. Protect these snapshots
   as private data. Trip slugs start with the numeric ID, for example `42-adventure`.
4. The scraper maps the trip owner (`user`) first, followed by `trip_buddies`, as companions. It maps
   nondeleted steps with `type` equal to `1` and their available media into the shared schema; steps
   without that type are skipped. Country flags are resolved from the shared FlagCDN cache using the
   source country code or an unambiguous English name. Photos become lossless WebP; a thumbnail
   fallback is reported. Unavailable videos and missing required data raise errors.
5. GPX tracks use `zelda_steps`, or encoded route segments when tracker points are absent. Invalid
   route segments are skipped with a warning; without a track, only available waypoints are written.
   The route map is transparent and does not fetch map tiles. Track points may be sent to
   OpenTopoData for elevation enrichment.
6. The shared writers produce JSON manifests, GPX and XML; multiple accounts also get
   `profiles.xml`. The same converter consumes both services' manifests.

Polarsteps `--skip` reads saved API snapshots and existing media without login. Elevation
enrichment can still access the network. Missing required snapshots or media stop the run.
`--skip` overrides `--force`.

Both scrapers cache FlagCDN's name-to-code lists in `<output>/flags/codes.json` and all listed
64×48 WebP flags as `<code>.webp`. Duplicate names keep all codes. Ambiguous names without a
usable source code are reported and left without a flag. The cache is reused until its table is
removed; missing or invalid flag images are repaired during normal runs. `--skip` never fetches
this cache, and warns if the table or flag images are missing.

## XML and GPX

- One profile XML file is written to `<output>/<uid>/<uid>.xml`; multiple selected profiles also
  produce `<output>/profiles.xml`.
- One enriched GPX is written to `<output>/<uid>/<trip-slug>.gpx`.
- Track elements from the downloaded FindPenguins GPX or generated Polarsteps GPX are preserved.
  Existing waypoints are replaced with coordinate-bearing footprints.
- The closest track point supplies a footprint waypoint's time, its elevation when the footprint has
  none, and the custom matched-point extension (including elevation when available).
- Both scrapers attempt OpenTopoData SRTM90m elevation enrichment when track points exist;
  failures are warnings.

See [`xml-gpx-structure.md`](./xml-gpx-structure.md) for the serialized structure and
[`data-fields.md`](./data-fields.md) for field provenance.

## Pelican Article Export

Originals are kept and resized lossless WebP variants (never upscaled) are created next to them.
Companions are represented by their profile picture (`<uid>/<uid>_profile_*.webp`, downloaded once
and shared by all trips), shrunk in place to `small_size`. An owner's companion UID is matched
case-insensitively and uses the profile UID's directory casing. `TripImage` (`cover_trip.webp`),
`TripMap` (`map_trip.webp`), `TripSatelliteMap` (`satellite_trip.webp`) and `map_country.webp`
are shrunk in place to `large_size`. Footprint photos keep the original in `Photo`; the theme
derives the `_thumb` variant (`large_size`) from each name for thumbnails and the carousel.

The converter generates, under `--content`:

- `<content>/<uid>/<trip-slug>/trip.rst` with trip index metadata, copied cover/map images and
  companion metadata.
- `<content>/<uid>/<trip-slug>/footprint_N/footprint.rst` for each footprint, with copied photos,
  videos and attachments. Each geolocated footprint also gets a `map_country.webp`.
- `<content>/flags/` contains the shared flags used by all exported trips. The website publishes
  them under its output root `flags/`; failed flag downloads are reported and omitted.

The RST export does not generate a user/profile page or a global service index. A consuming Pelican
site can build its own index from trip pages using the configured `--category` and trip metadata
(`Date`, `EndDate`, `Transport`).
The `TripMap` is generated as `map_trip.webp` from the GPX track after the GPX is finalized.
The separate `TripSatelliteMap` is generated as `satellite_trip.webp`, always with an Esri
satellite background and footprint bubbles. Each map is generated independently;
a satellite request failure is reported without discarding the main map.

Trip maps are 1200×800 WebP images with a white 4px route line. Their background defaults to transparent;
`map_background: satellite` or `street` requests an Esri map image. These backgrounds require
network access. Footprint bubbles are omitted by default and enabled with
`footprint_bubbles`. Bubbles display the first footprint photo, or the step number
when no photo is available. A matching `.inc` file contains positioned HTML buttons
for linking each bubble to its footprint section; the converter copies it beside
the map. When no valid route exists, no map is generated.

Trip RST metadata retains values used by an index (including period, duration, distance,
countries, description, cover, route map and companions). It has no body sections for insights or
footprint links. Country names are individual tags; integer transport-mode distances are summed
from the mode-tagged GPX tracks and combined into the `Transport` field.

## Operational Notes

- `scrapers reminder --list NAME --output DIR [--all] [--force]` currently prepares the output directory
  (`--force` clears it after `output_safety.validate_clear_directory`) and prints the
  `rem export --list NAME --format json --incomplete > DIR/reminders.json` command to run in a
  terminal; the direct `rem` invocation is commented out in `export_reminders`, so `--all` has no
  effect for now. `scrapers reminders2rst --output DIR [--content DIR]` writes one stable-named
  article per reminder, category `reminder`. Neither converter deletes stale articles.

- Playwright requires an installed Chromium browser; install it with
  `python -m playwright install chromium` in the same Python environment as the project.
- Missing optional fields are omitted from output.
- FindPenguins generally logs failed media downloads and skips the item; Polarsteps reports
  photo thumbnail fallback and fails when required media cannot be downloaded.
- Do not commit credential files such as `profiles.json`.
