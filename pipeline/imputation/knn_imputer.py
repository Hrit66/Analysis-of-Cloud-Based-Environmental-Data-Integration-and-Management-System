from typing import List, Optional
import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer


def impute_knn(
    data: pd.DataFrame,
    columns: Optional[List[str]] = None,
    n_neighbors: int = 5,
    **kwargs,
) -> pd.DataFrame:
    """Impute missing numeric values using k-Nearest Neighbors.

    Args:
        data (pd.DataFrame): Input DataFrame.
        columns (Optional[List[str]]): Specific numeric columns to impute. If None,
            imputes all numeric columns.
        n_neighbors (int): Number of neighboring samples to use for imputation.
        **kwargs: Additional keyword arguments passed to `sklearn.impute.KNNImputer`.

    Returns:
        pd.DataFrame: DataFrame with missing values imputed in a new copy.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"Expected data to be a pandas DataFrame, got {type(data).__name__}")

    df = data.copy()
    if columns is None:
        target_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    else:
        target_cols = [
            col for col in columns if col in df.columns and np.issubdtype(df[col].dtype, np.number)
        ]

    if not target_cols or df[target_cols].isna().sum().sum() == 0:
        return df

    imputer = KNNImputer(n_neighbors=n_neighbors, **kwargs)
    df[target_cols] = imputer.fit_transform(df[target_cols])
    return df
