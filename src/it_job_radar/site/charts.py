"""Charts as inline SVG — pure functions from rows to markup.

SVG rather than embedded PNG for three reasons that matter on this page: it inherits the
reader's colour scheme, so dark mode is not a second rendering; it stays sharp at any
size; and its text is real text, so a screen reader and a search engine can both read the
figures.

Every chart here carries its `n`. A chart that cannot say how many offers stand behind it
does not belong on the page.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape

from it_job_radar import config

_WIDTH = 720
_ROW_HEIGHT = 26
_LABEL_WIDTH = 150
_PAD = 12

# Geometry of the accumulation chart, which is plotted rather than laid out in rows.
_SERIES_HEIGHT = 210
_SERIES_LEFT = 58
_SERIES_RIGHT = 96  # room for the label on the final point
_SERIES_TOP = 30
_SERIES_BASELINE = 168


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    note: str | None = None  # e.g. "n=19", rendered next to the value
    muted: bool = False  # a stratum too thin to read as solid


@dataclass(frozen=True)
class Range:
    """One salary range: a median low-to-high span with an interval around the low end."""

    label: str
    low: float
    high: float
    ci_low: float
    ci_high: float
    n: int
    muted: bool = False


@dataclass(frozen=True)
class Point:
    """One recorded run: what had accumulated by then, and whether that run added to it."""

    label: str  # the date the run observed
    value: float
    fetched: bool = False  # a run that spent its page budget, rather than only observing


def _text(value) -> str:
    return escape(str(value), quote=True)


def _thousands(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _svg(width: int, height: int, title: str, body: str) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{_text(title)}" xmlns="http://www.w3.org/2000/svg">'
        f"<title>{_text(title)}</title>{body}</svg>"
    )


def bar_chart(bars: list[Bar], title: str, unit: str = "offers") -> str:
    """Horizontal bars, longest first, each labelled with its value."""
    if not bars:
        return '<p class="empty">No data in this snapshot.</p>'

    largest = max((bar.value for bar in bars), default=1) or 1
    plot_width = _WIDTH - _LABEL_WIDTH - 70
    height = len(bars) * _ROW_HEIGHT + _PAD * 2

    parts = []
    for index, bar in enumerate(bars):
        y = _PAD + index * _ROW_HEIGHT
        width = max(1.0, bar.value / largest * plot_width)
        classes = "bar muted" if bar.muted else "bar"
        note = f" {bar.note}" if bar.note else ""
        parts.append(
            f'<text class="bar-label" x="{_LABEL_WIDTH - 8}" y="{y + 13}" '
            f'text-anchor="end">{_text(bar.label)}</text>'
            f'<rect class="{classes}" x="{_LABEL_WIDTH}" y="{y + 3}" '
            f'width="{width:.1f}" height="{_ROW_HEIGHT - 9}" rx="2"></rect>'
            f'<text class="bar-value" x="{_LABEL_WIDTH + width + 6:.1f}" y="{y + 13}">'
            f"{_thousands(bar.value)}{_text(note)}</text>"
        )
    return _svg(_WIDTH, height, f"{title} ({unit})", "".join(parts))


def accumulation_chart(
    points: list[Point],
    title: str,
    reference: float,
    reference_label: str,
    unit: str = "offers",
    min_points: int = config.MIN_SERIES_POINTS,
) -> str:
    """One accumulating series, with the ceiling it is climbing towards stated in words.

    Four decisions are deliberate.

    The x axis is **ordinal** — one slot per recorded run, evenly spaced — because runs sit
    minutes or days apart and a date axis would draw a rate nobody measured.

    The y axis starts at zero and ends just above the largest value, **not** at the
    population. Scaled to the population this figure is a flat line hugging the axis: at
    10% coverage the whole accumulation is fourteen pixels, and the shape the chart exists
    to show disappears. The distance to the ceiling is therefore carried by text — the
    reference label and the share on the final point — where it can be read exactly instead
    of estimated from a gap. A rising line with "10.3%" printed on its end cannot be
    mistaken for a covered market; a flat line that shows nothing simply fails.

    Below ``min_points`` no line is drawn: a segment between two points asserts something
    about the interval between them, which a two-run series cannot support.

    Only the final point is labelled. A number on every marker would be a table drawn as a
    chart, and the table is already on the page.
    """
    if not points:
        return '<p class="empty">No recorded runs yet.</p>'

    largest = max(point.value for point in points)
    ceiling = largest * 1.12 or 1  # headroom, so the last marker is not clipped by the frame
    plot_width = _WIDTH - _SERIES_LEFT - _SERIES_RIGHT
    step = plot_width / (len(points) - 1) if len(points) > 1 else 0.0

    def x_of(index: int) -> float:
        return _SERIES_LEFT + (index * step if len(points) > 1 else plot_width / 2)

    def y_of(value: float) -> float:
        span = _SERIES_BASELINE - _SERIES_TOP
        return _SERIES_BASELINE - max(0.0, min(1.0, value / ceiling)) * span

    parts = [
        f'<line class="axis-line" x1="{_SERIES_LEFT}" x2="{_SERIES_LEFT + plot_width}" '
        f'y1="{_SERIES_BASELINE}" y2="{_SERIES_BASELINE}"></line>',
        f'<text class="axis" x="{_SERIES_LEFT + plot_width}" y="{_SERIES_TOP - 12}" '
        f'text-anchor="end">of {_text(reference_label)}</text>',
        # No tick for the top of the scale: it is the final point's own value, and the
        # label on that point already states it — twice would be one number too many.
        f'<text class="axis" x="{_SERIES_LEFT - 8}" y="{_SERIES_BASELINE + 4}" '
        f'text-anchor="end">0</text>',
    ]

    if len(points) >= min_points:
        path = " ".join(f"{x_of(i):.1f},{y_of(p.value):.1f}" for i, p in enumerate(points))
        parts.append(f'<polyline class="series" points="{path}"></polyline>')

    seen_labels: set[str] = set()
    for index, point in enumerate(points):
        x, y = x_of(index), y_of(point.value)
        classes = "series-dot" if point.fetched else "series-dot observed"
        parts.append(f'<circle class="{classes}" cx="{x:.1f}" cy="{y:.1f}" r="4"></circle>')
        # One tick per date, not per run: several runs share a day, and repeating the date
        # under each of them reads as several days.
        if point.label not in seen_labels:
            seen_labels.add(point.label)
            parts.append(
                f'<text class="axis" x="{x:.1f}" y="{_SERIES_BASELINE + 18}" '
                f'text-anchor="middle">{_text(point.label)}</text>'
            )

    last = points[-1]
    share = last.value / reference if reference else 0.0
    parts.append(
        f'<text class="bar-value" x="{x_of(len(points) - 1) + 10:.1f}" '
        f'y="{y_of(last.value) + 4:.1f}">'
        f"{_thousands(last.value)} ({share:.1%})</text>"
    )
    note = f"{len(points)} runs" if len(points) != 1 else "1 run"
    drawn = "" if len(points) >= min_points else " — too short for a line, so the points stand alone"
    parts.append(
        f'<text class="axis" x="{_SERIES_LEFT}" y="{_SERIES_HEIGHT - 6}">'
        f"{_text(note)}, {_text(unit)} with attributes collected{_text(drawn)}</text>"
    )
    return _svg(_WIDTH, _SERIES_HEIGHT, f"{title} ({unit})", "".join(parts))


def range_chart(ranges: list[Range], title: str, unit: str = "PLN/month") -> str:
    """Salary ranges as spans, not stacked bars.

    The previous chart drew the median lower and upper bounds as two overlapping bars,
    which reads as a stacked total — inviting the reader to add two numbers that must not
    be added. A span from low to high says what the data actually is, and the thin line
    behind the lower marker is its bootstrap interval: where a small `n` makes the figure
    unreliable, the interval is visibly wide.
    """
    if not ranges:
        return '<p class="empty">No disclosed salaries in this snapshot.</p>'

    candidates = [
        value
        for item in ranges
        for value in (item.high, item.ci_high)
        if value is not None and not math.isnan(value)
    ]
    largest = max(candidates, default=1) or 1
    plot_width = _WIDTH - _LABEL_WIDTH - 90
    height = len(ranges) * (_ROW_HEIGHT + 6) + _PAD * 2 + 18

    def x_of(value: float) -> float:
        return _LABEL_WIDTH + max(0.0, min(1.0, value / largest)) * plot_width

    parts = []
    for index, item in enumerate(ranges):
        y = _PAD + index * (_ROW_HEIGHT + 6) + 12
        classes = "range muted" if item.muted else "range"
        parts.append(
            f'<text class="bar-label" x="{_LABEL_WIDTH - 8}" y="{y + 4}" text-anchor="end">'
            f"{_text(item.label)}</text>"
            f'<line class="ci" x1="{x_of(item.ci_low):.1f}" x2="{x_of(item.ci_high):.1f}" '
            f'y1="{y}" y2="{y}"></line>'
            f'<line class="{classes}" x1="{x_of(item.low):.1f}" x2="{x_of(item.high):.1f}" '
            f'y1="{y}" y2="{y}"></line>'
            f'<circle class="{classes}-dot" cx="{x_of(item.low):.1f}" cy="{y}" r="4"></circle>'
            f'<circle class="{classes}-dot high" cx="{x_of(item.high):.1f}" cy="{y}" r="4">'
            f"</circle>"
            f'<text class="bar-value" x="{x_of(item.high) + 8:.1f}" y="{y + 4}">'
            f"{_thousands(item.low)}–{_thousands(item.high)} (n={item.n})</text>"
        )
    axis_y = height - 6
    parts.append(
        f'<text class="axis" x="{_LABEL_WIDTH}" y="{axis_y}">0</text>'
        f'<text class="axis" x="{_LABEL_WIDTH + plot_width}" y="{axis_y}" text-anchor="end">'
        f"{_thousands(largest)} {_text(unit)}</text>"
    )
    return _svg(_WIDTH, height, f"{title} ({unit})", "".join(parts))
