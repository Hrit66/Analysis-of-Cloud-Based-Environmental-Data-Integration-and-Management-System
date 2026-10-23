"""Build a complete, renderer-agnostic report payload.

``build_report_data`` is the single source of truth for every export format.
The Excel, PDF and CSV-ZIP renderers only format the values collected here;
none of them recompute statistics. All aggregates come from
``app.services.dashboard_queries`` so exports match the dashboards exactly.
"""
from datetime import datetime
import calendar
import difflib
import re
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import pandas as pd

from app.services.dashboard_queries import (
    anomaly_records,
    anomaly_statistics,
    collection_for,
    extreme_do_samples,
    forecast_documents,
    monthly_parameter_counts,
    monthly_statistics,
    parameter_completeness,
    station_statistics,
    station_value,
)
from app.services.report_units import (
    PARAMETER_LABELS,
    PARAMETER_UNITS,
    TYPE_LABELS,
    TYPE_ORDER,
    dataset_tags,
    header_with_unit,
)
from app.services import dataset_config
from app.services.aqi_calculator import aqi_category
from app.services.authz import readable_query
from app.services.water_forecaster import MIN_MONTHS_FOR_OUTLOOK, forecast_water_parameter
from app.services.wqi_calculator import MIN_SAMPLES_FOR_RANK, WQI_CATEGORIES

DATASET_TYPE_TO_CAPABILITIES: Dict[str, List[str]] = {
    "air_quality": ["air_quality"],
    "water_quality": ["water_quality"],
    "temperature": ["temperature", "rainfall"],
    "rainfall": ["temperature", "rainfall"],
}

def _fmt(value: float) -> str:
    """Compact numeric label for method notes (15 not 15.0)."""
    number = float(value)
    return f"{number:g}"


ANOMALIES_PER_DATASET = 500
SEVERITY_ORDER = {"extreme": 0, "high": 1, "moderate": 2, "mild": 3}
EFFECT_ORDER = {"deterioration": 0, "unusual": 1, "improvement": 2}

# Direction of harm for anomaly ranking: high values are bad for most
# pollutants and for the WQI; DO is the exception (low DO is bad).
LOWER_IS_BETTER = {
    "wqi", "aqi", "pm25", "pm10", "no2", "so2", "co", "o3", "bod", "ammonia",
    "turbidity", "tds", "conductivity", "hardness", "chlorides", "sulfates",
    "nitrates", "fluorides", "iron", "manganese", "total_coliform",
    "precipitation",
}
HIGHER_IS_BETTER = {"do"}
NEUTRAL_DIRECTION = {"ph", "temperature", "temp_min", "temp_max"}

PARAMETER_CAPABILITY: Dict[str, str] = {
    "aqi": "air_quality",
    "pm25": "air_quality",
    "pm10": "air_quality",
    "no2": "air_quality",
    "so2": "air_quality",
    "co": "air_quality",
    "o3": "air_quality",
    "wqi": "water_quality",
    "do": "water_quality",
    "total_coliform": "water_quality",
    "ph": "water_quality",
    "bod": "water_quality",
    "temperature": "temperature",
    "temp_min": "temperature",
    "temp_max": "temperature",
    "precipitation": "rainfall",
}

MIN_VALUE_KEY = {
    "water_quality": "min_wqi",
    "air_quality": "min_aqi",
    "temperature": "min_temp",
    "rainfall": "min_precip",
}

PLAUSIBILITY_CAPS = {
    "do": dataset_config.RANGES["water_quality"]["do"][1],
    "bod": dataset_config.RANGES["water_quality"]["bod"][1],
    "total_coliform": dataset_config.RANGES["water_quality"]["total_coliform"][1],
}

_LOCATION_FIXES = {
    "UPIINGADY": "UPPINAGADY",
    "NETHRAVATHI": "NETRAVATHI",
    "TNAK": "TANK",
}
_LOCATION_ACRONYMS = {"U/S", "D/S", "KIOCL", "T.G."}
_LOCATION_SMALL_WORDS = {"at", "of", "the", "before", "with", "to", "in", "on", "for", "and"}


def _partial_month_labels(start_date, end_date) -> set:
    """Window-edge months that are not covered end to end by the selection."""
    labels = set()
    if isinstance(start_date, datetime) and start_date.day > 1:
        labels.add(start_date.strftime("%Y-%m"))
    if isinstance(end_date, datetime):
        last_day = calendar.monthrange(end_date.year, end_date.month)[1]
        if end_date.day < last_day:
            labels.add(end_date.strftime("%Y-%m"))
    return labels


