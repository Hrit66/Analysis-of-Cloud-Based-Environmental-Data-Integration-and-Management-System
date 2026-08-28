# AQI Environmental Analytics API - Backend

Production-ready FastAPI backend for environmental data processing, analytics, and visualization.

## Features

- **File Upload & Processing**: CSV/JSON/Excel upload with background processing
- **Data Cleaning**: Column normalization, missing value handling, deduplication, outlier capping
- **AQI Computation**: CPCB standard formula for 6 pollutants (PM2.5, PM10, NO2, SO2, CO, O3)
- **Anomaly Detection**: Isolation Forest with time-series train/test split per location
- **Forecasting**: Prophet with relative time indexing for historical data
- **Export**: CSV export for AQI, anomalies, forecasts, and raw data
- **Authentication**: JWT-based auth with register/login
- **Rate Limiting**: 100 req/min, 1000 req/hour per IP
- **Structured Logging**: JSON logs with request IDs
- **Pagination**: All list endpoints support limit/skip
- **Tests**: Unit tests for core services

## Quick Start

### Local Development

```bash
# Clone and navigate
cd back

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your MongoDB Atlas URI

# Run development server
make dev
# or: uvicorn app.main:app --reload
```

### Docker Compose (with local MongoDB)

```bash
# Create .env with local MongoDB URI
echo "MONGO_URI=mongodb://mongo:27017" > .env
echo "DB_NAME=aqi_db" >> .env
echo "JWT_SECRET=your-secret-key" >> .env

# Start services
make docker-up

# View logs
make docker-logs
```

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login (returns JWT)
- `GET /api/auth/me` - Get current user

### Datasets
- `POST /api/datasets/upload` - Upload CSV/JSON/Excel file
- `GET /api/datasets` - List datasets (paginated)
- `GET /api/datasets/{id}` - Get dataset details
- `GET /api/datasets/{id}/status` - Poll processing status
- `DELETE /api/datasets/{id}` - Delete dataset and associated data

### Analytics
- `GET /api/analytics/aqi/{dataset_id}` - AQI results (paginated)
- `GET /api/analytics/aqi/{dataset_id}/summary` - AQI summary per location
- `GET /api/analytics/anomalies/{dataset_id}` - Anomaly detections (paginated)
- `GET /api/analytics/anomalies/{dataset_id}/summary` - Anomaly rates
- `GET /api/analytics/forecasts/{dataset_id}` - Forecast results
- `GET /api/analytics/forecasts/{dataset_id}/latest` - Latest forecast for location/parameter
- `GET /api/analytics/trends/{dataset_id}` - Time series trends

### Export
- `GET /api/export/aqi/{dataset_id}` - Export AQI as CSV
- `GET /api/export/anomalies/{dataset_id}` - Export anomalies as CSV
- `GET /api/export/forecasts/{dataset_id}` - Export forecasts as CSV
- `GET /api/export/raw/{dataset_id}` - Export raw data as CSV

### Health
- `GET /health` - Health check with DB status
- `GET /health/ready` - Readiness check

## Frontend Integration Flow

```javascript
// 1. Upload file
const upload = await fetch('/api/datasets/upload', {
  method: 'POST',
  body: formData  // file + dataset_type
});
const { dataset_id } = await upload.json();

// 2. Poll status
let status = 'processing';
while (status === 'processing') {
  await new Promise(r => setTimeout(r, 2000));
  const res = await fetch(`/api/datasets/${dataset_id}/status`);
  status = (await res.json()).status;
}

// 3. Fetch analytics
const aqi = await fetch(`/api/analytics/aqi/${dataset_id}`).then(r => r.json());
const anomalies = await fetch(`/api/analytics/anomalies/${dataset_id}`).then(r => r.json());
const forecasts = await fetch(`/api/analytics/forecasts/${dataset_id}`).then(r => r.json());
```

## ML Pipeline Details

### Anomaly Detection
- **Algorithm**: Isolation Forest (scikit-learn)
- **Training**: Per-location, time-series split (80/20 chronological)
- **Evaluation**: Train/test anomaly rates tracked in metadata
- **Persistence**: Models saved to `models/` directory

### Forecasting
- **Algorithm**: Facebook Prophet
- **Time Handling**: Relative day indexing (handles historical dates)
- **Seasonality**: Daily + weekly (yearly if >365 days data)
- **Evaluation**: MAE/RMSE on chronological test split
- **Persistence**: Models + base timestamp saved to `models/`

### AQI Computation
- **Standard**: CPCB (India) breakpoint formula
- **Pollutants**: PM2.5, PM10, NO2, SO2, CO, O3
- **Output**: AQI value, category, dominant pollutant, sub-indices

## Project Structure

```
back/
├── app/
│   ├── api/           # FastAPI routers
│   │   ├── auth.py    # JWT authentication
│   │   ├── datasets.py # File upload & management
│   │   ├── analytics.py # AQI, anomalies, forecasts
│   │   ├── export.py  # CSV exports
│   │   └── health.py  # Health checks
│   ├── core/
│   │   ├── logging.py     # Structured JSON logging
│   │   └── rate_limit.py  # SlowAPI rate limiting
│   ├── models/        # Pydantic models
│   ├── services/      # Business logic
│   │   ├── aqi_calculator.py
│   │   ├── anomaly_detector.py
│   │   ├── forecaster.py
│   │   ├── auth.py
│   │   └── pipeline_interface.py
│   ├── database.py    # MongoDB connection
│   ├── config.py      # Pydantic settings
│   └── main.py        # FastAPI app factory
├── tests/             # Pytest unit tests
├── models/            # Trained ML models (gitignored)
├── uploads/           # Temporary upload storage (gitignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── Makefile
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGO_URI` | MongoDB connection string | Required |
| `DB_NAME` | Database name | `aqi_db` |
| `JWT_SECRET` | JWT signing secret | Required |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiry | `1440` |
| `ENVIRONMENT` | Environment mode | `development` |

## Testing

```bash
# Run all tests
make test

# Run specific test file
pytest tests/test_services.py -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

## Deployment

### Render / Railway / Fly.io
1. Connect GitHub repo
2. Set environment variables
3. Deploy with `Dockerfile`

### Docker Production
```bash
docker build -t aqi-api .
docker run -d -p 8000:8000 --env-file .env aqi-api
```

## Development Notes

- **Background jobs**: Currently uses FastAPI BackgroundTasks (not persistent)
- **For production**: Replace with Celery + Redis for job persistence
- **Model retraining**: Automatic if model >24h old (configurable)
- **CORS**: Enabled for all origins (configure for production)