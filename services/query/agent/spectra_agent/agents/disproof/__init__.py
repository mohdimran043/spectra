"""Disproof Agent - the falsification pass.

Half retrieval, half cognition: ``search_disconfirming_evidence`` chases the
negation of a claim and its competing outcomes across every enabled modality,
and ``DisproofAgent`` drives that probe against the leading claim during the
Brain's disproof phase.  Finding nothing is a result in its own right - a claim
that survived a deliberate attempt to break it - so a clean probe is reported,
never silently dropped.

Switched off with the ``disproof`` deployment flag.
"""

from __future__ import annotations

from .disproof import DisproofAgent
from .tools import DISPROOF_TOOLS, SearchDisconfirmingEvidenceTool

__all__ = ["DISPROOF_TOOLS", "DisproofAgent", "SearchDisconfirmingEvidenceTool"]
