"""`python -m spectra_eval.runners` - run a benchmark suite from the CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from spectra_config import get_settings
from spectra_config.logging import configure_logging

from ..baselines import BASELINES
from ..datasets.benchmark import GroundTruthMissing, load_suites
from .runner import BenchmarkRunner


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="spectra_eval.runners", description="Run a SPECTRA benchmark")
    parser.add_argument("--suite", default="default")
    parser.add_argument("--baselines", default=",".join(BASELINES))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list", action="store_true", help="list suites and baselines, then exit")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    from spectra_api.container import build_container, shutdown_container

    container = await build_container()
    try:
        runner = BenchmarkRunner(container)
        payload = await runner.run(
            suite=args.suite,
            baselines=[b.strip() for b in args.baselines.split(",") if b.strip()],
            limit=args.limit,
        )
    finally:
        await shutdown_container()

    for baseline, data in payload["summary"].items():
        overall = data["overall"]
        print(
            f"  {baseline:16} success={overall['investigation_success']:.3f} "
            f"recall@10={overall['recall@10']:.3f} claim_support={overall['claim_support']:.3f} "
            f"wrongly_answered={overall['wrongly_answered']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.list:
        try:
            suites = load_suites()
        except GroundTruthMissing as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"suites": {k: len(v) for k, v in sorted(suites.items())},
                          "baselines": sorted(BASELINES)}, indent=2))
        return 0

    try:
        return asyncio.run(_run(args))
    except GroundTruthMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
