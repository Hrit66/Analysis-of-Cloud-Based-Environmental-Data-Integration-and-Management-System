"""
shared/features.py
==================
Feature-engineering helpers shared across all three ML sub-systems.

Provides
--------
- Lag features for time-series (pollutant concentrations shifted back N steps)
- Rolling-window statistics (mean, std, min, max)
- Relative-time index (hours since dataset start – for XGBoost ordinal time)
- Cyclical encoding for hour-of-day and day-of-week
- Pollutant ratio features (e.g., NO2/PM2.5)
- Missing-value handling (forward-fill then median imputation)

All functions accept and return ``pd.DataFrame`` so they compose easily
inside training pipelines.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------

def add_relative_time_index(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
    unit: str = "h",
) -> pd.DataFrame:
    """Add a ``t_rel`` column: time elapsed since the earliest observation.

    Parameters
    ----------
    unit : 'h' for hours (default), 'm' for minutes, 's' for seconds.
    """
    df = df.copy()
    ts = pd.to_datetime(df[timestamp_col])
    origin = ts.min()
    divisors = {"s": 1e9, "m": 6e10, "h": 3.6e12}
    ns_per_unit = divisors.get(unit, 3.6e12)
    df["t_rel"] = ((ts - origin).values.astype(np.int64) / ns_per_unit).round(4)
    return df


def add_cyclical_time_features(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
) -> pd.DataFrame:
    """Encode hour-of-day and day-of-week as sin/cos pairs (cyclical encoding)."""
    df = df.copy()
    ts = pd.to_datetime(df[timestamp_col])

    hour = ts.dt.hour
    dow = ts.dt.dayofweek   # 0 = Monday … 6 = Sunday

    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    return df


# ---------------------------------------------------------------------------
# Lag & rolling features
# ---------------------------------------------------------------------------

def add_lag_features(
    df: pd.DataFrame,
    cols: list[str],
    lags: list[int],
    timestamp_col: str = "measured_at",
) -> pd.DataFrame:
    """Add lagged values for each column × lag combination.

    The dataframe is sorted by ``timestamp_col`` before shifting so that
    lag-1 always means "one observation earlier in time".

    Parameters
    ----------
    cols : Feature columns to lag.
    lags : List of integer step lags (e.g., [1, 2, 3, 6, 12, 24]).
    """
    df = df.sort_values(timestamp_col).reset_index(drop=True)
    new_cols: list[pd.Series] = []
    for col in cols:
        if col not in df.columns:
            logger.warning("Lag target column '%s' not found – skipping.", col)
            continue
        for lag in lags:
            s = df[col].shift(lag)
            s.name = f"{col}_lag{lag}"
            new_cols.append(s)
    if new_cols:
        df = pd.concat([df] + new_cols, axis=1)
    return df


def add_rolling_features(
    df: pd.DataFrame,
    cols: list[str],
    windows: list[int],
    stats: list[str] = ("mean", "std", "min", "max"),
    timestamp_col: str = "measured_at",
) -> pd.DataFrame:
    """Add rolling-window statistics for each column × window × stat.

    Parameters
    ----------
    windows : Window sizes in rows (e.g., [3, 6, 12, 24]).
    stats   : Any subset of {'mean', 'std', 'min', 'max', 'median'}.
    """
    df = df.sort_values(timestamp_col).reset_index(drop=True)
    new_cols: list[pd.Series] = []
    for col in cols:
        if col not in df.columns:
            logger.warning("Rolling target column '%s' not found – skipping.", col)
            continue
        for w in windows:
            roll = df[col].rolling(window=w, min_periods=1)
            for stat in stats:
                s = getattr(roll, stat)()
                s.name = f"{col}_roll{w}_{stat}"
                new_cols.append(s)
    if new_cols:
        df = pd.concat([df] + new_cols, axis=1)
    return df


# ---------------------------------------------------------------------------
# Ratio / interaction features
# ---------------------------------------------------------------------------

def add_pollutant_ratios(
    df: pd.DataFrame,
    numerators: list[str],
    denominators: list[str],
    epsilon: float = 1e-6,
) -> pd.DataFrame:
    """Compute pairwise ratio features (numerator / denominator + epsilon)."""
    df = df.copy()
    new_cols: list[pd.Series] = []
    for num in numerators:
        for den in denominators:
            if num == den:
                continue
            if num in df.columns and den in df.columns:
                s = df[num] / (df[den] + epsilon)
                s.name = f"ratio_{num}_per_{den}"
                new_cols.append(s)
    if new_cols:
        df = pd.concat([df] + new_cols, axis=1)
    return df


# ---------------------------------------------------------------------------
# Missing-value handling
# ---------------------------------------------------------------------------

def fill_missing(
    df: pd.DataFrame,
    method: str = "ffill_then_median",
    numeric_only: bool = True,
) -> pd.DataFrame:
    """Impute missing values.

    Strategies
    ----------
    ffill_then_median : Forward-fill first (preserves temporal correlation),
                        then fill any remaining NaN with column median.
    median            : Column-wise median imputation only.
    zero              : Fill with 0 (useful for pollutant counts).
    """
    df = df.copy()
    num_cols = df.select_dtypes(include="number").columns if numeric_only else df.columns

    if method == "ffill_then_median":
        df[num_cols] = df[num_cols].ffill()
        medians = df[num_cols].median()
        df[num_cols] = df[num_cols].fillna(medians)
    elif method == "median":
        medians = df[num_cols].median()
        df[num_cols] = df[num_cols].fillna(medians)
    elif method == "zero":
        df[num_cols] = df[num_cols].fillna(0.0)
    else:
        raise ValueError(f"Unknown imputation method: '{method}'")

    remaining = df[num_cols].isna().sum().sum()
    if remaining:
        logger.warning("%d NaN values remain after imputation.", remaining)
    return df


# ---------------------------------------------------------------------------
# Feature-selection helper
# ---------------------------------------------------------------------------

def drop_low_variance(
    df: pd.DataFrame,
    threshold: float = 1e-5,
    exclude_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Drop numeric columns whose variance is below ``threshold``."""
    exclude_cols = exclude_cols or []
    df = df.copy()
    num_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in exclude_cols
    ]
    variances = df[num_cols].var()
    low_var_cols = variances[variances < threshold].index.tolist()
    if low_var_cols:
        logger.info("Dropping %d low-variance columns: %s", len(low_var_cols), low_var_cols)
        df = df.drop(columns=low_var_cols)
    return df


