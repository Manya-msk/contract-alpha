from __future__ import annotations

from datetime import date
import hashlib

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from models import Job
from services.timegate import filter_by_cutoff


def get_jobs(db: Session, cutoff_date: str | date) -> pd.DataFrame:
    rows = db.query(Job).all()
    df = pd.DataFrame(
        [
            {
                "id": row.id,
                "ticker": row.ticker,
                "date": row.date,
                "open_roles": row.open_roles,
                "mfg_roles": row.mfg_roles,
                "eng_roles": row.eng_roles,
            }
            for row in rows
        ]
    )
    return filter_by_cutoff(df, cutoff_date, "date")


def generate_hiring_signals(tickers: list[str], cutoff_date: str | date, horizon_months: int) -> pd.DataFrame:
    cutoff = pd.to_datetime(cutoff_date).date()
    rows = []
    months = max(int(horizon_months) * 2, 12)
    for ticker in sorted(set(tickers)):
        seed = int(hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)
        base_roles = 120 + (seed % 900)
        trend = ((seed % 17) - 5) / 100
        for offset in range(months, -1, -1):
            point_date = cutoff - relativedelta(months=offset)
            age = months - offset
            open_roles = int(base_roles * (1 + trend * age) * (0.92 + ((seed + age) % 7) * 0.025))
            rows.append(
                {
                    "ticker": ticker,
                    "date": point_date,
                    "open_roles": max(open_roles, 1),
                    "mfg_roles": max(int(open_roles * 0.24), 1),
                    "eng_roles": max(int(open_roles * 0.34), 1),
                }
            )
    return pd.DataFrame(rows)
