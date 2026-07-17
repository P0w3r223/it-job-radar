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


def _fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _bar_chart(labels, values, title, xlabel, color) -> str:
    fig, ax = plt.subplots(figsize=(9, max(3, len(labels) * 0.4)))
    ax.barh(labels[::-1], values[::-1], color=color)
    ax.set(title=title, xlabel=xlabel)
    fig.tight_layout()
    return _fig_to_base64(fig)


def _salary_chart(salary_df) -> str:
    fig, ax = plt.subplots(figsize=(9, 4))
    x = range(len(salary_df))
    ax.bar(x, salary_df["median_to"], color="#c6dbef", label="median upper")
    ax.bar(x, salary_df["median_from"], color="#4575b4", label="median lower")
    ax.set_xticks(list(x))
    ax.set_xticklabels(salary_df["seniority"])
    ax.set(title="Median B2B salary per seniority (PLN/month)", ylabel="PLN/month")
    ax.legend()
    fig.tight_layout()
    return _fig_to_base64(fig)


def generate_report(output_path: Path | None = None) -> Path:
    """Build the HTML mini site and write it to ``output_path``."""
    output_path = output_path or _DEFAULT_REPORT_PATH
    conn = db.connect()
    try:
        top_tech = analyze.top_technologies(conn, limit=12)
        top_tech_junior = analyze.top_technologies(conn, seniority="junior", limit=8)
        salary = analyze.salary_by_seniority(conn, kind=config.CONTRACT_B2B)
        work_modes = analyze.work_mode_distribution(conn)
        offer_count = len(db.read_table(conn, "offers"))
    finally:
        conn.close()

    tech_chart = _bar_chart(
        list(top_tech["technology"]), list(top_tech["offers"]),
        "Most in-demand technologies", "offers", "#4575b4",
    )
    modes_chart = _bar_chart(
        list(work_modes["work_mode"]), list(work_modes["offers"]),
        "Work modes", "offers", "#5aae61",
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
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto;
         padding: 0 1rem; color: #1a1a1a; line-height: 1.5; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .sub {{ color: #666; margin-top: 0; }}
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
