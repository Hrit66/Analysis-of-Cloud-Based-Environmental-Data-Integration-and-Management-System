"""Aggregation queries shared by the dashboard endpoints and the report builder.

Single source of truth: ``analytics.py`` and ``reports/build.py`` both call
these functions, so an exported report can never disagree with what the
dashboard shows. Each function accepts the same dataset/window/location
filters the dashboards use.

Row contracts intentionally keep the legacy dashboard key names (``avg_wqi``,
``count`` ...) and add the extra fields reports need (coverage, latest/worst
sample, rank, best-use class). Nothing is recomputed in the renderers.
"""
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.wqi_calculator import add_station_ranks
from app.services.report_units import PARAMETER_UNITS


# Parameters shown in the per-parameter completeness breakdown. Only columns
# the platform actually stores are listed; a capability can share a collection
# with another capability (IMD temperature + rainfall).
CAPABILITY_PARAMETERS: Dict[str, List[str]] = {
    "air_quality": ["aqi", "pm25", "pm10", "no2", "so2", "co", "o3"],
    "water_quality": [
        "wqi", "ph", "do", "bod", "turbidity", "tds", "hardness", "chlorides",
        "sulfates", "nitrates", "fluorides", "iron", "manganese", "total_coliform",
    ],
    "temperature": ["temperature", "temp_min", "temp_max"],
    "rainfall": ["precipitation"],
}

HEADLINE_PARAMETER: Dict[str, Tuple[str, str]] = {
    "air_quality": ("aqi", "AQI"),
    "water_quality": ("wqi", "WQI"),
    "temperature": ("temperature", "temperature"),
    "rainfall": ("precipitation", "precipitation"),
}


def collection_for(database: AsyncIOMotorDatabase, capability: str):
    return database.water_quality if capability == "water_quality" else database.air_quality


def inclusive_end(value):
    """Treat a midnight end date as the whole calendar day (inclusive)."""
    if isinstance(value, datetime) and value.time() == datetime.min.time():
        return datetime.combine(value.date(), time.max)
    return value


def match_stage(dataset_id: str, start_date=None, end_date=None, location: Optional[str] = None) -> dict:
    match: Dict[str, Any] = {"dataset_id": dataset_id}
    if location:
        match["location"] = location
    if start_date or end_date:
        match["timestamp"] = {}
        if start_date:
            match["timestamp"]["$gte"] = start_date
        if end_date:
            match["timestamp"]["$lte"] = inclusive_end(end_date)
    return match


def _top_timestamp_for(field: str) -> dict:
    return {"$top": {"sortBy": {field: -1}, "output": "$timestamp"}}


def _sum_true(condition: dict) -> dict:
    return {"$sum": {"$cond": [condition, 1, 0]}}


