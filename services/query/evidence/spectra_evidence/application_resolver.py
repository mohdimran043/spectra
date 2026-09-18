"""Enterprise application deep links.

A link is only produced when the record id matches the pattern configured for
that entity type, the base URL is a credential-free http(s) URL, and the expanded
URL still points inside that base.  ``verified_in_database`` is set only when an
injected verifier confirms the record exists - a demo never gets a fabricated
link to a record nobody can open.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote, urlsplit

import yaml
from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import ApplicationLink, CanonicalEntity, EntityType

log = get_logger(__name__)

CONFIG_PACKAGE = "spectra_config"
CONFIG_RESOURCE = "resources/applications.yaml"

# Record ids are opaque business keys; anything longer is an injection attempt or
# a bug, and long inputs are never handed to a regex engine.
MAX_RECORD_ID_LENGTH = 64
ALLOWED_SCHEMES = frozenset({"http", "https"})
# Placeholders the URL templates may contain.  Anything else is a config error.
TEMPLATE_BASE = "{base}"
TEMPLATE_ID = "{id}"

VerifyCallable = Callable[[str, str], bool]


class ApplicationConfigError(ValueError):
    """Raised when applications.yaml cannot be used safely."""


@dataclass(frozen=True)
class ApplicationTemplate:
    entity_type: EntityType
    label: str
    url_template: str
    id_pattern: re.Pattern[str]


@lru_cache(maxsize=8)
def load_application_templates(config_path: str | None = None) -> Mapping[EntityType, ApplicationTemplate]:
    """Load, validate and compile the application link templates."""
    path = Path(config_path) if config_path else Path(str(files(CONFIG_PACKAGE).joinpath(CONFIG_RESOURCE)))
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ApplicationConfigError(f"cannot read application config at {path}: {exc}")
    except yaml.YAMLError as exc:
        raise ApplicationConfigError(f"invalid YAML in {path}: {exc}")
    applications = payload.get("applications") if isinstance(payload, Mapping) else None
    if not isinstance(applications, Mapping):
        raise ApplicationConfigError(f"{path} must define an 'applications' mapping")
    templates: dict[EntityType, ApplicationTemplate] = {}
    for key, raw in applications.items():
        template = _parse_template(str(key), raw)
        if template is not None:
            templates[template.entity_type] = template
    if not templates:
        raise ApplicationConfigError(f"{path} defines no usable application templates")
    log.debug("applications.config_loaded", path=str(path), count=len(templates))
    return templates


def _parse_template(key: str, raw: object) -> ApplicationTemplate | None:
    if not isinstance(raw, Mapping):
        log.warning("applications.entry_ignored", entity_type=key, reason="not a mapping")
        return None
    try:
        entity_type = EntityType(key)
    except ValueError:
        log.warning("applications.entry_ignored", entity_type=key, reason="unknown entity type")
        return None
    url_template = str(raw.get("url_template") or "")
    pattern = str(raw.get("id_pattern") or "")
    if TEMPLATE_BASE not in url_template or TEMPLATE_ID not in url_template:
        log.warning("applications.entry_ignored", entity_type=key, reason="template missing {base}/{id}")
        return None
    if not pattern:
        log.warning("applications.entry_ignored", entity_type=key, reason="missing id_pattern")
        return None
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ApplicationConfigError(f"invalid id_pattern for {key}: {exc}")
    return ApplicationTemplate(
        entity_type=entity_type,
        label=str(raw.get("label") or f"Open {entity_type.value}"),
        url_template=url_template,
        id_pattern=compiled,
    )


class ApplicationResolver:
    """Resolves canonical entities to safe, verified application deep links."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        config_path: str | None = None,
        base_url: str | None = None,
        verify: VerifyCallable | None = None,
    ) -> None:
        self._config_path = config_path
        self._templates = load_application_templates(config_path)
        raw_base = base_url if base_url is not None else (settings or get_settings()).application_base_url
        self._base_url = _validated_base(raw_base)
        self._verify = verify

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def entity_types(self) -> tuple[EntityType, ...]:
        return tuple(self._templates)

    def with_verifier(self, verify: VerifyCallable | None) -> ApplicationResolver:
        """Return a NEW resolver bound to this verifier."""
        return ApplicationResolver(
            config_path=self._config_path, base_url=self._base_url, verify=verify
        )

    def resolve(self, entity: CanonicalEntity) -> ApplicationLink | None:
        """Build a deep link for this entity, or ``None`` when unsafe/unverified."""
        template = self._templates.get(entity.entity_type)
        if template is None:
            return None
        record_id = self._record_id(entity, template)
        if record_id is None:
            return None
        url = self._safe_url(template, record_id)
        if url is None:
            return None
        verified = self._verified(entity.entity_type, record_id)
        if verified is None:
            return None
        return ApplicationLink(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            label=template.label,
            url=url,
            record_id=record_id,
            verified_in_database=verified,
        )

    def resolve_many(self, entities: Sequence[CanonicalEntity]) -> list[ApplicationLink]:
        links = [self.resolve(entity) for entity in entities]
        return [link for link in links if link is not None]

    # -- internals --------------------------------------------------------
    def _record_id(self, entity: CanonicalEntity, template: ApplicationTemplate) -> str | None:
        candidates = [
            str(entity.attributes.get("record_id") or ""),
            entity.canonical_name,
            *entity.aliases,
        ]
        for candidate in candidates:
            cleaned = (candidate or "").strip()
            if not cleaned or len(cleaned) > MAX_RECORD_ID_LENGTH:
                continue
            if template.id_pattern.fullmatch(cleaned):
                return cleaned
        log.warning(
            "applications.record_id_rejected",
            entity_id=entity.entity_id,
            entity_type=entity.entity_type.value,
            pattern=template.id_pattern.pattern,
        )
        return None

    def _safe_url(self, template: ApplicationTemplate, record_id: str) -> str | None:
        url = template.url_template.replace(TEMPLATE_BASE, self._base_url).replace(
            TEMPLATE_ID, quote(record_id, safe="")
        )
        if _escapes_base(url, self._base_url):
            log.warning("applications.url_escapes_base", url=url, base_url=self._base_url)
            return None
        return url

    def _verified(self, entity_type: EntityType, record_id: str) -> bool | None:
        """``None`` means "do not emit a link at all"."""
        if self._verify is None:
            # No verifier wired in: the link is offered, but never claimed as verified.
            return False
        try:
            confirmed = bool(self._verify(entity_type.value, record_id))
        except Exception as exc:
            log.warning("applications.verify_failed", record_id=record_id, error=str(exc))
            return None
        if not confirmed:
            log.info("applications.record_not_found", entity_type=entity_type.value, record_id=record_id)
            return None
        return True


