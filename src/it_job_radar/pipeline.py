"""End-to-end pipeline: observe -> collect -> normalize -> store.

Thin orchestration over the library modules, exposed as a small CLI:

    python -m it_job_radar.pipeline observe
    python -m it_job_radar.pipeline collect --budget 300 --seed 20260811

The two commands cost very different things (ADR 0003). ``observe`` spends a handful of
requests to record the whole population frame — who is listed today, who is new, who
disappeared. ``collect`` does the same and then spends its bounded page budget on offers
whose attributes are still unknown.

Running ``observe`` daily is enough to build the survival panel; ``collect`` is what fills
in what those offers actually contain.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime

from it_job_radar import config, db, export, normalize, quality, sampling
from it_job_radar.site import build as site_build
from it_job_radar.collect import theprotocol

# The metric whose detail is the working end of the report: the names to curate next.
_COVERAGE_METRIC = "stored_alias_coverage_rate"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _git_sha() -> str | None:
    """Short commit of the code that produced a snapshot — provenance for the manifest."""
    try:
        result = subprocess.run(
            ["git", "-C", str(config.PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _sync_frame(
    conn, entries: list[tuple[str, str]], today: str, context: normalize.Normalization
) -> db.FrameDelta:
    """Record the observation and bring stored data in line with the current rules.

    Every repair here is idempotent, so they run on each observation rather than as one-off
    fixes that can be forgotten: the frame learns which offers we already hold, lost URLs
    are recovered, and offers stored before a classification rule existed get classified.
    """
    delta = db.record_frame(conn, entries, today)
    db.reconcile_fetch_state(conn)
    repaired, _ = db.backfill_offer_urls(conn)
    if repaired:
        print(f"[frame] recovered {repaired} offer URLs from the frame")
    reclassified = _classify_roles(conn, context)
    if reclassified:
        print(f"[frame] role family changed for {reclassified} offers")
    regrouped = _group_vacancies(conn)
    if regrouped:
        print(f"[frame] vacancy key set for {regrouped} offers")
    reresolved, merged = _renormalize_technologies(conn, context)
    if reresolved:
        print(
            f"[frame] alias dictionary re-resolved {reresolved} technology mentions"
            f" ({merged} rows merged into an existing one)"
        )
    return delta


def _classify_roles(conn, context: normalize.Normalization) -> int:
    """Re-derive every offer's role family from the current rules. Returns rows changed.

    Runs over all offers, not only unclassified ones, so improving a rule in the YAML
    repairs offers that were already labelled — otherwise old misclassifications would
    outlive the fix.
    """
    changed = [
        (offer_id, family)
        for offer_id, title, current in db.offer_titles(conn)
        if (family := normalize.classify_role_family(title, context.role_rules)) != current
    ]
    return db.set_role_families(conn, changed) if changed else 0


def _group_vacancies(conn) -> int:
    """Re-derive which job each advert belongs to. Returns rows changed.

    Same reason as ``_classify_roles``: the key is a rule, and a rule that ran once would
    freeze its first version into data collected under it.
    """
    changed = [
        (offer_id, key)
        for offer_id, title, company, current in db.offer_identities(conn)
        if (key := normalize.vacancy_key(title, company)) != current
    ]
    return db.set_vacancy_keys(conn, changed) if changed else 0


def _renormalize_technologies(conn, context: normalize.Normalization) -> tuple[int, int]:
    """Re-resolve stored technologies against the current dictionary. ``(changed, merged)``.

    The counterpart of ``_classify_roles`` for the alias dictionary: adding an alias is what
    fixes the data, not just what improves the next collection. Without this the quality
    layer could report a coverage gap it had no way to close.

    An empty resolution is skipped rather than written: it would blank the technology and
    trip the contract rule that requires the name to be present.
    """
    changed = [
        (rowid, resolved)
        for rowid, raw, current in db.technology_names(conn)
        if (resolved := normalize.normalize_technology(raw, context.tech_aliases))
        and resolved != current
    ]
    return db.set_technologies(conn, changed) if changed else (0, 0)


def _record_quality_metrics(
    conn, snapshot_id: int, today: str, context: normalize.Normalization
) -> None:
    """Write the instrument panel: how much we hold, how curated it is, how thin it gets."""
    for metric, measured in quality.snapshot_metrics(conn, today, context.tech_aliases).items():
        db.write_snapshot_stat(conn, snapshot_id, today, metric, measured.value, measured.detail)


def _record_frame_metrics(conn, snapshot_id: int, today: str, delta: db.FrameDelta) -> None:
    fetched, live = db.coverage(conn, today)
    metrics = {
        "frame_live": delta.live,
        "frame_new": delta.new,
        "frame_disappeared": delta.disappeared,
        "frame_returned": delta.returned,
        "coverage_fetched": fetched,
        "coverage_share": fetched / live if live else 0.0,
    }
    for metric, value in metrics.items():
        db.write_snapshot_stat(conn, snapshot_id, today, metric, value)


def observe(session=None) -> db.FrameDelta:
    """Record one full sitemap observation. Costs a handful of requests, no offer pages."""
    print("[observe] reading the sitemap frame ...")
    entries = theprotocol.fetch_frame(session)
    today = date.today().isoformat()
    context = normalize.load_normalization()

    conn = db.connect()
    try:
        snapshot_id = db.start_snapshot(
            conn, config.SNAPSHOT_OBSERVE, today, _now(), git_sha=_git_sha()
        )
        delta = _sync_frame(conn, entries, today, context)
        _record_frame_metrics(conn, snapshot_id, today, delta)
        # Observation is where the alias repair runs, so it is also where its effect has to
        # be recorded. Measuring only on `collect` would date a curation gain to the next
        # collection, or lose it when collections are sparse.
        _record_quality_metrics(conn, snapshot_id, today, context)
        fetched, live = db.coverage(conn, today)
    finally:
        conn.close()

    print(
        f"[observe] live {delta.live} | new {delta.new} | gone {delta.disappeared} | "
        f"returned {delta.returned} | attributes known for {fetched}/{live}"
    )
    return delta


class DailyBudgetSpent(RuntimeError):
    """Raised when the day's page allowance is already gone."""


