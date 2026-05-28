from __future__ import annotations

from datetime import date
import hashlib

from dateutil.relativedelta import relativedelta

from models import Contract, Job, SessionLocal, init_db
from services.discovery import FALLBACK_PUBLIC_COMPANIES


AGENCIES = [
    "Department of Defense",
    "Department of Energy",
    "Department of Homeland Security",
    "Department of Transportation",
    "Department of Commerce",
]


def _seed_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        db.query(Contract).delete()
        db.query(Job).delete()
        start = date(2021, 1, 1)

        for month in range(36):
            current = start + relativedelta(months=month)
            for idx, (ticker, company) in enumerate(FALLBACK_PUBLIC_COMPANIES):
                seed_value = _seed_int(ticker)
                base_contract = 24_000_000 + (seed_value % 115_000_000)
                trend = ((seed_value % 13) - 4) / 100
                late_cycle = 0.65 if (seed_value + month) % 7 > 4 and month >= 18 else 0
                momentum = max(0.35, 1 + (trend * month) + late_cycle)
                amount = base_contract * momentum * (0.74 + ((month + idx) % 6) * 0.08)
                db.add(
                    Contract(
                        ticker=ticker,
                        company=company,
                        award_date=current + relativedelta(days=(month * 3 + idx) % 24),
                        amount=round(amount, 2),
                        agency=AGENCIES[idx % len(AGENCIES)],
                    )
                )

                base_roles = 120 + (seed_value % 900)
                job_trend = ((seed_value % 11) - 3) / 120
                open_roles = int(base_roles * max(0.4, 1 + job_trend * month) * (0.9 + (month % 4) * 0.05))
                db.add(
                    Job(
                        ticker=ticker,
                        date=current + relativedelta(days=14),
                        open_roles=max(open_roles, 1),
                        mfg_roles=max(int(open_roles * 0.24), 1),
                        eng_roles=max(int(open_roles * 0.34), 1),
                    )
                )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seeded ContractAlpha database.")
