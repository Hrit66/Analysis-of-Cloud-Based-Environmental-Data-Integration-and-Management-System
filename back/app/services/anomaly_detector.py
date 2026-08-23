import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from typing import List, Dict, Any
import joblib
import os


MODEL_DIR = "models"
ANOMALY_MODEL_PATH = os.path.join(MODEL_DIR, "isolation_forest_air_quality.joblib")

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']


def train_anomaly_model(df: pd.DataFrame, contamination: float = 0.05) -> IsolationForest:
    """Train Isolation Forest on pollutant columns."""
    features = df[POLLUTANT_COLS].dropna()
    
    if len(features) < 10:
        raise ValueError("Insufficient data for training anomaly model")
    
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
        n_jobs=-1
    )
    model.fit(features)
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(model, ANOMALY_MODEL_PATH)
    
    return model


def load_anomaly_model() -> IsolationForest:
    """Load trained Isolation Forest model."""
    if not os.path.exists(ANOMALY_MODEL_PATH):
        raise FileNotFoundError("Anomaly model not found. Train first.")
    return joblib.load(ANOMALY_MODEL_PATH)


def detect_anomalies(df: pd.DataFrame, model: IsolationForest = None) -> List[Dict[str, Any]]:
    """
    Detect anomalies in air quality data.
    Returns list of anomaly results per record per pollutant.
    """
    if model is None:
        try:
            model = load_anomaly_model()
        except FileNotFoundError:
            model = train_anomaly_model(df)
    
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