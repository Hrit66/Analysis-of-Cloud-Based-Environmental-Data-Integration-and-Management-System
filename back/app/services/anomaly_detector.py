import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Any, Optional, Tuple
import joblib
import os
import json
from datetime import datetime

from app.services.forecaster import fit_seasonal_baseline, predict_seasonal_baseline


MODEL_DIR = "models"
ANOMALY_MODEL_PREFIX = "isolation_forest_"
METADATA_FILE = os.path.join(MODEL_DIR, "anomaly_metadata.json")

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']
WEATHER_COLS = ['temperature', 'temp_min', 'temp_max', 'precipitation']
WATER_ANOMALY_COLS = ['do', 'wqi']
FEATURE_POOL = POLLUTANT_COLS + WEATHER_COLS

# Air quality uses Isolation Forest. 2% is deliberately conservative: a
# flagged sample means "unusual for this station", not "failed a limit", and
# the same record is emitted once per populated pollutant, so 5% would label
# roughly one in twenty station-days on every parameter.
DEFAULT_CONTAMINATION = 0.02
MIN_TRAIN_SAMPLES = 50
MIN_COLUMN_COVERAGE = 0.5
MIN_REUSE_COVERAGE = 0.1
TEST_SPLIT_RATIO = 0.2

WEATHER_Z_THRESHOLD = 3.0
WEATHER_MIN_POINTS = 50
WEATHER_SEASONAL_MIN_SAMPLES = 200
WEATHER_SEASONAL_MIN_SPAN_DAYS = 300.0

# Water series are far shorter than weather series (15-48 monthly samples per
# station), so the minimum is lower and every series is scored with a raw
# robust z-score - a seasonal fit would be fitted on noise at this length.
WATER_Z_THRESHOLD = 3.0
WATER_MIN_POINTS = 15


def _model_key(location: str, scope: Optional[str] = None) -> str:
    """Models are keyed by location, optionally namespaced by a scope
    (e.g. one dataset) so pollutant and weather models never collide."""
    return f"{location}__{scope}" if scope else location


def _get_model_path(location: str, scope: Optional[str] = None) -> str:
    key = _model_key(location, scope)
    safe_key = key.replace(" ", "_").replace("/", "_")
    return os.path.join(MODEL_DIR, f"{ANOMALY_MODEL_PREFIX}{safe_key}.joblib")


def _load_metadata() -> Dict[str, Any]:
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {}


def _save_metadata(metadata: Dict[str, Any]):
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)


