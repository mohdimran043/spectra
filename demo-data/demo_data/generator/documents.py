"""Document generation: the narrative set plus procedural filler for scale.

Filler exists to make retrieval hard, not to answer questions: its templates
never touch the narrative's findings, so recall measured against the expected
targets stays meaningful as the corpus grows.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Final

from spectra_config.logging import get_logger

from .constants import DOCUMENTS_DIR
from .content import build_document_specs
from .docwriters import DocumentArtifact, write_document
from .rng import iso_date, make_rng, pick
from .specs import FORMAT_DOCX, FORMAT_MD, FORMAT_PDF, FORMAT_TXT, DocumentSpec, section
from .world import STREAM_FILLER, World

log = get_logger(__name__)

FILLER_TOPICS: Final[tuple[str, ...]] = (
    "weekly operations review",
    "backlog grooming note",
    "dependency upgrade record",
    "cost review summary",
    "access recertification note",
    "load test observation",
    "release readiness checklist",
    "vendor status update",
    "documentation gap report",
    "toil reduction proposal",
)
FILLER_BODIES: Final[tuple[str, ...]] = (
    "No customer-visible impact was recorded for {service} during the period under review.",
    "Queue depth for {service} stayed inside the agreed envelope and required no intervention.",
    "The scheduled maintenance for {service} completed inside its window with no rollback.",
    "Dashboards for {service} were refreshed and the stale panels were retired.",
    "Runbook links for {service} were checked and two dead links were replaced.",
    "Alert thresholds for {service} were reviewed; no threshold was changed this cycle.",
)
#: Only every Nth filler document is a PDF, so the large tier stays cheap.
FILLER_PDF_EVERY: Final[int] = 10
FILLER_DOCX_EVERY: Final[int] = 7
FILLER_PARAGRAPHS: Final[int] = 4


def _filler_format(index: int) -> str:
    if index % FILLER_PDF_EVERY == 0:
        return FORMAT_PDF
    if index % FILLER_DOCX_EVERY == 0:
        return FORMAT_DOCX
    return FORMAT_MD if index % 2 == 0 else FORMAT_TXT


def _filler_spec(world: World, rng: random.Random, index: int) -> DocumentSpec:
    service = pick(rng, [asset.service for asset in world.data.assets])
    topic = pick(rng, FILLER_TOPICS)
    incident = pick(rng, world.data.incidents[3:] or world.data.incidents)
    paragraphs = tuple(pick(rng, FILLER_BODIES).format(service=service) for _ in range(FILLER_PARAGRAPHS))
    pages = (
        section(f"{topic.title()} - {service}", *paragraphs),
        section(
            "References",
            f"Related ticket {incident.incident_id} ({incident.status}), opened {iso_date(incident.opened_at)}.",
        ),
    )
    return DocumentSpec(
        slug=f"ops-note-{index:05d}",
        fmt=_filler_format(index),
        title=f"{topic.title()} {index:05d} - {service}",
        sections=pages,
        tags=("filler", "operations"),
        entities=(incident.incident_id,),
        occurred_at=incident.opened_at,
    )


def generate_documents(world: World, out_dir: Path) -> tuple[DocumentArtifact, ...]:
    """Write every document and return the manifest records, narrative first."""
    directory = out_dir / DOCUMENTS_DIR
    specs = list(build_document_specs(world))
    rng = make_rng(world.seed, STREAM_FILLER)
    for index in range(max(0, world.scale.documents - len(specs))):
        specs.append(_filler_spec(world, rng, index))
    artifacts = [
        write_document(spec, world.ids.document(), directory, out_dir)
        for spec in specs
    ]
    log.info("demo_data.documents_generated", count=len(artifacts), directory=str(directory))
    return tuple(artifacts)