# ---------------------------------------------------------------------------
# Convenience: build full feature matrix for anomaly / forecast pipelines
# ---------------------------------------------------------------------------

def build_feature_matrix(
    df: pd.DataFrame,
    pollutant_cols: list[str],
    timestamp_col: str = "measured_at",
    lags: Optional[list[int]] = None,
    windows: Optional[list[int]] = None,
    include_cyclical: bool = True,
    include_t_rel: bool = True,
) -> pd.DataFrame:
    """One-shot feature engineering pipeline.

    Applies (in order): lag features → rolling features → cyclical time →
    relative time index → missing-value fill → drop low-variance.
    """
    lags = lags or [1, 2, 3, 6, 12, 24]
    windows = windows or [3, 6, 12, 24]

    df = add_lag_features(df, pollutant_cols, lags, timestamp_col)
    df = add_rolling_features(df, pollutant_cols, windows, timestamp_col=timestamp_col)

    if include_cyclical:
        df = add_cyclical_time_features(df, timestamp_col)
    if include_t_rel:
        df = add_relative_time_index(df, timestamp_col)

    df = fill_missing(df)
    df = drop_low_variance(df, exclude_cols=pollutant_cols)
    return df


# ---------------------------------------------------------------------------
# AQI predictor feature builder (exported so serving/inference.py avoids
# circular imports through aqi_predictor.train)
# ---------------------------------------------------------------------------

def _build_features_aqi(
    df: pd.DataFrame,
    pollutant_cols: list[str],
    ts_col: str,
    include_ratios: bool = True,
    include_cyclical: bool = True,
) -> pd.DataFrame:
    """Build features for the AQI classifier (no lag/rolling needed)."""
    df = fill_missing(df.copy())
    if include_ratios:
        df = add_pollutant_ratios(df, numerators=pollutant_cols, denominators=pollutant_cols)
    if include_cyclical and ts_col in df.columns:
        df = add_cyclical_time_features(df, timestamp_col=ts_col)
    return df
