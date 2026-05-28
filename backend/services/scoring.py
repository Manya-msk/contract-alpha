from __future__ import annotations

from datetime import date
from math import log1p

import pandas as pd
from dateutil.relativedelta import relativedelta


def _growth(current: float, previous: float) -> float:
    if previous <= 0 and current <= 0:
        return 0.0
    if previous <= 0:
        return 1.0
    return max(min((current - previous) / previous, 2.0), -1.0)


def _signal(score: float) -> str:
    if score > 0.4:
        return "BUY"
    if score > 0.2:
        return "HOLD"
    return "AVOID"


def score_companies(
    contracts: pd.DataFrame,
    jobs: pd.DataFrame,
    cutoff_date: str | date,
    horizon_months: int = 12,
) -> list[dict]:
    cutoff = pd.to_datetime(cutoff_date).date()
    window_months = max(int(horizon_months), 1)
    tickers = sorted(set(contracts.get("ticker", [])) | set(jobs.get("ticker", [])))
    totals = {
        ticker: float(contracts.loc[contracts["ticker"] == ticker, "amount"].sum())
        for ticker in tickers
        if not contracts.empty
    }
    max_log_awards = max([log1p(value) for value in totals.values()] or [1.0])

    results = []
    for ticker in tickers:
        ticker_contracts = contracts[contracts["ticker"] == ticker].copy() if not contracts.empty else pd.DataFrame()
        ticker_jobs = jobs[jobs["ticker"] == ticker].copy() if not jobs.empty else pd.DataFrame()
        company = (
            str(ticker_contracts["company"].iloc[0])
            if not ticker_contracts.empty and "company" in ticker_contracts
            else ticker
        )
        trigger_award = (
            str(ticker_contracts["trigger_award"].iloc[0])
            if not ticker_contracts.empty and "trigger_award" in ticker_contracts
            else ""
        )

        current_contract_start = cutoff - relativedelta(months=window_months)
        previous_contract_start = cutoff - relativedelta(months=window_months * 2)
        current_awards = (
            ticker_contracts.loc[
                (pd.to_datetime(ticker_contracts["award_date"]).dt.date > current_contract_start)
                & (pd.to_datetime(ticker_contracts["award_date"]).dt.date <= cutoff),
                "amount",
            ].sum()
            if not ticker_contracts.empty
            else 0
        )
        previous_awards = (
            ticker_contracts.loc[
                (pd.to_datetime(ticker_contracts["award_date"]).dt.date > previous_contract_start)
                & (pd.to_datetime(ticker_contracts["award_date"]).dt.date <= current_contract_start),
                "amount",
            ].sum()
            if not ticker_contracts.empty
            else 0
        )
        contract_growth = _growth(float(current_awards), float(previous_awards))

        current_job_start = cutoff - relativedelta(months=window_months)
        previous_job_start = cutoff - relativedelta(months=window_months * 2)
        if not ticker_jobs.empty:
            job_dates = pd.to_datetime(ticker_jobs["date"]).dt.date
            current_jobs = ticker_jobs.loc[
                (job_dates > current_job_start) & (job_dates <= cutoff), "open_roles"
            ].mean()
            previous_jobs = ticker_jobs.loc[
                (job_dates > previous_job_start) & (job_dates <= current_job_start), "open_roles"
            ].mean()
        else:
            current_jobs = previous_jobs = 0
        hiring_growth = _growth(float(current_jobs or 0), float(previous_jobs or 0))
        # Hiring data is synthetic in the MVP. Prevent negative mock swings from dragging scores down.
        hiring_growth = max(hiring_growth, 0.0)

        award_size = log1p(totals.get(ticker, 0.0)) / max_log_awards if max_log_awards else 0.0
        score = (0.4 * contract_growth) + (0.3 * hiring_growth) + (0.3 * award_size)
        results.append(
            {
                "ticker": ticker,
                "company": company,
                "score": round(score, 3),
                "signal": _signal(score),
                "contract_growth": round(contract_growth, 3),
                "hiring_growth": round(hiring_growth, 3),
                "award_size": round(award_size, 3),
                "total_awards": round(totals.get(ticker, 0.0), 2),
                "trigger_award": trigger_award,
            }
        )

    return sorted(results, key=lambda row: row["score"], reverse=True)
