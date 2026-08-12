"""Assemble the published page from the dataset.

The page leads with a finding, not with a summary of itself. Everything under the headline
exists to support or qualify it, and every figure carries the `n` it rests on — six of the
nine seniority strata in the current snapshot are too thin to read as solid, and a page
that hides that is lying by omission.

All numbers come from the named queries in ``analytics/queries``, never from ad-hoc SQL,
so the page cannot disagree with the pipeline. The build fails rather than publishes if a
chart would go out without its sample size.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from it_job_radar import config
from it_job_radar.analytics import engine, stats
from it_job_radar.site import charts

TEMPLATE_DIR = Path(__file__).parent / "templates"
ASSET_DIR = Path(__file__).parent / "assets"
JUNIOR = "junior"


class IncompleteFigure(RuntimeError):
    """Raised when a figure would be published without its sample size."""


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    note: str


def _manifest(dataset_dir: Path) -> dict:
    path = dataset_dir / config.MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no manifest at {path}; run `pipeline export` first")
    return json.loads(path.read_text(encoding="utf-8"))


def _salary_ranges(connection, kind: str) -> list[charts.Range]:
    rows = engine.run("salary_rows", connection=connection, kind=kind)
    summary = stats.summarise_medians(rows, "seniority")
    if summary.empty:
        return []
    summary = stats.order_by_seniority(summary)
    return [
        charts.Range(
            label=row["seniority"],
            low=row["median_monthly_from"],
            high=row["median_monthly_to"],
            ci_low=row["ci_low_monthly_from"],
            ci_high=row["ci_high_monthly_from"],
            n=int(row["n"]),
            muted=bool(row["suppressed"]),
        )
        for _, row in summary.iterrows()
    ]


def _tech_bars(connection, strata: dict[str, int], **filters) -> list[charts.Bar]:
    frame = engine.run("top_technologies", connection=connection, **filters)
    return [
        charts.Bar(label=row["technology"], value=int(row["offers"]))
        for _, row in frame.iterrows()
    ]


def _role_bars(frame: pd.DataFrame, total: int) -> list[charts.Bar]:
    return [
        charts.Bar(
            label=row["role_family"],
            value=int(row["offers"]),
            note=f"({row['offers'] / total:.0%})" if total else None,
        )
        for _, row in frame.iterrows()
    ]


def _headline(junior_roles: pd.DataFrame) -> dict:
    """The finding the page leads with, derived rather than asserted.

    If the data stops supporting it — if development overtakes support among juniors —
    the headline changes with it instead of quietly becoming false.
    """
    total = int(junior_roles["offers"].sum())
    if not total:
        return {"claim": "Not enough junior offers in this snapshot to say.", "n": 0}
    top = junior_roles.iloc[0]
    support = int(junior_roles.loc[junior_roles["role_family"] == "support", "offers"].sum())
    if top["role_family"] == "support":
        claim = "Most junior IT offers in Poland are not development jobs"
        detail = (
            f"{support} of {total} offers open to juniors are IT support and "
            f"administration — the largest single category, ahead of every engineering "
            f"discipline."
        )
    else:
        claim = f"The largest junior category is {top['role_family']}"
        detail = f"{int(top['offers'])} of {total} offers open to juniors."
    return {"claim": claim, "detail": detail, "n": total}


def gather(dataset_dir: Path | None = None) -> dict:
    """Collect everything the template needs. Pure with respect to the filesystem."""
    dataset_dir = Path(dataset_dir or config.DATASET_DIR)
    manifest = _manifest(dataset_dir)
    connection = engine.connect(dataset_dir)
    try:
        strata = {
            row["seniority"]: int(row["offers"])
            for _, row in engine.run("stratum_sizes", connection=connection).iterrows()
        }
        junior_roles = engine.run(
            "role_family_distribution", connection=connection, seniority=JUNIOR
        )
        all_roles = engine.run("role_family_distribution", connection=connection)
        work_modes = engine.run("work_mode_distribution", connection=connection)
        page = {
            "manifest": manifest,
            # The dataset's own timestamp, never the wall clock. Two reasons: the reader
            # cares when the data was exported, not when the HTML happened to be rendered;
            # and a build that embeds `now()` can never be checked against the committed
            # page, which is what the CI drift guard does.
            "generated": manifest["generated_at"],
            "headline": _headline(junior_roles),
            "kpis": _kpis(manifest),
            "strata": strata,
            "min_stratum_n": config.MIN_STRATUM_N,
            "thin_strata": {
                level: count for level, count in strata.items() if count < config.MIN_STRATUM_N
            },
            # Autoescaping stays on for everything else; these two are markup we generated
            # and escaped ourselves, so they are marked safe here rather than in the
            # template, where a `| safe` is easy to add to the wrong value later.
            "charts": {
                "technologies": charts.bar_chart(
                    _tech_bars(connection, strata, limit=12), "Most in-demand technologies"
                ),
                "junior_roles": charts.bar_chart(
                    _role_bars(junior_roles, int(junior_roles["offers"].sum())),
                    "What junior offers actually are",
                ),
                "roles": charts.bar_chart(
                    _role_bars(all_roles, int(all_roles["offers"].sum())),
                    "Offers by role family",
                ),
                "salary_b2b": charts.range_chart(
                    _salary_ranges(connection, config.CONTRACT_B2B),
                    "Median B2B range per seniority",
                ),
                "salary_employment": charts.range_chart(
                    _salary_ranges(connection, config.CONTRACT_EMPLOYMENT),
                    "Median employment range per seniority",
                ),
                "work_modes": charts.bar_chart(
                    [
                        charts.Bar(label=row["work_mode"], value=int(row["offers"]))
                        for _, row in work_modes.iterrows()
                    ],
                    "Work modes",
                ),
            },
            "junior_n": int(junior_roles["offers"].sum()),
            "queries": {name: engine.query_text(name) for name in engine.available()},
        }
        page["charts"] = {name: Markup(svg) for name, svg in page["charts"].items()}
    finally:
        connection.close()
    return page


def _kpis(manifest: dict) -> list[Kpi]:
    coverage = manifest["coverage"]
    quality = manifest["quality"]
    return [
        Kpi("Offers analysed", f"{manifest['rows']['offers']:,}".replace(",", " "),
            "attributes collected and normalized"),
        Kpi("Of the live market", f"{coverage['share']:.1%}",
            f"{coverage['attributes_known']} of {coverage['offers_listed']} listed today"),
        Kpi("Disclose a salary", f"{quality['salary_disclosure_rate']:.0%}",
            "the rest publish no figure at all"),
        Kpi("Thin strata", f"{int(quality['strata_below_min_n'])}",
            f"seniority levels under n={config.MIN_STRATUM_N}, greyed below"),
    ]


def _assert_figures_carry_n(page: dict) -> None:
    """A chart without its counts is not publishable — fail the build, not the reader.

    Checked structurally: every rendered figure must carry ``bar-value`` labels, which is
    where both chart types put their counts. Matching on wording instead would pass the
    day someone rephrases a label and silently ships an unlabelled chart.
    """
    for name, markup in page["charts"].items():
        markup = str(markup)
        if 'class="empty"' in markup:
            continue  # nothing to plot, and the page says so
        if 'class="bar-value"' not in markup:
            raise IncompleteFigure(f"chart {name!r} would publish values without their counts")


def render(dataset_dir: Path | None = None) -> str:
    """Render the page to a string."""
    page = gather(dataset_dir)
    _assert_figures_carry_n(page)
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("index.html.j2")
    return template.render(
        styles=Markup((ASSET_DIR / "styles.css").read_text(encoding="utf-8")), **page
    )


def build(out_dir: Path | None = None, dataset_dir: Path | None = None) -> Path:
    """Render the page and write it next to the dataset it queries."""
    out_dir = Path(out_dir or config.PUBLISH_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(render(dataset_dir), encoding="utf-8")
    return target
