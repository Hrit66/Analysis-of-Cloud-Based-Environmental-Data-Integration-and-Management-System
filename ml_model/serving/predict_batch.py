"""
serving/predict_batch.py
========================
Batch prediction helper.

Runs inference over a DataFrame of rows and returns a structured result list.
Useful for back-filling historical data, bulk scoring in background jobs,
or populating a dashboard with retrospective anomaly/AQI scores.

Supports
--------
- Batch AQI prediction (rule-based, using calculate_aqi from inference.py)
- Batch anomaly scoring (model-based)
- Batch AQI category prediction (model-based)

Usage
-----
    from serving.predict_batch import batch_aqi, batch_detect_anomalies

    aqi_results = batch_aqi(df)
    anomaly_results = batch_detect_anomalies(df, "pm25")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from serving.inference import predict_aqi, predict_wqi, detect_anomalies
from serving.model_loader import load as _load_model
from shared.features import _build_features_aqi, fill_missing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Batch AQI (ML Model)
# ---------------------------------------------------------------------------

_POLLUTANT_COLS = ["pm25", "pm10", "no2", "so2", "co", "o3", "nh3", "pb"]


def batch_aqi(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
) -> list[dict]:
    """Compute ML AQI for every row in df.

    Parameters
    ----------
    df            : DataFrame with pollutant columns.
    timestamp_col : If present, included in output for traceability.

    Returns
    -------
    List of dicts, one per row, each containing timestamp + ML AQI prediction.
    """
    df = fill_missing(df)
    results = []
    present_pollutants = [c for c in _POLLUTANT_COLS if c in df.columns]

    for idx, row in df.iterrows():
        readings = {col: float(row[col]) for col in present_pollutants}
        try:
            aqi_result = predict_aqi(readings)
        except Exception as exc:
            logger.debug("Row %s skipped: %s", idx, exc)
            aqi_result = {"error": str(exc)}

        entry = {"row_index": int(idx)}
        if timestamp_col in df.columns:
            entry["timestamp"] = str(row[timestamp_col])
        entry.update(aqi_result)
        results.append(entry)

    logger.info("batch_aqi: processed %d rows.", len(results))
    return results


# ---------------------------------------------------------------------------
# Batch WQI (ML Model)
# ---------------------------------------------------------------------------

def batch_wqi(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
) -> list[dict]:
    """Compute ML WQI for every row in df."""
    df = fill_missing(df)
    results = []
    water_cols = ["pH", "turbidity", "TDS", "hardness", "chlorides", "sulfates", "nitrates", "fluorides", "iron", "manganese", "do", "bod"]
    present = [c for c in water_cols if c in df.columns or c.lower() in [x.lower() for x in df.columns]]

    for idx, row in df.iterrows():
        readings = {col: float(row[col]) for col in present if not pd.isna(row[col])}
        try:
            wqi_result = predict_wqi(readings)
        except Exception as exc:
            logger.debug("Row %s skipped: %s", idx, exc)
            wqi_result = {"error": str(exc)}

        entry = {"row_index": int(idx)}
        if timestamp_col in df.columns:
            entry["timestamp"] = str(row[timestamp_col])
        entry.update(wqi_result)
        results.append(entry)

    logger.info("batch_wqi: processed %d rows.", len(results))
    return results


# ---------------------------------------------------------------------------
# Batch anomaly detection
# ---------------------------------------------------------------------------

def batch_detect_anomalies(
    df: pd.DataFrame,
    parameter: str = "pm25",
    dataset_id: str = "batch",
    chunk_size: int = 10_000,
) -> list[dict]:
    """Run the anomaly model over df in chunks (memory-safe for large datasets)."""
    all_anomalies = []
    for start in range(0, len(df), chunk_size):
        chunk = df.iloc[start : start + chunk_size].copy()
        chunk_anomalies = detect_anomalies(
            dataset_id=dataset_id,
            parameter=parameter,
            data=chunk,
        )
        all_anomalies.extend(chunk_anomalies)

    logger.info("batch_detect_anomalies: %d anomalies in %d rows.", len(all_anomalies), len(df))
    return all_anomalies


# ---------------------------------------------------------------------------
# Batch AQI category prediction (ML model)
# ---------------------------------------------------------------------------

def batch_predict_aqi_category(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
) -> list[dict]:
    """Predict AQI category using the trained XGBoost classifier."""
    pipeline = _load_model("aqi")
    classifier = pipeline["classifier"]
    le = pipeline["label_encoder"]
    feature_cols: list[str] = pipeline["feature_cols"]
    pollutant_cols: list[str] = pipeline["pollutant_cols"]
    category_names: dict = pipeline.get("category_names", {})

    present = [c for c in pollutant_cols if c in df.columns]
    df_feat = _build_features_aqi(
        df,
        pollutant_cols=present,
        ts_col=timestamp_col,
        include_ratios=True,
        include_cyclical=True,
    )
    available = [c for c in feature_cols if c in df_feat.columns]
    X = df_feat[available].fillna(0)
    for col in feature_cols:
        if col not in X.columns:
            X[col] = 0.0
    X = X[feature_cols]

    y_pred_enc = classifier.predict(X)
    y_pred = le.inverse_transform(y_pred_enc)

    results = []
    for i, (idx, row) in enumerate(df.iterrows()):
        cat_idx = int(y_pred[i])
        results.append({
            "row_index": int(idx),
            "timestamp": str(row[timestamp_col]) if timestamp_col in df.columns else None,
            "predicted_category_index": cat_idx,
            "predicted_category": category_names.get(str(cat_idx), str(cat_idx)),
        })

    logger.info("batch_predict_aqi_category: processed %d rows.", len(results))
    return results

