"""The grounding law: every sentence that asserts something must cite evidence.

The only sentences allowed to carry no citation are *procedural* ones - the
statements SPECTRA makes about its own search ("Insufficient evidence...",
section headings, "Not found: ...").  Everything else is a claim about the
world and must point at an EvidenceItem.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

CITATION = re.compile(r"\[E(\d+)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Sentences about the investigation itself rather than about the evidence.
PROCEDURAL_PREFIXES: tuple[str, ...] = (
    "insufficient evidence",
    "not found:",
    "missing:",
    "what i found",
    "what is missing",
    "note:",
    "sources searched:",
)


def labels_for(evidence_ids: Sequence[str]) -> dict[str, str]:
    """``{'E1': evidence_id, ...}`` in presentation order."""
    return {f"E{index + 1}": evidence_id for index, evidence_id in enumerate(evidence_ids)}


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-• ").strip()
        if not stripped:
            continue
        sentences.extend(part.strip() for part in _SENTENCE_SPLIT.split(stripped) if part.strip())
    return sentences


def is_procedural(sentence: str) -> bool:
    """True for headings and first-person statements about the search itself.

    SPECTRA never asserts a fact about the world in the first person, so "I
    found ... but cannot establish ..." is procedural while any impersonal
    statement is a claim and must be cited.
    """
    lowered = sentence.strip().lower()
    return (
        lowered.endswith(":")
        or lowered.startswith(PROCEDURAL_PREFIXES)
        or lowered.startswith(("i ", "i'"))
    )


def cited_labels(sentence: str, labels: Mapping[str, str]) -> list[str]:
    """Evidence ids cited by ``sentence``, ignoring citations that do not exist."""
    out: list[str] = []
    for number in CITATION.findall(sentence):
        evidence_id = labels.get(f"E{number}")
        if evidence_id and evidence_id not in out:
            out.append(evidence_id)
    return out


def unsupported_sentences(text: str, labels: Mapping[str, str]) -> list[str]:
    """Sentences that assert something without a valid citation."""
    return [
        sentence
        for sentence in split_sentences(text)
        if not is_procedural(sentence) and not cited_labels(sentence, labels)
    ]
