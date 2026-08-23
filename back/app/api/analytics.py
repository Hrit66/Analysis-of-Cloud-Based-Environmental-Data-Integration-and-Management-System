from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException, Depends
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db
from app.models.analytics import AQIResult, AnomalyResult, ForecastResult

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_database() -> AsyncIOMotorDatabase:
    return db.db


@router.get("/aqi/{dataset_id}", response_model=List[AQIResult])
async def get_aqi_results(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            query["timestamp"]["$gte"] = start_date
        if end_date:
            query["timestamp"]["$lte"] = end_date
    
    cursor = database.air_quality.find(query).sort("timestamp", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results


@router.get("/aqi/{dataset_id}/summary")
async def get_aqi_summary(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    match_stage = {"dataset_id": dataset_id}
    if location:
        match_stage["location"] = location
    
    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": "$location",
            "avg_aqi": {"$avg": "$aqi"},
            "max_aqi": {"$max": "$aqi"},
            "min_aqi": {"$min": "$aqi"},
            "count": {"$sum": 1},
            "categories": {"$push": "$aqi_category"},
            "dominant_pollutants": {"$push": "$dominant_pollutant"},
        }},
    ]
    
    results = await database.air_quality.aggregate(pipeline).to_list(length=None)
    
    for r in results:
        r["location"] = r.pop("_id")
        cat_counts = {}
        for cat in r["categories"]:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        r["category_distribution"] = cat_counts
        
        poll_counts = {}
        for poll in r["dominant_pollutants"]:
            if poll:
                poll_counts[poll] = poll_counts.get(poll, 0) + 1
        r["dominant_pollutant_distribution"] = poll_counts
        del r["categories"]
        del r["dominant_pollutants"]
    
    return results


@router.get("/anomalies/{dataset_id}", response_model=List[AnomalyResult])
async def get_anomalies(
    dataset_id: str,
    location: Optional[str] = None,
    parameter: Optional[str] = None,
    only_anomalies: bool = True,
    limit: int = 1000,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    query = {"dataset_id": dataset_id}
    
    if location:
        query["location"] = location
    if parameter:
        query["parameter"] = parameter
    if only_anomalies:
        query["is_anomaly"] = True
    
    cursor = database.anomalies.find(query).sort("timestamp", -1).limit(limit)
    results = await cursor.to_list(length=limit)
    
    for r in results:
        r["id"] = str(r.pop("_id"))
    
    return results


@router.get("/anomalies/{dataset_id}/summary")
async def get_anomaly_summary(dataset_id: str, database: AsyncIOMotorDatabase = Depends(get_database)):
    pipeline = [
        {"$match": {"dataset_id": dataset_id}},
        {"$group": {
            "_id": {"location": "$location", "parameter": "$parameter"},
            "total": {"$sum": 1},
            "anomalies": {"$sum": {"$cond": ["$is_anomaly", 1, 0]}},
        }},
    ]
    
    results = await database.anomalies.aggregate(pipeline).to_list(length=None)
    
    summary = {}
    for r in results:
        key = f"{r['_id']['location']}_{r['_id']['parameter']}"
        summary[key] = {
            "location": r["_id"]["location"],
            "parameter": r["_id"]["parameter"],
            "total": r["total"],
            "anomalies": r["anomalies"],
            "anomaly_rate": round(r["anomalies"] / r["total"] * 100, 2) if r["total"] > 0 else 0,
        }
    
    return {"dataset_id": dataset_id, "summary": summary}


@router.get("/forecasts/{dataset_id}", response_model=List[ForecastResult])
async def get_forecasts(
    dataset_id: str,
    location: Optional[str] = None,
    parameter: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
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
):
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
):
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