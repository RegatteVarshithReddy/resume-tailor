"""Daily submission stats: bucket tracked applications by day and by
open (still active) vs closed (rejected/archived), and compute the geometry
for a simple inline-SVG stacked bar chart. No JS, no external chart library —
consistent with the app's dependency-light stance; hover tooltips are native
SVG <title> elements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# A submitted application is "closed" once it can't move further on its own —
# rejected or archived. Everything else non-draft (applied/screening/interview/
# offer, and any future status this module doesn't know about) is "still open".
CLOSED_STATUSES = {"rejected", "archived"}

DAY_CHOICES = [7, 14, 30, 60, 90]
DEFAULT_DAYS = 30


@dataclass
class DayBucket:
    day: date
    open: int = 0
    closed: int = 0

    @property
    def total(self) -> int:
        return self.open + self.closed


def bucket_by_day(rows: list[dict], days: int) -> list[DayBucket]:
    """rows: [{'created_at': unix_ts, 'status': str}, ...] (status != 'draft').
    Returns one bucket per calendar day for the trailing `days`-day window
    ending today (local time), oldest first, zero-filled where there's no data.
    """
    today = date.today()
    start = today - timedelta(days=days - 1)
    buckets = {
        start + timedelta(days=i): DayBucket(day=start + timedelta(days=i))
        for i in range(days)
    }
    for r in rows:
        d = datetime.fromtimestamp(r["created_at"]).date()
        b = buckets.get(d)
        if b is None:
            continue  # outside the window
        if r["status"] in CLOSED_STATUSES:
            b.closed += 1
        else:
            b.open += 1
    return [buckets[start + timedelta(days=i)] for i in range(days)]


def _nice_ceiling(x: float) -> int:
    """Smallest 'nice' integer (1/2/5 x 10^n) >= x, for gridline maxima."""
    if x <= 0:
        return 1
    n = math.floor(math.log10(x))
    base = 10 ** n
    for m in (1, 2, 5, 10):
        if m * base >= x:
            return int(m * base)
    return int(10 * base)


@dataclass
class ChartBar:
    label: str          # short x-axis label, e.g. "9/15"
    show_label: bool    # thinned for wide windows, to avoid collisions
    total: int
    x: float
    width: float
    open_y: float
    open_h: float
    closed_y: float
    closed_h: float
    tooltip: str


@dataclass
class ChartGeom:
    width: int
    height: int
    bars: list[ChartBar] = field(default_factory=list)
    gridlines: list[tuple[float, str]] = field(default_factory=list)
    baseline_y: float = 0
    plot_left: float = 0
    plot_right: float = 0
    has_data: bool = False


def build_chart(
    buckets: list[DayBucket], *, width: int = 900, height: int = 260,
    top_pad: int = 12, bottom_pad: int = 26, left_pad: int = 30, right_pad: int = 10,
    bar_gap: int = 3, seg_gap: int = 2,
) -> ChartGeom:
    n = len(buckets)
    plot_w = width - left_pad - right_pad
    plot_h = height - top_pad - bottom_pad
    baseline_y = top_pad + plot_h
    has_data = any(b.total for b in buckets)
    domain_max = _nice_ceiling(max((b.total for b in buckets), default=1) or 1)

    slot_w = plot_w / n
    bar_w = max(2.0, slot_w - bar_gap)
    label_stride = max(1, round(n / 10))

    bars = []
    for i, b in enumerate(buckets):
        x = left_pad + i * slot_w + (slot_w - bar_w) / 2
        open_h = (b.open / domain_max) * plot_h if domain_max else 0.0
        closed_h = (b.closed / domain_max) * plot_h if domain_max else 0.0
        gap = seg_gap if (open_h > 0 and closed_h > 0) else 0
        open_y = baseline_y - open_h
        closed_y = open_y - gap - closed_h
        show_label = (i % label_stride == 0) or i == n - 1
        bars.append(ChartBar(
            label=f"{b.day.month}/{b.day.day}", show_label=show_label, total=b.total,
            x=round(x, 1), width=round(bar_w, 1),
            open_y=round(open_y, 1), open_h=round(open_h, 1),
            closed_y=round(closed_y, 1), closed_h=round(closed_h, 1),
            tooltip=f"{b.day.strftime('%a, %b %d')} — Open {b.open} · Closed {b.closed} "
                    f"(total {b.total})",
        ))

    gridlines = []
    for frac in (0.0, 0.5, 1.0):
        val = round(domain_max * frac)
        y = baseline_y - (val / domain_max) * plot_h if domain_max else baseline_y
        gridlines.append((round(y, 1), str(val)))

    return ChartGeom(width=width, height=height, bars=bars, gridlines=gridlines,
                     baseline_y=round(baseline_y, 1), plot_left=left_pad,
                     plot_right=width - right_pad, has_data=has_data)


@dataclass
class SubmissionStats:
    days: int
    buckets: list[DayBucket]
    chart: ChartGeom
    window_submitted: int
    window_open: int
    window_closed: int
    all_open: int
    all_closed: int
    all_submitted: int


def compute(rows: list[dict], status_counts: dict[str, int], days: int) -> SubmissionStats:
    """rows: Store.list_submitted() output. status_counts: Store.counts_by_status()."""
    buckets = bucket_by_day(rows, days)
    chart = build_chart(buckets)
    all_closed = sum(status_counts.get(s, 0) for s in CLOSED_STATUSES)
    all_submitted = sum(n for s, n in status_counts.items() if s != "draft")
    return SubmissionStats(
        days=days, buckets=buckets, chart=chart,
        window_submitted=sum(b.total for b in buckets),
        window_open=sum(b.open for b in buckets),
        window_closed=sum(b.closed for b in buckets),
        all_open=all_submitted - all_closed,
        all_closed=all_closed,
        all_submitted=all_submitted,
    )
