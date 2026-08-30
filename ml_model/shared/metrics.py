"""
shared/metrics.py
=================
Centralised metric computation for all three ML sub-systems.

Metrics provided
----------------
Regression  : MAE, RMSE, MAPE, R²
Classification: Precision, Recall, F1 (macro/weighted), Accuracy, confusion matrix
Drift       : KS-test p-value and statistic per feature column

All functions return plain Python dicts so results can be JSON-serialised
and written to the model registry without additional transformation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regression metrics
# ---------------------------------------------------------------------------

def regression_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    prefix: str = "",
) -> dict[str, float]:
    """Compute MAE, RMSE, MAPE, R² and return as a flat dict."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))

    # MAPE – guard against zeros in y_true
    nonzero = y_true != 0
    mape = float(
        np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100
    ) if nonzero.any() else float("nan")

    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else float("nan")

    result = {
        f"{prefix}mae": round(mae, 6),
        f"{prefix}rmse": round(rmse, 6),
        f"{prefix}mape": round(mape, 4),
        f"{prefix}r2": round(r2, 6),
    }
    logger.info("Regression metrics: %s", result)
    return result


# ---------------------------------------------------------------------------
# Classification metrics
# ---------------------------------------------------------------------------

def classification_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    labels: Optional[list] = None,
    average: str = "weighted",
    prefix: str = "",
) -> dict[str, Any]:
    """Compute Precision, Recall, F1, Accuracy and a confusion matrix."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    kwargs: dict[str, Any] = {"average": average, "zero_division": 0}
    if labels is not None:
        kwargs["labels"] = labels

    precision = float(precision_score(y_true, y_pred, **kwargs))
    recall = float(recall_score(y_true, y_pred, **kwargs))
    f1 = float(f1_score(y_true, y_pred, **kwargs))
    accuracy = float(accuracy_score(y_true, y_pred))

    cm_labels = labels if labels is not None else sorted(set(y_true.tolist() + y_pred.tolist()))
    cm = confusion_matrix(y_true, y_pred, labels=cm_labels).tolist()

    result: dict[str, Any] = {
        f"{prefix}precision_{average}": round(precision, 6),
        f"{prefix}recall_{average}": round(recall, 6),
        f"{prefix}f1_{average}": round(f1, 6),
        f"{prefix}accuracy": round(accuracy, 6),
        f"{prefix}confusion_matrix": cm,
        f"{prefix}labels": cm_labels,
    }
    logger.info(
        "Classification metrics: precision=%.4f recall=%.4f f1=%.4f acc=%.4f",
        precision, recall, f1, accuracy,
    )
    return result


# ---------------------------------------------------------------------------
# Anomaly detection metrics
# ---------------------------------------------------------------------------

def anomaly_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    prefix: str = "",
) -> dict[str, Any]:
    """Precision, Recall, F1 for binary anomaly labels (1=anomaly, 0=normal).

    Both ``y_true`` and ``y_pred`` should be binary arrays/series where
    1 indicates an anomaly.
    """
    return classification_metrics(
        y_true=y_true,
        y_pred=y_pred,
        labels=[0, 1],
        average="binary",
        prefix=prefix,
    )


# ---------------------------------------------------------------------------
# Drift detection – KS test
# ---------------------------------------------------------------------------

def ks_drift_test(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Run a two-sample Kolmogorov–Smirnov test on every shared numeric column.

    Parameters
    ----------
    reference : Training-set dataframe (baseline distribution).
    current   : New batch dataframe to test for drift.
    alpha     : Significance level for drift decision.

    Returns
    -------
    Dict with per-feature KS statistics and an overall ``drift_detected`` flag.
    """
    shared_cols = [
        c for c in reference.columns
        if c in current.columns and pd.api.types.is_numeric_dtype(reference[c])
    ]

    results: dict[str, Any] = {}
    any_drift = False

    for col in shared_cols:
        ref_vals = reference[col].dropna().values
        cur_vals = current[col].dropna().values

        if len(ref_vals) < 2 or len(cur_vals) < 2:
            logger.warning("Column '%s' has too few values for KS test – skipping.", col)
            continue

        ks_stat, p_value = stats.ks_2samp(ref_vals, cur_vals)
        drifted = bool(p_value < alpha)
        any_drift = any_drift or drifted

        results[col] = {
            "ks_statistic": round(float(ks_stat), 6),
            "p_value": round(float(p_value), 6),
            "drift_detected": drifted,
        }
        if drifted:
            logger.warning(
                "DRIFT detected on '%s': KS=%.4f p=%.4f (α=%.2f)",
                col, ks_stat, p_value, alpha,
            )

    results["overall_drift_detected"] = any_drift
    results["alpha"] = alpha
    return results


# ---------------------------------------------------------------------------
# Backtest summary (for time-series / walk-forward)
# ---------------------------------------------------------------------------

def backtest_summary(
    fold_metrics: list[dict[str, float]],
    metric_keys: list[str],
) -> dict[str, Any]:
    """Aggregate per-fold metrics into mean ± std across walk-forward folds."""
    summary: dict[str, Any] = {"n_folds": len(fold_metrics)}
    for key in metric_keys:
        values = [m[key] for m in fold_metrics if key in m]
        if values:
            summary[f"{key}_mean"] = round(float(np.mean(values)), 6)
            summary[f"{key}_std"] = round(float(np.std(values)), 6)
    return summary


# ---------------------------------------------------------------------------
# Utility: pretty-print a report dict
# ---------------------------------------------------------------------------

def print_report(report: dict, title: str = "Evaluation Report") -> None:
    """Pretty-print a metrics dictionary to stdout."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)
    print(json.dumps(report, indent=2, default=str))
    print("=" * 60 + "\n")
