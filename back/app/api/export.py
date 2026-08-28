import io
import csv
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db

router = APIRouter(prefix="/api/export", tags=["export"])


def get_database() -> AsyncIOMotorDatabase:
    return db.db


def _generate_csv(rows: list, fieldnames: list) -> io.StringIO:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    return output


@router.get("/aqi/{dataset_id}")
async def export_aqi_csv(
    dataset_id: str,
    location: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
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
    
    cursor = database.air_quality.find(query).sort("timestamp", 1)
    rows = await cursor.to_list(length=None)
    
    if not rows:
        raise HTTPException(status_code=404, detail="No data found for export")
    
    fieldnames = [
        "timestamp", "location", "aqi", "aqi_category", "dominant_pollutant",
        "pm25", "pm10", "no2", "so2", "co", "o3"
    ]
    
    csv_rows = []
    for r in rows:
        pv = r.get("pollutant_values", {})
        csv_rows.append({
            "timestamp": r.get("timestamp"),
            "location": r.get("location"),
            "aqi": r.get("aqi"),
            "aqi_category": r.get("aqi_category"),
            "dominant_pollutant": r.get("dominant_pollutant"),
            "pm25": pv.get("pm25"),
            "pm10": pv.get("pm10"),
            "no2": pv.get("no2"),
            "so2": pv.get("so2"),
            "co": pv.get("co"),
            "o3": pv.get("o3"),
        })
    
    output = _generate_csv(csv_rows, fieldnames)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=aqi_{dataset_id}.csv"}
    )


@router.get("/anomalies/{dataset_id}")
async def export_anomalies_csv(
    dataset_id: str,
    location: Optional[str] = None,
    parameter: Optional[str] = None,
    only_anomalies: bool = True,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    query = {"dataset_id": dataset_id}
    if location:
        query["location"] = location
    if parameter:
        query["parameter"] = parameter
    if only_anomalies:
        query["is_anomaly"] = True
    
    cursor = database.anomalies.find(query).sort("timestamp", 1)
    rows = await cursor.to_list(length=None)
    
    if not rows:
        raise HTTPException(status_code=404, detail="No anomaly data found for export")
    
    fieldnames = ["timestamp", "location", "parameter", "value", "is_anomaly", "anomaly_score"]
    
    csv_rows = []
    for r in rows:
        csv_rows.append({
            "timestamp": r.get("timestamp"),
            "location": r.get("location"),
            "parameter": r.get("parameter"),
            "value": r.get("value"),
            "is_anomaly": r.get("is_anomaly"),
            "anomaly_score": r.get("anomaly_score"),
        })
    
    output = _generate_csv(csv_rows, fieldnames)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=anomalies_{dataset_id}.csv"}
    )


@router.get("/forecasts/{dataset_id}")
async def export_forecasts_csv(
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
    docs = await cursor.to_list(length=None)
    
    if not docs:
        raise HTTPException(status_code=404, detail="No forecast data found for export")
    
    fieldnames = [
        "location", "parameter", "model_used", "forecast_horizon",
        "prediction_timestamp", "predicted_value", "lower_bound", "upper_bound",
        "mae", "rmse", "training_samples"
    ]
    
    csv_rows = []
    for doc in docs:
        metrics = doc.get("metrics", {})
        for pred in doc.get("predictions", []):
            csv_rows.append({
                "location": doc.get("location"),
                "parameter": doc.get("parameter"),
                "model_used": doc.get("model_used"),
                "forecast_horizon": doc.get("forecast_horizon"),
                "prediction_timestamp": pred.get("timestamp"),
                "predicted_value": pred.get("predicted_value"),
                "lower_bound": pred.get("lower_bound"),
                "upper_bound": pred.get("upper_bound"),
                "mae": metrics.get("mae"),
                "rmse": metrics.get("rmse"),
                "training_samples": metrics.get("training_samples"),
            })
    
    output = _generate_csv(csv_rows, fieldnames)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=forecasts_{dataset_id}.csv"}
    )


@router.get("/raw/{dataset_id}")
async def export_raw_csv(
    dataset_id: str,
    location: Optional[str] = None,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    query = {"dataset_id": dataset_id}
    if location:
        query["location"] = location
    
    cursor = database.air_quality.find(query).sort("timestamp", 1)
    rows = await cursor.to_list(length=None)
    
    if not rows:
        raise HTTPException(status_code=404, detail="No raw data found for export")
    
    fieldnames = [
        "timestamp", "location", "pm25", "pm10", "no2", "so2", "co", "o3"
    ]
    
    csv_rows = []
    for r in rows:
        csv_rows.append({
            "timestamp": r.get("timestamp"),
            "location": r.get("location"),
            "pm25": r.get("pm25"),
            "pm10": r.get("pm10"),
            "no2": r.get("no2"),
            "so2": r.get("so2"),
            "co": r.get("co"),
            "o3": r.get("o3"),
        })
    
    output = _generate_csv(csv_rows, fieldnames)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=raw_{dataset_id}.csv"}
    )