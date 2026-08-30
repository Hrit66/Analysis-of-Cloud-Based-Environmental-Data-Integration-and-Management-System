"""
serving/api.py
==============
FastAPI application exposing the ML inference endpoints.

All business logic is delegated to serving/inference.py.
This file only handles HTTP routing, validation, and error handling.

Endpoints
---------
GET  /health                     – Liveness probe
POST /aqi                        – Calculate CPCB AQI (rule-based)
POST /wqi                        – Calculate WQI (rule-based)
POST /forecast                   – 24–72 hour pollutant forecast (ML)
POST /anomaly                    – Detect anomalous sensor readings (ML)
POST /batch/aqi                  – Bulk AQI calculation
POST /batch/anomaly              – Bulk anomaly detection
POST /batch/aqi-category         – Bulk AQI category prediction (ML)
GET  /model/info/{artifact}      – Registry metadata for a model artifact
POST /model/reload/{artifact}    – Evict cache and force model reload

Run locally
-----------
    uvicorn serving.api:app --host 0.0.0.0 --port 8001 --reload

Environment Variables
---------------------
CLOUD_PROVIDER  : "local" | "s3" | "gcs"  (default: local)
CLOUD_BUCKET    : Cloud bucket name
CLOUD_PREFIX    : Key prefix in bucket
LOG_LEVEL       : Python log level string (default: INFO)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from serving import inference
from serving.model_loader import evict, load as _load_model
from serving.predict_batch import (
    batch_aqi,
    batch_detect_anomalies,
    batch_predict_aqi_category,
)

import pandas as pd

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Environmental ML Inference API",
    description=(
        "ML module for the Analysis of Cloud-Based Environmental Data "
        "Integration and Management System. Provides AQI calculation (CPCB), "
        "WQI calculation, time-series forecasting, and anomaly detection."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AQIRequest(BaseModel):
    pollutant_readings: dict[str, float] = Field(
        ...,
        example={"pm25": 55.0, "pm10": 100.0, "no2": 80.0},
        description="Pollutant concentrations in CPCB standard units.",
    )


class WQIRequest(BaseModel):
    water_params: dict[str, float] = Field(
        ...,
        example={"pH": 7.2, "turbidity": 2.5, "TDS": 320.0, "DO": 6.5},
        description="Water quality parameters in BIS IS:10500-2012 units.",
    )


class ForecastRequest(BaseModel):
    dataset_id: str = Field(..., example="station_001")
    parameter: str = Field(..., example="pm25")
    hours: int = Field(..., ge=1, le=168, example=24,
                       description="Forecast horizon in hours (1–168). Snapped to nearest trained horizon.")
    historical_data: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Optional list of row dicts with historical readings. "
                    "If omitted, synthetic data is used (demo only).",
    )


class AnomalyRequest(BaseModel):
    dataset_id: str = Field(..., example="station_001")
    parameter: str = Field(..., example="pm25")
    data: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="List of row dicts containing sensor readings. "
                    "If omitted, synthetic data is used (demo only).",
    )


class BatchAQIRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(
        ...,
        description="List of row dicts, each containing pollutant readings.",
    )
    timestamp_col: str = Field(default="measured_at")


class BatchAnomalyRequest(BaseModel):
    rows: list[dict[str, Any]]
    parameter: str = Field(default="pm25")
    dataset_id: str = Field(default="batch")


class BatchAQICategoryRequest(BaseModel):
    rows: list[dict[str, Any]]
    timestamp_col: str = Field(default="measured_at")


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Utility"])
async def health() -> dict:
    """Liveness probe – returns 200 if the API is running."""
    return {"status": "ok", "service": "ml-inference", "version": app.version}


# ---------------------------------------------------------------------------
# AQI (ML-Based XGBoost)
# ---------------------------------------------------------------------------

@app.post("/aqi", tags=["ML Inference"])
async def compute_aqi(body: AQIRequest) -> dict:
    """
    Predict Air Quality Index (AQI) score and category using trained XGBoost ML model.

    Returns predicted AQI numeric score, category name, prediction confidence,
    and class probability distribution.
    """
    try:
        return inference.predict_aqi(body.pollutant_readings)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# WQI (ML-Based XGBoost)
# ---------------------------------------------------------------------------

@app.post("/wqi", tags=["ML Inference"])
async def compute_wqi(body: WQIRequest) -> dict:
    """
    Predict Water Quality Index (WQI) score and category using trained XGBoost ML model.

    Returns predicted WQI score, category name, prediction confidence,
    and class probability distribution.
    """
    try:
        return inference.predict_wqi(body.water_params)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Forecast (ML)
# ---------------------------------------------------------------------------

@app.post("/forecast", tags=["ML Inference"])
async def forecast(body: ForecastRequest) -> list[dict]:
    """
    Predict pollutant / weather values for the next N hours.

    The trained XGBoost direct multi-step model is used.  Supported horizons
    depend on which horizons were included during training (default: 24 / 48 / 72 h).
    Input horizon is snapped to the nearest trained horizon.
    """
    try:
        hist_df = pd.DataFrame(body.historical_data) if body.historical_data else None
        return inference.forecast(
            dataset_id=body.dataset_id,
            parameter=body.parameter,
            hours=body.hours,
            historical_df=hist_df,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Anomaly Detection (ML)
# ---------------------------------------------------------------------------

@app.post("/anomaly", tags=["ML Inference"])
async def anomaly(body: AnomalyRequest) -> list[dict]:
    """
    Detect anomalous sensor readings using IsolationForest.

    Returns only the flagged rows with anomaly scores.  An empty list means
    no anomalies were detected.
    """
    try:
        data_df = pd.DataFrame(body.data) if body.data else None
        return inference.detect_anomalies(
            dataset_id=body.dataset_id,
            parameter=body.parameter,
            data=data_df,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Batch endpoints
# ---------------------------------------------------------------------------

@app.post("/batch/aqi", tags=["Batch"])
async def batch_aqi_endpoint(body: BatchAQIRequest) -> list[dict]:
    """Compute AQI for every row in the provided dataset."""
    df = pd.DataFrame(body.rows)
    return batch_aqi(df, timestamp_col=body.timestamp_col)


@app.post("/batch/anomaly", tags=["Batch"])
async def batch_anomaly_endpoint(body: BatchAnomalyRequest) -> list[dict]:
    """Run anomaly detection across the entire provided dataset (chunked)."""
    df = pd.DataFrame(body.rows)
    return batch_detect_anomalies(df, parameter=body.parameter, dataset_id=body.dataset_id)


@app.post("/batch/aqi-category", tags=["Batch"])
async def batch_aqi_category_endpoint(body: BatchAQICategoryRequest) -> list[dict]:
    """Predict CPCB AQI category for every row using the XGBoost classifier."""
    df = pd.DataFrame(body.rows)
    return batch_predict_aqi_category(df, timestamp_col=body.timestamp_col)


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

@app.get("/model/info/{artifact}", tags=["Model Management"])
async def model_info(artifact: str) -> dict:
    """
    Return metadata for the currently loaded model artefact.

    artifact : one of "anomaly", "forecast", "aqi", "wqi".
    """
    valid = {"anomaly", "forecast", "aqi", "wqi"}
    if artifact not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown artifact '{artifact}'. Valid: {valid}")

    import glob
    import json
    import re

    dir_map = {
        "anomaly":  _ML_ROOT / "models" / "anomaly",
        "forecast": _ML_ROOT / "models" / "forecast",
        "aqi":      _ML_ROOT / "models" / "aqi_predictor",
        "wqi":      _ML_ROOT / "models" / "wqi_predictor",
    }
    prefix_map = {
        "anomaly":  "isolation_forest",
        "forecast": "xgb_forecast",
        "aqi":      "xgb_aqi",
        "wqi":      "xgb_wqi",
    }
    reg_dir = dir_map[artifact]
    prefix = prefix_map[artifact]
    meta_files = sorted(glob.glob(str(reg_dir / f"{prefix}_v*_meta.json")))
    if not meta_files:
        return {"artifact": artifact, "status": "no_models_registered", "versions": []}

    versions = []
    for mf in meta_files:
        with open(mf, "r", encoding="utf-8") as f:
            versions.append(json.load(f))
    return {"artifact": artifact, "n_versions": len(versions), "versions": versions}


@app.post("/model/reload/{artifact}", tags=["Model Management"])
async def model_reload(artifact: str) -> dict:
    """Evict cache for artifact and force a fresh load on next inference call."""
    valid = {"anomaly", "forecast", "aqi", "wqi"}
    if artifact not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown artifact '{artifact}'.")
    evict(artifact)
    return {"status": "evicted", "artifact": artifact}
