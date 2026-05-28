from __future__ import annotations

from datetime import date
import re
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf
from dateutil.relativedelta import relativedelta


USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]
US_EXCHANGES = {"NYQ", "NMS", "NGM", "NCM", "ASE", "PCX", "NYSE", "NASDAQ", "AMEX"}
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ContractAlpha/1.0)"}
PRIVATE_MARKERS = {
    " LLC",
    " JV",
    " JOINT VENTURE",
    " UNIVERSITY",
    " STATE OF ",
    " CITY OF ",
    " COUNTY",
    " TRIBE",
    " GOVERNMENT",
}

RECIPIENT_SEARCH_HINTS: dict[str, list[str]] = {
    "RAYTHEON": ["Raytheon Technologies Corporation", "RTX Corporation"],
    "SIKORSKY": ["Lockheed Martin Corporation"],
    "NORTHROP GRUMMAN": ["Northrop Grumman Corporation"],
    "ELECTRIC BOAT": ["General Dynamics Corporation"],
    "BELL TEXTRON": ["Textron Inc"],
    "HUNTINGTON INGALLS": ["Huntington Ingalls Industries Inc"],
    "BOOZ ALLEN": ["Booz Allen Hamilton Holding Corporation"],
    "GENERAL DYNAMICS": ["General Dynamics Corporation"],
    "L3HARRIS": ["L3Harris Technologies Inc"],
    "BAE SYSTEMS": ["BAE Systems plc"],
}

FALLBACK_PUBLIC_COMPANIES = [
    ("BA", "Boeing Co."),
    ("NOC", "Northrop Grumman Corp."),
    ("GD", "General Dynamics Corp."),
    ("HII", "Huntington Ingalls Industries Inc."),
    ("TXT", "Textron Inc."),
    ("LHX", "L3Harris Technologies Inc."),
    ("TDG", "TransDigm Group Inc."),
    ("MRCY", "Mercury Systems Inc."),
    ("AVAV", "AeroVironment Inc."),
    ("KTOS", "Kratos Defense & Security Solutions Inc."),
    ("BWXT", "BWX Technologies Inc."),
    ("TDY", "Teledyne Technologies Inc."),
    ("HON", "Honeywell International Inc."),
    ("GE", "GE Aerospace"),
    ("LDOS", "Leidos Holdings Inc."),
    ("CACI", "CACI International Inc."),
    ("SAIC", "Science Applications International Corp."),
    ("KBR", "KBR Inc."),
    ("J", "Jacobs Solutions Inc."),
    ("ACM", "AECOM"),
    ("FLR", "Fluor Corp."),
    ("PWR", "Quanta Services Inc."),
    ("DE", "Deere & Co."),
    ("CMI", "Cummins Inc."),
    ("OSK", "Oshkosh Corp."),
    ("XOM", "Exxon Mobil Corp."),
    ("CVX", "Chevron Corp."),
]


def _clean_company_name(value: str) -> str:
    name = re.sub(r"\s+", " ", value or "").strip()
    name = re.sub(
        r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED)\.?$",
        "",
        name,
        flags=re.I,
    )
    return name.strip(" ,.-").upper()


def _search_name_variants(company: str, recipient_name: str) -> list[str]:
    variants = []
    upper_company = company.upper()
    for key, hints in RECIPIENT_SEARCH_HINTS.items():
        if key in upper_company:
            variants.extend(hints)
    for raw in (company, recipient_name):
        cleaned = re.sub(r"\s+", " ", raw or "").strip()
        if not cleaned:
            continue
        variants.append(cleaned)
        stripped = re.sub(r"^(THE|A)\s+", "", cleaned, flags=re.I).strip()
        if stripped and stripped not in variants:
            variants.append(stripped)
        title = cleaned.title()
        if title not in variants:
            variants.append(title)
    return variants


def _is_likely_private_or_public_sector(name: str) -> bool:
    upper = f" {name.upper()} "
    return any(marker in upper for marker in PRIVATE_MARKERS)


def _name_match_score(query: str, quote: dict) -> float:
    query_tokens = {token for token in re.split(r"[^A-Z0-9]+", query.upper()) if len(token) > 2}
    if not query_tokens:
        return 0.0
    name = str(quote.get("shortname") or quote.get("longname") or "").upper()
    name_tokens = {token for token in re.split(r"[^A-Z0-9]+", name) if len(token) > 2}
    overlap = len(query_tokens & name_tokens)
    return overlap / len(query_tokens)


