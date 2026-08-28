import pandas as pd
import numpy as np
from prophet import Prophet
from typing import List, Dict, Any, Optional, Tuple
import joblib
import os
import warnings
import json
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

MODEL_DIR = "models"
FORECAST_MODEL_PREFIX = "prophet_"
METADATA_FILE = os.path.join(MODEL_DIR, "forecast_metadata.json")

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']

MIN_TRAIN_SAMPLES = 30
TEST_SPLIT_RATIO = 0.2
DEFAULT_HORIZON = 7
DEFAULT_FREQ = 'D'


def _get_model_path(location: str, parameter: str) -> str:
    safe_location = location.replace(" ", "_").replace("/", "_")
    return os.path.join(MODEL_DIR, f"{FORECAST_MODEL_PREFIX}{safe_location}_{parameter}.joblib")


def _load_metadata() -> Dict[str, Any]:
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {}


def _save_metadata(metadata: Dict[str, Any]):
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)


def _prepare_relative_data(df: pd.DataFrame, location: str, parameter: str) -> Tuple[pd.DataFrame, datetime, float]:
    """
    Prepare data with relative time indexing.
    Returns (prophet_df, base_timestamp, days_per_unit)
    """
    loc_df = df[df['location'] == location].copy()
    loc_df = loc_df.sort_values('timestamp')
    
    ds_series = pd.to_datetime(loc_df['timestamp'], utc=True, format="mixed", errors="coerce")
    ds_naive = ds_series.dt.tz_localize(None)
    
    base_timestamp = ds_naive.min()
    
    # Calculate days since base
    days_since_base = (ds_naive - base_timestamp).dt.total_seconds() / (24 * 3600)
    
    prophet_df = pd.DataFrame({
        'ds': days_since_base,
        'y': loc_df[parameter]
    }).dropna()
    
    # Determine frequency - assume daily if regular, else use median interval
    if len(prophet_df) > 1:
        intervals = np.diff(prophet_df['ds'].values)
        median_interval = np.median(intervals[intervals > 0])
        days_per_unit = max(median_interval, 1.0/24.0)  # at least hourly
    else:
        days_per_unit = 1.0
    
    return prophet_df, base_timestamp, days_per_unit


