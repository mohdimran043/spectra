"""Command line entry point for the demo dataset generator."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from spectra_config import REPO_ROOT, get_settings
from spectra_config.logging import configure_logging, get_logger

from .constants import SCALES
from .database import default_sqlite_path
from .pipeline import GenerationResult, UnknownScaleError, generate

log = get_logger(__name__)

DEFAULT_SEED = 42
DEFAULT_SCALE = "small"
DEFAULT_OUT = "demo-data/generated"
EXIT_OK = 0
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m demo_data.generator",
        description="Generate the SPECTRA synthetic enterprise dataset.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="master seed (default: 42)")
    parser.add_argument(
        "--scale", choices=sorted(SCALES), default=DEFAULT_SCALE, help="dataset tier (default: small)"
    )
    parser.add_argument(
        "--out", type=Path, default=Path(DEFAULT_OUT), help=f"output directory (default: {DEFAULT_OUT})"
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=None,
        help="where to write the enterprise SQLite database (default: data/runtime/enterprise.db)",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="do not wipe the output directory before generating",
    )
    return parser


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    out_dir = _resolve(args.out)
    sqlite_path = _resolve(args.sqlite_path) if args.sqlite_path else default_sqlite_path(REPO_ROOT)
    try:
        result: GenerationResult = generate(
            seed=args.seed,
            scale_name=args.scale,
            out_dir=out_dir,
            sqlite_path=sqlite_path,
            clean=not args.keep_existing,
        )
    except UnknownScaleError as exc:
        parser.error(str(exc))
        return EXIT_ERROR
    except (OSError, RuntimeError, ValueError) as exc:
        log.error("demo_data.generation_failed", error=str(exc), error_type=type(exc).__name__)
        return EXIT_ERROR
    _print_summary(result)
    return EXIT_OK


def _print_summary(result: GenerationResult) -> None:
    manifest = result.manifest
    print(f"manifest: {result.manifest_path}")
    print(f"seed={manifest['seed']} scale={manifest['scale']}")
    for key, value in sorted(result.counts.items()):
        print(f"  {key:<14} {value}")
    print(f"  {'questions':<14} {manifest['expected']['count']}")
    print(f"sqlite: {manifest['database']['sqlite_path']}")


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(run())
