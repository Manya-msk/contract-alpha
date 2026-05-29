from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from models import SerpCache, init_db


AIML_ENDPOINT = "https://api.aimlapi.com/v1/chat/completions"


def _score_sentiment_with_llm(ticker: str, company: str, cutoff_year: int) -> float:
    api_key = os.getenv("AIML_API_KEY")
    if not api_key:
        return 0.0

    prompt = (
        f"You are a financial analyst. Based on your knowledge of {company} ({ticker}) "
        f"up to {cutoff_year}, return a single sentiment score between -1.0 (very negative) "
        f"and 1.0 (very positive) reflecting the market and news sentiment around the company "
        f"at that time. Only return the number, nothing else."
    )

    for attempt in range(2):
        try:
            response = requests.post(
                AIML_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0.0,
                },
                timeout=15,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()
            return max(-1.0, min(1.0, float(raw)))
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
            else:
                print(f"Sentiment error for {company} ({ticker}): {e}")
    return 0.0


def get_sentiment_scores(
    db: Session,
    companies: list[dict],
    cutoff_year: int,
    max_calls: int = 5,
) -> dict[str, float]:
    init_db()
    scores: dict[str, float] = {}
    to_fetch = []

    for company in companies:
        ticker = company["ticker"]
        cache_key = f"sentiment_aiml:{ticker}:{cutoff_year}"
        cached = db.query(SerpCache).filter(SerpCache.query == cache_key).one_or_none()
        if cached:
            try:
                scores[ticker] = float(cached.response_json)
                print(f"Sentiment [{ticker}] cached={scores[ticker]}")
                continue
            except Exception:
                pass
        to_fetch.append(company)

    def call(company: dict) -> tuple[str, str, float]:
        ticker = company["ticker"]
        name = company["company"]
        score = _score_sentiment_with_llm(ticker, name, cutoff_year)
        return ticker, f"sentiment_aiml:{ticker}:{cutoff_year}", score

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(call, c): c for c in to_fetch[:max_calls] if c}
        for future in as_completed(futures):
            try:
                ticker, cache_key, score = future.result()
                scores[ticker] = score
                try:
                    db.add(SerpCache(
                        query=cache_key,
                        response_json=str(score),
                        created_at=datetime.utcnow(),
                    ))
                    db.commit()
                except Exception as e:
                    print(f"Cache write error: {e}")
                    db.rollback()
            except Exception as e:
                print(f"Sentiment future error: {e}")

    return scores
