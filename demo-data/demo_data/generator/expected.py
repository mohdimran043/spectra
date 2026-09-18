"""Ground truth: stable target locators and the expected-answer record.

A *target key* is the stable address of one retrievable unit, shared by the
generator and the evaluation harness:

``document:<DOC id>#page=<n>``, ``image:<IMG id>``,
``video:<VID id>#t=<start>-<end>``, ``audio:<AUD id>#t=<start>-<end>``,
``database:<table>#<record id>``.

Ranges are compared by overlap, pages by equality, so a benchmark answer can
be checked without depending on how a baseline chunks the corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .audio import AudioArtifact
from .constants import EXPECTED_DIR
from .docwriters import DocumentArtifact
from .images import ImageArtifact
from .videos import VideoArtifact

QUESTIONS_FILENAME = "questions.json"
TARGETS_README = "README.md"


def document_target(document_id: str, page: int | None = None) -> str:
    return f"document:{document_id}" if page is None else f"document:{document_id}#page={page}"


def image_target(image_id: str) -> str:
    return f"image:{image_id}"


def video_target(video_id: str, span: tuple[float, float] | None = None) -> str:
    if span is None:
        return f"video:{video_id}"
    return f"video:{video_id}#t={span[0]:.2f}-{span[1]:.2f}"


def audio_target(audio_id: str, span: tuple[float, float] | None = None) -> str:
    if span is None:
        return f"audio:{audio_id}"
    return f"audio:{audio_id}#t={span[0]:.2f}-{span[1]:.2f}"


def database_target(table: str, record_id: str) -> str:
    return f"database:{table}#{record_id}"


@dataclass(frozen=True)
class ExpectedQuestion:
    """One benchmark question and everything a correct answer must contain."""

    id: str
    question: str
    category: str
    mode: str
    expected_entities: tuple[str, ...]
    expected_targets: tuple[str, ...]
    expected_conclusion: str
    expected_status: str
    notes: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "question": self.question,
            "category": self.category,
            "mode": self.mode,
            "expected_entities": list(self.expected_entities),
            "expected_targets": list(self.expected_targets),
            "expected_conclusion": self.expected_conclusion,
            "expected_status": self.expected_status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CorpusIndex:
    """Slug-addressed view of everything that was generated."""

    documents: tuple[DocumentArtifact, ...]
    images: tuple[ImageArtifact, ...]
    audio: tuple[AudioArtifact, ...]
    videos: tuple[VideoArtifact, ...]

    def document(self, prefix: str) -> DocumentArtifact:
        return _first(self.documents, prefix, "document")

    def image(self, prefix: str) -> ImageArtifact:
        return _first(self.images, prefix, "image")

    def clip(self, prefix: str) -> AudioArtifact:
        return _first(self.audio, prefix, "audio")

    def video(self, prefix: str) -> VideoArtifact:
        return _first(self.videos, prefix, "video")


def _first(items: Sequence[object], prefix: str, kind: str):
    for item in items:
        if str(getattr(item, "slug", "")).startswith(prefix):
            return item
    raise KeyError(f"no {kind} artifact with slug prefix {prefix!r}")


def write_expected(directory: Path, questions: Sequence[ExpectedQuestion]) -> Path:
    """Write ``expected/questions.json`` plus a short format note."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / QUESTIONS_FILENAME
    categories: dict[str, int] = {}
    for question in questions:
        categories[question.category] = categories.get(question.category, 0) + 1
    payload = {
        "count": len(questions),
        "categories": dict(sorted(categories.items())),
        "questions": [question.as_dict() for question in questions],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    (directory / TARGETS_README).write_text(_readme(), encoding="utf-8")
    return path


def _readme() -> str:
    return (
        "# Expected answers\n\n"
        "`questions.json` is the benchmark ground truth. Every id in it is generated, "
        "never hard-coded: regenerate with a different seed and the ids change while the "
        "questions stay valid.\n\n"
        "## Target key format\n\n"
        "| kind | format |\n"
        "| --- | --- |\n"
        "| document | `document:<DOC id>#page=<n>` (page optional) |\n"
        "| image | `image:<IMG id>` |\n"
        "| video | `video:<VID id>#t=<start>-<end>` |\n"
        "| audio | `audio:<AUD id>#t=<start>-<end>` |\n"
        "| database | `database:<table>#<record id>` |\n\n"
        "Pages must match exactly; time ranges match on overlap.\n"
    )


def expected_dir(out_dir: Path) -> Path:
    return out_dir / EXPECTED_DIR
