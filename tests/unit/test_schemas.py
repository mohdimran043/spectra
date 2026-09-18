"""Contract tests for the shared schema package."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from spectra_schemas import (
    DocumentLocator,
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
