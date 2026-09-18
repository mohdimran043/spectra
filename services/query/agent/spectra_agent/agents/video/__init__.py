"""Video Agent - what the footage shows and says.

Searches scenes, sampled frames and spoken content across ingested video, and
reads back the few seconds around a given offset so a claim can be checked by
watching it.  Retrieval is GPU-bound and queues behind the single GPU slot.

Switched off with the ``video`` deployment flag.
"""

from __future__ import annotations

from .tools import VIDEO_TOOLS, GetVideoTimestampTool, SearchVideosTool

__all__ = ["VIDEO_TOOLS", "GetVideoTimestampTool", "SearchVideosTool"]
