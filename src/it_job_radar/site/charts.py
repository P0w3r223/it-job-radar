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

_WIDTH = 720
_ROW_HEIGHT = 26
_LABEL_WIDTH = 150
_PAD = 12


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
