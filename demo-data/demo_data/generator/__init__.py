"""SPECTRA demo dataset generator.

``python -m demo_data.generator --seed 42 --scale small --out demo-data/generated``
writes a complete, genuinely indexable enterprise corpus plus the manifest and
the expected answers the evaluation harness reads.
"""

from __future__ import annotations

from .constants import LARGE, MEDIUM, SMALL, SCALES, ScaleProfile
from .manifest import load_manifest
from .pipeline import GenerationResult, generate, resolve_scale
from .world import World, build_world

__all__ = [
    "LARGE",
    "MEDIUM",
    "SCALES",
    "SMALL",
    "GenerationResult",
    "ScaleProfile",
    "World",
    "build_world",
    "generate",
    "load_manifest",
    "resolve_scale",
]
