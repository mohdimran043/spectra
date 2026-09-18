"""`spectra` command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys

from spectra_config import get_settings
from spectra_config.logging import configure_logging, get_logger

log = get_logger(__name__)


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "spectra_api.main:app",
        host=args.host or settings.api_host,
        port=args.port or settings.api_port,
        reload=args.reload,
        log_config=None,
    )
    return 0


def _health(_: argparse.Namespace) -> int:
    async def run() -> int:
        from .container import build_container, shutdown_container

        container = await build_container()
        report = await container.storage.health()
        for name, detail in report.items():
            print(f"{name:12} {detail}")
        if container.gateway is not None:
            status = await container.gateway.status()
            print(f"\nprofile      {status.profile}")
            print(f"gpu          available={status.gpu.available} {status.gpu.detail or ''}")
            for info in status.models:
                print(
                    f"  {info.role.value:14} {info.state.value:11} "
                    f"{info.active_runtime or '-':14} {info.active_model or '-'}"
                )
        if container.degraded:
            print("\nDegraded:")
            for reason in container.degraded:
                print(f"  - {reason}")
        await shutdown_container()
        return 0

    return asyncio.run(run())


def _init_db(_: argparse.Namespace) -> int:
    async def run() -> int:
        from spectra_storage import get_storage

        storage = await get_storage()
        await storage.repository.initialise()
        stats = await storage.repository.stats()
        print(f"schema ready: {stats}")
        return 0

    return asyncio.run(run())


#: Extensions the pipelines know how to handle; anything else is skipped with
#: a line saying so rather than failing the whole run.
INGESTIBLE = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".json",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff",
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg",
}


def _ingest(args: argparse.Namespace) -> int:
    """Ingest every supported file under a path, then report what was indexed."""
    from pathlib import Path

    async def run() -> int:
        from spectra_ingestion import IngestionService

        root = Path(args.path).expanduser().resolve()
        if not root.exists():
            print(f"not found: {root}", file=sys.stderr)
            return 1

        files = sorted(
            candidate
            for candidate in ([root] if root.is_file() else root.rglob("*"))
            if candidate.is_file() and candidate.suffix.lower() in INGESTIBLE
        )
        if not files:
            print(f"nothing ingestible under {root}")
            return 1

        service = await IngestionService.create()
        print(f"ingesting {len(files)} file(s) into source {args.source!r}")
        indexed = failed = 0
        for index, path in enumerate(files, start=1):
            try:
                job = await service.ingest_path(path, args.source)
                job = await service.wait_for_job(job.job_id, timeout=args.timeout)
            except Exception as exc:  # one bad file must not end the run
                failed += 1
                print(f"  [{index}/{len(files)}] FAILED {path.name}: {exc}", file=sys.stderr)
                continue
            indexed += 1
            print(f"  [{index}/{len(files)}] {job.status.value:10} {path.name}")
        print(f"\ndone: {indexed} indexed, {failed} failed")
        return 0 if indexed else 1

    return asyncio.run(run())


def _seed_demo(args: argparse.Namespace) -> int:
    """Ingest the generated demo corpus, so there is something to search."""
    from pathlib import Path

    corpus = Path(args.path or "demo-data/generated").expanduser().resolve()
    if not corpus.exists():
        print(
            f"{corpus} does not exist. Generate it first:\n"
            f"  cd demo-data && {sys.executable} -m demo_data.generate",
            file=sys.stderr,
        )
        return 1
    args.path, args.source = str(corpus), args.source or "src_demo"
    return _ingest(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spectra", description="SPECTRA control CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_serve)

    sub.add_parser("health", help="print component + model health").set_defaults(func=_health)
    sub.add_parser("init-db", help="create the control-plane schema").set_defaults(func=_init_db)

    ingest = sub.add_parser("ingest", help="ingest a file or a folder tree")
    ingest.add_argument("path")
    ingest.add_argument("--source", default="src_uploads", help="source id to file it under")
    ingest.add_argument("--timeout", type=float, default=900.0)
    ingest.set_defaults(func=_ingest)

    seed = sub.add_parser("seed-demo", help="ingest the generated demo corpus")
    seed.add_argument("--path", default=None)
    seed.add_argument("--source", default="src_demo")
    seed.add_argument("--timeout", type=float, default=900.0)
    seed.set_defaults(func=_seed_demo)

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
