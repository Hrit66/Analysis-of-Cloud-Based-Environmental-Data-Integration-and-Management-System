"""
wqi_predictor/evaluate.py
========================
Evaluation script for trained WQI predictor.

Evaluates regression MAE and classification F1-score on new data.
Also computes KS data drift test.
Generates an evaluation report JSON in models/reports/wqi_predictor/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from shared.features import _build_features_aqi as _build_features_wqi
from shared.metrics import classification_metrics, ks_drift_test, regression_metrics
from wqi_predictor.model_registry import load_latest_model
from wqi_predictor.train import _derive_wqi_labels

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def evaluate(
    new_data: pd.DataFrame,
    labels_col_wqi: Optional[str] = None,
    labels_col_cat: Optional[str] = None,
    model_dir: Optional[str] = None,
) -> dict:
    cfg = _load_config()
    registry_dir = Path(model_dir) if model_dir else _ML_ROOT / cfg["registry"]["local_dir"]
    pipeline, meta = load_latest_model(registry_dir, cfg["registry"]["artifact_prefix"])

    regressor = pipeline["regressor"]
    classifier = pipeline["classifier"]
    le = pipeline["label_encoder"]
    feature_cols = pipeline["feature_cols"]
    water_cols = pipeline["water_cols"]
    ts_col = pipeline["ts_col"]
    model_version = meta.get("version", "unknown")

    df_feat = _build_features_wqi(
        new_data,
        pollutant_cols=water_cols,
        ts_col=ts_col,
        include_ratios=cfg["features"]["include_ratios"],
        include_cyclical=cfg["features"]["include_cyclical"],
    )

    available = [c for c in feature_cols if c in df_feat.columns]
    X = df_feat[available].fillna(0)

    y_pred_wqi = regressor.predict(X)
    y_pred_cat_enc = classifier.predict(X)
    y_pred_cat = le.inverse_transform(y_pred_cat_enc)

    report = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model_version": model_version,
        "n_samples": int(len(X)),
    }

    retrain_required = False

    # Derive or check ground truth
    if not labels_col_wqi or labels_col_wqi not in new_data.columns:
        w_scores, w_cats = _derive_wqi_labels(new_data)
        y_true_wqi = w_scores.iloc[-len(y_pred_wqi):].values
        y_true_cat = w_cats.iloc[-len(y_pred_cat):].values
    else:
        y_true_wqi = new_data[labels_col_wqi].iloc[-len(y_pred_wqi):].values
        y_true_cat = new_data[labels_col_cat].iloc[-len(y_pred_cat):].values

    reg_m = regression_metrics(y_true_wqi, y_pred_wqi, prefix="wqi_")
    cls_m = classification_metrics(y_true_cat, y_pred_cat, labels=sorted(le.classes_), average="weighted")

    report["metrics"] = {**reg_m, **cls_m}

    if reg_m["wqi_mae"] > cfg["evaluation"]["mae_retrain_threshold"]:
        retrain_required = True
    if cls_m["f1_weighted"] < cfg["evaluation"]["f1_retrain_threshold"]:
        retrain_required = True

    # Drift test
    _rng = np.random.default_rng(seed=42)
    training_stats = meta.get("training", {}).get("feature_stats", {})
    if training_stats:
        ref_data = pd.DataFrame({
            c: _rng.normal(training_stats[c]["mean"], max(training_stats[c]["std"], 1e-6), 500)
            for c in available if c in training_stats
        })
    else:
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

    logger.info("Report written to %s", report_dir / fname)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate WQI Predictor")
    parser.add_argument("--data", required=True, help="Path to evaluation data CSV")
    args = parser.parse_args()
    data = pd.read_csv(args.data)
    rep = evaluate(data)
    print("Evaluation Complete. Report summary:")
    print(json.dumps(rep, indent=2, default=str))
