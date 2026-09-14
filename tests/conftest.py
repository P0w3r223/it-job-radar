"""Shared helpers for the guards that sweep the repository rather than the filesystem.

There is exactly one thing here, and it earns a shared home by being the answer to a defect
both sweeps below it walked into independently: a guard that asks the working tree gets an
answer no clone would give. `.venv/` alone carries four Parquet files pyarrow ships as its
own fixtures, and the first edition of `test_notice.py` convicted all four.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked(*patterns: str) -> list[str]:
    """Repository-relative paths git tracks, matching any of the given pathspecs.

    A machine without git cannot answer this, and that is a failure rather than a skip: a
    skip reads as a pass in pytest's summary line, which is how a guard stops running
    without anything turning red.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", *patterns],
            capture_output=True,
            text=True,
        )
    except OSError as exc:  # pragma: no cover - a machine without git
        raise AssertionError(f"git is needed to answer this and is not here: {exc}") from exc
    assert done.returncode == 0, f"git ls-files failed: {done.stderr.strip()}"
    return sorted(one for one in done.stdout.split("\0") if one)