async def station_statistics(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    capability: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> List[dict]:
    """Per-station summary rows (dashboard contract + report extras)."""
    match = match_stage(dataset_id, start_date, end_date, location)
    collection = collection_for(database, capability)

    if capability == "water_quality":
        pipeline = [
            {"$match": match},
            {"$sort": {"timestamp": 1}},
            {"$group": {
                "_id": "$location",
                "count": {"$sum": 1},
                "scored_count": _sum_true({"$ne": ["$wqi", None]}),
                "avg_wqi": {"$avg": "$wqi"},
                "min_wqi": {"$min": "$wqi"},
                "max_wqi": {"$max": "$wqi"},
                "latest_wqi": {"$last": "$wqi"},
                "latest_category": {"$last": "$wqi_category"},
                "latest_ts": {"$last": "$timestamp"},
                "first_ts": {"$first": "$timestamp"},
                "worst_ts": _top_timestamp_for("wqi"),
                "latest_ph": {"$last": "$ph"},
                "latest_do": {"$last": "$do"},
                "latest_bod": {"$last": "$bod"},
                "latest_coliform": {"$last": "$total_coliform"},
                "latest_cpcb": {"$last": "$cpcb_use_class"},
                "min_do": {"$min": "$do"},
                "max_do": {"$max": "$do"},
                "max_bod": {"$max": "$bod"},
                "max_coliform": {"$max": "$total_coliform"},
            }},
            {"$sort": {"_id": 1}},
        ]
        results = await collection.aggregate(pipeline).to_list(length=None)
        for row in results:
            row["location"] = row.pop("_id")
            row["bacteriological_flag"] = _bacteriological_flag(row.get("latest_coliform"))
            row["do_flag"] = _low_do_flag(row.get("min_do"))
        add_station_ranks(results)
        results.sort(key=lambda r: r["location"])
        return results

    if capability == "temperature":
        pipeline = [
            {"$match": match},
            {"$sort": {"timestamp": 1}},
            {"$group": {
                "_id": "$location",
                "count": {"$sum": 1},
                "scored_count": _sum_true({"$ne": [{"$ifNull": ["$temperature", None]}, None]}),
                "avg_temp": {"$avg": "$temperature"},
                "min_temp": {"$min": "$temperature"},
                "max_temp": {"$max": "$temperature"},
                "latest_temp": {"$last": "$temperature"},
                "latest_ts": {"$last": "$timestamp"},
                "first_ts": {"$first": "$timestamp"},
                "worst_ts": _top_timestamp_for("temperature"),
            }},
            {"$sort": {"_id": 1}},
        ]
        results = await collection.aggregate(pipeline).to_list(length=None)
        for row in results:
            row["location"] = row.pop("_id")
        return results

    if capability == "rainfall":
        pipeline = [
            {"$match": match},
            {"$sort": {"timestamp": 1}},
            {"$group": {
                "_id": "$location",
                "count": {"$sum": 1},
                "scored_count": _sum_true({"$ne": [{"$ifNull": ["$precipitation", None]}, None]}),
                "total_precip": {"$sum": "$precipitation"},
                "avg_precip": {"$avg": "$precipitation"},
                "min_precip": {"$min": "$precipitation"},
                "max_precip": {"$max": "$precipitation"},
                "latest_precip": {"$last": "$precipitation"},
                "rainy_count": _sum_true({"$gt": ["$precipitation", 0]}),
                "latest_ts": {"$last": "$timestamp"},
                "first_ts": {"$first": "$timestamp"},
                "worst_ts": _top_timestamp_for("precipitation"),
            }},
            {"$sort": {"_id": 1}},
        ]
        results = await collection.aggregate(pipeline).to_list(length=None)
        for row in results:
            row["location"] = row.pop("_id")
        return results

    pipeline = [
        {"$match": match},
        {"$sort": {"timestamp": 1}},
        {"$group": {
            "_id": "$location",
            "count": {"$sum": 1},
            "scored_count": _sum_true({"$ne": [{"$ifNull": ["$aqi", None]}, None]}),
            "avg_aqi": {"$avg": "$aqi"},
            "min_aqi": {"$min": "$aqi"},
            "max_aqi": {"$max": "$aqi"},
            "latest_aqi": {"$last": "$aqi"},
            "latest_category": {"$last": "$aqi_category"},
            "latest_ts": {"$last": "$timestamp"},
            "first_ts": {"$first": "$timestamp"},
            "worst_ts": _top_timestamp_for("aqi"),
            "categories": {"$push": "$aqi_category"},
            "dominant_pollutants": {"$push": "$dominant_pollutant"},
        }},
        {"$sort": {"_id": 1}},
    ]
    results = await collection.aggregate(pipeline).to_list(length=None)
    for row in results:
        row["location"] = row.pop("_id")
        categories = row.pop("categories", []) or []
        pollutants = row.pop("dominant_pollutants", []) or []
        cat_counts: Dict[str, int] = {}
        for category in categories:
            if category:
                cat_counts[category] = cat_counts.get(category, 0) + 1
        row["category_distribution"] = cat_counts
        poll_counts: Dict[str, int] = {}
        for pollutant in pollutants:
            if pollutant:
                poll_counts[pollutant] = poll_counts.get(pollutant, 0) + 1
        row["dominant_pollutant_distribution"] = poll_counts
    return results


def _low_do_flag(min_do) -> Optional[str]:
    """Absolute dissolved-oxygen flag for the worst sample in the window."""
    if min_do is None:
        return None
    try:
        value = float(min_do)
    except (TypeError, ValueError):
        return None
    if value < 2:
        return "critical low DO (<2 mg/L)"
    if value < 4:
        return "low DO (<4 mg/L)"
    return None


def _bacteriological_flag(latest_coliform) -> Optional[str]:
    """Best-use bacteriological band of the latest total-coliform sample."""
    if latest_coliform is None:
        return None
    try:
        value = float(latest_coliform)
    except (TypeError, ValueError):
        return None
    if value <= 50:
        return "meets Class A (\u226450 MPN/100 mL)"
    if value <= 500:
        return "Class B band (\u2264500 MPN/100 mL)"
    if value <= 5000:
        return "Class C band (\u22645000 MPN/100 mL)"
    return "fails Class C (>5000 MPN/100 mL)"


async def monthly_statistics(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    capability: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> List[dict]:
    """Station x month aggregates for the headline parameter."""
    parameter, _ = HEADLINE_PARAMETER[capability]
    match = match_stage(dataset_id, start_date, end_date, location)
    collection = collection_for(database, capability)
    field = f"${parameter}"

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "location": "$location",
                "month": {"$dateToString": {"format": "%Y-%m", "date": "$timestamp"}},
            },
            "count": {"$sum": 1},
            "scored_count": _sum_true({"$ne": [{"$ifNull": [field, None]}, None]}),
            "mean": {"$avg": field},
            "min": {"$min": field},
            "max": {"$max": field},
        }},
        {"$sort": {"_id.month": -1, "_id.location": 1}},
    ]
    results = await collection.aggregate(pipeline).to_list(length=None)
    return [
        {
            "location": row["_id"]["location"],
            "month": row["_id"]["month"],
            "count": row["count"],
            "scored_count": row.get("scored_count"),
            "mean": row["mean"],
            "min": row["min"],
            "max": row["max"],
            "parameter": parameter,
        }
        for row in results
    ]


