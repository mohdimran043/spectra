"""Top-level generation pipeline.

One call produces the whole dataset: records, the two database emissions, the
documents, the images, the audio, the videos, the expected answers and the
manifest that ties them together.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spectra_config import REPO_ROOT
from spectra_config.logging import get_logger

from .audio import generate_audio
from .constants import DATABASE_DIR, SCALES, ScaleProfile
from .database import default_sqlite_path, emit_database
from .documents import generate_documents
from .expected import CorpusIndex, expected_dir, write_expected
from .images import generate_images
from .manifest import build_manifest, write_manifest
from .questions import build_questions
from .videos import generate_videos
from .world import build_world

log = get_logger(__name__)


class UnknownScaleError(ValueError):
    """Raised when an unknown scale tier is requested."""


@dataclass(frozen=True)
class GenerationResult:
    out_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def counts(self) -> dict[str, int]:
        return dict(self.manifest["counts"])


def resolve_scale(name: str) -> ScaleProfile:
    profile = SCALES.get(name)
    if profile is None:
        raise UnknownScaleError(f"unknown scale {name!r}; choose one of {sorted(SCALES)}")
    return profile


def _prepare(out_dir: Path, clean: bool) -> None:
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def generate(
    *,
    seed: int,
    scale_name: str,
    out_dir: Path,
    sqlite_path: Path | None = None,
    clean: bool = True,
) -> GenerationResult:
    """Generate the whole dataset and return the manifest that describes it."""
    scale = resolve_scale(scale_name)
    _prepare(out_dir, clean)
    world = build_world(seed, scale)
    log.info("demo_data.generation_started", seed=seed, scale=scale.name, out=str(out_dir))

    database = emit_database(
        out_dir / DATABASE_DIR,
        sqlite_path or default_sqlite_path(REPO_ROOT),
        world.data,
    )
    documents = generate_documents(world, out_dir)
    images = generate_images(world, out_dir)
    audio = generate_audio(world, out_dir)
    videos = generate_videos(world, out_dir)

    index = CorpusIndex(documents=documents, images=images, audio=audio, videos=videos)
    questions = build_questions(world, index)
    expected_path = write_expected(expected_dir(out_dir), questions)

    manifest = build_manifest(
        world, database, documents, images, audio, videos, questions, expected_path, out_dir
    )
    manifest_path = write_manifest(out_dir, manifest)
    log.info("demo_data.generation_complete", **manifest["counts"], questions=len(questions))
    return GenerationResult(out_dir=out_dir, manifest_path=manifest_path, manifest=manifest)
