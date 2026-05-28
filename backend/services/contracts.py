from __future__ import annotations

from datetime import date

import pandas as pd
import requests
from sqlalchemy.orm import Session

from models import Contract
from services.timegate import filter_by_cutoff


USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def _contracts_from_db(db: Session) -> pd.DataFrame:
    rows = db.query(Contract).all()
    return pd.DataFrame(
        [
            {
                "id": row.id,
                "ticker": row.ticker,
                "company": row.company,
                "award_date": row.award_date,
                "amount": row.amount,
                "agency": row.agency,
            }
            for row in rows
        ]
    )


def get_contracts(db: Session, cutoff_date: str | date, use_live: bool = True) -> pd.DataFrame:
    return filter_by_cutoff(_contracts_from_db(db), cutoff_date, "award_date")
