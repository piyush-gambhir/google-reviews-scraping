import argparse
import logging
import sys
from pathlib import Path

from . import config
from .db import connect, init_db, reset_status, status_counts


def cmd_init(args: argparse.Namespace) -> int:
    path = init_db()
    print(f"initialized db at {path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest import ingest_file
    result = ingest_file(Path(args.path))
    print(f"inserted={result['inserted']} skipped={result['skipped']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with connect() as conn:
        counts = status_counts(conn)
    if not counts:
        print("(no businesses)")
        return 0
    width = max(len(s) for s in counts)
    for s, n in sorted(counts.items()):
        print(f"{s.ljust(width)}  {n}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .runner import run
    headless = not args.debug if args.debug else args.headless
    result = run(workers=args.workers, limit=args.limit, headless=headless)
    print(
        f"total={result['total']} done={result['done']} "
        f"failed={result['failed']} blocked={result['blocked']} "
        f"reviews_added={result['reviews_added']}"
    )
    return 0 if not result["blocked"] else 2


def cmd_retry(args: argparse.Namespace) -> int:
    with connect() as conn:
        n = reset_status(conn, from_status=args.status, to_status="queued")
        conn.commit()
    print(f"requeued {n} businesses (was status={args.status})")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from .sync import sync
    result = sync(
        raw_targets="\n".join(args.target) if args.target else None,
        sink_uris=args.sink or None,
        headless=not args.debug,
        limit=args.limit,
        retry_blocked=not args.no_retry_blocked,
        only_done=args.only_done,
        include_internal=args.include_internal,
    )
    result.pop("payload", None)
    run = result["run"]
    # Summary goes to stderr: the `-` sink owns stdout, so `sync > out.json`
    # must yield the payload and nothing else.
    print(
        f"targets={result['targets']} requeued={result['requeued']} "
        f"done={run['done']} failed={run['failed']} blocked={run['blocked']} "
        f"reviews_added={run['reviews_added']} "
        f"businesses={result['businesses']} reviews={result['reviews']}",
        file=sys.stderr,
    )
    for dest in result["delivery"]["delivered"]:
        print(f"  -> {dest}", file=sys.stderr)
    for err in result["delivery"]["errors"]:
        print(f"  !! {err}", file=sys.stderr)
    return result["exit_code"]


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve
    return serve(args.port)


def cmd_export(args: argparse.Namespace) -> int:
    from .export import export_businesses, export_combined, export_reviews
    if args.target == "reviews":
        out = export_reviews(args.format)
    elif args.target == "businesses":
        out = export_businesses(args.format)
    elif args.target == "combined":
        out = export_combined("ndjson")
    else:
        print(f"unknown target: {args.target}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="grscraper")
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("ingest")
    sp.add_argument("path", help="CSV (header value[,type]) or newline-delimited file")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("status")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("run")
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--headless", dest="headless", action="store_true", default=True)
    sp.add_argument("--no-headless", dest="headless", action="store_false")
    sp.add_argument("--debug", action="store_true", help="run headed and verbose")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("retry")
    sp.add_argument("--status", choices=["failed", "blocked"], default="failed")
    sp.set_defaults(func=cmd_retry)

    sp = sub.add_parser("export")
    sp.add_argument("target", choices=["reviews", "businesses", "combined"])
    sp.add_argument("--format", choices=["csv", "json", "ndjson"], default="csv")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser(
        "sync",
        help="one-shot: enqueue targets, scrape, deliver to sinks (for schedulers)",
    )
    sp.add_argument(
        "target", nargs="*",
        help="business name, Maps URL or place id; may be `value|type`. "
             "Defaults to $GRS_TARGETS.",
    )
    sp.add_argument(
        "--sink", action="append", default=[],
        help="delivery URI (-, file://, http(s)://, s3://, gs://); repeatable. "
             "Defaults to $GRS_SINKS.",
    )
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--debug", action="store_true", help="run headed")
    sp.add_argument(
        "--no-retry-blocked", action="store_true",
        help="do not requeue previously blocked/failed businesses",
    )
    sp.add_argument(
        "--only-done", action="store_true",
        help="emit only businesses that scraped cleanly",
    )
    sp.add_argument(
        "--include-internal", action="store_true",
        help="keep queue bookkeeping columns (status, retry_count) in the output",
    )
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("serve", help="HTTP mode for Cloud Run services and similar")
    sp.add_argument("--port", type=int, default=None, help="defaults to $PORT, then 8080")
    sp.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
