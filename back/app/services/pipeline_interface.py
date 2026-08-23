import re
import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict, List
from app.models.air_quality import AirQualityCreate

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

AIR_QUALITY_RANGES: Dict[str, Tuple[float, float]] = {
    "pm25": (0.0, 1000.0),
    "pm10": (0.0, 1500.0),
    "no2": (0.0, 1000.0),
    "so2": (0.0, 2000.0),
    "co": (0.0, 200.0),
    "o3": (0.0, 1000.0),
}


def _match_column_name(raw_col: str) -> Optional[str]:
    cleaned = str(raw_col).strip().lower()
    norm = re.sub(r"[\s\-\/\(\)\[\]µ]+", "_", cleaned).strip("_")

    for canonical, patterns in _AIR_QUALITY_COLUMN_PATTERNS.items():
        if cleaned == canonical or norm == canonical:
            return canonical
        for pat in patterns:
            if re.search(pat, cleaned) or re.search(pat, norm):
                return canonical
    return None


def parse_file(file_path: str, dataset_type: str) -> pd.DataFrame:
    """
    Parse uploaded file (CSV, JSON, Excel) into a raw DataFrame.
    Returns raw DataFrame with original columns preserved.
    """
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
    elif file_path.endswith('.json'):
        df = pd.read_json(file_path)
    elif file_path.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file format: {file_path}")
    return df


def clean_dataframe(df: pd.DataFrame, dataset_type: str) -> Tuple[pd.DataFrame, dict]:
    """
    Clean and normalize DataFrame for the given dataset_type.
    Returns (cleaned_df, cleaning_report)
    
    cleaning_report contains:
    - original_shape, cleaned_shape
    - columns_renamed, columns_dropped
    - missing_values_count, duplicates_removed
    - out_of_range_values_set_to_nan
    """
    report = {
        "original_shape": df.shape,
        "columns_renamed": {},
        "columns_dropped": [],
        "missing_values_count": {},
        "duplicates_removed": 0,
        "out_of_range_values_set_to_nan": {},
    }
    
    df = df.copy()
    
    if dataset_type == "air_quality":
        df, report = _clean_air_quality(df, report)
    else:
        df, report = _clean_generic(df, report)
    
    report["cleaned_shape"] = df.shape
    return df, report


def _clean_air_quality(df: pd.DataFrame, report: dict) -> Tuple[pd.DataFrame, dict]:
    column_mapping = {}
    for col in df.columns:
        matched = _match_column_name(col)
        if matched and matched not in column_mapping.values():
            column_mapping[col] = matched
    
    df = df.rename(columns=column_mapping)
    report["columns_renamed"] = column_mapping
    
    for canonical_col in STANDARDIZED_AIR_QUALITY_COLUMNS:
        if canonical_col not in df.columns:
            df[canonical_col] = np.nan
    
    required_cols = ['timestamp', 'location']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Required column '{col}' not found in data")
    
    dt_series = pd.to_datetime(df["timestamp"], utc=True, format="mixed", errors="coerce")
    df["timestamp"] = dt_series.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df = df.dropna(subset=['timestamp'])
    
    df["location"] = df["location"].fillna("").astype(str)
    
    pollutant_cols = ["pm25", "pm10", "no2", "so2", "co", "o3"]
    for col in pollutant_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
            missing_count = df[col].isna().sum()
            if missing_count > 0:
                report["missing_values_count"][col] = int(missing_count)
    
    duplicates = df.duplicated(subset=['timestamp', 'location']).sum()
    if duplicates > 0:
        df = df.drop_duplicates(subset=['timestamp', 'location'], keep='first')
        report["duplicates_removed"] = int(duplicates)
    
    for col, (min_val, max_val) in AIR_QUALITY_RANGES.items():
        if col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce")
            invalid_mask = (series < min_val) | (series > max_val)
            invalid_count = invalid_mask.sum()
            if invalid_count > 0:
                series[invalid_mask] = np.nan
                df[col] = series.astype(float)
                report["out_of_range_values_set_to_nan"][col] = int(invalid_count)
    
    return df[STANDARDIZED_AIR_QUALITY_COLUMNS], report


def _clean_generic(df: pd.DataFrame, report: dict) -> Tuple[pd.DataFrame, dict]:
    df.columns = df.columns.str.lower().str.strip()
    
    duplicates = df.duplicated().sum()
    if duplicates > 0:
        df = df.drop_duplicates(keep='first')
        report["duplicates_removed"] = int(duplicates)
    
    for col in df.select_dtypes(include=['number']).columns:
        missing = df[col].isna().sum()
        if missing > 0:
            report["missing_values_count"][col] = int(missing)
    
    return df, report


def dataframe_to_records(df: pd.DataFrame, dataset_id: str, dataset_type: str) -> list:
    """Convert cleaned DataFrame to list of model instances for DB insertion."""
    records = []
    for _, row in df.iterrows():
        if dataset_type == "air_quality":
            timestamp = row['timestamp']
            if isinstance(timestamp, str):
                timestamp = pd.to_datetime(timestamp, utc=True).to_pydatetime()
            
            record = AirQualityCreate(
                timestamp=timestamp,
                location=str(row['location']),
                pm25=row.get('pm25'),
                pm10=row.get('pm10'),
                no2=row.get('no2'),
                so2=row.get('so2'),
                co=row.get('co'),
                o3=row.get('o3'),
                dataset_id=dataset_id,
                dataset_type=dataset_type,
            )
            records.append(record.model_dump())
    return records