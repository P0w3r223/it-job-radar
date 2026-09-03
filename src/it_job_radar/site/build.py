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
from it_job_radar.analytics import engine, movement, premium, stats
from it_job_radar.site import charts

TEMPLATE_DIR = Path(__file__).parent / "templates"
ASSET_DIR = Path(__file__).parent / "assets"
# The same level the dated series tracks, from one place: a page claiming one seniority
# while the series recorded another would be two answers to one question.
JUNIOR = config.HEADLINE_SENIORITY


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


def _tech_bars(connection, **filters) -> list[charts.Bar]:
    frame = engine.run("top_technologies", connection=connection, **filters)
    return [
        charts.Bar(label=row["technology"], value=int(row["offers"]))
        for _, row in frame.iterrows()
    ]


def _coverage_points(connection) -> tuple[list[charts.Point], float]:
    """The accumulation and the population it is measured against.

    The ceiling is the frame size of the *latest* run rather than the largest ever seen:
    coverage is a share of the market as it stands today, and a base that only ever grew
    would quietly flatter every earlier point.
    """
    frame = engine.run("coverage_over_time", connection=connection)
    if frame.empty:
        return [], 0.0
    points = [
        charts.Point(
            label=row["observed_date"],
            value=float(row["offers_analysed"]),
            fetched=row["kind"] == config.SNAPSHOT_COLLECT,
        )
        for _, row in frame.iterrows()
    ]
    return points, float(frame["offers_listed"].iloc[-1])


def _premium(connection, kind: str) -> tuple[str, dict]:
    """The premium forest for one contract kind, and what it was measured on."""
    fit = premium.estimate(engine.run("salary_premium_rows", connection=connection, kind=kind))
    estimates = [
        charts.Estimate(
            label=item.technology,
            value=item.percent,
            low=item.ci_low,
            high=item.ci_high,
            n=item.n,
            muted=not item.distinguishable,
        )
        for item in fit.premiums
    ]
    waiting = (
        f"No technology is listed by {config.MIN_PREMIUM_N} vacancies disclosing this "
        "contract kind — too few to hold anything level."
    )
    svg = charts.forest_chart(estimates, f"Estimated pay premium, {kind}", waiting)
    return svg, {"vacancies": fit.vacancies, "controls": ", ".join(fit.controls)}


def _pair_bars(connection) -> tuple[list[charts.Bar], int]:
    """Technology pairs by lift, and the population the lift was measured over.

    The bar is the lift and the note is the pair's own count, because neither reads without
    the other: lift says how far from chance, `n` says how much market that covers.
    """
    frame = engine.run("technology_pairs", connection=connection, limit=config.PAIR_LIMIT)
    if frame.empty:
        return [], 0
    bars = [
        charts.Bar(
            label=f"{row['technology_a']} + {row['technology_b']}",
            value=float(row["lift"]),
            value_text=f"{row['lift']:.1f}×",
            note=f"n={int(row['vacancies'])}",
        )
        for _, row in frame.iterrows()
    ]
    return bars, int(frame["analysed_vacancies"].iloc[0])


def _movement(connection) -> tuple[str, dict]:
    """The technology movement panel, and what it is allowed to claim today.

    The panel renders in every state, including the state where it draws nothing: a reader
    who is told "two of the three runs needed, and runs below 90% coverage are not counted"
    knows what is missing, while a section that simply disappears until the data is ready
    looks like a page that never had one.
    """
    comparison = movement.compare(engine.run("technology_movement", connection=connection))
    changes = [
        charts.Change(
            label=move.technology,
            delta=move.delta,
            note=f"{move.first_vacancies} → {move.last_vacancies}",
        )
        for move in comparison.moves
    ]
    context = {
        "movement_days": len(comparison.days),
        "movement_first": comparison.first_day,
        "movement_last": comparison.last_day,
        "movement_min_days": config.MIN_SERIES_POINTS,
        "min_comparable_coverage": config.MIN_COMPARABLE_COVERAGE,
    }
    if comparison.drawable:
        base = comparison.moves[0]
        footer = (
            f"{comparison.first_day} → {comparison.last_day}, share of "
            f"{base.n_first} and {base.n_last} analysed vacancies"
        )
    else:
        footer = ""
    waiting = (
        f"{len(comparison.days)} comparable "
        f"{'run' if len(comparison.days) == 1 else 'runs'} of the "
        f"{config.MIN_SERIES_POINTS} needed — this waits for days, not for offers."
    )
    chart = charts.movement_chart(
        changes, "How each technology's share moved", waiting, footer
    )
    return chart, context