async def parameter_completeness(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    capability: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Total rows and missing count per stored parameter."""
    params = CAPABILITY_PARAMETERS.get(capability, [])
    if not params:
        return {}
    match = match_stage(dataset_id, start_date, end_date, location)
    collection = collection_for(database, capability)
    group: Dict[str, Any] = {"_id": None, "total": {"$sum": 1}}
    for param in params:
        group[param] = _sum_true({"$eq": [{"$ifNull": [f"${param}", None]}, None]})
        group[f"{param}__present"] = _sum_true({"$ne": [{"$ifNull": [f"${param}", None]}, None]})
    results = await collection.aggregate([
        {"$match": match},
        {"$group": group},
    ]).to_list(length=1)

    presence_group: Dict[str, Any] = {"_id": None, "total": {"$sum": 1}}
    for param in params:
        presence_group[f"{param}__any"] = _sum_true(
            {"$ne": [{"$ifNull": [f"${param}", None]}, None]}
        )
    presence_rows = await collection.aggregate([
        {"$match": {"dataset_id": dataset_id}},
        {"$group": presence_group},
    ]).to_list(length=1)
    presence = presence_rows[0] if presence_rows else {}
    presence_total = presence.get("total", 0)
    if not results:
        return {
            param: {
                "total": 0, "missing": 0, "missing_pct": 0.0, "present": 0,
                "in_source": None,
            }
            for param in params
        }

    row = results[0]
    total = row.get("total", 0)
    return {
        param: {
            "total": total,
            "missing": row.get(param, 0),
            "missing_pct": round(row.get(param, 0) / total * 100, 2) if total else 0.0,
            "present": row.get(f"{param}__present", 0),
            "in_source": (
                presence.get(f"{param}__any", 0) > 0
            ) if presence_total else None,
        }
        for param in params
    }


async def extreme_do_samples(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    start_date=None,
    end_date=None,
    limit: int = 6,
) -> List[dict]:
    """Lowest dissolved-oxygen readings in the window, regardless of flags."""
    query = match_stage(dataset_id, start_date, end_date)
    query["do"] = {"$ne": None}
    cursor = (
        database.water_quality.find(query, {"location": 1, "timestamp": 1, "do": 1})
        .sort("do", 1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def anomaly_statistics(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> Dict[str, dict]:
    """Anomaly counts per station x parameter inside the requested window."""
    match = {"dataset_id": dataset_id}
    if location:
        match["location"] = location
    if start_date or end_date:
        match["timestamp"] = {}
        if start_date:
            match["timestamp"]["$gte"] = start_date
        if end_date:
            match["timestamp"]["$lte"] = inclusive_end(end_date)

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"location": "$location", "parameter": "$parameter"},
            "total": {"$sum": 1},
            "anomalies": _sum_true({"$eq": ["$is_anomaly", True]}),
        }},
    ]
    results = await database.anomalies.aggregate(pipeline).to_list(length=None)
    summary: Dict[str, dict] = {}
    for row in results:
        key = f"{row['_id']['location']}_{row['_id']['parameter']}"
        summary[key] = {
            "location": row["_id"]["location"],
            "parameter": row["_id"]["parameter"],
            "total": row["total"],
            "anomalies": row["anomalies"],
            "anomaly_rate": round(row["anomalies"] / row["total"] * 100, 2) if row["total"] else 0,
        }
    return summary


async def anomaly_totals(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> Dict[str, int]:
    """Headline anomaly counts for a window.

    ``flagged_samples`` counts stored detector rows (one per parameter), which
    is what the anomaly table lists. ``anomaly_days`` counts distinct
    station-days with at least one flag; the dashboard card uses that so a
    record flagged on five pollutants is not counted five times.
    """
    match: Dict[str, Any] = {"dataset_id": dataset_id, "is_anomaly": True}
    if location:
        match["location"] = location
    if start_date or end_date:
        match["timestamp"] = {}
        if start_date:
            match["timestamp"]["$gte"] = start_date
        if end_date:
            match["timestamp"]["$lte"] = inclusive_end(end_date)

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": "$location",
            "flagged_samples": {"$sum": 1},
            "days": {"$addToSet": {
                "$dateToString": {
                    "format": "%Y-%m-%d",
                    "date": {"$convert": {
                        "input": "$timestamp",
                        "to": "date",
                        "onError": None,
                        "onNull": None,
                    }},
                }
            }},
        }},
    ]
    rows = await database.anomalies.aggregate(pipeline).to_list(length=None)
    return {
        "flagged_samples": int(sum(row.get("flagged_samples", 0) for row in rows)),
        "anomaly_days": int(sum(
            len([day for day in (row.get("days") or []) if day])
            for row in rows
        )),
    }


async def anomaly_records(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
    limit: Optional[int] = None,
    most_severe: bool = False,
) -> List[dict]:
    """Flagged samples, newest first, with the detector metadata stored on them."""
    query: Dict[str, Any] = {"dataset_id": dataset_id, "is_anomaly": True}
    if location:
        query["location"] = location
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)

    if most_severe:
        pipeline: List[dict] = [
            {"$match": query},
            {"$addFields": {"_abs_score": {"$abs": "$anomaly_score"}}},
            {"$sort": {"_abs_score": -1}},
            {"$project": {"_abs_score": 0}},
        ]
        if limit:
            pipeline.append({"$limit": limit})
        return await database.anomalies.aggregate(pipeline).to_list(length=None)

    cursor = database.anomalies.find(query).sort("timestamp", -1)
    if limit:
        cursor = cursor.limit(limit)
    return await cursor.to_list(length=limit)


async def forecast_documents(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    location: Optional[str] = None,
) -> List[dict]:
    """Latest forecast document per station x parameter (newest first input)."""
    query: Dict[str, Any] = {"dataset_id": dataset_id}
    if location:
        query["location"] = location
    cursor = database.forecasts.find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=None)
    latest: Dict[tuple, dict] = {}
    for doc in docs:
        key = (doc.get("location"), doc.get("parameter"))
        if key not in latest:
            latest[key] = doc
    return list(latest.values())


async def monthly_parameter_counts(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    parameters: List[str],
    start_date=None,
    end_date=None,
    location: Optional[str] = None,
) -> Dict[tuple, Dict[str, int]]:
    """Distinct months with data per station for each parameter (outlook reasons)."""
    match = match_stage(dataset_id, start_date, end_date, location)
    collection = collection_for(database, "water_quality")
    first_group: Dict[str, Any] = {"_id": {"location": "$location", "month": {"$dateToString": {"format": "%Y-%m", "date": "$timestamp"}}}}
    second_group: Dict[str, Any] = {"_id": "$_id.location"}
    for param in parameters:
        condition = {"$ne": [{"$ifNull": [f"${param}", None]}, None]}
        first_group[param] = _sum_true(condition)
        second_group[param] = {"$sum": {"$cond": [{"$gt": [f"${param}", 0]}, 1, 0]}}

    results = await collection.aggregate([
        {"$match": match},
        {"$group": first_group},
        {"$group": second_group},
    ]).to_list(length=None)
    return {
        (row["_id"], param): row.get(param, 0)
        for row in results
        for param in parameters
    }


def station_value(row: dict, capability: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[datetime], Optional[datetime], Optional[str]]:
    """(latest, mean, worst, latest_ts, worst_ts, category) for a summary row."""
    if capability == "water_quality":
        return (row.get("latest_wqi"), row.get("avg_wqi"), row.get("max_wqi"),
                row.get("latest_ts"), row.get("worst_ts"), row.get("latest_category"))
    if capability == "temperature":
        return (row.get("latest_temp"), row.get("avg_temp"), row.get("max_temp"),
                row.get("latest_ts"), row.get("worst_ts"), None)
    if capability == "rainfall":
        return (row.get("latest_precip"), row.get("avg_precip"), row.get("max_precip"),
                row.get("latest_ts"), row.get("worst_ts"), None)
    return (row.get("latest_aqi"), row.get("avg_aqi"), row.get("max_aqi"),
            row.get("latest_ts"), row.get("worst_ts"), row.get("latest_category"))


def headline_unit(parameter: str) -> str:
    return PARAMETER_UNITS.get(parameter, "")
