"""The model registry: roles -> ordered candidate implementations.

Backed by ``spectra_config/resources/models.yaml``.  Application code asks for a
:class:`ModelRole`; only the runtime manager ever sees a concrete model name.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from spectra_config.logging import get_logger
from spectra_schemas import ModelCandidate, ModelRole

log = get_logger(__name__)

RESOURCE_PACKAGE = "spectra_config.resources"
REGISTRY_FILENAME = "models.yaml"
DEFAULT_PREFER_DEVICE = "cpu"
DEFAULT_VRAM_BUDGET_MB = 0

# ``${NAME}`` or ``${NAME:-fallback}`` - the shell-style form used in models.yaml.
ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


@dataclass(frozen=True)
class ProfileSpec:
    """A hardware profile: how much VRAM may be spent and on what device."""

    name: str
    description: str
    vram_budget_mb: int
    allow_concurrent_gpu_models: bool
    prefer_device: str


@dataclass(frozen=True)
class RoleSpec:
    """Everything the manager needs to satisfy one capability."""

    role: ModelRole
    enabled: bool
    purpose: str
    dimension: int | None
    candidates: tuple[ModelCandidate, ...]
    fallback_role: ModelRole | None


def expand_env(value: str) -> str:
    """Expand ``${NAME:-default}`` placeholders against the process environment."""

    def _replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.environ.get(name) or (default or "")

    return ENV_PLACEHOLDER.sub(_replace, value)


def _expand(value: Any) -> Any:
    return expand_env(value) if isinstance(value, str) else value


def _registry_path() -> Path:
    """Locate models.yaml via the installed package, falling back to the repo layout."""
    try:
        from importlib.resources import files

        resource = files(RESOURCE_PACKAGE) / REGISTRY_FILENAME
        path = Path(str(resource))
        if path.is_file():
            return path
    except (ImportError, ModuleNotFoundError, TypeError) as exc:  # pragma: no cover - packaging edge
        log.debug("registry.resource_lookup_failed", error=str(exc))
    import spectra_config

    return Path(spectra_config.__file__).resolve().parent / "resources" / REGISTRY_FILENAME


def _build_profile(name: str, raw: Mapping[str, Any]) -> ProfileSpec:
    return ProfileSpec(
        name=name,
        description=str(raw.get("description", "")),
        vram_budget_mb=int(raw.get("vram_budget_mb", DEFAULT_VRAM_BUDGET_MB)),
        allow_concurrent_gpu_models=bool(raw.get("allow_concurrent_gpu_models", False)),
        prefer_device=str(raw.get("prefer_device", DEFAULT_PREFER_DEVICE)),
    )


def _build_candidate(raw: Mapping[str, Any]) -> ModelCandidate:
    dimension = raw.get("dimension")
    return ModelCandidate(
        runtime=str(_expand(raw.get("runtime", ""))),
        model=str(_expand(raw.get("model", ""))),
        vram_mb=int(raw.get("vram_mb", 0)),
        device=str(_expand(raw.get("device", "auto"))),
        dimension=int(dimension) if dimension is not None else None,
        compute_type=_expand(raw.get("compute_type")),
    )


def _build_role(role: ModelRole, raw: Mapping[str, Any]) -> RoleSpec:
    raw_candidates: Sequence[Mapping[str, Any]] = raw.get("candidates") or ()
    dimension = raw.get("dimension")
    fallback = raw.get("fallback_role")
    return RoleSpec(
        role=role,
        enabled=bool(raw.get("enabled", True)),
        purpose=str(raw.get("purpose", "")),
        dimension=int(dimension) if dimension is not None else None,
        candidates=tuple(_build_candidate(item) for item in raw_candidates),
        fallback_role=ModelRole(str(fallback)) if fallback else None,
    )


def _disabled_role(role: ModelRole) -> RoleSpec:
    return RoleSpec(
        role=role,
        enabled=False,
        purpose="",
        dimension=None,
        candidates=(),
        fallback_role=None,
    )


class ModelRegistry:
    """Read-only view over models.yaml."""

    def __init__(self, document: Mapping[str, Any], source: str = "<memory>") -> None:
        self.source = source
        self.version = int(document.get("version", 1))
        profiles = document.get("profiles") or {}
        roles = document.get("roles") or {}
        self._profiles: dict[str, ProfileSpec] = {
            name: _build_profile(name, raw or {}) for name, raw in profiles.items()
        }
        self._roles: dict[ModelRole, RoleSpec] = {}
        for name, raw in roles.items():
            try:
                role = ModelRole(str(name))
            except ValueError:
                log.warning("registry.unknown_role", role=str(name), source=source)
                continue
            self._roles[role] = _build_role(role, raw or {})

    @classmethod
    def load(cls, path: Path | None = None) -> ModelRegistry:
        target = path or _registry_path()
        if not target.is_file():
            raise FileNotFoundError(f"model registry not found: {target}")
        document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            raise ValueError(f"model registry must be a mapping: {target}")
        return cls(document, source=str(target))

    def profile(self, name: str) -> ProfileSpec:
        spec = self._profiles.get(name)
        if spec is None:
            known = ", ".join(sorted(self._profiles)) or "<none>"
            raise ValueError(f"unknown model profile {name!r}; registry defines: {known}")
        return spec

    def profiles(self) -> tuple[ProfileSpec, ...]:
        return tuple(self._profiles.values())

    def role(self, role: ModelRole) -> RoleSpec:
        """Never raises: a role missing from the registry is simply disabled."""
        return self._roles.get(role) or _disabled_role(role)

    def roles(self) -> tuple[RoleSpec, ...]:
        """Every :class:`ModelRole`, in enum order, so iteration is deterministic."""
        return tuple(self.role(role) for role in ModelRole)


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    return ModelRegistry.load()
