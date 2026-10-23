import os
import json
import math
import warnings
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

from app.services import dataset_config
from app.services.aqi_calculator import AQI_CATEGORIES, aqi_category

warnings.filterwarnings("ignore")

MODEL_DIR = "models"
FORECAST_MODEL_PREFIX = "forecast_"
METADATA_FILE = os.path.join(MODEL_DIR, "forecast_metadata.json")

POLLUTANT_COLS = ['pm25', 'pm10', 'no2', 'so2', 'co', 'o3']
WEATHER_COLS = ['temperature', 'temp_min', 'temp_max', 'precipitation']
FEATURE_POOL = POLLUTANT_COLS + WEATHER_COLS

MIN_TRAIN_SAMPLES = 10
TEST_SPLIT_RATIO = 0.2
DEFAULT_HORIZON = 7
DEFAULT_FREQ = 'D'

SEASONAL_PERIOD_DAYS = 365.25
SEASONAL_HARMONICS = 2
MIN_SEASONAL_SAMPLES = 200
MIN_SEASONAL_SPAN_DAYS = 300.0
SES_ALPHA = 0.3
Z_80 = 1.2816  # 80% prediction interval (fallback when rolling calibration is unavailable)
INTERVAL_COVERAGE = 0.8  # target coverage for empirically calibrated intervals
RAIN_DAY_THRESHOLD_MM = 1.0  # WMO-style 'rainy day' threshold for climatology
MIN_CLIMATOLOGY_YEARS = 10  # below this history the rain chance is too uncertain to publish
DAMPING = 1.0  # residual anchor decay per forecast step
ANCHOR_RESIDUALS = 7  # residuals averaged by the mean7 anchor
ANCHOR_SES_ALPHA = 0.5  # smoothing of the ses anchor
DEFAULT_ANCHOR_MODE = 'ses'
ANCHOR_MODES = ('last', 'ses', 'mean7', 'none')
ANCHOR_LABELS = {
    'last': 'last-observation',
    'ses': 'exponentially-smoothed',
    'mean7': '7-day-mean',
    'none': 'none',
}

MAX_ROLLING_ORIGINS = 108
ROLLING_START_RATIO = 0.6

AQI_PARAMETER = 'aqi'
AQI_FORECAST_MIN_DAYS = 730  # two years of daily observations
AQI_FORECAST_MIN_SPAN_DAYS = 730.0
AQI_DAMPING = 0.85  # AQI residuals decay more quickly than a flat anchor
AQI_ANCHOR_MODE = 'last'  # day 1 should stay close to persistence

HARMONIC_NOTE = "seasonal harmonic regression with {anchor} residual level"
SES_NOTE = "short series — exponential smoothing fallback (no annual seasonality fitted)"

PRECIPITATION_LIMITATION = (
    "Precipitation is intermittent; the rolling-origin MAE is dominated by dry days. "
    "Extreme rainfall days are surfaced as anomaly events, and the next-7-day rain "
    "chance built from the full observational record is the more reliable signal."
)
RAINFALL_DRY_BASELINE_WINS = (
    "Daily rainfall is intermittent: the always-dry baseline (MAE {zero}mm) beats this "
    "model (MAE {model}mm) at the 7-day horizon. Treat daily values as indicative only; "
    "the next-7-day rain chance built from the full observational record is the more "
    "reliable signal."
)

USE_PROPHET = False  # Prophet disabled due to version compatibility issues


def _model_key(location: str, parameter: str, dataset_id: Optional[str] = None) -> str:
    if dataset_id:
        return f"{dataset_id}_{location}_{parameter}"
    return f"{location}_{parameter}"


def _get_model_path(location: str, parameter: str, dataset_id: Optional[str] = None) -> str:
    parts = [FORECAST_MODEL_PREFIX]
    if dataset_id:
        parts.append(f"{dataset_id}_")
    parts.append(str(location).replace(" ", "_").replace("/", "_"))
    parts.append(f"_{parameter}.joblib")
    return os.path.join(MODEL_DIR, "".join(parts))


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
    Returns (series_df, base_timestamp, days_per_unit)
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


def _design_matrix(days: np.ndarray, harmonics: int = SEASONAL_HARMONICS, period: float = SEASONAL_PERIOD_DAYS) -> np.ndarray:
    """Trend + annual Fourier terms: [1, t, sin(2πkt/P), cos(2πkt/P), ...]."""
    columns = [np.ones_like(days), days]
    for k in range(1, harmonics + 1):
        angle = 2.0 * np.pi * k * days / period
        columns.append(np.sin(angle))
        columns.append(np.cos(angle))
    return np.column_stack(columns)


def _compute_anchor(residuals: np.ndarray, anchor_mode: str) -> float:
    """Level shift carried into the forecast from the most recent residuals."""
    if anchor_mode == 'none' or len(residuals) == 0:
        return 0.0
    if anchor_mode == 'last':
        return float(residuals[-1])
    if anchor_mode == 'ses':
        level = float(residuals[0])
        for residual in residuals[1:]:
            level = ANCHOR_SES_ALPHA * float(residual) + (1 - ANCHOR_SES_ALPHA) * level
        return level
    recent = residuals[-ANCHOR_RESIDUALS:] if len(residuals) > ANCHOR_RESIDUALS else residuals
    return float(np.mean(recent))


