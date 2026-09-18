"""Shared test fixtures.

Every test runs against an isolated data directory with all-embedded backends,
so the suite needs no infrastructure and cannot pollute a developer's data/.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def isolated_environment():
    """Point every service at a throwaway data directory with embedded backends."""
    tmp = Path(tempfile.mkdtemp(prefix="spectra-tests-"))
    env = {
        "DATA_DIR": str(tmp),
        "SQLITE_URL": f"sqlite+aiosqlite:///{tmp}/spectra.db",
        "RELATIONAL_BACKEND": "sqlite",
        "VECTOR_BACKEND": "embedded",
        "LEXICAL_BACKEND": "embedded",
        "GRAPH_BACKEND": "embedded",
        "OBJECT_BACKEND": "filesystem",
        "CACHE_BACKEND": "memory",
        "MODEL_PROFILE": "cpu",
        "MODEL_RUNTIME": "deterministic",
        "LOG_LEVEL": "WARNING",
        "SPECTRA_ENV_FILE": str(tmp / "nonexistent.env"),
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    from spectra_config import reload_settings

    reload_settings()
    yield tmp

    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    reload_settings()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def settings(isolated_environment):
    from spectra_config import get_settings

    return get_settings()


@pytest.fixture
async def storage(isolated_environment):
    from spectra_storage import get_storage, reset_storage

    store = await get_storage()
    await store.repository.initialise()
    yield store
    await reset_storage()


@pytest.fixture
async def gateway(isolated_environment):
    from spectra_ai_core import get_gateway, reset_gateway

    gw = await get_gateway()
    yield gw
    await reset_gateway()


@pytest.fixture
def analyst_ctx():
    from spectra_schemas import PermissionContext, Role

    return PermissionContext(user_id="test-analyst", role=Role.ANALYST)


@pytest.fixture
def viewer_ctx():
    from spectra_schemas import PermissionContext, Role

    return PermissionContext(user_id="test-viewer", role=Role.VIEWER)
