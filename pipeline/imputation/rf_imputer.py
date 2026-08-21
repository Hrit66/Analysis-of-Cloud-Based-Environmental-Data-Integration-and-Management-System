from typing import List, Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor


def impute_rf(
    data: pd.DataFrame,
    columns: Optional[List[str]] = None,
    n_estimators: int = 50,
    random_state: int = 42,
) -> pd.DataFrame:
    """Impute missing numeric values using iterative Random Forest regression.

    Args:
        data (pd.DataFrame): Input DataFrame.
        columns (Optional[List[str]]): Specific numeric columns to impute.
        n_estimators (int): Number of trees in the random forest.
        random_state (int): Random seed for reproducibility.

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

    for col in target_cols:
        if df[col].isna().sum() == 0:
            continue
        missing_mask = df[col].isna()
        features = [c for c in target_cols if c != col and df[c].isna().sum() == 0]
        if not features:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val if pd.notna(median_val) else 0.0)
            continue

        train_data = df.loc[~missing_mask]
        test_data = df.loc[missing_mask]

        if train_data.empty:
            continue

        rf = RandomForestRegressor(n_estimators=n_estimators, random_state=random_state)
        rf.fit(train_data[features], train_data[col])
        df.loc[missing_mask, col] = rf.predict(test_data[features])

    return df
