"""Polarsteps authentication, API access, and media download utilities."""

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from common_archive import _write_json
from polarsteps_config import API_URL, MEDIA_URL, SITE_URL, API_VERSION


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


def _require_list(data, *names):
    """Return the first present named list, or raise if it is missing or invalid."""
    for name in names:
        value = data.get(name)
        if value is not None:
            if not isinstance(value, list):
                raise ValueError(f"Invalid Polarsteps {name}: expected a list")
            return value
    raise ValueError(f"Polarsteps response is missing {' or '.join(names)}")


def media_url(value):
    """Resolve a media path against the Polarsteps CDN and require HTTPS."""
    if not isinstance(value, str) or not value:
        return ""
    url = urljoin(MEDIA_URL, value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Polarsteps media URL must be an absolute HTTPS URL")
    return url


def download_media(item, directory, stem, kind, skip, refresh=False):
    """Reuse or download a photo/video, warning when a photo uses a thumbnail.

    Photos are written as lossless WebP. Skip mode requires the media to have
    been archived already; refresh replaces existing media after a successful download.
    Unavailable videos and failed downloads raise errors.
    """
    if skip and refresh:
        raise ValueError("Cannot refresh media in skip mode")
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
    if destination.is_file() and not refresh:
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
        image_temporary = None
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
                    with tempfile.NamedTemporaryFile(dir=directory, prefix=".media-image-", delete=False) as handle:
                        image_temporary = Path(handle.name)
                        image.save(handle, "WEBP", lossless=True, quality=100, method=4)
                os.replace(image_temporary, destination)
                image_temporary = None
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
            if image_temporary is not None:
                image_temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to download {kind} {stem}") from failure
