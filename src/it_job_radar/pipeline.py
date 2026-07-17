"""End-to-end pipeline: collect -> normalize -> store.

Thin orchestration over the library modules, exposed as a small CLI:

    python -m it_job_radar.pipeline collect --sample 300

Collects a bounded, spread sample of offers, normalizes them, writes them to SQLite,
and records dated snapshot metrics (offer count, offers-with-salary) for trends.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from it_job_radar import config, db, normalize
from it_job_radar.collect import theprotocol


def collect_and_store(sample_size: int = config.DEFAULT_SAMPLE_SIZE) -> int:
    """Collect, normalize and store a sample of offers. Returns the count stored."""
    print(f"[collect] fetching up to {sample_size} offers from theprotocol.it ...")
    raw = theprotocol.collect_offers(sample_size=sample_size)
    print(f"[collect] parsed {len(raw)} offers")

    alias_index = normalize.load_tech_aliases()
    normalized = [normalize.normalize_offer(o, alias_index) for o in raw]
    today = date.today().isoformat()

    conn = db.connect()
    try:
        stored = db.write_offers(conn, normalized, today)
        with_salary = sum(
            1 for o in normalized if any(s.get("monthly_from") for s in o["salaries"])
        )
        db.write_snapshot_stat(conn, today, "offer_count", stored)
        db.write_snapshot_stat(conn, today, "offers_with_salary", with_salary)
    finally:
        conn.close()

    print(f"[collect] stored {stored} offers ({with_salary} with salary) -> {config.DB_PATH}")
    return stored


def main(argv: list[str] | None = None) -> None:
    # Windows consoles default to cp1250; force UTF-8 so Polish characters print.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="it-job-radar pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_cmd = sub.add_parser("collect", help="collect + normalize + store offers")
    collect_cmd.add_argument("--sample", type=int, default=config.DEFAULT_SAMPLE_SIZE)
    args = parser.parse_args(argv)

    if args.command == "collect":
        collect_and_store(args.sample)


if __name__ == "__main__":
    main()
