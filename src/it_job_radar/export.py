"""Write the analytical dataset the site queries — redacted by design (ADR 0002).

The published artifact is derived, not a copy: titles, employer names and offer URLs never
leave this machine, and ``offer_id`` becomes a salted hash. What remains answers *market*
questions — what is in demand, what it pays, where, on what contract — and cannot answer
*listing* questions like who is hiring or where to apply. That boundary is enforced here,
in one place, and asserted by a test rather than left to reviewer vigilance.

The hash is stable across snapshots, so an offer can still be followed over time.

Parquet rather than JSON or CSV because the browser reads it column by column: the page
downloads one file and runs real SQL against it (ADR 0001).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from it_job_radar import config, db, migrations, quality
from it_job_radar.analytics import history


class ArtifactTooLarge(RuntimeError):
    """Raised when the published dataset exceeds its size budget."""


# The one table written twice per publication: a run cannot appear in the dataset its own
# metrics are measured from until they have been measured. See `_record_series`.
SERIES_TABLE = "snapshot_dimension_metrics"


def hash_offer_id(offer_id: str) -> str:
    """Salted, truncated digest of an offer id — stable across snapshots, not reversible.

    The salt lives in the repository. The goal is to make the artifact useless as a
    job-board substitute, not to withstand a determined adversary; claiming otherwise
    would be security theatre.
    """
    digest = hashlib.sha256(f"{config.EXPORT_ID_SALT}:{offer_id}".encode())
    return digest.hexdigest()[: config.EXPORT_ID_LENGTH]


def redact(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop what must never be published and what was never meant to be, and hash the id.

    Two different reasons, applied in one place: `REDACTED_COLUMNS` would make the artifact
    a substitute for the source, and `INTERNAL_COLUMNS` are the pipeline's own bookkeeping —
    published they would put un-normalized source text into a dataset that promises
    normalized attributes.
    """
    out = frame
    # The vacancy key is built from the title and the company, so publishing it would
    # republish both. Hashed with the same salt as the offer id it stays a grouping key —
    # which is all the analysis needs — without carrying the text it was built from.
    if "vacancy_key" in out.columns:
        out = out.assign(vacancy_id=out["vacancy_key"].map(hash_offer_id, na_action="ignore"))
    excluded = (*config.REDACTED_COLUMNS, *config.INTERNAL_COLUMNS)
    out = out.drop(columns=[c for c in excluded if c in out.columns])
    if "offer_id" in out.columns:
        out = out.assign(offer_id=out["offer_id"].map(hash_offer_id, na_action="ignore"))
    return out


