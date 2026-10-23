"""Per-dataset-type import configuration.

Everything a user may legitimately want to tune lives here instead of being
hardcoded in the cleaners, the WQI calculator, or the forecasters:

* plausibility ranges (values outside are blanked and counted),
* WQI limits (Si / Vid, core parameters, clamps),
* forecast eligibility gates,
* station-name matching thresholds.

The cleaners read these dicts at call time, so tests (and, through the upload
API, users) can override them without touching code.
"""
from typing import Any, Dict, Optional, Tuple

PIPELINE_VERSION = "2026.10.2"

# Values outside these bounds are set to NaN and counted in
# ``out_of_range_values_set_to_nan``. Keep the order stable for reports.
RANGES: Dict[str, Dict[str, Tuple[float, float]]] = {
    "water_quality": {
        "ph": (0.0, 14.0),
        "turbidity": (0.0, 10000.0),
        "tds": (0.0, 200000.0),
        "hardness": (0.0, 100000.0),
        "chlorides": (0.0, 100000.0),
        "sulfates": (0.0, 100000.0),
        "nitrates": (0.0, 100000.0),
        "fluorides": (0.0, 100.0),
        "iron": (0.0, 10000.0),
        "manganese": (0.0, 10000.0),
        "do": (0.0, 15.0),
        "bod": (0.0, 500.0),
        "ammonia": (0.0, 1000.0),
        "total_coliform": (0.0, 100000000.0),
        "conductivity": (0.0, 100000.0),
        "latitude": (-90.0, 90.0),
        "longitude": (-180.0, 180.0),
    },
    "air_quality": {
        "pm25": (0.0, 1000.0),
        "pm10": (0.0, 1500.0),
        "no2": (0.0, 1000.0),
        "so2": (0.0, 2000.0),
        # CO is stored in µg/m³ (CPCB sub-index breakpoints are mg/m³ and are
        # converted in aqi_calculator); 200,000 µg/m³ = 200 mg/m³.
        "co": (0.0, 200000.0),
        "o3": (0.0, 1000.0),
        # Source AQI columns are indices, not concentrations.
        "us_aqi_max": (0.0, 500.0),
        "india_aqi": (0.0, 500.0),
        "temperature": (-50.0, 60.0),
        "temp_min": (-50.0, 60.0),
        "temp_max": (-50.0, 60.0),
        "precipitation": (0.0, 2000.0),
    },
}
RANGES["temperature"] = {
    key: RANGES["air_quality"][key]
    for key in ("temperature", "temp_min", "temp_max")
}
RANGES["rainfall"] = {"precipitation": RANGES["air_quality"]["precipitation"]}

# WQI limits from BIS IS:10500-2012 / CPCB (see wqi_calculator docstring).
WQI: Dict[str, Any] = {
    "params": {
        "ph": {"Si": 8.5, "Vid": 7.0},
        "turbidity": {"Si": 5.0, "Vid": 0.0},
        "tds": {"Si": 500.0, "Vid": 0.0},
        "hardness": {"Si": 300.0, "Vid": 0.0},
        "chlorides": {"Si": 250.0, "Vid": 0.0},
        "sulfates": {"Si": 200.0, "Vid": 0.0},
        "nitrates": {"Si": 45.0, "Vid": 0.0},
        "fluorides": {"Si": 1.0, "Vid": 0.0},
        "iron": {"Si": 0.3, "Vid": 0.0},
        "manganese": {"Si": 0.1, "Vid": 0.0},
        "do": {"Si": 5.0, "Vid": 14.6},
        "bod": {"Si": 3.0, "Vid": 0.0},
    },
    "core": ("ph", "do", "bod"),
    "min_extended_params": 3,
    "required_extended_any": ("do", "bod"),
    "sub_index_max": 200.0,
}

ML_GATES: Dict[str, Dict[str, Any]] = {
    "water_quality": {
        "min_points": 24,
        "min_span_days": 365,
        "max_missing_share": 0.5,
        "point_unit": "months",
    },
    "air_quality": {
        "min_points": 10,
        "min_span_days": 14,
        "max_missing_share": 0.5,
        "point_unit": "samples",
    },
    "temperature": {
        "min_points": 10,
        "min_span_days": 14,
        "max_missing_share": 0.5,
        "point_unit": "samples",
    },
    "rainfall": {
        "min_points": 10,
        "min_span_days": 14,
        "max_missing_share": 0.5,
        "point_unit": "samples",
    },
}

STATION_MATCH: Dict[str, Any] = {
    "similarity_threshold": 0.88,
    "min_token_overlap": 0.6,
    "max_suggestions": 50,
}

SUPPORTED_DATASET_TYPES = tuple(RANGES)


def ranges_for(
    dataset_type: Optional[str],
    overrides: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Tuple[float, float]]:
    """Effective plausibility ranges for one import (copy, safe to mutate)."""
    ranges = dict(RANGES.get(dataset_type or "", {}))
    for column, bounds in (overrides or {}).items():
        if column in ranges and len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if low < high:
                ranges[column] = (low, high)
    return ranges


def wqi_params() -> Dict[str, Dict[str, float]]:
    """The live WQI limit table (read at call time, so overrides apply)."""
    return WQI["params"]


def wqi_core() -> Tuple[str, ...]:
    return tuple(WQI["core"])


def k_const() -> float:
    return 1.0 / sum(1.0 / p["Si"] for p in wqi_params().values())


def gates_for(dataset_type: Optional[str]) -> Dict[str, Any]:
    """ML eligibility gates for a dataset type."""
    return dict(ML_GATES.get(dataset_type or "", ML_GATES["air_quality"]))


def check_ml_eligibility(
    dataset_type: Optional[str],
    points: int,
    span_days: float,
    missing_share: float = 0.0,
) -> Tuple[bool, Optional[str]]:
    """Apply the configured ML gates and explain any skip.

    Returns ``(eligible, reason)``. Callers must surface the reason instead of
    silently dropping a series.
    """
    gates = gates_for(dataset_type)
    unit = gates.get("point_unit", "points")
    if points < int(gates["min_points"]):
        return False, f"only {points} {unit} (minimum {gates['min_points']})"
    if span_days < float(gates["min_span_days"]):
        return False, (
            f"span {span_days:.0f} days (minimum {gates['min_span_days']:.0f})"
        )
    if missing_share > float(gates["max_missing_share"]):
        return False, (
            f"missing share {missing_share:.0%} exceeds "
            f"{gates['max_missing_share']:.0%}"
        )
    return True, None
