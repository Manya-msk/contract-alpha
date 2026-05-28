from __future__ import annotations

import contextlib
from datetime import date
import hashlib
import io
import logging

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta


logger = logging.getLogger(__name__)

SPY_MOCK_ANNUAL_RETURN = 0.18


def _mock_annual_return(ticker: str) -> float:
    seed = int(hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)
    return ((seed % 90) - 10) / 100


def _fallback_series(tickers: list[str], cutoff: date, horizon_months: int) -> dict:
    end = cutoff + relativedelta(months=horizon_months)
    rows = []
    horizon_scale = horizon_months / 12
    portfolio_target_return = (
        sum(_mock_annual_return(ticker) for ticker in tickers) / max(len(tickers), 1)
    ) * horizon_scale
    spy_target_return = SPY_MOCK_ANNUAL_RETURN * horizon_scale
    for idx in range(horizon_months + 1):
        point_date = cutoff + relativedelta(months=idx)
        fraction = idx / max(horizon_months, 1)
        rows.append(
            {
                "date": point_date.isoformat(),
                "portfolio": round((1 + portfolio_target_return * fraction) * 100, 2),
                "spy": round((1 + spy_target_return * fraction) * 100, 2),
            }
        )
    portfolio_return = (rows[-1]["portfolio"] / rows[0]["portfolio"]) - 1
    spy_return = (rows[-1]["spy"] / rows[0]["spy"]) - 1
    return {
        "start_date": cutoff.isoformat(),
        "end_date": end.isoformat(),
        "portfolio_return": round(portfolio_return, 4),
        "spy_return": round(spy_return, 4),
        "alpha": round(portfolio_return - spy_return, 4),
        "series": rows,
        "source": "mock_fallback",
    }


def _download_end_exclusive(end: date) -> str:
    return (end + relativedelta(days=1)).isoformat()


def _close_series_from_download(data: pd.DataFrame, symbol: str) -> pd.Series | None:
    if data is None or data.empty:
        return None

    symbol = symbol.upper()
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            close = data["Close"]
        elif "Adj Close" in data.columns.get_level_values(0):
            close = data["Adj Close"]
        else:
            return None
        if isinstance(close, pd.Series):
            return close.rename(symbol)
        if symbol in close.columns:
            return close[symbol].rename(symbol)
        if len(close.columns) == 1:
            return close.iloc[:, 0].rename(symbol)
        return None

    if "Close" in data.columns:
        return data["Close"].rename(symbol)
    if len(data.columns) == 1:
        return data.iloc[:, 0].rename(symbol)
    return None


