from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import SessionLocal, init_db
from seed import seed
from services.backtest import run_backtest
from services.config import load_env
from services.contracts import get_contracts
from services.discovery import discover_public_contract_companies
from services.evidence import get_contract_evidence
from services.jobs import generate_hiring_signals, get_jobs
from services.scoring import score_companies


load_env()
app = FastAPI(title="ContractAlpha API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.post("/seed")
def seed_database() -> dict:
    seed()
    return {"status": "seeded"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


class SimulationRequest(BaseModel):
    cutoff_date: date
    horizon_months: int = Field(default=12, ge=1, le=36)
    use_live_contracts: bool = True


def build_simulation(
    db: Session,
    cutoff_date: date,
    horizon_months: int,
    use_live_contracts: bool = False,
) -> dict:
    discovery = discover_public_contract_companies(cutoff_date, horizon_months) if use_live_contracts else {}
    contracts = discovery.get("contracts") if discovery else get_contracts(db, cutoff_date, use_live=False)
    tickers = [] if contracts is None or contracts.empty else contracts["ticker"].dropna().astype(str).tolist()
    jobs = generate_hiring_signals(tickers, cutoff_date, horizon_months)
    scores = score_companies(contracts, jobs, cutoff_date, horizon_months)
    evidence = get_contract_evidence(db, scores, cutoff_date.year, max_calls=5)
    scores = [
        {
            **row,
            "evidence": evidence.get(
                row["ticker"],
                {"title": "No evidence available", "url": "", "snippet": "", "source": "none"},
            ),
        }
        for row in scores
    ]
    buys = [row["ticker"] for row in scores if row["signal"] == "BUY"] or [row["ticker"] for row in scores[:3]]
    backtest = run_backtest(buys, cutoff_date, horizon_months)
    return {
        "cutoff_date": cutoff_date.isoformat(),
        "horizon_months": horizon_months,
        "scores": scores,
        "selected_tickers": buys,
        "backtest": backtest,
        "visible_rows": {
            "contracts": int(len(contracts)),
            "jobs": int(len(jobs)),
        },
        "discovery": {
            "companies_found": int(discovery.get("companies_found", len(tickers))) if discovery else len(tickers),
            "companies_after_filter": int(discovery.get("companies_after_filter", len(tickers))) if discovery else len(tickers),
            "source": discovery.get("discovery_source", "seeded_db") if discovery else "seeded_db",
        },
    }


@app.post("/simulate")
def simulate(payload: SimulationRequest, db: Session = Depends(get_db)) -> dict:
    return build_simulation(
        db=db,
        cutoff_date=payload.cutoff_date,
        horizon_months=payload.horizon_months,
        use_live_contracts=payload.use_live_contracts,
    )


@app.get("/signals")
def signals(
    cutoff_date: date = Query(...),
    horizon_months: int = Query(12, ge=1, le=36),
    use_live_contracts: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    return build_simulation(
        db=db,
        cutoff_date=cutoff_date,
        horizon_months=horizon_months,
        use_live_contracts=use_live_contracts,
    )


@app.get("/contracts")
def contracts(cutoff_date: date = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    df = get_contracts(db, cutoff_date, use_live=False)
    if df.empty:
        return []
    df = df.sort_values("award_date", ascending=False)
    df["award_date"] = df["award_date"].astype(str)
    return df.to_dict(orient="records")


@app.get("/jobs")
def jobs(cutoff_date: date = Query(...), db: Session = Depends(get_db)) -> list[dict]:
    df = get_jobs(db, cutoff_date)
    if df.empty:
        return []
    df = df.sort_values("date", ascending=False)
    df["date"] = df["date"].astype(str)
    return df.to_dict(orient="records")
