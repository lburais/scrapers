"""Read service-specific accounts from a shared profiles file."""

import json


DEFAULT_SETTINGS = {
    "small_size": 128,
    "large_size": 1600,
    "map_background": "transparent",
    "footprint_bubbles": False,
    "footprint_bubble_size": 48,
}


def load_profiles(path, service):
    """Return account tuples and settings from a shared profiles JSON file.

    Service sections and per-person service entries are supported, as are
    legacy FindPenguins accounts. Missing passwords become empty strings.
    Raise ValueError for malformed data or when the service has no accounts.
    """
    if service not in ("findpenguins", "polarsteps"):
        raise ValueError(f"Unknown profile service: {service}")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("Profile settings must be a JSON object")
    accounts = []
    for name, person in data.items():
        if name == "settings":
            continue
        if name in ("findpenguins", "polarsteps"):
            if not isinstance(person, dict):
                raise ValueError(f"{name} section must be a JSON object")
            if name == service:
                accounts.extend(person.items())
            continue
        if not isinstance(person, dict):
            raise ValueError(f"Profile {name!r} must be a JSON object")
        if service in person:
            account = person[service]
        elif any(key in person for key in ("id", "username", "password")):
            if service != "findpenguins":
                continue
            account = person
        elif "findpenguins" in person or "polarsteps" in person:
            continue
        else:
            raise ValueError(f"Profile {name!r} has no supported service account")
        accounts.append((name, account))
    profiles = []
    for name, account in accounts:
        if not isinstance(account, dict):
            raise ValueError(f"{service} account for {name!r} must be a JSON object")
        profile_id = account.get("id")
        username = account.get("username")
        password = account.get("password", "")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError(f"{service} account for {name!r} needs an id")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str):
            raise ValueError(f"{service} account for {name!r} needs a username and string password")
        profiles.append((profile_id, username, password))
    if not profiles:
        raise ValueError(f"No {service} profiles found in {path}")
    return profiles, settings