def write_dataset(
    conn: sqlite3.Connection, out_dir: Path | None = None
) -> dict[str, int]:
    """Write every dataset table to ``out_dir`` as redacted Parquet. Returns row counts."""
    out_dir = Path(out_dir or config.DATASET_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for table in config.DATASET_TABLES:
        counts[table] = _write_table(conn, table, out_dir)
    return counts


def _write_table(conn: sqlite3.Connection, table: str, out_dir: Path) -> int:
    """Write one table as redacted Parquet. Returns the rows published."""
    frame = redact(db.read_table(conn, table))
    frame.to_parquet(out_dir / f"{table}.parquet", index=False)
    return len(frame)


def dataset_bytes(out_dir: Path) -> int:
    """Total size of the published files — what a reader actually downloads."""
    return sum(path.stat().st_size for path in out_dir.glob("*.parquet"))


def verify(dataset_dir: Path | None = None) -> list[str]:
    """Check the manifest against the files beside it. Returns readable mismatches.

    The one path the drift guard cannot see: the page is rebuilt *from* the manifest, so a
    stale or hand-edited manifest reproduces itself — page and manifest agree while both
    describe data the parquet does not contain.
    """
    dataset_dir = Path(dataset_dir or config.DATASET_DIR)
    manifest_path = dataset_dir / config.MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"no manifest at {manifest_path}"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for table, expected in (manifest.get("rows") or {}).items():
        parquet = dataset_dir / f"{table}.parquet"
        if not parquet.is_file():
            problems.append(f"{table}: manifest claims {expected} rows, file is missing")
            continue
        actual = len(pd.read_parquet(parquet))
        if actual != expected:
            problems.append(f"{table}: manifest claims {expected} rows, file holds {actual}")

    size = dataset_bytes(dataset_dir)
    if manifest.get("bytes") != size:
        problems.append(f"bytes: manifest claims {manifest.get('bytes')}, files total {size}")
    return problems


def build_manifest(
    conn: sqlite3.Connection,
    counts: dict[str, int],
    size_bytes: int,
    git_sha: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Describe the artifact well enough that a reader can judge it without asking.

    Provenance (which commit, which snapshot, how fresh), scale (rows, bytes), measured
    trustworthiness (the quality metrics), and what was deliberately removed. A figure on
    the page can be traced back through this to the run that produced it.
    """
    snapshot = db.latest_snapshot(conn)
    observed_date = snapshot[2] if snapshot else None
    frame_size, with_attributes = 0, 0
    if observed_date:
        with_attributes, frame_size = db.coverage(conn, observed_date)

    metrics = quality.snapshot_metrics(conn, observed_date) if observed_date else {}
    return {
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "schema_version": migrations.SCHEMA_VERSION,
        "snapshot": {
            "id": snapshot[0], "kind": snapshot[1], "observed_date": snapshot[2],
            "started_at": snapshot[3],
        } if snapshot else None,
        "coverage": {
            "offers_listed": frame_size,
            "attributes_known": with_attributes,
            "share": round(with_attributes / frame_size, 4) if frame_size else 0.0,
        },
        "rows": counts,
        "bytes": size_bytes,
        "quality": {name: round(m.value, 4) for name, m in metrics.items()},
        "redaction": {
            "columns": list(config.REDACTED_COLUMNS),
            "offer_id": (
                "salted sha256, truncated, stable across snapshots. Pseudonymised, not "
                "anonymised: the salt is in the public repository and the id space is "
                "enumerable from the source's sitemap, so this breaks casual joins "
                "rather than resisting a determined reader. vacancy_id hashes title and "
                "company, which are themselves withheld — the same caveat applies."
            ),
            "note": (
                "Derived analytical data. It answers market questions and deliberately "
                "cannot answer listing questions (who is hiring, where to apply)."
            ),
        },
        "source": {
            "name": config.SOURCE_NAME,
            "url": config.SOURCE_URL,
            "attribution": config.ATTRIBUTION,
        },
    }


def _record_series(conn: sqlite3.Connection, out_dir: Path, counts: dict[str, int]) -> int:
    """Measure this run's per-dimension metrics from the dataset just written, and store them.

    Two phases rather than one, because the measurement's own input is the published data:
    the tables go out, the named queries run over them, the resulting points are written to
    the system of record, and the series table alone is republished so the run appears in
    the artifact it produced. Measuring against SQLite instead would avoid the second write
    and cost a second definition of every metric — a trade this project has already refused.

    Silently does nothing when no run has been recorded, which is the case in tests that
    publish a bare database: a point with no snapshot has no date and no provenance.
    """
    snapshot = db.latest_snapshot(conn)
    if snapshot is None:
        return 0
    snapshot_id, _, observed_date, _ = snapshot
    rows = history.measure(dataset_dir=out_dir)
    db.write_dimension_metrics(conn, snapshot_id, observed_date, rows)
    counts[SERIES_TABLE] = _write_table(conn, SERIES_TABLE, out_dir)
    return len(rows)


def publish(
    conn: sqlite3.Connection, out_dir: Path | None = None, git_sha: str | None = None
) -> dict:
    """Write the dataset and its manifest, refusing to publish an oversized artifact."""
    out_dir = Path(out_dir or config.DATASET_DIR)
    counts = write_dataset(conn, out_dir)
    _record_series(conn, out_dir, counts)
    size_bytes = dataset_bytes(out_dir)
    if size_bytes > config.MAX_ARTIFACT_BYTES:
        raise ArtifactTooLarge(
            f"dataset is {size_bytes} bytes, over the "
            f"{config.MAX_ARTIFACT_BYTES} budget — the page would make readers download it"
        )

    manifest = build_manifest(conn, counts, size_bytes, git_sha=git_sha)
    (out_dir / config.MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest
