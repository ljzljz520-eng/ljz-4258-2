"""Time alignment for measurements with different granularities.

Rules used here:
* Point samples are modeled as half-open intervals ending at the next observed
  timestamp. A point with no successor remains valid only until the window end.
* Flow intervals intersect auxiliary intervals (density/fat/solids). The product
  is integrated over intersection duration.
* Overlapping same-metric observations for one target are rejected before
  enqueue; gaps are carried into the result as uncovered duration, not silently
  interpolated.
* Range changes are represented by adjacent, non-overlapping records with
  different range_code values.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    value: float
    sigma: float
    metric: str
    id: int | None = None
    range_code: str | None = None
    basis: str = "wet"


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt


def point_end(ts: datetime, next_ts: datetime | None, window_end: datetime) -> datetime:
    if next_ts is None:
        return window_end
    return min(next_ts, window_end)


def build_intervals(rows: Sequence, window_start: datetime, window_end: datetime,
                    point_metrics: set[str]) -> dict[str, list[Interval]]:
    groups: dict[str, list[object]] = {}
    for r in rows:
        groups.setdefault(r.metric, []).append(r)

    result: dict[str, list[Interval]] = {}
    for metric, items in groups.items():
        if metric in point_metrics:
            items = sorted(items, key=lambda x: x.period_start)
            intervals = []
            for i, r in enumerate(items):
                ts = max(_ensure_aware(r.period_start), window_start)
                next_ts = items[i + 1].period_start if i + 1 < len(items) else None
                end = min(point_end(r.period_start, next_ts, window_end), window_end)
                if ts < end:
                    intervals.append(Interval(ts, end, float(r.value), float(r.uncertainty_value),
                                              metric, r.id, getattr(r, "range_code", None),
                                              getattr(r, "basis", "wet")))
        else:
            intervals = []
            for r in items:
                if r.period_end is None:
                    raise ValueError(f"{metric} measurement {r.id} requires period_end")
                start = max(_ensure_aware(r.period_start), window_start)
                end = min(_ensure_aware(r.period_end), window_end)
                if start < end:
                    intervals.append(Interval(start, end, float(r.value), float(r.uncertainty_value),
                                              metric, r.id, getattr(r, "range_code", None),
                                              getattr(r, "basis", "wet")))
        intervals.sort(key=lambda x: (x.start, x.end))
        for a, b in zip(intervals, intervals[1:]):
            if b.start < a.end:
                raise ValueError(f"overlapping {metric} intervals for same target: ids {a.id} and {b.id}")
        result[metric] = intervals
    return result


def intersect(a: Interval, b: Interval) -> tuple[datetime, datetime] | None:
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    return (start, end) if start < end else None


def duration_hours(start: datetime, end: datetime, base_hours: float) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0 / base_hours) if base_hours else 0.0


def uncovered_hours(intervals: Iterable[Interval], window_start: datetime, window_end: datetime) -> float:
    total = (window_end - window_start).total_seconds()
    covered = sum((i.end - i.start).total_seconds() for i in intervals)
    return max(0.0, total - covered) / 3600.0


def split_ranges(intervals: Sequence[Interval]) -> dict[str, tuple[float, float]]:
    """Return total duration covered by each range code in hours."""
    out: dict[str, float] = {}
    for i in intervals:
        key = i.range_code or "default"
        out[key] = out.get(key, 0.0) + (i.end - i.start).total_seconds() / 3600.0
    return out
