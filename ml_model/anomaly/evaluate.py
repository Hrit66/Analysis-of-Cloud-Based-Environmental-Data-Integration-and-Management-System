"""
anomaly/evaluate.py
===================
Evaluation and drift-detection script for the anomaly-detection model.

Produces
--------
- Precision / Recall / F1 report (when ground-truth labels are available).
- Per-feature KS-test drift report comparing training distribution vs new data.
- Scheduled retraining trigger (sets RETRAIN_REQUIRED flag in report).
- JSON report written to models/reports/anomaly/.

Usage
-----
    python -m anomaly.evaluate --data path/to/new_data.csv [--labels-col is_anomaly]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from anomaly.model_registry import load_model, latest_version
from shared.features import build_feature_matrix
from shared.metrics import anomaly_metrics, ks_drift_test, print_report

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate(
    new_data: pd.DataFrame,
    labels_col: Optional[str] = None,
    version: Optional[str] = None,
    retrain_threshold_precision: float = 0.60,
    retrain_threshold_recall: float = 0.55,
) -> dict:
    """Evaluate the anomaly model on new data and generate a drift report.

    Parameters
    ----------
    new_data    : New sensor readings dataframe.
    labels_col  : Column name for ground-truth anomaly labels (0/1).
                  If None, skips precision/recall computation.
    version     : Model version to load (None = latest).
    retrain_threshold_precision / recall : If metrics fall below these,
                  the report flags RETRAIN_REQUIRED = True.

    Returns
    -------
    Full evaluation report as a dict (also written to disk).
    """
    cfg = _load_config()
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    ts_col = cfg["data"]["timestamp_col"]
    pollutant_cols = [c for c in cfg["data"]["pollutant_cols"] if c in new_data.columns]
    feat_cfg = cfg["features"]
    threshold = cfg["evaluation"]["score_threshold"]

    # ── Load model pipeline ───────────────────────────────────────────────────
    pipeline, meta = load_model(version=version, prefix=cfg["registry"]["artifact_prefix"])
    scaler = pipeline["scaler"]
    model = pipeline["model"]
    train_feature_cols: list[str] = pipeline["feature_cols"]
    model_version = meta.get("version", latest_version(cfg["registry"]["artifact_prefix"]))
    logger.info("Loaded model version %s", model_version)

    # ── Feature engineering on new data ──────────────────────────────────────
    df_feat = build_feature_matrix(
        new_data,
        pollutant_cols=pollutant_cols,
        timestamp_col=ts_col,
        lags=feat_cfg["lags"],
        windows=feat_cfg["rolling_windows"],
        include_cyclical=feat_cfg["include_cyclical"],
        include_t_rel=feat_cfg["include_t_rel"],
    )

    # Align feature columns to training schema
    available = [c for c in train_feature_cols if c in df_feat.columns]
    missing = set(train_feature_cols) - set(available)
    if missing:
        logger.warning("Missing feature columns in new data: %s", missing)
    X_new = df_feat[available].fillna(0)
    X_new_scaled = scaler.transform(X_new)

    # ── Score + predict ───────────────────────────────────────────────────────
    scores = model.decision_function(X_new_scaled)
    predictions = (scores < threshold).astype(int)  # 1 = anomaly

    report: dict = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model_version": model_version,
        "n_samples": int(len(X_new)),
        "n_predicted_anomalies": int(predictions.sum()),
        "anomaly_rate_pct": round(float(predictions.mean()) * 100, 2),
        "score_threshold": threshold,
    }

    # ── Ground-truth metrics (optional) ──────────────────────────────────────
    retrain_required = False
    if labels_col and labels_col in new_data.columns:
        y_true = new_data[labels_col].iloc[-len(predictions):].values
        cls_metrics = anomaly_metrics(y_true, predictions, prefix="")
        report["classification"] = cls_metrics
        prec = cls_metrics.get("precision_binary", 1.0)
        rec = cls_metrics.get("recall_binary", 1.0)
        if prec < retrain_threshold_precision or rec < retrain_threshold_recall:
            retrain_required = True
            logger.warning(
                "Performance drop detected: precision=%.3f recall=%.3f → retraining flagged.",
                prec, rec,
            )

    # ── KS-drift detection ────────────────────────────────────────────────────
    # Reconstruct training distribution from saved feature statistics in metadata.
    # Using a fixed RNG seed so results are deterministic across evaluate() calls.
    _rng = np.random.default_rng(seed=42)
    if "training_feature_stats" in meta and meta["training_feature_stats"]:
        feature_stats = meta["training_feature_stats"]
        train_pollutant_data = pd.DataFrame({
            c: _rng.normal(feature_stats[c]["mean"], max(feature_stats[c]["std"], 1e-6), 1000)
            for c in available if c in feature_stats
        })
    else:
        # Fallback: use current data statistics as reference (no drift detectable)
        logger.warning("No training_feature_stats in metadata – using current data as reference (no drift baseline).")
        train_pollutant_data = X_new.copy()

    drift_report = ks_drift_test(
        reference=train_pollutant_data,
        current=X_new,
        alpha=cfg["evaluation"]["ks_alpha"],
    )

    report["drift"] = drift_report

    if drift_report.get("overall_drift_detected"):
        retrain_required = True
        logger.warning("Significant data drift detected – retraining recommended.")

    report["RETRAIN_REQUIRED"] = retrain_required

    # ── Write report to disk ──────────────────────────────────────────────────
    report_dir = _ML_ROOT / cfg["evaluation"]["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    report_filename = f"eval_{model_version}_{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    report_path = report_dir / report_filename
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print_report(report, title=f"Anomaly Evaluation – v{model_version}")
    logger.info("Report written to %s", report_path)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate anomaly detection model")
    parser.add_argument("--data", required=True, help="Path to new CSV/Parquet data")
    parser.add_argument("--labels-col", default=None, help="Column with ground-truth 0/1 labels")
    parser.add_argument("--version", default=None, help="Model version (default: latest)")
    args = parser.parse_args()

    ext = Path(args.data).suffix.lower()
    df = pd.read_parquet(args.data) if ext == ".parquet" else pd.read_csv(args.data)
    evaluate(new_data=df, labels_col=args.labels_col, version=args.version)