def display_location(value) -> str:
    """Tidy a raw station name for presentation only (joins keep the raw value)."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return text
    text = re.sub(r"\s+BENGALURU(?:\s+NORTH)?$", "", text, flags=re.IGNORECASE).strip()
    tokens = text.split()
    if len(tokens) >= 3:
        first, last = tokens[0].upper(), tokens[-1].upper()
        if first == last or difflib.SequenceMatcher(None, first, last).ratio() >= 0.85:
            tokens = tokens[:-1]
    words: List[str] = []
    for index, token in enumerate(tokens):
        fixed = _LOCATION_FIXES.get(token.upper(), token)
        upper = fixed.upper()
        if upper in _LOCATION_ACRONYMS:
            words.append(upper)
        elif index > 0 and fixed.lower() in _LOCATION_SMALL_WORDS:
            words.append(fixed.lower())
        else:
            words.append(fixed.title())
    return " ".join(words)

CSV_COLUMNS: Dict[str, List[str]] = {
    "water_quality": [
        "timestamp", "location", "ph", "do", "bod", "ammonia", "turbidity",
        "tds", "conductivity", "hardness", "chlorides", "sulfates", "nitrates",
        "fluorides", "iron", "manganese", "total_coliform", "wqi",
        "wqi_category", "extended_wqi", "extended_wqi_category",
        "extended_param_count",
    ],
    "air_quality": [
        "timestamp", "location", "pm25", "pm10", "no2", "so2", "co", "o3",
        "aqi", "aqi_category", "dominant_pollutant",
    ],
    "temperature": ["timestamp", "location", "temperature", "temp_min", "temp_max"],
    "rainfall": ["timestamp", "location", "precipitation"],
}

CSV_LABELS: Dict[str, str] = {
    "timestamp": "Timestamp (UTC)",
    "location": "Station",
    "wqi_category": "WQI category",
    "extended_wqi": "Extended WQI",
    "extended_wqi_category": "Extended WQI category",
    "extended_param_count": "Extended WQI parameter count",
    "aqi": "AQI",
    "aqi_category": "AQI category",
    "dominant_pollutant": "Dominant pollutant",
}


class ReportScopeError(Exception):
    """A requested dataset does not exist or belongs to another account."""


def user_field(user, *names):
    """Read a field from a dict or a Pydantic user model."""
    for name in names:
        value = user.get(name) if isinstance(user, dict) else getattr(user, name, None)
        if value is not None:
            return value
    return None


def user_id(user) -> str:
    return str(user_field(user, "_id", "id"))


def _clean_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


def _round(value, digits: int = 2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _parameter_label(parameter: str) -> str:
    return PARAMETER_LABELS.get(parameter, parameter.replace("_", " "))


def _unit(parameter: str) -> str:
    return PARAMETER_UNITS.get(parameter, "")


def _rank_parts(row: dict):
    """Human rank, numeric position and ranked pool size (None when unranked)."""
    if row.get("rank_pct") is None or row.get("rank_of") is None:
        return None, None, None
    pool = int(row["rank_of"])
    position = round(row["rank_pct"] / 100 * (pool - 1)) + 1
    return f"{position} of {pool}", position, pool


def _month_date(month) -> Optional[datetime]:
    if not month:
        return None
    try:
        return datetime.strptime(str(month), "%Y-%m")
    except ValueError:
        return None


async def _generate_missing_water_outlooks(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    pairs: List[tuple],
) -> List[dict]:
    """Generate and persist outlooks that are eligible but absent from storage.

    The report should not call an eligible series "no stored forecast" merely
    because the upload-time job missed it. Rebuilding from the stored samples
    keeps the report self-contained; the generated document is persisted so a
    later request reuses it.
    """
    if not pairs:
        return []
    docs = await database.water_quality.find({"dataset_id": dataset_id}).to_list(length=None)
    if not docs:
        return []
    frame = pd.DataFrame([
        {
            "timestamp": doc.get("timestamp"),
            "location": doc.get("location"),
            "do": doc.get("do"),
            "wqi": doc.get("wqi"),
            "total_coliform": doc.get("total_coliform"),
        }
        for doc in docs
    ])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    generated: List[dict] = []
    for location, parameter in pairs:
        try:
            result = forecast_water_parameter(frame, location, parameter)
        except Exception:
            continue
        result["dataset_id"] = dataset_id
        result["created_at"] = datetime.utcnow()
        try:
            await database.forecasts.insert_one(result)
        except Exception:
            pass
        generated.append(result)
    return generated


async def _coliform_stats(database: AsyncIOMotorDatabase, dataset_id: str) -> dict:
    rows = await database.water_quality.aggregate([
        {"$match": {"dataset_id": dataset_id, "total_coliform": {"$ne": None}}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "max": {"$max": "$total_coliform"},
            "above_1e7": {"$sum": {"$cond": [{"$gt": ["$total_coliform", 10_000_000]}, 1, 0]}},
        }},
    ]).to_list(length=1)
    return rows[0] if rows else {}


def _category_for_value(capability: str, value) -> Optional[str]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if capability == "water_quality":
        for low, high, name in WQI_CATEGORIES:
            if low <= number < high:
                return name
        return "Unsuitable (>100)"
    if capability == "air_quality":
        return aqi_category(number)
    return None


def _anomaly_direction(doc: dict) -> Optional[str]:
    kind = doc.get("kind")
    if kind == "unusually_low":
        return "low"
    if kind == "unusually_high":
        return "high"
    value, baseline = doc.get("value"), doc.get("baseline")
    if value is None or baseline is None:
        return None
    try:
        return "high" if float(value) > float(baseline) else "low"
    except (TypeError, ValueError):
        return None


def _anomaly_effect(parameter: Optional[str], direction: Optional[str]) -> Optional[str]:
    if not parameter or not direction:
        return None
    if parameter in NEUTRAL_DIRECTION:
        return "unusual"
    if parameter in HIGHER_IS_BETTER:
        return "deterioration" if direction == "low" else "improvement"
    if parameter in LOWER_IS_BETTER:
        return "deterioration" if direction == "high" else "improvement"
    return "unusual"


def _short_summary(station_rows: List[dict], capability: str) -> dict:
    """Headline stats across stations for the overview row."""
    latest_value = mean_value = min_value = max_value = None
    latest_ts = worst_ts = None
    latest_station = worst_station = category = None
    weighted_sum = 0.0
    weighted_count = 0
    mins, maxes = [], []
    min_key = MIN_VALUE_KEY.get(capability)

    for row in station_rows:
        latest, mean, worst, row_latest_ts, row_worst_ts, row_category = station_value(row, capability)
        count = row.get("count") or 0
        scored = row.get("scored_count")
        weight = scored if scored is not None else count
        if mean is not None and weight:
            weighted_sum += mean * weight
            weighted_count += weight
        if min_key and row.get(min_key) is not None:
            mins.append(row[min_key])
        if worst is not None:
            maxes.append(worst)
        if latest is not None and (latest_ts is None or (row_latest_ts and row_latest_ts > latest_ts)):
            latest_ts = row_latest_ts or latest_ts
            latest_value = latest
            latest_station = row.get("location")
            if row_category:
                category = row_category
        if worst is not None and (worst_ts is None or (row_worst_ts and row_worst_ts >= worst_ts)):
            worst_ts = row_worst_ts or worst_ts
            worst_station = row.get("location")

    mean_value = _round(weighted_sum / weighted_count) if weighted_count else None
    min_value = _round(min(mins)) if mins else None
    max_value = _round(max(maxes)) if maxes else None

    return {
        "latest_value": _round(latest_value),
        "latest_date": latest_ts,
        "latest_station": display_location(latest_station) if latest_station else None,
        "category": category,
        "mean_value": mean_value,
        "min_value": min_value,
        "max_value": max_value,
        "max_date": worst_ts,
        "max_station": display_location(worst_station) if worst_station else None,
    }


def _anomaly_row(doc: dict, dataset: dict, capability: str) -> dict:
    parameter = doc.get("parameter")
    direction = _anomaly_direction(doc)
    return {
        "dataset_id": dataset["id"],
        "dataset_name": dataset["name"],
        "data_type": capability,
        "data_type_label": TYPE_LABELS.get(capability, capability),
        "location": doc.get("location"),
        "location_label": display_location(doc.get("location")),
        "timestamp": _clean_dt(doc.get("timestamp")),
        "parameter": parameter,
        "parameter_label": _parameter_label(parameter or ""),
        "unit": _unit(parameter or ""),
        "value": _round(doc.get("value"), 3),
        "expected_low": _round(doc.get("expected_low"), 3),
        "expected_high": _round(doc.get("expected_high"), 3),
        "baseline": _round(doc.get("baseline"), 3),
        "severity": doc.get("severity"),
        "kind": doc.get("kind"),
        "direction": direction,
        "direction_label": (
            {"low": "Unusually low", "high": "Unusually high"}.get(direction, "—")
        ),
        "effect": _anomaly_effect(parameter, direction),
        "detector": doc.get("detector"),
        "score": _round(doc.get("anomaly_score"), 3),
    }


def _outlook_row(doc: dict, dataset: dict, capability: str) -> Optional[dict]:
    predictions = doc.get("predictions") or []
    if not predictions:
        return None
    first = predictions[0] or {}
    metrics = doc.get("metrics") or {}
    parameter = doc.get("parameter")
    mae = _round(metrics.get("test_mae", metrics.get("mae")), 3)
    baseline = _round(metrics.get("baseline_persistence_mae"), 3)
    skill = metrics.get("skill_vs_persistence_pct")
    if mae is not None and baseline not in (None, 0):
        skill = round((1 - mae / baseline) * 100, 1)
    point_count = metrics.get("monthly_points", metrics.get("training_samples", metrics.get("sample_count")))
    return {
        "dataset_id": dataset["id"],
        "dataset_name": dataset["name"],
        "data_type": capability,
        "data_type_label": TYPE_LABELS.get(capability, capability),
        "location": doc.get("location"),
        "location_label": display_location(doc.get("location")),
        "parameter": parameter,
        "parameter_label": _parameter_label(parameter or ""),
        "unit": _unit(parameter or ""),
        "method": doc.get("model_used"),
        "target_date": _clean_dt(first.get("timestamp")),
        "forecast_value": _round(first.get("predicted_value"), 3),
        "lower_bound": _round(first.get("lower_bound"), 3),
        "upper_bound": _round(first.get("upper_bound"), 3),
        "horizon_steps": len(predictions),
        "horizon_label": doc.get("forecast_horizon"),
        "mae": _round(mae, 3),
        "baseline_mae": _round(baseline, 3),
        "skill_pct": _round(skill, 1),
        "sample_count": point_count,
        "beats_baseline": bool(skill is not None and skill > 0),
        "stale": False,
        "note": metrics.get("limitation") or metrics.get("model_note"),
    }


def _data_quality_row(dataset: dict, extras: Optional[dict] = None) -> dict:
    report = dataset.get("cleaning_report") or {}
    rows_read = report.get("rows_read")
    if rows_read is None and report.get("original_shape"):
        rows_read = report["original_shape"][0]
    rows_stored = dataset.get("row_count")
    if rows_stored is None and report.get("cleaned_shape"):
        rows_stored = report["cleaned_shape"][0]

    notes: List[str] = []
    missing_markers = report.get("missing_markers_found") or {}
    if missing_markers:
        total_markers = sum(int(v or 0) for v in missing_markers.values())
        notes.append(
            f"{total_markers:,} blank/NA missing-value markers were blanked across "
            f"{len(missing_markers)} stored parameters after synonym columns were merged "
            "(counted before duplicate station-dates were averaged). Sentinel values such "
            "as -999 and below-detection tokens such as BDL/ND are counted separately when present."
        )
        if missing_markers.get("fluorides"):
            notes.append(
                f"Fluorides account for {missing_markers['fluorides']:,} of these markers; "
                "blank fluoride cells are missing samples, not zero concentrations."
            )
    sentinels = report.get("sentinel_values_detected") or {}
    if sentinels:
        total_sent = sum(int(v or 0) for v in sentinels.values())
        notes.append(
            f"{total_sent:,} sentinel values (for example -999) blanked across "
            f"{len(sentinels)} parameters."
        )
    bdl_missing = report.get("below_detection_limit_treated_missing") or {}
    if bdl_missing:
        total_bdl = sum(int(v or 0) for v in bdl_missing.values())
        notes.append(
            f"{total_bdl:,} below-detection (BDL/ND) values treated as missing across "
            f"{len(bdl_missing)} parameters."
        )
    bdl_converted = report.get("below_detection_limit_converted") or {}
    if bdl_converted:
        total_converted = sum(int(v or 0) for v in bdl_converted.values())
        notes.append(
            f"{total_converted:,} '<limit' values replaced by half the detection limit across "
            f"{len(bdl_converted)} parameters."
        )
    duplicates = report.get("duplicates_removed") or 0
    if duplicates:
        notes.append(f"{duplicates:,} duplicate station-dates averaged.")
    out_of_range = report.get("out_of_range_values_set_to_nan") or {}
    total_out = sum(int(v or 0) for v in out_of_range.values() if isinstance(v, (int, float)))
    if total_out:
        air_out = {
            column: count for column, count in out_of_range.items()
            if column in ("us_aqi_max", "india_aqi")
        }
        if air_out.get("us_aqi_max"):
            notes.append(
                f"{int(air_out['us_aqi_max']):,} us_aqi_max value(s) above the "
                "AQI 500 ceiling were impossible and were blanked."
            )
        remaining = total_out - sum(int(v or 0) for v in air_out.values())
        if remaining:
            notes.append(
                f"{remaining:,} impossible value{'s' if remaining != 1 else ''} blanked "
                "outside the configured plausibility ranges."
            )
    source_caps = report.get("source_aqi_at_cap") or {}
    if source_caps.get("india_aqi"):
        notes.append(
            f"{int(source_caps['india_aqi']):,} source india_aqi rows are exactly "
            "500; the source caps the index at 500, so these mean '500 or above', "
            "not a measured value."
        )
    dominant_share = dataset.get("dominant_pollutant_share") or {}
    if dominant_share.get("o3", 0) >= 0.8:
        notes.append(
            f"O3 is the dominant pollutant on {dominant_share['o3'] * 100:.1f}% of "
            "records; the dataset is tagged modelled because this pattern is "
            "typical of modelled/reanalysis data."
        )
    if dataset.get("dataset_type") == "air_quality":
        original = {str(column).lower() for column in (dataset.get("original_columns") or [])}
        if "o3_8h_max" in original:
            notes.append(
                "O3 is the source daily maximum 8-hour concentration (o3_8h_max), "
                "not an instantaneous reading; the import maps it to the stored o3 field."
            )
    ranges = report.get("plausibility_ranges") or {}
    if ranges:
        if dataset.get("dataset_type") == "air_quality":
            key_ranges = ["pm25", "pm10", "co", "us_aqi_max"]
        else:
            key_ranges = ["ph", "do", "bod", "total_coliform"]
        shown = ", ".join(
            f"{PARAMETER_LABELS.get(column, column)} {ranges[column][0]:g}-{ranges[column][1]:g}"
            for column in key_ranges if column in ranges
        )
        notes.append(
            f"Plausibility ranges applied (values outside are blanked): {shown}; "
            f"{max(len(ranges) - len(key_ranges), 0)} more bounds are stored in the dataset "
            "config and can be overridden on upload."
        )
    if dataset.get("dataset_type") == "water_quality":
        limits = dataset_config.wqi_params()
        notes.append(
            "WQI limits: pH Si "
            f"{limits['ph']['Si']:g}/Vid {limits['ph']['Vid']:g}, DO "
            f"{limits['do']['Si']:g}/{limits['do']['Vid']:g}, BOD "
            f"{limits['bod']['Si']:g}/{limits['bod']['Vid']:g}; sub-indices capped at "
            f"{dataset_config.WQI['sub_index_max']:g}. Limits are config-driven."
        )
    date_format = report.get("date_format") or {}
    if date_format.get("warning"):
        notes.append(date_format["warning"])
    units = report.get("units_detected") or {}
    ambiguous = {
        column: info for column, info in units.items()
        if info.get("confidence") == "assumed"
    }
    if ambiguous:
        notes.append(
            "Units assumed (verify source): "
            + ", ".join(
                f"{PARAMETER_LABELS.get(column, column)} {info.get('unit')}"
                for column, info in sorted(ambiguous.items())
            )
            + "."
        )
    converted = {
        column: info for column, info in units.items()
        if info.get("converted")
    }
    if converted:
        notes.append(
            "Units converted: "
            + ", ".join(
                f"{PARAMETER_LABELS.get(column, column)} {info.get('source_unit')}->{info.get('unit')}"
                for column, info in sorted(converted.items())
            )
            + "."
        )
    dropped_columns = report.get("columns_dropped") or []
    renamed_columns = report.get("columns_renamed") or {}
    synonym_merged = report.get("synonym_columns_merged") or {}
    if dropped_columns:
        merged_count = sum(len(sources) for sources in synonym_merged.values() if sources)
        notes.append(
            f"{len(dropped_columns)} unused/empty source columns dropped; "
            f"{len(renamed_columns)} renamed and {merged_count} synonym aliases merged into "
            "stored fields."
        )
    if report.get("synonym_columns_merged"):
        notes.append("Duplicate columns for the same parameter merged.")
    if report.get("derived_values_imputed"):
        notes.append("Some derived values were imputed and tagged in the cleaned data.")
    if report.get("source_format", "").startswith("imd"):
        notes.append("IMD files merge on date; missing days stay blank, not zero.")
    if "modelled" in dataset_tags(dataset):
        notes.append("Contains modelled or derived values (tagged in About).")
    for note in extras or []:
        notes.append(note)

    return {
        "dataset_id": str(dataset["_id"]),
        "dataset_name": dataset.get("display_name") or dataset.get("filename") or str(dataset["_id"]),
        "data_type": dataset.get("dataset_type"),
        "rows_read": rows_read,
        "rows_stored": rows_stored,
        "rows_dropped": report.get("rows_dropped") if isinstance(report.get("rows_dropped"), (int, float)) else None,
        "duplicates_removed": duplicates or None,
        "columns_dropped": len(dropped_columns),
        "columns_renamed": len(report.get("columns_renamed") or {}),
        "synonym_columns_merged": sum(
            len(sources) for sources in (report.get("synonym_columns_merged") or {}).values()
            if sources
        ),
        "source_format": report.get("source_format") or "tabular",
        "notes": notes,
    }


def _dataset_public(dataset: dict, capabilities: List[str]) -> dict:
    return {
        "id": str(dataset["_id"]),
        "name": dataset.get("display_name") or dataset.get("filename") or str(dataset["_id"]),
        "filename": dataset.get("filename"),
        "dataset_type": dataset.get("dataset_type"),
        "capabilities": capabilities,
        "tags": dataset_tags(dataset),
        "row_count": dataset.get("row_count"),
        "created_at": _clean_dt(dataset.get("created_at")),
        "updated_at": _clean_dt(dataset.get("updated_at")),
    }


async def resolve_datasets(
    database: AsyncIOMotorDatabase,
    owner_id: str,
    dataset_ids: Optional[Iterable[str]],
    data_types: Optional[Iterable[str]],
    user=None,
) -> List[dict]:
    """Load the caller's readable completed datasets, refusing foreign/missing ids."""
    base: Dict[str, Any] = readable_query(user) if user is not None else {"user_id": owner_id}
    if dataset_ids is not None:
        requested = list(dataset_ids)
        if not requested:
            return []
        object_ids = []
        for raw in requested:
            if not ObjectId.is_valid(raw):
                raise ReportScopeError("Dataset not found or not available to this account.")
            object_ids.append(ObjectId(raw))
        base["_id"] = {"$in": object_ids}
        base["status"] = "completed"
        docs = await database.datasets.find(base).to_list(length=None)
        if len(docs) != len(set(requested)):
            raise ReportScopeError("Dataset not found or not available to this account.")
    else:
        base["status"] = "completed"
        docs = await database.datasets.find(base).to_list(length=None)

    wanted = set(data_types or TYPE_ORDER)
    selected = []
    for doc in docs:
        caps = doc.get("capabilities") or DATASET_TYPE_TO_CAPABILITIES.get(doc.get("dataset_type"), [])
        caps = [cap for cap in TYPE_ORDER if cap in caps and cap in wanted]
        if caps:
            selected.append((doc, caps))

    selected.sort(key=lambda pair: (
        TYPE_ORDER.index(pair[1][0]) if pair[1] else 99,
        str(pair[0].get("display_name") or pair[0].get("filename") or pair[0]["_id"]).lower(),
    ))
    return [(doc, caps) for doc, caps in selected]


