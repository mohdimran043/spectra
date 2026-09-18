"""Conversions between ORM rows and the shared pydantic schemas.

Every write path dumps the model with ``mode="json"`` before it touches a JSON
column: free-form ``dict[str, Any]`` fields (connection details, metadata,
provenance) routinely contain enums and datetimes, and a driver-level "object of
type X is not JSON serialisable" at 2 a.m. is a far worse failure than a
normalised value.  Read paths hand the raw column values back to pydantic, which
re-validates them - that is what makes the round trip lossless.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from spectra_config.logging import get_logger
from spectra_schemas import (
    Asset,
    CanonicalEntity,
    Chunk,
    EntityLink,
    IndexVersion,
    IngestJob,
    SourceDescriptor,
)

from .models import (
    AssetRow,
    ChunkRow,
    EntityLinkRow,
    EntityRow,
    IndexVersionRow,
    IngestJobRow,
    SourceRow,
)

log = get_logger(__name__)


def json_payload(model: BaseModel) -> dict[str, Any]:
    """JSON-safe view of a pydantic model (enums flattened, datetimes ISO)."""
    return model.model_dump(mode="json")


# -- sources --------------------------------------------------------------
def source_values(source: SourceDescriptor) -> dict[str, Any]:
    payload = json_payload(source)
    return {
        "source_id": source.source_id,
        "name": source.name,
        "type": source.type.value,
        "modalities": payload["modalities"],
        "connection": payload["connection"],
        "credential_ref": source.credential_ref,
        "enabled": source.enabled,
        "reliability_override": source.reliability_override,
        "reliability_reason": source.reliability_reason,
        "permissions": payload["permissions"],
        "created_at": source.created_at,
        "last_sync": source.last_sync,
        "record_count": source.record_count,
        "asset_count": source.asset_count,
        "status": source.status.value,
        "status_detail": source.status_detail,
    }


def source_model(row: SourceRow) -> SourceDescriptor:
    return SourceDescriptor(
        source_id=row.source_id,
        name=row.name,
        type=row.type,
        modalities=row.modalities,
        connection=row.connection,
        credential_ref=row.credential_ref,
        enabled=row.enabled,
        reliability_override=row.reliability_override,
        reliability_reason=row.reliability_reason,
        permissions=row.permissions,
        created_at=row.created_at,
        last_sync=row.last_sync,
        record_count=row.record_count,
        asset_count=row.asset_count,
        status=row.status,
        status_detail=row.status_detail,
    )


# -- assets ---------------------------------------------------------------
def asset_values(asset: Asset) -> dict[str, Any]:
    payload = json_payload(asset)
    return {
        "asset_id": asset.asset_id,
        "source_id": asset.source_id,
        "kind": asset.kind.value,
        "title": asset.title,
        "object_uri": asset.object_uri,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "content_hash": asset.content_hash,
        "version": asset.version,
        "version_status": asset.version_status,
        "created_at": asset.created_at,
        "modified_at": asset.modified_at,
        "ingested_at": asset.ingested_at,
        "status": asset.status.value,
        "error": asset.error,
        "metadata_json": payload["metadata"],
        "duration_seconds": asset.duration_seconds,
        "page_count": asset.page_count,
        "permissions": payload["permissions"],
    }


def asset_model(row: AssetRow) -> Asset:
    return Asset(
        asset_id=row.asset_id,
        source_id=row.source_id,
        kind=row.kind,
        title=row.title,
        object_uri=row.object_uri,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        content_hash=row.content_hash,
        version=row.version,
        version_status=row.version_status,
        created_at=row.created_at,
        modified_at=row.modified_at,
        ingested_at=row.ingested_at,
        status=row.status,
        error=row.error,
        metadata=row.metadata_json,
        duration_seconds=row.duration_seconds,
        page_count=row.page_count,
        permissions=row.permissions,
    )


# -- chunks ---------------------------------------------------------------
def chunk_values(chunk: Chunk) -> dict[str, Any]:
    payload = json_payload(chunk)
    return {
        "chunk_id": chunk.chunk_id,
        "asset_id": chunk.asset_id,
        "source_id": chunk.source_id,
        "modality": chunk.modality.value,
        "text": chunk.text,
        "title": chunk.title,
        "ordinal": chunk.ordinal,
        "provenance": payload["provenance"],
        "entities": payload["entities"],
        "metadata_json": payload["metadata"],
        "index_version": chunk.index_version,
        "embedding_ref": chunk.embedding_ref,
        "created_at": chunk.created_at,
        "occurred_at": chunk.occurred_at,
        "permissions": payload["permissions"],
    }


def chunk_model(row: ChunkRow) -> Chunk:
    return Chunk(
        chunk_id=row.chunk_id,
        asset_id=row.asset_id,
        source_id=row.source_id,
        modality=row.modality,
        text=row.text,
        title=row.title,
        ordinal=row.ordinal,
        provenance=row.provenance,
        entities=row.entities,
        metadata=row.metadata_json,
        index_version=row.index_version,
        embedding_ref=row.embedding_ref,
        created_at=row.created_at,
        occurred_at=row.occurred_at,
        permissions=row.permissions,
    )


# -- entities -------------------------------------------------------------
def entity_values(entity: CanonicalEntity) -> dict[str, Any]:
    payload = json_payload(entity)
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "canonical_name": entity.canonical_name,
        "aliases": payload["aliases"],
        "normalized_keys": payload["normalized_keys"],
        "confidence": entity.confidence,
        "source_ids": payload["source_ids"],
        "modalities": payload["modalities"],
        "attributes": payload["attributes"],
        "mention_count": entity.mention_count,
        "first_seen": entity.first_seen,
        "last_seen": entity.last_seen,
    }


def entity_model(row: EntityRow) -> CanonicalEntity:
    return CanonicalEntity(
        entity_id=row.entity_id,
        entity_type=row.entity_type,
        canonical_name=row.canonical_name,
        aliases=row.aliases,
        normalized_keys=row.normalized_keys,
        confidence=row.confidence,
        source_ids=row.source_ids,
        modalities=row.modalities,
        attributes=row.attributes,
        mention_count=row.mention_count,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
    )


def link_values(link: EntityLink) -> dict[str, Any]:
    return {
        "entity_id": link.entity_id,
        "chunk_id": link.chunk_id,
        "asset_id": link.asset_id,
        "source_id": link.source_id,
        "modality": link.modality.value,
        "surface": link.surface,
        "confidence": link.confidence,
    }


def link_model(row: EntityLinkRow) -> EntityLink:
    return EntityLink(
        entity_id=row.entity_id,
        chunk_id=row.chunk_id,
        asset_id=row.asset_id,
        source_id=row.source_id,
        modality=row.modality,
        surface=row.surface,
        confidence=row.confidence,
    )


# -- jobs -----------------------------------------------------------------
def job_values(job: IngestJob) -> dict[str, Any]:
    payload = json_payload(job)
    return {
        "job_id": job.job_id,
        "asset_id": job.asset_id,
        "source_id": job.source_id,
        "status": job.status.value,
        "stage": job.stage,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "stages_completed": payload["stages_completed"],
    }


def job_model(row: IngestJobRow) -> IngestJob:
    return IngestJob(
        job_id=row.job_id,
        asset_id=row.asset_id,
        source_id=row.source_id,
        status=row.status,
        stage=row.stage,
        progress=row.progress,
        message=row.message,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        stages_completed=row.stages_completed,
    )


# -- index versions / audit ----------------------------------------------
def index_version_values(version: IndexVersion) -> dict[str, Any]:
    return {
        "index_version": version.index_version,
        "embedding_model": version.embedding_model,
        "embedding_dimension": version.embedding_dimension,
        "parser_version": version.parser_version,
        "vision_model": version.vision_model,
        "speech_model": version.speech_model,
        "ocr_engine": version.ocr_engine,
        "created_at": version.created_at,
    }


def index_version_model(row: IndexVersionRow) -> IndexVersion:
    return IndexVersion(
        index_version=row.index_version,
        embedding_model=row.embedding_model,
        embedding_dimension=row.embedding_dimension,
        parser_version=row.parser_version,
        vision_model=row.vision_model,
        speech_model=row.speech_model,
        ocr_engine=row.ocr_engine,
        created_at=row.created_at,
    )


