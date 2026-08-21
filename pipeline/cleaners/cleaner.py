import pandas as pd


def clean_data(data: pd.DataFrame) -> pd.DataFrame:
    """Clean a pandas DataFrame by removing empty records, duplicates, and cleaning headers.

    Performs the following cleaning operations on a copy of the input DataFrame:
    1. Strips leading and trailing whitespace from column names.
    2. Drops rows where all values are NA / empty.
    3. Drops columns where all values are NA / empty.
    4. Drops duplicate rows.

    Args:
        data (pd.DataFrame): The DataFrame to clean.

    Returns:
        pd.DataFrame: A new cleaned DataFrame.

    Raises:
        TypeError: If `data` is not a pandas DataFrame.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"Expected data to be a pandas DataFrame, got {type(data).__name__}")

    df = data.copy()

    # Strip leading and trailing whitespace from column names
    df.columns = [col.strip() if isinstance(col, str) else col for col in df.columns]

    # Remove completely empty rows and columns
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")

    # Remove duplicate rows
    df = df.drop_duplicates()

    return df
