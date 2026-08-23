import os
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import db
from app.models.dataset import Dataset, DatasetCreate, DatasetStatus
from app.services.pipeline_interface import parse_file, clean_dataframe, dataframe_to_records
from app.services.aqi_calculator import compute_aqi_for_record
from app.services.anomaly_detector import detect_anomalies
from app.services.forecaster import generate_multi_location_forecast

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_database() -> AsyncIOMotorDatabase:
    return db.db


async def process_dataset(dataset_id: str, file_path: str, dataset_type: str):
    """Background task to process uploaded dataset."""
    database = db.db
    
    try:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.PROCESSING, "updated_at": datetime.utcnow()}}
        )
        
        raw_df = parse_file(file_path, dataset_type)
        
        cleaned_df, cleaning_report = clean_dataframe(raw_df, dataset_type)
        
        records = dataframe_to_records(cleaned_df, dataset_id, dataset_type)
        
        if dataset_type == "air_quality":
            for record in records:
                aqi_result = compute_aqi_for_record(record)
                record.update(aqi_result)
            
            await database.air_quality.insert_many(records)
            
            anomaly_results = detect_anomalies(cleaned_df)
            if anomaly_results:
                for ar in anomaly_results:
                    ar['dataset_id'] = dataset_id
                await database.anomalies.insert_many(aromaly_results)
            
            forecast_results = generate_multi_location_forecast(cleaned_df)
            for fr in forecast_results:
                if 'error' not in fr:
                    fr['dataset_id'] = dataset_id
                    await database.forecasts.insert_one(fr)
        
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {
                "$set": {
                    "status": DatasetStatus.COMPLETED,
                    "row_count": len(records),
                    "original_columns": list(raw_df.columns),
                    "cleaning_report": cleaning_report,
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        
    except Exception as e:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {
                "$set": {
                    "status": DatasetStatus.FAILED,
                    "error_message": str(e),
                    "updated_at": datetime.utcnow(),
                }
            }
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/upload")
async def upload_dataset(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dataset_type: str = "air_quality",
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    allowed_extensions = {'.csv', '.json', '.xlsx', '.xls'}
    if not any(file.filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(status_code=400, detail="Unsupported file format")
    
    dataset_id = str(ObjectId())
    file_extension = os.path.splitext(file.filename)[1]
    file_path = os.path.join(UPLOAD_DIR, f"{dataset_id}{file_extension}")
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    dataset_create = DatasetCreate(
        filename=file.filename,
        dataset_type=dataset_type,
        original_columns=[],
        row_count=0,
    )
    
    dataset_doc = dataset_create.model_dump()
    dataset_doc["_id"] = ObjectId(dataset_id)
    dataset_doc["status"] = DatasetStatus.UPLOADED
    dataset_doc["created_at"] = datetime.utcnow()
    dataset_doc["updated_at"] = datetime.utcnow()
    
    await database.datasets.insert_one(dataset_doc)
    
    background_tasks.add_task(process_dataset, dataset_id, file_path, dataset_type)
    
    return {"dataset_id": dataset_id, "status": DatasetStatus.UPLOADED, "message": "File uploaded. Processing started in background."}


@router.get("")
async def list_datasets(
    status: DatasetStatus = None,
    limit: int = 50,
    skip: int = 0,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    query = {}
    if status:
        query["status"] = status
    
    cursor = database.datasets.find(query).sort("created_at", -1).skip(skip).limit(limit)
    datasets = await cursor.to_list(length=limit)
    
    for d in datasets:
        d["id"] = str(d.pop("_id"))
    
    return datasets


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, database: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        dataset = await database.datasets.find_one({"_id": ObjectId(dataset_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid dataset ID")
    
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    dataset["id"] = str(dataset.pop("_id"))
    return dataset


@router.get("/{dataset_id}/status")
async def get_dataset_status(dataset_id: str, database: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        dataset = await database.datasets.find_one({"_id": ObjectId(dataset_id)}, {"status": 1, "error_message": 1, "row_count": 1})
    except:
        raise HTTPException(status_code=400, detail="Invalid dataset ID")
    
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    
    return {
        "dataset_id": dataset_id,
        "status": dataset.get("status"),
        "row_count": dataset.get("row_count", 0),
        "error_message": dataset.get("error_message"),
    }


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str, database: AsyncIOMotorDatabase = Depends(get_database)):
    try:
        result = await database.datasets.delete_one({"_id": ObjectId(dataset_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        await database.air_quality.delete_many({"dataset_id": dataset_id})
        await database.anomalies.delete_many({"dataset_id": dataset_id})
        await database.forecasts.delete_many({"dataset_id": dataset_id})
        
        return {"message": "Dataset and associated data deleted"}
    except HTTPException:
        raise
    except:
        raise HTTPException(status_code=400, detail="Invalid dataset ID")