import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

# Filename sanitization
def sanitize_filename(name: str) -> str:
    """Return safe basename: alphanumeric, dots, dashes, underscores only."""
    # Remove path components
    name = os.path.basename(name)
    # Replace non-safe chars with underscore
    name = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Limit length
    if len(name) > 255:
        ext = os.path.splitext(name)[1]
        name = name[:255 - len(ext)] + ext
    return name or "upload"

PROCESSING_TIMEOUT = 300  # 5 minutes
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from bson import ObjectId
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.database import db
from app.api.auth import get_optional_user
from app.models.dataset import Dataset, DatasetCreate, DatasetStatus
from app.services import dataset_config
from app.services.pipeline_interface import (
    parse_file,
    clean_dataframe,
    dataframe_to_records,
    derive_capabilities,
    merge_imd_files,
    merge_river_summary_files,
    imd_parameter_from_source,
)
from app.services.authz import is_platform_admin, readable_query, require_dataset_access
from app.services.quotas import enforce_upload_quota, upload_limit_for, enforce_upload_size_limit, precheck_quotas, estimate_rows_from_bytes
from app.services.upload_limiter import check_upload_rate_limit
from app.services.concurrency import acquire_upload_slot, release_upload_slot
from app.services.station_names import suggest_station_merges
from app.services.type_detector import detect_dataset_type
from app.services.aqi_calculator import compute_aqi_for_record
from app.services.wqi_calculator import calculate_wqi, compute_wqi_for_record
from app.services.anomaly_detector import (
    detect_anomalies,
    detect_water_anomalies,
    detect_weather_anomalies,
    purge_dataset_models as purge_anomaly_models,
)
from app.services.forecaster import (
    generate_multi_location_forecast,
    purge_dataset_models as purge_forecast_models,
)
from app.services.water_forecaster import generate_water_forecasts
from app.services.auth import write_audit
from app.services.dataset_meta import SOURCE_TAGS, source_tag_for
from app.services.job_progress import (
    JobCancelled,
    bind_job,
    cancel_job,
    check_cancelled,
    complete_job,
    create_job,
    fail_job,
    forecast_readiness,
    get_job,
    report_stage,
    reset_job,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

INSERT_BATCH_SIZE = 5000
RETAIN_UPLOAD_FILES = os.getenv("RETAIN_UPLOAD_FILES", "").strip().lower() in {
    "1", "true", "yes"
}


def compute_file_hash(
    content: bytes,
    dataset_type: str = "",
    pipeline_version: Optional[str] = None,
    location: str = "",
) -> str:
    """Idempotency key: bytes + type + location + cleaner version.

    Including the pipeline version means a cleaner fix can re-import the same
    file (a new hash) instead of being silently deduplicated against output
    produced by the old code. The same bytes uploaded under a different
    station/location are a different dataset, not a duplicate.
    """
    version = pipeline_version or dataset_config.PIPELINE_VERSION
    payload = b"|".join([
        content,
        str(dataset_type or "").encode("utf-8"),
        version.encode("utf-8"),
        str(location or "").encode("utf-8"),
    ])
    return hashlib.sha256(payload).hexdigest()


def _parse_config_overrides(raw: Optional[str]) -> Dict[str, List[float]]:
    """Validate the optional per-upload plausibility-range overrides."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"config_overrides is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="config_overrides must be a JSON object")
    overrides: Dict[str, List[float]] = {}
    for column, bounds in data.items():
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise HTTPException(
                status_code=400,
                detail=f"config_overrides[{column}] must be [low, high]",
            )
        try:
            low, high = float(bounds[0]), float(bounds[1])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"config_overrides[{column}] bounds must be numeric",
            )
        if low >= high:
            raise HTTPException(
                status_code=400,
                detail=f"config_overrides[{column}] low must be below high",
            )
        overrides[str(column)] = [low, high]
    return overrides


def _validate_overrides(dataset_type: str, overrides: Dict[str, List[float]]) -> None:
    known = set(dataset_config.RANGES.get(dataset_type, {}))
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"config_overrides has unknown columns for {dataset_type}: {', '.join(unknown)}",
        )


def _normalize_source_tag(value: Optional[str]) -> Optional[str]:
    tag = str(value or "").strip().lower()
    if tag in {"", "not_sure", "unsure", "unknown"}:
        return None
    if tag not in SOURCE_TAGS:
        raise HTTPException(
            status_code=400,
            detail="source_tag must be real, synthetic, modelled, or omitted",
        )
    return tag


def _ownership_fields(user) -> dict:
    if not user:
        return {
            "user_id": None,
            "owner_id": None,
            "org_id": None,
            "visibility": None,
            "shared_with_users": [],
        }
    user_id = str(user.id)
    return {
        "user_id": user_id,
        "owner_id": user_id,
        "org_id": getattr(user, "org_id", None),
        "visibility": "private",
        "shared_with_users": [],
        "license": "unspecified",
    }


async def _dataset_owner(database: AsyncIOMotorDatabase, dataset_id: str) -> Optional[str]:
    try:
        doc = await database.datasets.find_one(
            {"_id": ObjectId(dataset_id)}, {"user_id": 1, "owner_id": 1}
        )
    except Exception:
        return None
    return (doc or {}).get("owner_id") or (doc or {}).get("user_id")


async def _find_active_duplicate(database: AsyncIOMotorDatabase, file_hash: str, owner_id: Optional[str] = None):
    query = {
        "file_hash": file_hash,
        "status": {
            "$in": [
                DatasetStatus.UPLOADED,
                DatasetStatus.PROCESSING,
                DatasetStatus.COMPLETED,
            ]
        },
    }
    if owner_id:
        # Signed-in uploads only match their own files; a duplicate uploaded by
        # another user must not leak that dataset to this caller.
        query["user_id"] = owner_id
    return await database.datasets.find_one(query)


async def _insert_in_batches(collection, records: list, track_progress: bool = False):
    """Insert records in batches to avoid oversized single insert_many payloads."""
    total_batches = max(1, (len(records) + INSERT_BATCH_SIZE - 1) // INSERT_BATCH_SIZE)
    for batch_index, i in enumerate(range(0, len(records), INSERT_BATCH_SIZE), start=1):
        if track_progress:
            check_cancelled()
            report_stage(
                "saving",
                label=f"Saving (batch {batch_index} of {total_batches})",
                percent=60 + round(24 * batch_index / total_batches),
                counts={"batch": batch_index, "batches_total": total_batches},
            )
        batch = records[i:i + INSERT_BATCH_SIZE]
        if batch:
            await collection.insert_many(batch)


def _apply_derived_indexes(records: list, dataset_type: str) -> None:
    if dataset_type == "air_quality":
        for index, record in enumerate(records):
            if index % 500 == 0:
                check_cancelled()
            record.update(compute_aqi_for_record(record))
    elif dataset_type == "water_quality":
        for index, record in enumerate(records):
            if index % 500 == 0:
                check_cancelled()
            record.update(compute_wqi_for_record(record))


def _with_aqi_column(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["aqi"] = result.apply(
        lambda row: compute_aqi_for_record(row.to_dict()).get("aqi"), axis=1
    )
    return result


def _with_wqi_column(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["wqi"] = result.apply(
        lambda row: calculate_wqi(row.to_dict())[0], axis=1
    )
    return result


def get_database() -> AsyncIOMotorDatabase:
    return db.db


ML_DATASET_TYPES = {"air_quality", "temperature", "rainfall"}


async def _generate_ml_insights(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    dataset_type: str,
    cleaned_df: pd.DataFrame,
    owner_id: Optional[str] = None,
):
    """Run anomaly detection and forecasting for a processed dataset.

    Every dataset gets its own model scope (weather datasets use residual
    thresholds, air-quality datasets use Isolation Forest), so two datasets
    containing the same location never share or overwrite each other's models.
    """
    is_weather = dataset_type in ("temperature", "rainfall")
    scope = f"weather_{dataset_id}" if is_weather else f"aqi_{dataset_id}"

    anomaly_results = []
    for location in cleaned_df['location'].unique():
        check_cancelled()
        try:
            loc_df = cleaned_df[cleaned_df['location'] == location]
            if is_weather:
                results = await asyncio.to_thread(
                    detect_weather_anomalies,
                    loc_df,
                    location=location,
                    scope=scope,
                )
            else:
                results = await asyncio.to_thread(
                    detect_anomalies,
                    loc_df,
                    location=location,
                    scope=scope,
                )
            anomaly_results.extend(results)
        except JobCancelled:
            raise
        except Exception as e:
            print(f"Anomaly detection failed for {location}: {e}")

    check_cancelled()
    if anomaly_results:
        for result in anomaly_results:
            result['dataset_id'] = dataset_id
        await database.anomalies.insert_many(anomaly_results)

    forecast_df = cleaned_df
    forecast_parameters = None
    if dataset_type == "air_quality":
        # AQI is derived, not an imported column. Forecast only the modelled
        # AQI series, not every pollutant/weather column in the file.
        forecast_df = await asyncio.to_thread(_with_aqi_column, cleaned_df)
        forecast_parameters = ["aqi"]

    check_cancelled()
    skip_reasons: list = []
    forecast_results = await asyncio.to_thread(
        generate_multi_location_forecast,
        forecast_df,
        parameters=forecast_parameters,
        dataset_id=dataset_id,
        skip_reasons=skip_reasons,
        cancel_check=check_cancelled,
    )
    check_cancelled()
    created = 0
    for forecast in forecast_results:
        check_cancelled()
        if 'error' not in forecast:
            forecast['dataset_id'] = dataset_id
            forecast['created_at'] = datetime.utcnow()
            await database.forecasts.insert_one(forecast)
            created += 1
        elif owner_id:
            # Notify owner that forecast unavailable for this location/parameter
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "forecast_unavailable",
                f"Forecast unavailable: {forecast.get('location', 'unknown')} / {forecast.get('parameter', 'unknown')}",
                f"Could not generate forecast: {forecast.get('error', 'Unknown error')[:200]}",
                link=f"/datasets/{dataset_id}",
                severity="warning",
            )

    if dataset_type == "air_quality":
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {
                "forecast_parameters": forecast_parameters,
                "forecast_skip_reasons": skip_reasons,
            }},
        )
    return {
        "forecasts_created": created,
        "skip_reasons": skip_reasons,
        "locations": int(cleaned_df["location"].nunique()) if "location" in cleaned_df else 0,
    }


async def _generate_water_ml_insights(
    database: AsyncIOMotorDatabase,
    dataset_id: str,
    cleaned_df: pd.DataFrame,
):
    """Anomalies and monthly outlooks for a water-quality dataset.

    Anomaly detection scores dissolved oxygen and the core WQI per station with
    a robust z-score (series are too short for a seasonal baseline). Outlooks
    cover coliform (log1p space), DO and WQI in native units, evaluated
    rolling-origin against persistence; stations below the minimum monthly
    count are skipped (see app.services.water_forecaster).
    """
    ml_df = await asyncio.to_thread(_with_wqi_column, cleaned_df)

    scope = f"water_{dataset_id}"
    anomaly_results = []
    for location in ml_df['location'].unique():
        check_cancelled()
        try:
            loc_df = ml_df[ml_df['location'] == location]
            results = await asyncio.to_thread(
                detect_water_anomalies,
                loc_df,
                location=location,
                scope=scope,
            )
            anomaly_results.extend(results)
        except JobCancelled:
            raise
        except Exception as e:
            print(f"Water anomaly detection failed for {location}: {e}")

    check_cancelled()
    if anomaly_results:
        for result in anomaly_results:
            result['dataset_id'] = dataset_id
        await _insert_in_batches(database.anomalies, anomaly_results)

    check_cancelled()
    skip_reasons: list = []
    forecasts = await asyncio.to_thread(
        generate_water_forecasts,
        ml_df,
        dataset_id,
        skip_reasons=skip_reasons,
        cancel_check=check_cancelled,
    )
    check_cancelled()
    for forecast in forecasts:
        check_cancelled()
        await database.forecasts.insert_one(forecast)
    return {
        "forecasts_created": len(forecasts),
        "skip_reasons": skip_reasons,
        "locations": int(ml_df["location"].nunique()) if "location" in ml_df else 0,
    }


async def process_dataset(
    dataset_id: str,
    file_path: str,
    dataset_type: str,
    source_name: Optional[str] = None,
    location: Optional[str] = None,
    range_overrides: Optional[dict] = None,
    type_detection: Optional[dict] = None,
    job_id: Optional[str] = None,
    source_tag: Optional[str] = None,
):
    """Background task to process uploaded dataset."""
    database = db.db
    owner_id = await _dataset_owner(database, dataset_id)
    token = bind_job(job_id)
    forecast_meta: dict = {}

    try:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.PROCESSING, "updated_at": datetime.utcnow()}}
        )

        report_stage("reading_file")
        raw_df = await asyncio.to_thread(parse_file, file_path, dataset_type)
        report_stage(
            "detecting_type",
            counts={"rows_read": int(len(raw_df))},
        )

        cleaned_df, cleaning_report = await asyncio.to_thread(
            clean_dataframe,
            raw_df,
            dataset_type,
            source_name=source_name or os.path.basename(file_path),
            default_location=location,
            range_overrides=range_overrides,
        )

        records = await asyncio.to_thread(
            dataframe_to_records, cleaned_df, dataset_id, dataset_type
        )
        for record in records:
            record["owner_id"] = owner_id

        index_label = {
            "air_quality": "Calculating AQI",
            "water_quality": "Calculating WQI",
        }.get(dataset_type, "Calculating derived values")
        report_stage("calculating_index", label=index_label)
        check_cancelled()
        await asyncio.to_thread(_apply_derived_indexes, records, dataset_type)
        check_cancelled()

        if records:
            target_collection = database.water_quality if dataset_type == "water_quality" else database.air_quality
            await _insert_in_batches(target_collection, records, track_progress=True)

        check_cancelled()
        report_stage("checking_forecast")
        if dataset_type in ML_DATASET_TYPES:
            forecast_meta = await _generate_ml_insights(
                database, dataset_id, dataset_type, cleaned_df, owner_id=owner_id
            ) or {}
        elif dataset_type == "water_quality":
            forecast_meta = await _generate_water_ml_insights(
                database, dataset_id, cleaned_df
            ) or {}

        check_cancelled()
        dataset_update = {
            "status": DatasetStatus.COMPLETED,
            "row_count": len(records),
            "original_columns": list(raw_df.columns),
            "capabilities": derive_capabilities(raw_df.columns, dataset_type),
            "cleaning_report": cleaning_report,
            "pipeline_version": dataset_config.PIPELINE_VERSION,
            "config_overrides": range_overrides or {},
            "type_detection": type_detection or {},
            "updated_at": datetime.utcnow(),
        }
        if dataset_type == "air_quality":
            dominant = Counter(
                record.get("dominant_pollutant")
                for record in records
                if record.get("dominant_pollutant")
            )
            total_dominant = sum(dominant.values())
            share = {
                pollutant: round(count / total_dominant, 4)
                for pollutant, count in dominant.items()
            } if total_dominant else {}
            dataset_update["dominant_pollutant_share"] = share
            if share.get("o3", 0) >= 0.8:
                dataset_update["data_nature"] = "modelled"
                dataset_update["data_nature_reason"] = (
                    "O3 is the dominant pollutant on "
                    f"{share['o3'] * 100:.1f}% of records; this pattern is "
                    "typical of modelled/reanalysis data."
                )
        if forecast_meta.get("skip_reasons"):
            dataset_update["forecast_skip_reasons"] = forecast_meta["skip_reasons"]

        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": dataset_update},
        )
        check_cancelled()

        resolved_source_tag = source_tag_for({
            "source_tag": source_tag,
            "data_nature": dataset_update.get("data_nature"),
            "filename": source_name or os.path.basename(file_path),
            "cleaning_report": cleaning_report,
        })
        complete_job(job_id, {
            "dataset_id": dataset_id,
            "dataset_type": dataset_type,
            "rows_read": cleaning_report.get("rows_read", 0),
            "rows_kept": cleaning_report.get("rows_kept", 0),
            "rows_dropped": max(
                0,
                int(cleaning_report.get("rows_read", 0))
                - int(cleaning_report.get("rows_kept", 0)),
            ),
            "source_tag": resolved_source_tag,
            "forecast_readiness": forecast_readiness(dataset_type, forecast_meta),
            "cleaning_report": cleaning_report,
            "duplicate": False,
        })

        # Notify owner on success
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_completed",
                f"Dataset ready: {source_name or os.path.basename(file_path)}",
                f"Your dataset has been processed ({len(records):,} rows).",
                link=f"/datasets/{dataset_id}",
                severity="info",
            )

    except JobCancelled:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {
                "$set": {
                    "status": DatasetStatus.FAILED,
                    "error_message": "Processing cancelled",
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        cancel_job(job_id)
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
        fail_job(job_id, str(e))
        # Notify owner on failure
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_failed",
                f"Dataset processing failed: {source_name or os.path.basename(file_path)}",
                f"Error: {str(e)[:200]}",
                link=f"/datasets/{dataset_id}",
                severity="warning",
            )
    finally:
        reset_job(token)
        if not RETAIN_UPLOAD_FILES and os.path.exists(file_path):
            os.remove(file_path)


def _authorized_job(job_id: str, user):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Processing job not found")
    owner_id = job.get("owner_id")
    if owner_id:
        requester = str(user.id) if user else None
        if requester != owner_id and not is_platform_admin(user):
            raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.get("/jobs/{job_id}")
async def dataset_job_status(job_id: str, user=Depends(get_optional_user)):
    return _authorized_job(job_id, user)


@router.post("/jobs/{job_id}/cancel")
async def cancel_dataset_job(
    job_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    job = _authorized_job(job_id, user)
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return job
    cancelled = cancel_job(job_id)
    dataset_id = (cancelled or {}).get("dataset_id")
    if dataset_id:
        try:
            object_id = ObjectId(dataset_id)
        except Exception:
            object_id = None
        if object_id is not None:
            await database.datasets.update_one(
                {"_id": object_id},
                {
                    "$set": {
                        "status": DatasetStatus.FAILED,
                        "error_message": "Processing cancelled",
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
    return cancelled


@router.post("/upload")
async def upload_dataset(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dataset_type: str = Form("auto"),
    location: Optional[str] = Form(None),
    config_overrides: Optional[str] = Form(None),
    source_tag: Optional[str] = Form(None),
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    if is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Platform administrators cannot upload datasets",
        )
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    allowed_extensions = {'.csv', '.json', '.xlsx', '.xls'}
    if not any(file.filename.lower().endswith(ext) for ext in allowed_extensions):
        raise HTTPException(status_code=400, detail="Unsupported file format")

    # Streaming size check — abort early if over limit
    limit = upload_limit_for(user)
    await enforce_upload_size_limit(file, limit)

    # Per-user rate limit (TTL-backed)
    if user:
        await check_upload_rate_limit(database, str(user.id), user)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if not user and not get_settings().ALLOW_ANONYMOUS_UPLOAD:
        raise HTTPException(status_code=401, detail="Sign in to upload datasets")

    # Pre-check quotas before any processing
    estimated_rows = estimate_rows_from_bytes(content, resolved_type if 'resolved_type' in locals() else dataset_type)
    await precheck_quotas(database, user, estimated_rows, len(content))

    await enforce_upload_quota(database, user, len(content))

    overrides = _parse_config_overrides(config_overrides)
    source_tag = _normalize_source_tag(source_tag)
    dataset_id = str(ObjectId())
    file_extension = os.path.splitext(sanitize_filename(file.filename))[1]
    file_path = os.path.join(UPLOAD_DIR, f"{dataset_id}{file_extension}")

    with open(file_path, "wb") as handle:
        handle.write(content)

    try:
        raw_df = await asyncio.to_thread(parse_file, file_path, dataset_type)
    except ValueError as exc:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}")

    parameter_column = next(
        (
            column for column in raw_df.columns
            if str(column).strip().lower() in {
                "parameter", "pollutant", "parameter_name", "parameter_code",
                "metric", "variable", "measure", "element",
            }
        ),
        None,
    )
    parameter_values = (
        raw_df[parameter_column].dropna().astype(str).unique().tolist()[:200]
        if parameter_column is not None else None
    )
    detection = detect_dataset_type(raw_df.columns, file.filename, parameter_values)
    requested_type = str(dataset_type or "").strip().lower()
    if requested_type in ("", "auto"):
        resolved_type = str(detection["dataset_type"])
        type_source = "detected"
    else:
        resolved_type = requested_type
        type_source = "override"
        if resolved_type not in dataset_config.SUPPORTED_DATASET_TYPES:
            os.remove(file_path)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported dataset_type '{dataset_type}'. "
                    f"Choose one of: {', '.join(dataset_config.SUPPORTED_DATASET_TYPES)}"
                ),
            )

    try:
        _validate_overrides(resolved_type, overrides)
        await asyncio.to_thread(
            clean_dataframe,
            raw_df,
            resolved_type,
            source_name=file.filename,
            default_location=location,
            range_overrides=overrides,
        )
    except ValueError as exc:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail=f"Could not import file: {exc}")

    file_hash = compute_file_hash(content, resolved_type, location=location or "")
    duplicate = await _find_active_duplicate(
        database, file_hash, owner_id=str(user.id) if user else None
    )
    if duplicate:
        os.remove(file_path)
        return {
            "dataset_id": str(duplicate["_id"]),
            "status": duplicate.get("status"),
            "duplicate": True,
            "dataset_type": duplicate.get("dataset_type", resolved_type),
            "type_detection": duplicate.get("type_detection"),
            "message": (
                "This exact file was already uploaded with the same pipeline version — "
                "returning the existing dataset instead of duplicating records."
            ),
        }

    dataset_create = DatasetCreate(
        filename=file.filename,
        dataset_type=resolved_type,
        original_columns=[],
        row_count=0,
    )

    dataset_doc = dataset_create.model_dump()
    dataset_doc["_id"] = ObjectId(dataset_id)
    dataset_doc["status"] = DatasetStatus.UPLOADED
    dataset_doc["file_hash"] = file_hash
    dataset_doc["pipeline_version"] = dataset_config.PIPELINE_VERSION
    dataset_doc["type_detection"] = {**detection, "source": type_source}
    dataset_doc["config_overrides"] = overrides
    dataset_doc["source_paths"] = [file_path]
    dataset_doc["upload_location"] = location
    dataset_doc["import_mode"] = "generic"
    dataset_doc.update(_ownership_fields(user))
    if source_tag:
        dataset_doc["source_tag"] = source_tag
    dataset_doc["file_size_bytes"] = len(content)
    dataset_doc["created_at"] = datetime.utcnow()
    dataset_doc["updated_at"] = datetime.utcnow()

    await database.datasets.insert_one(dataset_doc)
    job = create_job(
        dataset_id,
        dataset_type=resolved_type,
        owner_id=str(user.id) if user else None,
        mode="standard",
        file_count=1,
        source_name=file.filename,
    )
    job_id = job["job_id"]

    async def _wrapped_process():
        user_id = str(user.id) if user else "anonymous"
        await acquire_upload_slot(user_id)
        try:
            await asyncio.wait_for(
                process_dataset(
                    dataset_id, file_path, resolved_type,
                    file.filename, location, overrides, detection,
                    job_id=job_id, source_tag=source_tag,
                ),
                timeout=PROCESSING_TIMEOUT
            )
        except asyncio.TimeoutError:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, "Processing timeout")
        except Exception as exc:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, str(exc))
        finally:
            release_upload_slot(user_id)
            # Cleanup temp file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                pass

    background_tasks.add_task(_wrapped_process)

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": DatasetStatus.UPLOADED,
        "duplicate": False,
        "dataset_type": resolved_type,
        "dataset_type_source": type_source,
        "type_detection": detection,
        "config_overrides": overrides,
        "pipeline_version": dataset_config.PIPELINE_VERSION,
        "message": "File uploaded. Processing started in background.",
    }


@router.post("/upload-imd")
async def upload_imd_dataset(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    location: Optional[str] = Form(None),
    config_overrides: Optional[str] = Form(None),
    source_tag: Optional[str] = Form(None),
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    if is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Platform administrators cannot upload datasets",
        )

    if not files:
        raise HTTPException(status_code=400, detail="No IMD files provided")

    # Multi-file caps for IMD
    MAX_IMD_FILES = 20
    MAX_IMD_TOTAL_BYTES = 200 * 1024 * 1024  # 200 MB
    if len(files) > MAX_IMD_FILES:
        raise HTTPException(status_code=400, detail=f"Too many IMD files ({len(files)} > {MAX_IMD_FILES})")

    contents = []
    limit = upload_limit_for(user)
    total_bytes = 0
    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        extension = os.path.splitext(upload.filename)[1].lower()
        if extension not in {'.csv', '.txt'}:
            raise HTTPException(status_code=400, detail=f"IMD files must be CSV: {upload.filename}")
        # Streaming size check per file
        await enforce_upload_size_limit(upload, limit)
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {upload.filename}")
        total_bytes += len(content)
        if total_bytes > MAX_IMD_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail=f"Total IMD upload size exceeds {MAX_IMD_TOTAL_BYTES // (1024*1024)} MB limit")
        contents.append((content, upload.filename))

    parameters = {imd_parameter_from_source(name) for _, name in contents}
    parameters.discard(None)
    if not parameters:
        raise HTTPException(
            status_code=400,
            detail="Cannot tell the IMD parameter from the filenames — include 'rain', 'tmax' or 'tmin' in the names",
        )
    dataset_type = "rainfall" if "precipitation" in parameters else "temperature"

    overrides = _parse_config_overrides(config_overrides)
    _validate_overrides(dataset_type, overrides)
    source_tag = _normalize_source_tag(source_tag)
    # Per-user rate limit (counts as 1 upload regardless of file count)
    if user:
        await check_upload_rate_limit(database, str(user.id), user)
    if not user and not get_settings().ALLOW_ANONYMOUS_UPLOAD:
        raise HTTPException(status_code=401, detail="Sign in to upload datasets")

    # Pre-check quotas for IMD (sum of all files)
    total_bytes = sum(len(content) for content, _ in contents)
    estimated_rows = sum(estimate_rows_from_bytes(content, dataset_type) for content, _ in contents)
    await precheck_quotas(database, user, estimated_rows, total_bytes)

    await enforce_upload_quota(database, user, total_bytes)

    ordered = sorted(contents, key=lambda pair: pair[1])
    dataset_id = str(ObjectId())
    file_paths = []
    for index, (content, name) in enumerate(ordered):
        safe_name = sanitize_filename(name)
        file_path = os.path.join(UPLOAD_DIR, f"{dataset_id}_{index}_{safe_name}")
        with open(file_path, "wb") as handle:
            handle.write(content)
        file_paths.append(file_path)

    try:
        merge_imd_files(file_paths, location)
    except ValueError as exc:
        for path in file_paths:
            os.remove(path)
        raise HTTPException(status_code=400, detail=f"Could not read IMD files: {exc}")

    file_hash = compute_file_hash(
        b"".join(content for content, _ in ordered), "imd", location=location or ""
    )
    duplicate = await _find_active_duplicate(database, file_hash, owner_id=str(user.id) if user else None)
    if duplicate:
        for path in file_paths:
            os.remove(path)
        return {
            "dataset_id": str(duplicate["_id"]),
            "status": duplicate.get("status"),
            "duplicate": True,
            "dataset_type": duplicate.get("dataset_type", dataset_type),
            "message": "This exact set of IMD files was already uploaded — returning the existing dataset.",
        }

    dataset_doc = DatasetCreate(
        filename="IMD: " + ", ".join(name for _, name in contents),
        dataset_type=dataset_type,
        original_columns=[],
        row_count=0,
    ).model_dump()
    dataset_doc["_id"] = ObjectId(dataset_id)
    dataset_doc["status"] = DatasetStatus.UPLOADED
    dataset_doc["file_hash"] = file_hash
    dataset_doc["pipeline_version"] = dataset_config.PIPELINE_VERSION
    dataset_doc["config_overrides"] = overrides
    dataset_doc["source_paths"] = file_paths
    dataset_doc["upload_location"] = location
    dataset_doc["import_mode"] = "imd"
    dataset_doc.update(_ownership_fields(user))
    if source_tag:
        dataset_doc["source_tag"] = source_tag
    dataset_doc["file_size_bytes"] = sum(len(content) for content, _ in contents)
    dataset_doc["created_at"] = datetime.utcnow()
    dataset_doc["updated_at"] = datetime.utcnow()

    await database.datasets.insert_one(dataset_doc)
    job = create_job(
        dataset_id,
        dataset_type=dataset_type,
        owner_id=str(user.id) if user else None,
        mode="imd",
        file_count=len(file_paths),
        source_name=dataset_doc["filename"],
    )
    job_id = job["job_id"]

    async def _wrapped_imd():
        user_id = str(user.id) if user else "anonymous"
        await acquire_upload_slot(user_id)
        try:
            await asyncio.wait_for(
                process_imd_dataset(
                    dataset_id, file_paths, location, dataset_type, overrides,
                    job_id=job_id, source_tag=source_tag,
                ),
                timeout=PROCESSING_TIMEOUT
            )
        except asyncio.TimeoutError:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, "Processing timeout")
        except Exception as exc:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, str(exc))
        finally:
            release_upload_slot(user_id)
            # Cleanup temp files
            for p in file_paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    background_tasks.add_task(_wrapped_imd)

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": DatasetStatus.UPLOADED,
        "duplicate": False,
        "dataset_type": dataset_type,
        "pipeline_version": dataset_config.PIPELINE_VERSION,
        "message": "IMD files uploaded. Merging on date and processing in background.",
    }


@router.post("/upload-river-summary")
async def upload_river_summary_dataset(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    location: Optional[str] = Form(None),
    config_overrides: Optional[str] = Form(None),
    source_tag: Optional[str] = Form(None),
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    """Import CPCB-style river-year summaries (one row per river-year, .xls/.xlsx/.csv)."""
    if is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Platform administrators cannot upload datasets",
        )
    if not files:
        raise HTTPException(status_code=400, detail="No river-summary files provided")

    # Multi-file caps for River Summary
    MAX_RIVER_FILES = 10
    MAX_RIVER_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MB
    if len(files) > MAX_RIVER_FILES:
        raise HTTPException(status_code=400, detail=f"Too many river summary files ({len(files)} > {MAX_RIVER_FILES})")

    contents = []
    limit = upload_limit_for(user)
    total_bytes = 0
    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        extension = os.path.splitext(upload.filename)[1].lower()
        if extension not in {'.csv', '.xls', '.xlsx'}:
            raise HTTPException(
                status_code=400,
                detail=f"River-year summaries must be CSV or Excel: {upload.filename}",
            )
        # Streaming size check per file
        await enforce_upload_size_limit(upload, limit)
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {upload.filename}")
        total_bytes += len(content)
        if total_bytes > MAX_RIVER_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail=f"Total river summary upload size exceeds {MAX_RIVER_TOTAL_BYTES // (1024*1024)} MB limit")
        contents.append((content, upload.filename))

    overrides = _parse_config_overrides(config_overrides)
    _validate_overrides("water_quality", overrides)
    source_tag = _normalize_source_tag(source_tag)
    # Per-user rate limit (counts as 1 upload regardless of file count)
    if user:
        await check_upload_rate_limit(database, str(user.id), user)
    if not user and not get_settings().ALLOW_ANONYMOUS_UPLOAD:
        raise HTTPException(status_code=401, detail="Sign in to upload datasets")

    # Pre-check quotas for River Summary
    total_bytes = sum(len(content) for content, _ in contents)
    estimated_rows = sum(estimate_rows_from_bytes(content, "water_quality") for content, _ in contents)
    await precheck_quotas(database, user, estimated_rows, total_bytes)

    await enforce_upload_quota(database, user, total_bytes)

    ordered = sorted(contents, key=lambda pair: pair[1])
    dataset_id = str(ObjectId())
    file_paths = []
    for index, (content, name) in enumerate(ordered):
        safe_name = sanitize_filename(name)
        file_path = os.path.join(UPLOAD_DIR, f"{dataset_id}_{index}_{safe_name}")
        with open(file_path, "wb") as handle:
            handle.write(content)
        file_paths.append(file_path)

    try:
        merge_river_summary_files(file_paths, location)
    except ValueError as exc:
        for path in file_paths:
            os.remove(path)
        raise HTTPException(status_code=400, detail=f"Could not read river summaries: {exc}")

    file_hash = compute_file_hash(
        b"".join(content for content, _ in ordered), "river_summary",
        location=location or "",
    )
    duplicate = await _find_active_duplicate(database, file_hash, owner_id=str(user.id) if user else None)
    if duplicate:
        for path in file_paths:
            os.remove(path)
        return {
            "dataset_id": str(duplicate["_id"]),
            "status": duplicate.get("status"),
            "duplicate": True,
            "dataset_type": duplicate.get("dataset_type", "water_quality"),
            "message": "This exact set of river-summary files was already uploaded — returning the existing dataset.",
        }

    dataset_doc = DatasetCreate(
        filename="River summary: " + ", ".join(name for _, name in contents),
        dataset_type="water_quality",
        original_columns=[],
        row_count=0,
    ).model_dump()
    dataset_doc["_id"] = ObjectId(dataset_id)
    dataset_doc["status"] = DatasetStatus.UPLOADED
    dataset_doc["file_hash"] = file_hash
    dataset_doc["pipeline_version"] = dataset_config.PIPELINE_VERSION
    dataset_doc["config_overrides"] = overrides
    dataset_doc["source_paths"] = file_paths
    dataset_doc["upload_location"] = location
    dataset_doc["import_mode"] = "river_summary"
    dataset_doc.update(_ownership_fields(user))
    if source_tag:
        dataset_doc["source_tag"] = source_tag
    dataset_doc["file_size_bytes"] = sum(len(content) for content, _ in contents)
    dataset_doc["created_at"] = datetime.utcnow()
    dataset_doc["updated_at"] = datetime.utcnow()

    await database.datasets.insert_one(dataset_doc)
    job = create_job(
        dataset_id,
        dataset_type="water_quality",
        owner_id=str(user.id) if user else None,
        mode="river",
        file_count=len(file_paths),
        source_name=dataset_doc["filename"],
    )
    job_id = job["job_id"]

    async def _wrapped_river():
        user_id = str(user.id) if user else "anonymous"
        await acquire_upload_slot(user_id)
        try:
            await asyncio.wait_for(
                process_river_summary_dataset(
                    dataset_id, file_paths, location, overrides,
                    job_id=job_id, source_tag=source_tag,
                ),
                timeout=PROCESSING_TIMEOUT
            )
        except asyncio.TimeoutError:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, "Processing timeout")
        except Exception as exc:
            await database.datasets.update_one(
                {"_id": ObjectId(dataset_id)},
                {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
            )
            fail_job(job_id, str(exc))
        finally:
            release_upload_slot(user_id)
            # Cleanup temp files
            for p in file_paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    background_tasks.add_task(_wrapped_river)

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": DatasetStatus.UPLOADED,
        "duplicate": False,
        "dataset_type": "water_quality",
        "pipeline_version": dataset_config.PIPELINE_VERSION,
        "message": "River-year summaries uploaded. Pivoting and processing in background.",
    }


async def process_river_summary_dataset(
    dataset_id: str,
    file_paths: List[str],
    location: Optional[str],
    range_overrides: Optional[dict] = None,
    job_id: Optional[str] = None,
    source_tag: Optional[str] = None,
):
    """Background task pivoting river-year summary sheets into water-quality records."""
    database = db.db
    owner_id = await _dataset_owner(database, dataset_id)
    token = bind_job(job_id)
    forecast_meta: dict = {}

    try:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.PROCESSING, "updated_at": datetime.utcnow()}}
        )

        report_stage("reading_file")
        merged_df, merge_meta = await asyncio.to_thread(
            merge_river_summary_files, file_paths, location
        )
        report_stage("detecting_type", counts={"rows_read": int(len(merged_df))})
        cleaned_df, cleaning_report = await asyncio.to_thread(
            clean_dataframe,
            merged_df,
            "water_quality",
            extra_report=merge_meta,
            range_overrides=range_overrides,
        )

        records = await asyncio.to_thread(
            dataframe_to_records, cleaned_df, dataset_id, "water_quality"
        )
        for record in records:
            record["owner_id"] = owner_id
        report_stage("calculating_index", label="Calculating WQI")
        if records:
            check_cancelled()
            await asyncio.to_thread(_apply_derived_indexes, records, "water_quality")
            await _insert_in_batches(database.water_quality, records, track_progress=True)

        display_name = None
        if records:
            rivers = sorted({str(record["location"]) for record in records if record.get("location")})
            years = sorted({
                str(record["timestamp"])[:4]
                for record in records
                if record.get("timestamp")
            })
            span = f"{years[0]}–{years[-1]}" if years else None
            subject = f"{len(rivers)} rivers" if len(rivers) > 1 else (rivers[0] if rivers else None)
            display_name = " · ".join(part for part in ("River year summary", subject, span) if part)

        report_stage("checking_forecast")

        check_cancelled()
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {
                "$set": {
                    "status": DatasetStatus.COMPLETED,
                    "row_count": len(records),
                    "original_columns": list(merged_df.columns),
                    "capabilities": derive_capabilities(merged_df.columns, "water_quality"),
                    "cleaning_report": cleaning_report,
                    "pipeline_version": dataset_config.PIPELINE_VERSION,
                    "config_overrides": range_overrides or {},
                    "display_name": display_name,
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        check_cancelled()
        resolved_source_tag = source_tag_for({
            "source_tag": source_tag,
            "filename": display_name or dataset_id,
            "cleaning_report": cleaning_report,
        })
        complete_job(job_id, {
            "dataset_id": dataset_id,
            "dataset_type": "water_quality",
            "rows_read": cleaning_report.get("rows_read", 0),
            "rows_kept": cleaning_report.get("rows_kept", 0),
            "rows_dropped": max(
                0,
                int(cleaning_report.get("rows_read", 0))
                - int(cleaning_report.get("rows_kept", 0)),
            ),
            "source_tag": resolved_source_tag,
            "forecast_readiness": forecast_readiness("water_quality", forecast_meta),
            "cleaning_report": cleaning_report,
            "duplicate": False,
        })
        # Notify owner on success
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_completed",
                f"River summary dataset ready: {display_name or dataset_id}",
                f"Your river year summary has been processed ({len(records):,} rows).",
                link=f"/datasets/{dataset_id}",
                severity="info",
            )
    except JobCancelled:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing cancelled", "updated_at": datetime.utcnow()}},
        )
        cancel_job(job_id)
    except Exception as e:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.FAILED, "error_message": str(e), "updated_at": datetime.utcnow()}},
        )
        fail_job(job_id, str(e))
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_failed",
                "River summary processing failed",
                f"Error: {str(e)[:200]}",
                link=f"/datasets/{dataset_id}",
                severity="warning",
            )
    finally:
        reset_job(token)
        if not RETAIN_UPLOAD_FILES:
            for path in file_paths:
                if os.path.exists(path):
                    os.remove(path)


async def process_imd_dataset(
    dataset_id: str,
    file_paths: List[str],
    location: Optional[str],
    dataset_type: str,
    range_overrides: Optional[dict] = None,
    job_id: Optional[str] = None,
    source_tag: Optional[str] = None,
):
    """Background task merging IMD rain/tmax/tmin files into one weather dataset."""
    database = db.db
    owner_id = await _dataset_owner(database, dataset_id)
    token = bind_job(job_id)
    forecast_meta: dict = {}

    try:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.PROCESSING, "updated_at": datetime.utcnow()}}
        )

        report_stage("reading_file")
        merged_df, merge_meta = await asyncio.to_thread(
            merge_imd_files, file_paths, location
        )
        report_stage("detecting_type", counts={"rows_read": int(len(merged_df))})
        cleaned_df, cleaning_report = await asyncio.to_thread(
            clean_dataframe,
            merged_df,
            dataset_type,
            extra_report=merge_meta,
            range_overrides=range_overrides,
        )

        records = await asyncio.to_thread(
            dataframe_to_records, cleaned_df, dataset_id, dataset_type
        )
        for record in records:
            record["owner_id"] = owner_id
        report_stage("calculating_index", label="Calculating derived values")
        if records:
            await _insert_in_batches(database.air_quality, records, track_progress=True)
            check_cancelled()
            report_stage("checking_forecast")
            forecast_meta = await _generate_ml_insights(
                database, dataset_id, dataset_type, cleaned_df, owner_id=owner_id
            ) or {}

        display_name = None
        if records:
            years = sorted({
                str(record["timestamp"])[:4]
                for record in records
                if record.get("timestamp")
            })
            span = f"{years[0]}–{years[-1]}" if years else None
            display_name = " · ".join(part for part in ("IMD", location, span) if part)

        check_cancelled()
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {
                "$set": {
                    "status": DatasetStatus.COMPLETED,
                    "row_count": len(records),
                    "original_columns": list(merged_df.columns),
                    "capabilities": derive_capabilities(merged_df.columns, dataset_type),
                    "cleaning_report": cleaning_report,
                    "pipeline_version": dataset_config.PIPELINE_VERSION,
                    "config_overrides": range_overrides or {},
                    "display_name": display_name,
                    "forecast_skip_reasons": forecast_meta.get("skip_reasons") or [],
                    "updated_at": datetime.utcnow(),
                }
            }
        )
        check_cancelled()
        resolved_source_tag = source_tag_for({
            "source_tag": source_tag,
            "filename": display_name or dataset_id,
            "cleaning_report": cleaning_report,
        })
        complete_job(job_id, {
            "dataset_id": dataset_id,
            "dataset_type": dataset_type,
            "rows_read": cleaning_report.get("rows_read", 0),
            "rows_kept": cleaning_report.get("rows_kept", 0),
            "rows_dropped": max(
                0,
                int(cleaning_report.get("rows_read", 0))
                - int(cleaning_report.get("rows_kept", 0)),
            ),
            "source_tag": resolved_source_tag,
            "forecast_readiness": forecast_readiness(dataset_type, forecast_meta),
            "cleaning_report": cleaning_report,
            "duplicate": False,
        })
        # Notify owner on success
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_completed",
                f"IMD dataset ready: {display_name or dataset_id}",
                f"Your IMD weather dataset has been processed ({len(records):,} rows).",
                link=f"/datasets/{dataset_id}",
                severity="info",
            )
    except JobCancelled:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing cancelled", "updated_at": datetime.utcnow()}},
        )
        cancel_job(job_id)
    except Exception as e:
        await database.datasets.update_one(
            {"_id": ObjectId(dataset_id)},
            {"$set": {"status": DatasetStatus.FAILED, "error_message": str(e), "updated_at": datetime.utcnow()}},
        )
        fail_job(job_id, str(e))
        if owner_id:
            from app.services.notifications import notify_user
            await notify_user(
                database, owner_id, "upload_failed",
                "IMD dataset processing failed",
                f"Error: {str(e)[:200]}",
                link=f"/datasets/{dataset_id}",
                severity="warning",
            )
    finally:
        reset_job(token)
        if not RETAIN_UPLOAD_FILES:
            for path in file_paths:
                if os.path.exists(path):
                    os.remove(path)


@router.get("")
async def list_datasets(
    status: DatasetStatus = None,
    limit: int = 50,
    skip: int = 0,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    query = readable_query(user)
    if status:
        query = {"$and": [query, {"status": status}]}

    total = await database.datasets.count_documents(query)
    cursor = database.datasets.find(query).sort("created_at", -1).skip(skip).limit(limit)
    datasets = await cursor.to_list(length=limit)

    for d in datasets:
        d["id"] = str(d.pop("_id"))
        d["source_tag"] = source_tag_for(d)

    return {
        "items": datasets,
        "total": total,
        "limit": limit,
        "skip": skip,
        "has_more": (skip + limit) < total,
    }


@router.get("/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    dataset = await require_dataset_access(database, dataset_id, user)
    dataset["id"] = str(dataset.pop("_id"))
    dataset["source_tag"] = source_tag_for(dataset)
    return dataset


@router.get("/{dataset_id}/status")
async def get_dataset_status(
    dataset_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    dataset = await require_dataset_access(database, dataset_id, user)

    return {
        "dataset_id": dataset_id,
        "status": dataset.get("status"),
        "row_count": dataset.get("row_count", 0),
        "error_message": dataset.get("error_message"),
        "cleaning_report": dataset.get("cleaning_report"),
    }


class DatasetRename(BaseModel):
    display_name: str


class DatasetSourceTagUpdate(BaseModel):
    source_tag: str
    reason: str


class DatasetPublishRequest(BaseModel):
    reason: str


class StationMerge(BaseModel):
    canonical: str
    aliases: List[str]


class StationMergeRequest(BaseModel):
    merges: List[StationMerge]


@router.patch("/{dataset_id}")
async def rename_dataset(
    dataset_id: str,
    payload: DatasetRename,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Display name cannot be empty")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="Display name must be 80 characters or fewer")

    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    await database.datasets.update_one(
        {"_id": dataset["_id"]},
        {"$set": {"display_name": name, "updated_at": datetime.utcnow()}},
    )
    await write_audit(database, "dataset.renamed", actor=user, target=dataset_id)
    return {"dataset_id": dataset_id, "display_name": name}


@router.patch("/{dataset_id}/source-tag")
async def update_source_tag(
    dataset_id: str,
    payload: DatasetSourceTagUpdate,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    tag = payload.source_tag.strip().lower()
    if tag not in SOURCE_TAGS:
        raise HTTPException(status_code=400, detail="source_tag must be real, synthetic, or modelled")
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="A reason is required")
    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    before = source_tag_for(dataset)
    await database.datasets.update_one(
        {"_id": dataset["_id"]},
        {"$set": {
            "source_tag": tag,
            "source_tag_updated_at": datetime.utcnow(),
            "source_tag_updated_by": str(user.id) if user else None,
            "updated_at": datetime.utcnow(),
        }},
    )
    await write_audit(
        database, "dataset.source_tag_updated", actor=user, target=dataset_id,
        metadata={"reason": reason, "before": {"source_tag": before}, "after": {"source_tag": tag}},
    )
    return {"dataset_id": dataset_id, "source_tag": tag}


@router.post("/{dataset_id}/publish-request")
async def request_publication(
    dataset_id: str,
    payload: DatasetPublishRequest,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    owner = str(dataset.get("owner_id") or dataset.get("user_id") or "")
    if owner != str(user.id):
        raise HTTPException(status_code=403, detail="Only the dataset owner can request publication")
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="A reason is required")
    await database.datasets.update_one(
        {"_id": dataset["_id"]},
        {"$set": {
            "publish_requested_at": datetime.utcnow(),
            "publish_requested_by": str(user.id),
            "publish_request_reason": reason,
            "publish_request_status": "requested",
            "updated_at": datetime.utcnow(),
        }},
    )
    await write_audit(
        database, "dataset.publish_requested", actor=user, target=dataset_id,
        metadata={"reason": reason, "filename": dataset.get("filename")},
    )
    return {"dataset_id": dataset_id, "status": "requested"}


@router.post("/{dataset_id}/reprocess", status_code=202)
async def reprocess_dataset(
    dataset_id: str,
    background_tasks: BackgroundTasks,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    """Re-run an import using the retained source files and the current pipeline.

    Re-uploading the same file is deliberately deduplicated by (bytes + type +
    pipeline version). This action is the explicit escape hatch for reprocessing
    when sources were retained with RETAIN_UPLOAD_FILES=1.
    """
    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    object_id = dataset["_id"]

    stored_paths = [
        path for path in (dataset.get("source_paths") or []) if path
    ]
    source_paths = [path for path in stored_paths if os.path.exists(path)]
    if not stored_paths or len(source_paths) != len(stored_paths):
        raise HTTPException(
            status_code=409,
            detail=(
                "Source files for this dataset are no longer retained. "
                "Re-upload the original file to reprocess it with the current pipeline "
                "(or set RETAIN_UPLOAD_FILES=1 before uploading)."
            ),
        )

    await database.air_quality.delete_many({"dataset_id": dataset_id})
    await database.water_quality.delete_many({"dataset_id": dataset_id})
    await database.anomalies.delete_many({"dataset_id": dataset_id})
    await database.forecasts.delete_many({"dataset_id": dataset_id})
    purge_forecast_models(dataset_id)
    purge_anomaly_models(dataset_id)

    dataset_type = dataset.get("dataset_type", "air_quality")
    overrides = dataset.get("config_overrides") or {}
    mode = dataset.get("import_mode")
    filename = dataset.get("filename") or ""
    if not mode:
        mode = (
            "imd" if filename.startswith("IMD:")
            else "river_summary" if filename.startswith("River summary:")
            else "generic"
        )

    if mode == "imd":
        hash_type = "imd"
    elif mode == "river_summary":
        hash_type = "river_summary"
    else:
        hash_type = dataset_type
    try:
        source_payload = b"".join(
            Path(path).read_bytes() for path in sorted(source_paths)
        )
        new_hash = compute_file_hash(
            source_payload, hash_type, location=dataset.get("upload_location") or ""
        )
    except OSError:
        new_hash = dataset.get("file_hash")

    await database.datasets.update_one(
        {"_id": object_id},
        {"$set": {
            "status": DatasetStatus.UPLOADED,
            "row_count": 0,
            "error_message": None,
            "file_hash": new_hash,
            "pipeline_version": dataset_config.PIPELINE_VERSION,
            "updated_at": datetime.utcnow(),
        }},
    )

    if mode == "imd":
        async def _wrapped():
            user_id = str(user.id) if user else "anonymous"
            await acquire_upload_slot(user_id)
            try:
                await asyncio.wait_for(
                    process_imd_dataset(
                        dataset_id, source_paths,
                        dataset.get("upload_location"), dataset_type, overrides
                    ),
                    timeout=PROCESSING_TIMEOUT
                )
            except asyncio.TimeoutError:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
                )
            except Exception as exc:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
                )
            finally:
                release_upload_slot(user_id)
        background_tasks.add_task(_wrapped)
    elif mode == "river_summary":
        async def _wrapped():
            user_id = str(user.id) if user else "anonymous"
            await acquire_upload_slot(user_id)
            try:
                await asyncio.wait_for(
                    process_river_summary_dataset(
                        dataset_id, source_paths,
                        dataset.get("upload_location"), overrides
                    ),
                    timeout=PROCESSING_TIMEOUT
                )
            except asyncio.TimeoutError:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
                )
            except Exception as exc:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
                )
            finally:
                release_upload_slot(user_id)
        background_tasks.add_task(_wrapped)
    else:
        async def _wrapped():
            user_id = str(user.id) if user else "anonymous"
            await acquire_upload_slot(user_id)
            try:
                await asyncio.wait_for(
                    process_dataset(
                        dataset_id, source_paths[0], dataset_type,
                        dataset.get("filename"), dataset.get("upload_location"),
                        overrides, dataset.get("type_detection")
                    ),
                    timeout=PROCESSING_TIMEOUT
                )
            except asyncio.TimeoutError:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": "Processing timeout", "updated_at": datetime.utcnow()}}
                )
            except Exception as exc:
                await database.datasets.update_one(
                    {"_id": object_id},
                    {"$set": {"status": DatasetStatus.FAILED, "error_message": str(exc), "updated_at": datetime.utcnow()}}
                )
            finally:
                release_upload_slot(user_id)
        background_tasks.add_task(_wrapped)

    # Notify user that reprocessing started
    if user:
        from app.services.notifications import notify_user
        await notify_user(
            database, str(user.id), "reprocess_completed",
            "Reprocessing started",
            f"Your dataset '{dataset.get('filename') or dataset_id}' is being reprocessed with the current pipeline.",
            link=f"/datasets/{dataset_id}",
            severity="info",
        )

    return {
        "dataset_id": dataset_id,
        "status": DatasetStatus.UPLOADED,
        "import_mode": mode,
        "message": "Reprocessing started with the current pipeline version.",
    }


@router.get("/{dataset_id}/station-suggestions")
async def station_suggestions(
    dataset_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    """Propose near-identical station names; merges are never applied silently."""
    await require_dataset_access(database, dataset_id, user)

    locations = set()
    for collection in (database.air_quality, database.water_quality):
        cursor = collection.aggregate([
            {"$match": {"dataset_id": dataset_id}},
            {"$group": {"_id": "$location"}},
        ])
        async for row in cursor:
            if row.get("_id"):
                locations.add(str(row["_id"]))

    return {
        "dataset_id": dataset_id,
        "locations": len(locations),
        "suggestions": suggest_station_merges(locations),
        "action": "Suggestions only. POST the accepted groups to apply them.",
    }


@router.post("/{dataset_id}/station-merges")
async def apply_station_merges(
    dataset_id: str,
    payload: StationMergeRequest,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    """Apply user-confirmed station-name merges for one dataset."""
    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    object_id = dataset["_id"]
    if not payload.merges:
        raise HTTPException(status_code=400, detail="merges cannot be empty")

    applied = []
    for merge in payload.merges:
        canonical = merge.canonical.strip()
        aliases = sorted({
            alias.strip() for alias in merge.aliases
            if alias and alias.strip() and alias.strip() != canonical
        })
        if not canonical:
            raise HTTPException(status_code=400, detail="canonical station name cannot be empty")
        if not aliases:
            raise HTTPException(status_code=400, detail="each merge needs at least one alias")

        updated = 0
        for collection in (
            database.air_quality,
            database.water_quality,
            database.anomalies,
            database.forecasts,
        ):
            result = await collection.update_many(
                {"dataset_id": dataset_id, "location": {"$in": aliases}},
                {"$set": {"location": canonical}},
            )
            updated += result.modified_count
        applied.append({"canonical": canonical, "aliases": aliases, "records_updated": updated})

    await database.datasets.update_one(
        {"_id": object_id},
        {
            "$push": {"station_name_merges": {"$each": applied}},
            "$set": {"updated_at": datetime.utcnow()},
        },
    )

    return {
        "dataset_id": dataset_id,
        "applied": applied,
        "message": "Confirmed station-name merges applied to this dataset only.",
    }


@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
    user=Depends(get_optional_user),
):
    dataset = await require_dataset_access(database, dataset_id, user, write=True)
    await database.datasets.delete_one({"_id": dataset["_id"]})
    await database.air_quality.delete_many({"dataset_id": dataset_id})
    await database.water_quality.delete_many({"dataset_id": dataset_id})
    await database.anomalies.delete_many({"dataset_id": dataset_id})
    await database.forecasts.delete_many({"dataset_id": dataset_id})

    purge_forecast_models(dataset_id)
    purge_anomaly_models(dataset_id)
    await write_audit(database, "dataset.deleted", actor=user, target=dataset_id)
    return {"message": "Dataset and associated data deleted"}