def _download_ticker_close(symbol: str, start: date, end: date) -> pd.Series | None:
    symbol = symbol.upper()
    start_s = start.isoformat()
    end_s = _download_end_exclusive(end)

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            batch = yf.download(
                symbol,
                start=start_s,
                end=end_s,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            series = _close_series_from_download(batch, symbol)
            if series is not None and not series.empty:
                return series.dropna()
        except Exception:
            pass

        try:
            history = yf.Ticker(symbol).history(
                start=start_s,
                end=end_s,
                auto_adjust=True,
            )
            if history is not None and not history.empty and "Close" in history.columns:
                return history["Close"].rename(symbol).dropna()
        except Exception:
            pass

    return None


def _download_portfolio_closes(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    columns: dict[str, pd.Series] = {}
    for ticker in tickers:
        series = _download_ticker_close(ticker, start, end)
        if series is not None and not series.empty:
            columns[ticker] = series

    if not columns:
        return pd.DataFrame()

    prices = pd.DataFrame(columns)
    prices.index = pd.to_datetime(prices.index)
    return prices.sort_index().ffill().dropna(how="all")


def _build_indexed_series(prices: pd.DataFrame, portfolio_cols: list[str]) -> pd.DataFrame:
    """Equal-weight portfolio and SPY indexed to 100 at the first shared date."""
    normalized = prices / prices.iloc[0] * 100
    normalized["portfolio"] = normalized[portfolio_cols].mean(axis=1)
    return normalized[["portfolio", "SPY"]]


def _chart_rows(indexed: pd.DataFrame) -> list[dict]:
    chart = indexed
    if len(chart) > 180:
        chart = chart.resample("W-FRI").last().dropna()

    return [
        {
            "date": index.date().isoformat(),
            "portfolio": round(float(row["portfolio"]), 2),
            "spy": round(float(row["SPY"]), 2),
        }
        for index, row in chart.iterrows()
    ]


def _returns_from_indexed_line(indexed: pd.DataFrame) -> tuple[float, float, dict]:
    """Returns are derived from the same portfolio/SPY lines sent to the chart."""
    chart = indexed
    if len(chart) > 180:
        chart = chart.resample("W-FRI").last().dropna()

    start_portfolio = float(chart["portfolio"].iloc[0])
    end_portfolio = float(chart["portfolio"].iloc[-1])
    start_spy = float(chart["SPY"].iloc[0])
    end_spy = float(chart["SPY"].iloc[-1])

    portfolio_return = (end_portfolio / start_portfolio) - 1
    spy_return = (end_spy / start_spy) - 1

    debug = {
        "portfolio_start": round(start_portfolio, 4),
        "portfolio_end": round(end_portfolio, 4),
        "portfolio_return_pct": round(portfolio_return * 100, 2),
        "spy_start": round(start_spy, 4),
        "spy_end": round(end_spy, 4),
        "spy_return_pct": round(spy_return * 100, 2),
        "alpha_pct": round((portfolio_return - spy_return) * 100, 2),
        "chart_start_date": chart.index[0].date().isoformat(),
        "chart_end_date": chart.index[-1].date().isoformat(),
    }
    return portfolio_return, spy_return, debug


def run_backtest(tickers: list[str], cutoff_date: str | date, horizon_months: int = 12) -> dict:
    cutoff = pd.to_datetime(cutoff_date).date()
    end = cutoff + relativedelta(months=horizon_months)
    requested = sorted({ticker.upper() for ticker in tickers if ticker})

    if not requested:
        return _fallback_series([], cutoff, horizon_months)

    portfolio_prices = _download_portfolio_closes(requested, cutoff, end)
    spy_prices = _download_ticker_close("SPY", cutoff, end)

    if portfolio_prices.empty or spy_prices is None or spy_prices.empty:
        return _fallback_series(requested, cutoff, horizon_months)

    prices = portfolio_prices.copy()
    prices["SPY"] = spy_prices
    prices = prices.sort_index().ffill().dropna(how="all")

    portfolio_cols = [col for col in prices.columns if col != "SPY"]
    if not portfolio_cols:
        return _fallback_series(requested, cutoff, horizon_months)

    indexed = _build_indexed_series(prices, portfolio_cols)
    portfolio_return, spy_return, debug = _returns_from_indexed_line(indexed)
    rows = _chart_rows(indexed)

    if not rows:
        return _fallback_series(requested, cutoff, horizon_months)

    logger.info(
        "Backtest returns (%s to %s, %s months): portfolio start=%.2f end=%.2f return=%.2f%% | "
        "SPY start=%.2f end=%.2f return=%.2f%% | alpha=%.2f%% | tickers=%s",
        debug["chart_start_date"],
        debug["chart_end_date"],
        horizon_months,
        debug["portfolio_start"],
        debug["portfolio_end"],
        debug["portfolio_return_pct"],
        debug["spy_start"],
        debug["spy_end"],
        debug["spy_return_pct"],
        debug["alpha_pct"],
        portfolio_cols,
    )

    return {
        "start_date": cutoff.isoformat(),
        "end_date": end.isoformat(),
        "portfolio_return": round(portfolio_return, 4),
        "spy_return": round(spy_return, 4),
        "alpha": round(portfolio_return - spy_return, 4),
        "series": rows,
        "source": "yfinance",
        "tickers_used": portfolio_cols,
        "debug": debug,
    }