async def build_report_data(
    database: AsyncIOMotorDatabase,
    user: dict,
    dataset_ids: Optional[Iterable[str]] = None,
    data_types: Optional[Iterable[str]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """Collect every value the renderers need for one export."""
    owner_id = user_id(user)
    selected = await resolve_datasets(database, owner_id, dataset_ids, data_types, user=user)
    partial_months = _partial_month_labels(start_date, end_date)

    report: Dict[str, Any] = {
        "meta": {
            "title": "Environment Data Report",
            "generated_at": datetime.utcnow(),
            "user_email": user_field(user, "email", "username"),
            "user_name": user_field(user, "full_name", "name"),
            "start_date": _clean_dt(start_date),
            "end_date": _clean_dt(end_date),
            "data_types": [t for t in TYPE_ORDER if t in set(data_types or TYPE_ORDER)],
            "dataset_ids": [str(doc["_id"]) for doc, _ in selected],
            "datasets": [],
        },
        "overview": [],
        "stations": [],
        "monthly": [],
        "low_do": [],
        "do_summary": [],
        "anomalies": [],
        "anomaly_totals": [],
        "outlooks": [],
        "outlook_coverage": [],
        "data_quality": [],
        "notes": [],
    }

    quality_notes_map: Dict[str, List[str]] = {}
    for doc, capabilities in selected:
        public = _dataset_public(doc, capabilities)
        report["meta"]["datasets"].append(public)
        dataset_id = public["id"]
        capability_set = set(capabilities)
        dataset_last = None
        water_stations: List[dict] = []
        quality_extras: List[str] = []

        # Anomalies and outlooks are stored per dataset (a weather dataset mixes
        # temperature and rainfall parameters), so fetch them once and keep only
        # the parameters that belong to the selected capabilities.
        anomaly_stats = await anomaly_statistics(
            database, dataset_id, start_date, end_date
        )
        anomaly_stats = {
            key: item for key, item in anomaly_stats.items()
            if PARAMETER_CAPABILITY.get(item.get("parameter")) in capability_set
        }
        flagged = sum(item.get("anomalies", 0) for item in anomaly_stats.values())
        scanned = sum(item.get("total", 0) for item in anomaly_stats.values())
        if flagged:
            docs = await anomaly_records(
                database, dataset_id, start_date, end_date,
                limit=ANOMALIES_PER_DATASET * 2, most_severe=True,
            )
            for item in docs:
                capability = PARAMETER_CAPABILITY.get(item.get("parameter"))
                if capability in capability_set:
                    report["anomalies"].append(_anomaly_row(item, public, capability))

        forecasts = await forecast_documents(database, dataset_id)
        for item in forecasts:
            capability = PARAMETER_CAPABILITY.get(item.get("parameter"))
            if capability in capability_set:
                row = _outlook_row(item, public, capability)
                if row:
                    report["outlooks"].append(row)

        for capability in capabilities:
            station_rows = await station_statistics(
                database, dataset_id, capability, start_date, end_date
            )
            completeness = await parameter_completeness(
                database, dataset_id, capability, start_date, end_date
            )
            monthly = await monthly_statistics(
                database, dataset_id, capability, start_date, end_date
            )

            total = next(iter(completeness.values()), {}).get("total") if completeness else None
            if total is None:
                total = sum(row.get("count") or 0 for row in station_rows)
            headline = {
                "air_quality": "aqi",
                "water_quality": "wqi",
                "temperature": "temperature",
                "rainfall": "precipitation",
            }[capability]
            headline_info = completeness.get(headline) or {}
            scored_rows = headline_info.get("present")
            if scored_rows is None:
                scored_rows = sum(row.get("scored_count") or 0 for row in station_rows)
            coverage_pct = round(scored_rows / total * 100, 1) if total else 0.0
            summary = _short_summary(station_rows, capability)
            mean_category = _category_for_value(capability, summary.get("mean_value"))
            latest_category = (
                summary.get("category") if summary.get("latest_value") is not None else None
            )
            min_key = MIN_VALUE_KEY.get(capability)
            if capability == "water_quality":
                water_stations = station_rows
                dataset_last = max(
                    (r.get("latest_ts") for r in station_rows if r.get("latest_ts")),
                    default=dataset_last,
                )

            report["overview"].append({
                "dataset_id": dataset_id,
                "dataset_name": public["name"],
                "data_type": capability,
                "data_type_label": TYPE_LABELS.get(capability, capability),
                "station_count": len(station_rows),
                "row_count": total,
                "scored_rows": scored_rows,
                "start_date": min((r.get("first_ts") for r in station_rows if r.get("first_ts")), default=None),
                "end_date": max((r.get("latest_ts") for r in station_rows if r.get("latest_ts")), default=None),
                "coverage_pct": coverage_pct,
                "headline_parameter": headline,
                "headline_label": _parameter_label(headline),
                "unit": _unit(headline),
                "missing": {
                    param: info.get("missing_pct", 0.0)
                    for param, info in completeness.items()
                    if info.get("in_source") is not False
                },
                "not_in_source": [
                    param for param, info in completeness.items()
                    if info.get("in_source") is False
                ],
                "anomaly_count": flagged,
                "scanned_count": scanned,
                "mean_category": mean_category,
                "latest_category": latest_category,
                **summary,
                "category": mean_category,
            })

            for row in station_rows:
                latest, mean, worst, latest_ts, worst_ts, category = station_value(row, capability)
                mean_category = _category_for_value(capability, mean)
                rank_text, rank_position, rank_of = (
                    _rank_parts(row) if capability == "water_quality" else (None, None, None)
                )
                if capability != "water_quality":
                    dataset_last = max(
                        (value for value in (dataset_last, latest_ts) if value),
                        default=None,
                    )
                report["stations"].append({
                    "dataset_id": dataset_id,
                    "dataset_name": public["name"],
                    "data_type": capability,
                    "data_type_label": TYPE_LABELS.get(capability, capability),
                    "location": row.get("location"),
                    "location_label": display_location(row.get("location")),
                    "sample_count": row.get("count"),
                    "scored_count": (
                        row.get("scored_count")
                        if row.get("scored_count") is not None else row.get("count")
                    ),
                    "first_date": row.get("first_ts"),
                    "last_date": latest_ts,
                    "latest_value": _round(latest),
                    "latest_category": category if latest is not None else None,
                    "mean_value": _round(mean),
                    "mean_category": mean_category,
                    "category": mean_category,
                    "min_value": _round(row.get(min_key)) if min_key else None,
                    "max_value": _round(worst),
                    "max_date": worst_ts,
                    "unit": _unit(headline),
                    "rank": rank_text,
                    "rank_position": rank_position,
                    "rank_of": rank_of,
                    "rank_samples": row.get("rank_samples") if capability == "water_quality" else None,
                    "best_use_class": (row.get("latest_cpcb") or {}).get("class")
                    if isinstance(row.get("latest_cpcb"), dict) else None,
                    "bacteriological_flag": row.get("bacteriological_flag"),
                    "min_do": _round(row.get("min_do")),
                    "do_flag": row.get("do_flag"),
                    "max_bod": _round(row.get("max_bod")),
                    "max_coliform": _round(row.get("max_coliform")),
                })

            for row in monthly:
                parameter = row.get("parameter")
                report["monthly"].append({
                    "dataset_id": dataset_id,
                    "dataset_name": public["name"],
                    "data_type": capability,
                    "data_type_label": TYPE_LABELS.get(capability, capability),
                    "parameter": parameter,
                    "parameter_label": _parameter_label(parameter or ""),
                    "unit": _unit(parameter or ""),
                    "location": row.get("location"),
                    "location_label": display_location(row.get("location")),
                    "month": row.get("month"),
                    "month_date": _month_date(row.get("month")),
                    "partial": row.get("month") in partial_months,
                    "mean": _round(row.get("mean")),
                    "min": _round(row.get("min")),
                    "max": _round(row.get("max")),
                    "count": row.get("count"),
                    "scored_count": row.get("scored_count"),
                })

            report["notes"].append(
                f"{public['name']} · {TYPE_LABELS.get(capability, capability)}: "
                f"{len(station_rows)} stations, {total or 0:,} rows in the selected window."
            )

        # Stale outlooks point at months already covered by the observations;
        # they are backtest artefacts, not forecasts for the future. Same-month
        # targets are still usable, so the cutoff is the first of the last month.
        dataset_month = (
            dataset_last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if dataset_last else None
        )
        for row in report["outlooks"]:
            if row["dataset_id"] == dataset_id and row.get("target_date") and dataset_month:
                row["stale"] = row["target_date"] < dataset_month

        if "water_quality" in capability_set and water_stations:
            present = {
                (row.get("location"), row.get("parameter"))
                for row in report["outlooks"] if row["dataset_id"] == dataset_id
            }
            month_counts = await monthly_parameter_counts(
                database, dataset_id, ["wqi", "do", "total_coliform"],
            )
            missing_eligible = [
                (station.get("location"), parameter)
                for station in water_stations
                for parameter in ("wqi", "do", "total_coliform")
                if (station.get("location"), parameter) not in present
                and (month_counts.get((station.get("location"), parameter)) or 0) >= MIN_MONTHS_FOR_OUTLOOK
            ]
            if missing_eligible:
                generated = await _generate_missing_water_outlooks(
                    database, dataset_id, missing_eligible
                )
                for item in generated:
                    row = _outlook_row(item, public, "water_quality")
                    if row:
                        if dataset_month and row.get("target_date"):
                            row["stale"] = row["target_date"] < dataset_month
                        report["outlooks"].append(row)
                        present.add((item.get("location"), item.get("parameter")))
            missing_slots = sparse_slots = unexplained_slots = 0
            missing_stations = []
            for station in water_stations:
                location = station.get("location")
                covered = 0
                for parameter in ("wqi", "do", "total_coliform"):
                    if (location, parameter) in present:
                        covered += 1
                        continue
                    missing_slots += 1
                    if (month_counts.get((location, parameter)) or 0) < MIN_MONTHS_FOR_OUTLOOK:
                        sparse_slots += 1
                    else:
                        unexplained_slots += 1
                if covered == 0:
                    missing_stations.append(location)
            report["outlook_coverage"].append({
                "dataset_id": dataset_id,
                "dataset_name": public["name"],
                "station_count": len(water_stations),
                "stations_with_outlook": len(water_stations) - len(missing_stations),
                "missing_stations": missing_stations,
                "missing_station_labels": [display_location(name) for name in missing_stations],
                "missing_slots": missing_slots,
                "sparse_slots": sparse_slots,
                "unexplained_slots": unexplained_slots,
                "min_months": MIN_MONTHS_FOR_OUTLOOK,
            })

        if "water_quality" in capability_set:
            coliform = await _coliform_stats(database, dataset_id)
            if coliform.get("total"):
                quality_extras.append(
                    f"Total coliform reaches {coliform['max']:,.0f} MPN/100 mL; "
                    f"{coliform['above_1e7']:,} values exceed 10^7. Values are retained as "
                    "reported (no unit conversion); verify the source units."
                )
            with_reading = sum(
                1 for row in water_stations if row.get("latest_coliform") is not None
            )
            failing = sum(
                1 for row in water_stations
                if (row.get("bacteriological_flag") or "").startswith("fails Class C")
            )
            if with_reading:
                quality_extras.append(
                    f"Bacteriological flag: {failing} of {with_reading} stations with a coliform "
                    "reading exceed 5,000 MPN/100 mL on their latest sample (Class C limit)."
                )
            critical_do = sum(
                1 for row in water_stations
                if (row.get("do_flag") or "").startswith("critical")
            )
            low_do = sum(
                1 for row in water_stations
                if (row.get("do_flag") or "").startswith("low DO")
            )
            if water_stations:
                quality_extras.append(
                    f"Dissolved oxygen (absolute, not anomaly-relative): {critical_do} stations "
                    f"below 2 mg/L and {low_do} more between 2 and 4 mg/L on their worst sample "
                    "in the window."
                )
            do_samples = await extreme_do_samples(
                database, dataset_id, start_date, end_date, limit=6
            )
            for sample in do_samples:
                report["low_do"].append({
                    "dataset_id": dataset_id,
                    "dataset_name": public["name"],
                    "data_type": "water_quality",
                    "location": sample.get("location"),
                    "location_label": display_location(sample.get("location")),
                    "value": _round(sample.get("do"), 3),
                    "timestamp": _clean_dt(sample.get("timestamp")),
                })
            report["do_summary"].append({
                "dataset_id": dataset_id,
                "dataset_name": public["name"],
                "critical": critical_do,
                "low": low_do,
                "below_one": sum(
                    1 for row in water_stations
                    if row.get("min_do") is not None and row["min_do"] < 1
                ),
            })
            bod_over = sum(
                1 for row in water_stations
                if (row.get("max_bod") or 0) > PLAUSIBILITY_CAPS["bod"]
            )
            coliform_over = sum(
                1 for row in water_stations
                if (row.get("max_coliform") or 0) > PLAUSIBILITY_CAPS["total_coliform"]
            )
            do_over = sum(
                1 for row in water_stations
                if (row.get("max_do") or 0) > PLAUSIBILITY_CAPS["do"]
            )
            if bod_over or coliform_over or do_over:
                quality_extras.append(
                    "Plausibility screen (DO >15 mg/L, BOD >500 mg/L, total coliform "
                    f">100,000,000 MPN/100 mL): {bod_over} BOD, {coliform_over} coliform and "
                    f"{do_over} DO station(s) exceed a cap; values are retained but should be "
                    "treated as suspect."
                )
            scored = sum(row.get("scored_count") or 0 for row in water_stations)
            samples = sum(row.get("count") or 0 for row in water_stations)
            if samples and scored < samples:
                quality_extras.append(
                    f"WQI scored for {scored:,} of {samples:,} rows "
                    f"({scored / samples * 100:.1f}%); rows failing the minimum-parameter rule are blank."
                )

        quality_notes_map[dataset_id] = quality_extras

        report["anomaly_totals"].append({
            "dataset_id": dataset_id,
            "dataset_name": public["name"],
            "data_types": capabilities,
            "data_types_label": ", ".join(TYPE_LABELS.get(cap, cap) for cap in capabilities),
            "flagged": flagged,
            "scanned": scanned,
            "rate_pct": round(flagged / scanned * 100, 2) if scanned else 0.0,
            "parameters": sorted(anomaly_stats.values(), key=lambda item: -item.get("anomalies", 0)),
        })

    report["anomalies"].sort(
        key=lambda row: (
            EFFECT_ORDER.get(row.get("effect") or "unusual", 1),
            SEVERITY_ORDER.get(row.get("severity") or "", 9),
            -abs(row.get("score") or 0),
        )
    )
    report["outlooks"].sort(
        key=lambda row: (row.get("data_type") or "", row.get("location") or "", row.get("parameter") or "")
    )

    for doc, _ in selected:
        report["data_quality"].append(
            _data_quality_row(doc, quality_notes_map.get(str(doc["_id"])))
        )

    report["meta"]["selection"] = {
        "dataset_count": len(selected),
        "station_count": len({(row["dataset_id"], row["location"]) for row in report["stations"]}),
        # A weather dataset serves both temperature and rainfall from the same
        # documents; count the larger capability total once, not twice.
        "row_count": sum(
            max(
                (row.get("row_count") or 0)
                for row in report["overview"]
                if row["dataset_id"] == str(dataset["_id"])
            ) if any(row["dataset_id"] == str(dataset["_id"]) for row in report["overview"]) else 0
            for dataset, _ in selected
        ),
        "anomaly_count": sum(row.get("flagged", 0) for row in report["anomaly_totals"]),
        "outlook_count": len(report["outlooks"]),
    }
    notes = _method_notes(report["meta"]["data_types"])
    stale = sum(1 for row in report["outlooks"] if row.get("stale"))
    weaker = sum(
        1 for row in report["outlooks"]
        if row.get("skill_pct") is not None and not row.get("beats_baseline")
    )
    if report["outlooks"]:
        notes.append(
            f"{len(report['outlooks'])} outlooks are included; {len(report['outlooks']) - weaker} beat "
            f"persistence and {weaker} are worse than it (flagged, not hidden). "
            f"{stale} target dates fall before the last observation and are stale."
        )
    for coverage in report["outlook_coverage"]:
        if coverage["missing_stations"]:
            notes.append(
                f"{coverage['dataset_name']}: {len(coverage['missing_stations'])} of "
                f"{coverage['station_count']} stations have no outlook. "
                f"{coverage['sparse_slots']} station-parameter series have fewer than "
                f"{coverage['min_months']} monthly points; {coverage['unexplained_slots']} have "
                "enough points but no stored forecast."
            )
    report["meta"]["notes"] = notes
    return report


async def _dataset_bounds(database, dataset_id: str, capabilities: List[str]):
    """First and last stored timestamp across a dataset's capabilities."""
    firsts, lasts = [], []
    for capability in capabilities:
        collection = collection_for(database, capability)
        rows = await collection.aggregate([
            {"$match": {"dataset_id": dataset_id}},
            {"$group": {"_id": None, "first": {"$min": "$timestamp"}, "last": {"$max": "$timestamp"}}},
        ]).to_list(length=1)
        if rows:
            if rows[0].get("first"):
                firsts.append(rows[0]["first"])
            if rows[0].get("last"):
                lasts.append(rows[0]["last"])
    return (min(firsts) if firsts else None, max(lasts) if lasts else None)


async def preview_report(
    database: AsyncIOMotorDatabase,
    user: dict,
    dataset_ids: Optional[Iterable[str]] = None,
    data_types: Optional[Iterable[str]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """Lightweight counts for the Reports UI (no monthly/anomaly/forecast scan)."""
    owner_id = user_id(user)
    available_pairs = await resolve_datasets(database, owner_id, None, None, user=user)
    selected_pairs = await resolve_datasets(database, owner_id, dataset_ids, data_types, user=user)
    selected_ids = {str(doc["_id"]) for doc, _ in selected_pairs}

    available = []
    for doc, capabilities in available_pairs:
        first, last = await _dataset_bounds(database, str(doc["_id"]), capabilities)
        available.append({
            **_dataset_public(doc, capabilities),
            "selected": str(doc["_id"]) in selected_ids,
            "first_date": first,
            "last_date": last,
        })

    selected_rows = []
    station_keys = set()
    row_total = 0
    firsts, lasts = [], []
    for doc, capabilities in selected_pairs:
        dataset_id = str(doc["_id"])
        public = _dataset_public(doc, capabilities)
        dataset_total = 0
        for capability in capabilities:
            stats = await station_statistics(
                database, dataset_id, capability, start_date, end_date
            )
            completeness = await parameter_completeness(
                database, dataset_id, capability, start_date, end_date
            )
            total = next(iter(completeness.values()), {}).get("total")
            if total is None:
                total = sum(row.get("count") or 0 for row in stats)
            dataset_total = max(dataset_total, total or 0)
            for row in stats:
                station_keys.add((dataset_id, row.get("location")))
            row_first, row_last = await _dataset_bounds(database, dataset_id, [capability])
            firsts.append(row_first)
            lasts.append(row_last)
            selected_rows.append({
                "dataset_id": dataset_id,
                "dataset_name": public["name"],
                "data_type": capability,
                "data_type_label": TYPE_LABELS.get(capability, capability),
                "station_count": len(stats),
                "row_count": total or 0,
                "first_date": row_first,
                "last_date": row_last,
            })
        row_total += dataset_total

    warnings = []
    if not selected_pairs:
        warnings.append("No datasets match this selection.")
    elif row_total == 0:
        warnings.append("No data for this selection in the chosen date range.")

    bounds_first = min((value for value in firsts if value), default=None)
    bounds_last = max((value for value in lasts if value), default=None)
    return {
        "available": available,
        "selected": selected_rows,
        "totals": {
            "dataset_count": len(selected_pairs),
            "station_count": len(station_keys),
            "row_count": row_total,
        },
        "date_bounds": {"first": bounds_first, "last": bounds_last},
        "warnings": warnings,
    }


def _method_notes(data_types: List[str]) -> List[str]:
    selected = set(data_types)
    notes: List[str] = []
    if "air_quality" in selected:
        notes.append(
            "AQI follows the CPCB continuous breakpoint method; PM2.5 30-60 µg/m³ maps "
            "continuously to 50-100 rather than using the integer table edge (31-60 -> 51-100), "
            "so no concentration falls into a gap. CO is stored in µg/m³ and converted to the "
            "mg/m³ breakpoint scale before its sub-index is computed. The dominant pollutant is "
            "the one with the highest sub-index."
        )
    if "water_quality" in selected:
        notes.extend([
            "WQI is a weighted arithmetic index on a 0-200 scale (higher is worse, capped at 200). "
            "The headline WQI uses the core set (pH, DO, BOD all required); the extended WQI adds the "
            "other measured parameters when at least three are present.",
            "pH sub-index uses the absolute deviation from 7 (|pH - 7| / 1.5).",
            f"Station ranks use mean WQI over the selected window and only include stations with at "
            f"least {MIN_SAMPLES_FOR_RANK} scored samples; a rank never appears without its sample count.",
            "The bacteriological flag compares each station's latest total coliform with the Class C "
            "limit of 5,000 MPN/100 mL; it is a latest-sample flag, not a window average.",
            "Low-DO flags use absolute thresholds on the worst sample in the window (<2 mg/L "
            "'critical', 2-4 mg/L 'low'); they are independent of anomaly detection.",
            "Import plausibility caps (configurable per upload) blank values outside "
            f"DO {_fmt(dataset_config.RANGES['water_quality']['do'][0])}-"
            f"{_fmt(dataset_config.RANGES['water_quality']['do'][1])} mg/L, "
            f"BOD 0-{_fmt(dataset_config.RANGES['water_quality']['bod'][1])} mg/L and "
            f"total coliform 0-{_fmt(dataset_config.RANGES['water_quality']['total_coliform'][1])} MPN/100 mL.",
        ])
    if selected & {"temperature", "rainfall"}:
        notes.append(
            "Temperature and rainfall summaries use the stored daily values; IMD files merge on date "
            "and leave missing days blank rather than zero."
        )
    if "rainfall" in selected:
        notes.append(
            "Rain chance is climatological (roughly +/-12 percentage points), not a deterministic forecast. The outlook also reports a leave-one-year-out Brier score against the constant base rate and a 95% Wilson interval."
        )
    notes.append(
        "Anomalies are robust z-scores (median/MAD) for water and weather, and Isolation Forest for "
        "air quality. Water series need at least 15 points and weather series at least 50; water and "
        "weather flag |robust z| > 3, while air uses Isolation Forest with 2% contamination. The "
        "expected range is descriptive: for Isolation Forest it is the parameter's median +/- 3 robust "
        "SD, not the model boundary. Ranges are fitted per station on its full stored history, not the "
        "report window, while flagged samples listed here are limited to the window. Air anomalies are "
        "multivariate pollutant outliers, not AQI day-to-day change alerts, so a large AQI swing can "
        "still be unremarkable if the pollutant levels remain within the station's normal range. "
        "Deteriorations are listed before improvements; a low WQI flag means unusually good water, not "
        "a hazard."
    )
    if "water_quality" in selected:
        notes.append(
            "Outlooks require at least "
            f"{MIN_MONTHS_FOR_OUTLOOK} monthly points and are evaluated rolling-origin against "
            "persistence. A candidate that loses to the persistence baseline at the 1-month "
            "horizon is replaced by persistence and claims no skill. Intervals are 80% prediction "
            "intervals."
        )
        notes.append(
            "Forecast outlooks are generated from each station's full stored history; the report "
            "date range does not filter or retrain them."
        )
    return notes
