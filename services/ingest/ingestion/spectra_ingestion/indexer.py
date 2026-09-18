"""The one place a chunk is written everywhere it has to exist.

A chunk is only useful when the repository, the vector store, the lexical index
and the graph all agree about it.  Doing that in five pipelines would guarantee
drift, so every pipeline hands finished chunks to :class:`Indexer` instead.

Re-indexing an asset replaces *that asset's* records and nothing else, so an
ingest can be repeated safely after a crash or a model upgrade.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final, TypeVar

from spectra_ai_core.gateway import ModelGateway, get_gateway
from spectra_config.logging import get_logger
from spectra_schemas import (
    Asset,
    CanonicalEntity,
    Chunk,
    EntityLink,
    IndexVersion,
    Modality,
)
from spectra_storage.facade import IMAGE_COLLECTION, LEXICAL_INDEX, TEXT_COLLECTION, Storage, get_storage
from spectra_storage.interfaces import LexicalDocument, VectorRecord

log = get_logger(__name__)

EMBED_BATCH: Final[int] = 32
UPSERT_BATCH: Final[int] = 256
GRAPH_BATCH: Final[int] = 32
PREVIEW_CHARS: Final[int] = 320
PARSER_VERSION: Final[str] = "spectra-ingestion/1"

T = TypeVar("T")

#: chunk.modality -> graph label for the owning asset node.
ASSET_LABELS: Final[dict[Modality, str]] = {
    Modality.DOCUMENT: "Document",
    Modality.IMAGE: "Image",
    Modality.VIDEO: "Video",
    Modality.AUDIO: "Audio",
    Modality.DATABASE: "DatabaseRecord",
}


@dataclass(frozen=True)
class IndexReport:
    """What one ``index_asset`` call actually wrote."""

    asset_id: str
    index_version: str
    chunk_count: int = 0
    text_vectors: int = 0
    image_vectors: int = 0
    lexical_documents: int = 0
    entities: int = 0
    links: int = 0
    warnings: tuple[str, ...] = ()


@dataclass
class _Collected:
    warnings: list[str] = field(default_factory=list)

    def note(self, event: str, error: Exception) -> None:
        message = f"{event}: {error}"
        log.warning(f"index.{event}", error=str(error))
        self.warnings.append(message)


class Indexer:
    """Writes chunks to the repository, both vector spaces, BM25 and the graph."""

    def __init__(self, storage: Storage, gateway: ModelGateway) -> None:
        self._storage = storage
        self._gateway = gateway
        self._version: IndexVersion | None = None

    @classmethod
    async def create(cls) -> Indexer:
        return cls(await get_storage(), await get_gateway())

    async def index_version(self) -> IndexVersion:
        """Current index version, built once from the gateway's model signature."""
        if self._version is not None:
            return self._version
        version = _build_index_version(self._signature(), self._dimension())
        try:
            await self._storage.repository.record_index_version(version)
        except Exception as exc:
            log.warning("index.record_version_failed", error=str(exc))
        self._version = version
        return version

    async def index_asset(
        self,
        asset: Asset,
        chunks: Sequence[Chunk],
        *,
        image_vectors: Mapping[str, Sequence[float]] | None = None,
        entities: Sequence[CanonicalEntity] = (),
        links: Sequence[EntityLink] = (),
        replace: bool = True,
    ) -> IndexReport:
        """Write one asset's chunks everywhere.  ``replace`` makes it idempotent."""
        version = await self.index_version()
        collected = _Collected()
        if replace:
            await self._purge(asset.asset_id, collected)
        if not chunks:
            return IndexReport(asset_id=asset.asset_id, index_version=version.index_version,
                               warnings=tuple(collected.warnings))

        stamped = [_stamp(chunk, version) for chunk in chunks]
        await self._persist_chunks(stamped, collected)
        text_vectors = await self._write_text_vectors(stamped, collected)
        written_images = await self._write_image_vectors(image_vectors or {}, stamped, collected)
        lexical = await self._write_lexical(asset, stamped, collected)
        await self._write_entities(entities, links, collected)
        await self._write_graph(asset, stamped, entities, links, collected)

        return IndexReport(
            asset_id=asset.asset_id,
            index_version=version.index_version,
            chunk_count=len(stamped),
            text_vectors=text_vectors,
            image_vectors=written_images,
            lexical_documents=lexical,
            entities=len(entities),
            links=len(links),
            warnings=tuple(collected.warnings),
        )

    async def reindex(self, asset_ids: Sequence[str] | None = None) -> list[IndexReport]:
        """Re-embed and rewrite stored chunks under the current index version.

        Extraction is never repeated - the stored chunk text is authoritative -
        and existing image vectors are left in place because they cannot be
        recomputed without the source media.
        """
        repository = self._storage.repository
        targets = list(asset_ids) if asset_ids else [asset.asset_id for asset in await repository.list_assets()]
        reports: list[IndexReport] = []
        for asset_id in targets:
            asset = await repository.get_asset(asset_id)
            if asset is None:
                log.warning("index.reindex_unknown_asset", asset_id=asset_id)
                continue
            chunks = await repository.list_chunks_by_asset(asset_id)
            reports.append(await self.index_asset(asset, chunks, replace=False))
        return reports

    # -- write steps ------------------------------------------------------
    async def _purge(self, asset_id: str, collected: _Collected) -> None:
        try:
            previous = await self._storage.repository.list_chunks_by_asset(asset_id)
        except Exception as exc:
            collected.note("purge_lookup_failed", exc)
            return
        ids = [chunk.chunk_id for chunk in previous]
        if not ids:
            return
        for collection in (TEXT_COLLECTION, IMAGE_COLLECTION):
            try:
                await self._storage.vectors.delete(collection, ids)
            except Exception as exc:
                collected.note("vector_delete_failed", exc)
        try:
            await self._storage.lexical.delete(LEXICAL_INDEX, ids)
        except Exception as exc:
            collected.note("lexical_delete_failed", exc)
        try:
            await self._storage.repository.delete_chunks_for_asset(asset_id)
        except Exception as exc:
            collected.note("chunk_delete_failed", exc)

    async def _persist_chunks(self, chunks: Sequence[Chunk], collected: _Collected) -> None:
        for batch in _batched(chunks, UPSERT_BATCH):
            try:
                await self._storage.repository.upsert_chunks(batch)
            except Exception as exc:
                collected.note("chunk_upsert_failed", exc)

    async def _write_text_vectors(self, chunks: Sequence[Chunk], collected: _Collected) -> int:
        written = 0
        for batch in _batched(chunks, EMBED_BATCH):
            vectors = await self._embed([chunk.text for chunk in batch], collected)
            if not vectors:
                continue
            records = [
                VectorRecord(id=chunk.chunk_id, vector=vector, payload=_payload(chunk))
                for chunk, vector in zip(batch, vectors, strict=False)
            ]
            written += await self._upsert_vectors(TEXT_COLLECTION, records, collected)
        return written

    async def _write_image_vectors(
        self,
        image_vectors: Mapping[str, Sequence[float]],
        chunks: Sequence[Chunk],
        collected: _Collected,
    ) -> int:
        if not image_vectors:
            return 0
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        records = [
            VectorRecord(id=chunk_id, vector=list(vector), payload=_payload(by_id[chunk_id]))
            for chunk_id, vector in image_vectors.items()
            if chunk_id in by_id and vector
        ]
        return await self._upsert_vectors(IMAGE_COLLECTION, records, collected)

    async def _upsert_vectors(
        self, collection: str, records: Sequence[VectorRecord], collected: _Collected
    ) -> int:
        if not records:
            return 0
        try:
            await self._storage.vectors.ensure_collection(collection, len(records[0].vector))
            return int(await self._storage.vectors.upsert(collection, records))
        except Exception as exc:
            collected.note(f"vector_upsert_failed:{collection}", exc)
            return 0

    async def _write_lexical(self, asset: Asset, chunks: Sequence[Chunk], collected: _Collected) -> int:
        documents = [
            LexicalDocument(
                id=chunk.chunk_id,
                text=chunk.text,
                title=chunk.title or asset.title,
                payload=_payload(chunk),
            )
            for chunk in chunks
        ]
        written = 0
        try:
            await self._storage.lexical.ensure_index(LEXICAL_INDEX)
        except Exception as exc:
            collected.note("lexical_ensure_failed", exc)
            return 0
        for batch in _batched(documents, UPSERT_BATCH):
            try:
                written += int(await self._storage.lexical.index(LEXICAL_INDEX, batch))
            except Exception as exc:
                collected.note("lexical_index_failed", exc)
        return written

    async def _write_entities(
        self, entities: Sequence[CanonicalEntity], links: Sequence[EntityLink], collected: _Collected
    ) -> None:
        for entity in entities:
            try:
                await self._storage.repository.upsert_entity(entity)
            except Exception as exc:
                collected.note("entity_upsert_failed", exc)
        for batch in _batched(links, UPSERT_BATCH):
            try:
                await self._storage.repository.upsert_entity_links(batch)
            except Exception as exc:
                collected.note("entity_link_upsert_failed", exc)

    async def _write_graph(
        self,
        asset: Asset,
        chunks: Sequence[Chunk],
        entities: Sequence[CanonicalEntity],
        links: Sequence[EntityLink],
        collected: _Collected,
    ) -> None:
        graph = self._storage.graph
        label = ASSET_LABELS.get(asset.modality, "Asset")
        try:
            await graph.upsert_node(asset.asset_id, ["Asset", label], _asset_properties(asset))
        except Exception as exc:
            collected.note("graph_asset_failed", exc)
            return
        for chunk in chunks:
            await self._graph_chunk(chunk, asset, collected)
        for entity in entities:
            await self._graph_entity(entity, collected)
        for link in links:
            await self._graph_edge("MENTIONS", link.chunk_id, link.entity_id,
                                   {"surface": link.surface, "confidence": link.confidence}, collected)

    async def _graph_chunk(self, chunk: Chunk, asset: Asset, collected: _Collected) -> None:
        try:
            await self._storage.graph.upsert_node(chunk.chunk_id, ["Chunk"], _chunk_properties(chunk))
        except Exception as exc:
            collected.note("graph_chunk_failed", exc)
            return
        await self._graph_edge("BELONGS_TO", chunk.chunk_id, asset.asset_id, {}, collected)

    async def _graph_entity(self, entity: CanonicalEntity, collected: _Collected) -> None:
        labels = ["Entity", entity.entity_type.value.capitalize()]
        properties = {
            "entity_id": entity.entity_id,
            "name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "mention_count": entity.mention_count,
        }
        try:
            await self._storage.graph.upsert_node(entity.entity_id, labels, properties)
        except Exception as exc:
            collected.note("graph_entity_failed", exc)

    async def _graph_edge(
        self, edge_type: str, start: str, end: str, properties: dict[str, Any], collected: _Collected
    ) -> None:
        try:
            await self._storage.graph.upsert_edge(edge_type, start, end, properties)
        except Exception as exc:
            collected.note(f"graph_edge_failed:{edge_type}", exc)

    # -- model calls ------------------------------------------------------
    async def _embed(self, texts: Sequence[str], collected: _Collected) -> list[list[float]]:
        if not texts:
            return []
        try:
            result = await self._gateway.embed_texts(texts)
        except Exception as exc:
            collected.note("embed_failed", exc)
            return []
        vectors = list(result.vectors)
        if len(vectors) != len(texts):
            collected.note("embed_size_mismatch", ValueError(f"{len(vectors)} != {len(texts)}"))
            return []
        return vectors

    def _signature(self) -> dict[str, Any]:
        try:
            return dict(self._gateway.index_signature())
        except Exception as exc:
            log.warning("index.signature_failed", error=str(exc))
            return {}

    def _dimension(self) -> int:
        try:
            return int(self._gateway.embedding_dimension())
        except Exception as exc:
            log.warning("index.dimension_failed", error=str(exc))
            return 0


