"""Generate a self-contained mini site (GitHub Pages) describing the project + results.

The page explains what it-job-radar is and what it covers, then shows the current
snapshot: top technologies, median salaries per seniority, and work-mode split. Charts
are embedded as base64 so the HTML is standalone.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from it_job_radar import analyze, config, db  # noqa: E402

_DEFAULT_REPORT_PATH = config.PROJECT_ROOT / "reports" / "site" / "index.html"

# --- Chart styling: clean, print-quality matplotlib aligned with the page palette. ---
_ACCENT = "#2563eb"
_ACCENT_LIGHT = "#93c5fd"
_GREEN = "#059669"
_CHART_STYLE = {
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True,
    "grid.color": "#e3e7ee", "grid.linewidth": 0.9,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlecolor": "#1c2430",
    "axes.titlepad": 12, "axes.labelcolor": "#667085", "axes.labelsize": 10.5,
    "text.color": "#1c2430", "xtick.color": "#667085", "ytick.color": "#667085",
    "xtick.labelsize": 9.5, "ytick.labelsize": 9.5, "font.size": 10.5,
    "legend.frameon": False, "legend.fontsize": 9.5,
}
plt.rcParams.update(_CHART_STYLE)


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _bar_chart(labels, values, title, xlabel, color) -> str:
    fig, ax = plt.subplots(figsize=(9, max(3, len(labels) * 0.45)))
    bars = ax.barh(labels[::-1], values[::-1], color=color, height=0.72, zorder=3)
    ax.grid(False)
    ax.grid(True, axis="x")
    ax.bar_label(bars, padding=4, fontsize=8.5, color="#667085")
    ax.margins(x=0.12)
    ax.set(title=title, xlabel=xlabel)
    fig.tight_layout()
    return _fig_to_base64(fig)


def _salary_chart(salary_df) -> str:
    fig, ax = plt.subplots(figsize=(9, 4))
    x = range(len(salary_df))
    ax.bar(x, salary_df["median_to"], color=_ACCENT_LIGHT, width=0.6, zorder=3,
           label="median upper")
    ax.bar(x, salary_df["median_from"], color=_ACCENT, width=0.6, zorder=4,
           label="median lower")
    ax.set_xticks(list(x))
    ax.set_xticklabels(salary_df["seniority"])
    ax.set(title="Median B2B salary per seniority (PLN/month)", ylabel="PLN/month")
    ax.legend()
    fig.tight_layout()
    return _fig_to_base64(fig)


def generate_report(output_path: Path | None = None, conn=None) -> Path:
    """Build the HTML mini site and write it to ``output_path``.

    A ``conn`` can be injected for testing; otherwise a default connection is opened and
    closed here.
    """
    output_path = output_path or _DEFAULT_REPORT_PATH
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        top_tech = analyze.top_technologies(conn, limit=12)
        top_tech_junior = analyze.top_technologies(conn, seniority="junior", limit=8)
        salary = analyze.salary_by_seniority(conn, kind=config.CONTRACT_B2B)
        work_modes = analyze.work_mode_distribution(conn)
        offer_count = len(db.read_table(conn, "offers"))
    finally:
        if own_conn:
            conn.close()

    tech_chart = _bar_chart(
        list(top_tech["technology"]), list(top_tech["offers"]),
        "Most in-demand technologies", "offers", _ACCENT,
    )
    modes_chart = _bar_chart(
        list(work_modes["work_mode"]), list(work_modes["offers"]),
        "Work modes", "offers", _GREEN,
    )
    salary_chart = _salary_chart(salary) if not salary.empty else ""
    junior_tech = ", ".join(top_tech_junior["technology"]) or "n/a"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    salary_block = (
        f'<img src="data:image/png;base64,{salary_chart}" alt="Median salary per seniority">'
        if salary_chart else "<p><em>Not enough salaried offers in this snapshot.</em></p>"
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>it-job-radar — Polish IT job market</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
         -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
         max-width: 860px; margin: 2rem auto; padding: 0 1rem; color: #1c2430; line-height: 1.5; }}
  h1 {{ margin-bottom: 0.2rem; font-weight: 700; letter-spacing: -0.01em; }}
  .sub {{ color: #667085; margin-top: 0; }}
  .card {{ background: #f6f8fa; border-radius: 10px; padding: 1rem 1.2rem; margin: 1.2rem 0; }}
  img {{ max-width: 100%; height: auto; }}
  code {{ background: #eef; padding: 0.1rem 0.3rem; border-radius: 4px; }}
  footer {{ color: #888; font-size: 0.85rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>it-job-radar</h1>
<p class="sub">Polish IT job market — technology trends &amp; salary ranges</p>

<div class="card">
  <strong>What this is.</strong> A data pipeline that collects a sample of Polish IT job
  offers from <a href="https://theprotocol.it">theprotocol.it</a>, normalizes them
  (unifying technology names, seniority levels and currencies), stores them in SQLite,
  and analyses <em>which technologies are in demand</em> and <em>what they pay</em>.
  Snapshot: <strong>{offer_count} offers</strong>. B2B (net) and employment (gross)
  salaries are kept separate.
</div>

<h2>Most in-demand technologies</h2>
<img src="data:image/png;base64,{tech_chart}" alt="Top technologies">
<p>For <strong>junior</strong> roles specifically: <code>{junior_tech}</code>.</p>

<h2>Salaries by seniority</h2>
{salary_block}

<h2>Work modes</h2>
<img src="data:image/png;base64,{modes_chart}" alt="Work modes">

<div class="card">
  <strong>Methodology &amp; limitations.</strong> A bounded, spread sample (not the whole
  base), respecting robots.txt and dropping personal data. Salaries are medians within
  one currency/contract kind; small snapshots and unit edge-cases (hourly rates) can
  skew rare buckets. See the repo's <code>docs/research/data-sources.md</code>.
</div>

<footer>
  Generated {generated} ·
  <a href="https://github.com/P0w3r223/it-job-radar">source on GitHub</a> ·
  Job data © theprotocol.it (Grupa Pracuj), collected respectfully for educational use.
</footer>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    print("wrote", generate_report())
