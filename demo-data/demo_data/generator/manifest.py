"""The manifest: the single place downstream code learns the generated ids.

Nothing else - not the guided demo, not the benchmark, not the expected
answers - may contain a literal demo identifier.  They all read this file, so
re-seeding moves every id at once and everything still lines up.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence

from .audio import AudioArtifact
from .constants import (
    ARCHITECTURE_DATABASE_NODES,
    FAILED_PAYMENT_THRESHOLD,
    GENERATOR_VERSION,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
)
from .database import DatabaseArtifacts
from .docwriters import DocumentArtifact
from .expected import ExpectedQuestion
from .images import ImageArtifact
from .rng import iso
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, LEDGER_SERVICE, SESSION_DB
from .videos import VideoArtifact
from .world import World


def _records(items: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if not is_dataclass(item):  # pragma: no cover - defensive
            raise TypeError(f"manifest entries must be dataclasses, got {type(item)!r}")
        out.append(asdict(item))
    return out


def _story(world: World) -> dict[str, Any]:
    cast = world.cast
    transaction = world.data.focus_transaction
    incident = world.data.root_incident
    return {
        "customer_name": world.customer_name,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "failure_reason": transaction.failure_reason,
        "root_cause": cast.root_cause,
        "key_finding": world.key_finding,
        "release_tag": cast.release_tag,
        "region": cast.region,
        "available_balance": world.data.focus_available_balance,
        "architecture_database_nodes": ARCHITECTURE_DATABASE_NODES,
        "services": {
            "auth": AUTH_SERVICE,
            "gateway": GATEWAY_SERVICE,
            "fraud": FRAUD_SERVICE,
            "ledger": LEDGER_SERVICE,
            "session_store": SESSION_DB,
        },
        "people": [
            {"name": person.name, "role": person.role, "email": person.email, "speaker": person.speaker}
            for person in cast.people
        ],
        "timeline": {name: iso(moment) for name, moment in cast.timeline.ordered},
        "approval": {
            "approved": incident.approved,
            "approved_by": incident.approved_by,
            "at": iso(cast.timeline.approval_at),
            "contradiction": "approval memo revision 1 (superseded) denies the approval that revision 2 "
                             "(current) and the incidents table both record",
        },
        "variants": {
            "transaction": list(world.transaction_variants),
            "customer": list(world.customer_variants),
            "incident": list(world.incident_variants),
        },
    }


def _identifiers(world: World) -> dict[str, Any]:
    data = world.data
    failures = data.failed_counts()
    above = [
        customer.customer_id
        for customer in data.customers
        if failures.get(customer.customer_id, 0) > FAILED_PAYMENT_THRESHOLD
    ]
    return {
        "customer": world.customer_id,
        "transaction": world.transaction_id,
        "incident": world.incident_id,
        "fraud_incident": world.fraud_incident_id,
        "network_incident": world.network_incident_id,
        "auth_asset": data.auth_asset.asset_id,
        "gateway_asset": data.gateway_asset.asset_id,
        "database_assets": [asset.asset_id for asset in data.database_assets],
        "boosted_failure_customers": list(data.high_failure_customers),
        "customers_above_threshold": above,
        "meeting_customers": list(data.meeting_customers),
        "failed_payment_threshold": FAILED_PAYMENT_THRESHOLD,
    }


def build_manifest(
    world: World,
    database: DatabaseArtifacts,
    documents: Sequence[DocumentArtifact],
    images: Sequence[ImageArtifact],
    audio: Sequence[AudioArtifact],
    videos: Sequence[VideoArtifact],
    questions: Sequence[ExpectedQuestion],
    expected_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """Assemble the manifest document (no wall-clock values, so it stays reproducible)."""
    categories: dict[str, int] = {}
    for question in questions:
        categories[question.category] = categories.get(question.category, 0) + 1
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": world.seed,
        "scale": world.scale.name,
        "ids": _identifiers(world),
        "story": _story(world),
        "database": {
            "sqlite_path": str(database.sqlite_path),
            "schema_sql": database.schema_sql_path.relative_to(out_dir).as_posix(),
            "inserts_sql": database.inserts_sql_path.relative_to(out_dir).as_posix(),
            "counts": database.counts,
        },
        "documents": _records(documents),
        "images": _records(images),
        "audio": _records(audio),
        "videos": _records(videos),
        "expected": {
            "path": expected_path.relative_to(out_dir).as_posix(),
            "count": len(questions),
            "categories": dict(sorted(categories.items())),
        },
        "counts": {
            "documents": len(documents),
            "images": len(images),
            "audio": len(audio),
            "videos": len(videos),
            **database.counts,
        },
    }


def write_manifest(out_dir: Path, manifest: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_FILENAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def load_manifest(out_dir: Path) -> dict[str, Any]:
    """Read a manifest back; raises ``FileNotFoundError`` when nothing was generated."""
    path = out_dir / MANIFEST_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"no manifest at {path}; run `python -m demo_data.generator` first")
    return json.loads(path.read_text(encoding="utf-8"))
