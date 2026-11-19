"""Generic XML, text, and image helpers shared by scraper and converter."""

import os
import re
import json
import tempfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from common_archive import _write_json
from common_config import GPX_NS


def download_country_flags(output, skip=False):
    """Cache FlagCDN's name-to-codes table and 64x48 WebP flags under output/flags.

    Duplicate names retain every code. Skip mode uses only cached data and warns
    about missing flags; normal mode downloads or repairs missing files.
    """
    print(f"  - Loading country flags ...")
    flags_dir = Path(output) / "flags"
    if flags_dir.is_symlink():
        raise ValueError(f"Refusing symbolic-link flags directory: {flags_dir}")
    codes_path = flags_dir / "codes.json"
    if codes_path.is_symlink():
        raise ValueError(f"Refusing symbolic-link flag table: {codes_path}")
    if codes_path.exists():
        with codes_path.open(encoding="utf-8") as handle:
            names = json.load(handle)
    elif skip:
        print(f"  WARNING: no saved country flag table at {codes_path}")
        return {}
    else:
        response = requests.get("https://flagcdn.com/en/codes.json", timeout=30)
        response.raise_for_status()
        source = response.json()
        if not isinstance(source, dict) or not source:
            raise ValueError("FlagCDN country codes must be a nonempty object")
        names = {}
        for code, name in source.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Invalid FlagCDN country name for code {code!r}")
            names.setdefault(name, []).append(code)

    if not isinstance(names, dict) or not names:
        raise ValueError(f"Invalid country flag table: {codes_path}")
    codes = set()
    for name, entries in names.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(entries, list) or not entries:
            raise ValueError(f"Invalid country flag table entry: {name!r}")
        for code in entries:
            if not isinstance(code, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)*", code):
                raise ValueError(f"Invalid country flag code: {code!r}")
            codes.add(code)

    flags_dir.mkdir(parents=True, exist_ok=True)
    available = set()
    for code in sorted(codes):
        destination = flags_dir / f"{code}.webp"
        if destination.is_symlink():
            raise ValueError(f"Refusing symbolic-link flag file: {destination}")
        valid = False
        if destination.is_file():
            try:
                with Image.open(destination) as image:
                    valid = image.format == "WEBP" and image.size == (64, 48)
                    image.verify()
            except OSError:
                valid = False
        if not valid:
            if skip:
                print(f"  WARNING: missing or invalid saved flag: {destination}")
                continue
            response = requests.get(f"https://flagcdn.com/64x48/{code}.webp", timeout=30)
            response.raise_for_status()
            with Image.open(BytesIO(response.content)) as image:
                if image.format != "WEBP" or image.size != (64, 48):
                    raise ValueError(f"FlagCDN returned an invalid 64x48 WebP flag for {code}")
                image.verify()
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=flags_dir, prefix=".flag-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(response.content)
                os.replace(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        available.add(code)
    if not skip:
        _write_json(str(codes_path), names)
    return {name: entries if all(code in available for code in entries) else []
            for name, entries in names.items()}


def country_flag(name, country_codes, code=None):
    """Return an archive-relative flag path when the country can be identified."""
    if not country_codes or not name:
        return ""
    requested_code = code.lower() if isinstance(code, str) else ""
    matches = [item for country, codes in country_codes.items()
               if country.casefold() == str(name).strip().casefold() for item in codes]
    if requested_code and any(requested_code in codes for codes in country_codes.values()):
        if matches and requested_code not in matches:
            print(f"  WARNING: country flag code {requested_code!r} does not match {name!r}")
            return ""
        return f"flags/{requested_code}.webp"
    if requested_code:
        print(f"  WARNING: unknown or unavailable country flag code: {requested_code!r}")
    if len(matches) == 1:
        return f"flags/{matches[0]}.webp"
    print(f"  WARNING: {'ambiguous' if matches else 'unknown'} country flag for {name!r}")
    return ""


def gpx_tag(name):
    """! @brief Build a GPX namespaced tag for ElementTree operations.
    @param name Local (non-namespaced) tag name.
    @return Fully-qualified namespaced tag string.
    """
    return f"{{{GPX_NS}}}{name}"


def add_text_element(parent, name, value, namespace=GPX_NS):
    """! @brief Append a text child element only when value is non-empty.
    @param parent Parent XML element.
    @param name Child tag name.
    @param value Value assigned to child text; skipped when empty.
    @param namespace Namespace URI or falsy value for plain tag.
    @return Newly created child element or None when skipped.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    tag = gpx_tag(name) if namespace else name
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def format_tree(tree):
    """! @brief Apply 2-space indentation to an ElementTree.
    @param tree XML tree to format.
    @return Same input tree after in-place indentation.
    """
    ET.indent(tree, space="  ", level=0)
    return tree


def clean_text(t):
    """! @brief Normalize contiguous whitespace to single spaces.
    @param t Input text value (nullable).
    @return Trimmed string with compacted whitespace.
    """
    return re.sub(r"\s+", " ", (t or "")).strip()


def strip_leading_flag(text):
    """Remove a leading Unicode country or subdivision flag from text."""
    return re.sub(
        r"^\s*(?:[\U0001f1e6-\U0001f1ff]{2}|\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f)\s*",
        "", str(text or ""),
    ).strip()


def extract_private_references(text):
    """! @brief Extract URL references from private text notes.
    @param text Raw note text that may include URLs.
    @return Tuple (cleaned_text, list of (search_text, url) references).
    """
    if not text:
        return "", []

    references = []
    text_lines = []
    for line in text.splitlines():
        line_text = line.strip()
        search_text = ""
        url = line_text
        if line_text.startswith("[") and "]" in line_text:
            search_end = line_text.index("]")
            search_text = line_text[1:search_end].strip()
            url = line_text[search_end + 1:].strip()

        try:
            parsed_url = urlparse(url)
            valid_url = (
                parsed_url.scheme.lower() in ("http", "https")
                and bool(parsed_url.hostname)
                and not any(char.isspace() for char in url)
            )
            parsed_url.port
        except ValueError:
            valid_url = False

        if valid_url:
            reference = search_text, url
            if reference not in references:
                references.append(reference)
        else:
            text_lines.append(line)

    cleaned = "\n".join(text_lines)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, references


def to_webp(path):
    """! @brief Convert an image to lossless WebP next to the source and remove the source.
    @param path Source image path.
    @return Path of the WebP file (unchanged when already WebP).
    """
    if path.lower().endswith(".webp"):
        return path
    webp_path = os.path.splitext(path)[0] + ".webp"
    with Image.open(path) as image:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info or image.mode in ("LA", "PA") else "RGB")
        image.save(webp_path, "WEBP", lossless=True, quality=100, method=4, exact=True)
    os.remove(path)
    return webp_path


def variant_path(path, suffix):
    """! @brief Return the path of a size variant, e.g. `a.webp` -> `a_large.webp`."""
    root, ext = os.path.splitext(path)
    return f"{root}_{suffix}{ext}"


def make_variant(path, suffix, max_size):
    """! @brief Create a lossless WebP copy of an image whose longest side is at most `max_size`.
    The original is kept and never upscaled; an existing variant of the right size is reused.
    @param path Source WebP image path.
    @param suffix Variant suffix (e.g. "small", "medium", "large").
    @param max_size Maximum width/height in pixels.
    @return Path of the variant file.
    """
    target = variant_path(path, suffix)
    with Image.open(path) as image:
        expected = image.size
        if max(expected) > max_size:
            ratio = max_size / max(expected)
            expected = (max(1, round(expected[0] * ratio)), max(1, round(expected[1] * ratio)))
        if os.path.isfile(target):
            with Image.open(target) as existing:
                if existing.size == expected:
                    return target
        resized = image.copy()
        if resized.size != expected:
            resized = resized.resize(expected, Image.LANCZOS)
        resized.save(target, "WEBP", lossless=True, quality=100, method=4, exact=True)
    return target


def shrink_image(path, max_size):
    """! @brief Downscale a WebP image in place (lossless) so its longest side is at most `max_size`.
    Images already small enough are left untouched.
    @param path WebP image path.
    @param max_size Maximum width/height in pixels.
    @return The same path.
    """
    with Image.open(path) as image:
        if max(image.size) <= max_size:
            return path
        ratio = max_size / max(image.size)
        resized = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.LANCZOS)
    resized.save(path, "WEBP", lossless=True, quality=100, method=4, exact=True)
    return path


