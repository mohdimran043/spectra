"""Named constants and scale profiles for the demo dataset generator.

Nothing in the generator hard-codes a magic number: sizes, tiers, rendering
geometry and media parameters are declared once here and read everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

GENERATOR_VERSION: Final[str] = "1.0.0"
MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"
MANIFEST_FILENAME: Final[str] = "manifest.json"

# -- identifier grammars (must match spectra_entity_resolution.patterns) ------
CUSTOMER_PREFIX: Final[str] = "C"
CUSTOMER_DIGITS: Final[int] = 5
TRANSACTION_PREFIX: Final[str] = "TX"
TRANSACTION_DIGITS: Final[int] = 5
INCIDENT_PREFIX: Final[str] = "INC"
INCIDENT_DIGITS: Final[int] = 4
ASSET_PREFIX: Final[str] = "AST"
ASSET_DIGITS: Final[int] = 4
DOCUMENT_PREFIX: Final[str] = "DOC"
DOCUMENT_DIGITS: Final[int] = 4
IMAGE_PREFIX: Final[str] = "IMG"
IMAGE_DIGITS: Final[int] = 4
VIDEO_PREFIX: Final[str] = "VID"
VIDEO_DIGITS: Final[int] = 4
AUDIO_PREFIX: Final[str] = "AUD"
AUDIO_DIGITS: Final[int] = 4

# -- output tree --------------------------------------------------------------
DOCUMENTS_DIR: Final[str] = "documents"
IMAGES_DIR: Final[str] = "images"
VIDEOS_DIR: Final[str] = "videos"
AUDIO_DIR: Final[str] = "audio"
DATABASE_DIR: Final[str] = "database"
EXPECTED_DIR: Final[str] = "expected"

SQLITE_FILENAME: Final[str] = "enterprise.db"
SQL_FILENAME: Final[str] = "enterprise_demo_inserts.sql"
DEFAULT_SQLITE_RELATIVE: Final[str] = "data/runtime/enterprise.db"

# -- narrative sizing (the story tier) ---------------------------------------
STORY_CUSTOMERS: Final[int] = 120
STORY_TRANSACTIONS: Final[int] = 900
STORY_INCIDENTS: Final[int] = 14
STORY_ASSETS: Final[int] = 25

#: Customers deliberately given more than this many failed payments so that
#: "which customers had more than five failed payments" has a correct answer.
FAILED_PAYMENT_THRESHOLD: Final[int] = 5
HIGH_FAILURE_CUSTOMERS: Final[int] = 6
HIGH_FAILURE_MIN: Final[int] = 6
HIGH_FAILURE_MAX: Final[int] = 11

#: Share of the transaction population that fails at all (before the boosted
#: high-failure customers are applied).
BASE_FAILURE_RATE: Final[float] = 0.17

# -- document rendering -------------------------------------------------------
PDF_PAGE_WIDTH: Final[float] = 595.0
PDF_PAGE_HEIGHT: Final[float] = 842.0
PDF_MARGIN: Final[float] = 56.0
PDF_BODY_FONTSIZE: Final[float] = 10.5
PDF_HEADING_FONTSIZE: Final[float] = 15.0
PDF_LINE_HEIGHT: Final[float] = 14.0
INCIDENT_REPORT_PAGES: Final[int] = 16
#: 1-based page of the incident report that carries the true root cause.
INCIDENT_REPORT_KEY_PAGE: Final[int] = 14
RUNBOOK_PAGES: Final[int] = 7
RUNBOOK_KEY_PAGE: Final[int] = 5

# -- image rendering ----------------------------------------------------------
IMAGE_WIDTH: Final[int] = 1280
IMAGE_HEIGHT: Final[int] = 720
IMAGE_MARGIN: Final[int] = 40
FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
MONO_FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
)
BOLD_FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
#: Exactly three database nodes, so "diagrams showing three database nodes"
#: has a single true answer in the corpus.
ARCHITECTURE_DATABASE_NODES: Final[int] = 3

# -- audio synthesis ----------------------------------------------------------
AUDIO_SAMPLE_RATE: Final[int] = 16_000
AUDIO_CHANNELS: Final[int] = 1
AUDIO_SAMPLE_WIDTH_BYTES: Final[int] = 2
AUDIO_PEAK_AMPLITUDE: Final[int] = 9_000
SPEAKER_BASE_FREQUENCIES_HZ: Final[tuple[float, ...]] = (118.0, 168.0, 205.0, 142.0)
SYLLABLE_RATE_HZ: Final[float] = 4.2
INTER_SEGMENT_SILENCE_SECONDS: Final[float] = 0.35
WORDS_PER_SECOND: Final[float] = 2.6
MIN_SEGMENT_SECONDS: Final[float] = 1.8

# -- video synthesis ----------------------------------------------------------
VIDEO_WIDTH: Final[int] = 1280
VIDEO_HEIGHT: Final[int] = 720
VIDEO_FPS: Final[int] = 8
VIDEO_CRF: Final[int] = 30
VIDEO_PRESET: Final[str] = "veryfast"
VIDEO_AUDIO_BITRATE: Final[str] = "48k"
FFMPEG_TIMEOUT_SECONDS: Final[int] = 300

# -- scale tiers --------------------------------------------------------------


@dataclass(frozen=True)
class ScaleProfile:
    """How much filler is generated on top of the narrative corpus."""

    name: str
    documents: int
    images: int
    videos: int
    database_records: int
    filler_document_pages: int


SMALL: Final[ScaleProfile] = ScaleProfile(
    name="small",
    documents=24,
    images=12,
    videos=3,
    database_records=STORY_CUSTOMERS + STORY_TRANSACTIONS + STORY_INCIDENTS + STORY_ASSETS,
    filler_document_pages=2,
)
MEDIUM: Final[ScaleProfile] = ScaleProfile(
    name="medium",
    documents=100,
    images=1_000,
    videos=10,
    database_records=10_000,
    filler_document_pages=2,
)
LARGE: Final[ScaleProfile] = ScaleProfile(
    name="large",
    documents=1_000,
    images=10_000,
    videos=100,
    database_records=100_000,
    filler_document_pages=1,
)

SCALES: Final[dict[str, ScaleProfile]] = {SMALL.name: SMALL, MEDIUM.name: MEDIUM, LARGE.name: LARGE}

#: Filler media are deliberately cheap so the large tier stays feasible.
FILLER_IMAGE_WIDTH: Final[int] = 480
FILLER_IMAGE_HEIGHT: Final[int] = 300
FILLER_VIDEO_SCENES: Final[int] = 2
FILLER_VIDEO_SCENE_SECONDS: Final[float] = 1.5
