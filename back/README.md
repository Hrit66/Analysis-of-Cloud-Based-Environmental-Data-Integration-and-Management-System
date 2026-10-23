# AQI Environmental Analytics API - Backend

Production-ready FastAPI backend for environmental data processing, analytics, and visualization.

## Features

- **File Upload & Processing**: CSV/JSON/Excel upload with background processing; dedicated importers for IMD weather grids (rain/tmax/tmin merged on date) and CPCB river-year summary sheets (one river-year per row, pivoted to records)
- **Dataset Capabilities**: each dataset records which dashboards it can feed (air quality, water quality, temperature, rainfall), derived from its actual source columns; pages and analytics endpoints refuse datasets that lack the requested data
- **Data Cleaning**: Column normalization, missing value handling, deduplication, outlier capping
- **AQI Computation**: CPCB standard formula for 6 pollutants (PM2.5, PM10, NO2, SO2, CO, O3)
- **Anomaly Detection**: Isolation Forest for pollutant series; residual-based robust z-score detector for weather series (precipitation extremes labelled as events)
- **Forecasting**: Seasonal harmonic regression (trend + annual Fourier terms) with exponentially-smoothed residual level, exponential-smoothing fallback for short series; rolling-origin evaluation against naive baselines
- **Export**: CSV export for AQI, anomalies, forecasts, and raw data, plus authenticated report packages built from one shared payload (`POST /api/reports/export`, formats `xlsx` / `pdf` / `csv`): overview, per-station summary (with WQI rank and CPCB class for water), monthly aggregates, anomaly rates, outlooks and data-quality notes. Excel (xlsxwriter) and PDF (ReportLab) come from the same `build_report_data` payload the dashboards use, so numbers cannot drift; CSV is a streaming ZIP with one file per dataset plus a manifest. Selections over 50,000 rows run as background jobs with polling and a 2-hour download window; exports are limited to 10 per hour per account and scoped to the signed-in owner
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
- `POST /api/datasets/upload-imd` - Merge IMD rain/tmax/tmin files into one weather dataset
- `POST /api/datasets/upload-river-summary` - Import a CPCB river-year summary sheet (river × year rows) as water-quality records
- `GET /api/datasets` - List datasets (paginated)
- `GET /api/datasets/{id}` - Get dataset details
- `GET /api/datasets/{id}/status` - Poll processing status
- `PATCH /api/datasets/{id}` - Rename a dataset (display name)
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
- `GET /api/export/dataset/{dataset_id}` - Export any dataset (air or water) as cleaned CSV, optional location/date filters
- `POST /api/reports/preview` - Resolve datasets and return available/selected rows, station counts, date bounds and warnings (`dataset_ids`, `data_types`, `from`, `to`)
- `POST /api/reports/export` - Render `xlsx`, `pdf` or `csv` (ZIP) from the shared report payload; returns 202 + job for selections over 50,000 rows
- `GET /api/reports/jobs/{job_id}` - Background job status (`queued`, `running`, `completed`, `failed`)
- `GET /api/reports/jobs/{job_id}/download` - Download a completed background report (valid for 2 hours)

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
- **Pollutant series**: Isolation Forest (scikit-learn), per-location, time-series split (80/20 chronological); feature columns auto-selected and validated on reuse
- **Weather series**: residual-based detector — fits the seasonal baseline (harmonic regression, no forecast anchor), then flags days whose robust z-score (median/MAD, std fallback) exceeds 3σ. Precipitation is scored on raw values (single-day extremes are the signal) and labelled `heavy_rain` / `dry_spell` rather than treated as sensor errors
- **Evaluation**: Train/test anomaly rates tracked in metadata; Bengaluru daily-mean temperature flags ~0.3% of days
- **Persistence**: Models saved to `models/` directory, scoped per dataset for weather data

### Forecasting
- **Algorithm**: Seasonal harmonic regression (linear trend + annual Fourier terms, least squares) plus an exponentially-smoothed residual level so short-horizon forecasts track recent conditions instead of pure climatology; simple exponential smoothing fallback for series under ~200 points or 300 days
- **Time Handling**: Relative day indexing (handles historical dates); predictions start one interval after the last observation
- **Intervals**: 80% prediction intervals calibrated per horizon from rolling-origin errors (measured coverage ≈80%, widths widen with lead time)
- **Evaluation**: Rolling-origin (walk-forward) evaluation — refits at ~108 historical origins, scores the next 7 steps, and reports MAE alongside naive baselines (persistence, last-7-day mean) with a skill percentage. On the IMD Bengaluru series the model beats persistence on all four series (temperature 0.73°C vs 0.73°C, min 0.56 vs 0.59, max 1.12 vs 1.13, rain 3.79 vs 3.83)
- **Limitation**: daily precipitation is intermittent and near-random beyond heavy-rain events; for daily rainfall the always-dry baseline (MAE 3.09mm) still beats the model (3.79mm), so the dashboard leads with a rain-chance statement instead of daily amounts
- **Rain climatology**: built from the 30-year IMD record (1995–2024); the headline "rain chance (next 7 days)" is the share of observed years with at least one ≥1mm day in the same calendar week — an empirical, cluster-aware probability shown with its sample size (e.g. 4 of 30 years). A minimum of 10 years of history is required before the probability is published; datasets below that show the shortfall instead of a number. Even at 30 years the estimate is uncertain by roughly ±12 percentage points (95% confidence, e.g. 4 of 30 years), so it should be read as a climatological outlook, not a daily guarantee
- **Persistence**: Models + base timestamp saved to `models/`

