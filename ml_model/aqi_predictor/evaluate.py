"""
aqi_predictor/evaluate.py
=========================
Evaluation and drift detection for the AQI category classifier.

Produces
--------
- F1 / Precision / Recall / Accuracy + confusion matrix on new data.
- KS-drift report for input features.
- RETRAIN_REQUIRED flag if weighted F1 < configured threshold.
- JSON report written to models/reports/aqi_predictor/.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import yaml

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from aqi_predictor.train import _build_features, _derive_labels_from_pollutants
from shared.metrics import classification_metrics, ks_drift_test, print_report

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_latest(cfg: dict) -> tuple:
    registry_dir = _ML_ROOT / cfg["registry"]["local_dir"]
    prefix = cfg["registry"]["artifact_prefix"]
    meta_files = sorted(glob.glob(str(registry_dir / f"{prefix}_v*_meta.json")))
    if not meta_files:
        raise FileNotFoundError(f"No AQI predictor models in {registry_dir}")
    meta_path = meta_files[-1]
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    pipeline = joblib.load(meta["model_path"])
    return pipeline, meta


def evaluate(
    new_data: pd.DataFrame,
    labels_col: Optional[str] = None,
) -> dict:
    cfg = _load_config()
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    pipeline, meta = _load_latest(cfg)
    model = pipeline["model"]
    le = pipeline["label_encoder"]
    feature_cols: list[str] = pipeline["feature_cols"]
    pollutant_cols: list[str] = pipeline["pollutant_cols"]
    model_version = meta.get("version", "unknown")

    ts_col = cfg["data"]["timestamp_col"]
    feat_cfg = cfg["features"]

    present_pollutants = [c for c in pollutant_cols if c in new_data.columns]
    df_feat = _build_features(
        new_data,
        pollutant_cols=present_pollutants,
        ts_col=ts_col,
        include_ratios=feat_cfg["include_ratios"],
        include_cyclical=feat_cfg["include_cyclical"],
    )

    available = [c for c in feature_cols if c in df_feat.columns]
    X = df_feat[available].fillna(0)

    y_pred_enc = model.predict(X)
    y_pred = le.inverse_transform(y_pred_enc)

    report: dict = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model_version": model_version,
        "n_samples": int(len(X)),
    }

    retrain_required = False
    f1_threshold = cfg["evaluation"]["f1_retrain_threshold"]

    # Ground-truth metrics
    if labels_col and labels_col in new_data.columns:
        y_true = new_data[labels_col].iloc[-len(y_pred):].values
        cls_m = classification_metrics(y_true, y_pred, labels=sorted(le.classes_), average="weighted")
        report["classification"] = cls_m
        f1 = cls_m.get("f1_weighted", 1.0)
        if f1 < f1_threshold:
            retrain_required = True
            logger.warning("F1 %.4f < threshold %.4f → retraining flagged.", f1, f1_threshold)
    elif cfg["data"]["target_col"] not in new_data.columns:
        # Derive labels for self-evaluation
        derived = _derive_labels_from_pollutants(new_data, present_pollutants)
        derived_vals = derived.iloc[-len(y_pred):].values
        cls_m = classification_metrics(derived_vals, y_pred, labels=sorted(le.classes_), average="weighted")
        report["classification_vs_derived"] = cls_m

    # Drift – use training feature stats from metadata if available
    _rng = np.random.default_rng(seed=42)
    training_stats = meta.get("training", {}).get("feature_stats", {})
    if training_stats:
        ref_data = pd.DataFrame({
            c: _rng.normal(training_stats[c]["mean"], max(training_stats[c]["std"], 1e-6), 500)
            for c in available if c in training_stats
        })
    else:
        logger.warning("No feature_stats in AQI metadata – using current data as KS reference.")
        ref_data = X.copy()
    drift_report = ks_drift_test(ref_data, X, alpha=cfg["evaluation"]["ks_alpha"])
    report["drift"] = drift_report

    if drift_report.get("overall_drift_detected"):
        retrain_required = True

    report["RETRAIN_REQUIRED"] = retrain_required

    report_dir = _ML_ROOT / cfg["evaluation"]["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    fname = f"eval_{model_version}_{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    with open(report_dir / fname, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print_report(report, title=f"AQI Predictor Evaluation – v{model_version}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate AQI predictor")
    parser.add_argument("--data", required=True)
    parser.add_argument("--labels-col", default=None)
    args = parser.parse_args()
    ext = Path(args.data).suffix.lower()
    df = pd.read_parquet(args.data) if ext == ".parquet" else pd.read_csv(args.data)
    evaluate(new_data=df, labels_col=args.labels_col)