def _validated_base(raw: str) -> str:
    base = (raw or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ApplicationConfigError(f"application base URL must be http(s), got {raw!r}")
    if not parsed.netloc:
        raise ApplicationConfigError(f"application base URL needs a host, got {raw!r}")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise ApplicationConfigError("application base URL must not carry credentials")
    if parsed.query or parsed.fragment:
        raise ApplicationConfigError("application base URL must not carry a query or fragment")
    return base


def _escapes_base(url: str, base: str) -> bool:
    """True when the expanded URL leaves the configured base."""
    target, anchor = urlsplit(url), urlsplit(base)
    if target.scheme.lower() != anchor.scheme.lower() or target.netloc != anchor.netloc:
        return True
    if target.username or target.password or "@" in target.netloc:
        return True
    raw_path = target.path or "/"
    if ".." in raw_path.split("/") or "//" in raw_path:
        return True
    normalised = posixpath.normpath(raw_path)
    root = posixpath.normpath(anchor.path or "/")
    if root == "/":
        return not normalised.startswith("/")
    return normalised != root and not normalised.startswith(f"{root}/")


__all__ = [
    "MAX_RECORD_ID_LENGTH",
    "ApplicationConfigError",
    "ApplicationResolver",
    "ApplicationTemplate",
    "VerifyCallable",
    "load_application_templates",
]
