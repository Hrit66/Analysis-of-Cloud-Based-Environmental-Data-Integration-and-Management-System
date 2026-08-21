from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd

AIR_QUALITY_RANGES: Dict[str, Tuple[float, float]] = {
    "pm25": (0.0, 1000.0),   # µg/m³
    "pm10": (0.0, 1500.0),   # µg/m³
    "no2": (0.0, 1000.0),    # µg/m³
    "so2": (0.0, 2000.0),    # µg/m³
    "co": (0.0, 200.0),      # mg/m³
    "o3": (0.0, 1000.0),     # µg/m³
}


def check_and_filter_ranges(
    df: pd.DataFrame,
    ranges: Optional[Dict[str, Tuple[float, float]]] = None,
    set_invalid_to_nan: bool = True,
) -> pd.DataFrame:
    """Validate numeric pollutant columns against physical/realistic range limits.

    Values outside the expected range (such as negative sensor noise or impossible outliers)
    are replaced with NaN to prevent sensor artifacts from corrupting downstream metrics.

    Args:
        df (pd.DataFrame): DataFrame containing numeric pollutant columns.
        ranges (Optional[Dict[str, Tuple[float, float]]]): Custom min/max range boundaries.
        set_invalid_to_nan (bool): If True, replaces out-of-range values with NaN.

    Returns:
        pd.DataFrame: Sanitized copy of the DataFrame.
    """
    cleaned_df = df.copy()
    limits = ranges if ranges is not None else AIR_QUALITY_RANGES

    for col, (min_val, max_val) in limits.items():
        if col in cleaned_df.columns:
            series = pd.to_numeric(cleaned_df[col], errors="coerce")
            if set_invalid_to_nan:
                invalid_mask = (series < min_val) | (series > max_val)
                series[invalid_mask] = np.nan
            cleaned_df[col] = series.astype(float)

    return cleaned_df
