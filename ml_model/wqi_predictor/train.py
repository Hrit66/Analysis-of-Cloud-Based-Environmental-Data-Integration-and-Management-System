"""
wqi_predictor/train.py
======================
Training pipeline for XGBoost Water Quality Index (WQI) Predictor.

Trains two models:
1. XGBRegressor: Predicts continuous WQI score (0-300+).
2. XGBClassifier: Predicts WQI category (Excellent, Good, Poor, Very Poor, Unsuitable).

Data splits are strictly chronological. Models are saved with versioning to
models/wqi_predictor/.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier, XGBRegressor

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from shared.data_split import chronological_split
from shared.features import _build_features_aqi as _build_features_wqi, fill_missing
from shared.metrics import classification_metrics, regression_metrics
from wqi_predictor.model_registry import save_model

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config(path: Path = _CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Label generator using BIS IS:10500-2012 Weighted Arithmetic Index
# ---------------------------------------------------------------------------

_WQI_PARAMS = {
    "ph":        {"Si": 8.5,  "Vid": 7.0},
    "turbidity": {"Si": 5.0,  "Vid": 0.0},
    "tds":       {"Si": 500.0,"Vid": 0.0},
    "hardness":  {"Si": 300.0,"Vid": 0.0},
    "chlorides": {"Si": 250.0,"Vid": 0.0},
    "sulfates":  {"Si": 200.0,"Vid": 0.0},
    "nitrates":  {"Si": 45.0, "Vid": 0.0},
    "fluorides": {"Si": 1.0,  "Vid": 0.0},
    "iron":      {"Si": 0.3,  "Vid": 0.0},
    "manganese": {"Si": 0.1,  "Vid": 0.0},
    "do":        {"Si": 5.0,  "Vid": 14.6},
    "bod":       {"Si": 5.0,  "Vid": 0.0},
}

_WQI_CATEGORIES = [
    (0, 25, "Excellent"),
    (25, 50, "Good"),
    (50, 75, "Poor"),
    (75, 100, "Very Poor"),
    (100, 9999, "Unsuitable for Drinking"),
]


def _derive_wqi_labels(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Calculate exact WQI score and category for labelling training data."""
    wqi_scores = []
    wqi_cats = []

    k_const = 1.0 / sum(1.0 / p["Si"] for p in _WQI_PARAMS.values())

    for _, row in df.iterrows():
        weighted_sum = 0.0
        weight_total = 0.0
        for param, stds in _WQI_PARAMS.items():
            if param in row and not pd.isna(row[param]):
                val = float(row[param])
                Si, Vid = stds["Si"], stds["Vid"]
                if param == "do":
                    Qi = 100.0 * (Vid - val) / (Vid - Si) if (Vid - Si) != 0 else 0.0
                else:
                    Qi = 100.0 * (val - Vid) / (Si - Vid) if (Si - Vid) != 0 else 0.0
                Qi = max(0.0, min(Qi, 200.0))
                Wi = k_const / Si
                weighted_sum += Qi * Wi
                weight_total += Wi

        score = round(weighted_sum / weight_total, 4) if weight_total > 0 else 0.0
        cat = "Unsuitable for Drinking"
        for lo, hi, cname in _WQI_CATEGORIES:
            if lo <= score < hi:
                cat = cname
                break
        wqi_scores.append(score)
        wqi_cats.append(cat)

    return pd.Series(wqi_scores, index=df.index), pd.Series(wqi_cats, index=df.index)


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------