def _stamp(chunk: Chunk, version: IndexVersion) -> Chunk:
    return chunk.model_copy(
        update={
            "index_version": version.index_version,
            "embedding_ref": f"{TEXT_COLLECTION}:{chunk.chunk_id}",
        }
    )


def _payload(chunk: Chunk) -> dict[str, Any]:
    provenance = chunk.provenance or {}
    locator = provenance.get("locator", {}) if isinstance(provenance, dict) else {}
    return {
        "chunk_id": chunk.chunk_id,
        "asset_id": chunk.asset_id,
        "source_id": chunk.source_id,
        "modality": chunk.modality.value,
        "title": chunk.title or "",
        "ordinal": chunk.ordinal,
        "permissions": list(chunk.permissions),
        "index_version": chunk.index_version or "",
        "occurred_at": chunk.occurred_at.isoformat() if chunk.occurred_at else None,
        "page": locator.get("page") if isinstance(locator, dict) else None,
        "section": locator.get("section") if isinstance(locator, dict) else None,
        "start_seconds": locator.get("start_seconds") if isinstance(locator, dict) else None,
        "end_seconds": locator.get("end_seconds") if isinstance(locator, dict) else None,
        "entities": list(chunk.entities),
        "preview": chunk.text[:PREVIEW_CHARS],
    }


