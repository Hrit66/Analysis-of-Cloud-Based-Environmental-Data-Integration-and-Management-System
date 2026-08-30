"""
forecast/evaluate.py
====================
Evaluation and drift detection for the XGBoost forecasting model.

Produces
--------
- Per-horizon MAE / RMSE / MAPE / R² on new data.
- KS-test drift report for input features.
- RETRAIN_REQUIRED flag if MAE exceeds configured threshold.
- JSON report written to models/reports/forecast/.
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

from forecast.model_registry import load_model, latest_version
from forecast.train import _build_target
from shared.features import build_feature_matrix
from shared.metrics import regression_metrics, ks_drift_test, print_report

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def evaluate(
    new_data: pd.DataFrame,
    version: Optional[str] = None,
    target_col: Optional[str] = None,
) -> dict:
    """Evaluate forecast model on new_data for all trained horizons.

    Returns a report dict and writes it to disk.
    """
    cfg = _load_config()
    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    pipeline, meta = load_model(version=version, prefix=cfg["registry"]["artifact_prefix"])
    model_version = meta.get("version", "unknown")
    target_col = target_col or pipeline.get("target_col", cfg["data"]["target_col"])
    horizons: list[int] = pipeline.get("horizons", cfg["forecast"]["horizons_hours"])
    feature_cols: list[str] = pipeline.get("feature_cols", [])
    ts_col = pipeline.get("ts_col", cfg["data"]["timestamp_col"])

    feat_cfg = cfg["features"]
    pollutant_cols = [c for c in cfg["data"]["pollutant_cols"] if c in new_data.columns]
    weather_cols = [c for c in cfg["data"]["weather_cols"] if c in new_data.columns]

    df_feat = build_feature_matrix(
        new_data,
        pollutant_cols=pollutant_cols + weather_cols,
        timestamp_col=ts_col,
        lags=feat_cfg["lags"],
        windows=feat_cfg["rolling_windows"],
        include_cyclical=feat_cfg["include_cyclical"],
        include_t_rel=feat_cfg["include_t_rel"],
    )

    mae_threshold = cfg["evaluation"]["mae_retrain_threshold"]
    horizon_results: dict[str, dict] = {}
    retrain_required = False

    for h in horizons:
        if f"h{h}" not in pipeline["horizon_models"]:
            logger.warning("No trained model for horizon h=%d, skipping.", h)
            continue

        df_h = _build_target(df_feat, target_col, h, ts_col)
        target_h = f"y_h{h}"
        available_feat = [c for c in feature_cols if c in df_h.columns]
        X = df_h[available_feat].fillna(0)
        y = df_h[target_h]

        model = pipeline["horizon_models"][f"h{h}"]
        y_pred = model.predict(X)

        m = regression_metrics(y.values, y_pred, prefix="")
        horizon_results[f"h{h}"] = m

        if m["mae"] > mae_threshold:
            retrain_required = True
            logger.warning(
                "MAE %.3f > threshold %.3f at h=%d → retraining flagged.",
                m["mae"], mae_threshold, h,
            )

    # KS drift on features – use training feature stats from metadata if available
    available_feat = [c for c in feature_cols if c in df_feat.columns]
    X_current = df_feat[available_feat].fillna(0)
    _rng = np.random.default_rng(seed=42)
    training_stats = meta.get("training", {}).get("feature_stats", {})
    if training_stats:
        ref_data = pd.DataFrame({
            c: _rng.normal(training_stats[c]["mean"], max(training_stats[c]["std"], 1e-6), 500)
            for c in available_feat if c in training_stats
        })
    else:
        logger.warning("No feature_stats in forecast metadata – using current data as KS reference.")
        ref_data = X_current.copy()

    drift_report = ks_drift_test(
        reference=ref_data,
        current=X_current,
        alpha=cfg["evaluation"]["ks_alpha"],
    )


    if drift_report.get("overall_drift_detected"):
        retrain_required = True

    report = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model_version": model_version,
        "target_col": target_col,
        "horizon_metrics": horizon_results,
        "drift": drift_report,
        "RETRAIN_REQUIRED": retrain_required,
    }

    report_dir = _ML_ROOT / cfg["evaluation"]["report_dir"]
    report_dir.mkdir(parents=True, exist_ok=True)
    fname = f"eval_{model_version}_{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    with open(report_dir / fname, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print_report(report, title=f"Forecast Evaluation – v{model_version}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate forecast model")
    parser.add_argument("--data", required=True)
    parser.add_argument("--target", default=None)
    parser.add_argument("--version", default=None)
    args = parser.parse_args()
    ext = Path(args.data).suffix.lower()
    df = pd.read_parquet(args.data) if ext == ".parquet" else pd.read_csv(args.data)
    evaluate(new_data=df, version=args.version, target_col=args.target)
