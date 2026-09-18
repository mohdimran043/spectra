"""The architectural law is enforced, not merely documented.

Expensive per-object media processing belongs to ingestion. If the query path
could call it, query cost would grow with corpus size - which is precisely the
design the whole system is arranged to avoid.
"""

from __future__ import annotations

import pytest
from spectra_ai_core.phase import (
    INGESTION_ONLY,
    QUERY_SAFE,
    ExecutionPhase,
    PhaseViolation,
    current_phase,
    guard,
    ingestion_phase,
    query_phase,
)


class TestCapabilityClassification:
    def test_media_processing_is_ingestion_only(self):
        assert INGESTION_ONLY == {"ocr", "transcribe", "describe_image", "embed_images"}

    def test_cheap_per_call_work_is_query_safe(self):
        assert {"embed_texts", "rerank", "generate"} <= QUERY_SAFE

    def test_the_two_sets_do_not_overlap(self):
        assert not (INGESTION_ONLY & QUERY_SAFE)


class TestGuard:
    async def test_query_phase_refuses_every_ingestion_only_capability(self):
        async with query_phase():
            for capability in sorted(INGESTION_ONLY):
                with pytest.raises(PhaseViolation) as exc:
                    guard(capability)
                assert capability in str(exc.value)

    async def test_query_phase_permits_query_safe_capabilities(self):
        async with query_phase():
            for capability in sorted(QUERY_SAFE):
                guard(capability)  # must not raise

    async def test_ingestion_phase_permits_everything(self):
        async with ingestion_phase():
            for capability in sorted(INGESTION_ONLY | QUERY_SAFE):
                guard(capability)

    def test_unset_phase_permits_everything(self):
        """Library use and tests are unaffected until a caller opts in."""
        assert current_phase() is ExecutionPhase.UNSET
        for capability in sorted(INGESTION_ONLY | QUERY_SAFE):
            guard(capability)

    async def test_the_violation_message_says_what_to_do_instead(self):
        async with query_phase():
            with pytest.raises(PhaseViolation) as exc:
                guard("ocr")
        message = str(exc.value)
        assert "ingestion" in message
        assert "retrieve it instead" in message


class TestPhaseScoping:
    async def test_phase_is_restored_after_the_block(self):
        async with query_phase():
            assert current_phase() is ExecutionPhase.QUERY
        assert current_phase() is ExecutionPhase.UNSET

    async def test_phases_nest_correctly(self):
        async with query_phase():
            async with ingestion_phase():
                assert current_phase() is ExecutionPhase.INGESTION
                guard("ocr")  # permitted in the inner phase
            assert current_phase() is ExecutionPhase.QUERY

    async def test_phase_is_restored_even_when_the_block_raises(self):
        with pytest.raises(ValueError):
            async with query_phase():
                raise ValueError("boom")
        assert current_phase() is ExecutionPhase.UNSET


class TestGatewayEnforcement:
    """The guard is wired into the real gateway, not just available to call."""

    async def test_gateway_ocr_is_refused_during_a_query(self, gateway):
        async with query_phase():
            with pytest.raises(PhaseViolation):
                await gateway.ocr(b"not-really-an-image")

    async def test_gateway_transcribe_is_refused_during_a_query(self, gateway):
        async with query_phase():
            with pytest.raises(PhaseViolation):
                await gateway.transcribe("/nonexistent.wav")

    async def test_gateway_describe_image_is_refused_during_a_query(self, gateway):
        async with query_phase():
            with pytest.raises(PhaseViolation):
                await gateway.describe_image(b"not-really-an-image")

    async def test_gateway_embed_images_is_refused_during_a_query(self, gateway):
        async with query_phase():
            with pytest.raises(PhaseViolation):
                await gateway.embed_images([b"not-really-an-image"])

    async def test_embedding_a_query_string_is_still_allowed(self, gateway):
        async with query_phase():
            result = await gateway.embed_texts(["why did the transaction fail"], is_query=True)
        assert result.dimension > 0