def _generate_synthetic_data(n_rows: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    periods = pd.date_range("2023-01-01", periods=n_rows, freq="h")
    df = pd.DataFrame({
        "measured_at": periods,
        "pH": np.clip(rng.normal(7.2, 0.6, size=n_rows), 5.5, 9.5),
        "turbidity": np.clip(rng.exponential(2.0, size=n_rows), 0.1, 20.0),
        "TDS": np.clip(rng.gamma(4, 100, size=n_rows), 50, 1500),
        "hardness": np.clip(rng.gamma(3, 80, size=n_rows), 30, 800),
        "chlorides": np.clip(rng.gamma(2, 60, size=n_rows), 10, 600),
        "sulfates": np.clip(rng.gamma(2, 50, size=n_rows), 10, 500),
        "nitrates": np.clip(rng.gamma(2, 10, size=n_rows), 1, 100),
        "fluorides": np.clip(rng.normal(0.8, 0.4, size=n_rows), 0.1, 3.5),
        "iron": np.clip(rng.exponential(0.2, size=n_rows), 0.01, 2.0),
        "manganese": np.clip(rng.exponential(0.05, size=n_rows), 0.005, 0.5),
        "do": np.clip(rng.normal(6.5, 1.5, size=n_rows), 1.0, 12.0),
        "bod": np.clip(rng.exponential(2.0, size=n_rows), 0.2, 15.0),
    })
    return df


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train_wqi_predictor(
    df: Optional[pd.DataFrame] = None,
    data_path: Optional[str] = None,
    config_override: Optional[dict] = None,
) -> dict:
    """Train XGBoost WQI Regressor + Classifier and register them."""
    cfg = _load_config()
    if config_override:
        cfg.update(config_override)

    # 1. Load data
    if df is None:
        if data_path:
            logger.info("Loading WQI dataset from %s", data_path)
            df = pd.read_parquet(data_path) if data_path.endswith(".parquet") else pd.read_csv(data_path)
        else:
            logger.warning("No data supplied -> generating synthetic water quality data.")
            df = _generate_synthetic_data()

    water_cols = [c for c in cfg["data"]["water_cols"] if c in df.columns or c.lower() in [x.lower() for x in df.columns]]
    ts_col = cfg["data"]["timestamp_col"]

    # 2. Derive targets if not present
    target_wqi = cfg["data"]["target_wqi_col"]
    target_cat = cfg["data"]["target_category_col"]

    if target_wqi not in df.columns or target_cat not in df.columns:
        logger.info("Deriving WQI score and category labels from water parameters...")
        df[target_wqi], df[target_cat] = _derive_wqi_labels(df)

    # 3. Build features
    df_feat = _build_features_wqi(
        df,
        pollutant_cols=water_cols,
        ts_col=ts_col,
        include_ratios=cfg["features"]["include_ratios"],
        include_cyclical=cfg["features"]["include_cyclical"],
    )

    feature_cols = [c for c in df_feat.select_dtypes(include=[np.number]).columns if c not in {target_wqi, target_cat, ts_col}]

    # 4. Encode category labels
    le = LabelEncoder()
    df_feat["cat_encoded"] = le.fit_transform(df_feat[target_cat])
    category_names = {int(i): str(name) for i, name in enumerate(le.classes_)}

    # 5. Chronological Split
    X_train, X_test, y_train_wqi, y_test_wqi = chronological_split(
        df_feat,
        target_col=target_wqi,
        timestamp_col=ts_col,
        test_ratio=cfg["data"]["test_ratio"],
        gap_rows=cfg["data"]["gap_rows"],
    )
    y_train_cat = df_feat.loc[X_train.index, "cat_encoded"]
    y_test_cat = df_feat.loc[X_test.index, "cat_encoded"]

    X_train_f = X_train[feature_cols].fillna(0)
    X_test_f = X_test[feature_cols].fillna(0)

    # 6. Fit Regressor (Numeric WQI score)
    reg_params = cfg["model"]["regressor"]
    regressor = XGBRegressor(**reg_params)
    regressor.fit(X_train_f, y_train_wqi)

    y_pred_wqi = regressor.predict(X_test_f)
    reg_metrics_dict = regression_metrics(y_test_wqi.values, y_pred_wqi, prefix="wqi_")

    # 7. Fit Classifier (WQI Category)
    clf_params = cfg["model"]["classifier"]
    classifier = XGBClassifier(**clf_params)
    classifier.fit(X_train_f, y_train_cat)

    y_pred_cat = classifier.predict(X_test_f)
    cls_metrics_dict = classification_metrics(y_test_cat.values, y_pred_cat, labels=sorted(np.unique(y_train_cat)), average="weighted")

    logger.info("WQI Model Trained -> MAE: %.3f, Category F1: %.4f", reg_metrics_dict["wqi_mae"], cls_metrics_dict["f1_weighted"])

    # 8. Assembly pipeline package
    pipeline = {
        "regressor": regressor,
        "classifier": classifier,
        "label_encoder": le,
        "feature_cols": feature_cols,
        "water_cols": water_cols,
        "ts_col": ts_col,
        "category_names": category_names,
    }

    metadata = {
        "model_type": "XGBRegressor + XGBClassifier (WQI)",
        "training": {
            "n_train_samples": len(X_train),
            "n_test_samples": len(X_test),
            "n_features": len(feature_cols),
            "feature_cols": feature_cols,
            "water_cols": water_cols,
            "trained_at": datetime.now(tz=timezone.utc).isoformat(),
            "feature_stats": {
                col: {
                    "mean": round(float(X_train_f[col].mean()), 6),
                    "std": round(float(X_train_f[col].std()), 6),
                }
                for col in feature_cols
                if X_train_f[col].std() > 0
            },
        },
        "evaluation": {
            **reg_metrics_dict,
            **cls_metrics_dict,
        },
        "category_names": category_names,
    }

    # 9. Register
    reg_cfg = cfg["registry"]
    registry_dir = _ML_ROOT / reg_cfg["local_dir"]
    paths = save_model(
        model=pipeline,
        metadata=metadata,
        prefix=reg_cfg["artifact_prefix"],
        registry_dir=registry_dir,
    )

    _m = re.search(r"_v([\d.]+)\.joblib$", paths["model_path"])
    saved_version = _m.group(1) if _m else "unknown"

    return {**paths, "version": saved_version, "metrics": metadata["evaluation"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost WQI Predictor")
    parser.add_argument("--data", default=None, help="Path to CSV dataset")
    args = parser.parse_args()
    res = train_wqi_predictor(data_path=args.data)
    print("WQI Training complete:", res)
