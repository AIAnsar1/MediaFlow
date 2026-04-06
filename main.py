import sys
import os


def run_server():
    import granian
    from granian.constants import Interfaces

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")

    granian.Granian(
        target="app:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        workers=1 if sys.platform == "win32" else 4,
        reload=True,
        reload_paths=["."],  # ← ТОЛЬКО исходники, не storage/logs
    ).serve()


def run_worker():
    import asyncio
    from arq import run_worker as arq_run_worker
    from workers.worker import WorkerSettings

    if sys.platform != "win32":
        import uvloop
        uvloop.install()

    arq_run_worker(WorkerSettings)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["server", "worker"], default="server", nargs="?")
    args = parser.parse_args()

    if args.command == "worker":
        run_worker()
    else:
        run_server()