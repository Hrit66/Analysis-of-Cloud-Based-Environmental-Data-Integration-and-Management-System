"""Monthly water-quality outlooks for CPCB surface-water datasets.

Outlooks are published per station and parameter for total coliform, dissolved
oxygen and the core WQI:

* **Coliform** MPN counts span several orders of magnitude (the current dataset
  reaches 9.2e9), so that series is modelled in log1p space: every sample is
  transformed with log1p and averaged per calendar month, then transformed back
  to MPN/100 mL.
* **DO and WQI** are modelled in native units (mg/L and index points) - their
  ranges are tame and a log transform would only complicate the metrics.

A station's monthly series is short (44 points for Allasandra over 2018-2021),
far below the 200-sample minimum for the annual-harmonic model, so the fit
falls back to simple exponential smoothing for every parameter.

Every outlook is evaluated rolling-origin against the persistence baseline
(repeat the last observed month) at horizons 1-3 months. Stored metrics carry
both MAEs per horizon plus an honest limitation note: monthly sampling is
sparse and this source often repeats values across consecutive months, which
makes persistence hard to beat. When persistence matches or beats the model at
the 1-month horizon, the note says so. Stations below the minimum monthly
count (24, the coliform standard, applied to all three parameters) are
skipped - there is nothing defensible to publish for them.
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services import dataset_config
from app.services.forecaster import (
    ANCHOR_LABELS,
    DEFAULT_ANCHOR_MODE,
    fit_seasonal_baseline,
    predict_seasonal_baseline,
    rolling_origin_metrics,
)

WATER_PARAMETER = "total_coliform"
WATER_FORECAST_PARAMETERS: Tuple[str, ...] = ("total_coliform", "do", "wqi")
DEFAULT_WATER_HORIZON = 3  # months
MIN_MONTHS_FOR_OUTLOOK = 24  # two years of monthly samples before publishing
Z_80 = 1.2816  # fallback 80% interval when rolling calibration is unavailable

# Per-parameter modelling configuration: transform, display units, rounding
# precision of the published predictions and the wording used in notes.
PARAMETER_CONFIG: Dict[str, Dict[str, Any]] = {
    "total_coliform": {
        "transform": "log1p",
        "label": "coliform",
        "units": "MPN/100 mL (inverse-transformed)",
        "scale": "log1p",
        "precision": 0,
    },
    "do": {
        "transform": "identity",
        "label": "dissolved oxygen",
        "units": "mg/L",
        "scale": "native",
        "precision": 2,
    },
    "wqi": {
        "transform": "identity",
        "label": "WQI",
        "units": "index points (0-200)",
        "scale": "native",
        "precision": 2,
    },
}

COLIFORM_CARRY_FORWARD_NOTE = (
    "Monthly coliform is sparse and this source often repeats the same MPN "
    "across consecutive months. The persistence baseline (repeat the last "
    "month) scores MAE {persistence} vs the model's {model} at the 1-month "
    "horizon, so there is no meaningful gain over persistence here - treat the "
    "outlook as a broad level indicator only."
)
COLIFORM_LIMITATION = (
    "Monthly coliform outlook from {months} monthly points; sampling is sparse "
    "and consecutive months often repeat the same MPN, so treat the outlook as "
    "a broad level indicator, not a precise forecast."
)
WATER_CARRY_FORWARD_NOTE = (
    "Monthly sampling is sparse and this source often repeats values across "
    "consecutive months. The persistence baseline (repeat the last month) "
    "scores MAE {persistence} vs the model's {model} at the 1-month horizon, "
    "so there is no meaningful gain over persistence here - treat the outlook "
    "as a broad level indicator only."
)
WATER_LIMITATION = (
    "Monthly {label} outlook from {months} monthly points; sampling is roughly "
    "monthly and sparse, so treat the outlook as a broad level indicator, not "
    "a precise forecast."
)


def _monthly_series(
    df: pd.DataFrame,
    location: str,
    parameter: str,
    transform: str,
) -> Tuple[np.ndarray, np.ndarray, pd.PeriodIndex, int]:
    """Monthly mean of one station/parameter, transformed per config.

    Returns (values, days_since_first_month, month_index, raw_sample_count)
    where ``values`` and ``days_since_first_month`` are numpy arrays and
    ``month_index`` is a monthly PeriodIndex.
    """
    if parameter not in df.columns:
        raise ValueError(f"No {parameter} column in the dataset")

    loc = df[df['location'] == location].copy()
    loc['timestamp'] = pd.to_datetime(loc['timestamp'], utc=True, format='mixed', errors='coerce')
    loc[parameter] = pd.to_numeric(loc[parameter], errors='coerce')
    loc = loc.dropna(subset=['timestamp', parameter])
    if loc.empty:
        raise ValueError(f"No {parameter} samples for {location}")

    values = loc[parameter].astype(float)
    if (values < 0).any():
        raise ValueError(f"Negative {parameter} values for {location}")

    transformed = np.log1p(values) if transform == "log1p" else values
    loc['transformed'] = transformed
    loc['month'] = loc['timestamp'].dt.to_period('M')
    monthly = loc.groupby('month')['transformed'].mean().sort_index()

    month_starts = monthly.index.to_timestamp()
    days = np.array(
        [(stamp - month_starts[0]).total_seconds() / 86400.0 for stamp in month_starts],
        dtype=float,
    )
    return monthly.to_numpy(dtype=float), days, monthly.index, int(len(loc))


def _monthly_log_series(df: pd.DataFrame, location: str):
    """Monthly mean of log1p(coliform) for one station (coliform entry point)."""
    return _monthly_series(df, location, WATER_PARAMETER, "log1p")


def _future_month_starts(month_index, horizon: int):
    """Month-start timestamps and day offsets for the next ``horizon`` months."""
    first_start = month_index[0].to_timestamp()
    starts = [(month_index[-1] + step).to_timestamp() for step in range(1, horizon + 1)]
    days = np.array(
        [(stamp - first_start).total_seconds() / 86400.0 for stamp in starts],
        dtype=float,
    )
    return starts, days


def _model_note(fit: Dict[str, Any], months: int, config: Dict[str, Any]) -> str:
    if fit['model_type'] == 'HarmonicRegression':
        anchor_label = ANCHOR_LABELS.get(
            fit.get('anchor_mode') or DEFAULT_ANCHOR_MODE, DEFAULT_ANCHOR_MODE
        )
        return (
            "annual-harmonic regression with "
            f"{anchor_label} residual level on monthly {config['label']} ({months} monthly points)"
        )
    if config['transform'] == 'log1p':
        return (
            "monthly mean of log1p(MPN) with exponential smoothing fallback "
            f"({months} monthly points; no annual seasonality fitted at this sample size)"
        )
    return (
        f"monthly mean {config['label']} with exponential smoothing fallback "
        f"({months} monthly points; no annual seasonality fitted at this sample size)"
    )


def _back_transform(value: float, half_width: float, config: Dict[str, Any]) -> Tuple[float, float, float]:
    """Point prediction and interval bounds in the published units."""
    precision = config['precision']
    if config['transform'] == 'log1p':
        point = float(np.expm1(value))
        lower = float(np.expm1(value - half_width))
        upper = float(np.expm1(value + half_width))
    else:
        point = float(value)
        lower = max(0.0, float(value - half_width))
        upper = float(value + half_width)
    return (
        float(round(point, precision)),
        float(round(max(lower, 0.0), precision)),
        float(round(upper, precision)),
    )


def forecast_water_parameter(
    df: pd.DataFrame,
    location: str,
    parameter: str = WATER_PARAMETER,
    horizon: int = DEFAULT_WATER_HORIZON,
    min_months: int = MIN_MONTHS_FOR_OUTLOOK,
) -> Dict[str, Any]:
    """Fit and evaluate a monthly outlook for one station and parameter.

    The returned document matches the air/weather forecast schema (location,
    parameter, model_used, forecast_horizon, predictions, metrics) with
    predictions in the parameter's own units, so the API and dashboards can
    consume it unchanged.
    """
    config = PARAMETER_CONFIG.get(parameter)
    if config is None:
        raise ValueError(f"Unsupported water forecast parameter: {parameter}")

    values, days, month_index, raw_samples = _monthly_series(
        df, location, parameter, config['transform']
    )
    months = len(values)
    first_month, last_month = month_index[0], month_index[-1]
    span_days = float((last_month.start_time - first_month.start_time).days)
    span_months = int((last_month - first_month).n)
    missing_share = max(0.0, 1.0 - months / (span_months + 1))
    eligible, reason = dataset_config.check_ml_eligibility(
        "water_quality", months, span_days, missing_share
    )
    if not eligible:
        raise ValueError(
            f"Insufficient monthly {config['label']} history for {location}: {reason}"
        )

    days_per_unit = float(np.median(np.diff(days)))
    fit = fit_seasonal_baseline(days, values, days_per_unit)
    rolling = rolling_origin_metrics(days, values, days_per_unit, horizon=horizon)

    persistence_mae = (rolling or {}).get('persistence_mae')
    model_mae = (rolling or {}).get('mae')
    loses_to_persistence = bool(
        persistence_mae is not None
        and model_mae is not None
        and model_mae > persistence_mae
    )
    if loses_to_persistence:
        selection_reason = (
            f"model MAE {model_mae:.3f} was worse than persistence MAE "
            f"{persistence_mae:.3f} at the 1-month horizon; publishing the "
            "persistence baseline instead of claiming skill."
        )
    elif persistence_mae is not None:
        selection_reason = (
            f"model MAE {model_mae:.3f} beat persistence MAE "
            f"{persistence_mae:.3f} at the 1-month horizon."
        )
    else:
        selection_reason = (
            "series too short for rolling-origin evaluation; no skill over "
            "persistence is claimed."
        )

    future_starts, future_days = _future_month_starts(month_index, horizon)
    if loses_to_persistence:
        predicted = np.full(len(future_days), float(values[-1]))
    else:
        predicted = predict_seasonal_baseline(fit, future_days)
    half_widths = (rolling or {}).get('interval_half_widths') or []
    fallback_half_width = (
        float(persistence_mae) if loses_to_persistence
        else Z_80 * float(fit['residual_std'])
    )

    predictions: List[Dict[str, Any]] = []
    for index, value in enumerate(predicted):
        half_width = float(half_widths[index]) if index < len(half_widths) else fallback_half_width
        point, lower, upper = _back_transform(value, half_width, config)
        predictions.append({
            'timestamp': future_starts[index].tz_localize('UTC').isoformat().replace('+00:00', 'Z'),
            'predicted_value': point,
            'lower_bound': lower,
            'upper_bound': upper,
        })

    horizon_mae = (rolling or {}).get('horizon_mae') or []
    horizon_persistence = (rolling or {}).get('horizon_persistence_mae') or []
    skill = None
    if rolling and rolling.get('persistence_mae'):
        skill = round((1 - rolling['mae'] / rolling['persistence_mae']) * 100, 1)
    skill_claimed = bool(skill is not None and skill > 0 and not loses_to_persistence)

    if config['transform'] == 'log1p':
        limitation = COLIFORM_LIMITATION.format(months=months)
        carry_forward = COLIFORM_CARRY_FORWARD_NOTE
    else:
        limitation = WATER_LIMITATION.format(label=config['label'], months=months)
        carry_forward = WATER_CARRY_FORWARD_NOTE
    if horizon_mae and horizon_persistence and horizon_mae[0] >= horizon_persistence[0]:
        limitation = carry_forward.format(
            persistence=round(horizon_persistence[0], 3),
            model=round(horizon_mae[0], 3),
        )

    if loses_to_persistence:
        model_used = "persistence_baseline"
        model_note = (
            f"persistence baseline for monthly {config['label']} "
            f"({months} monthly points)"
        )
    else:
        model_used = fit['model_type']
        if config['transform'] == 'log1p':
            model_used = f"{model_used}_log1p"
        model_note = _model_note(fit, months, config)

    metrics = {
        'monthly_points': months,
        'sample_count': raw_samples,
        'first_month': str(month_index[0]),
        'last_month': str(month_index[-1]),
        'scale': config['scale'],
        'units': config['units'],
        'test_mae': round(rolling['mae'], 3) if rolling else None,
        'test_rmse': round(rolling['rmse'], 3) if rolling else None,
        'mae_multiplicative_factor': round(float(np.exp(rolling['mae'])), 2) if rolling and config['transform'] == 'log1p' else None,
        'baseline_persistence_mae': round(rolling['persistence_mae'], 3) if rolling else None,
        'skill_vs_persistence_pct': (
            0.0 if loses_to_persistence else skill
        ),
        'candidate_skill_vs_persistence_pct': skill,
        'skill_claimed': skill_claimed,
        'selection_reason': selection_reason,
        'series_eligibility': 'eligible',
        'horizon_mae': [round(value, 3) for value in horizon_mae],
        'horizon_persistence_mae': [round(value, 3) for value in horizon_persistence],
        'interval_coverage_pct': (rolling or {}).get('interval_coverage_pct'),
        'rolling_origins': (rolling or {}).get('origins', 0),
        'rolling_horizon': horizon,
        'evaluation': (rolling or {}).get(
            'evaluation', 'in-sample (series too short for rolling-origin evaluation)'
        ),
        'model_note': model_note,
        'limitation': limitation,
        'min_months_required': min_months,
    }

    return {
        'location': location,
        'parameter': parameter,
        'model_used': model_used,
        'forecast_horizon': horizon,
        'predictions': predictions,
        'metrics': metrics,
    }


def forecast_coliform(
    df: pd.DataFrame,
    location: str,
    horizon: int = DEFAULT_WATER_HORIZON,
    min_months: int = MIN_MONTHS_FOR_OUTLOOK,
) -> Dict[str, Any]:
    """Back-compat wrapper: monthly coliform outlook for one station."""
    return forecast_water_parameter(df, location, WATER_PARAMETER, horizon=horizon, min_months=min_months)


def generate_water_forecasts(
    df: pd.DataFrame,
    dataset_id: Optional[str] = None,
    horizon: int = DEFAULT_WATER_HORIZON,
    min_months: int = MIN_MONTHS_FOR_OUTLOOK,
    parameters: Tuple[str, ...] = WATER_FORECAST_PARAMETERS,
    skip_reasons: Optional[List[Dict[str, Any]]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> List[Dict[str, Any]]:
    """Outlooks for every station/parameter with enough monthly history.

    Stations or parameters below ``min_months`` are skipped silently - there is
    nothing defensible to publish for them yet.
    """
    if 'location' not in df.columns:
        return []

    results: List[Dict[str, Any]] = []
    for location in df['location'].dropna().unique():
        for parameter in parameters:
            if parameter not in df.columns:
                continue
            if cancel_check is not None:
                cancel_check()
            try:
                result = forecast_water_parameter(
                    df, location, parameter, horizon=horizon, min_months=min_months
                )
            except ValueError as exc:
                if skip_reasons is not None:
                    skip_reasons.append({
                        "location": location,
                        "parameter": parameter,
                        "reason": str(exc),
                    })
                continue
            result['dataset_id'] = dataset_id
            result['created_at'] = datetime.utcnow()
            results.append(result)
    return results


def generate_coliform_forecasts(
    df: pd.DataFrame,
    dataset_id: Optional[str] = None,
    horizon: int = DEFAULT_WATER_HORIZON,
    min_months: int = MIN_MONTHS_FOR_OUTLOOK,
) -> List[Dict[str, Any]]:
    """Back-compat wrapper: coliform outlooks for every qualifying station."""
    return generate_water_forecasts(
        df, dataset_id=dataset_id, horizon=horizon, min_months=min_months,
        parameters=(WATER_PARAMETER,),
    )
