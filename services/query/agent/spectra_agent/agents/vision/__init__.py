"""Vision Agent - what the pictures show.

Searches ingested images by description, by the OCR text baked into them or by a
reference image, and opens a single stored image by asset id so a citation can
point at the picture itself.  Its tools are declared under ``AgentName.IMAGE``
and run on the GPU, so they queue behind the single GPU slot.

Switched off with the ``image`` deployment flag.
"""

from __future__ import annotations

from .tools import VISION_TOOLS, GetImageTool, SearchImagesTool

__all__ = ["VISION_TOOLS", "GetImageTool", "SearchImagesTool"]