def _role_bars(frame: pd.DataFrame, total: int) -> list[charts.Bar]:
    return [
        charts.Bar(
            label=row["role_family"],
            value=int(row["offers"]),
            note=f"({row['offers'] / total:.0%})" if total else None,
        )
        for _, row in frame.iterrows()
    ]


def _vacancy_count(connection) -> int:
    """Distinct live jobs behind the adverts — the unit every demand figure here counts."""
    return int(
        connection.execute(
            "SELECT COUNT(DISTINCT COALESCE(o.vacancy_id, o.offer_id)) FROM offers o "
            "JOIN sitemap_offers f ON f.offer_id = o.offer_id "
            "  AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)"
        ).fetchdf().iloc[0, 0]
    )


def _headline(junior_roles: pd.DataFrame) -> dict:
    """The finding the page leads with, derived rather than asserted.

    If the data stops supporting it — if development overtakes support among juniors —
    the headline changes with it instead of quietly becoming false.

    The residue families are excluded from the claim but not from the count. "other" is
    what our own rule table failed to match, so leading with it would publish a gap in
    the normalization as a fact about the market; its share is already reported as a
    quality metric and the chart below still shows it. The denominator stays every junior
    offer, and the qualifier weakens to "classified" whenever the residue is the larger
    bucket — the reader is told that a claim about the top family is a claim about the
    part we can name.
    """
    total = int(junior_roles["offers"].sum())
    if not total:
        return {
            "claim": "Not enough junior offers in this snapshot to say.",
            "detail": "No vacancy in this snapshot is open to juniors.",
            "n": 0,
        }
    is_residue = junior_roles["role_family"].isin(config.ROLE_FAMILY_RESIDUE)
    classified = junior_roles[~is_residue]
    if classified.empty:
        return {
            "claim": "No junior offer in this snapshot could be classified",
            "detail": f"All {total} vacancies open to juniors fell outside the rule table.",
            "n": total,
        }
    top = classified.iloc[0]
    residue_max = int(junior_roles.loc[is_residue, "offers"].max()) if is_residue.any() else 0
    rank = (
        "the largest single category"
        if int(top["offers"]) >= residue_max
        else "the largest classified category"
    )
    # "Most … are not development jobs" is a statement about a majority, so it is checked as
    # one. Ranking first among families would not establish it: the development families are
    # fine-grained and could jointly pass half the segment while each stays below support.
    development = int(
        junior_roles.loc[
            junior_roles["role_family"].isin(config.DEVELOPMENT_FAMILIES), "offers"
        ].sum()
    )
    if top["role_family"] == "support" and development * 2 < total:
        claim = "Most junior IT offers in Poland are not development jobs"
        # "and administration" was dropped when the rule table gave network and systems work
        # its own family: support now means the desk and the lines behind it, and the claim
        # has to mean what the family means.
        detail = (
            f"{int(top['offers'])} of {total} vacancies open to juniors are IT support and "
            f"service-desk work — {rank}. Development accounts for {development}."
        )
    else:
        claim = f"The largest junior category is {top['role_family']}"
        detail = (
            f"{int(top['offers'])} of {total} vacancies open to juniors are "
            f"{top['role_family']} work — {rank}."
        )
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
        coverage_points, coverage_ceiling = _coverage_points(connection)
        movement_chart, movement_context = _movement(connection)
        pair_bars, pair_base = _pair_bars(connection)
        premium_b2b, premium_b2b_context = _premium(connection, config.CONTRACT_B2B)
        premium_employment, premium_employment_context = _premium(
            connection, config.CONTRACT_EMPLOYMENT
        )
        page = {
            **movement_context,
            "pair_base": pair_base,
            "min_pair_n": config.MIN_PAIR_N,
            "min_premium_n": config.MIN_PREMIUM_N,
            "premium_b2b": premium_b2b_context,
            "premium_employment": premium_employment_context,
            "manifest": manifest,
            # The dataset's own timestamp, never the wall clock. Two reasons: the reader
            # cares when the data was exported, not when the HTML happened to be rendered;
            # and a build that embeds `now()` can never be checked against the committed
            # page, which is what the CI drift guard does.
            "generated": manifest["generated_at"],
            "headline": _headline(junior_roles),
            "kpis": _kpis(manifest, _vacancy_count(connection)),
            "strata": strata,
            "min_stratum_n": config.MIN_STRATUM_N,
            "max_ci_width": config.MAX_CI_WIDTH_SHARE,
            "vacancy_count": _vacancy_count(connection),
            "thin_strata": {
                level: count for level, count in strata.items() if count < config.MIN_STRATUM_N
            },
            # Autoescaping stays on for everything else; these two are markup we generated
            # and escaped ourselves, so they are marked safe here rather than in the
            # template, where a `| safe` is easy to add to the wrong value later.
            "charts": {
                "technologies": charts.bar_chart(
                    _tech_bars(connection, limit=12), "Most in-demand technologies"
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
                "premium_b2b": premium_b2b,
                "premium_employment": premium_employment,
                "pairs": charts.bar_chart(
                    pair_bars, "Asked together more often than chance", unit="lift"
                ),
                "movement": movement_chart,
                "coverage": charts.accumulation_chart(
                    coverage_points,
                    "Coverage accumulated run by run",
                    reference=coverage_ceiling,
                    reference_label=f"{coverage_ceiling:,.0f}".replace(",", " ") + " listed",
                ),
            },
            "runs_recorded": len(coverage_points),
            "junior_n": int(junior_roles["offers"].sum()),
            "queries": {name: engine.query_text(name) for name in engine.available()},
        }
        page["charts"] = {name: Markup(svg) for name, svg in page["charts"].items()}
    finally:
        connection.close()
    return page


def _disclosure_note(withheld: int) -> str:
    """"The rest publish nothing" stops being true the moment we withhold a figure.

    A salary we refused to convert is not a salary nobody published, and the reader has no
    way to tell the two apart from a percentage alone.
    """
    if not withheld:
        return "the rest publish no figure at all"
    return f"of the rest, {withheld} published one we withheld as a unit error"


def _kpis(manifest: dict, vacancies: int) -> list[Kpi]:
    coverage = manifest["coverage"]
    quality = manifest["quality"]
    return [
        # The live vacancy count, not `rows.offers`: that row count includes adverts the
        # source has since retired and the per-city copies of one job, so it answered a
        # question no figure below it asks (ADR 0004).
        Kpi("Vacancies analysed", f"{vacancies:,}".replace(",", " "),
            "distinct live jobs, attributes collected and normalized"),
        Kpi("Of the live market", f"{coverage['share']:.1%}",
            f"{coverage['attributes_known']} of {coverage['offers_listed']} listed today"),
        Kpi("Disclose a salary", f"{quality['salary_disclosure_rate']:.0%}",
            _disclosure_note(int(quality["salary_monthly_withheld"]))),
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
    # Explicit LF, not the platform's line ending: this file is committed and CI rebuilds it
    # on another OS, so "the page is a function of the dataset" has to hold across both.
    with open(target, "w", encoding="utf-8", newline="\n") as page:
        page.write(render(dataset_dir))
    return target
