from pathlib import Path
from typing import Union
import pandas as pd


def read_json(file_path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """Read a JSON file into a pandas DataFrame.

    Validates that the target file exists before attempting to read.

    Args:
        file_path (Union[str, Path]): Path to the JSON file to be loaded.
        **kwargs: Additional keyword arguments to pass to `pandas.read_json`.

    Returns:
        pd.DataFrame: Loaded dataset as a pandas DataFrame.

    Raises:
        FileNotFoundError: If the specified file does not exist or is not a file.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found at: {file_path}")

    return pd.read_json(path, **kwargs)