### AQI Computation
- **Standard**: CPCB (India) breakpoint formula
- **Pollutants**: PM2.5, PM10, NO2, SO2, CO, O3
- **Output**: AQI value, category, dominant pollutant, sub-indices

### Water Quality Index (WQI)
- **Headline method**: CPCB weighted-arithmetic index scored on a FIXED CORE SET (pH, DO, BOD) so every scored sample is comparable. `WQI = sum(Qi*Wi)/sum(Wi)`, `Qi = 100*(Vi-Vid)/(Si-Vid)` (reversed for DO), `Wi = K/Si`, `K = 1/sum(1/Si)` over the 12-parameter set (`K = 0.06569927`, cancels in the ratio); sub-indices are clamped to 0..200 (capped above at 200, floored at 0 — a DO reading above its 14.6 saturation ideal scores 0, not a negative sub-index); the pH sub-index uses the ABSOLUTE deviation from the ideal 7.0 (`Qi = 100*|Vi-7.0|/1.5`, so pH 6.5 and 7.5 both score 33.33); final score floored at 0. A sample is scored only when ALL THREE core parameters are present — otherwise its index is `None` (no renormalisation of the headline series)
- **Extended index**: reported separately in the dashboard breakdown, labelled with its parameter count ("N of 12 parameters"). Scores every present parameter; requires at least 3 present including DO or BOD, otherwise `None`. Never used for the chart, average card or station rank — with different parameter sets it is not comparable across samples
- **Parameters**: core pH (8.5, ideal 7.0), DO 5 (ideal 14.6), BOD 3.0 (CPCB designated-best-use classes B/C); extended turbidity 5, TDS 500, hardness 300, chlorides 250, sulfates 200, nitrates 45 (as NO3), fluorides 1.0, iron 0.3, manganese 0.1 (BIS IS:10500-2012) — mg/L unless noted. `CORE_PARAMS = ("ph", "do", "bod")` in `app/services/wqi_calculator.py`
- **Nitrate units**: the source files report nitrate as N (columns like `no3_n`); the import converts nitrate-N to nitrate (x4.4266 = 62.004/14.007) so the BIS 45 mg/L limit — defined for nitrate as NO3 — applies to a consistent unit. Previously stored raw as-N values were migrated in the same rebuild
- **Limit sources (audited)**: BIS IS:10500-2012 acceptable values for pH (range 6.5-8.5), TDS, chlorides, sulfates, nitrates, fluorides, iron, manganese; turbidity uses the BIS **permissible** value (5 NTU; acceptable is 1 NTU, which would saturate the index on raw lake samples); hardness 300 follows IS:10500:1991 / Indian WQI parameter tables (the 2012 acceptable limit is 200 — flagged, not silently changed); DO 5 and BOD 3 are CPCB class B/C criteria; DO ideal 14.6 mg/L is the saturation constant used by CPCB WQI tables
- **Not scored but stored**: total coliform (BIS limit "not detectable" makes the ratio undefined; MPN reaches 9.2e9), ammonia and conductivity. Ammonia values are kept exactly as measured — the frequently repeated 0.40 mg/L is not converted to a below-detection value. Coliform is surfaced instead as a bacteriological flag against the CPCB class limits (Class A 50, Class B 500, Class C 5,000 MPN/100 mL)
- **Station rank** (`/wqi/{ds}/summary` with `start_date`/`end_date`): each station's window mean of **core-scored** samples is ranked against every station in the same dataset and window with at least 3 scored samples. The response carries `rank_pct` ("worse than X% of stations"), `rank_of` (ranked station count) and `rank_samples` (the sample count the rank is based on); a rank is never returned without its sample count, and stations with fewer than 3 samples are never ranked
- **CPCB best-use class** (`app/services/cpcb_classes.py`, reported separately from the WQI): designated-best-use classes A-E per IS 2296:1992 / CPCB criteria (A: coliform ≤ 50, pH 6.5-8.5, DO ≥ 6, BOD ≤ 2; B: coliform ≤ 500, pH 6.5-8.5, DO ≥ 5, BOD ≤ 3; C: coliform ≤ 5000, pH 6-9, DO ≥ 4, BOD ≤ 3; D: pH 6.5-8.5, DO ≥ 4, free ammonia ≤ 1.2; E: pH 6-8.5, conductivity ≤ 2250, SAR ≤ 26, boron ≤ 2). A sample's class is the best class whose checkable criteria are all met; missing parameters mark the result `partial` (with their names) instead of guessing. Class D is flagged `approximate` because the files store total NH3-N, not free ammonia (free ammonia is a fraction of the total, so total ≤ 1.2 proves the criterion); SAR and boron are not stored, so class E is partial. Failing every checkable criterion reads "Below E"
- **Scale (lower is better)**: 0-25 Excellent, 25-50 Good, 50-75 Poor, 75-100 Very Poor, 100+ Unsuitable (>100)
- **Reproducible examples (core set; locked by `tests/test_wqi_calculator.py`)**: pH 8.0, DO 6.4, BOD 4.0 -> Qi 66.67/85.42/133.33 -> WQI 106.56; pH 7.1, DO 5.7, BOD 5.0 -> Qi 6.67/92.71/166.67 -> WQI 115.03; pH 6.9, DO 2.0, BOD 16.0 -> WQI 143.94 (BOD sub-index capped at 200); pH 6.5, DO 6.1, BOD 4.0 -> WQI 101.50 (pH 6.5 is inside the BIS range but below the ideal and carries the same penalty as pH 7.5); pH 7.1, DO 6.2, BOD 4.0 -> WQI 96.36 — that sample (Ibbalur, 30 Dec 2020) also carries turbidity 6.6 NTU and nitrate 5.75 mg/L as NO3 (1.3 as N), so its extended index (5 of 12 parameters) is 102.40 and is shown separately. On the live dataset the core-scored Ibbalur 12-month window mean is 120.68 (13 samples; latest 115.03, window worst 143.94)
- **Data coverage**: of 3,388 cleaned samples, 3,150 carry the full core set (118 carry exactly two of the three, 120 none); the excluded samples are stored with `wqi = null`. The dashboard exposes the full method behind "About this index" and shows the core breakdown plus the extended block for the latest sample
- **Implementation**: `app/services/wqi_calculator.py` (full method in the module docstring)
- **Water outlooks** (`app/services/water_forecaster.py`): next-3-months monthly outlooks per station for three parameters — total coliform (log1p space, MPN spans several orders of magnitude), dissolved oxygen and the core WQI (both native units, mg/L and index points). Exponential-smoothing fit (annual harmonics need 200+ points; the longest stations have ~44 monthly samples), each evaluated rolling-origin against the persistence baseline at horizons 1-3 months. Published only for stations with ≥24 monthly samples of that parameter (68 stations for DO/WQI, 63 for coliform in the current dataset). On Allasandra the coliform model (MAE 2.202) does not beat persistence (2.148) at the 1-month horizon but is better at 2-3 months (2.406 vs 2.885, 2.481 vs 2.988), while the DO model wins at 1 month (0.578 vs 0.807 mg/L) and the WQI model too (13.24 vs 20.14 index points, 20% skill) — the stored note always says when persistence matches or wins. Coliform errors are reported in log1p units plus a multiplicative factor (x10.6 here); native-unit errors are reported in mg/L / index points directly. The outlooks are broad level indicators, not precise forecasts
- **Water anomalies** (`detect_water_anomalies` in `app/services/anomaly_detector.py`): robust z-score (median/MAD scale, |z| > 3) on DO and core WQI per station over its full history; series are 15-48 monthly samples, far below the 200-point minimum for the seasonal baseline, so raw values are scored. Stations with fewer than 15 samples for a parameter are skipped. Flagged samples carry a direction tag — `unusually_low` (hypoxia events: DO 0.5-1.2 mg/L) or `unusually_high` (supersaturation: DO 15.0). Observed rates in the current dataset: 2.0% of DO samples (61 of 3,113) and 7.4% of WQI samples (228 of 3,087). The WQI dashboard shows the split for the selected station in the DO / WQI anomalies card

## Project Structure

```
back/
├── app/
│   ├── api/           # FastAPI routers
│   │   ├── auth.py    # JWT authentication
│   │   ├── datasets.py # File upload & management
│   │   ├── analytics.py # AQI, anomalies, forecasts
│   │   ├── export.py  # CSV exports
│   │   ├── reports.py # Preview/export/job API
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
│   │   ├── cpcb_classes.py
│   │   ├── water_forecaster.py
│   │   ├── wqi_calculator.py
│   │   └── pipeline_interface.py
│   ├── reports/       # Shared payload + Excel/PDF/CSV renderers
│   │   ├── build.py
│   │   ├── excel.py
│   │   ├── pdf.py
│   │   └── csv_zip.py
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