"""Contract tests for the shared schema package."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from spectra_schemas import (
    ConfidenceLabel,
    DocumentLocator,
    EvidenceItem,
    EvidenceKind,
    EvidenceLedger,
    EvidenceStance,
    Modality,
    Provenance,
    VideoLocator,
    asset_id,
    chunk_id,
    entity_id,
    format_timestamp,
    object_uri,
    parse_locator,
)


def _provenance(source: str, kind: str = "document", **kw) -> Provenance:
    locator = (
        DocumentLocator(document_id=kw.pop("doc", "DOC1"), page=kw.pop("page", 1))
        if kind == "document"
        else VideoLocator(video_id="VID1", start_seconds=10.0, end_seconds=20.0)
    )
    return Provenance(
        source_id=source,
        modality=Modality.DOCUMENT if kind == "document" else Modality.VIDEO,
        object_uri=f"spectra://objects/ab/{'a' * 64}",
        locator=locator,
        **kw,
    )


def _evidence(eid: str, source: str, modality: Modality, kind: EvidenceKind, doc: str = "DOC1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=eid,
        kind=kind,
        modality=modality,
        summary="s",
        provenance=Provenance(
            source_id=source,
            modality=modality,
            object_uri=f"spectra://objects/ab/{'a' * 64}",
            locator=DocumentLocator(document_id=doc, page=1),
        ),
        relevance=0.8,
        reliability=0.7,
    )


class TestIdentifiers:
    def test_asset_id_is_content_addressed(self):
        assert asset_id("src", "abc") == asset_id("src", "abc")
        assert asset_id("src", "abc") != asset_id("src", "abd")

    def test_chunk_id_is_stable_per_ordinal(self):
        assert chunk_id("ast_1", 3) == chunk_id("ast_1", 3)
        assert chunk_id("ast_1", 3) != chunk_id("ast_1", 4)

    def test_entity_id_collapses_the_same_normalised_key(self):
        assert entity_id("transaction", "TX82931") == entity_id("transaction", "TX82931")

    def test_object_uri_shards_by_hash_prefix(self):
        uri = object_uri("ab" + "c" * 62, "pdf")
        assert uri.startswith("spectra://objects/ab/")
        assert uri.endswith(".pdf")


class TestProvenance:
    def test_document_locator_renders_a_human_citation(self):
        p = Provenance(
            source_id="src",
            modality=Modality.DOCUMENT,
            object_uri="spectra://objects/ab/x",
            locator=DocumentLocator(document_id="DOC9182", page=14, section="Authentication"),
        )
        assert p.human() == "Document: DOC9182 | Page: 14 | Section: Authentication"

    def test_video_locator_renders_a_timestamp(self):
        loc = VideoLocator(video_id="VID129", start_seconds=2537)
        assert loc.human() == "Video: VID129 @ 00:42:17"

    def test_locators_round_trip_through_serialisation(self):
        original = VideoLocator(video_id="V", scene_id="S1", start_seconds=1.5, end_seconds=9.0)
        assert parse_locator(original.model_dump()) == original

    def test_unknown_locator_kind_is_rejected(self):
        with pytest.raises(ValueError):
            parse_locator({"kind": "hologram"})

    def test_locators_are_immutable(self):
        loc = DocumentLocator(document_id="D", page=1)
        with pytest.raises(ValidationError):
            loc.page = 2

    @pytest.mark.parametrize("seconds,expected", [(0, "00:00:00"), (61, "00:01:01"), (3742, "01:02:22")])
    def test_timestamp_formatting(self, seconds, expected):
        assert format_timestamp(seconds) == expected


class TestEvidenceLedger:
    def test_with_items_returns_a_new_ledger(self):
        ledger = EvidenceLedger()
        item = _evidence("e1", "src", Modality.DOCUMENT, EvidenceKind.DOCUMENT)
        updated = ledger.with_items([item])
        assert ledger.items == []          # original untouched
        assert len(updated.items) == 1

    def test_with_items_deduplicates_by_id(self):
        item = _evidence("e1", "src", Modality.DOCUMENT, EvidenceKind.DOCUMENT)
        ledger = EvidenceLedger().with_items([item]).with_items([item])
        assert len(ledger.items) == 1

    def test_diverse_evidence_outranks_one_source(self):
        """Explicit product requirement: 1 DB + 1 PDF + 1 video beats 3 chunks of one PDF."""
        same_pdf = EvidenceLedger().with_items(
            [
                _evidence("a", "src_docs", Modality.DOCUMENT, EvidenceKind.DOCUMENT, "DOC1"),
                _evidence("b", "src_docs", Modality.DOCUMENT, EvidenceKind.DOCUMENT, "DOC1"),
                _evidence("c", "src_docs", Modality.DOCUMENT, EvidenceKind.DOCUMENT, "DOC1"),
            ]
        )
        diverse = EvidenceLedger().with_items(
            [
                _evidence("d", "src_db", Modality.DATABASE, EvidenceKind.DATABASE, "R1"),
                _evidence("e", "src_docs", Modality.DOCUMENT, EvidenceKind.DOCUMENT, "DOC1"),
                _evidence("f", "src_media", Modality.VIDEO, EvidenceKind.VIDEO, "VID1"),
            ]
        )
        assert diverse.diversity() > same_pdf.diversity()

    def test_empty_ledger_has_zero_diversity(self):
        assert EvidenceLedger().diversity() == 0.0

    def test_weight_combines_relevance_and_reliability(self):
        item = _evidence("e", "src", Modality.DOCUMENT, EvidenceKind.DOCUMENT)
        assert item.weight == pytest.approx(0.8 * 0.7)

    def test_stance_filtering(self):
        supporting = _evidence("s", "src", Modality.DOCUMENT, EvidenceKind.DOCUMENT).model_copy(
            update={"stance": EvidenceStance.SUPPORTING}
        )
        against = _evidence("c", "src", Modality.DOCUMENT, EvidenceKind.DOCUMENT).model_copy(
            update={"stance": EvidenceStance.CONTRADICTING}
        )
        ledger = EvidenceLedger().with_items([supporting, against])
        assert [i.evidence_id for i in ledger.by_stance(EvidenceStance.SUPPORTING)] == ["s"]
        assert [i.evidence_id for i in ledger.by_stance(EvidenceStance.CONTRADICTING)] == ["c"]


class TestConfidence:
    @pytest.mark.parametrize(
        "score,label",
        [
            (0.95, ConfidenceLabel.HIGH),
            (0.80, ConfidenceLabel.HIGH),
            (0.60, ConfidenceLabel.MEDIUM),
            (0.40, ConfidenceLabel.LOW),
            (0.10, ConfidenceLabel.INSUFFICIENT),
            (0.0, ConfidenceLabel.INSUFFICIENT),
        ],
    )
    def test_labels_bucket_scores(self, score, label):
        assert ConfidenceLabel.from_score(score) is label