def _asset_properties(asset: Asset) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "source_id": asset.source_id,
        "title": asset.title,
        "kind": asset.kind.value,
        "media_type": asset.media_type,
        "object_uri": asset.object_uri,
        "content_hash": asset.content_hash,
        "permissions": list(asset.permissions),
    }


def _chunk_properties(chunk: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "asset_id": chunk.asset_id,
        "source_id": chunk.source_id,
        "modality": chunk.modality.value,
        "ordinal": chunk.ordinal,
        "preview": chunk.text[:PREVIEW_CHARS],
        "index_version": chunk.index_version or "",
    }


def _build_index_version(signature: Mapping[str, Any], dimension: int) -> IndexVersion:
    """Build the version record from whichever spelling the gateway reports."""
    embedding_model = _pick(signature, "embedding_model", "embedding") or "unknown"
    resolved_dimension = int(signature.get("embedding_dimension", dimension) or dimension or 0)
    parser_version = str(signature.get("parser_version") or PARSER_VERSION)
    identifier = signature.get("index_version") or _signature_digest(
        embedding_model, resolved_dimension, parser_version, signature
    )
    return IndexVersion(
        index_version=str(identifier),
        embedding_model=embedding_model,
        embedding_dimension=resolved_dimension,
        parser_version=parser_version,
        vision_model=_pick(signature, "vision_model", "vision"),
        speech_model=_pick(signature, "speech_model", "speech"),
        ocr_engine=_pick(signature, "ocr_engine", "ocr"),
        created_at=datetime.now(timezone.utc),
    )


def _pick(signature: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _optional(signature.get(key))
        if value:
            return value
    return None


def _signature_digest(model: str, dimension: int, parser: str, signature: Mapping[str, Any]) -> str:
    payload = "|".join(
        [model, str(dimension), parser, *(f"{k}={signature[k]}" for k in sorted(signature))]
    )
    return f"idx_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _batched(items: Sequence[T] | Iterable[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
