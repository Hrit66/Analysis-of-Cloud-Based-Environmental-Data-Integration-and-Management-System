from typing import Iterable, List
import pandas as pd


def validate_schema(data: pd.DataFrame, required_columns: Iterable[str]) -> bool:
    """Validate that all required columns are present in the pandas DataFrame.

    Args:
        data (pd.DataFrame): The DataFrame to validate.
        required_columns (Iterable[str]): An iterable of column names that must exist in `data`.

    Returns:
        bool: True if all required columns are present.

    Raises:
        TypeError: If `data` is not a pandas DataFrame.
        ValueError: If one or more required columns are missing from `data`.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"Expected data to be a pandas DataFrame, got {type(data).__name__}")

    missing_columns: List[str] = [col for col in required_columns if col not in data.columns]
    if missing_columns:
        raise ValueError(f"Missing required column(s): {', '.join(missing_columns)}")

    return True