def _time_series_split(df: pd.DataFrame, test_ratio: float = TEST_SPLIT_RATIO) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split data chronologically - train on earlier data, test on later."""
    df = df.sort_values('timestamp').reset_index(drop=True)
    split_idx = int(len(df) * (1 - test_ratio))
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df


def _select_feature_columns(loc_df: pd.DataFrame) -> List[str]:
    """Pick feature columns that are well populated for this location.

    Handles both pollutant series (air quality) and weather series
    (temperature, precipitation). Real-world data (e.g. Kaggle city_day) is
    sparse: many stations report only a subset of pollutants. Columns with
    >=50% coverage are used; if none qualify, fall back to any column with
    enough samples to train.
    """
    pool = [c for c in FEATURE_POOL if c in loc_df.columns]
    coverage = loc_df[pool].notna().mean() if pool else pd.Series(dtype=float)
    cols = [c for c in pool if coverage.get(c, 0) >= MIN_COLUMN_COVERAGE]
    if not cols:
        cols = [c for c in pool if loc_df[c].notna().sum() >= MIN_TRAIN_SAMPLES]
    return cols


def _features_usable(df: pd.DataFrame, feature_columns: List[str]) -> bool:
    """Guard against reusing a model whose features are absent or empty in
    this dataframe (e.g. a pollutant model applied to a weather dataset)."""
    if not feature_columns or any(c not in df.columns for c in feature_columns):
        return False
    return float(df[feature_columns].notna().mean().min()) >= MIN_REUSE_COVERAGE


def _feature_frame(loc_df: pd.DataFrame, columns: Optional[List[str]] = None) -> Tuple[pd.DataFrame, List[str]]:
    """Build the feature matrix with per-column median imputation."""
    cols = list(columns) if columns else _select_feature_columns(loc_df)
    if not cols:
        raise ValueError("no feature columns with sufficient coverage")
    missing = [c for c in cols if c not in loc_df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}")
    X = loc_df[cols].astype(float)
    medians = X.median().fillna(0)
    return X.fillna(medians), cols


def _load_trained_model(location: str, scope: Optional[str] = None) -> Tuple[Optional[IsolationForest], Optional[List[str]]]:
    """Load a model only if its metadata records the feature columns it was
    trained with (older artifacts without this are treated as stale)."""
    metadata = _load_metadata()
    meta = metadata.get(_model_key(location, scope))
    model_path = _get_model_path(location, scope)
    if not meta or 'feature_columns' not in meta or not os.path.exists(model_path):
        return None, None
    return joblib.load(model_path), list(meta['feature_columns'])


def train_anomaly_model(
    df: pd.DataFrame, 
    location: str,
    contamination: float = DEFAULT_CONTAMINATION,
    test_ratio: float = TEST_SPLIT_RATIO,
    scope: Optional[str] = None
) -> Tuple[IsolationForest, Dict[str, Any]]:
    """
    Train Isolation Forest per location with time-series split.
    Handles sparse data by selecting well-populated columns and
    imputing gaps with the training median.
    Returns (model, evaluation_metrics).
    """
    loc_df = df[df['location'] == location].copy()
    loc_df = loc_df.sort_values('timestamp')
    
    if len(loc_df) < MIN_TRAIN_SAMPLES:
        raise ValueError(f"Insufficient data for {location}: {len(loc_df)} rows (min {MIN_TRAIN_SAMPLES})")
    
    columns = _select_feature_columns(loc_df)
    if not columns:
        raise ValueError(f"No usable feature columns for {location} (all candidate columns mostly empty)")
    
    train_df, test_df = _time_series_split(loc_df, test_ratio)
    
    train_X = train_df[columns].astype(float)
    medians = train_X.median().fillna(0)
    train_X = train_X.fillna(medians)
    test_X = test_df[columns].astype(float).fillna(medians)
    
    if len(train_X) < 10:
        raise ValueError(f"Insufficient training data for {location} after split")
    
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=200,
        n_jobs=-1,
        max_samples='auto'
    )
    model.fit(train_X)
    
    if len(test_X) > 0:
        test_scores = model.decision_function(test_X)
        test_preds = model.predict(test_X)
        test_anomaly_rate = (test_preds == -1).mean()
        score_mean = round(float(test_scores.mean()), 4)
        score_std = round(float(test_scores.std()), 4)
    else:
        test_anomaly_rate = 0.0
        score_mean = 0.0
        score_std = 0.0
    
    train_preds = model.predict(train_X)
    train_anomaly_rate = (train_preds == -1).mean()
    
    metrics = {
        "location": location,
        "scope": scope,
        "feature_columns": columns,
        "train_samples": int(len(train_X)),
        "test_samples": int(len(test_X)),
        "train_anomaly_rate": round(float(train_anomaly_rate) * 100, 2),
        "test_anomaly_rate": round(float(test_anomaly_rate) * 100, 2),
        "contamination_setting": contamination,
        "score_mean": score_mean,
        "score_std": score_std,
        "trained_at": datetime.utcnow().isoformat(),
    }
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = _get_model_path(location, scope)
    joblib.dump(model, model_path)
    
    # Update metadata
    metadata = _load_metadata()
    metadata[_model_key(location, scope)] = metrics
    _save_metadata(metadata)
    
    return model, metrics


def load_anomaly_model(location: str, scope: Optional[str] = None) -> IsolationForest:
    """Load trained Isolation Forest model for a location."""
    model_path = _get_model_path(location, scope)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Anomaly model not found for {location}. Train first.")
    return joblib.load(model_path)


def detect_anomalies(
    df: pd.DataFrame, 
    location: str = None,
    model: IsolationForest = None,
    contamination: float = DEFAULT_CONTAMINATION,
    scope: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Detect anomalies in air quality or weather data.
    If location specified, use/load the model for that location (retraining
    when missing, stale, or when its feature columns do not exist in this
    dataframe). If no location, use the legacy global model.
    Emits one row per (record, populated feature) with the record-level score.
    """
    feature_columns: Optional[List[str]] = None
    
    if model is None:
        if location:
            model, feature_columns = _load_trained_model(location, scope)
            if model is not None and not _features_usable(df, feature_columns or []):
                model, feature_columns = None, None
            if model is None:
                model, metrics = train_anomaly_model(df, location, contamination, scope=scope)
                feature_columns = metrics.get('feature_columns')
        else:
            # Global model fallback (legacy)
            try:
                global_path = os.path.join(MODEL_DIR, f"{ANOMALY_MODEL_PREFIX}global.joblib")
                model = joblib.load(global_path)
            except FileNotFoundError:
                model = train_global_model(df, contamination)
            feature_columns = POLLUTANT_COLS
    
    X, feature_columns = _feature_frame(df, feature_columns)

    scores = model.decision_function(X.values)
    preds = model.predict(X.values)

    # Isolation Forest is multivariate: the expected range stored with each
    # flagged sample is a descriptive per-parameter band (median +/- 3 robust
    # SD), not the decision boundary. The detector column says so.
    bands: Dict[str, Tuple[float, float, float]] = {}
    for col in feature_columns:
        values = pd.to_numeric(df[col], errors='coerce').to_numpy(dtype=float)
        values = values[~np.isnan(values)]
        if len(values) == 0:
            bands[col] = (None, None, None)
            continue
        median, scale = _robust_stats(values)
        bands[col] = (median, median - 3.0 * scale, median + 3.0 * scale)

    results = []
    for i, (_, row) in enumerate(df.iterrows()):
        for col in feature_columns:
            val = row[col]
            if pd.notna(val):
                is_anomaly = bool(preds[i] == -1)
                baseline, expected_low, expected_high = bands.get(col, (None, None, None))
                timestamp = row['timestamp']
                if isinstance(timestamp, str):
                    timestamp = pd.to_datetime(
                        timestamp, utc=True, format='mixed'
                    ).to_pydatetime()
                entry = {
                    'timestamp': timestamp,
                    'location': row['location'],
                    'parameter': col,
                    'value': float(val),
                    'is_anomaly': is_anomaly,
                    'anomaly_score': float(scores[i]),
                    'detector': 'isolation_forest',
                    'threshold': None,
                }
                if baseline is not None:
                    entry['baseline'] = round(float(baseline), 3)
                    entry['expected_low'] = round(float(expected_low), 3)
                    entry['expected_high'] = round(float(expected_high), 3)
                if is_anomaly:
                    entry['severity'] = _if_severity(float(scores[i]))
                results.append(entry)
    
    return results


