"""
forecast/train.py
=================
Time-series forecasting pipeline using XGBoost with lag/rolling features.

Workflow
--------
1. Load pollutant + weather data.
2. Engineer lag, rolling-window, cyclical, and relative-time features.
3. Strict chronological train/test split (no shuffle).
4. Walk-forward backtest across N folds → compute MAE/RMSE per fold.
5. Train final model on full training set.
6. Save versioned artefact via forecast/model_registry.py.

Multi-step forecasting approach
--------------------------------
We use a direct multi-output strategy: one separate XGBoost model is trained
per horizon step (1h, 2h, … H hours ahead).  This avoids compounding errors
from recursive forecasting.  All horizon models are bundled in one joblib
pipeline dict.

Usage
-----
    python -m forecast.train --data path/to/data.csv --target pm25 --horizon 24
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
from sklearn.preprocessing import StandardScaler

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from shared.data_split import chronological_split, walk_forward_splits
from shared.features import build_feature_matrix
from shared.metrics import regression_metrics, backtest_summary
from forecast.model_registry import save_model

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

def _generate_synthetic_data(n_rows: int = 4000, target: str = "pm25") -> pd.DataFrame:
    rng = np.random.default_rng(seed=1)
    periods = pd.date_range("2022-01-01", periods=n_rows, freq="h")
    t = np.linspace(0, 4 * np.pi, n_rows)
    df = pd.DataFrame({
        "measured_at": periods,
        "pm25": np.clip(50 + 20 * np.sin(t) + rng.normal(0, 5, n_rows), 0, None),
        "pm10": np.clip(90 + 30 * np.sin(t + 0.3) + rng.normal(0, 8, n_rows), 0, None),
        "no2": np.clip(35 + 10 * np.sin(t + 0.6) + rng.normal(0, 3, n_rows), 0, None),
        "so2": np.clip(15 + 5 * np.sin(t + 0.9) + rng.normal(0, 2, n_rows), 0, None),
        "co": np.clip(1.2 + 0.4 * np.sin(t + 1.2) + rng.normal(0, 0.1, n_rows), 0, None),
        "o3": np.clip(45 + 15 * np.sin(t + 1.5) + rng.normal(0, 4, n_rows), 0, None),
        "temperature": 25 + 10 * np.sin(t / 2) + rng.normal(0, 1, n_rows),
        "humidity": np.clip(60 + 20 * np.cos(t / 2) + rng.normal(0, 3, n_rows), 0, 100),
        "wind_speed": np.clip(3 + 2 * np.sin(t / 3) + rng.normal(0, 0.5, n_rows), 0, None),
    })
    return df


# ---------------------------------------------------------------------------
# Build target shifted by horizon
# ---------------------------------------------------------------------------

def _build_target(
    df: pd.DataFrame,
    target_col: str,
    horizon: int,
    timestamp_col: str = "measured_at",
) -> pd.DataFrame:
    """Add a future-shifted target column 'y_h{horizon}' to df."""
    df = df.sort_values(timestamp_col).copy()
    df[f"y_h{horizon}"] = df[target_col].shift(-horizon)
    return df.dropna(subset=[f"y_h{horizon}"])


# ---------------------------------------------------------------------------
# Train single-horizon XGBoost
# ---------------------------------------------------------------------------

def _train_single_horizon(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    cfg: dict,
) -> xgb.XGBRegressor:
    m = cfg["model"]
    model = xgb.XGBRegressor(
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
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    return model


# ---------------------------------------------------------------------------
# Walk-forward backtest
# ---------------------------------------------------------------------------

def _backtest(
    df_feat: pd.DataFrame,
    target_col: str,
    horizon: int,
    cfg: dict,
    ts_col: str,
) -> dict:
    """Run walk-forward backtest for a single horizon and return summary metrics."""
    bt_cfg = cfg["backtesting"]
    df_h = _build_target(df_feat, target_col, horizon, ts_col)
    target_h = f"y_h{horizon}"

    folds = walk_forward_splits(
        df_h,
        target_col=target_h,
        timestamp_col=ts_col,
        n_splits=bt_cfg["n_splits"],
        min_train_ratio=bt_cfg["min_train_ratio"],
        gap_rows=cfg["data"]["gap_rows"],
    )

    fold_metrics = []
    for i, (X_tr, X_te, y_tr, y_te) in enumerate(folds):
        # Mini validation: last 10 % of training fold
        n_val = max(1, int(0.1 * len(X_tr)))
        X_val = X_tr.iloc[-n_val:]
        y_val = y_tr.iloc[-n_val:]
        X_tr2 = X_tr.iloc[:-n_val]
        y_tr2 = y_tr.iloc[:-n_val]

        model = _train_single_horizon(X_tr2, y_tr2, X_val, y_val, cfg)
        y_pred = model.predict(X_te)
        m = regression_metrics(y_te.values, y_pred, prefix="")
        fold_metrics.append(m)
        logger.debug("Fold %d h=%d: MAE=%.3f RMSE=%.3f", i, horizon, m["mae"], m["rmse"])

    return backtest_summary(fold_metrics, ["mae", "rmse", "mape", "r2"])


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train_forecast_model(
    df: Optional[pd.DataFrame] = None,
    data_path: Optional[str] = None,
    target_col: Optional[str] = None,
    horizons: Optional[list[int]] = None,
    config_override: Optional[dict] = None,
) -> dict:
    """Train one XGBoost per forecast horizon and register the bundle.

    Parameters
    ----------
    target_col : Pollutant column to forecast (default from config).
    horizons   : List of hours-ahead steps (default from config).

    Returns
    -------
    Dict with registry paths, version, backtest metrics.
    """
    cfg = _load_config()
    if config_override:
        cfg.update(config_override)

    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"], logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    target_col = target_col or cfg["data"]["target_col"]
    horizons = horizons or cfg["forecast"]["horizons_hours"]

    # ── 1. Load data ──────────────────────────────────────────────────────────
    if df is None:
        if data_path:
            ext = Path(data_path).suffix.lower()
            df = pd.read_parquet(data_path) if ext == ".parquet" else pd.read_csv(data_path)
            logger.info("Loaded %d rows from %s", len(df), data_path)
        else:
            logger.warning("No data supplied – generating synthetic time-series.")
            df = _generate_synthetic_data(target=target_col)

    # Normalize column names (e.g. Datetime -> measured_at, PM2.5 -> pm25, TEMP -> temperature)
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
        elif c_clean in ("temp", "temperature"):
            mapping[col] = "temperature"
        elif c_clean in ("dewp", "pres", "humidity"):
            mapping[col] = "humidity"
        elif c_clean in ("wspm", "windspeed"):
            mapping[col] = "wind_speed"
    df = df.rename(columns=mapping)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)

    ts_col = cfg["data"]["timestamp_col"]
    if ts_col not in df.columns:
        date_parts = [c for c in ["year", "month", "day", "hour"] if c in df.columns or c.capitalize() in df.columns]
        if len(date_parts) == 4:
            logger.info("Constructing timestamp '%s' from year, month, day, hour columns", ts_col)
            df[ts_col] = pd.to_datetime(df[["year", "month", "day", "hour"]])
        elif "date" in [c.lower() for c in df.columns]:
            d_col = [c for c in df.columns if c.lower() == "date"][0]
            df[ts_col] = pd.to_datetime(df[d_col])
        else:
            logger.info("Creating default timestamp column '%s'", ts_col)
            df[ts_col] = pd.date_range("2023-01-01", periods=len(df), freq="1h")

    t_clean = str(target_col).lower().replace(".", "").replace("_", "").replace(" ", "")
    for col in df.columns:
        if str(col).lower().replace(".", "").replace("_", "").replace(" ", "") == t_clean:
            target_col = col
            break

    numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != ts_col]
    if target_col not in numeric_cols and target_col in df.columns:
        numeric_cols.append(target_col)
    keep_cols = [ts_col] + numeric_cols if ts_col in df.columns else numeric_cols
    df = df[[c for c in keep_cols if c in df.columns]]
    df = df.loc[:, ~df.columns.duplicated()].copy()

    pollutant_cols = [c for c in cfg["data"]["pollutant_cols"] if c in df.columns]
    weather_cols = [c for c in cfg["data"]["weather_cols"] if c in df.columns]
    all_feature_input_cols = list(set(pollutant_cols + weather_cols + [target_col]))

    # ── 2. Feature engineering ────────────────────────────────────────────────
    feat_cfg = cfg["features"]
    df_feat = build_feature_matrix(
        df,
        pollutant_cols=all_feature_input_cols,
        timestamp_col=ts_col,
        lags=feat_cfg["lags"],
        windows=feat_cfg["rolling_windows"],
        include_cyclical=feat_cfg["include_cyclical"],
        include_t_rel=feat_cfg["include_t_rel"],
    )

    # ── 3. Walk-forward backtest (per horizon) ────────────────────────────────
    backtest_results: dict[str, dict] = {}
    for h in horizons:
        logger.info("Backtesting horizon h=%d hours…", h)
        summary = _backtest(df_feat, target_col, h, cfg, ts_col)
        backtest_results[f"h{h}"] = summary
        logger.info("h=%d → MAE=%.3f ± %.3f", h, summary["mae_mean"], summary["mae_std"])

    # ── 4. Train final models on full train set (per horizon) ─────────────────
    horizon_models: dict[str, xgb.XGBRegressor] = {}
    feature_cols: Optional[list[str]] = None

    for h in horizons:
        df_h = _build_target(df_feat, target_col, h, ts_col)
        target_h = f"y_h{h}"

        X_train, X_test, y_train, y_test = chronological_split(
            df_h,
            target_col=target_h,
            timestamp_col=ts_col,
            test_ratio=cfg["data"]["test_ratio"],
            gap_rows=cfg["data"]["gap_rows"],
        )
        if feature_cols is None:
            feature_cols = list(X_train.columns)

        # Validation split from training set tail
        n_val = max(1, int(0.1 * len(X_train)))
        X_val = X_train.iloc[-n_val:]
        y_val = y_train.iloc[-n_val:]
        X_tr = X_train.iloc[:-n_val]
        y_tr = y_train.iloc[:-n_val]

        model = _train_single_horizon(X_tr, y_tr, X_val, y_val, cfg)
        horizon_models[f"h{h}"] = model
        logger.info("Final model trained for horizon h=%d (%d trees used).", h, model.best_iteration or cfg["model"]["n_estimators"])

    # ── 5. Build pipeline bundle ──────────────────────────────────────────────
    pipeline = {
        "horizon_models": horizon_models,
        "feature_cols": feature_cols or [],
        "target_col": target_col,
        "horizons": horizons,
        "ts_col": ts_col,
    }

    # ── 6. Metadata ───────────────────────────────────────────────────────────
    metadata = {
        "model_type": "XGBRegressor_multi_horizon",
        "target_col": target_col,
        "horizons_hours": horizons,
        "hyperparameters": {k: v for k, v in cfg["model"].items()},
        "training": {
            "pollutant_cols": pollutant_cols,
            "weather_cols": weather_cols,
            "feature_cols": feature_cols,
            "ts_col": ts_col,
            "test_ratio": cfg["data"]["test_ratio"],
            "gap_rows": cfg["data"]["gap_rows"],
            "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        "backtest": backtest_results,
    }

    # ── 7. Register ────────────────────────────────────────────────────────────
    reg_cfg = cfg["registry"]
    registry_dir = _ML_ROOT / reg_cfg["local_dir"]
    paths = save_model(
        model=pipeline,
        metadata=metadata,
        prefix=reg_cfg["artifact_prefix"],
        registry_dir=registry_dir,
    )

    result = {**paths, "backtest": backtest_results}
    logger.info("Forecast training complete. Artefacts: %s", paths)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train XGBoost forecast model")
    parser.add_argument("--data", default=None)
    parser.add_argument("--target", default=None, help="Target pollutant column")
    parser.add_argument("--horizon", type=int, nargs="+", default=None, help="Forecast horizons (hours)")
    args = parser.parse_args()
    result = train_forecast_model(
        data_path=args.data,
        target_col=args.target,
        horizons=args.horizon,
    )
    print("Training complete:", result)
