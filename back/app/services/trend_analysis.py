"""Robust monotonic trend diagnostics for water-quality index series.

The Sen slope is the median of all pairwise slopes, so a single unusual
sample cannot dominate the estimate. The Mann-Kendall test checks whether the
series has a monotonic trend; its variance includes the standard tie
correction because water-quality indices often repeat values.
"""
from collections import Counter
from datetime import datetime
import math
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MIN_TREND_SAMPLES = 8
ALPHA = 0.05
SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Unsupported timestamp: {value!r}")


def _coerce_value(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _sen_slope(points: Sequence[Tuple[float, float]]) -> Optional[float]:
    slopes: List[float] = []
    for index, (x_i, y_i) in enumerate(points):
        for x_j, y_j in points[index + 1:]:
            delta_x = x_j - x_i
            if delta_x > 0:
                slopes.append((y_j - y_i) / delta_x)
    return median(slopes) if slopes else None


def _mann_kendall(values: Sequence[float]) -> Dict[str, Any]:
    n = len(values)
    s = 0
    for index, value in enumerate(values):
        for later in values[index + 1:]:
            if later > value:
                s += 1
            elif later < value:
                s -= 1

    tie_counts = Counter(values)
    tie_term = sum(
        count * (count - 1) * (2 * count + 5)
        for count in tie_counts.values()
        if count > 1
    )
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    if variance <= 0:
        z = 0.0
    elif s > 0:
        z = (s - 1) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1) / math.sqrt(variance)
    else:
        z = 0.0

    p_value = math.erfc(abs(z) / math.sqrt(2.0))
    return {
        "s": s,
        "variance": variance,
        "z": z,
        "p_value": p_value,
    }


def analyze_trend(
    timestamps: Iterable,
    values: Iterable,
    min_samples: int = MIN_TREND_SAMPLES,
    alpha: float = ALPHA,
) -> Dict[str, Any]:
    """Return Sen's slope and Mann-Kendall diagnostics for one series."""
    points: List[Tuple[float, float, datetime]] = []
    for raw_timestamp, raw_value in zip(timestamps, values):
        value = _coerce_value(raw_value)
        if value is None:
            continue
        try:
            timestamp = _coerce_datetime(raw_timestamp)
        except (TypeError, ValueError):
            continue
        points.append((timestamp.timestamp(), value, timestamp))

    points.sort(key=lambda item: item[0])
    n = len(points)
    base = {
        "available": False,
        "n": n,
        "min_samples": min_samples,
        "alpha": alpha,
        "reason": None,
        "sen_slope_per_year": None,
        "direction": None,
        "significant": False,
        "mann_kendall": None,
    }
    if n < min_samples:
        base["reason"] = (
            f"needs at least {min_samples} scored samples in the window (has {n})"
        )
        return base

    pairs = [(x, y) for x, y, _ in points]
    slope = _sen_slope(pairs)
    if slope is None:
        base["reason"] = "needs at least two distinct sample dates"
        return base

    slope_per_year = slope * SECONDS_PER_YEAR
    mk = _mann_kendall([y for _, y, _ in points])
    significant = mk["p_value"] < alpha
    if mk["s"] > 0:
        direction = "increasing"
    elif mk["s"] < 0:
        direction = "decreasing"
    else:
        direction = "no trend"

    if significant and direction == "increasing":
        interpretation = (
            "Significant increasing trend: WQI is worsening because higher values are worse."
        )
    elif significant and direction == "decreasing":
        interpretation = (
            "Significant decreasing trend: WQI is improving because lower values are better."
        )
    else:
        interpretation = "No statistically significant monotonic trend at the 5% level."

    start = points[0][2]
    end = points[-1][2]
    base.update({
        "available": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "span_years": (points[-1][0] - points[0][0]) / SECONDS_PER_YEAR,
        "sen_slope_per_year": round(slope_per_year, 3),
        "direction": direction,
        "significant": significant,
        "interpretation": interpretation,
        "mann_kendall": {
            "s": mk["s"],
            "z": round(mk["z"], 4),
            "p_value": round(mk["p_value"], 6),
            "variance": round(mk["variance"], 3),
            "significant": significant,
            "alpha": alpha,
        },
    })
    return base
