from __future__ import annotations

import os
import sys


def run_server() -> None:
    import granian
    from granian.constants import Interfaces

    # Логирование настраивается здесь — один раз, до старта сервера
    from app.logging import setup_logging
    setup_logging()

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    workers = int(os.environ.get("WORKERS", 1))

    # runtime_threads — Rust I/O потоков на worker (Granian 2.x).
    # Для async RSGI/ASGI Granian сам подбирает хорошие дефолты,
    # выставляй только если явно замеряешь узкое место.
    runtime_threads = os.environ.get("RUNTIME_THREADS")

    debug = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")

    kwargs = dict(
        target="app.lifecycle:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,  # Litestar — ASGI фреймворк, RSGI не поддерживает
        workers=workers,
        reload=debug,
        websockets=False,
    )
    if runtime_threads is not None:
        kwargs["runtime_threads"] = int(runtime_threads)

    granian.Granian(**kwargs).serve()


def run_worker() -> None:
    from arq import run_worker as arq_run_worker
    from workers.worker import WorkerSettings

    # uvloop даёт ~20% прироста на Linux для arq workers
    if sys.platform != "win32":
        import uvloop
        uvloop.install()

    from app.logging import setup_logging
    setup_logging()

    arq_run_worker(WorkerSettings)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MediaFlow entrypoint")
    parser.add_argument(
        "command",
        choices=["server", "worker"],
        default="server",
        nargs="?",
        help="What to run (default: server)",
    )
    args = parser.parse_args()

    match args.command:
        case "worker":
            run_worker()
        case _:
            run_server()


if __name__ == "__main__":
    main()