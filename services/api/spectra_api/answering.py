"""One short answer, grounded in the results that were actually retrieved.

This is the generation half of retrieval-augmented generation, and it is
deliberately small. It takes the hits search already found, asks the model to
answer from those excerpts and nothing else, then verifies every sentence it
gets back carries a citation to one of them. A sentence without a citation is
dropped rather than published.

Two rules keep it honest:

* **No hits, no answer.** Search decides whether anything matched; this module
  never invents a reason to speak when it did not.
* **Nothing but the excerpts.** The model is given the retrieved text and the
  question. It is not given the corpus, the internet or its own recollection.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import ModelRole, SearchHit

log = get_logger(__name__)

#: How many hits are offered to the model. Beyond this a reader cannot check the
#: citations, which is the only thing that makes the answer worth anything.
MAX_CITED_HITS = 6

#: Answers are a short paragraph, not an essay.
MAX_ANSWER_TOKENS = 400

SYSTEM_PROMPT = (
    "Answer the question from the numbered excerpts and nothing else. "
    "Write at most three sentences. End each sentence with the citation it came "
    "from - [1], or [2][3] - before the full stop. "
    'Example: "The pool was exhausted at 02:03 [1]. No fraud rule fired [3]." '
    "Do not explain your reasoning, restate the excerpts, or describe these "
    "instructions. Output only the finished answer."
)

#: The model is asked for one field. Reasoning models otherwise narrate their
#: working into the answer, and a schema is the only reliable way to stop it.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

_CITATION = re.compile(r"\[(\d+)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
#: A fragment of nothing but citation markers belongs to the sentence before it.
_CITATIONS_ONLY = re.compile(r"^(?:\[\d+\]|[\s,;.)(]|and)+$", re.IGNORECASE)
#: Everything a citation marker is made of, so what is left can be inspected.
_CITATION_MARKUP = re.compile(r"\[\d+\]|[\s,;.)(]")


@dataclass(frozen=True)
class Answer:
    """What the model said, and which hits it is allowed to have said it from."""

    text: str
    citations: list[int] = field(default_factory=list)
    model: str = ""
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def split_sentences(text: str) -> list[str]:
    """The asserting sentences of ``text``.

    A bare run of citations is not a sentence - it is the citation of the
    sentence before it. Treating it as one would make it the only fragment
    carrying a citation, so the grounding check below would drop all the prose
    and publish the markers alone.
    """
    sentences: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-• ").strip()
        if not stripped:
            continue
        for part in _SENTENCE_SPLIT.split(stripped):
            part = part.strip()
            if not part:
                continue
            if sentences and _CITATIONS_ONLY.match(part):
                sentences[-1] = f"{sentences[-1]} {part}"
                continue
            sentences.append(part)
    return sentences


def carries_prose(text: str) -> bool:
    """True when ``text`` asserts something rather than only citing."""
    return bool(_CITATION_MARKUP.sub("", text).strip())


def cited_indexes(sentence: str, available: int) -> list[int]:
    """The 1-based hit numbers a sentence cites, ignoring ones that do not exist."""
    out: list[int] = []
    for raw in _CITATION.findall(sentence):
        index = int(raw)
        if 1 <= index <= available and index not in out:
            out.append(index)
    return out


def ground(text: str, available: int) -> tuple[str, list[int]]:
    """Drop every sentence that asserts something without a valid citation."""
    kept: list[str] = []
    used: list[int] = []
    for sentence in split_sentences(text):
        indexes = cited_indexes(sentence, available)
        if not indexes:
            continue
        kept.append(sentence)
        used.extend(index for index in indexes if index not in used)
    return " ".join(kept), sorted(used)


def excerpts_for(hits: Sequence[SearchHit]) -> str:
    """The numbered evidence block the model is allowed to answer from."""
    lines = []
    for index, hit in enumerate(hits, start=1):
        body = (hit.snippet or hit.text or "").strip().replace("«", "").replace("»", "")
        lines.append(f"[{index}] {body}")
    return "\n".join(lines)


async def answer_from_hits(query: str, hits: Sequence[SearchHit], gateway: Any | None) -> Answer:
    """A short cited answer, or an empty one when nothing can be said."""
    cited = list(hits)[:MAX_CITED_HITS]
    if not cited:
        return Answer(text="", degraded=False)
    if gateway is None:
        return Answer(text="", degraded=True, degraded_reason="no generative runtime available")

    from spectra_ai_core.interfaces import ChatMessage

    try:
        result = await gateway.generate(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=f"Question: {query}\n\nExcerpts:\n{excerpts_for(cited)}",
                ),
            ],
            role=ModelRole.DEEP_BRAIN,
            max_tokens=MAX_ANSWER_TOKENS,
            json_schema=ANSWER_SCHEMA,
        )
    except Exception as exc:  # the answer is optional; the results are not
        log.warning("answer.generation_failed", error=str(exc))
        return Answer(text="", degraded=True, degraded_reason=f"generation failed: {exc}")

    structured = result.structured or {}
    raw = str(structured.get("answer") or result.text or "").strip()
    grounded, used = ground(raw, len(cited))
    if not carries_prose(grounded):
        log.info("answer.dropped_ungrounded", query=query, model=result.model)
        return Answer(
            text="",
            model=result.model,
            degraded=True,
            degraded_reason="the generated answer cited nothing that was retrieved",
        )
    return Answer(
        text=grounded,
        citations=used,
        model=result.model,
        degraded=result.degraded,
        degraded_reason=result.degraded_reason,
    )
