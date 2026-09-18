"""Stored investigations survive the schema change that removed hypotheses.

A schema change must never make previously persisted work unreadable: the
models are `extra="forbid"`, so a pre-change payload would otherwise raise and
500 every route that lists or opens an investigation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from spectra_schemas import InvestigationState
from spectra_storage.mappers import upgrade_investigation_payload

LEGACY = {
    "investigation_id": "inv_legacy",
    "goal": "why did TX83155 fail",
    "mode": "deep",
    "status": "completed",
    # removed in the claim refactor
    "hypotheses": [{"hypothesis_id": "H1", "description": "auth timeout", "confidence": 0.2}],
    "claims": [
        {
            "claim_id": "C1",
            "text": "The authorisation call timed out.",
            "confidence": 0.7,
            "status": "contested",          # retired ClaimStatus value
            "evidence_ids": ["evd_1"],      # now a derived property, not a field
            "supporting_evidence": ["evd_1"],
        }
    ],
    "evidence": {
        "items": [
            {
                "evidence_id": "evd_1",
                "kind": "document",
                "modality": "document",
                "summary": "The pool was exhausted.",
                "hypothesis_ids": [],       # renamed to claim_ids
                "provenance": {
                    "source_id": "src_docs",
                    "modality": "document",
                    "object_uri": "spectra://objects/ab/" + "c" * 64,
                    "locator": {"kind": "document", "document_id": "DOC1", "page": 3},
                },
            }
        ]
    },
    "trace": [
        {
            "step_id": "s1",
            "investigation_id": "inv_legacy",
            "sequence": 1,
            "agent": "hypothesis_engine",   # renamed to claim_builder
            "status": "ok",
        }
    ],
}


class TestLegacyUpgrade:
    def test_the_raw_payload_is_rejected_by_the_current_models(self):
        with pytest.raises(ValidationError):
            InvestigationState.model_validate(LEGACY)

    def test_the_upgraded_payload_validates(self):
        state = InvestigationState.model_validate(upgrade_investigation_payload(LEGACY))
        assert state.investigation_id == "inv_legacy"

    def test_retired_top_level_fields_are_dropped(self):
        assert "hypotheses" not in upgrade_investigation_payload(LEGACY)

    def test_the_retired_agent_name_is_mapped(self):
        state = InvestigationState.model_validate(upgrade_investigation_payload(LEGACY))
        assert state.trace[0].agent.value == "claim_builder"

    def test_a_retired_claim_status_is_mapped(self):
        state = InvestigationState.model_validate(upgrade_investigation_payload(LEGACY))
        assert state.claims[0].status.value == "weak"

    def test_evidence_survives_with_its_provenance(self):
        state = InvestigationState.model_validate(upgrade_investigation_payload(LEGACY))
        item = state.evidence.items[0]
        assert item.evidence_id == "evd_1"
        assert item.provenance.locator.page == 3
        assert item.claim_ids == []

    def test_the_claim_keeps_its_supporting_evidence(self):
        state = InvestigationState.model_validate(upgrade_investigation_payload(LEGACY))
        assert state.claims[0].supporting_evidence == ["evd_1"]
        assert state.claims[0].evidence_ids == ["evd_1"]

    def test_upgrading_does_not_mutate_the_input(self):
        before = dict(LEGACY)
        upgrade_investigation_payload(LEGACY)
        assert LEGACY == before
        assert "hypotheses" in LEGACY

    def test_a_current_payload_passes_through_unchanged(self):
        state = InvestigationState(investigation_id="inv_new", goal="x")
        payload = state.model_dump(mode="json")
        assert InvestigationState.model_validate(upgrade_investigation_payload(payload))