def _fit_harmonic(
    days: np.ndarray,
    values: np.ndarray,
    days_per_unit: float = 1.0,
    anchor_mode: Optional[str] = None,
    damping: Optional[float] = None,
) -> Dict[str, Any]:
    """Least-squares fit of a linear trend plus annual seasonality, with an
    anchor on the most recent residuals so short-horizon forecasts follow
    recent conditions (pure climatology loses to persistence at h=1)."""
    matrix = _design_matrix(days)
    coefficients, *_ = np.linalg.lstsq(matrix, values, rcond=None)
    residuals = values - matrix @ coefficients
    mode = anchor_mode if anchor_mode in ANCHOR_MODES else DEFAULT_ANCHOR_MODE
    return {
        'model_type': 'HarmonicRegression',
        'coefficients': coefficients.tolist(),
        'alpha': None,
        'residual_std': float(np.std(residuals)),
        'anchor': _compute_anchor(residuals, mode),
        'anchor_mode': mode,
        'anchor_day': float(days[-1]) if len(days) else 0.0,
        'days_per_unit': float(days_per_unit) or 1.0,
        'damping': float(damping) if damping is not None else DAMPING,
    }


def _fit_ses(values: np.ndarray) -> Dict[str, Any]:
    """Simple exponential smoothing with one-step error scale."""
    alpha = SES_ALPHA
    smoothed = [float(values[0])]
    for value in values[1:]:
        smoothed.append(alpha * float(value) + (1 - alpha) * smoothed[-1])
    one_step_errors = np.array([float(values[i]) - smoothed[i - 1] for i in range(1, len(values))])
    residual_std = float(np.std(one_step_errors)) if len(one_step_errors) else 0.0
    return {
        'model_type': 'SimpleExponentialSmoothing',
        'coefficients': None,
        'alpha': alpha,
        'residual_std': residual_std,
        'last_value': smoothed[-1],
    }


def _fit_series(
    days: np.ndarray,
    values: np.ndarray,
    days_per_unit: float = 1.0,
    anchor_mode: Optional[str] = None,
    damping: Optional[float] = None,
) -> Dict[str, Any]:
    """Fit the best available model: seasonal harmonic regression when the
    series spans enough time for annual seasonality, otherwise SES."""
    span = float(days.max() - days.min()) if len(days) else 0.0
    if len(values) >= MIN_SEASONAL_SAMPLES and span >= MIN_SEASONAL_SPAN_DAYS:
        return _fit_harmonic(days, values, days_per_unit, anchor_mode, damping)
    return _fit_ses(values)


def _predict(fit: Dict[str, Any], days: np.ndarray) -> np.ndarray:
    days = np.asarray(days, dtype=float)
    if fit['model_type'] == 'HarmonicRegression':
        matrix = _design_matrix(days)
        values = matrix @ np.asarray(fit['coefficients'], dtype=float)
        anchor = fit.get('anchor')
        if anchor:
            step_days = float(fit.get('days_per_unit') or 1.0)
            damping = float(fit.get('damping', DAMPING))
            steps_ahead = (days - float(fit.get('anchor_day', days.min()))) / step_days
            values = values + float(anchor) * np.power(damping, np.clip(steps_ahead, 0.0, None))
        return values
    return np.full(len(days), float(fit['last_value']), dtype=float)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def aqi_category_chances(value: float, half_width: float) -> Dict[str, float]:
    """CPCB category probabilities implied by the calibrated 80% interval.

    The interval width is converted to a normal scale (half width / z80), then
    integrated over the category boundaries. AQI is an integer index, so the
    boundaries sit at 50.5, 100.5, ... to avoid splitting a reported category.
    """
    value = float(value)
    half_width = max(0.0, float(half_width or 0.0))
    sigma = half_width / Z_80 if half_width > 0 else 0.0
    chances: Dict[str, float] = {}
    previous_high = None
    for index, (_, high, label) in enumerate(AQI_CATEGORIES):
        lower_edge = float('-inf') if previous_high is None else previous_high + 0.5
        upper_edge = float('inf') if index == len(AQI_CATEGORIES) - 1 else high + 0.5
        if sigma == 0:
            probability = 1.0 if aqi_category(value) == label else 0.0
        else:
            probability = (
                _normal_cdf((upper_edge - value) / sigma)
                - _normal_cdf((lower_edge - value) / sigma)
            )
        percentage = round(probability * 100.0, 1)
        if percentage > 0:
            chances[label] = percentage
        previous_high = high
    if not chances:
        chances[aqi_category(value)] = 100.0
    else:
        # Rounding individual bands can leave the display at 99.9 or 100.1.
        # Put the residual on the most likely band so the chips always total 100.
        residual = round(100.0 - sum(chances.values()), 1)
        if residual:
            largest = max(chances, key=chances.get)
            chances[largest] = round(chances[largest] + residual, 1)
    return chances


def fit_seasonal_baseline(
    days: np.ndarray,
    values: np.ndarray,
    days_per_unit: float = 1.0,
    anchor_mode: Optional[str] = None,
    damping: Optional[float] = None,
) -> Dict[str, Any]:
    """Public helper: fit the seasonal baseline used by forecasting and by
    residual-based anomaly detection."""
    return _fit_series(
        np.asarray(days, dtype=float),
        np.asarray(values, dtype=float),
        days_per_unit,
        anchor_mode,
        damping,
    )


def predict_seasonal_baseline(fit: Dict[str, Any], days: np.ndarray) -> np.ndarray:
    """Public helper: evaluate a fitted seasonal baseline at given day offsets."""
    return _predict(fit, days)


