"""Audio Agent tools: search transcribed speech."""

from __future__ import annotations

from spectra_schemas import AgentName, Modality, ToolSpec

from ...tools.base import Tool
from ...tools.modality_search import ModalitySearchTool
from ...tools.schemas import EVIDENCE_OUTPUT, SEARCH_INPUT
from ...tools.timeouts import SEARCH_TEXT_TIMEOUT_SECONDS


class SearchAudioTool(ModalitySearchTool):
    modality = Modality.AUDIO
    spec = ToolSpec(
        name="search_audio",
        description=(
            "Search transcribed audio (calls, meetings, voice notes). Evidence carries "
            "the audio id, speaker and segment offsets."
        ),
        agent=AgentName.AUDIO,
        input_schema=SEARCH_INPUT,
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=SEARCH_TEXT_TIMEOUT_SECONDS,
        requires_flag="audio",
        cost_hint=1.5,
    )


AUDIO_TOOLS: tuple[type[Tool], ...] = (SearchAudioTool,)
