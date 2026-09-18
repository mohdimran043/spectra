"""Integration tests across the embedded storage backends."""

from __future__ import annotations

import pytest
from spectra_schemas import (
    Asset,
    AssetKind,
    Chunk,
    DocumentLocator,
    Modality,
    Provenance,
    SourceDescriptor,
    SourceType,
)
from spectra_storage import LEXICAL_INDEX, TEXT_COLLECTION, LexicalDocument, VectorRecord

pytestmark = pytest.mark.integration

SHA = "ab" + "c" * 62


def _source() -> SourceDescriptor:
    return SourceDescriptor(
        source_id="src_docs", name="Corporate Documents", type=SourceType.LOCAL_FOLDER
    )


def _asset() -> Asset:
    return Asset(
        asset_id="ast_1",
        source_id="src_docs",
        kind=AssetKind.DOCUMENT,
        title="Incident_Report.pdf",
        object_uri=f"spectra://objects/ab/{SHA}.pdf",
        media_type="application/pdf",
        content_hash=SHA,
    )


def _chunk(cid: str, text: str, page: int = 1) -> Chunk:
    return Chunk(
        chunk_id=cid,
        asset_id="ast_1",
        source_id="src_docs",
        modality=Modality.DOCUMENT,
        text=text,
        title="Incident_Report.pdf",
        provenance=Provenance(
            source_id="src_docs",
            modality=Modality.DOCUMENT,
            object_uri=f"spectra://objects/ab/{SHA}.pdf",
            locator=DocumentLocator(document_id="DOC9182", page=page),
        ).model_dump(mode="json"),
    )


class TestControlPlane:
    async def test_source_and_asset_round_trip(self, storage):
        await storage.repository.upsert_source(_source())
        await storage.repository.upsert_asset(_asset())

        assert (await storage.repository.get_source("src_docs")).name == "Corporate Documents"
        assert (await storage.repository.get_asset("ast_1")).title == "Incident_Report.pdf"
        assert await storage.repository.count_assets("src_docs") == 1

    async def test_content_hash_dedupe_lookup(self, storage):
        await storage.repository.upsert_source(_source())
        await storage.repository.upsert_asset(_asset())
        found = await storage.repository.find_asset_by_hash(SHA)
        assert found is not None and found.asset_id == "ast_1"

    async def test_chunks_carry_provenance_through_persistence(self, storage):
        await storage.repository.upsert_source(_source())
        await storage.repository.upsert_asset(_asset())
        await storage.repository.upsert_chunks([_chunk("chk_1", "auth timeout", page=14)])

        loaded = await storage.repository.get_chunk("chk_1")
        assert loaded.provenance["locator"]["page"] == 14
        assert loaded.provenance["locator"]["document_id"] == "DOC9182"


class TestVectorStore:
    async def test_cosine_ordering_is_correct(self, storage):
        await storage.vectors.ensure_collection(TEXT_COLLECTION, 3)
        await storage.vectors.upsert(
            TEXT_COLLECTION,
            [
                VectorRecord(id="near", vector=[1.0, 0.0, 0.0], payload={"source_id": "s"}),
                VectorRecord(id="mid", vector=[0.7, 0.7, 0.0], payload={"source_id": "s"}),
                VectorRecord(id="far", vector=[0.0, 0.0, 1.0], payload={"source_id": "s"}),
            ],
        )
        matches = await storage.vectors.search(TEXT_COLLECTION, [1.0, 0.0, 0.0], limit=3)
        assert [m.id for m in matches] == ["near", "mid", "far"]

    async def test_payload_filtering_excludes_other_sources(self, storage):
        await storage.vectors.ensure_collection(TEXT_COLLECTION, 3)
        await storage.vectors.upsert(
            TEXT_COLLECTION,
            [
                VectorRecord(id="a", vector=[1.0, 0.0, 0.0], payload={"source_id": "s1"}),
                VectorRecord(id="b", vector=[1.0, 0.0, 0.0], payload={"source_id": "s2"}),
            ],
        )
        matches = await storage.vectors.search(
            TEXT_COLLECTION, [1.0, 0.0, 0.0], limit=5, filters={"source_id": "s2"}
        )
        assert [m.id for m in matches] == ["b"]


class TestLexicalStore:
    async def test_identifier_query_ranks_the_exact_document_first(self, storage):
        await storage.lexical.ensure_index(LEXICAL_INDEX)
        await storage.lexical.index(
            LEXICAL_INDEX,
            [
                LexicalDocument(id="d1", text="Transaction TX82931 failed at the payment gateway."),
                LexicalDocument(id="d2", text="General notes about transactions and payments."),
                LexicalDocument(id="d3", text="Unrelated capacity planning discussion."),
            ],
        )
        matches = await storage.lexical.search(LEXICAL_INDEX, "TX82931", limit=5)
        assert matches and matches[0].id == "d1"

    async def test_semantic_free_text_still_ranks_sensibly(self, storage):
        await storage.lexical.ensure_index(LEXICAL_INDEX)
        await storage.lexical.index(
            LEXICAL_INDEX,
            [
                LexicalDocument(id="d1", text="The authentication service timed out during login."),
                LexicalDocument(id="d2", text="Quarterly revenue summary for the retail segment."),
            ],
        )
        matches = await storage.lexical.search(LEXICAL_INDEX, "authentication timeout", limit=5)
        assert matches[0].id == "d1"


class TestGraphStore:
    async def test_two_hop_traversal_connects_evidence(self, storage):
        await storage.graph.upsert_node("ent_tx", ["Transaction"], {"canonical_name": "TX82931"})
        await storage.graph.upsert_node("ent_inc", ["Incident"], {"canonical_name": "INC1829"})
        await storage.graph.upsert_node("chk_1", ["Evidence"], {"summary": "auth timeout"})
        await storage.graph.upsert_edge("MENTIONS", "chk_1", "ent_tx")
        await storage.graph.upsert_edge("CAUSED_BY", "ent_tx", "ent_inc")

        view = await storage.graph.neighbours("chk_1", depth=2)
        ids = {n["node_id"] if "node_id" in n else n.get("id") for n in view["nodes"]}
        assert {"chk_1", "ent_tx", "ent_inc"} <= ids


class TestObjectStore:
    async def test_put_and_get_round_trip(self, storage):
        uri = f"spectra://objects/ab/{SHA}.txt"
        await storage.objects.put(uri, b"hello evidence", "text/plain")
        assert await storage.objects.get(uri) == b"hello evidence"
        assert await storage.objects.exists(uri)

    @pytest.mark.parametrize(
        "malicious",
        [
            "spectra://objects/../../etc/passwd",
            "spectra://objects/ab/../../../etc/passwd",
            "file:///etc/passwd",
        ],
    )
    async def test_path_traversal_is_rejected(self, storage, malicious):
        from spectra_storage.object_uris import ObjectUriError

        with pytest.raises(ObjectUriError):
            await storage.objects.get(malicious)


class TestCache:
    async def test_set_get_delete_and_incr(self, storage):
        await storage.cache.set("k", {"v": 1}, ttl_seconds=60)
        assert await storage.cache.get("k") == {"v": 1}
        await storage.cache.delete("k")
        assert await storage.cache.get("k") is None
        assert await storage.cache.incr("counter") == 1
        assert await storage.cache.incr("counter", 4) == 5
