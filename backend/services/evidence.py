from __future__ import annotations

from datetime import datetime
import json
import os
from urllib.parse import quote_plus

from sqlalchemy.orm import Session
import requests

from models import SerpCache, init_db
from services.config import env_bool


BRIGHTDATA_ENDPOINT = "https://api.brightdata.com/request"


def _fallback_evidence(company: str, year: int) -> dict:
    return {
        "title": f"{company} government contract activity ({year})",
        "url": "",
        "snippet": "Fallback evidence: public contract recipient found through USAspending or the demo fallback universe.",
        "source": "mock_fallback",
    }


def _extract_organic_results(payload: dict) -> list[dict]:
    if isinstance(payload.get("organic"), list):
        return payload["organic"]
    body = payload.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}
    if isinstance(body, dict) and isinstance(body.get("organic"), list):
        return body["organic"]
    return []


def _parse_serp_response(payload: dict, company: str, year: int) -> list[dict]:
    organic = _extract_organic_results(payload)
    results = []
    for result in organic:
        title = str(result.get("title") or "")
        description = str(result.get("description") or result.get("snippet") or "")
        text = f"{title} {description}".lower()
        if "contract" in text or "award" in text or "government" in text:
            results.append({
                "title": title or f"{company} contract result",
                "url": result.get("link") or result.get("url") or "",
                "snippet": description or f"Search result for {company} government contract award {year}",
                "source": "brightdata_serp",
            })
            if len(results) >= 3:
                break
    return results if results else [_fallback_evidence(company, year)]


def get_contract_evidence(db: Session, companies: list[dict], cutoff_year: int, max_calls: int = 5) -> dict[str, list[dict]]:
    init_db()
    evidence: dict[str, list[dict]] = {}
    enabled = env_bool("BRIGHTDATA_ENABLED", False)
    api_key = os.getenv("BRIGHTDATA_SERP_KEY")
    zone = os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    calls = 0

    for company in companies:
        ticker = company["ticker"]
        name = company["company"]
        query = f"{name} government contract award {cutoff_year}"
        cached = db.query(SerpCache).filter(SerpCache.query == query).one_or_none()
        if cached:
            try:
                evidence[ticker] = _parse_serp_response(json.loads(cached.response_json), name, cutoff_year)
                continue
            except Exception:
                evidence[ticker] = [_fallback_evidence(name, cutoff_year)]
                continue

        if not enabled or not api_key or calls >= max_calls:
            evidence[ticker] = [_fallback_evidence(name, cutoff_year)]
            continue

        try:
            search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&gl=us"
            response = requests.post(
                BRIGHTDATA_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "zone": zone,
                    "url": search_url,
                    "format": "json",
                    "method": "GET",
                    "country": "us",
                    "data_format": "parsed_light",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            db.add(SerpCache(query=query, response_json=json.dumps(payload), created_at=datetime.utcnow()))
            db.commit()
            calls += 1
            evidence[ticker] = _parse_serp_response(payload, name, cutoff_year)
        except Exception:
            db.rollback()
            evidence[ticker] = [_fallback_evidence(name, cutoff_year)]

    return evidence
