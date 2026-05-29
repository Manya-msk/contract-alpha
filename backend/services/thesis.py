from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


_thesis_cache: dict[str, str] = {}


def generate_thesis(
    ticker: str,
    company: str,
    contract_growth: float,
    hiring_growth: float,
    award_size: float,
    sentiment_score: float,
    total_awards: float,
    trigger_award: str,
    signal: str,
) -> str:
    cache_key = f"{ticker}:{signal}:{round(contract_growth, 1)}"
    if cache_key in _thesis_cache:
        return _thesis_cache[cache_key]

    api_key = os.getenv("AIML_API_KEY")
    if not api_key:
        return ""

    prompt = f"""You are a quantitative finance analyst specializing in government contract intelligence.

Given the following signals for {company} ({ticker}), write exactly 3 bullet points explaining the {signal} rating. Each bullet must be one sentence max in this format:
- [specific metric with number] — [what it means for the stock]

Signals:
- Contract growth (YoY): {contract_growth * 100:.1f}%
- Hiring growth (YoY): {hiring_growth * 100:.1f}%
- Award size (normalized): {award_size:.2f}
- News sentiment score: {sentiment_score:.2f} (range -1 to 1)
- Total government awards: ${total_awards:,.0f}
- Notable contract: {trigger_award or "N/A"}
- Signal: {signal}

Write only the 3 bullets, no headers, no preamble."""

    for attempt in range(2):
        try:
            response = requests.post(
                "https://api.aimlapi.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 120,
                    "temperature": 0.3,
                },
                timeout=20,
            )
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"].strip()
            if result:
                _thesis_cache[cache_key] = result
                return result
            time.sleep(2)
        except Exception as e:
            print(f"Thesis error attempt {attempt + 1} for {ticker}: {e}")
            if attempt == 0:
                time.sleep(2)

    return ""


def generate_theses(scores: list[dict], max_calls: int = 30) -> dict[str, str]:
    theses: dict[str, str] = {}
    subset = scores[:max_calls]

    def call(args: tuple) -> tuple[str, str]:
        idx, row = args
        time.sleep(idx * 0.3)
        return row["ticker"], generate_thesis(
            ticker=row["ticker"],
            company=row["company"],
            contract_growth=row.get("contract_growth", 0.0),
            hiring_growth=row.get("hiring_growth", 0.0),
            award_size=row.get("award_size", 0.0),
            sentiment_score=row.get("sentiment_score", 0.0),
            total_awards=row.get("total_awards", 0.0),
            trigger_award=row.get("trigger_award", ""),
            signal=row.get("signal", "HOLD"),
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(call, (i, row)): row for i, row in enumerate(subset)}
        for future in as_completed(futures):
            try:
                ticker, thesis = future.result()
                theses[ticker] = thesis
                if not thesis:
                    print(f"WARNING: empty thesis for {futures[future]['ticker']}")
            except Exception as e:
                print(f"Thesis future error: {e}")

    missing = [row["ticker"] for row in subset if not theses.get(row["ticker"])]
    if missing:
        print(f"Missing thesis for: {missing}")

    return theses
