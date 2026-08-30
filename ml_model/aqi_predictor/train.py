"""
aqi_predictor/train.py
======================
XGBoost multi-class classifier to predict CPCB AQI categories from
partial pollutant readings.

AQI Categories (CPCB India)
---------------------------
0 – Good          (AQI  0–50)
1 – Satisfactory  (AQI 51–100)
2 – Moderate      (AQI 101–200)
3 – Poor          (AQI 201–300)
4 – Very Poor     (AQI 301–400)
5 – Severe        (AQI 401–500)

The model handles *partial* readings – missing pollutant columns are zero-
filled so that the API can accept any subset of measurements.

Workflow
--------
1. Load / generate labelled dataset.
2. Derive AQI category labels using the CPCB formula (via serving/inference.py).
3. Strict chronological train/test split.
4. Fit XGBClassifier with early stopping.
5. Save pipeline (model + label encoder + feature schema) to registry.

Usage
-----
    python -m aqi_predictor.train --data path/to/data.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
import yaml
from sklearn.preprocessing import LabelEncoder

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from shared.data_split import chronological_split
from shared.features import add_cyclical_time_features, add_pollutant_ratios, fill_missing, _build_features_aqi
from shared.metrics import classification_metrics, regression_metrics

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_DEFAULT_REGISTRY_DIR = _ML_ROOT / "models" / "aqi_predictor"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# CPCB AQI category derivation (label generation)
# ---------------------------------------------------------------------------

def _aqi_to_category(aqi: float) -> int:
    """Convert numeric AQI to CPCB category index (0–5)."""
    if aqi <= 50:
        return 0
    elif aqi <= 100:
        return 1
    elif aqi <= 200:
        return 2
    elif aqi <= 300:
        return 3
    elif aqi <= 400:
        return 4
    else:
        return 5


def _derive_labels_from_aqi(df: pd.DataFrame, aqi_col: str = "aqi") -> pd.Series:
    """Create integer category labels from a numeric AQI column."""
    return df[aqi_col].apply(_aqi_to_category)


def _derive_labels_from_pollutants(df: pd.DataFrame, pollutant_cols: list[str]) -> tuple[pd.Series, pd.Series]:
    """Estimate AQI numeric score and category index from raw pollutant readings using sub-index max rule."""
    sub_index = pd.DataFrame(index=df.index)
    bp = {
        "pm25":  [(0, 30, 0, 50), (30, 60, 51, 100), (60, 90, 101, 200), (90, 120, 201, 300), (120, 250, 301, 400), (250, 500, 401, 500)],
        "pm10":  [(0, 50, 0, 50), (50, 100, 51, 100), (100, 250, 101, 200), (250, 350, 201, 300), (350, 430, 301, 400), (430, 600, 401, 500)],
        "no2":   [(0, 40, 0, 50), (40, 80, 51, 100), (80, 180, 101, 200), (180, 280, 201, 300), (280, 400, 301, 400), (400, 800, 401, 500)],
        "so2":   [(0, 40, 0, 50), (40, 80, 51, 100), (80, 380, 101, 200), (380, 800, 201, 300), (800, 1600, 301, 400), (1600, 2100, 401, 500)],
        "co":    [(0, 1, 0, 50), (1, 2, 51, 100), (2, 10, 101, 200), (10, 17, 201, 300), (17, 34, 301, 400), (34, 48, 401, 500)],
        "o3":    [(0, 50, 0, 50), (50, 100, 51, 100), (100, 168, 101, 200), (168, 208, 201, 300), (208, 748, 301, 400), (748, 1000, 401, 500)],
    }

    def _sub(value: float, breaks: list) -> float:
        for (c_lo, c_hi, i_lo, i_hi) in breaks:
            if c_lo <= value <= c_hi:
                return i_lo + (i_hi - i_lo) * (value - c_lo) / max(c_hi - c_lo, 1e-6)
        return 500.0

    for col in pollutant_cols:
        if col in bp and col in df.columns:
            sub_index[col] = df[col].apply(lambda v: _sub(v, bp[col]))

    aqi_numeric = sub_index.max(axis=1).fillna(0)
    aqi_cat = aqi_numeric.apply(_aqi_to_category)
    return aqi_numeric, aqi_cat


# ---------------------------------------------------------------------------
# Synthetic labelled dataset
# ---------------------------------------------------------------------------

def _generate_synthetic_data(n_rows: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed=2)
    periods = pd.date_range("2023-01-01", periods=n_rows, freq="h")
    df = pd.DataFrame({
        "measured_at": periods,
        "pm25": np.clip(rng.gamma(shape=2, scale=30, size=n_rows), 0, 500),
        "pm10": np.clip(rng.gamma(shape=2, scale=50, size=n_rows), 0, 600),
        "no2":  np.clip(rng.gamma(shape=2, scale=20, size=n_rows), 0, 800),
        "so2":  np.clip(rng.gamma(shape=2, scale=15, size=n_rows), 0, 1600),
        "co":   np.clip(rng.gamma(shape=2, scale=1, size=n_rows), 0, 48),
        "o3":   np.clip(rng.gamma(shape=2, scale=25, size=n_rows), 0, 748),
    })
    return df


# _build_features is aliased from shared.features._build_features_aqi (imported above)
_build_features = _build_features_aqi


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common CSV column names (e.g. Datetime -> measured_at, PM2.5 -> pm25)."""
    mapping = {}
    for col in df.columns:
        c_clean = str(col).lower().replace(".", "").replace("_", "").replace(" ", "")
        if c_clean in ("datetime", "timestamp", "date", "time", "ts", "readingtime"):
            mapping[col] = "measured_at"
        elif c_clean in ("pm25", "pm25"):
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
        elif c_clean == "nh3":
            mapping[col] = "nh3"
        elif c_clean == "pb":
            mapping[col] = "pb"
        elif c_clean == "aqi":
            mapping[col] = "aqi_numeric"
        elif c_clean in ("aqibucket", "aqicategory", "category"):
            mapping[col] = "aqi_category"
    return df.rename(columns=mapping)


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train_aqi_predictor(
    df: Optional[pd.DataFrame] = None,
    data_path: Optional[str] = None,
    config_override: Optional[dict] = None,
) -> dict:
    """Train XGBoost AQI numerical regressor and category classifier and register them."""
    import glob, json, re
    import joblib

    cfg = _load_config()
    if config_override:
        cfg.update(config_override)

    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    # ── 1. Load data ──────────────────────────────────────────────────────────
    if df is None:
        if data_path:
            ext = Path(data_path).suffix.lower()
            df = pd.read_parquet(data_path) if ext == ".parquet" else pd.read_csv(data_path)
        else:
            logger.warning("No data supplied – generating synthetic data.")
            df = _generate_synthetic_data()

    df = _normalize_columns(df)
    ts_col = cfg["data"]["timestamp_col"]
    target_cat_col = cfg["data"]["target_col"]
    target_num_col = "aqi_numeric"
    pollutant_cols = [c for c in cfg["data"]["pollutant_cols"] if c in df.columns]

    # ── 2. Derive labels ──────────────────────────────────────────────────────
    if target_cat_col not in df.columns or target_num_col not in df.columns:
        logger.info("Deriving AQI numeric and category labels from pollutant readings…")
        df[target_num_col], df[target_cat_col] = _derive_labels_from_pollutants(df, pollutant_cols)

    # ── 3. Feature engineering ────────────────────────────────────────────────
    feat_cfg = cfg["features"]
    df_feat = _build_features(
        df,
        pollutant_cols=pollutant_cols,
        ts_col=ts_col,
        include_ratios=feat_cfg["include_ratios"],
        include_cyclical=feat_cfg["include_cyclical"],
    )

    # ── 4. Chronological split ────────────────────────────────────────────────
    X_train, X_test, y_train_cat, y_test_cat = chronological_split(
        df_feat,
        target_col=target_cat_col,
        timestamp_col=ts_col,
        test_ratio=cfg["data"]["test_ratio"],
        gap_rows=cfg["data"]["gap_rows"],
    )
    y_train_num = df_feat.loc[X_train.index, target_num_col]
    y_test_num = df_feat.loc[X_test.index, target_num_col]

    feature_cols = [c for c in X_train.select_dtypes(include=[np.number]).columns if c not in {target_cat_col, target_num_col}]

    X_tr_f = X_train[feature_cols].fillna(0)
    X_te_f = X_test[feature_cols].fillna(0)

    # Encode labels for classifier
    le = LabelEncoder()
    y_train_enc = le.fit_transform(y_train_cat)
    y_test_enc = le.transform(y_test_cat)
    n_classes = len(le.classes_)

    # Validation tail
    n_val = max(1, int(0.1 * len(X_train)))
    X_val = X_tr_f.iloc[-n_val:]
    y_val_enc = y_train_enc[-n_val:]
    X_tr = X_tr_f.iloc[:-n_val]
    y_tr_enc = y_train_enc[:-n_val]
    y_tr_num = y_train_num.iloc[:-n_val]
    y_val_num = y_train_num.iloc[-n_val:]

    # ── 5. Train XGBClassifier ────────────────────────────────────────────────
    m = cfg["model"]
    classifier = xgb.XGBClassifier(
        n_estimators=m["n_estimators"],
        max_depth=m["max_depth"],
        learning_rate=m["learning_rate"],
        subsample=m["subsample"],
        colsample_bytree=m["colsample_bytree"],
        reg_alpha=m["reg_alpha"],
        reg_lambda=m["reg_lambda"],
        objective=m["objective"],
        eval_metric=m["eval_metric"],
        early_stopping_rounds=m["early_stopping_rounds"],
        random_state=m["random_state"],
        num_class=n_classes,
        n_jobs=-1,
        verbosity=0,
    )
    classifier.fit(
        X_tr, y_tr_enc,
        eval_set=[(X_val, y_val_enc)],
        verbose=False,
    )

    # ── 5b. Train XGBRegressor ────────────────────────────────────────────────
    regressor = xgb.XGBRegressor(
        n_estimators=m["n_estimators"],
        max_depth=m["max_depth"],
        learning_rate=m["learning_rate"],
        subsample=m["subsample"],
        colsample_bytree=m["colsample_bytree"],
        random_state=m["random_state"],
        n_jobs=-1,
    )
    regressor.fit(X_tr_f, y_train_num)

    # ── 6. Evaluate on test set ───────────────────────────────────────────────
    y_pred_enc = classifier.predict(X_te_f)
    y_pred_cat = le.inverse_transform(y_pred_enc)
    y_true_cat = le.inverse_transform(y_test_enc)
    cls_m = classification_metrics(y_true_cat, y_pred_cat, labels=sorted(le.classes_), average="weighted")

    y_pred_num = regressor.predict(X_te_f)
    reg_m = regression_metrics(y_test_num.values, y_pred_num, prefix="aqi_")

    logger.info(
        "Test: Regress MAE=%.3f Classifier F1=%.4f Accuracy=%.4f",
        reg_m["aqi_mae"], cls_m["f1_weighted"], cls_m["accuracy"],
    )

    category_names = {str(k): v for k, v in cfg["aqi_categories"].items()}

    # ── 7. Bundle pipeline ────────────────────────────────────────────────────
    pipeline = {
        "classifier": classifier,
        "regressor": regressor,
        "label_encoder": le,
        "feature_cols": feature_cols,
        "pollutant_cols": pollutant_cols,
        "n_classes": n_classes,
        "category_names": category_names,
    }

    # ── 8. Metadata ────────────────────────────────────────────────────────────
    metadata = {
        "model_type": "XGBClassifier_AQI",
        "n_classes": n_classes,
        "class_labels": le.classes_.tolist(),
        "category_names": cfg["aqi_categories"],
        "hyperparameters": {k: v for k, v in m.items()},
        "training": {
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "feature_cols": feature_cols,
            "pollutant_cols": pollutant_cols,
            "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        "evaluation": cls_m,
    }

    # ── 9. Register ────────────────────────────────────────────────────────────
    _DEFAULT_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    prefix = cfg["registry"]["artifact_prefix"]
    registry_dir = _ML_ROOT / cfg["registry"]["local_dir"]
    registry_dir.mkdir(parents=True, exist_ok=True)

    # Determine version
    existing = sorted(glob.glob(str(registry_dir / f"{prefix}_v*_meta.json")))
    if existing:
        last = existing[-1]
        m_v = re.search(r"_v([\d.]+)_meta\.json$", last)
        parts = m_v.group(1).split(".") if m_v else ["1", "0", "0"]
        parts[-1] = str(int(parts[-1]) + 1)
        version = ".".join(parts)
    else:
        version = "1.0.0"

    model_path = registry_dir / f"{prefix}_v{version}.joblib"
    meta_path = registry_dir / f"{prefix}_v{version}_meta.json"
    joblib.dump(pipeline, model_path, compress=3)
    metadata["version"] = version
    metadata["model_path"] = str(model_path)
    metadata["saved_at"] = datetime.now(tz=timezone.utc).isoformat()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)

    logger.info("AQI classifier v%s saved → %s", version, model_path)
    return {"model_path": str(model_path), "meta_path": str(meta_path), "version": version, "metrics": cls_m}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost AQI category classifier")
    parser.add_argument("--data", default=None)
    args = parser.parse_args()
    result = train_aqi_predictor(data_path=args.data)
    print("Training complete:", result)