def _is_us_public_equity(quote: dict) -> bool:
    symbol = str(quote.get("symbol") or "").upper()
    # Keep US-listed equities even if they use '-' share-class notation (e.g. BRK-B).
    if not symbol or "." in symbol or symbol.endswith("=F"):
        return False
    if quote.get("quoteType") not in {None, "EQUITY"}:
        return False
    exchange = str(quote.get("exchange") or quote.get("exchDisp") or "").upper()
    if exchange not in US_EXCHANGES:
        return False
    name = str(quote.get("shortname") or quote.get("longname") or "").upper()
    if any(marker in name for marker in (" ADR", "ETF", "FUND", "WARRANT")):
        return False
    return True


def _yahoo_search_quotes(company: str) -> list[dict]:
    try:
        if hasattr(yf, "Search"):
            search = yf.Search(company, max_results=8)
            quotes = getattr(search, "quotes", None) or []
            if quotes:
                return list(quotes)
    except Exception:
        pass

    try:
        url = (
            "https://query2.finance.yahoo.com/v1/finance/search"
            f"?q={quote_plus(company)}&quotes_count=8&news_count=0"
        )
        response = requests.get(url, timeout=8, headers=YAHOO_HEADERS)
        response.raise_for_status()
        return response.json().get("quotes", []) or []
    except Exception:
        return []


def _has_price_history(symbol: str) -> bool:
    try:
        history = yf.Ticker(symbol).history(period="1mo", interval="1d")
        return not history.empty
    except Exception:
        return False


def _search_yahoo_company(company: str, recipient_name: str = "") -> dict | None:
    best_match: dict | None = None
    # USAspending recipient names can be noisy; accept weaker matches as long as the ticker is US-listed
    # and has recent price history.
    min_score = 0.2

    for candidate in _search_name_variants(company, recipient_name):
        query_key = _clean_company_name(company) or company.upper()
        for quote in _yahoo_search_quotes(candidate):
            if not _is_us_public_equity(quote):
                continue
            score = _name_match_score(query_key, quote)
            if score < min_score:
                continue
            symbol = str(quote.get("symbol") or "").upper()
            if not _has_price_history(symbol):
                continue
            name = str(quote.get("shortname") or quote.get("longname") or candidate)
            if not best_match or score > best_match["match_score"]:
                best_match = {"ticker": symbol, "company": name, "match_score": score}

    if best_match:
        return {"ticker": best_match["ticker"], "company": best_match["company"]}
    return None


def _extract_awards(results: list[dict]) -> pd.DataFrame:
    rows = []
    seen_award_ids: set[str] = set()
    for item in results:
        award_id = str(item.get("Award ID") or item.get("generated_internal_id") or "")
        if award_id and award_id in seen_award_ids:
            continue
        if award_id:
            seen_award_ids.add(award_id)

        recipient = item.get("Recipient Name") or item.get("recipient_name") or ""
        amount = item.get("Award Amount") or item.get("award_amount") or 0
        award_date = item.get("Start Date") or item.get("start_date")
        if not recipient or not award_date:
            continue
        rows.append(
            {
                "company_key": _clean_company_name(str(recipient)),
                "recipient_name": recipient,
                "award_date": award_date,
                "amount": float(amount or 0),
                "agency": item.get("Awarding Agency") or item.get("awarding_agency") or "Unknown",
                "trigger_award": (
                    f"{recipient} - {item.get('Awarding Agency') or 'US government'}"
                    f" - ${float(amount or 0):,.0f}"
                ),
            }
        )
    return pd.DataFrame(rows)


def _lookback_months(horizon_months: int) -> int:
    return max(int(horizon_months) * 3, 36)


