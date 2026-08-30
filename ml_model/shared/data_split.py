"""
shared/data_split.py
====================
Strict chronological train/test splitting utilities.

Rules enforced here:
  - Data is ALWAYS sorted by timestamp before splitting.
  - NO random shuffle is applied at any point.
  - A gap (in rows) can be left between train and test to avoid
    look-ahead leakage in rolling-window features.

Usage
-----
    from shared.data_split import chronological_split, walk_forward_splits

    X_train, X_test, y_train, y_test = chronological_split(
        df, target_col="aqi", timestamp_col="measured_at", test_ratio=0.2
    )
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core split
# ---------------------------------------------------------------------------

def chronological_split(
    df: pd.DataFrame,
    target_col: str,
    timestamp_col: str = "measured_at",
    test_ratio: float = 0.20,
    gap_rows: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Return (X_train, X_test, y_train, y_test) using strict time ordering.

    Parameters
    ----------
    df          : Raw dataframe containing features + target + timestamp.
    target_col  : Column name for the prediction target.
    timestamp_col: Column used to sort chronologically.
    test_ratio  : Fraction of data reserved for test (0 < ratio < 1).
    gap_rows    : Number of rows to drop between train and test to prevent
                  leakage when lag/rolling features are used.
    """
    if timestamp_col not in df.columns:
        raise ValueError(
            f"timestamp_col '{timestamp_col}' not found. "
            f"Available columns: {list(df.columns)}"
        )
    if target_col not in df.columns:
        raise ValueError(f"target_col '{target_col}' not found.")

    df = df.sort_values(timestamp_col).reset_index(drop=True)

    n = len(df)
    split_idx = int(n * (1 - test_ratio))

    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx + gap_rows :]

    feature_cols = [c for c in df.columns if c not in (target_col, timestamp_col)]

    X_train = train_df[feature_cols]
    y_train = train_df[target_col]
    X_test = test_df[feature_cols]
    y_test = test_df[target_col]

    logger.info(
        "Chronological split: total=%d | train=%d | gap=%d | test=%d",
        n, len(train_df), gap_rows, len(test_df),
    )
    logger.info(
        "Train period: %s → %s",
        train_df[timestamp_col].min(),
        train_df[timestamp_col].max(),
    )
    logger.info(
        "Test  period: %s → %s",
        test_df[timestamp_col].min(),
        test_df[timestamp_col].max(),
    )
    return X_train, X_test, y_train, y_test


# ---------------------------------------------------------------------------
# Walk-forward (expanding window) splits for backtesting
# ---------------------------------------------------------------------------

def walk_forward_splits(
    df: pd.DataFrame,
    target_col: str,
    timestamp_col: str = "measured_at",
    n_splits: int = 5,
    min_train_ratio: float = 0.40,
    gap_rows: int = 0,
) -> list[tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]]:
    """Generate expanding-window walk-forward splits for backtesting.

    The training window starts at ``min_train_ratio`` of the data and expands
    to cover all but the last fold's test window.

    Parameters
    ----------
    n_splits        : Number of (train, test) fold pairs.
    min_train_ratio : Minimum fraction of data that forms the initial training window.
    gap_rows        : Rows to leave between train end and test start.

    Returns
    -------
    List of (X_train, X_test, y_train, y_test) tuples.
    """
    df = df.sort_values(timestamp_col).reset_index(drop=True)
    n = len(df)
    feature_cols = [c for c in df.columns if c not in (target_col, timestamp_col)]

    min_train_end = int(n * min_train_ratio)
    remaining = n - min_train_end
    fold_size = remaining // (n_splits + 1)

    splits = []
    for i in range(n_splits):
        train_end = min_train_end + i * fold_size
        test_start = train_end + gap_rows
        test_end = train_end + fold_size + gap_rows

        train_df = df.iloc[:train_end]
        test_df = df.iloc[test_start:test_end]

        if len(test_df) == 0:
            logger.warning("Fold %d produced empty test set – skipping.", i)
            continue

        splits.append((
            train_df[feature_cols],
            test_df[feature_cols],
            train_df[target_col],
            test_df[target_col],
        ))
        logger.debug(
            "Fold %d: train[0:%d] test[%d:%d]", i, train_end, test_start, test_end
        )

    logger.info("Generated %d walk-forward folds.", len(splits))
    return splits


# ---------------------------------------------------------------------------
# Anomaly-specific split (unsupervised: only X)
# ---------------------------------------------------------------------------

def chronological_split_unsupervised(
    df: pd.DataFrame,
    timestamp_col: str = "measured_at",
    test_ratio: float = 0.20,
    gap_rows: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (X_train, X_test) without a target column (for anomaly detection)."""
    if timestamp_col not in df.columns:
        raise ValueError(f"timestamp_col '{timestamp_col}' not found.")

    df = df.sort_values(timestamp_col).reset_index(drop=True)
    n = len(df)
    split_idx = int(n * (1 - test_ratio))

    feature_cols = [c for c in df.columns if c != timestamp_col]
    X_train = df.iloc[:split_idx][feature_cols]
    X_test = df.iloc[split_idx + gap_rows :][feature_cols]

    logger.info(
        "Unsupervised chronological split: train=%d | test=%d", len(X_train), len(X_test)
    )
    return X_train, X_test
