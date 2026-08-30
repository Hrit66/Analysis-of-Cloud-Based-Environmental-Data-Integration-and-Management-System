# ML Model Module

> Part of the **Analysis of Cloud-Based Environmental Data Integration and Management System** project.

This directory is a **fully self-contained** ML micro-service.  
The backend team consumes it through thin HTTP wrappers — no model files, no cloud credentials, no ML libraries are needed on the backend side.

---

## Directory Structure

```
ml_model/
├── anomaly/                    IsolationForest anomaly detection
│   ├── train.py                Training pipeline
│   ├── evaluate.py             Evaluation + KS-drift + retrain trigger
│   ├── model_registry.py       Versioned .joblib + metadata JSON
│   └── config.yaml             Hyperparameters & paths
│
├── forecast/                   XGBoost time-series forecasting
│   ├── train.py                Multi-horizon direct training + walk-forward backtest
│   ├── evaluate.py             MAE/RMSE per horizon + drift detection
│   ├── model_registry.py       Versioned .joblib + metadata JSON
│   └── config.yaml
│
├── aqi_predictor/              XGBoost multi-class AQI category classifier
│   ├── train.py                Training pipeline with CPCB label derivation
│   ├── evaluate.py             F1/Precision/Recall + drift + retrain trigger
│   └── config.yaml
│
├── shared/                     Shared utilities (no external dependencies on backend)
│   ├── data_split.py           Strict chronological train/test splits
│   ├── features.py             Lag, rolling, cyclical, ratio feature engineering
│   └── metrics.py              MAE, RMSE, Precision, Recall, F1, KS-test
│
├── serving/                    Inference layer & FastAPI app
│   ├── model_loader.py         ★ Secure cloud fetch + in-memory cache
│   ├── inference.py            ★ Public inference functions (4 endpoints)
│   ├── predict_batch.py        Batch scoring helpers
│   ├── api.py                  FastAPI HTTP application
│   └── __init__.py
│
├── models/                     Local model artifact cache (.gitignored)
│   ├── anomaly/
│   ├── forecast/
│   ├── aqi_predictor/
│   └── reports/
│
├── requirements.txt
├── Dockerfile
└── README.md  (this file)
```

---

## Quick Start

### 1. Install dependencies

```bash
cd ml_model
pip install -r requirements.txt
```

### 2. Train all models (uses synthetic data if no CSV supplied)

```bash
# Anomaly detection
python -m anomaly.train

# Time-series forecasting
python -m forecast.train --target pm25

# AQI category classifier
python -m aqi_predictor.train
```

### 3. Start the inference API

```bash
uvicorn serving.api:app --host 0.0.0.0 --port 8001 --reload
```

Open **http://localhost:8001/docs** for the interactive Swagger UI.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness probe |
| POST | `/aqi` | CPCB AQI calculation (rule-based) |
| POST | `/wqi` | BIS WQI calculation (rule-based) |
| POST | `/forecast` | 24–72 h pollutant forecast (ML) |
| POST | `/anomaly` | Anomaly detection (ML) |
| POST | `/batch/aqi` | Bulk AQI computation |
| POST | `/batch/anomaly` | Bulk anomaly detection |
| POST | `/batch/aqi-category` | Bulk AQI category prediction (ML) |
| GET | `/model/info/{artifact}` | Registry metadata |
| POST | `/model/reload/{artifact}` | Force model cache eviction |

### Example – AQI

```bash
curl -X POST http://localhost:8001/aqi \
  -H "Content-Type: application/json" \
  -d '{"pollutant_readings": {"pm25": 55.0, "pm10": 100.0, "no2": 80.0}}'
```

Response:
```json
{
  "aqi": 109,
  "category": "Moderate",
  "health_message": "Breathing discomfort for people with lung/heart disease.",
  "dominant_pollutant": "pm25",
  "sub_indices": {"pm25": 109.17, "pm10": 100.0, "no2": 66.67},
  "timestamp": "2024-01-15T10:30:00+00:00"
}
```

---

## CPCB AQI Formula

The Indian CPCB (Central Pollution Control Board) AQI formula uses linear interpolation within breakpoint ranges:

```
Sub-Index_i = I_Lo + (I_Hi - I_Lo) / (C_Hi - C_Lo) × (C_p - C_Lo)
Overall AQI  = MAX(Sub-Index_1, Sub-Index_2, ..., Sub-Index_n)
```

Pollutants supported: **PM2.5, PM10, NO₂, SO₂, CO, O₃, NH₃, Pb**  
Categories: Good (0–50) → Satisfactory → Moderate → Poor → Very Poor → Severe (401–500)

---

## WQI Formula

Weighted Arithmetic Index (BIS IS:10500-2012):

```
Qi  = 100 × (Vi - Vid) / (Si - Vid)
Wi  = K / Si   where  K = 1 / Σ(1/Si)
WQI = Σ(Qi × Wi) / Σ Wi
```

Parameters: pH, Turbidity, TDS, Hardness, Chlorides, Sulfates, Nitrates,  
Fluorides, Iron, Manganese, Arsenic, DO, BOD, Total/Fecal Coliforms

---

## Cloud Storage Architecture

```
┌──────────────────────────────────────────────────┐
│               Backend Container                  │
│  (No AWS/GCS credentials, no ML libraries)       │
│                                                  │
│  POST /forecast  ──────────────────────────────► │
└──────────────────────────────────────────────────┘
                          │ HTTP
                          ▼
┌──────────────────────────────────────────────────┐
│           ml_model serving/api.py                │
│                    │                             │
│            inference.py                          │
│                    │                             │
│         model_loader.py  ◄──── env vars          │
│        ┌───────────┤                             │
│        │  In-memory │  Pre-signed URL fetch       │
│        │   Cache    │  ──► S3 / GCS              │
│        └───────────┘                             │
└──────────────────────────────────────────────────┘
```

Set `CLOUD_PROVIDER=s3` (or `gcs`) and `CLOUD_BUCKET=<your-bucket>` to enable cloud fetching.  
For zero-credential backend deployments, set `S3_PRESIGNED_URL_ANOMALY`, `S3_PRESIGNED_URL_FORECAST`, `S3_PRESIGNED_URL_AQI` to pre-signed URLs.

---

## Model Registry

Each training run produces two files per model:

```
models/anomaly/isolation_forest_v1.0.1.joblib
models/anomaly/isolation_forest_v1.0.1_meta.json
```

The metadata JSON contains hyperparameters, training dataset stats, evaluation metrics, and a timestamp — enabling full audit trail for the project viva.

---

## Evaluation & Retraining

| Model | Trigger | Metric |
|-------|---------|--------|
| Anomaly | Precision < 0.60 **or** KS-drift detected | Precision/Recall/F1 |
| Forecast | MAE > 50 µg/m³ **or** KS-drift detected | MAE/RMSE/MAPE per horizon |
| AQI Predictor | F1 < 0.70 **or** KS-drift detected | Weighted F1/Precision/Recall |

Run evaluation scripts after each new data batch:

```bash
python -m anomaly.evaluate --data new_data.csv --labels-col is_anomaly
python -m forecast.evaluate --data new_data.csv --target pm25
python -m aqi_predictor.evaluate --data new_data.csv
```

Reports are written to `models/reports/<module>/`.

---

## Docker

```bash
docker build -t ml-model:latest .
docker run -p 8001:8001 \
  -e CLOUD_PROVIDER=local \
  -v $(pwd)/models:/app/ml_model/models \
  ml-model:latest
```