def _budget_left_today(conn, today: str, budget: int) -> int:
    """Trim this run's budget to what the day has left, or refuse if the day is spent.

    `MAX_FETCH_BUDGET` bounds one invocation, which is not what the project promises. On
    2026-08-13 seven runs, each individually within the ceiling, fetched 6037 pages against
    a 6530-offer base — the whole base in a day, which is precisely what the guardrail is
    documented to prevent. A ceiling that resets every time it is hit is a tuning knob, not
    a limit, so the accounting is per day and reads the runs already recorded.
    """
    spent = db.fetch_pages_on(conn, today)
    remaining = config.MAX_DAILY_FETCH - spent
    if remaining <= 0:
        raise DailyBudgetSpent(
            f"{spent} pages already fetched today, at the daily limit of "
            f"{config.MAX_DAILY_FETCH}; the frame is still observed, offers are not"
        )
    if budget > remaining:
        print(
            f"[collect] budget trimmed {budget} -> {remaining}: "
            f"{spent} of {config.MAX_DAILY_FETCH} pages already fetched today"
        )
        return remaining
    return budget


def collect_and_store(
    budget: int = config.DEFAULT_FETCH_BUDGET, seed: int | None = None, session=None
) -> int:
    """Observe the frame, fetch a bounded queue of unknown offers, normalize and store."""
    session = session or theprotocol.new_session()
    print("[collect] reading the sitemap frame ...")
    entries = theprotocol.fetch_frame(session)
    today = date.today().isoformat()
    context = normalize.load_normalization()

    conn = db.connect()
    try:
        snapshot_id = db.start_snapshot(
            conn, config.SNAPSHOT_COLLECT, today, _now(),
            seed=seed, budget=budget, git_sha=_git_sha(),
        )
        delta = _sync_frame(conn, entries, today, context)
        budget = _budget_left_today(conn, today, budget)
        state = db.frame_state(conn, today)
        queue = sampling.build_queue(
            new_today=state.new_today,
            backlog=state.backlog,
            fetched_live=state.fetched_live,
            budget=budget,
            seed=seed,
        )
        print(
            f"[collect] queue: {len(queue.inflow)} new (of {queue.inflow_available}), "
            f"{len(queue.backlog)} backlog, {len(queue.audit)} audit"
        )

        raw, outcomes = theprotocol.fetch_offers(queue.entries, session)
        db.mark_fetched(conn, outcomes, today)

        normalized = [normalize.normalize_offer(offer, context) for offer in raw]
        db.write_offers(conn, normalized, today)

        offer_total = len(db.read_table(conn, "offers"))
        with_salary = sum(
            1 for offer in normalized if any(s.get("monthly_from") for s in offer["salaries"])
        )
        failed = sum(1 for _, outcome in outcomes if outcome != config.FETCH_DONE)

        _record_frame_metrics(conn, snapshot_id, today, delta)
        run_metrics = {
            # the database total, not this run's queue size — the two are different
            # questions, and conflating them is what made the old stat read 250 of 314
            "offer_count": offer_total,
            "offers_stored_this_run": len(normalized),
            "offers_with_salary": with_salary,
            "fetch_attempted": len(outcomes),
            "fetch_failed": failed,
            "inflow_capture_rate": queue.inflow_capture_rate,
        }
        for metric, value in run_metrics.items():
            db.write_snapshot_stat(conn, snapshot_id, today, metric, value)
        _record_quality_metrics(conn, snapshot_id, today, context)
    finally:
        conn.close()

    print(
        f"[collect] stored {len(normalized)} offers ({with_salary} with salary), "
        f"{failed} failed | database now holds {offer_total} -> {config.DB_PATH}"
    )
    if queue.inflow_capture_rate < 1.0:
        print(
            f"[collect] WARNING inflow_capture_rate={queue.inflow_capture_rate:.2f} — the "
            "budget is below the daily inflow, so the panel will skew toward long-lived "
            "offers (see ADR 0003)"
        )
    return len(normalized)


