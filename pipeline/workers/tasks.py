from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from pipeline.pipeline import clean_dataframe, parse_file


def process_file_task(
    file_path: Union[str, Path],
    dataset_type: str = "air_quality",
    file_type: Optional[str] = None,
    **kwargs,
) -> pd.DataFrame:
    """Execute the complete pure pipeline on a single file.

    Chains parse_file and clean_dataframe in memory without database side-effects.

    Args:
        file_path (Union[str, Path]): Path to the raw data file.
        dataset_type (str): Type of environmental dataset ('air_quality').
        file_type (Optional[str]): Explicit file extension/type.
        **kwargs: Additional parsing keyword arguments.

    Returns:
        pd.DataFrame: Standardized, cleaned DataFrame.
    """
    raw_df = parse_file(file_path=file_path, file_type=file_type, **kwargs)
    return clean_dataframe(df=raw_df, dataset_type=dataset_type)


def process_batch_task(
    file_paths: List[Union[str, Path]],
    dataset_type: str = "air_quality",
    **kwargs,
) -> Dict[str, pd.DataFrame]:
    """Execute the pure pipeline over a batch of files in memory.

    Args:
        file_paths (List[Union[str, Path]]): List of file paths to process.
        dataset_type (str): Type of environmental dataset ('air_quality').
        **kwargs: Additional parsing keyword arguments.

    Returns:
        Dict[str, pd.DataFrame]: Mapping of file path string to cleaned DataFrame.
    """
    results: Dict[str, pd.DataFrame] = {}
    for path in file_paths:
        results[str(path)] = process_file_task(
            file_path=path, dataset_type=dataset_type, **kwargs
        )
    return results
