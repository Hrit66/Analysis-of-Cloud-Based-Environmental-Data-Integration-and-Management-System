import pandas as pd
import numpy as np
from prophet import Prophet
from typing import List, Dict, Any, Optional
import joblib
import os
import warnings

warnings.filterwarnings("ignore")

MODEL_DIR = "models"
FORECAST_MODEL_PREFIX = "prophet_"

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']


def prepare_prophet_data(df: pd.DataFrame, location: str, parameter: str) -> pd.DataFrame:
    """Prepare data for Prophet (requires ds, y columns)."""
    loc_df = df[df['location'] == location].copy()
    loc_df = loc_df.sort_values('timestamp')
    
    # Convert ISO 8601 UTC strings to timezone-naive datetime for Prophet
    ds_series = pd.to_datetime(loc_df['timestamp'], utc=True, format="mixed", errors="coerce")
    ds_naive = ds_series.dt.tz_localize(None)
    
    prophet_df = pd.DataFrame({
        'ds': ds_naive,
        'y': loc_df[parameter]
    }).dropna()
    
    return prophet_df


def train_forecast_model(df: pd.DataFrame, location: str, parameter: str, 
                         seasonality_mode: str = 'additive') -> Prophet:
    """Train Prophet model for a specific location and parameter."""
    prophet_df = prepare_prophet_data(df, location, parameter)
    
    if len(prophet_df) < 20:
        raise ValueError(f"Insufficient data for {location} - {parameter}: {len(prophet_df)} points")
    
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        seasonality_mode=seasonality_mode,
        changepoint_prior_scale=0.05,
    )
    model.fit(prophet_df)
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, f"{FORECAST_MODEL_PREFIX}{location}_{parameter}.joblib")
    joblib.dump(model, model_path)
    
    return model


def load_forecast_model(location: str, parameter: str) -> Prophet:
    """Load trained Prophet model."""
    model_path = os.path.join(MODEL_DIR, f"{FORECAST_MODEL_PREFIX}{location}_{parameter}.joblib")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Forecast model not found for {location}_{parameter}")
    return joblib.load(model_path)


def generate_forecast(df: pd.DataFrame, location: str, parameter: str, 
                      horizon: int = 7, freq: str = 'D') -> Dict[str, Any]:
    """
    Generate forecast for a location and parameter.
    Returns predictions with confidence intervals.
    """
    try:
        model = load_forecast_model(location, parameter)
    except FileNotFoundError:
        model = train_forecast_model(df, location, parameter)
    
    future = model.make_future_dataframe(periods=horizon, freq=freq)
    forecast = model.predict(future)
    
    predictions = []
    for _, row in forecast.tail(horizon).iterrows():
        predictions.append({
            'timestamp': row['ds'],
            'predicted_value': round(row['yhat'], 2),
            'lower_bound': round(row['yhat_lower'], 2),
            'upper_bound': round(row['yhat_upper'], 2),
        })
    
    from sklearn.metrics import mean_absolute_error, mean_squared_error
    train_predictions = model.predict(prophet_df := prepare_prophet_data(df, location, parameter))
    mae = mean_absolute_error(prophet_df['y'], train_predictions['yhat'])
    rmse = np.sqrt(mean_squared_error(prophet_df['y'], train_predictions['yhat']))
    
    return {
        'location': location,
        'parameter': parameter,
        'model_used': 'Prophet',
        'forecast_horizon': horizon,
        'predictions': predictions,
        'metrics': {
            'mae': round(mae, 2),
            'rmse': round(rmse, 2),
            'training_samples': len(prophet_df),
        }
    }


def generate_multi_location_forecast(df: pd.DataFrame, parameters: List[str] = None, 
                                      horizon: int = 7) -> List[Dict[str, Any]]:
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