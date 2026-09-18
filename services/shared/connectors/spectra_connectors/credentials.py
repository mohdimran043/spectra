"""Credential resolution and redaction.

Three rules hold everywhere in this package:

1. **Credentials are never stored in** ``SourceDescriptor.connection``.  A
   descriptor only carries a ``credential_ref`` - a pointer.  Inlined secrets
   are rejected by :func:`reject_inline_secrets`, which the Source Service calls
   on every create/update.
2. **Credentials are never logged.**  Every log call in this package passes its
   payload through :func:`redact` first.
3. **Credentials are never returned by an API-facing method.**  ``metadata()``,
   ``safe_connection()`` and the health/catalog surfaces emit redacted views
   only; resolved secrets stay inside the connector that needs them.

Resolution order for a ``credential_ref``:

* ``env:NAME``          -> the ``NAME`` environment variable (a scalar secret)
* ``SPECTRA_SECRET_<SLUG>``          -> JSON object, or a scalar secret
* ``SPECTRA_SECRET_<SLUG>__<FIELD>`` -> one field of the credential
* ``<runtime_dir>/secrets.json``     -> ``{"<ref>": {...}}``, file mode 0600

Environment values win over the file, so a container can override a laptop file.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger

from .errors import CredentialError

log = get_logger(__name__)

REDACTED = "***redacted***"
SECRETS_FILENAME = "secrets.json"
SECRETS_FILE_MODE = 0o600
ENV_PREFIX = "SPECTRA_SECRET_"
ENV_FIELD_SEPARATOR = "__"
_SCALAR_KEY = "value"

#: Any mapping key matching this is treated as a secret by :func:`redact`.
SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|credential|authorization|auth[_-]?header|session[_-]?key|passphrase|dsn|sas)",
    re.IGNORECASE,
)
_SLUG_PATTERN = re.compile(r"[^A-Za-z0-9]+")


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_PATTERN.search(key or ""))


def redact(value: Any) -> Any:
    """Return a deep copy of ``value`` with every secret-looking entry masked.

    Used by *every* log call in this package.  Accepts mappings, sequences and
    scalars so it can be dropped in front of an arbitrary payload.
    """
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_secret_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def reject_inline_secrets(connection: Mapping[str, Any], *, where: str = "connection") -> None:
    """Raise if a descriptor tries to store a secret inline.

    Enforces the contract documented on ``SourceDescriptor.connection``
    ("Secrets are never stored here").
    """
    offenders = sorted(str(key) for key in connection if is_secret_key(str(key)))
    if offenders:
        raise CredentialError(
            f"secrets must not be stored in {where}: {', '.join(offenders)}; "
            "put them in the secret store and set credential_ref instead"
        )


def _slug(ref: str) -> str:
    return _SLUG_PATTERN.sub("_", ref).strip("_").upper()


def _coerce(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CredentialError(f"credential payload is not valid JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise CredentialError("credential payload must be a JSON object")
        return {str(key): item for key, item in parsed.items()}
    return {_SCALAR_KEY: raw}


class CredentialStore:
    """Resolves ``SourceDescriptor.credential_ref`` into a secret mapping."""

    def __init__(
        self,
        settings: Settings | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._env: Mapping[str, str] = env if env is not None else os.environ

    @property
    def secrets_path(self) -> Path:
        return Path(self._settings.runtime_dir) / SECRETS_FILENAME

    # -- resolution -------------------------------------------------------
    def resolve(self, credential_ref: str | None) -> dict[str, Any]:
        """Return the secret mapping for ``credential_ref`` (empty when unset).

        The returned dict is a fresh copy: callers cannot mutate the store.
        """
        if not credential_ref:
            return {}
        if credential_ref.startswith("env:"):
            return self._from_named_env(credential_ref[4:])
        resolved = {**self._from_file(credential_ref), **self._from_env(credential_ref)}
        log.debug(
            "credentials.resolved",
            source_ref=credential_ref,
            fields=sorted(resolved),
            payload=redact(resolved),
        )
        return resolved

    def require(self, credential_ref: str | None, *fields: str) -> dict[str, Any]:
        """Resolve and assert that every field in ``fields`` is present."""
        resolved = self.resolve(credential_ref)
        missing = [name for name in fields if not resolved.get(name)]
        if missing:
            raise CredentialError(
                f"credential {credential_ref!r} is missing required field(s): {', '.join(missing)}"
            )
        return resolved

    def value(self, credential_ref: str | None, field: str, default: Any = None) -> Any:
        """One field of a credential, or ``default``.

        A scalar secret (``env:PGPASSWORD``) answers to any field name.
        """
        resolved = self.resolve(credential_ref)
        if field in resolved:
            return resolved[field]
        if set(resolved) == {_SCALAR_KEY}:
            return resolved[_SCALAR_KEY]
        return default

    def _from_named_env(self, name: str) -> dict[str, Any]:
        raw = self._env.get(name)
        if raw is None:
            raise CredentialError(f"environment variable {name!r} referenced by credential_ref is not set")
        return _coerce(raw)

    def _from_env(self, credential_ref: str) -> dict[str, Any]:
        slug = _slug(credential_ref)
        base_key = f"{ENV_PREFIX}{slug}"
        resolved: dict[str, Any] = {}
        raw = self._env.get(base_key)
        if raw is not None:
            resolved.update(_coerce(raw))
        field_prefix = f"{base_key}{ENV_FIELD_SEPARATOR}"
        for key, item in self._env.items():
            if key.startswith(field_prefix) and len(key) > len(field_prefix):
                resolved[key[len(field_prefix) :].lower()] = item
        return resolved

    def _from_file(self, credential_ref: str) -> dict[str, Any]:
        path = self.secrets_path
        if not path.exists():
            return {}
        self._warn_on_loose_permissions(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialError(f"secrets file {path.name} is unreadable: {exc}") from exc
        if not isinstance(payload, dict):
            raise CredentialError(f"secrets file {path.name} must contain a JSON object")
        entry = payload.get(credential_ref)
        if entry is None:
            return {}
        if isinstance(entry, dict):
            return {str(key): item for key, item in entry.items()}
        return {_SCALAR_KEY: entry}

    # -- writing ----------------------------------------------------------
    def put(self, credential_ref: str, secret: Mapping[str, Any] | str) -> None:
        """Store a secret in the local secrets file with mode 0600."""
        if not credential_ref:
            raise CredentialError("credential_ref must be a non-empty string")
        path = self.secrets_path
        payload = self._read_all(path)
        entry: Any = dict(secret) if isinstance(secret, Mapping) else secret
        merged = {**payload, credential_ref: entry}
        self._write_all(path, merged)
        log.info("credentials.stored", source_ref=credential_ref, path=str(path))

    def delete(self, credential_ref: str) -> bool:
        path = self.secrets_path
        payload = self._read_all(path)
        if credential_ref not in payload:
            return False
        remaining = {key: item for key, item in payload.items() if key != credential_ref}
        self._write_all(path, remaining)
        log.info("credentials.deleted", source_ref=credential_ref)
        return True

    def _read_all(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialError(f"secrets file {path.name} is unreadable: {exc}") from exc
        return payload if isinstance(payload, dict) else {}

    def _write_all(self, path: Path, payload: MutableMapping[str, Any] | dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECRETS_FILE_MODE)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.chmod(path, SECRETS_FILE_MODE)
        except OSError as exc:
            raise CredentialError(f"cannot write secrets file {path.name}: {exc}") from exc

    @staticmethod
    def _warn_on_loose_permissions(path: Path) -> None:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:  # pragma: no cover - race with deletion
            return
        if mode & 0o077:
            log.warning("credentials.file_permissions_loose", path=str(path), mode=oct(mode))
