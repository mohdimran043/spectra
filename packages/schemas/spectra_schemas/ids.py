"""Deterministic, collision-resistant identifier helpers.

Ids are content-addressed wherever possible so re-ingesting the same object
produces the same ids - which is what makes reindexing idempotent.
"""

from __future__ import annotations

import hashlib
import uuid


def _digest(*parts: object, length: int = 12) -> str:
    joined = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def asset_id(source_id: str, content_sha: str) -> str:
    return f"ast_{_digest(source_id, content_sha, length=16)}"


def chunk_id(asset_id_: str, ordinal: int, discriminator: str = "") -> str:
    return f"chk_{_digest(asset_id_, ordinal, discriminator, length=16)}"


def entity_id(entity_type: str, normalized: str) -> str:
    return f"ent_{entity_type}_{_digest(entity_type, normalized, length=12)}"


def mention_id(chunk_id_: str, start: int, surface: str) -> str:
    return f"men_{_digest(chunk_id_, start, surface, length=14)}"


def evidence_id(chunk_or_record: str, claim_scope: str = "") -> str:
    return f"evd_{_digest(chunk_or_record, claim_scope, length=14)}"


def claim_id(investigation_id_: str, index: int) -> str:
    return f"C{index + 1}"


def investigation_id() -> str:
    return new_id("inv")


def case_id() -> str:
    return new_id("case")


def job_id() -> str:
    return new_id("job")


def step_id(investigation_id_: str, sequence: int) -> str:
    return f"step_{_digest(investigation_id_, sequence, length=10)}"


def call_id() -> str:
    return new_id("call")


def object_uri(content_sha: str, extension: str = "") -> str:
    suffix = f".{extension.lstrip('.')}" if extension else ""
    return f"spectra://objects/{content_sha[:2]}/{content_sha}{suffix}"
