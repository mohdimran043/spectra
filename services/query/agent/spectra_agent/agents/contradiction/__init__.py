"""Contradiction Radar - the pairs of evidence that cannot both be true.

Compares the gathered evidence pair by pair and reports the conflicts: opposite
outcomes stated about the same subject, and the same field carrying two
different values.  The deployment's own contradiction service is preferred when
one is wired in; ``contradictions.detect`` is the deterministic fallback that
always works.  An unresolved contradiction is what makes the Verifier refuse a
claim, so this agent is what stops a confident wrong answer.

Always enabled - it reads the ledger and needs no external service.
"""

from __future__ import annotations

from .contradictions import detect
from .tools import CONTRADICTION_TOOLS, DetectContradictionsTool

__all__ = ["CONTRADICTION_TOOLS", "DetectContradictionsTool", "detect"]
