from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


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
    api_key = os.getenv("AIML_API_KEY")
    if not api_key:
        return ""

    prompt = f"""You are a quantitative finance analyst specializing in government contract intelligence.

Given the following signals for {company} ({ticker}), write exactly 3 bullet points explaining the {signal} rating. Each bullet must be one sentence max. Cite the numbers. Use this exact format:
- [key signal observation with number] — [what it means for the stock]
- [key signal observation with number] — [what it means for the stock]
- [key signal observation with number] — [what it means for the stock]

Signals:
- Contract growth (YoY): {contract_growth * 100:.1f}%
- Hiring growth (YoY): {hiring_growth * 100:.1f}%
- Award size (normalized): {award_size:.2f}
- News sentiment score: {sentiment_score:.2f} (range -1 to 1)
- Total government awards: ${total_awards:,.0f}
- Notable contract: {trigger_award or "N/A"}
- Signal: {signal}

Output only the 3 bullet lines, nothing else."""

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
            timeout=15,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Thesis error for {ticker}: {e}")
        return ""


def generate_theses(scores: list[dict], max_calls: int = 10) -> dict[str, str]:
    theses: dict[str, str] = {}
    subset = scores[:max_calls]

    def call(row: dict) -> tuple[str, str]:
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

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(call, row): row for row in subset}
        for future in as_completed(futures):
            try:
                ticker, thesis = future.result()
                theses[ticker] = thesis
            except Exception as e:
                print(f"Thesis future error: {e}")

    return theses
