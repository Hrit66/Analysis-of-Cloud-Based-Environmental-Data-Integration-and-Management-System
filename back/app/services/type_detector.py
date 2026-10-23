"""Column-scored dataset-type detection.

The upload endpoint used to trust the form field (defaulting to air quality),
which silently mis-typed files unless the user knew to change it. Detection
scores the actual headers first; the filename is only a weak tie-breaker and
the user's explicit choice always wins.

Returned ``scores`` are the number of recognised parameter columns per type,
``confidence`` is the winner's share of all recognised parameter columns, and
``ambiguous`` is True when two types are both well represented (for example a
water-quality station table that also carries PM2.5 columns). Ambiguous files
are imported with the best guess but the response records the ambiguity so the
UI can ask for an override.
"""
from typing import Dict, Iterable, List, Optional

from app.services.pipeline_interface import (
    _AIR_QUALITY_COLUMN_PATTERNS,
    _WATER_QUALITY_COLUMN_PATTERNS,
    _match_column_name,
)

AIR_PARAMETERS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
WEATHER_PARAMETERS = {"temperature", "temp_min", "temp_max", "precipitation"}
WATER_PARAMETERS = {
    "ph", "turbidity", "tds", "hardness", "chlorides", "sulfates", "nitrates",
    "fluorides", "iron", "manganese", "do", "bod", "ammonia", "total_coliform",
    "conductivity",
}
LONG_FORMAT_MARKERS = {"parameter", "pollutant", "variable", "metric", "value"}


def detect_dataset_type(
    columns: Iterable,
    filename: Optional[str] = None,
    parameter_values: Optional[Iterable] = None,
) -> Dict[str, object]:
    """Score headers (and long-format parameter names) for a dataset type.

    ``parameter_values`` lets a long-format file (one row per parameter) be
    typed from the values in its parameter column rather than from the file
    name.
    """
    canonical: List[str] = []
    lowered = set()
    for column in ([] if columns is None else columns):
        lowered.add(str(column).strip().lower())
        matched = _match_column_name(column, _WATER_QUALITY_COLUMN_PATTERNS)
        if matched:
            canonical.append("water:" + matched)
            continue
        matched = _match_column_name(column, _AIR_QUALITY_COLUMN_PATTERNS)
        if matched:
            canonical.append("air:" + matched)

    water_hits = {
        value.split(":", 1)[1] for value in canonical
        if value.startswith("water:") and value.split(":", 1)[1] in WATER_PARAMETERS
    }
    air_hits = {
        value.split(":", 1)[1] for value in canonical
        if value.startswith("air:") and value.split(":", 1)[1] in AIR_PARAMETERS
    }
    weather_hits = {
        value.split(":", 1)[1] for value in canonical
        if value.startswith("air:") and value.split(":", 1)[1] in WEATHER_PARAMETERS
    }

    for raw_value in ([] if parameter_values is None else parameter_values):
        value = str(raw_value).strip()
        if not value:
            continue
        matched = _match_column_name(value, _WATER_QUALITY_COLUMN_PATTERNS)
        if matched in WATER_PARAMETERS:
            water_hits.add(matched)
            continue
        matched = _match_column_name(value, _AIR_QUALITY_COLUMN_PATTERNS)
        if matched in AIR_PARAMETERS:
            air_hits.add(matched)
        elif matched in WEATHER_PARAMETERS:
            weather_hits.add(matched)

    scores = {
        "water_quality": len(water_hits),
        "air_quality": len(air_hits),
        "temperature": len(weather_hits & {"temperature", "temp_min", "temp_max"}),
        "rainfall": 1 if "precipitation" in weather_hits else 0,
    }

    filename_hint = None
    name = str(filename or "").lower()
    if any(token in name for token in ("rain", "precip", "imd")):
        filename_hint = "rainfall"
    elif any(token in name for token in ("temp", "tmax", "tmin")):
        filename_hint = "temperature"
    elif any(token in name for token in ("water", "wqi", "cpcb", "karna")):
        filename_hint = "water_quality"
    elif any(token in name for token in ("air", "aqi", "city_day", "pm25")):
        filename_hint = "air_quality"

    if filename_hint:
        scores[filename_hint] = scores.get(filename_hint, 0) + 1

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    best_type, best_score = ranked[0]
    second_type, second_score = ranked[1] if len(ranked) > 1 else (None, 0)
    total = sum(scores.values())

    long_format = bool(lowered & LONG_FORMAT_MARKERS) and bool(
        lowered & {"value", "measurement", "reading", "concentration"}
    )
    ambiguous = bool(
        best_score
        and second_score >= 2
        and (best_score - second_score) <= max(1, int(0.25 * best_score))
    ) or (long_format and best_score == 0) or best_score == 0

    confidence = round(best_score / total, 2) if total else 0.0
    if best_score == 0:
        reason = (
            "No recognised parameter columns; the file needs an explicit dataset type."
        )
        best_type = "air_quality"  # legacy default for the background job
    elif ambiguous:
        reason = (
            f"Headers match more than one type ({best_type}={best_score}, "
            f"{second_type}={second_score}); best guess used."
        )
    else:
        reason = f"{best_score} recognised parameter column(s) for {best_type}."

    return {
        "dataset_type": best_type,
        "confidence": confidence,
        "scores": scores,
        "ambiguous": ambiguous,
        "long_format": long_format,
        "filename_hint": filename_hint,
        "reason": reason,
    }