def _robust_stats(values: np.ndarray) -> Tuple[float, float]:
    """Median and MAD-based robust SD (1.4826*MAD)."""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = 1.4826 * mad
    if scale <= 0:
        std = float(np.std(values))
        scale = std if std > 0 else 1.0
    return median, scale


def _robust_z(values: np.ndarray) -> np.ndarray:
    """Robust z-score via median absolute deviation (1.4826*MAD approximates
    the SD for normal data but is not inflated by the outliers being tested)."""
    median, scale = _robust_stats(values)
    return (values - median) / scale


def _z_severity(z: float) -> str:
    magnitude = abs(z)
    if magnitude >= 6.0:
        return 'extreme'
    if magnitude >= 4.0:
        return 'high'
    return 'moderate'


def _if_severity(score: float) -> str:
    """Isolation Forest decision score bands (lower = more anomalous)."""
    if score <= -0.15:
        return 'extreme'
    if score <= -0.05:
        return 'high'
    return 'moderate'


def detect_weather_anomalies(
    df: pd.DataFrame,
    location: Optional[str] = None,
    scope: Optional[str] = None,
    skip_reasons: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Residual-threshold anomaly detection for weather series.

    Raw-value scoring flags normal seasonal extremes, so each series is
    deseasonalised with the same harmonic baseline used for forecasting and
    days whose residual exceeds ~3 robust SD are flagged. Rainfall is treated
    as an event series: upper-tail days are tagged 'heavy_rain' (an extreme
    event, not a data error). Short series fall back to a robust z-score on
    raw values.
    """
    loc_df = df[df['location'] == location].copy() if location else df.copy()
    loc_df = loc_df.sort_values('timestamp')
    if location is None and len(loc_df):
        location = str(loc_df['location'].iloc[0])

    results: List[Dict[str, Any]] = []
    series_methods: Dict[str, Dict[str, Any]] = {}

    for parameter in [c for c in WEATHER_COLS if c in loc_df.columns]:
        mask = loc_df[parameter].notna()
        series_df = loc_df.loc[mask, ['timestamp', parameter]]
        values = pd.to_numeric(series_df[parameter], errors='coerce').to_numpy(dtype=float)
        timestamps = pd.to_datetime(series_df['timestamp'], utc=True, format='mixed', errors='coerce')
        valid = ~np.isnan(values)
        values = values[valid]
        timestamps = timestamps[valid]
        if len(values) < WEATHER_MIN_POINTS:
            if skip_reasons is not None:
                skip_reasons.append({
                    "location": location,
                    "parameter": parameter,
                    "reason": (
                        f"only {len(values)} points (minimum {WEATHER_MIN_POINTS})"
                    ),
                })
            continue

        ts_naive = timestamps.dt.tz_localize(None)
        days = ((ts_naive - ts_naive.min()).dt.total_seconds() / 86400).to_numpy(dtype=float)
        span = float(days.max() - days.min())
        intervals = np.diff(days)
        positive = intervals[intervals > 0]
        days_per_unit = float(np.median(positive)) if len(positive) else 1.0

        seasonal_ready = len(values) >= WEATHER_SEASONAL_MIN_SAMPLES and span >= WEATHER_SEASONAL_MIN_SPAN_DAYS
        if parameter == 'precipitation':
            # Rainfall is intermittent and only weakly seasonal; a seasonal
            # fit would smear single-day extremes across the series. Score raw
            # values so genuine heavy-rain events stand out while typical
            # rainy days stay normal.
            residuals = values
            method = 'raw_robust_zscore'
        elif seasonal_ready:
            fit = fit_seasonal_baseline(days, values, days_per_unit, anchor_mode='none')
            residuals = values - predict_seasonal_baseline(fit, days)
            method = 'seasonal_residual'
        else:
            residuals = values
            method = 'robust_zscore'

        z_scores = _robust_z(residuals)
        residual_median, residual_scale = _robust_stats(residuals)
        if method == 'seasonal_residual':
            fitted = values - residuals
        else:
            fitted = np.zeros(len(values), dtype=float)
        expected_low = fitted + residual_median - WEATHER_Z_THRESHOLD * residual_scale
        expected_high = fitted + residual_median + WEATHER_Z_THRESHOLD * residual_scale
        flagged = 0
        for index in range(len(values)):
            z = float(z_scores[index])
            is_anomaly = abs(z) > WEATHER_Z_THRESHOLD
            if is_anomaly:
                flagged += 1
            entry = {
                'timestamp': timestamps.iloc[index].to_pydatetime(),
                'location': location,
                'parameter': parameter,
                'value': float(values[index]),
                'is_anomaly': is_anomaly,
                'anomaly_score': round(z, 3),
                'detector': method,
                'threshold': WEATHER_Z_THRESHOLD,
                'baseline': round(float(fitted[index]), 3),
                'expected_low': round(float(expected_low[index]), 3),
                'expected_high': round(float(expected_high[index]), 3),
            }
            if is_anomaly:
                entry['severity'] = _z_severity(z)
                if parameter == 'precipitation':
                    entry['kind'] = 'heavy_rain' if z > 0 else 'dry_spell'
            results.append(entry)

        series_methods[parameter] = {
            'method': method,
            'points': int(len(values)),
            'flagged': flagged,
            'z_threshold': WEATHER_Z_THRESHOLD,
        }

    if scope and series_methods:
        metadata = _load_metadata()
        metadata[_model_key(location, scope)] = {
            'location': location,
            'scope': scope,
            'method': 'seasonal_residual_threshold',
            'series': series_methods,
            'trained_at': datetime.utcnow().isoformat(),
        }
        _save_metadata(metadata)

    return results


def detect_water_anomalies(
    df: pd.DataFrame,
    location: Optional[str] = None,
    scope: Optional[str] = None,
    skip_reasons: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Robust z-score anomaly detection for water-quality series.

    Scored parameters are dissolved oxygen (``do``) and the core WQI
    (``wqi`` - computed per record by the ingestion path). Series are short
    (15-48 monthly samples per station), far below the 200-point minimum for
    the seasonal baseline, so raw values are scored with the same robust
    (median/MAD) z-score used for short weather series. Flagged samples are
    tagged ``unusually_low`` (e.g. hypoxia: DO 1.2 mg/L) or ``unusually_high``
    (e.g. supersaturation: DO 15.0) so both directions read at a glance.
    """
    loc_df = df[df['location'] == location].copy() if location else df.copy()
    loc_df = loc_df.sort_values('timestamp')
    if location is None and len(loc_df):
        location = str(loc_df['location'].iloc[0])

    results: List[Dict[str, Any]] = []
    series_methods: Dict[str, Dict[str, Any]] = {}

    for parameter in [c for c in WATER_ANOMALY_COLS if c in loc_df.columns]:
        mask = loc_df[parameter].notna()
        series_df = loc_df.loc[mask, ['timestamp', parameter]]
        values = pd.to_numeric(series_df[parameter], errors='coerce').to_numpy(dtype=float)
        timestamps = pd.to_datetime(series_df['timestamp'], utc=True, format='mixed', errors='coerce')
        valid = ~np.isnan(values)
        values = values[valid]
        timestamps = timestamps[valid]
        if len(values) < WATER_MIN_POINTS:
            if skip_reasons is not None:
                skip_reasons.append({
                    "location": location,
                    "parameter": parameter,
                    "reason": (
                        f"only {len(values)} points (minimum {WATER_MIN_POINTS})"
                    ),
                })
            continue

        z_scores = _robust_z(values)
        baseline, scale = _robust_stats(values)
        expected_low = baseline - WATER_Z_THRESHOLD * scale
        expected_high = baseline + WATER_Z_THRESHOLD * scale
        flagged = 0
        for index in range(len(values)):
            z = float(z_scores[index])
            is_anomaly = abs(z) > WATER_Z_THRESHOLD
            entry = {
                'timestamp': timestamps.iloc[index].to_pydatetime(),
                'location': location,
                'parameter': parameter,
                'value': float(values[index]),
                'is_anomaly': is_anomaly,
                'anomaly_score': round(z, 3),
                'detector': 'robust_zscore',
                'threshold': WATER_Z_THRESHOLD,
                'baseline': round(float(baseline), 3),
                'expected_low': round(float(expected_low), 3),
                'expected_high': round(float(expected_high), 3),
            }
            if is_anomaly:
                flagged += 1
                entry['kind'] = 'unusually_high' if z > 0 else 'unusually_low'
                entry['severity'] = _z_severity(z)
            results.append(entry)

        series_methods[parameter] = {
            'method': 'robust_zscore',
            'points': int(len(values)),
            'flagged': flagged,
            'z_threshold': WATER_Z_THRESHOLD,
        }

    if scope and series_methods:
        metadata = _load_metadata()
        metadata[_model_key(location, scope)] = {
            'location': location,
            'scope': scope,
            'method': 'robust_zscore_threshold',
            'series': series_methods,
            'trained_at': datetime.utcnow().isoformat(),
        }
        _save_metadata(metadata)

    return results


def train_global_model(df: pd.DataFrame, contamination: float = DEFAULT_CONTAMINATION) -> IsolationForest:
    """Train a single global model (legacy fallback)."""
    features = df[POLLUTANT_COLS].dropna()
    
    if len(features) < 10:
        raise ValueError("Insufficient data for training global anomaly model")
    
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
        n_jobs=-1
    )
    model.fit(features)
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    global_path = os.path.join(MODEL_DIR, f"{ANOMALY_MODEL_PREFIX}global.joblib")
    joblib.dump(model, global_path)
    
    return model