def _rolling_origin_metrics(
    days: np.ndarray,
    values: np.ndarray,
    days_per_unit: float,
    horizon: int = DEFAULT_HORIZON,
    max_origins: int = MAX_ROLLING_ORIGINS,
    start_ratio: float = ROLLING_START_RATIO,
    anchor_mode: Optional[str] = None,
    damping: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Rolling-origin (walk-forward) evaluation of the production algorithm
    against naive baselines. Refits the model at each origin and scores the
    next `horizon` steps, so the reported error reflects real forecast skill
    instead of one noisy holdout window."""
    n = len(values)
    start = max(int(n * start_ratio), MIN_TRAIN_SAMPLES)
    available = n - horizon - start
    if available <= 0:
        return None
    count = min(max_origins, available)
    step = max(1, available // count)
    origins = list(range(start, n - horizon, step))[:count]
    if not origins:
        return None

    model_errors, persistence_errors, last7_errors = [], [], []
    signed_by_horizon: List[List[float]] = [[] for _ in range(horizon)]
    persistence_by_horizon: List[List[float]] = [[] for _ in range(horizon)]
    last7_by_horizon: List[List[float]] = [[] for _ in range(horizon)]
    zero_errors: List[float] = []
    for origin in origins:
        train_days = days[:origin + 1]
        train_values = values[:origin + 1]
        future_days = days[origin + 1:origin + 1 + horizon]
        actual = values[origin + 1:origin + 1 + horizon]
        if len(actual) == 0:
            continue
        fit = _fit_series(train_days, train_values, days_per_unit, anchor_mode, damping)
        predicted = _predict(fit, future_days)
        model_errors.extend(np.abs(predicted - actual))
        persistence_errors.extend(np.abs(np.full(len(actual), train_values[-1]) - actual))
        recent = train_values[-min(7, len(train_values)):]
        last7_level = float(np.mean(recent))
        last7_errors.extend(np.abs(np.full(len(actual), last7_level) - actual))
        zero_errors.extend(np.abs(actual))
        for step_index, (prediction, truth) in enumerate(zip(predicted, actual)):
            signed_by_horizon[step_index].append(float(prediction) - float(truth))
            persistence_by_horizon[step_index].append(float(train_values[-1]) - float(truth))
            last7_by_horizon[step_index].append(last7_level - float(truth))

    if not model_errors:
        return None

    model_errors = np.asarray(model_errors)
    persistence_mae = float(np.mean(persistence_errors))
    last7_mae = float(np.mean(last7_errors))

    horizon_mae = [float(np.mean(np.abs(errors))) for errors in signed_by_horizon if errors]
    horizon_persistence_mae = [float(np.mean(np.abs(errors))) for errors in persistence_by_horizon if errors]
    horizon_last7_mean_mae = [float(np.mean(np.abs(errors))) for errors in last7_by_horizon if errors]
    interval_half_widths = [
        float(np.quantile(np.abs(errors), INTERVAL_COVERAGE)) for errors in signed_by_horizon if errors
    ]
    covered = sum(
        1
        for errors, half_width in zip(signed_by_horizon, interval_half_widths)
        for error in errors
        if abs(error) <= half_width
    )
    total = sum(len(errors) for errors in signed_by_horizon)

    return {
        'mae': float(np.mean(model_errors)),
        'rmse': float(np.sqrt(np.mean(np.square(model_errors)))),
        'persistence_mae': persistence_mae,
        'last7_mean_mae': last7_mae,
        'zero_baseline_mae': float(np.mean(zero_errors)),
        'origins': len(origins),
        'test_samples': int(len(model_errors)),
        'evaluation': f"rolling-origin ({len(origins)} origins, {horizon}-step horizon)",
        'horizon_mae': horizon_mae,
        'horizon_persistence_mae': horizon_persistence_mae,
        'horizon_last7_mean_mae': horizon_last7_mean_mae,
        'interval_half_widths': interval_half_widths,
        'interval_coverage_pct': round(covered / total * 100, 1) if total else None,
    }


def rolling_origin_metrics(
    days: np.ndarray,
    values: np.ndarray,
    days_per_unit: float,
    horizon: int = DEFAULT_HORIZON,
    max_origins: int = MAX_ROLLING_ORIGINS,
    start_ratio: float = ROLLING_START_RATIO,
    anchor_mode: Optional[str] = None,
    damping: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Public helper: walk-forward evaluation of the production algorithm
    against naive baselines, shared by the air/weather forecasting path and
    the water-quality coliform outlook."""
    return _rolling_origin_metrics(
        days, values, days_per_unit, horizon, max_origins, start_ratio, anchor_mode, damping
    )


def _rain_climatology(
    base_timestamp: datetime,
    days: np.ndarray,
    values: np.ndarray,
    window_days: int = DEFAULT_HORIZON,
) -> Dict[str, Any]:
    """Empirical rain climatology from the full observation record.

    Headline metric: ``week_probability`` is the fraction of observed years in
    which at least one day of the same 7-day calendar window (the window that
    follows the last observation) reached RAIN_DAY_THRESHOLD_MM. This is the
    "chance of rain in the next 7 days" definition shown to users; unlike a
    per-day probability it captures the clustering of wet spells.
    """
    days = np.asarray(days, dtype=float)
    values = np.asarray(values, dtype=float)
    date_index = pd.Timestamp(base_timestamp).normalize() + pd.to_timedelta(days, unit='D')
    series = pd.Series(values, index=pd.DatetimeIndex(date_index)).dropna().sort_index()
    if series.empty:
        return {}

    last_date = series.index.max()
    window_dates = [last_date + pd.Timedelta(days=k) for k in range(1, window_days + 1)]
    years = sorted(set(series.index.year))

    wet_years = 0
    totals: List[float] = []
    for year in years:
        window_values: List[float] = []
        for target in window_dates:
            try:
                actual = target.replace(year=year)
            except ValueError:
                actual = target.replace(year=year, day=28)
            value = series.get(actual)
            if value is not None and not pd.isna(value):
                window_values.append(float(value))
        if not window_values:
            continue
        totals.append(sum(window_values))
        if any(value >= RAIN_DAY_THRESHOLD_MM for value in window_values):
            wet_years += 1

    n_years = len(totals)
    frame = pd.DataFrame({
        'month': series.index.month,
        'year': series.index.year,
        'value': series.values,
    })
    rainy = frame['value'] >= RAIN_DAY_THRESHOLD_MM
    frame['wet'] = rainy.to_numpy(dtype=float)
    month_daily_probability: List[Optional[float]] = []
    monthly: List[Dict[str, Any]] = []
    for month in range(1, 13):
        mask = frame['month'] == month
        values_for_month = frame.loc[mask, 'value']
        probability = float(rainy[mask].mean()) if mask.any() else None
        month_daily_probability.append(
            round(probability, 3) if probability is not None else None
        )
        monthly.append({
            'month': month,
            'rain_probability': round(probability, 4) if probability is not None else None,
            'rain_probability_pct': round(probability * 100) if probability is not None else None,
            'mean_precip_mm': (
                round(float(values_for_month.mean()), 2)
                if not values_for_month.empty else None
            ),
            'wet_days': int(rainy[mask].sum()) if mask.any() else 0,
            'days': int(mask.sum()),
        })

    # Proper probability score: leave-one-year-out monthly wet-day frequency.
    # Using the target year's own outcomes would make the score optimistic, so
    # each observation is scored with the same month's frequency from other
    # years. The reference is the constant overall wet-day rate.
    month_year = frame.groupby(['month', 'year'])['wet'].agg(['sum', 'count'])
    month_totals = frame.groupby('month')['wet'].agg(['sum', 'count'])
    base_rate = float(frame['wet'].mean()) if len(frame) else 0.0
    brier_model: List[float] = []
    brier_reference: List[float] = []
    for row in frame.itertuples(index=False):
        own = month_year.loc[(row.month, row.year)]
        other_count = float(month_totals.loc[row.month, 'count'] - own['count'])
        other_wet = float(month_totals.loc[row.month, 'sum'] - own['sum'])
        probability = other_wet / other_count if other_count > 0 else base_rate
        brier_model.append((probability - row.wet) ** 2)
        brier_reference.append((base_rate - row.wet) ** 2)
    brier_score = float(np.mean(brier_model)) if brier_model else None
    brier_ref = float(np.mean(brier_reference)) if brier_reference else None
    brier_skill = (
        1.0 - brier_score / brier_ref
        if brier_score is not None and brier_ref not in (None, 0.0) else None
    )

    return {
        'threshold_mm': RAIN_DAY_THRESHOLD_MM,
        'window_days': window_days,
        'years_observed': n_years,
        'wet_years': wet_years,
        'week_probability': round(wet_years / n_years, 4) if n_years else None,
        'mean_week_total_mm': round(float(np.mean(totals)), 1) if totals else None,
        'window_start': window_dates[0].date().isoformat(),
        'window_end': window_dates[-1].date().isoformat(),
        'month_daily_probability': month_daily_probability,
        'monthly': monthly,
        'brier_score': round(brier_score, 4) if brier_score is not None else None,
        'brier_reference': round(brier_ref, 4) if brier_ref is not None else None,
        'brier_skill_score': round(brier_skill, 4) if brier_skill is not None else None,
        'brier_samples': int(len(brier_model)),
    }


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    margin = (
        z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _rain_outlook_payload(
    climatology: Dict[str, Any],
    last_date: datetime,
    horizon: int = DEFAULT_HORIZON,
    model_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Probability-only rain outlook built from the observational record."""
    month_probabilities = climatology.get('month_daily_probability') or []
    daily: List[Dict[str, Any]] = []
    for offset in range(1, horizon + 1):
        date = last_date + timedelta(days=offset)
        probability = (
            month_probabilities[date.month - 1]
            if date.month - 1 < len(month_probabilities) else None
        )
        daily.append({
            'date': date.date().isoformat(),
            'rain_probability_pct': (
                round(probability * 100) if probability is not None else None
            ),
        })

    years_observed = int(climatology.get('years_observed') or 0)
    wet_years = int(climatology.get('wet_years') or 0)
    week_probability = climatology.get('week_probability')
    week_publishable = years_observed >= MIN_CLIMATOLOGY_YEARS
    ci_low, ci_high = _wilson_interval(wet_years, years_observed)

    model = None
    if model_metrics:
        mae = model_metrics.get('mae')
        if mae is None:
            mae = model_metrics.get('test_mae')
        zero_mae = model_metrics.get('baseline_zero_mae')
        if mae is not None and zero_mae is not None:
            beats = float(mae) <= float(zero_mae)
            model = {
                'mae': round(float(mae), 2),
                'zero_baseline_mae': round(float(zero_mae), 2),
                'beats_zero_baseline': beats,
                'suppressed': not beats,
                'reason': (
                    None if beats else
                    f"MAE {float(mae):.2f} mm did not beat the always-dry "
                    f"baseline MAE {float(zero_mae):.2f} mm."
                ),
            }

    note = (
        f"Rain probabilities are observed wet-day frequencies from "
        f"{years_observed} years of history (≥{RAIN_DAY_THRESHOLD_MM:g} mm/day). "
        "No daily millimetre forecast is shown."
    )
    if week_probability is not None and years_observed:
        note += (
            f" The 7-day figure is {int(climatology.get('wet_years') or 0)} of "
            f"{years_observed} years; with this sample size the chance is "
            "correspondingly uncertain."
        )
    if climatology.get('brier_score') is not None:
        note += (
            f" Probability skill is measured with a leave-one-year-out Brier "
            f"score of {climatology['brier_score']:.3f} vs "
            f"{climatology['brier_reference']:.3f} for the constant base rate."
        )
    if model and model['suppressed']:
        note = f"{note} {model['reason']}"

    return {
        'threshold_mm': RAIN_DAY_THRESHOLD_MM,
        'window_days': int(climatology.get('window_days') or horizon),
        'years_observed': years_observed,
        'wet_years': int(climatology.get('wet_years') or 0),
        'min_years': MIN_CLIMATOLOGY_YEARS,
        'week_probability_pct': (
            round(week_probability * 100)
            if week_publishable and week_probability is not None else None
        ),
        'week_probability_estimate_pct': (
            round(week_probability * 100) if week_probability is not None else None
        ),
        'week_probability_publishable': week_publishable,
        'week_probability_ci_low_pct': (
            round(ci_low * 100) if ci_low is not None else None
        ),
        'week_probability_ci_high_pct': (
            round(ci_high * 100) if ci_high is not None else None
        ),
        'window_start': climatology.get('window_start'),
        'window_end': climatology.get('window_end'),
        'daily': daily,
        'monthly': climatology.get('monthly') or [],
        'brier_score': climatology.get('brier_score'),
        'brier_reference': climatology.get('brier_reference'),
        'brier_skill_score_pct': (
            round(climatology['brier_skill_score'] * 100, 1)
            if climatology.get('brier_skill_score') is not None else None
        ),
        'brier_samples': climatology.get('brier_samples'),
        'model': model,
        'probability_only': True,
        'note': note,
    }


def rain_outlook_from_frame(
    df: pd.DataFrame,
    location: str,
    horizon: int = DEFAULT_HORIZON,
    model_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the rainfall dashboard outlook from observed daily totals."""
    prophet_df, base_timestamp, _ = _prepare_relative_data(df, location, 'precipitation')
    if prophet_df.empty:
        return {
            'threshold_mm': RAIN_DAY_THRESHOLD_MM,
            'daily': [],
            'monthly': [],
            'model': None,
            'probability_only': True,
            'note': 'No usable precipitation observations for this station.',
        }
    climatology = _rain_climatology(
        base_timestamp,
        prophet_df['ds'].to_numpy(dtype=float),
        prophet_df['y'].to_numpy(dtype=float),
        window_days=horizon,
    )
    last_date = base_timestamp + timedelta(days=float(prophet_df['ds'].max()))
    return _rain_outlook_payload(climatology, last_date, horizon, model_metrics)


def train_forecast_model(
    df: pd.DataFrame, 
    location: str, 
    parameter: str,
    seasonality_mode: str = 'additive',
    dataset_id: Optional[str] = None
) -> Tuple[Dict, Dict[str, Any]]:
    """
    Train a time-series model for one location/parameter pair and persist it.

    Skill metrics come from a rolling-origin (walk-forward) evaluation that
    refits the model at many historical origins and scores the next
    DEFAULT_HORIZON steps, reported alongside naive baselines so the forecast
    can be checked against "repeat yesterday". Returns (model_dict, metrics).
    """
    prophet_df, base_timestamp, days_per_unit = _prepare_relative_data(df, location, parameter)

    full_days = prophet_df['ds'].to_numpy(dtype=float)
    if len(prophet_df) < MIN_TRAIN_SAMPLES:
        raise ValueError(f"Insufficient data for {location} - {parameter}: {len(prophet_df)} points (min {MIN_TRAIN_SAMPLES})")

    ml_type = (
        "rainfall" if parameter == "precipitation"
        else "temperature" if parameter in ("temperature", "temp_min", "temp_max")
        else "air_quality"
    )
    span_days = float(full_days.max() - full_days.min()) if len(full_days) else 0.0
    step_days = max(float(days_per_unit or 1.0), 1e-6)
    expected_points = span_days / step_days + 1.0
    calendar_missing = (
        max(0.0, 1.0 - len(full_days) / expected_points) if expected_points > 0 else 0.0
    )
    raw_count = int((df['location'] == location).sum()) if 'location' in df.columns else 0
    coverage_missing = (
        max(0.0, 1.0 - len(full_days) / raw_count) if raw_count else 0.0
    )
    missing_share = max(calendar_missing, coverage_missing)
    eligible, reason = dataset_config.check_ml_eligibility(
        ml_type, len(full_days), span_days, missing_share
    )
    if not eligible:
        raise ValueError(
            f"Insufficient data for {location} - {parameter}: {reason}"
        )

    full_values = prophet_df['y'].to_numpy(dtype=float)
    if parameter == AQI_PARAMETER:
        if len(full_values) < AQI_FORECAST_MIN_DAYS:
            raise ValueError(
                f"Insufficient data for {location} - {parameter}: "
                f"{len(full_values)} daily points (AQI forecasts need at least "
                f"{AQI_FORECAST_MIN_DAYS} days / 2 years)"
            )
        if span_days < AQI_FORECAST_MIN_SPAN_DAYS:
            raise ValueError(
                f"Insufficient data for {location} - {parameter}: span "
                f"{span_days:.0f} days (AQI forecasts need at least "
                f"{AQI_FORECAST_MIN_SPAN_DAYS:.0f} days / 2 years)"
            )

    fit_damping = AQI_DAMPING if parameter == AQI_PARAMETER else None
    fit_anchor_mode = AQI_ANCHOR_MODE if parameter == AQI_PARAMETER else None
    full_fit = _fit_series(
        full_days, full_values, days_per_unit,
        anchor_mode=fit_anchor_mode, damping=fit_damping,
    )
    
    train_predictions = _predict(full_fit, full_days)
    train_mae = float(np.mean(np.abs(train_predictions - full_values)))
    train_rmse = float(np.sqrt(np.mean((train_predictions - full_values) ** 2)))
    
    rolling = _rolling_origin_metrics(
        full_days, full_values, days_per_unit, DEFAULT_HORIZON,
        anchor_mode=fit_anchor_mode, damping=fit_damping,
    )
    if rolling is None:
        rolling = {
            'mae': train_mae,
            'rmse': train_rmse,
            'persistence_mae': None,
            'last7_mean_mae': None,
            'origins': 0,
            'test_samples': int(len(full_values)),
            'evaluation': 'in-sample (series too short for rolling-origin evaluation)',
        }
    
    skill = None
    persistence_mae = rolling.get('persistence_mae')
    last7_mae = rolling.get('last7_mean_mae')
    if persistence_mae:
        skill = round((1 - rolling['mae'] / persistence_mae) * 100, 1)
    skill_last7 = (
        round((1 - rolling['mae'] / last7_mae) * 100, 1)
        if last7_mae else None
    )
    better_baseline = min(
        (value for value in (persistence_mae, last7_mae) if value is not None),
        default=None,
    )
    skill_better = (
        round((1 - rolling['mae'] / better_baseline) * 100, 1)
        if better_baseline else None
    )
    beats_persistence = bool(
        persistence_mae is not None and rolling['mae'] < persistence_mae
    )
    beats_last7 = bool(last7_mae is not None and rolling['mae'] < last7_mae)
    aqi_suppressed = parameter == AQI_PARAMETER and not (
        beats_persistence and beats_last7
    )
    loses_to_persistence = bool(
        parameter != AQI_PARAMETER
        and len(full_values) >= MIN_SEASONAL_SAMPLES
        and persistence_mae is not None
        and rolling['mae'] > persistence_mae
    )
    if parameter == AQI_PARAMETER:
        if aqi_suppressed:
            selection_reason = (
                f"AQI forecast hidden: model MAE {rolling['mae']:.3f} did not "
                f"beat both persistence MAE {persistence_mae:.3f} and 7-day "
                f"mean MAE {last7_mae:.3f} over rolling origins."
            )
        else:
            selection_reason = (
                f"AQI model MAE {rolling['mae']:.3f} beat both persistence "
                f"MAE {persistence_mae:.3f} and 7-day mean MAE "
                f"{last7_mae:.3f} over rolling origins; publishing the "
                "modelled-AQI forecast."
            )
    elif loses_to_persistence:
        selection_reason = (
            f"model MAE {rolling['mae']:.3f} was worse than persistence MAE "
            f"{persistence_mae:.3f} at the {DEFAULT_HORIZON}-day horizon; "
            "publishing the persistence baseline instead of claiming skill."
        )
    elif persistence_mae is not None:
        selection_reason = (
            f"model MAE {rolling['mae']:.3f} beat persistence MAE "
            f"{persistence_mae:.3f} at the {DEFAULT_HORIZON}-day horizon."
        )
    else:
        selection_reason = (
            "series too short for rolling-origin evaluation; no skill over "
            "persistence is claimed."
        )
    skill_claimed = bool(
        skill is not None and skill > 0 and not loses_to_persistence and not aqi_suppressed
    )
    
    if full_fit['model_type'] == 'HarmonicRegression':
        anchor_label = ANCHOR_LABELS.get(full_fit.get('anchor_mode') or DEFAULT_ANCHOR_MODE, DEFAULT_ANCHOR_MODE)
        model_note = HARMONIC_NOTE.format(anchor=anchor_label, damping=full_fit.get('damping', DAMPING))
    else:
        model_note = SES_NOTE
    
    rain_climatology = None
    if parameter == 'precipitation':
        rain_climatology = _rain_climatology(base_timestamp, full_days, full_values)
    
    metrics = {
        "location": location,
        "parameter": parameter,
        "dataset_id": dataset_id,
        "train_samples": int(len(prophet_df)),
        "test_samples": int(rolling['test_samples']),
        "train_mae": round(train_mae, 2),
        "train_rmse": round(train_rmse, 2),
        "test_mae": round(rolling['mae'], 2),
        "test_rmse": round(rolling['rmse'], 2),
        "baseline_persistence_mae": round(rolling['persistence_mae'], 2) if rolling['persistence_mae'] is not None else None,
        "baseline_last7_mean_mae": round(rolling['last7_mean_mae'], 2) if rolling['last7_mean_mae'] is not None else None,
        "baseline_zero_mae": round(rolling['zero_baseline_mae'], 2) if rolling.get('zero_baseline_mae') is not None else None,
        "skill_vs_persistence_pct": 0.0 if (loses_to_persistence or aqi_suppressed) else skill,
        "candidate_skill_vs_persistence_pct": skill,
        "candidate_skill_vs_last7_mean_pct": skill_last7,
        "skill_vs_last7_mean_pct": 0.0 if aqi_suppressed else skill_last7,
        "skill_vs_better_baseline_pct": 0.0 if (loses_to_persistence or aqi_suppressed) else skill_better,
        "skill_claimed": skill_claimed,
        "forecast_published": not aqi_suppressed,
        "forecast_suppression_reason": selection_reason if aqi_suppressed else None,
        "minimum_history_days": AQI_FORECAST_MIN_DAYS if parameter == AQI_PARAMETER else None,
        "selection_reason": selection_reason,
        "series_eligibility": "eligible",
        "horizon_mae": [round(value, 2) for value in rolling.get('horizon_mae', [])],
        "horizon_persistence_mae": [round(value, 2) for value in rolling.get('horizon_persistence_mae', [])],
        "horizon_last7_mean_mae": [round(value, 2) for value in rolling.get('horizon_last7_mean_mae', [])],
        "interval_coverage_pct": rolling.get('interval_coverage_pct'),
        "rolling_origins": rolling['origins'],
        "rolling_horizon": DEFAULT_HORIZON,
        "evaluation": rolling['evaluation'],
        "model_note": model_note,
        "anchor_mode": full_fit.get('anchor_mode'),
        "anchor_damping": full_fit.get('damping'),
        "base_timestamp": base_timestamp.isoformat(),
        "days_per_unit": float(days_per_unit),
        "trained_at": datetime.utcnow().isoformat(),
        "model_type": full_fit['model_type'],
        "residual_std": round(full_fit['residual_std'], 3),
    }
    if parameter == 'precipitation':
        zero_mae = rolling.get('zero_baseline_mae')
        if zero_mae is not None and rolling['mae'] > zero_mae:
            metrics['limitation'] = RAINFALL_DRY_BASELINE_WINS.format(
                zero=round(zero_mae, 2), model=round(rolling['mae'], 2)
            )
        else:
            metrics['limitation'] = PRECIPITATION_LIMITATION
        if rain_climatology:
            metrics.update({
                'rain_brier_score': rain_climatology.get('brier_score'),
                'rain_brier_reference': rain_climatology.get('brier_reference'),
                'rain_brier_skill_score_pct': (
                    round(rain_climatology['brier_skill_score'] * 100, 1)
                    if rain_climatology.get('brier_skill_score') is not None else None
                ),
                'rain_brier_samples': rain_climatology.get('brier_samples'),
            })
    
    model_dict = {
        "model_type": full_fit['model_type'],
        "base_timestamp": base_timestamp.isoformat(),
        "days_per_unit": float(days_per_unit),
        "last_value": float(full_values[-1]),
        "alpha": full_fit.get('alpha'),
        "coefficients": full_fit.get('coefficients'),
        "anchor": full_fit.get('anchor'),
        "anchor_mode": full_fit.get('anchor_mode'),
        "anchor_day": full_fit.get('anchor_day'),
        "damping": full_fit.get('damping'),
        "residual_std": float(full_fit['residual_std']),
        "interval_half_widths": rolling.get('interval_half_widths'),
        "rain_climatology": rain_climatology,
        "seasonal_period_days": SEASONAL_PERIOD_DAYS,
        "harmonics": SEASONAL_HARMONICS,
        "use_persistence": loses_to_persistence,
        "suppressed": aqi_suppressed,
        "suppression_reason": selection_reason if aqi_suppressed else None,
        "selection_reason": selection_reason,
        "persistence_mae": persistence_mae,
        "last7_mean_mae": last7_mae,
        "is_aqi_forecast": parameter == AQI_PARAMETER,
    }
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = _get_model_path(location, parameter, dataset_id)
    joblib.dump(model_dict, model_path)
    
    metadata = _load_metadata()
    key = _model_key(location, parameter, dataset_id)
    metadata[key] = metrics
    _save_metadata(metadata)
    
    return model_dict, metrics


def load_forecast_model(location: str, parameter: str, dataset_id: Optional[str] = None) -> Tuple[Dict, datetime, float]:
    """Load trained model with base timestamp and days_per_unit."""
    model_path = _get_model_path(location, parameter, dataset_id)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Forecast model not found for {_model_key(location, parameter, dataset_id)}")
    model_dict = joblib.load(model_path)
    base_timestamp = datetime.fromisoformat(model_dict['base_timestamp'])
    days_per_unit = model_dict['days_per_unit']
    return model_dict, base_timestamp, days_per_unit


def generate_forecast(
    df: pd.DataFrame, 
    location: str, 
    parameter: str, 
    horizon: int = DEFAULT_HORIZON, 
    freq: str = DEFAULT_FREQ,
    dataset_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate forecast for a location and parameter.
    Returns predictions with confidence intervals at real, strictly future
    timestamps (one step per observed interval after the last observation).
    """
    try:
        model_dict, _, _ = load_forecast_model(location, parameter, dataset_id)
    except FileNotFoundError:
        model_dict, _ = train_forecast_model(df, location, parameter, dataset_id=dataset_id)

    if model_dict.get('suppressed'):
        raise ValueError(
            model_dict.get('suppression_reason')
            or f"Forecast for {location} - {parameter} was hidden by skill gating."
        )
    
    prophet_df, base_timestamp, days_per_unit = _prepare_relative_data(df, location, parameter)
    if len(prophet_df) == 0:
        raise ValueError(f"No usable data for {location} - {parameter}")
    
    step = float(days_per_unit) if days_per_unit else 1.0
    last_day = float(prophet_df['ds'].max())
    last_timestamp = base_timestamp + timedelta(days=last_day)
    future_days = last_day + step * np.arange(1, horizon + 1)
    use_persistence = bool(model_dict.get('use_persistence'))
    if use_persistence:
        predicted_values = np.full(horizon, float(model_dict.get('last_value', 0.0)))
    else:
        predicted_values = _predict(model_dict, future_days)
    sigma = float(model_dict.get('residual_std') or 0.0)
    half_widths = model_dict.get('interval_half_widths') or []
    persistence_half_width = model_dict.get('persistence_mae')
    climatology = model_dict.get('rain_climatology') or {}
    if climatology:
        climatology_publishable = int(climatology.get('years_observed') or 0) >= MIN_CLIMATOLOGY_YEARS
    else:
        climatology_publishable = True  # legacy models carry no history metadata
    rain_probability = (
        climatology.get('month_daily_probability') or model_dict.get('monthly_rain_probability')
    ) if climatology_publishable else None
    
    predictions = []
    for index, value in enumerate(predicted_values):
        value = float(value)
        if use_persistence and persistence_half_width is not None:
            half_width = float(persistence_half_width)
        elif index < len(half_widths):
            half_width = float(half_widths[index])
        else:
            half_width = Z_80 * sigma
        lower = value - half_width
        upper = value + half_width
        prediction_timestamp = last_timestamp + timedelta(days=step * (index + 1))
        if parameter == 'precipitation':
            value = max(0.0, value)
            lower = max(0.0, lower)
        if parameter == AQI_PARAMETER:
            value = min(500.0, max(0.0, value))
            lower = min(500.0, max(0.0, lower))
            upper = min(500.0, max(0.0, upper))
        prediction = {
            'timestamp': prediction_timestamp.isoformat() + 'Z',
            'predicted_value': round(value, 2),
            'lower_bound': round(lower, 2),
            'upper_bound': round(upper, 2),
        }
        if parameter == AQI_PARAMETER:
            chances = aqi_category_chances(value, half_width)
            prediction['category_probabilities'] = chances
            prediction['most_likely_category'] = max(chances, key=chances.get)
        if parameter == 'precipitation' and rain_probability and rain_probability[prediction_timestamp.month - 1] is not None:
            prediction['rain_probability'] = rain_probability[prediction_timestamp.month - 1]
        predictions.append(prediction)
    
    metadata = _load_metadata()
    stored_metrics = metadata.get(_model_key(location, parameter, dataset_id), {})
    
    result_metrics = {
        'mae': stored_metrics.get('test_mae', 0.0),
        'rmse': stored_metrics.get('test_rmse', 0.0),
        'training_samples': stored_metrics.get('train_samples', len(prophet_df)),
        'baseline_persistence_mae': stored_metrics.get('baseline_persistence_mae'),
        'baseline_last7_mean_mae': stored_metrics.get('baseline_last7_mean_mae'),
        'baseline_zero_mae': stored_metrics.get('baseline_zero_mae'),
        'skill_vs_persistence_pct': stored_metrics.get('skill_vs_persistence_pct'),
        'candidate_skill_vs_persistence_pct': stored_metrics.get('candidate_skill_vs_persistence_pct'),
        'skill_vs_last7_mean_pct': stored_metrics.get('skill_vs_last7_mean_pct'),
        'candidate_skill_vs_last7_mean_pct': stored_metrics.get('candidate_skill_vs_last7_mean_pct'),
        'skill_vs_better_baseline_pct': stored_metrics.get('skill_vs_better_baseline_pct'),
        'skill_claimed': stored_metrics.get('skill_claimed'),
        'forecast_published': stored_metrics.get('forecast_published', True),
        'selection_reason': stored_metrics.get('selection_reason'),
        'series_eligibility': stored_metrics.get('series_eligibility'),
        'horizon_mae': stored_metrics.get('horizon_mae'),
        'horizon_persistence_mae': stored_metrics.get('horizon_persistence_mae'),
        'horizon_last7_mean_mae': stored_metrics.get('horizon_last7_mean_mae'),
        'interval_coverage_pct': stored_metrics.get('interval_coverage_pct'),
        'rolling_origins': stored_metrics.get('rolling_origins'),
        'evaluation': stored_metrics.get('evaluation'),
        'model_note': stored_metrics.get('model_note'),
    }
    if parameter == 'precipitation':
        result_metrics['limitation'] = stored_metrics.get('limitation') or PRECIPITATION_LIMITATION
        result_metrics['seven_day_total_mm'] = round(sum(p['predicted_value'] for p in predictions), 1)
        if climatology:
            result_metrics['rain_climatology_threshold_mm'] = climatology.get('threshold_mm')
            result_metrics['rain_climatology_years'] = climatology.get('years_observed')
            result_metrics['rain_climatology_wet_years'] = climatology.get('wet_years')
            result_metrics['rain_climatology_window_days'] = climatology.get('window_days')
            result_metrics['rain_climatology_min_years'] = MIN_CLIMATOLOGY_YEARS
            week_probability = climatology.get('week_probability') if climatology_publishable else None
            result_metrics['week_rain_probability_pct'] = (
                round(week_probability * 100) if week_probability is not None else None
            )
    
    return {
        'location': location,
        'parameter': parameter,
        'model_used': 'persistence_baseline' if use_persistence else model_dict['model_type'],
        'forecast_horizon': horizon,
        'predictions': predictions,
        'metrics': result_metrics,
    }


def _default_parameters(df: pd.DataFrame) -> List[str]:
    """Forecast every well-populated series in the dataframe, whether it holds
    pollutants (air quality datasets) or weather columns."""
    return [
        c for c in FEATURE_POOL
        if c in df.columns and df[c].notna().sum() >= MIN_TRAIN_SAMPLES
    ]


def purge_dataset_models(dataset_id: str) -> int:
    """Delete persisted forecaster models and metadata entries for one dataset."""
    removed = 0
    prefix = f"{FORECAST_MODEL_PREFIX}{dataset_id}_"
    if os.path.isdir(MODEL_DIR):
        for name in os.listdir(MODEL_DIR):
            if name.startswith(prefix) and name.endswith('.joblib'):
                os.remove(os.path.join(MODEL_DIR, name))
                removed += 1

    metadata = _load_metadata()
    stale_keys = [key for key in metadata if key.startswith(f"{dataset_id}_")]
    for key in stale_keys:
        metadata.pop(key)
    if stale_keys:
        _save_metadata(metadata)
    return removed


def generate_multi_location_forecast(
    df: pd.DataFrame, 
    parameters: List[str] = None, 
    horizon: int = DEFAULT_HORIZON,
    dataset_id: Optional[str] = None,
    skip_reasons: Optional[List[Dict[str, Any]]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    """Generate forecasts for all locations and parameters."""
    if parameters is None:
        parameters = _default_parameters(df)
    
    locations = df['location'].unique()
    results = []
    
    for location in locations:
        for parameter in parameters:
            if parameter not in df.columns:
                continue
            if cancel_check is not None:
                cancel_check()
            try:
                result = generate_forecast(df, location, parameter, horizon, dataset_id=dataset_id)
                results.append(result)
            except Exception as e:
                if skip_reasons is not None:
                    skip_reasons.append({
                        'location': location,
                        'parameter': parameter,
                        'reason': str(e),
                    })
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
    max_age_hours: int = 24,
    dataset_id: Optional[str] = None
) -> Tuple[Dict, Dict[str, Any]]:
    """Retrain model if it doesn't exist or is older than max_age_hours."""
    metadata = _load_metadata()
    key = _model_key(location, parameter, dataset_id)
    model_path = _get_model_path(location, parameter, dataset_id)
    
    if not os.path.exists(model_path) or key not in metadata:
        return train_forecast_model(df, location, parameter, dataset_id=dataset_id)
    
    trained_at = datetime.fromisoformat(metadata[key]['trained_at'])
    age_hours = (datetime.utcnow() - trained_at).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        return train_forecast_model(df, location, parameter, dataset_id=dataset_id)
    
    model, _, _ = load_forecast_model(location, parameter, dataset_id)
    return model, metadata[key]
