from __future__ import annotations

from datetime import date

import pandas as pd


def filter_by_cutoff(df: pd.DataFrame, cutoff_date: str | date, date_column: str) -> pd.DataFrame:
    """Strictly keep rows visible on or before the cutoff date."""
    if df.empty:
        return df.copy()

    cutoff = pd.to_datetime(cutoff_date).normalize()
    filtered = df.copy()
    filtered[date_column] = pd.to_datetime(filtered[date_column])
    return filtered.loc[filtered[date_column] <= cutoff].copy()
