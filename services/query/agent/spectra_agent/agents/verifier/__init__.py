"""Verifier - the gate an answer has to pass.

Runs the mandatory checks on a claim against the evidence actually gathered:
are the entities it names present, do independent sources agree, did the
disproof probe turn up anything that counts against it, and is the evidence
diverse enough to mean anything.  ``verify_claim`` exposes that to the Brain as a tool; the same
``Verifier`` runs in the Brain's verification phase before an answer is
synthesised.

Switched off with the ``verifier`` deployment flag.
"""

from __future__ import annotations

from .tools import VERIFIER_TOOLS, VerifyClaimTool
from .verifier import Verifier

__all__ = ["VERIFIER_TOOLS", "Verifier", "VerifyClaimTool"]