def fetch_usaspending_awards(cutoff_date: str | date, horizon_months: int) -> pd.DataFrame:
    cutoff = pd.to_datetime(cutoff_date).date()
    lookback = _lookback_months(horizon_months)
    start = cutoff - relativedelta(months=lookback)
    all_results: list[dict] = []

    # Pull more pages so we capture more unique recipients (targeting diversified ticker coverage).
    for page in range(1, 16):
        payload = {
            "filters": {
                "time_period": [{"start_date": start.isoformat(), "end_date": cutoff.isoformat()}],
                "award_type_codes": CONTRACT_AWARD_TYPES,
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Start Date", "Awarding Agency"],
            "page": page,
            "limit": 100,
            "sort": "Award Amount",
            "order": "desc",
        }
        try:
            response = requests.post(USASPENDING_URL, json=payload, timeout=30)
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                break
            all_results.extend(results)
            # Safety stop: enough awards to cover 200+ unique recipients.
            if len(all_results) >= 1500:
                break
        except Exception:
            # Keep partial results instead of failing discovery entirely.
            break

    awards = _extract_awards(all_results)
    if awards.empty:
        return awards

    award_dates = pd.to_datetime(awards["award_date"], errors="coerce").dt.date
    awards = awards.loc[(award_dates >= start) & (award_dates <= cutoff)].copy()
    awards = awards[~awards["company_key"].map(_is_likely_private_or_public_sector)]
    return awards


def fetch_usaspending_top_recipients(
    cutoff_date: str | date, horizon_months: int, top_n: int = 200
) -> tuple[pd.DataFrame, int]:
    awards = fetch_usaspending_awards(cutoff_date, horizon_months)
    if awards.empty:
        return awards, 0

    found_count = int(awards["company_key"].nunique())
    totals = (
        awards.groupby("company_key", as_index=False)
        .agg(
            amount=("amount", "sum"),
            award_date=("award_date", "max"),
            agency=("agency", "first"),
            recipient_name=("recipient_name", "first"),
            trigger_award=("trigger_award", "first"),
        )
        .sort_values("amount", ascending=False)
        .head(top_n)
    )
    return totals, found_count


def discover_public_contract_companies(cutoff_date: str | date, horizon_months: int) -> dict:
    source = "usaspending_yfinance"
    found_before_filter = 0
    awards = pd.DataFrame()
    recipients = pd.DataFrame()
    try:
        awards = fetch_usaspending_awards(cutoff_date, horizon_months)
        if not awards.empty:
            found_before_filter = int(awards["company_key"].nunique())
            recipients = (
                awards.groupby("company_key", as_index=False)
                .agg(
                    amount=("amount", "sum"),
                    recipient_name=("recipient_name", "first"),
                )
                .sort_values("amount", ascending=False)
            )
    except Exception:
        awards = pd.DataFrame()
        recipients = pd.DataFrame()
        found_before_filter = 0

    records: list[dict] = []
    ticker_by_company: dict[str, dict] = {}

    if not recipients.empty:
        for row in recipients.head(260).to_dict(orient="records"):
            company_key = str(row["company_key"])
            mapping = _search_yahoo_company(company_key, str(row.get("recipient_name", company_key)))
            if not mapping:
                continue
            ticker_by_company[company_key] = mapping
            if len(ticker_by_company) >= 200:
                break

    if not awards.empty and ticker_by_company:
        for award in awards.to_dict(orient="records"):
            company_key = str(award["company_key"])
            mapping = ticker_by_company.get(company_key)
            if not mapping:
                continue
            records.append(
                {
                    "ticker": mapping["ticker"],
                    "company": mapping["company"],
                    "award_date": award["award_date"],
                    "amount": award["amount"],
                    "agency": award["agency"],
                    "trigger_award": award["trigger_award"],
                }
            )

    if not records:
        source = "fallback_universe"
        cutoff = pd.to_datetime(cutoff_date).date()
        lookback = _lookback_months(horizon_months)
        for idx, (ticker, company) in enumerate(FALLBACK_PUBLIC_COMPANIES):
            for offset in range(lookback, -1, -max(horizon_months // 3, 1)):
                point_date = cutoff - relativedelta(months=offset)
                amount = 2_500_000 + (idx * 175_000) + ((lookback - offset) * 40_000)
                records.append(
                    {
                        "ticker": ticker,
                        "company": company,
                        "award_date": point_date.isoformat(),
                        "amount": float(amount),
                        "agency": "US government fallback",
                        "trigger_award": f"{company} appeared in fallback public defense/infrastructure universe",
                    }
                )

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(["ticker", "award_date"])
        df = df.drop_duplicates(subset=["ticker", "award_date", "amount"], keep="first")

    return {
        "contracts": df,
        "companies_found": found_before_filter,
        "companies_after_filter": int(df["ticker"].nunique()) if not df.empty else 0,
        "discovery_source": source,
    }
