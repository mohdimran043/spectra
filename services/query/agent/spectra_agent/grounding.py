"""The grounding law: every sentence that asserts something must cite evidence.

The only sentences allowed to carry no citation are *procedural* ones - the
statements SPECTRA makes about its own search ("Insufficient evidence...",
section headings, "Not found: ...").  Everything else is a claim about the
world and must point at an EvidenceItem.

The second half of the law is *subject* grounding: a claim about TX83155 has to
rest on evidence that names TX83155.  :func:`focal_terms` is what the evidence
admission gate and the claim builder both measure that against, so the two
agree on what the investigation is actually about.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from spectra_schemas import InvestigationState

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


#: A fragment that is nothing but citation markers and punctuation. Models
#: routinely end an answer with one instead of citing each sentence inline.
_CITATIONS_ONLY = re.compile(r"^(?:\[E\d+\]|[\s,;.)(]|and)+$", re.IGNORECASE)


def split_sentences(text: str) -> list[str]:
    """The asserting sentences of ``text``.

    A bare run of citations is not a sentence - it is the citation of the
    sentence before it.  Treating it as one made it the only fragment carrying a
    citation, so the grounding check dropped all the prose and published the
    markers alone.  Such a run is folded back onto the sentence it follows;
    with nothing before it, it stands as-is and fails the check on its own.
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


def focal_terms(state: InvestigationState) -> list[str]:
    """The identifiers this investigation is actually about, lower-cased.

    Built from the detected identifiers first and the resolved entities second,
    so an empty list genuinely means "this question names no subject" rather
    than "the subject has not been resolved yet".
    """
    terms: list[str] = []
    understanding = state.understanding
    if understanding:
        terms.extend(understanding.detected_ids)
    terms.extend(state.entities)
    return [t.strip().lower() for t in terms if t and str(t).strip()]
