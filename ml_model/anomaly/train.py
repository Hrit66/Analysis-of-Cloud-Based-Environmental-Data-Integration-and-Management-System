"""
anomaly/train.py
================
Training pipeline for Isolation Forest anomaly detection.

Workflow
--------
1. Load sensor data (CSV/parquet or injected DataFrame).
2. Engineer lag + rolling features (shared/features.py).
3. Apply strict chronological train/test split (shared/data_split.py).
4. Fit IsolationForest on training data only.
5. Save versioned artefact + metadata via model_registry.py.

Usage
-----
    # From CLI (uses synthetic data when no path supplied):
    python -m anomaly.train --data path/to/sensor_data.csv

    # From Python:
    from anomaly.train import train_anomaly_model
    result = train_anomaly_model(df)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib

# Ensure ml_model/ root is importable when running as a script
_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from shared.data_split import chronological_split_unsupervised
from shared.features import build_feature_matrix
from anomaly.model_registry import save_model

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Synthetic data generator (demo / unit tests)
# ---------------------------------------------------------------------------

def _generate_synthetic_data(n_rows: int = 2000) -> pd.DataFrame:
    """Generate realistic synthetic pollution readings for development."""
    rng = np.random.default_rng(seed=0)  # fixed seed for reproducibility
    periods = pd.date_range("2023-01-01", periods=n_rows, freq="h")
    df = pd.DataFrame({
        "measured_at": periods,
        "pm25": np.clip(rng.normal(60, 25, n_rows), 0, None),
        "pm10": np.clip(rng.normal(100, 40, n_rows), 0, None),
        "no2": np.clip(rng.normal(40, 15, n_rows), 0, None),
        "so2": np.clip(rng.normal(20, 8, n_rows), 0, None),
        "co": np.clip(rng.normal(1.5, 0.5, n_rows), 0, None),
        "o3": np.clip(rng.normal(50, 18, n_rows), 0, None),
    })
    # Inject synthetic anomalies (~5 % of rows)
    anomaly_idx = rng.choice(n_rows, size=int(0.05 * n_rows), replace=False)
    df.loc[anomaly_idx, "pm25"] *= rng.uniform(3, 8, size=len(anomaly_idx))
    return df


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train_anomaly_model(
    df: Optional[pd.DataFrame] = None,
    data_path: Optional[str] = None,
    config_override: Optional[dict] = None,
) -> dict:
    """Train an IsolationForest model and register it.

    Parameters
    ----------
    df              : Pre-loaded DataFrame (takes priority over data_path).
    data_path       : Path to CSV / Parquet file.
    config_override : Dict to deep-merge over config.yaml values.

    Returns
    -------
    Dict with 'model_path', 'meta_path', 'version', 'metrics'.
    """
    cfg = _load_config()
    if config_override:
        cfg.update(config_override)

    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    # ── 1. Load data ─────────────────────────────────────────────────────────
    if df is None:
        if data_path:
            ext = Path(data_path).suffix.lower()
            df = pd.read_parquet(data_path) if ext == ".parquet" else pd.read_csv(data_path)
            logger.info("Loaded %d rows from %s", len(df), data_path)
        else:
            logger.warning("No data supplied – using synthetic data for demonstration.")
            df = _generate_synthetic_data()

    # Normalize column names (e.g. Datetime -> measured_at, PM2.5 -> pm25)
    mapping = {}
    for col in df.columns:
        c_clean = str(col).lower().replace(".", "").replace("_", "").replace(" ", "")
        if c_clean in ("datetime", "timestamp", "date", "time", "ts", "readingtime"):
            mapping[col] = "measured_at"
        elif c_clean == "pm25":
            mapping[col] = "pm25"
        elif c_clean == "pm10":
            mapping[col] = "pm10"
        elif c_clean == "no2":
            mapping[col] = "no2"
        elif c_clean == "so2":
            mapping[col] = "so2"
        elif c_clean == "co":
            mapping[col] = "co"
        elif c_clean == "o3":
            mapping[col] = "o3"
    df = df.rename(columns=mapping)

    ts_col = cfg["data"]["timestamp_col"]
    numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != ts_col]
    keep_cols = [ts_col] + numeric_cols if ts_col in df.columns else numeric_cols
    df = df[[c for c in keep_cols if c in df.columns]]

    pollutant_cols = cfg["data"]["pollutant_cols"]
    pollutant_cols = [c for c in pollutant_cols if c in df.columns]
    if not pollutant_cols:
        raise ValueError("No recognised pollutant columns found in dataframe.")

    # ── 2. Feature engineering ───────────────────────────────────────────────
    feat_cfg = cfg["features"]
    df_feat = build_feature_matrix(
        df,
        pollutant_cols=pollutant_cols,
        timestamp_col=ts_col,
        lags=feat_cfg["lags"],
        windows=feat_cfg["rolling_windows"],
        include_cyclical=feat_cfg["include_cyclical"],
        include_t_rel=feat_cfg["include_t_rel"],
    )

    # ── 3. Chronological split ───────────────────────────────────────────────
    X_train, X_test = chronological_split_unsupervised(
        df_feat,
        timestamp_col=ts_col,
        test_ratio=cfg["data"]["test_ratio"],
        gap_rows=cfg["data"]["gap_rows"],
    )
    logger.info("Train shape: %s | Test shape: %s", X_train.shape, X_test.shape)

    # ── 4. Scale features ────────────────────────────────────────────────────
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # ── 5. Fit IsolationForest ───────────────────────────────────────────────
    model_cfg = cfg["model"]
    iso = IsolationForest(
        n_estimators=model_cfg["n_estimators"],
        max_samples=model_cfg["max_samples"],
        contamination=model_cfg["contamination"],
        max_features=model_cfg["max_features"],
        bootstrap=model_cfg["bootstrap"],
        random_state=model_cfg["random_state"],
        n_jobs=-1,
    )
    iso.fit(X_train_scaled)
    logger.info("IsolationForest fitted on %d samples.", len(X_train_scaled))

    # ── 6. Quick test-set scoring (decision_function) ────────────────────────
    threshold = cfg["evaluation"]["score_threshold"]
    test_scores = iso.decision_function(X_test_scaled)
    predicted_labels = (test_scores < threshold).astype(int)  # 1 = anomaly
    n_anomalies = int(predicted_labels.sum())
    anomaly_rate = round(n_anomalies / max(len(predicted_labels), 1) * 100, 2)
    logger.info(
        "Test anomaly detection: %d / %d (%.2f%%)", n_anomalies, len(predicted_labels), anomaly_rate
    )

    # ── 7. Bundle artefact: pipeline = (scaler, model) ───────────────────────
    pipeline = {"scaler": scaler, "model": iso, "feature_cols": list(X_train.columns)}

    # ── 8. Build metadata ────────────────────────────────────────────────────
    metadata = {
        "model_type": "IsolationForest",
        "hyperparameters": {
            "n_estimators": model_cfg["n_estimators"],
            "max_samples": model_cfg["max_samples"],
            "contamination": model_cfg["contamination"],
            "max_features": model_cfg["max_features"],
            "bootstrap": model_cfg["bootstrap"],
            "random_state": model_cfg["random_state"],
        },
        "training": {
            "n_train_samples": int(len(X_train)),
            "n_test_samples": int(len(X_test)),
            "n_features": int(X_train.shape[1]),
            "feature_cols": list(X_train.columns),
            "pollutant_cols": pollutant_cols,
            "timestamp_col": ts_col,
            "test_ratio": cfg["data"]["test_ratio"],
            "gap_rows": cfg["data"]["gap_rows"],
            "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        "evaluation": {
            "score_threshold": threshold,
            "test_anomaly_count": n_anomalies,
            "test_anomaly_rate_pct": anomaly_rate,
        },
        # Store training feature statistics for KS-drift comparison during evaluation
        "training_feature_stats": {
            col: {
                "mean": round(float(X_train[col].mean()), 6),
                "std": round(float(X_train[col].std()), 6),
            }
            for col in X_train.columns
            if X_train[col].std() > 0
        },
    }

    # ── 9. Register model ─────────────────────────────────────────────────────
    reg_cfg = cfg["registry"]
    registry_dir = _ML_ROOT / reg_cfg["local_dir"]
    paths = save_model(
        model=pipeline,
        metadata=metadata,
        prefix=reg_cfg["artifact_prefix"],
        registry_dir=registry_dir,
    )

    # Extract version from the saved model path (e.g. isolation_forest_v1.0.2.joblib -> 1.0.2)
    import re as _re
    _m = _re.search(r"_v([\d.]+)\.joblib$", paths["model_path"])
    saved_version = _m.group(1) if _m else "unknown"

    result = {**paths, "version": saved_version, "metrics": metadata["evaluation"]}
    logger.info("Training complete. Artefacts: %s", paths)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train IsolationForest anomaly detector")
    parser.add_argument("--data", default=None, help="Path to CSV/Parquet sensor data")
    args = parser.parse_args()
    result = train_anomaly_model(data_path=args.data)
    print("Training complete:", result)