def get_anomaly_summary(anomaly_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate summary statistics for anomalies."""
    if not anomaly_results:
        return {"total": 0, "anomalies": 0, "by_parameter": {}, "by_location": {}}
    
    df = pd.DataFrame(anomaly_results)
    total = len(df)
    anomalies = df['is_anomaly'].sum()
    
    by_param = df.groupby('parameter')['is_anomaly'].agg(['sum', 'count']).to_dict('index')
    by_loc = df.groupby('location')['is_anomaly'].agg(['sum', 'count']).to_dict('index')
    
    return {
        "total": int(total),
        "anomalies": int(anomalies),
        "anomaly_rate": round(anomalies / total * 100, 2) if total > 0 else 0,
        "by_parameter": {k: {"anomalies": int(v['sum']), "total": int(v['count'])} for k, v in by_param.items()},
        "by_location": {k: {"anomalies": int(v['sum']), "total": int(v['count'])} for k, v in by_loc.items()},
    }


def get_model_metadata() -> Dict[str, Any]:
    """Get metadata for all trained models."""
    return _load_metadata()


def retrain_if_needed(df: pd.DataFrame, location: str, max_age_hours: int = 24, scope: Optional[str] = None) -> Tuple[IsolationForest, Dict[str, Any]]:
    """Retrain model if it doesn't exist, is stale, or predates feature tracking."""
    metadata = _load_metadata()
    key = _model_key(location, scope)
    model_path = _get_model_path(location, scope)
    
    if not os.path.exists(model_path) or key not in metadata or 'feature_columns' not in metadata[key]:
        return train_anomaly_model(df, location, scope=scope)
    
    trained_at = datetime.fromisoformat(metadata[key]['trained_at'])
    age_hours = (datetime.utcnow() - trained_at).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        return train_anomaly_model(df, location, scope=scope)
    
    model = load_anomaly_model(location, scope)
    return model, metadata[key]


def purge_dataset_models(dataset_id: str) -> int:
    """Delete persisted anomaly models and metadata entries for one dataset.

    Dataset-scoped model keys always end in ``__weather_{dataset_id}``,
    ``__aqi_{dataset_id}`` or ``__water_{dataset_id}``; unscoped legacy models
    are left untouched.
    """
    scopes = (f"weather_{dataset_id}", f"aqi_{dataset_id}", f"water_{dataset_id}")
    removed = 0
    if os.path.isdir(MODEL_DIR):
        for name in os.listdir(MODEL_DIR):
            if not name.endswith('.joblib'):
                continue
            if any(name.endswith(f"__{scope}.joblib") for scope in scopes):
                os.remove(os.path.join(MODEL_DIR, name))
                removed += 1

    metadata = _load_metadata()
    stale_keys = [key for key in metadata if any(key.endswith(f"__{scope}") for scope in scopes)]
    for key in stale_keys:
        metadata.pop(key)
    if stale_keys:
        _save_metadata(metadata)
    return removed
