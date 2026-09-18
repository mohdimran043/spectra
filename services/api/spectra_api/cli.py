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

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
