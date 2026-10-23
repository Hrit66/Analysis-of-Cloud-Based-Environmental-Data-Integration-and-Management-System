from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, Query, HTTPException, Depends
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db
from app.api.auth import get_optional_user
from app.api.guards import require_dataset
from app.models.analytics import AQIResult, AnomalyResult, ForecastResult
from app.services.dashboard_queries import (
    anomaly_statistics,
    anomaly_totals,
    inclusive_end,
    station_statistics,
)
from app.services.forecaster import rain_outlook_from_frame
from app.services.trend_analysis import analyze_trend

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_database() -> AsyncIOMotorDatabase:
    return db.db


@router.get("/aqi/{dataset_id}")
async def get_aqi_results(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    skip: int = 0,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "air_quality", user=user)
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)
    
    total = await database.air_quality.count_documents(query)
    cursor = database.air_quality.find(query).sort("timestamp", -1).skip(skip).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return {
        "items": results,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


@router.get("/aqi/{dataset_id}/summary")
async def get_aqi_summary(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "air_quality", user=user)
    return await station_statistics(database, dataset_id, "air_quality", location=location)


@router.get("/anomalies/{dataset_id}")
async def get_anomalies(
    dataset_id: str,
    location: Optional[str] = None,
    parameter: Optional[str] = None,
    only_anomalies: bool = True,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    skip: int = 0,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, user=user)
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    if parameter:
        query["parameter"] = parameter
    if only_anomalies:
        query["is_anomaly"] = True
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)
    
    total = await database.anomalies.count_documents(query)
    cursor = database.anomalies.find(query).sort("timestamp", -1).skip(skip).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return {
        "items": results,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


@router.get("/anomalies/{dataset_id}/summary")
async def get_anomaly_summary(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, user=user)
    summary = await anomaly_statistics(database, dataset_id, start_date, end_date, location)
    totals = await anomaly_totals(database, dataset_id, start_date, end_date, location)
    return {"dataset_id": dataset_id, "summary": summary, "totals": totals}


@router.get("/forecasts/{dataset_id}", response_model=List[ForecastResult])
async def get_forecasts(
    dataset_id: str,
    location: Optional[str] = None,
    parameter: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, user=user)
    query = {"dataset_id": dataset_id}
    if location:
        query["location"] = location
    if parameter:
        query["parameter"] = parameter
    
    cursor = database.forecasts.find(query).sort("created_at", -1)
    results = await cursor.to_list(length=None)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results

@router.get("/forecasts/{dataset_id}/latest")
async def get_latest_forecast(
    dataset_id: str,
    location: str,
    parameter: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, user=user)
    forecast = await database.forecasts.find_one(
        {"dataset_id": dataset_id, "location": location, "parameter": parameter},
        sort=[("created_at", -1)]
    )
    
    if not forecast:
        raise HTTPException(status_code=404, detail="Forecast not found")
    
    forecast["id"] = str(forecast.pop("_id"))
    return forecast


@router.get("/trends/{dataset_id}")
async def get_trends(
    dataset_id: str,
    location: str,
    parameter: str,
    days: int = 30,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, user=user)
    start_date = datetime.utcnow() - timedelta(days=days)
    
    pipeline = [
        {"$match": {
            "dataset_id": dataset_id,
            "location": location,
            "timestamp": {"$gte": start_date},
        }},
        {"$sort": {"timestamp": 1}},
        {"$project": {
            "timestamp": 1,
            "value": f"${parameter}",
        }},
    ]
    
    results = await database.air_quality.aggregate(pipeline).to_list(length=None)
    
    return {
        "dataset_id": dataset_id,
        "location": location,
        "parameter": parameter,
        "data": [{"timestamp": r["timestamp"], "value": r["value"]} for r in results if r.get("value") is not None],
    }


@router.get("/temperature/{dataset_id}")
async def get_temperature_results(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "temperature", user=user)
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)
    
    cursor = database.air_quality.find(query).sort("timestamp", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results


@router.get("/temperature/{dataset_id}/summary")
async def get_temperature_summary(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "temperature", user=user)
    return await station_statistics(database, dataset_id, "temperature", location=location)


@router.get("/date-range/{dataset_id}")
async def get_dataset_date_range(
    dataset_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    dataset = await require_dataset(database, dataset_id, user=user)
    
    collection = database.water_quality if dataset.get("dataset_type") == "water_quality" else database.air_quality
    
    pipeline = [
        {"$match": {"dataset_id": dataset_id}},
        {"$group": {"_id": None, "first": {"$min": "$timestamp"}, "latest": {"$max": "$timestamp"}}},
    ]
    results = await collection.aggregate(pipeline).to_list(length=1)
    
    if not results:
        return {"first": None, "latest": None}
    
    return {"first": results[0]["first"], "latest": results[0]["latest"]}


@router.get("/rainfall/{dataset_id}")
async def get_rainfall_results(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "rainfall", user=user)
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)
    
    cursor = database.air_quality.find(query).sort("timestamp", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results


@router.get("/rainfall/{dataset_id}/summary")
async def get_rainfall_summary(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "rainfall", user=user)
    return await station_statistics(database, dataset_id, "rainfall", location=location)


@router.get("/rainfall/{dataset_id}/outlook")
async def get_rainfall_outlook(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "rainfall", user=user)
    query = {"dataset_id": dataset_id}
    if location:
        query["location"] = location

    docs = await database.air_quality.find(query).sort("timestamp", 1).to_list(length=None)
    if not docs:
        raise HTTPException(status_code=404, detail="No rainfall observations found")

    resolved_location = location or docs[0].get("location")
    frame = pd.DataFrame([
        {
            "timestamp": doc.get("timestamp"),
            "location": doc.get("location"),
            "precipitation": doc.get("precipitation"),
        }
        for doc in docs
    ])
    forecast_query = {
        "dataset_id": dataset_id,
        "parameter": "precipitation",
        "location": resolved_location,
    }
    forecast = await database.forecasts.find_one(
        forecast_query, sort=[("created_at", -1)]
    )
    return rain_outlook_from_frame(
        frame,
        resolved_location,
        model_metrics=(forecast or {}).get("metrics"),
    )


@router.get("/wqi/{dataset_id}")
async def get_wqi_results(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "water_quality", user=user)
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)
    
    cursor = database.water_quality.find(query).sort("timestamp", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results


@router.get("/wqi/{dataset_id}/summary")
async def get_wqi_summary(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "water_quality", user=user)
    return await station_statistics(
        database, dataset_id, "water_quality", start_date, end_date, location
    )


@router.get("/wqi/{dataset_id}/trend")
async def get_wqi_trend(
    dataset_id: str,
    location: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    await require_dataset(database, dataset_id, "water_quality", user=user)
    query = {"dataset_id": dataset_id, "location": location}
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = inclusive_end(end_date)

    cursor = database.water_quality.find(
        query, {"timestamp": 1, "wqi": 1}
    ).sort("timestamp", 1)
    docs = await cursor.to_list(length=None)
    result = analyze_trend(
        [doc.get("timestamp") for doc in docs],
        [doc.get("wqi") for doc in docs],
    )
    return {
        "dataset_id": dataset_id,
        "location": location,
        "parameter": "wqi",
        **result,
    }