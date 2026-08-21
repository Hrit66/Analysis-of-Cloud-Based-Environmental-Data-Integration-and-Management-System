import re
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

STANDARDIZED_AIR_QUALITY_COLUMNS: List[str] = [
    "timestamp",
    "location",
    "pm25",
    "pm10",
    "no2",
    "so2",
    "co",
    "o3",
]

_AIR_QUALITY_COLUMN_PATTERNS: Dict[str, List[str]] = {
    "timestamp": [
        r"^timestamp$",
        r"^time$",
        r"^datetime$",
        r"^date_time$",
        r"^date$",
        r"^ts$",
        r"^reading_time$",
        r"^sampling_time$",
        r"^utc_time$",
        r"^datetime_utc$",
        r"^recorded_at$",
    ],
    "location": [
        r"^location$",
        r"^station$",
        r"^station_name$",
        r"^station_id$",
        r"^site$",
        r"^site_name$",
        r"^city$",
        r"^area$",
        r"^monitoring_station$",
        r"^device_id$",
        r"^sensor_id$",
    ],
    "pm25": [
        r"^pm25",
        r"^pm2\.5",
        r"^pm_25",
        r"^pm_2\.5",
        r"^pm2_5",
        r"^particulate.*2\.5",
    ],
    "pm10": [
        r"^pm10",
        r"^pm_10",
        r"^particulate.*10",
    ],
    "no2": [
        r"^no2",
        r"^no_2",
        r"^nitrogen_dioxide",
    ],
    "so2": [
        r"^so2",
        r"^so_2",
        r"^sulfur_dioxide",
        r"^sulphur_dioxide",
    ],
    "co": [
        r"^co$",
        r"^co_",
        r"^co\b",
        r"^carbon_monoxide",
    ],
    "o3": [
        r"^o3",
        r"^o_3",
        r"^ozone",
    ],
}


def _match_column_name(raw_col: str) -> Optional[str]:
    """Map a raw column header string to a canonical air quality field name."""
    cleaned = str(raw_col).strip().lower()
    norm = re.sub(r"[\s\-\/\(\)\[\]µ]+", "_", cleaned).strip("_")

    for canonical, patterns in _AIR_QUALITY_COLUMN_PATTERNS.items():
        if cleaned == canonical or norm == canonical:
            return canonical
        for pat in patterns:
            if re.search(pat, cleaned) or re.search(pat, norm):
                return canonical
    return None


def normalize_air_quality(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize an air quality DataFrame into standardized schema and data types.

    Standardized output columns:
    - timestamp: ISO 8601 string, normalized to UTC (e.g. '2026-08-21T14:30:00Z')
    - location: string
    - pm25: float, µg/m³
    - pm10: float, µg/m³
    - no2: float, µg/m³
    - so2: float, µg/m³
    - co: float, mg/m³
    - o3: float, µg/m³

    Args:
        data (pd.DataFrame): Raw or pre-cleaned DataFrame.

    Returns:
        pd.DataFrame: A new DataFrame with exact standardized columns and types.

    Raises:
        TypeError: If `data` is not a pandas DataFrame.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"Expected data to be a pandas DataFrame, got {type(data).__name__}")

    df = data.copy()

    # Step 1: Map existing columns to canonical names
    column_mapping = {}
    for col in df.columns:
        matched = _match_column_name(col)
        if matched and matched not in column_mapping.values():
            column_mapping[col] = matched

    df = df.rename(columns=column_mapping)

    # Step 2: Ensure all standardized columns exist in df
    for canonical_col in STANDARDIZED_AIR_QUALITY_COLUMNS:
        if canonical_col not in df.columns:
            df[canonical_col] = np.nan

    # Step 3: Standardize timestamp (UTC ISO 8601 string)
    dt_series = pd.to_datetime(df["timestamp"], utc=True, format="mixed", errors="coerce")
    df["timestamp"] = dt_series.dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Step 4: Standardize location to string
    df["location"] = df["location"].fillna("").astype(str)

    # Step 5: Standardize pollutant metrics to float
    pollutant_cols = ["pm25", "pm10", "no2", "so2", "co", "o3"]
    for col in pollutant_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    # Step 6: Return exact standardized columns in canonical order
    return df[STANDARDIZED_AIR_QUALITY_COLUMNS]
