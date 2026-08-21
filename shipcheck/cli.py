"""CLI: python -m shipcheck worker | run-job <id> | serve"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from shipcheck import __version__
from shipcheck.store import claim_next, load_job, save_job


def drain_once() -> bool:
    job = claim_next()
    if not job:
        return False
    from shipcheck.runner import run_job

    run_job(job)
    return True


def cmd_worker(_args: argparse.Namespace) -> int:
    print(f"shipcheck worker {__version__} draining queue", flush=True)
    while True:
        did = drain_once()
        if not did:
            time.sleep(1.0)
    return 0


def cmd_run_job(args: argparse.Namespace) -> int:
    job = load_job(args.job_id)
    if not job:
        print(f"unknown job_id: {args.job_id}", file=sys.stderr)
        return 2
    if job.get("status") == "queued":
        job["status"] = "running"
        save_job(job)
    from shipcheck.runner import run_job

    done = run_job(job)
    json.dump({"job_id": done["job_id"], "status": done["status"], "error": done.get("error")}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if done.get("status") in ("pass", "needs_review") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    os.environ.setdefault("SHIPCHECK_INLINE_WORKER", "1")
    uvicorn.run(
        "shipcheck.server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shipcheck", description="ShipCheck preview QA")
    p.add_argument("--version", action="version", version=f"shipcheck {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worker", help="drain queued jobs forever")
    w.set_defaults(func=cmd_worker)

    r = sub.add_parser("run-job", help="run a single job id from the disk queue")
    r.add_argument("job_id")
    r.set_defaults(func=cmd_run_job)

    s = sub.add_parser("serve", help="run the HTTP API (inline worker on by default)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8788)
    s.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)
