"""Hugging Face asset availability: is a model already local, or can it be fetched?

Availability is answered *without* downloading anything.  Weights are pulled only
inside ``load()``, so ``initialise()`` never blocks on a multi-gigabyte transfer.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HUB_PROBE_TIMEOUT_SECONDS = 3.0
CONFIG_FILENAME = "config.json"
DEFAULT_ENDPOINT = "https://huggingface.co"


def package_missing(*packages: str) -> str:
    """Return a reason string naming the first absent package, or ``""``."""
    for package in packages:
        if importlib.util.find_spec(package) is None:
            return f"{package} package is not installed"
    return ""


def is_local_path(model: str) -> bool:
    return Path(model).expanduser().is_dir()


def is_cached(repo_id: str, filename: str = CONFIG_FILENAME) -> bool:
    """True when ``filename`` of ``repo_id`` is already in the local hub cache."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False
    try:
        return isinstance(try_to_load_from_cache(repo_id=repo_id, filename=filename), str)
    except Exception:
        return False


def _offline() -> bool:
    try:
        from huggingface_hub import constants

        return bool(getattr(constants, "HF_HUB_OFFLINE", False))
    except Exception:
        return False


def _endpoint() -> str:
    try:
        from huggingface_hub import constants

        return str(getattr(constants, "ENDPOINT", DEFAULT_ENDPOINT))
    except Exception:
        return DEFAULT_ENDPOINT


def hub_reachable(repo_id: str) -> tuple[bool, str]:
    """Cheap metadata HEAD against the hub.  Never raises."""
    import httpx

    url = f"{_endpoint()}/api/models/{repo_id}"
    try:
        response = httpx.head(url, timeout=HUB_PROBE_TIMEOUT_SECONDS, follow_redirects=True)
    except Exception as exc:
        return False, f"{type(exc).__name__} contacting {url}: {exc}"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code} for {repo_id} at {_endpoint()}"
    return True, ""


def asset_status(repo_id: str, *packages: str, filename: str = CONFIG_FILENAME) -> tuple[bool, str]:
    """``(available, reason)`` for a hub-hosted model plus its required packages."""
    missing = package_missing(*packages)
    if missing:
        return False, missing
    if is_local_path(repo_id):
        return True, f"local weights at {repo_id}"
    if is_cached(repo_id, filename):
        return True, f"{repo_id} present in the local hub cache"
    if _offline():
        return False, f"{repo_id} is not cached and HF_HUB_OFFLINE is set"
    reachable, error = hub_reachable(repo_id)
    if not reachable:
        return False, f"{repo_id} is not cached and the hub is unreachable: {error}"
    return True, f"{repo_id} will be downloaded from {_endpoint()} on first load"
