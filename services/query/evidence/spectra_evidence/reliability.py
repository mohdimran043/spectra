"""Configurable source-reliability scoring.

Reliability is never a hard-coded truth value: every weight, authority and decay
constant comes from ``spectra_config/resources/reliability.yaml`` and any source
in the registry may override the computed score outright.  The scorer always
returns the number *and* the reason, because an investigator has to be able to
argue with the ranking.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import yaml
from spectra_config.logging import get_logger
from spectra_schemas import EvidenceKind, Modality, Provenance, SourceDescriptor

log = get_logger(__name__)

CONFIG_PACKAGE = "spectra_config"
CONFIG_RESOURCE = "resources/reliability.yaml"

# Evidence with no usable date can be neither rewarded nor punished for age, so
# it scores the neutral midpoint instead of decaying towards zero.
NEUTRAL_FRESHNESS = 0.5
# Evidence that never names the target may still be topically relevant, but it
# cannot be attributed to the entity with confidence.
SPECIFICITY_WITHOUT_ENTITY = 0.4
# Three independent agreeing sources count as full corroboration - the same
# saturation point EvidenceLedger.diversity() uses for distinct sources.
CORROBORATION_SATURATION = 3.0
# Used when a source class is missing from authority_by_kind: unknown provenance
# is treated as exactly average rather than trusted or dismissed.
DEFAULT_AUTHORITY = 0.5
SECONDS_PER_DAY = 86_400.0

_KIND_BY_MODALITY: Mapping[Modality, EvidenceKind] = {
    Modality.DOCUMENT: EvidenceKind.DOCUMENT,
    Modality.IMAGE: EvidenceKind.IMAGE,
    Modality.VIDEO: EvidenceKind.VIDEO,
    Modality.AUDIO: EvidenceKind.AUDIO,
    Modality.DATABASE: EvidenceKind.DATABASE,
    Modality.GRAPH: EvidenceKind.GRAPH,
    Modality.EXTERNAL: EvidenceKind.EXTERNAL_API,
}

_KIND_PHRASES: Mapping[EvidenceKind, str] = {
    EvidenceKind.DATABASE: "Database record",
    EvidenceKind.APPLICATION_RECORD: "Application record",
    EvidenceKind.DOCUMENT: "Document",
    EvidenceKind.AUDIO: "Audio recording",
    EvidenceKind.VIDEO: "Video recording",
    EvidenceKind.IMAGE: "Image",
    EvidenceKind.EXTERNAL_API: "External API response",
    EvidenceKind.GRAPH: "Graph relationship",
}


class ReliabilityConfigError(ValueError):
    """Raised when reliability.yaml cannot be used as written."""


@dataclass(frozen=True)
class ReliabilityConfig:
    """Immutable view of reliability.yaml."""

    weights: Mapping[str, float]
    authority_by_kind: Mapping[str, float]
    version_status_score: Mapping[str, float]
    freshness_half_life_days: float
    version: int = 1

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> ReliabilityConfig:
        weights = _float_map(payload.get("weights"), "weights")
        if not weights or sum(weights.values()) <= 0:
            raise ReliabilityConfigError("reliability.yaml needs at least one positive weight")
        half_life = float(payload.get("freshness_half_life_days") or 0)
        if half_life <= 0:
            raise ReliabilityConfigError("freshness_half_life_days must be greater than zero")
        total = sum(weights.values())
        return cls(
            weights={key: value / total for key, value in weights.items()},
            authority_by_kind=_float_map(payload.get("authority_by_kind"), "authority_by_kind"),
            version_status_score=_float_map(payload.get("version_status_score"), "version_status_score"),
            freshness_half_life_days=half_life,
            version=int(payload.get("version") or 1),
        )

    def weight(self, name: str) -> float:
        return float(self.weights.get(name, 0.0))


def _float_map(raw: object, field: str) -> Mapping[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ReliabilityConfigError(f"{field} must be a mapping, got {type(raw).__name__}")
    parsed: dict[str, float] = {}
    for key, value in raw.items():
        try:
            parsed[str(key)] = float(value)
        except (TypeError, ValueError):
            raise ReliabilityConfigError(f"{field}.{key} must be numeric, got {value!r}")
    return parsed


@lru_cache(maxsize=8)
def load_reliability_config(config_path: str | None = None) -> ReliabilityConfig:
    """Load and validate reliability.yaml (cached per path)."""
    path = Path(config_path) if config_path else Path(str(files(CONFIG_PACKAGE).joinpath(CONFIG_RESOURCE)))
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ReliabilityConfigError(f"cannot read reliability config at {path}: {exc}")
    except yaml.YAMLError as exc:
        raise ReliabilityConfigError(f"invalid YAML in {path}: {exc}")
    if not isinstance(payload, Mapping):
        raise ReliabilityConfigError(f"{path} must contain a mapping at the top level")
    config = ReliabilityConfig.from_mapping(payload)
    log.debug("reliability.config_loaded", path=str(path), version=config.version)
    return config


def kind_for_provenance(provenance: Provenance) -> EvidenceKind:
    """Best evidence kind for a provenance record."""
    locator_kind = getattr(provenance.locator, "kind", None)
    if locator_kind == "database":
        return EvidenceKind.DATABASE
    if locator_kind == "external":
        return EvidenceKind.EXTERNAL_API
    return _KIND_BY_MODALITY.get(provenance.modality, EvidenceKind.EXTERNAL_API)


class ReliabilityScorer:
    """Scores one piece of provenance and explains the score in plain English."""

    def __init__(
        self,
        config: ReliabilityConfig | None = None,
        *,
        sources: Mapping[str, SourceDescriptor] | None = None,
        config_path: str | None = None,
    ) -> None:
        self._config = config or load_reliability_config(config_path)
        self._sources: dict[str, SourceDescriptor] = dict(sources or {})

    @property
    def config(self) -> ReliabilityConfig:
        return self._config

    def with_sources(self, sources: Mapping[str, SourceDescriptor]) -> ReliabilityScorer:
        """Return a NEW scorer that also knows about these registry entries."""
        return ReliabilityScorer(self._config, sources={**self._sources, **dict(sources)})

    def version_score(self, version_status: str | None) -> float:
        statuses = self._config.version_status_score
        key = (version_status or "unknown").strip().lower()
        return float(statuses.get(key, statuses.get("unknown", NEUTRAL_FRESHNESS)))

    def score(
        self,
        provenance: Provenance,
        *,
        corroboration_count: int = 0,
        entity_named: bool = False,
        entity_label: str | None = None,
        kind: EvidenceKind | None = None,
        source: SourceDescriptor | None = None,
        now: datetime | None = None,
    ) -> tuple[float, str]:
        """Return ``(score, reason)`` for this provenance."""
        descriptor = source or self._sources.get(provenance.source_id)
        override = self._override(descriptor)
        if override is not None:
            return override
        resolved_kind = kind or kind_for_provenance(provenance)
        components, phrases = self._components(
            provenance,
            resolved_kind,
            corroboration_count=max(int(corroboration_count), 0),
            entity_named=entity_named,
            entity_label=entity_label,
            now=now or datetime.now(timezone.utc),
        )
        score = sum(self._config.weight(name) * value for name, value in components.items())
        return round(_clamp(score), 4), ", ".join(phrases)

    # -- internals --------------------------------------------------------
    def _override(self, source: SourceDescriptor | None) -> tuple[float, str] | None:
        if source is None or source.reliability_override is None:
            return None
        value = round(_clamp(float(source.reliability_override)), 4)
        reason = f"Registry override {value:.2f} for source '{source.name}' (replaces the computed score)"
        if source.reliability_reason:
            reason = f"{reason}: {source.reliability_reason}"
        log.debug("reliability.override_applied", source_id=source.source_id, score=value)
        return value, reason

    def _components(
        self,
        provenance: Provenance,
        kind: EvidenceKind,
        *,
        corroboration_count: int,
        entity_named: bool,
        entity_label: str | None,
        now: datetime,
    ) -> tuple[dict[str, float], list[str]]:
        authority = self._authority(kind)
        freshness, freshness_phrase = self._freshness(provenance, now)
        version = self.version_score(provenance.version_status)
        specificity = 1.0 if entity_named else SPECIFICITY_WITHOUT_ENTITY
        corroboration = min(corroboration_count / CORROBORATION_SATURATION, 1.0)

        target = entity_label or "the target entity"
        phrases = [
            _KIND_PHRASES.get(kind, kind.value.replace("_", " ").capitalize()),
            _version_phrase(provenance.version_status),
            f"names {target} explicitly" if entity_named else f"does not name {target}",
            _corroboration_phrase(corroboration_count),
            freshness_phrase,
        ]
        components = {
            "authority": authority,
            "freshness": freshness,
            "specificity": specificity,
            "corroboration": corroboration,
            "version_status": version,
        }
        return components, phrases

    def _authority(self, kind: EvidenceKind) -> float:
        value = self._config.authority_by_kind.get(kind.value)
        if value is None:
            log.warning("reliability.authority_missing", kind=kind.value, default=DEFAULT_AUTHORITY)
            return DEFAULT_AUTHORITY
        return _clamp(value)

    def _freshness(self, provenance: Provenance, now: datetime) -> tuple[float, str]:
        stamp = provenance.modified_at or provenance.created_at or provenance.ingested_at
        if stamp is None:
            return NEUTRAL_FRESHNESS, "undated"
        age_days = max((now - _as_utc(stamp)).total_seconds() / SECONDS_PER_DAY, 0.0)
        # Exponential decay expressed directly as a half-life: after
        # freshness_half_life_days the freshness term is worth half as much.
        freshness = 0.5 ** (age_days / self._config.freshness_half_life_days)
        return _clamp(freshness), _age_phrase(age_days)


def _version_phrase(version_status: str | None) -> str:
    status = (version_status or "unknown").strip().lower()
    if status == "unknown":
        return "version status unknown"
    return f"{status} version"


def _corroboration_phrase(count: int) -> str:
    if count <= 0:
        return "uncorroborated"
    noun = "source" if count == 1 else "sources"
    return f"corroborated by {count} independent {noun}"


def _age_phrase(age_days: float) -> str:
    if age_days < 1.0:
        return "recorded today"
    days = int(round(age_days))
    return f"recorded {days} day{'s' if days != 1 else ''} ago"


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