def _time_series_split(df: pd.DataFrame, test_ratio: float = TEST_SPLIT_RATIO) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split data chronologically."""
    df = df.sort_values('ds').reset_index(drop=True)
    split_idx = int(len(df) * (1 - test_ratio))
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df


def train_forecast_model(
    df: pd.DataFrame, 
    location: str, 
    parameter: str,
    seasonality_mode: str = 'additive'
) -> Tuple[Prophet, Dict[str, Any]]:
    """
    Train Prophet model with relative time indexing and time-series split.
    Returns (model, evaluation_metrics).
    """
    prophet_df, base_timestamp, days_per_unit = _prepare_relative_data(df, location, parameter)
    
    if len(prophet_df) < MIN_TRAIN_SAMPLES:
        raise ValueError(f"Insufficient data for {location} - {parameter}: {len(prophet_df)} points (min {MIN_TRAIN_SAMPLES})")
    
    train_df, test_df = _time_series_split(prophet_df, TEST_SPLIT_RATIO)
    
    if len(train_df) < 10:
        raise ValueError(f"Insufficient training data for {location} - {parameter} after split")
    
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=len(prophet_df) > 365,
        seasonality_mode=seasonality_mode,
        changepoint_prior_scale=0.05,
        interval_width=0.95,
    )
    model.fit(train_df)
    
    # Evaluate on test set
    test_forecast = model.predict(test_df[['ds']])
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    mae = mean_absolute_error(test_df['y'], test_forecast['yhat'])
    rmse = np.sqrt(mean_squared_error(test_df['y'], test_forecast['yhat']))
    
    # Evaluate on train set
    train_forecast = model.predict(train_df[['ds']])
    train_mae = mean_absolute_error(train_df['y'], train_forecast['yhat'])
    train_rmse = np.sqrt(mean_squared_error(train_df['y'], train_forecast['yhat']))
    
    metrics = {
        "location": location,
        "parameter": parameter,
        "train_samples": int(len(train_df)),
        "test_samples": int(len(test_df)),
        "train_mae": round(float(train_mae), 4),
        "train_rmse": round(float(train_rmse), 4),
        "test_mae": round(float(mae), 4),
        "test_rmse": round(float(rmse), 4),
        "base_timestamp": base_timestamp.isoformat(),
        "days_per_unit": float(days_per_unit),
        "trained_at": datetime.utcnow().isoformat(),
    }
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = _get_model_path(location, parameter)
    joblib.dump((model, base_timestamp, days_per_unit), model_path)
    
    metadata = _load_metadata()
    key = f"{location}_{parameter}"
    metadata[key] = metrics
    _save_metadata(metadata)
    
    return model, metrics


def load_forecast_model(location: str, parameter: str) -> Tuple[Prophet, datetime, float]:
    """Load trained Prophet model with base timestamp and days_per_unit."""
    model_path = _get_model_path(location, parameter)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Forecast model not found for {location}_{parameter}")
    return joblib.load(model_path)


def generate_forecast(
    df: pd.DataFrame, 
    location: str, 
    parameter: str, 
    horizon: int = DEFAULT_HORIZON, 
    freq: str = DEFAULT_FREQ
) -> Dict[str, Any]:
    """
    Generate forecast for a location and parameter.
    Returns predictions with confidence intervals in real timestamps.
    """
    try:
        model, base_timestamp, days_per_unit = load_forecast_model(location, parameter)
    except FileNotFoundError:
        model, metrics = train_forecast_model(df, location, parameter)
        base_timestamp = datetime.fromisoformat(metrics['base_timestamp'])
        days_per_unit = metrics['days_per_unit']
    
    # Get last date in training data
    prophet_df, _, _ = _prepare_relative_data(df, location, parameter)
    last_ds = prophet_df['ds'].max()
    
    # Create future dataframe with relative days
    future_ds = np.arange(last_ds + days_per_unit, last_ds + (horizon + 1) * days_per_unit, days_per_unit)
    future_df = pd.DataFrame({'ds': future_ds[:horizon]})
    
    forecast = model.predict(future_df)
    
    predictions = []
    for _, row in forecast.iterrows():
        # Convert relative days back to real timestamp
        pred_timestamp = base_timestamp + timedelta(days=float(row['ds']))
        predictions.append({
            'timestamp': pred_timestamp.isoformat() + 'Z',
            'predicted_value': round(row['yhat'], 2),
            'lower_bound': round(row['yhat_lower'], 2),
            'upper_bound': round(row['yhat_upper'], 2),
        })
    
    # Get metrics from metadata or compute
    metadata = _load_metadata()
    key = f"{location}_{parameter}"
    stored_metrics = metadata.get(key, {})
    
    return {
        'location': location,
        'parameter': parameter,
        'model_used': 'Prophet',
        'forecast_horizon': horizon,
        'predictions': predictions,
        'metrics': {
            'mae': stored_metrics.get('test_mae', 0),
            'rmse': stored_metrics.get('test_rmse', 0),
            'training_samples': stored_metrics.get('train_samples', len(prophet_df)),
        }
    }


def generate_multi_location_forecast(
    df: pd.DataFrame, 
    parameters: List[str] = None, 
    horizon: int = DEFAULT_HORIZON
) -> List[Dict[str, Any]]:
    """Generate forecasts for all locations and parameters."""
    if parameters is None:
        parameters = [c for c in POLLUTANT_COLS if c in df.columns]
    
    locations = df['location'].unique()
    results = []
    
    for location in locations:
        for parameter in parameters:
            if parameter not in df.columns:
                continue
            try:
                result = generate_forecast(df, location, parameter, horizon)
                results.append(result)
            except Exception as e:
                results.append({
                    'location': location,
                    'parameter': parameter,
                    'error': str(e),
                })
    
    return results


def get_model_metadata() -> Dict[str, Any]:
    """Get metadata for all trained forecast models."""
    return _load_metadata()


def retrain_if_needed(
    df: pd.DataFrame, 
    location: str, 
    parameter: str, 
    max_age_hours: int = 24
) -> Tuple[Prophet, Dict[str, Any]]:
    """Retrain model if it doesn't exist or is older than max_age_hours."""
    metadata = _load_metadata()
    key = f"{location}_{parameter}"
    model_path = _get_model_path(location, parameter)
    
    if not os.path.exists(model_path) or key not in metadata:
        return train_forecast_model(df, location, parameter)
    
    trained_at = datetime.fromisoformat(metadata[key]['trained_at'])
    age_hours = (datetime.utcnow() - trained_at).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        return train_forecast_model(df, location, parameter)
    
    model, base_ts, days_per_unit = load_forecast_model(location, parameter)
    return model, metadata[key]