from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests
from sqlalchemy.orm import Session

from models import SerpCache, init_db


SAM_ENDPOINT = "https://api.sam.gov/opportunities/v2/search"
# Pre-award notice types (per SAM.gov API v2):
#   p = Presolicitation, k = Combined Synopsis/Solicitation,
#   r = Sources Sought, s = Special Notice, u = Justification (J&A)
# Excludes 'a' (Award Notice) since those are already-awarded contracts.
PREAWARD_PTYPES = "p,k,r,s,u"


def _fetch_opportunities_for_company(
    api_key: str,
    company: str,
    posted_from: str,
    posted_to: str,
) -> list[dict]:
    """Query SAM.gov for pre-award opportunities mentioning the company."""
    for attempt in range(2):
        try:
            response = requests.get(
                SAM_ENDPOINT,
                params={
                    "api_key": api_key,
                    "q": company,
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "ptype": PREAWARD_PTYPES,
                    "limit": 50,
                },
                timeout=20,
            )
            response.raise_for_status()
            return response.json().get("opportunitiesData", []) or []
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
            else:
                print(f"SAM opportunities error for {company}: {e}")
    return []


def _summarize(company: str, opps: list[dict]) -> dict:
    if not opps:
        return {
            "count": 0,
            "top_notice": "",
            "top_agency": "",
            "top_notice_url": "",
            "top_deadline": "",
        }
    # Surface the notice closest to (but not past) deadline as "most actionable"
    sorted_opps = sorted(
        opps,
        key=lambda o: o.get("responseDeadLine") or o.get("postedDate") or "",
        reverse=True,
    )
    top = sorted_opps[0]
    full_path = top.get("fullParentPathName") or ""
    top_agency = full_path.split(".")[1] if "." in full_path else full_path
    return {
        "count": len(opps),
        "top_notice": (top.get("title") or "")[:160],
        "top_agency": top_agency,
        "top_notice_url": top.get("uiLink", ""),
        "top_deadline": (top.get("responseDeadLine") or "")[:10],
    }


def get_pipeline_signals(
    db: Session,
    companies: list[dict],
    cutoff_date: date,
    lookback_days: int = 90,
    max_calls: int = 15,
) -> dict[str, dict]:
    """For each company, return SAM.gov pipeline summary:
    {count, top_notice, top_agency, top_notice_url, top_deadline}.
    Cached per (ticker, cutoff_date) in serp_cache.
    """
    init_db()
    api_key = os.getenv("SAM_API_KEY")
    empty = {"count": 0, "top_notice": "", "top_agency": "", "top_notice_url": "", "top_deadline": ""}
    if not api_key:
        return {c["ticker"]: dict(empty) for c in companies}

    posted_to = cutoff_date.strftime("%m/%d/%Y")
    posted_from = (cutoff_date - timedelta(days=lookback_days)).strftime("%m/%d/%Y")

    results: dict[str, dict] = {}
    to_fetch: list[dict] = []

    for c in companies:
        ticker = c["ticker"]
        cache_key = f"sam_opps:{ticker}:{cutoff_date.isoformat()}"
        cached = db.query(SerpCache).filter(SerpCache.query == cache_key).one_or_none()
        if cached:
            try:
                results[ticker] = json.loads(cached.response_json)
                continue
            except Exception:
                pass
        to_fetch.append(c)

    def call(args: tuple) -> tuple[str, dict]:
        idx, c = args
        # Stagger to avoid burst rate limiting on SAM.gov
        time.sleep(idx * 0.3)
        opps = _fetch_opportunities_for_company(api_key, c["company"], posted_from, posted_to)
        return c["ticker"], _summarize(c["company"], opps)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(call, (i, c)): c
            for i, c in enumerate(to_fetch[:max_calls])
        }
        for future in as_completed(futures):
            try:
                ticker, summary = future.result()
                results[ticker] = summary
                cache_key = f"sam_opps:{ticker}:{cutoff_date.isoformat()}"
                try:
                    db.add(SerpCache(
                        query=cache_key,
                        response_json=json.dumps(summary),
                        created_at=datetime.utcnow(),
                    ))
                    db.commit()
                except Exception as e:
                    print(f"Pipeline cache write error: {e}")
                    db.rollback()
            except Exception as e:
                print(f"Pipeline future error: {e}")

    for c in companies:
        if c["ticker"] not in results:
            results[c["ticker"]] = dict(empty)

    return results
