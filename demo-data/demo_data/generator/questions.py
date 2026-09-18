"""Assembly and validation of the benchmark suite.

The suite is validated at generation time: every category the specification
names must be present with at least :data:`MIN_PER_CATEGORY` questions, ids
must be unique, and no expected target may point at something that was not
generated.  A broken suite fails the generator rather than the benchmark run.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from spectra_config.logging import get_logger

from .expected import CorpusIndex, ExpectedQuestion
from .questions_reasoning import (
    abstention,
    claim_verification,
    conflicting_sources,
    entity_resolution,
    multi_hop,
    sufficiency,
    temporal,
)
from .questions_retrieval import (
    audio_questions,
    cross_document,
    database_questions,
    database_to_video,
    image_questions,
    image_to_database,
    single_source,
    video_questions,
    video_to_document,
)
from .world import World

log = get_logger(__name__)

MIN_PER_CATEGORY: Final[int] = 3

REQUIRED_CATEGORIES: Final[tuple[str, ...]] = (
    "single_source_retrieval",
    "cross_document_retrieval",
    "image_retrieval",
    "video_retrieval",
    "audio_retrieval",
    "database_reasoning",
    "image_to_database",
    "database_to_video",
    "video_to_document",
    "entity_resolution",
    "multi_hop_investigation",
    "temporal_reasoning",
    "conflicting_sources",
    "claim_verification",
    "evidence_sufficiency",
    "abstention",
)

_BUILDERS = (
    single_source,
    cross_document,
    image_questions,
    video_questions,
    audio_questions,
    database_questions,
    image_to_database,
    database_to_video,
    video_to_document,
    entity_resolution,
    multi_hop,
    temporal,
    conflicting_sources,
    claim_verification,
    sufficiency,
    abstention,
)


class SuiteValidationError(RuntimeError):
    """Raised when the generated suite does not satisfy the specification."""


def _known_targets(index: CorpusIndex) -> set[str]:
    known = {f"document:{document.document_id}" for document in index.documents}
    known |= {f"image:{image.image_id}" for image in index.images}
    known |= {f"video:{video.video_id}" for video in index.videos}
    known |= {f"audio:{clip.audio_id}" for clip in index.audio}
    return known


def _validate(questions: Sequence[ExpectedQuestion], index: CorpusIndex) -> None:
    identifiers = [question.id for question in questions]
    duplicates = {value for value in identifiers if identifiers.count(value) > 1}
    if duplicates:
        raise SuiteValidationError(f"duplicate question ids: {sorted(duplicates)}")
    counts: dict[str, int] = {}
    for question in questions:
        counts[question.category] = counts.get(question.category, 0) + 1
    missing = [category for category in REQUIRED_CATEGORIES if counts.get(category, 0) < MIN_PER_CATEGORY]
    if missing:
        raise SuiteValidationError(
            f"categories below {MIN_PER_CATEGORY} questions: {missing} (have {counts})"
        )
    unexpected = sorted(set(counts) - set(REQUIRED_CATEGORIES))
    if unexpected:
        raise SuiteValidationError(f"unknown categories emitted: {unexpected}")
    known = _known_targets(index)
    for question in questions:
        for target in question.expected_targets:
            head = target.split("#", 1)[0]
            if head.startswith("database:"):
                continue
            if head not in known:
                raise SuiteValidationError(
                    f"question {question.id} targets {target!r}, which was not generated"
                )


def build_questions(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    """Build every category's questions and validate the assembled suite."""
    questions: list[ExpectedQuestion] = []
    for builder in _BUILDERS:
        questions.extend(builder(world, index))
    suite = tuple(questions)
    _validate(suite, index)
    log.info("demo_data.suite_built", questions=len(suite), categories=len(REQUIRED_CATEGORIES))
    return suite
