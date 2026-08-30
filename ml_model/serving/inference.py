"""
serving/inference.py
====================
Public inference API for the ML module.

All four functions below are the ONLY entry points that backend teams need.
Cloud model fetching is handled internally by model_loader.py.

Functions
---------
calculate_aqi(pollutant_readings)  → dict   (rule-based CPCB formula)
calculate_wqi(water_params)        → dict   (rule-based WQI formula)
forecast(dataset_id, parameter, hours) → list[dict]   (XGBoost model)
detect_anomalies(dataset_id, parameter) → list[dict]  (IsolationForest)

CPCB AQI Formula (Indian Standard)
------------------------------------
Sub-Index for each pollutant i:

    SI_i = I_Hi + (I_Hi - I_Lo) / (C_Hi - C_Lo) × (C_p - C_Lo)

Where C_p is the measured concentration, C_Lo/C_Hi are the breakpoint
concentrations for the sub-index range I_Lo/I_Hi.

Overall AQI = MAX(SI_1, SI_2, …, SI_n)  [highest sub-index governs]

WQI Formula (Weighted Arithmetic Index – Indian BIS/WHO adapted)
-----------------------------------------------------------------
WQI = Σ (Qi × Wi) / Σ Wi

Where Qi = 100 × (Vi - Vid) / (Si - Vid)
  Vi  = observed value
  Vid = ideal value (usually 0 for most parameters, 7.0 for pH)
  Si  = standard permissible value (BIS IS:10500-2012 for drinking water)
  Wi  = unit weight = K / Si   (K = proportionality constant)

WQI Ranges
----------
0–25    : Excellent
26–50   : Good
51–75   : Poor
76–100  : Very Poor
> 100   : Unsuitable for drinking
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ML_ROOT))

from serving.model_loader import load as _load_model
from shared.features import build_feature_matrix, _build_features_aqi  # noqa: F401

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. CPCB AQI Calculation (Rule-Based)
# ===========================================================================

# Breakpoint table: {pollutant: [(C_lo, C_hi, I_lo, I_hi), ...]}
# Source: CPCB National Air Quality Index (2014)
_AQI_BREAKPOINTS: dict[str, list[tuple[float, float, int, int]]] = {
    "pm25": [      # µg/m³ (24-hr avg)
        (0.0,    30.0,   0,   50),
        (30.0,   60.0,  51,  100),
        (60.0,   90.0, 101,  200),
        (90.0,  120.0, 201,  300),
        (120.0, 250.0, 301,  400),
        (250.0, 500.0, 401,  500),
    ],
    "pm10": [      # µg/m³ (24-hr avg)
        (0.0,    50.0,   0,   50),
        (50.0,  100.0,  51,  100),
        (100.0, 250.0, 101,  200),
        (250.0, 350.0, 201,  300),
        (350.0, 430.0, 301,  400),
        (430.0, 600.0, 401,  500),
    ],
    "no2": [       # µg/m³ (24-hr avg)
        (0.0,    40.0,   0,   50),
        (40.0,   80.0,  51,  100),
        (80.0,  180.0, 101,  200),
        (180.0, 280.0, 201,  300),
        (280.0, 400.0, 301,  400),
        (400.0, 800.0, 401,  500),
    ],
    "so2": [       # µg/m³ (24-hr avg)
        (0.0,    40.0,   0,   50),
        (40.0,   80.0,  51,  100),
        (80.0,  380.0, 101,  200),
        (380.0, 800.0, 201,  300),
        (800.0,1600.0, 301,  400),
        (1600.0,2100.0,401,  500),
    ],
    "co": [        # mg/m³ (8-hr avg)
        (0.0,   1.0,   0,   50),
        (1.0,   2.0,  51,  100),
        (2.0,  10.0, 101,  200),
        (10.0, 17.0, 201,  300),
        (17.0, 34.0, 301,  400),
        (34.0, 48.0, 401,  500),
    ],
    "o3": [        # µg/m³ (8-hr avg)
        (0.0,   50.0,   0,   50),
        (50.0, 100.0,  51,  100),
        (100.0,168.0, 101,  200),
        (168.0,208.0, 201,  300),
        (208.0,748.0, 301,  400),
        (748.0,1000.0,401,  500),
    ],
    "nh3": [       # µg/m³ (24-hr avg)
        (0.0,    200.0,   0,   50),
        (200.0,  400.0,  51,  100),
        (400.0,  800.0, 101,  200),
        (800.0, 1200.0, 201,  300),
        (1200.0,1800.0, 301,  400),
        (1800.0,2400.0, 401,  500),
    ],
    "pb": [        # µg/m³ (24-hr avg)
        (0.0,    0.5,   0,   50),
        (0.5,   1.0,  51,  100),
        (1.0,   2.0, 101,  200),
        (2.0,   3.0, 201,  300),
        (3.0,   3.5, 301,  400),
        (3.5,   4.0, 401,  500),
    ],
}

_AQI_CATEGORY: dict[tuple[int, int], str] = {
    (0,    50):  "Good",
    (51,  100):  "Satisfactory",
    (101, 200):  "Moderate",
    (201, 300):  "Poor",
    (301, 400):  "Very Poor",
    (401, 500):  "Severe",
}

_HEALTH_MESSAGES: dict[str, str] = {
    "Good":         "Air quality is satisfactory. No health risk.",
    "Satisfactory": "Minor breathing discomfort for sensitive individuals.",
    "Moderate":     "Breathing discomfort for people with lung/heart disease.",
    "Poor":         "Breathing discomfort for most people on prolonged exposure.",
    "Very Poor":    "Respiratory illness on prolonged exposure. Avoid outdoor activities.",
    "Severe":       "Serious health hazard. Stay indoors. Avoid all physical activity.",
}


def _compute_sub_index(pollutant: str, concentration: float) -> Optional[float]:
    """Compute the CPCB sub-index for a single pollutant at given concentration."""
    if pollutant not in _AQI_BREAKPOINTS:
        return None
    for (c_lo, c_hi, i_lo, i_hi) in _AQI_BREAKPOINTS[pollutant]:
        if c_lo <= concentration <= c_hi:
            # Linear interpolation
            if c_hi == c_lo:
                return float(i_lo)
            si = i_lo + (i_hi - i_lo) * (concentration - c_lo) / (c_hi - c_lo)
            return round(si, 2)
    # Concentration above highest breakpoint – cap at 500
    return 500.0


def calculate_aqi(pollutant_readings: dict) -> dict:
    """
    Compute the CPCB Air Quality Index from pollutant concentrations.

    Parameters
    ----------
    pollutant_readings : dict
        Keys: any subset of {pm25, pm10, no2, so2, co, o3, nh3, pb}.
        Values: float concentration in the units defined by CPCB breakpoints.
        At least ONE recognised pollutant must be present.

    Returns
    -------
    dict with keys:
        aqi            : int   – overall AQI (max sub-index)
        category       : str   – CPCB category name
        health_message : str   – plain-language health advisory
        dominant       : str   – pollutant driving the AQI
        sub_indices    : dict  – individual sub-index per pollutant
        timestamp      : str   – ISO-8601 UTC computation time

    Raises
    ------
    ValueError : if no recognised pollutant key is provided.

    Example
    -------
    >>> calculate_aqi({"pm25": 55.0, "no2": 120.0})
    {
      "aqi": 110,
      "category": "Moderate",
      "dominant": "pm25",
      "sub_indices": {"pm25": 109.17, "no2": 66.67},
      ...
    }
    """
    sub_indices: dict[str, float] = {}

    for pollutant, concentration in pollutant_readings.items():
        key = pollutant.lower().replace(".", "").replace("-", "")
        if concentration is None or (isinstance(concentration, float) and np.isnan(concentration)):
            continue
        si = _compute_sub_index(key, float(concentration))
        if si is not None:
            sub_indices[key] = si

    if not sub_indices:
        raise ValueError(
            "No recognised pollutant readings found. "
            f"Recognised keys: {list(_AQI_BREAKPOINTS.keys())}. "
            f"Received: {list(pollutant_readings.keys())}"
        )

    overall_aqi = max(sub_indices.values())
    dominant = max(sub_indices, key=sub_indices.get)  # type: ignore[arg-type]
    aqi_int = int(round(overall_aqi))

    category = "Severe"  # default upper bound
    for (lo, hi), name in _AQI_CATEGORY.items():
        if lo <= aqi_int <= hi:
            category = name
            break

    return {
        "aqi": aqi_int,
        "category": category,
        "health_message": _HEALTH_MESSAGES.get(category, ""),
        "dominant_pollutant": dominant,
        "sub_indices": sub_indices,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


# ===========================================================================
# 2. WQI Calculation (Rule-Based – Weighted Arithmetic Index)
# ===========================================================================

# BIS IS:10500-2012 standards (Si) and ideal values (Vid)
# Unit weight Wi = K / Si  where K = 1 / Σ(1/Si)
_WQI_PARAMS: dict[str, dict[str, float]] = {
    "pH":                {"Si": 8.5,    "Vid": 7.0},
    "turbidity":         {"Si": 1.0,    "Vid": 0.0},   # NTU
    "TDS":               {"Si": 500.0,  "Vid": 0.0},   # mg/L
    "hardness":          {"Si": 300.0,  "Vid": 0.0},   # mg/L as CaCO3
    "chlorides":         {"Si": 250.0,  "Vid": 0.0},   # mg/L
    "sulfates":          {"Si": 200.0,  "Vid": 0.0},   # mg/L
    "nitrates":          {"Si": 45.0,   "Vid": 0.0},   # mg/L
    "fluorides":         {"Si": 1.0,    "Vid": 0.0},   # mg/L
    "iron":              {"Si": 0.3,    "Vid": 0.0},   # mg/L
    "manganese":         {"Si": 0.1,    "Vid": 0.0},   # mg/L
    "arsenic":           {"Si": 0.01,   "Vid": 0.0},   # mg/L
    "DO":                {"Si": 5.0,    "Vid": 14.6},  # mg/L (inverted – lower is worse)
    "BOD":               {"Si": 3.0,    "Vid": 0.0},   # mg/L (higher is worse)
    "total_coliforms":   {"Si": 0.0,    "Vid": 0.0},   # MPN/100mL (0 = standard; presence = bad)
    "fecal_coliforms":   {"Si": 0.0,    "Vid": 0.0},
}

_WQI_CATEGORY: list[tuple[tuple[float, float], str]] = [
    ((0.0,   25.0), "Excellent"),
    ((25.0,  50.0), "Good"),
    ((50.0,  75.0), "Poor"),
    ((75.0, 100.0), "Very Poor"),
    ((100.0, 1e9),  "Unsuitable for Drinking"),
]


def calculate_wqi(water_params: dict) -> dict:
    """
    Compute the Water Quality Index using the Weighted Arithmetic Index method.

    Parameters
    ----------
    water_params : dict
        Keys: any subset of recognised water quality parameters (case-insensitive).
        Values: float measured values in the units shown in _WQI_PARAMS.

    Returns
    -------
    dict with keys:
        wqi             : float – overall WQI score
        category        : str   – quality category
        parameter_scores: dict  – Qi score per parameter
        weights         : dict  – Wi weight per parameter
        timestamp       : str

    Raises
    ------
    ValueError : if no recognised parameter key is provided.

    Example
    -------
    >>> calculate_wqi({"pH": 7.2, "turbidity": 2.5, "TDS": 320.0, "DO": 6.0})
    {"wqi": 43.2, "category": "Good", ...}
    """
    # Normalise keys
    normalised = {k.lower().replace(" ", "_"): v for k, v in water_params.items()}
    params_lower = {k.lower().replace(" ", "_"): v for k, v in _WQI_PARAMS.items()}

    # Compute unit weights (Wi = K / Si)
    # K = 1 / Σ(1/Si) for parameters present and with Si > 0
    matched: dict[str, dict] = {}
    for param, val in normalised.items():
        if param in params_lower and val is not None:
            std_info = params_lower[param]
            if std_info["Si"] > 0:
                matched[param] = {"value": float(val), **std_info}

    if not matched:
        raise ValueError(
            "No recognised water quality parameters found. "
            f"Recognised keys: {list(_WQI_PARAMS.keys())}."
        )

    k_constant = 1.0 / sum(1.0 / d["Si"] for d in matched.values())

    qi_scores: dict[str, float] = {}
    weights: dict[str, float] = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for param, d in matched.items():
        Vi = d["value"]
        Si = d["Si"]
        Vid = d["Vid"]

        # For DO: lower observed value → higher sub-index (pollution indicator)
        if param == "do":
            Qi = 100.0 * (Vid - Vi) / (Vid - Si) if (Vid - Si) != 0 else 0.0
        else:
            Qi = 100.0 * (Vi - Vid) / (Si - Vid) if (Si - Vid) != 0 else 0.0

        Qi = max(0.0, min(Qi, 200.0))  # clamp (> 100 = beyond standard)
        Wi = k_constant / Si

        qi_scores[param] = round(Qi, 4)
        weights[param] = round(Wi, 8)
        weighted_sum += Qi * Wi
        weight_total += Wi

    wqi = round(weighted_sum / weight_total, 4) if weight_total > 0 else 0.0

    category = "Unsuitable for Drinking"
    for (lo, hi), name in _WQI_CATEGORY:
        if lo <= wqi < hi:
            category = name
            break

    return {
        "wqi": wqi,
        "category": category,
        "parameter_scores": qi_scores,
        "weights": weights,
        "n_parameters": len(matched),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


# ===========================================================================
# 1b. ML-Based AQI Prediction
# ===========================================================================

def predict_aqi(pollutant_readings: dict) -> dict:
    """
    Predict AQI score and category using trained XGBoost ML model.

    Parameters
    ----------
    pollutant_readings : dict
        Dict of pollutant concentrations (e.g. {"pm25": 55.0, "no2": 80.0}).

    Returns
    -------
    dict with keys:
        aqi            : float – predicted numeric AQI score from XGBRegressor
        category       : str   – predicted AQI category from XGBClassifier
        confidence     : float – probability score for the top predicted category
        class_probabilities : dict – probabilities across all AQI categories
        model_version  : str   – version of the loaded model artifact
        timestamp      : str   – UTC ISO timestamp
    """
    pipeline = _load_model("aqi")
    regressor = pipeline["regressor"]
    classifier = pipeline["classifier"]
    le = pipeline["label_encoder"]
    feature_cols: list[str] = pipeline["feature_cols"]
    pollutant_cols: list[str] = pipeline["pollutant_cols"]
    category_names: dict = pipeline.get("category_names", {})

    # Build input DataFrame
    normalised = {k.lower(): float(v) for k, v in pollutant_readings.items()}
    df_raw = pd.DataFrame([normalised])

    df_feat = _build_features_aqi(
        df_raw,
        pollutant_cols=pollutant_cols,
        ts_col="measured_at",
        include_ratios=True,
        include_cyclical=False,
    )

    X = df_feat.reindex(columns=feature_cols, fill_value=0.0)

    predicted_aqi = float(regressor.predict(X)[0])
    predicted_aqi = round(max(0.0, min(500.0, predicted_aqi)), 2)

    probs = classifier.predict_proba(X)[0]
    top_idx = int(np.argmax(probs))
    confidence = float(probs[top_idx])

    cat_label = str(le.classes_[top_idx])
    category_name = category_names.get(cat_label, cat_label)

    probs_dict = {
        category_names.get(str(cls), str(cls)): round(float(p), 4)
        for cls, p in zip(le.classes_, probs)
    }

    return {
        "aqi": predicted_aqi,
        "category": category_name,
        "confidence": round(confidence, 4),
        "class_probabilities": probs_dict,
        "model_type": "XGBoost (ML)",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


# ===========================================================================
# 2b. ML-Based WQI Prediction
# ===========================================================================

def predict_wqi(water_params: dict) -> dict:
    """
    Predict Water Quality Index (WQI) score and category using trained XGBoost ML model.

    Parameters
    ----------
    water_params : dict
        Dict of water parameters (e.g. {"pH": 7.2, "turbidity": 2.5, "TDS": 320.0, "DO": 6.5}).

    Returns
    -------
    dict with keys:
        wqi            : float – predicted WQI score from XGBRegressor
        category       : str   – predicted WQI category from XGBClassifier
        confidence     : float – probability score for the top predicted category
        class_probabilities : dict – probabilities across all WQI categories
        model_type     : str   – "XGBoost (ML)"
        timestamp      : str   – UTC ISO timestamp
    """
    pipeline = _load_model("wqi")
    regressor = pipeline["regressor"]
    classifier = pipeline["classifier"]
    le = pipeline["label_encoder"]
    feature_cols: list[str] = pipeline["feature_cols"]
    water_cols: list[str] = pipeline["water_cols"]
    category_names: dict = pipeline.get("category_names", {})

    normalised = {k.lower(): float(v) for k, v in water_params.items()}
    df_raw = pd.DataFrame([normalised])

    df_feat = _build_features_aqi(
        df_raw,
        pollutant_cols=water_cols,
        ts_col="measured_at",
        include_ratios=True,
        include_cyclical=False,
    )

    X = df_feat.reindex(columns=feature_cols, fill_value=0.0)

    predicted_wqi = float(regressor.predict(X)[0])
    predicted_wqi = round(max(0.0, predicted_wqi), 2)

    probs = classifier.predict_proba(X)[0]
    top_idx = int(np.argmax(probs))
    confidence = float(probs[top_idx])

    cat_name = category_names.get(str(top_idx), str(le.classes_[top_idx]))

    probs_dict = {
        category_names.get(str(i), str(cls)): round(float(p), 4)
        for i, (cls, p) in enumerate(zip(le.classes_, probs))
    }

    return {
        "wqi": predicted_wqi,
        "category": cat_name,
        "confidence": round(confidence, 4),
        "class_probabilities": probs_dict,
        "model_type": "XGBoost (ML)",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }



# ===========================================================================
# 3. Time-Series Forecast (ML Model)
# ===========================================================================

def forecast(
    dataset_id: str,
    parameter: str,
    hours: int,
    historical_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """
    Predict pollutant / weather values for the next ``hours`` hours.

    Parameters
    ----------
    dataset_id    : Logical identifier for the sensor station / dataset.
                    Used to fetch/filter data if historical_df is None.
    parameter     : Pollutant or weather column to forecast (e.g. "pm25").
    hours         : Forecast horizon in hours (supported: 24, 48, 72).
                    Snapped to the nearest trained horizon.
    historical_df : Pre-loaded DataFrame with columns [measured_at, <parameter>, …].
                    If None, a synthetic recent window is generated for demo.

    Returns
    -------
    list of dicts, one per hour:
        [
          {"step": 1, "hours_ahead": 1, "predicted": 58.3,
           "lower_ci": 52.1, "upper_ci": 64.5,
           "timestamp_utc": "2024-01-01T02:00:00+00:00"},
          ...
        ]
    """
    pipeline = _load_model("forecast")
    horizon_models: dict = pipeline["horizon_models"]
    feature_cols: list[str] = pipeline["feature_cols"]
    ts_col: str = pipeline.get("ts_col", "measured_at")
    trained_horizons: list[int] = pipeline.get("horizons", [24, 48, 72])

    # Snap to nearest trained horizon
    nearest_h = min(trained_horizons, key=lambda h: abs(h - hours))
    if nearest_h not in trained_horizons or f"h{nearest_h}" not in horizon_models:
        raise ValueError(
            f"No trained model for horizon ~{hours}h. "
            f"Available horizons: {trained_horizons}"
        )

    # Load / generate historical data
    if historical_df is None:
        logger.warning(
            "No historical_df supplied for dataset_id='%s'. "
            "Using synthetic data – integrate real data fetching here.",
            dataset_id,
        )
        from forecast.train import _generate_synthetic_data
        historical_df = _generate_synthetic_data(target=parameter)

    # Feature engineering
    pollutant_cols = [c for c in ["pm25", "pm10", "no2", "so2", "co", "o3"] if c in historical_df.columns]
    weather_cols = [c for c in ["temperature", "humidity", "wind_speed"] if c in historical_df.columns]

    from shared.features import build_feature_matrix as _bfm
    df_feat = _bfm(
        historical_df,
        pollutant_cols=pollutant_cols + weather_cols,
        timestamp_col=ts_col,
        lags=[1, 2, 3, 6, 12, 24, 48],
        windows=[3, 6, 12, 24, 48],
        include_cyclical=True,
        include_t_rel=True,
    )

    # Use last row as the feature vector for the 1-step prediction
    # (direct horizon model: one prediction per model, one row input)
    last_row = df_feat.reindex(columns=feature_cols, fill_value=0.0).iloc[-1:]

    model = horizon_models[f"h{nearest_h}"]
    pred_value = float(model.predict(last_row)[0])

    # Estimate confidence interval via ±10 % heuristic
    # (replace with quantile regression for production)
    margin = abs(pred_value) * 0.10
    base_time = pd.to_datetime(historical_df[ts_col].iloc[-1], utc=True)

    results = []
    for step in range(1, nearest_h + 1):
        ts = base_time + pd.Timedelta(hours=step)
        # Slight decay of uncertainty for inner steps vs outer
        step_margin = margin * (step / nearest_h)
        results.append({
            "step": step,
            "hours_ahead": step,
            "parameter": parameter,
            "predicted": round(pred_value, 4),
            "lower_ci": round(max(0.0, pred_value - step_margin), 4),
            "upper_ci": round(pred_value + step_margin, 4),
            "timestamp_utc": ts.isoformat(),
            "dataset_id": dataset_id,
        })

    return results


# ===========================================================================
# 4. Anomaly Detection (ML Model)
# ===========================================================================

def detect_anomalies(
    dataset_id: str,
    parameter: str,
    data: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """
    Run the IsolationForest model to flag anomalous readings.

    Parameters
    ----------
    dataset_id : Logical identifier for the sensor station / dataset.
    parameter  : Primary pollutant column to highlight (e.g. "pm25").
    data       : DataFrame with columns [measured_at, pm25, pm10, …].
                 If None, uses synthetic data for demo.

    Returns
    -------
    list of dicts for ANOMALY rows only:
        [
          {
            "index": 42,
            "measured_at": "2024-01-15T14:00:00",
            "parameter": "pm25",
            "value": 387.2,
            "anomaly_score": -0.28,
            "is_anomaly": true,
            "dataset_id": "station_001"
          },
          ...
        ]

    Returns an empty list if no anomalies are detected.
    """
    pipeline = _load_model("anomaly")
    scaler = pipeline["scaler"]
    model = pipeline["model"]
    feature_cols: list[str] = pipeline["feature_cols"]

    # Load data
    if data is None:
        logger.warning(
            "No data supplied for dataset_id='%s'. Using synthetic data.", dataset_id
        )
        from anomaly.train import _generate_synthetic_data
        data = _generate_synthetic_data()

    ts_col = "measured_at"
    pollutant_cols = [c for c in ["pm25", "pm10", "no2", "so2", "co", "o3"] if c in data.columns]

    from shared.features import build_feature_matrix as _bfm
    df_feat = _bfm(
        data,
        pollutant_cols=pollutant_cols,
        timestamp_col=ts_col,
        lags=[1, 2, 3, 6, 12, 24],
        windows=[3, 6, 12, 24],
        include_cyclical=True,
        include_t_rel=True,
    )

    X = df_feat.reindex(columns=feature_cols, fill_value=0.0)
    X_scaled = scaler.transform(X)

    scores = model.decision_function(X_scaled)
    threshold = float(os.environ.get("ANOMALY_THRESHOLD", "-0.1"))
    is_anomaly = scores < threshold

    anomaly_indices = np.where(is_anomaly)[0]
    results = []
    for idx in anomaly_indices:
        original_idx = df_feat.index[idx]
        row_ts = data.at[original_idx, ts_col] if ts_col in data.columns else None
        param_val = data.at[original_idx, parameter] if parameter in data.columns else None

        results.append({
            "index": int(original_idx),
            "measured_at": str(row_ts),
            "parameter": parameter,
            "value": round(float(param_val), 4) if param_val is not None else None,
            "anomaly_score": round(float(scores[idx]), 6),
            "is_anomaly": True,
            "dataset_id": dataset_id,
        })

    logger.info(
        "detect_anomalies: dataset_id=%s parameter=%s → %d anomalies out of %d rows",
        dataset_id, parameter, len(results), len(X),
    )
    return results