def export_dataset(out_dir=None, conn=None) -> dict:
    """Publish the redacted Parquet dataset and its manifest.

    The contract is enforced first: nothing is published from data that fails it.
    """
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        quality.enforce_contract(conn)
        manifest = export.publish(conn, out_dir, git_sha=_git_sha())
    finally:
        if own_conn:
            conn.close()

    coverage = manifest["coverage"]
    print(
        f"[export] {sum(manifest['rows'].values())} rows in "
        f"{len(manifest['rows'])} tables, {manifest['bytes'] / 1024:.0f} kB "
        f"-> {out_dir or config.DATASET_DIR}"
    )
    print(
        f"[export] attributes known for {coverage['attributes_known']}/"
        f"{coverage['offers_listed']} listed offers ({coverage['share']:.1%})"
    )
    return manifest


def quality_report(conn=None) -> list[quality.Violation]:
    """Print the instrument panel and check the contract. Returns any violations found.

    The unmatched-technology list is the working end of this: those strings are what the
    alias dictionary is missing, ranked by how often they cost us.
    """
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        today = date.today().isoformat()
        # Measured live against the dictionary on disk rather than read back from the last
        # run, so an edit to the YAML shows up here immediately — the point of a loop.
        metrics = quality.snapshot_metrics(conn, today)
        print(f"[quality] state on {today}")
        for metric, measured in metrics.items():
            suffix = f"  ({measured.detail})" if metric != _COVERAGE_METRIC and measured.detail else ""
            print(f"  {metric:<30} {measured.value:>8.3f}{suffix}")

        unmatched = metrics[_COVERAGE_METRIC].detail
        if unmatched:
            print("\n[quality] technology names the dictionary missed, most costly first:")
            for item in unmatched.split(", "):
                print(f"  {item}")
            print("  -> add the real ones to data/normalization/tech_aliases.yaml,")
            print("     then run `pipeline observe` to re-resolve what is already stored")

        violations = quality.validate_contract(conn)
        if violations:
            print(f"\n[quality] CONTRACT VIOLATED ({len(violations)}):")
            for violation in violations:
                print(f"  {violation}")
        else:
            print("\n[quality] contract: satisfied")
        return violations
    finally:
        if own_conn:
            conn.close()


def main(argv: list[str] | None = None) -> None:
    # Windows consoles default to cp1250; force UTF-8 so Polish characters print.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="it-job-radar pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("observe", help="record the sitemap frame (presence only, cheap)")
    collect_cmd = sub.add_parser("collect", help="observe, then fetch + store unknown offers")
    collect_cmd.add_argument("--budget", type=int, default=config.DEFAULT_FETCH_BUDGET)
    collect_cmd.add_argument(
        "--seed", type=int, default=None, help="makes the backlog draw reproducible"
    )
    sub.add_parser("quality", help="print quality metrics and check the data contract")
    export_cmd = sub.add_parser("export", help="write the redacted Parquet dataset")
    export_cmd.add_argument("--out", default=None, help=f"defaults to {config.DATASET_DIR}")
    site_cmd = sub.add_parser("site", help="render the published page from the dataset")
    site_cmd.add_argument("--out", default=None, help=f"defaults to {config.PUBLISH_DIR}")
    verify_cmd = sub.add_parser(
        "verify", help="check the published manifest against the data beside it"
    )
    verify_cmd.add_argument("--dataset", default=None, help=f"defaults to {config.DATASET_DIR}")
    args = parser.parse_args(argv)

    if args.command == "observe":
        observe()
    elif args.command == "collect":
        collect_and_store(args.budget, args.seed)
    elif args.command == "quality":
        if quality_report():
            sys.exit(1)  # a violated contract must fail a build, not just print
    elif args.command == "export":
        export_dataset(args.out)
    elif args.command == "site":
        print(f"[site] wrote {site_build.build(args.out)}")
    elif args.command == "verify":
        problems = export.verify(args.dataset)
        for problem in problems:
            print(f"[verify] {problem}")
        if problems:
            sys.exit(1)
        print("[verify] manifest agrees with the published data")


if __name__ == "__main__":
    main()
