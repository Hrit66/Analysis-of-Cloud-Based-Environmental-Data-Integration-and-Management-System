import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Any, Optional, Tuple
import joblib
import os
import json
from datetime import datetime


MODEL_DIR = "models"
ANOMALY_MODEL_PREFIX = "isolation_forest_"
METADATA_FILE = os.path.join(MODEL_DIR, "anomaly_metadata.json")

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']

DEFAULT_CONTAMINATION = 0.05
MIN_TRAIN_SAMPLES = 50
TEST_SPLIT_RATIO = 0.2


def _get_model_path(location: str) -> str:
    safe_location = location.replace(" ", "_").replace("/", "_")
    return os.path.join(MODEL_DIR, f"{ANOMALY_MODEL_PREFIX}{safe_location}.joblib")


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


def train_anomaly_model(
    df: pd.DataFrame, 
    location: str,
    contamination: float = DEFAULT_CONTAMINATION,
    test_ratio: float = TEST_SPLIT_RATIO
) -> Tuple[IsolationForest, Dict[str, Any]]:
    """
    Train Isolation Forest per location with time-series split.
    Returns (model, evaluation_metrics).
    """
    loc_df = df[df['location'] == location].copy()
    loc_df = loc_df.sort_values('timestamp')
    
    features = loc_df[POLLUTANT_COLS].dropna()
    
    if len(features) < MIN_TRAIN_SAMPLES:
        raise ValueError(f"Insufficient data for {location}: {len(features)} samples (min {MIN_TRAIN_SAMPLES})")
    
    train_df, test_df = _time_series_split(loc_df, test_ratio)
    train_features = train_df[POLLUTANT_COLS].dropna()
    test_features = test_df[POLLUTANT_COLS].dropna()
    
    if len(train_features) < 10:
        raise ValueError(f"Insufficient training data for {location} after split")
    
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=200,
        n_jobs=-1,
        max_samples='auto'
    )
    model.fit(train_features)
    
    # Evaluate on test set
    test_scores = model.decision_function(test_features)
    test_preds = model.predict(test_features)
    test_anomaly_rate = (test_preds == -1).mean()
    
    # Evaluate on train set (should be close to contamination)
    train_preds = model.predict(train_features)
    train_anomaly_rate = (train_preds == -1).mean()
    
    metrics = {
        "location": location,
        "train_samples": int(len(train_features)),
        "test_samples": int(len(test_features)),
        "train_anomaly_rate": round(float(train_anomaly_rate) * 100, 2),
        "test_anomaly_rate": round(float(test_anomaly_rate) * 100, 2),
        "contamination_setting": contamination,
        "score_mean": round(float(test_scores.mean()), 4),
        "score_std": round(float(test_scores.std()), 4),
        "trained_at": datetime.utcnow().isoformat(),
    }
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = _get_model_path(location)
    joblib.dump(model, model_path)
    
    # Update metadata
    metadata = _load_metadata()
    metadata[location] = metrics
    _save_metadata(metadata)
    
    return model, metrics


def load_anomaly_model(location: str) -> IsolationForest:
    """Load trained Isolation Forest model for a location."""
    model_path = _get_model_path(location)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Anomaly model not found for {location}. Train first.")
    return joblib.load(model_path)


def detect_anomalies(
    df: pd.DataFrame, 
    location: str = None,
    model: IsolationForest = None,
    contamination: float = DEFAULT_CONTAMINATION
) -> List[Dict[str, Any]]:
    """
    Detect anomalies in air quality data.
    If location specified, use/load model for that location.
    If no model provided and no location, train global model (legacy behavior).
    """
    if model is None:
        if location:
            try:
                model = load_anomaly_model(location)
            except FileNotFoundError:
                model, _ = train_anomaly_model(df, location, contamination)
        else:
            # Global model fallback (legacy)
            try:
                global_path = os.path.join(MODEL_DIR, f"{ANOMALY_MODEL_PREFIX}global.joblib")
                model = joblib.load(global_path)
            except FileNotFoundError:
                model = train_global_model(df, contamination)
    
    results = []
    
    for idx, row in df.iterrows():
        feature_vector = row[POLLUTANT_COLS].astype(float).values.reshape(1, -1)
        
        if np.any(np.isnan(feature_vector)):
            continue
        
        anomaly_score = model.decision_function(feature_vector)[0]
        is_anomaly = model.predict(feature_vector)[0] == -1
        
        for col in POLLUTANT_COLS:
            val = row[col]
            if pd.notna(val):
                results.append({
                    'timestamp': row['timestamp'],
                    'location': row['location'],
                    'parameter': col,
                    'value': float(val),
                    'is_anomaly': bool(is_anomaly),
                    'anomaly_score': float(anomaly_score),
                })
    
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


def retrain_if_needed(df: pd.DataFrame, location: str, max_age_hours: int = 24) -> Tuple[IsolationForest, Dict[str, Any]]:
    """Retrain model if it doesn't exist or is older than max_age_hours."""
    metadata = _load_metadata()
    model_path = _get_model_path(location)
    
    if not os.path.exists(model_path) or location not in metadata:
        return train_anomaly_model(df, location)
    
    trained_at = datetime.fromisoformat(metadata[location]['trained_at'])
    age_hours = (datetime.utcnow() - trained_at).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        return train_anomaly_model(df, location)
    
    model = load_anomaly_model(location)
    return model, metadata[location]