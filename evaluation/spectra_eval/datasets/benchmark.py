"""Benchmark questions, loaded from the generated corpus's ground truth.

Nothing here hard-codes an identifier: the generator writes the world it built
into ``manifest.json`` and the questions reference it, so re-generating with a
different seed produces a different world in which every question still has a
correct answer.  That is the check that the benchmark tests the *system* rather
than memorised constants.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spectra_config import REPO_ROOT

DEFAULT_DATA_DIRS: tuple[Path, ...] = (
    Path(os.environ.get("SPECTRA_DEMO_DIR", "")) if os.environ.get("SPECTRA_DEMO_DIR") else REPO_ROOT / "demo-data" / "generated",
    REPO_ROOT / "demo-data" / "generated",
    REPO_ROOT / "data" / "demo",
)

# A target names a place in the corpus precisely enough to check a citation.
#   document:DOC7033#page=14 · video:VID003#t=2537-2581 · database:transactions/TX83155
TARGET_KINDS = ("document", "image", "video", "audio", "database", "external")


@dataclass(frozen=True)
class Target:
    """One expected citation, parsed from its `kind:id#qualifier` string."""

    kind: str
    identifier: str
    page: int | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    raw: str = ""

    def matches(self, other: Target, *, seconds_tolerance: float = 30.0) -> bool:
        """Does a produced citation satisfy this expectation?

        Page and timestamp are checked only when the expectation states them, so
        a question that just requires "this document" is not failed by a system
        that also reports the page.
        """
        if self.kind != other.kind or not _same_id(self.identifier, other.identifier):
            return False
        if self.page is not None and other.page is not None and self.page != other.page:
            return False
        if self.start_seconds is not None and other.start_seconds is not None:
            if abs(self.start_seconds - other.start_seconds) > seconds_tolerance:
                return False
        return True

    def key(self) -> str:
        return f"{self.kind}:{self.identifier.lower()}"


def _same_id(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def parse_target(raw: str) -> Target:
    """``document:DOC7033#page=14`` -> Target(kind='document', identifier='DOC7033', page=14)."""
    text = str(raw).strip()
    kind, _, remainder = text.partition(":")
    kind = kind.lower()
    if kind not in TARGET_KINDS:
        # Bare identifiers are treated as documents, the commonest case.
        kind, remainder = "document", text
    identifier, _, qualifier = remainder.partition("#")
    page = start = end = None
    if qualifier.startswith("page="):
        page = _as_int(qualifier[5:])
    elif qualifier.startswith("t="):
        start, end = _as_span(qualifier[2:])
    return Target(
        kind=kind,
        identifier=identifier.strip().strip("/"),
        page=page,
        start_seconds=start,
        end_seconds=end,
        raw=text,
    )


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _as_span(value: str) -> tuple[float | None, float | None]:
    start_raw, _, end_raw = value.partition("-")
    return _as_float(start_raw), _as_float(end_raw)


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class BenchmarkQuestion:
    id: str
    question: str
    category: str
    mode: str = "deep"
    expected_entities: tuple[str, ...] = ()
    expected_targets: tuple[Target, ...] = ()
    expected_conclusion: str = ""
    expected_status: str = "supported"
    notes: str = ""

    @property
    def requires_abstention(self) -> bool:
        return self.expected_status == "insufficient_evidence"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkQuestion:
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            category=str(payload.get("category", "uncategorised")),
            mode=str(payload.get("mode", "deep")),
            expected_entities=tuple(payload.get("expected_entities", ())),
            expected_targets=tuple(parse_target(t) for t in payload.get("expected_targets", ())),
            expected_conclusion=str(payload.get("expected_conclusion", "")),
            expected_status=str(payload.get("expected_status", "supported")),
            notes=str(payload.get("notes", "")),
        )


@dataclass
class Suite:
    name: str
    questions: list[BenchmarkQuestion] = field(default_factory=list)

    def by_category(self) -> dict[str, list[BenchmarkQuestion]]:
        grouped: dict[str, list[BenchmarkQuestion]] = {}
        for question in self.questions:
            grouped.setdefault(question.category, []).append(question)
        return grouped


class GroundTruthMissing(FileNotFoundError):
    """The generated corpus has not been produced yet."""


def _first_existing(candidates: tuple[Path, ...]) -> Path | None:
    for path in candidates:
        if path and path.exists():
            return path
    return None


def data_root() -> Path:
    root = _first_existing(DEFAULT_DATA_DIRS)
    if root is None:
        raise GroundTruthMissing(
            "no generated demo corpus found; run "
            "`PYTHONPATH=demo-data python -m demo_data.generator --out demo-data/generated`"
        )
    return root


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    base = root or data_root()
    path = base / "manifest.json"
    if not path.exists():
        raise GroundTruthMissing(f"no manifest at {path}")
    return json.loads(path.read_text())


def load_questions(root: Path | None = None) -> list[BenchmarkQuestion]:
    base = root or data_root()
    path = base / "expected" / "questions.json"
    if not path.exists():
        raise GroundTruthMissing(f"no question set at {path}")
    payload = json.loads(path.read_text())
    raw = payload if isinstance(payload, list) else payload.get("questions", [])
    return [BenchmarkQuestion.from_dict(item) for item in raw]


def load_suites(root: Path | None = None) -> dict[str, list[BenchmarkQuestion]]:
    """Named suites: the whole set, plus one per category, plus useful slices."""
    questions = load_questions(root)
    suites: dict[str, list[BenchmarkQuestion]] = {"default": questions}
    for question in questions:
        suites.setdefault(question.category, []).append(question)
    suites["retrieval"] = [q for q in questions if q.category.endswith("retrieval")]
    suites["reasoning"] = [
        q
        for q in questions
        if q.category
        in {
            "multi_hop_investigation",
            "temporal_reasoning",
            "contradiction_detection",
            "claim_verification",
            "evidence_sufficiency",
            "abstention",
        }
    ]
    suites["cross_modal"] = [
        q for q in questions if "_to_" in q.category or q.category == "entity_resolution"
    ]
    return {name: qs for name, qs in suites.items() if qs}
