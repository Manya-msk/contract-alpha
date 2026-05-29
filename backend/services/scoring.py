from __future__ import annotations

import statistics
from datetime import date
from math import log1p
from typing import Optional

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session


def _growth(current: float, previous: float) -> float:
    if previous <= 0 and current <= 0:
        return 0.0
    if previous <= 0:
        return 1.0
    return max(min((current - previous) / previous, 2.0), -0.5)


def _signal(score: float) -> str:
    if score > 0.35:
        return "BUY"
    if score > 0.15:
        return "HOLD"
    return "AVOID"


def score_companies(
    contracts: pd.DataFrame,
    jobs: pd.DataFrame,
    cutoff_date: str | date,
    horizon_months: int = 12,
    sentiment_scores: dict[str, float] | None = None,
    pipeline_data: dict[str, dict] | None = None,
    db: Optional[Session] = None,
) -> list[dict]:
    from models import HiringSignal  # local import to avoid circular deps

    cutoff = pd.to_datetime(cutoff_date).date()
    window_months = max(int(horizon_months), 1)
    sentiment_scores = sentiment_scores or {}
    pipeline_data = pipeline_data or {}
    tickers = sorted(set(contracts.get("ticker", [])) | set(jobs.get("ticker", [])))
    totals = {
        ticker: float(contracts.loc[contracts["ticker"] == ticker, "amount"].sum())
        for ticker in tickers
        if not contracts.empty
    }
    max_log_awards = max([log1p(value) for value in totals.values()] or [1.0])

    # Log-normalize pipeline opportunity counts so a 50-notice giant doesn't dominate.
    pipeline_counts = {t: float(pipeline_data.get(t, {}).get("count", 0)) for t in tickers}
    max_log_pipeline = max([log1p(v) for v in pipeline_counts.values()] or [1.0])

    # Load real hiring scores from DB if available
    real_hiring: dict[str, float] = {}
    if db is not None:
        for row in db.query(HiringSignal).all():
            real_hiring[row.ticker] = float(row.hiring_score)

    # Pre-compute contract growth for all tickers so we can rank relatively.
    # When seeded data creates universal decline, absolute growth carries no signal —
    # relative ranking (vs median) preserves differentiation.
    _cs = cutoff - relativedelta(months=window_months)
    _ps = cutoff - relativedelta(months=window_months * 2)
    raw_growths: dict[str, float] = {}
    for _ticker in tickers:
        _tc = contracts[contracts["ticker"] == _ticker] if not contracts.empty else pd.DataFrame()
        if not _tc.empty:
            _dates = pd.to_datetime(_tc["award_date"]).dt.date
            _ca = float(_tc.loc[(_dates > _cs) & (_dates <= cutoff), "amount"].sum())
            _pa = float(_tc.loc[(_dates > _ps) & (_dates <= cutoff), "amount"].sum())
        else:
            _ca = _pa = 0.0
        raw_growths[_ticker] = _growth(_ca, _pa)

    _gvals = list(raw_growths.values())
    growth_median = statistics.median(_gvals) if _gvals else 0.0
    growth_spread = max(max(abs(v - growth_median) for v in _gvals), 0.01) if _gvals else 1.0

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

        contract_growth = raw_growths.get(ticker, 0.0)
        # Normalize relative to the peer group so the signal is meaningful even when
        # all companies are declining (seeded data) or all are growing (boom cycle).
        relative_growth = (contract_growth - growth_median) / growth_spread

        # Use real hiring score from DB if available, else fall back to synthetic
        if ticker in real_hiring:
            hiring_growth = real_hiring[ticker]
        else:
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
            hiring_growth = max(hiring_growth, 0.0)

        award_size = log1p(totals.get(ticker, 0.0)) / max_log_awards if max_log_awards else 0.0

        sentiment = float(sentiment_scores.get(ticker, 0.0))
        sentiment_normalized = (sentiment + 1) / 2

        # Pipeline signal: log-normalized count of pre-award SAM.gov notices
        # mentioning this company in the lookback window.
        pipeline_info = pipeline_data.get(ticker, {}) if pipeline_data else {}
        pipeline_count = float(pipeline_info.get("count", 0))
        pipeline_signal = log1p(pipeline_count) / max_log_pipeline if max_log_pipeline else 0.0

        total = totals.get(ticker, 0)
        volume_bonus = 0.15 if total > 10_000_000_000 else (0.10 if total > 5_000_000_000 else 0.0)
        momentum_bonus = 0.10 if contract_growth > 0 else 0.0
        # Rebalanced weights with pipeline as a 6th signal (25%):
        # contract_growth 25%, hiring 15%, award_size 25%, sentiment 10%, pipeline 25%
        score = (
            (0.25 * max(relative_growth, -1.0))
            + (0.15 * hiring_growth)
            + (0.25 * award_size)
            + (0.10 * sentiment_normalized)
            + (0.25 * pipeline_signal)
            + volume_bonus
            + momentum_bonus
        )

        results.append(
            {
                "ticker": ticker,
                "company": company,
                "score": round(score, 3),
                "signal": _signal(score),
                "contract_growth": round(contract_growth, 3),
                "hiring_growth": round(hiring_growth, 3),
                "award_size": round(award_size, 3),
                "sentiment_score": round(sentiment, 3),
                "pipeline_count": int(pipeline_count),
                "pipeline_signal": round(pipeline_signal, 3),
                "pipeline_top_notice": pipeline_info.get("top_notice", ""),
                "pipeline_top_agency": pipeline_info.get("top_agency", ""),
                "pipeline_top_url": pipeline_info.get("top_notice_url", ""),
                "pipeline_top_deadline": pipeline_info.get("top_deadline", ""),
                "total_awards": round(totals.get(ticker, 0.0), 2),
                "trigger_award": trigger_award,
            }
        )

    return sorted(results, key=lambda row: row["score"], reverse=True)
