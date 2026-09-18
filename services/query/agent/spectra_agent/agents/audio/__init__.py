"""Audio Agent - what was said.

Searches transcribed calls, meetings and voice notes; the evidence it returns
carries the audio id, the speaker and the segment offsets, so a quoted line can
always be played back where it was said.

Switched off with the ``audio`` deployment flag.
"""

from __future__ import annotations

from .tools import AUDIO_TOOLS, SearchAudioTool

__all__ = ["AUDIO_TOOLS", "SearchAudioTool"]
