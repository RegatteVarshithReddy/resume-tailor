from datetime import date, timedelta

from resume_tailor.stats import bucket_by_day, build_chart, compute


def _ts(days_ago: int) -> float:
    from datetime import datetime, time

    d = date.today() - timedelta(days=days_ago)
    return datetime.combine(d, time(12, 0)).timestamp()


def test_bucket_by_day_zero_fills_and_classifies():
    rows = [
        {"created_at": _ts(0), "status": "applied"},
        {"created_at": _ts(0), "status": "interview"},
        {"created_at": _ts(1), "status": "rejected"},
        {"created_at": _ts(10), "status": "applied"},  # outside a 7-day window
    ]
    buckets = bucket_by_day(rows, days=7)
    assert len(buckets) == 7
    assert buckets[-1].day == date.today()
    assert buckets[-1].open == 2 and buckets[-1].closed == 0
    assert buckets[-2].open == 0 and buckets[-2].closed == 1
    assert sum(b.total for b in buckets) == 3  # the 10-days-ago row is dropped


def test_build_chart_stacks_and_gaps_segments():
    rows = [{"created_at": _ts(0), "status": "applied"},
           {"created_at": _ts(0), "status": "rejected"}]
    buckets = bucket_by_day(rows, days=3)
    chart = build_chart(buckets)
    today_bar = chart.bars[-1]
    assert today_bar.open_h > 0 and today_bar.closed_h > 0
    # closed segment sits above the open segment with a visible gap
    assert today_bar.closed_y + today_bar.closed_h < today_bar.open_y
    assert chart.has_data is True


def test_build_chart_no_data_is_flat_not_broken():
    buckets = bucket_by_day([], days=5)
    chart = build_chart(buckets)
    assert chart.has_data is False
    assert all(b.open_h == 0 and b.closed_h == 0 for b in chart.bars)


def test_compute_separates_window_from_all_time():
    rows = [{"created_at": _ts(0), "status": "applied"}]
    status_counts = {"draft": 5, "applied": 1, "interview": 2, "rejected": 3, "archived": 1}
    s = compute(rows, status_counts, days=7)
    assert s.all_submitted == 7          # excludes the 5 drafts
    assert s.all_closed == 4             # rejected + archived
    assert s.all_open == 3               # applied + interview
    assert s.window_submitted == 1
    assert s.window_open == 1 and s.window_closed == 0
