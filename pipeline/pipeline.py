from pathlib import Path
from typing import Optional, Union
import pandas as pd

from pipeline.cleaners.cleaner import clean_data
from pipeline.cleaners.normalizer import normalize_air_quality
from pipeline.cleaners.range_checker import check_and_filter_ranges
from pipeline.readers.csv_reader import read_csv
from pipeline.readers.excel_reader import read_excel
from pipeline.readers.json_reader import read_json
from pipeline.validators.file_validator import validate_file


def parse_file(
    file_path: Union[str, Path],
    file_type: Optional[str] = None,
    **kwargs,
) -> pd.DataFrame:
    """Parse a data file into a pandas DataFrame based on file type or extension.

    This is a pure function with no database, background tasks, or backend dependencies.

    Supported formats: CSV, JSON, Excel (.xlsx, .xls)

    Args:
        file_path (Union[str, Path]): Path to the data file.
        file_type (Optional[str]): Explicit file format ('csv', 'json', 'excel', 'xlsx', 'xls').
            If not provided, inferred from the file extension.
        **kwargs: Additional keyword arguments passed to the underlying reader function.

    Returns:
        pd.DataFrame: The loaded dataset as a DataFrame.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file format/extension is unsupported.
    """
    validate_file(file_path)
    path = Path(file_path)

    ft = file_type.lower().strip() if file_type else path.suffix.lower().lstrip(".")

    if ft == "csv":
        return read_csv(path, **kwargs)
    elif ft == "json":
        return read_json(path, **kwargs)
    elif ft in ("excel", "xlsx", "xls"):
        return read_excel(path, **kwargs)
    else:
        raise ValueError(
            f"Unsupported file format: '{ft}'. Supported formats are: csv, json, excel, xlsx, xls"
        )


def clean_dataframe(
    df: pd.DataFrame,
    dataset_type: str = "air_quality",
) -> pd.DataFrame:
    """Clean and standardize a pandas DataFrame for a given dataset type.

    This is a pure function that performs generic sanitization, domain normalization,
    and range checking without interacting with any database or external service.

    For dataset_type="air_quality", produces a DataFrame with exactly:
    - timestamp: ISO 8601 string, normalized to UTC
    - location: string
    - pm25: float, µg/m³
    - pm10: float, µg/m³
    - no2: float, µg/m³
    - so2: float, µg/m³
    - co: float, mg/m³
    - o3: float, µg/m³

    Args:
        df (pd.DataFrame): Input DataFrame to be cleaned and standardized.
        dataset_type (str): Type of environmental dataset (default: 'air_quality').

    Returns:
        pd.DataFrame: Cleaned DataFrame containing exact standardized columns.

    Raises:
        TypeError: If `df` is not a pandas DataFrame.
        ValueError: If `dataset_type` is unsupported.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected df to be a pandas DataFrame, got {type(df).__name__}")

    dataset_key = dataset_type.lower().strip()

    if dataset_key == "air_quality":
        # 1. Generic cleaning: strip headers, drop completely empty rows/columns, drop duplicate rows
        cleaned = clean_data(df)
        # 2. Domain normalization: map column aliases, parse ISO 8601 UTC timestamps, cast types, project columns
        normalized = normalize_air_quality(cleaned)
        # 3. Physical range verification: filter negative sensor noise to NaN
        sanitized = check_and_filter_ranges(normalized)
        return sanitized
    else:
        raise ValueError(
            f"Unsupported dataset_type: '{dataset_type}'. Currently supported types: 'air_quality'"
        )
