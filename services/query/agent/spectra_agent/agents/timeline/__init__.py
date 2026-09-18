"""Timeline Builder - what happened, in order.

Takes the dated evidence out of the ledger and puts it on a line, with a
plain-language narrative of the sequence.  The deployment's timeline service is
used when one is wired in; otherwise the events are ordered locally from the
evidence timestamps.  Undated evidence is left out rather than guessed at.

Always enabled - it reads the ledger and needs no external service.
"""

from __future__ import annotations

from .tools import TIMELINE_TOOLS, BuildTimelineTool

__all__ = ["TIMELINE_TOOLS", "BuildTimelineTool"]
