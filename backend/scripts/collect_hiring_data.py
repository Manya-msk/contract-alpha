from __future__ import annotations

import os
import sys
import time
from datetime import date
from urllib.parse import quote_plus

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import HiringSignal, SessionLocal, init_db


BRIGHTDATA_ENDPOINT = "https://api.brightdata.com/request"

COMPANIES = [
    ("LMT", "Lockheed Martin"),
    ("RTX", "RTX Corporation"),
    ("NOC", "Northrop Grumman"),
    ("BA", "Boeing"),
    ("GD", "General Dynamics"),
    ("BAH", "Booz Allen Hamilton"),
    ("HII", "Huntington Ingalls"),
    ("LDOS", "Leidos"),
    ("TXT", "Textron"),
    ("NVDA", "Nvidia"),
    ("CAT", "Caterpillar"),
    ("GE", "GE Aerospace"),
    ("LLY", "Eli Lilly"),
    ("SAIC", "SAIC"),
]

TECH_KEYWORDS = ["engineer", "developer", "scientist", "analyst", "research"]
OPS_KEYWORDS = ["manufacturing", "operations", "supply chain", "logistics", "production"]


def fetch_jobs(company_name: str, api_key: str, zone: str) -> list[dict]:
    url = f"https://www.google.com/search?q={quote_plus(company_name + ' jobs site:linkedin.com United States')}&hl=en&gl=us"
    try:
        response = requests.post(
            BRIGHTDATA_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "zone": zone,
                "url": url,
                "format": "json",
                "method": "GET",
                "country": "us",
                "data_format": "parsed_light",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        organic = payload.get("organic") or []
        if not organic and isinstance(payload.get("body"), str):
            import json
            try:
                organic = json.loads(payload["body"]).get("organic", [])
            except Exception:
                organic = []
        return organic
    except Exception as e:
        print(f"    SERP error for {company_name}: {e}")
        return []


def score_results(results: list[dict]) -> tuple[int, int, int, float]:
    total_roles = len(results)
    tech_roles = 0
    ops_roles = 0

    for item in results:
        title = (item.get("title") or "").lower()
        if any(k in title for k in TECH_KEYWORDS):
            tech_roles += 1
        if any(k in title for k in OPS_KEYWORDS):
            ops_roles += 1

    tech_score = tech_roles / max(total_roles, 1)
    ops_score = ops_roles / max(total_roles, 1)
    base = 0.4
    hiring_score = round(min(base + (tech_score * 0.4) + (ops_score * 0.2), 1.0), 3)

    return total_roles, tech_roles, ops_roles, hiring_score


def main() -> None:
    init_db()
    db = SessionLocal()
    api_key = os.getenv("BRIGHTDATA_SERP_KEY")
    zone = os.getenv("BRIGHTDATA_SERP_ZONE", "serp_api1")

    if not api_key:
        print("ERROR: BRIGHTDATA_SERP_KEY not set in .env")
        return

    print(f"Collecting hiring data for {len(COMPANIES)} companies...")

    try:
        for ticker, company_name in COMPANIES:
            try:
                results = fetch_jobs(company_name, api_key, zone)
                total_roles, tech_roles, ops_roles, hiring_score = score_results(results)

                print(f"  Collecting {company_name} ({ticker})... found {total_roles} results, tech={tech_roles}, ops={ops_roles}, score: {hiring_score}")

                existing = db.query(HiringSignal).filter(HiringSignal.ticker == ticker).one_or_none()
                if existing:
                    existing.collection_date = date.today()
                    existing.total_roles = total_roles
                    existing.tech_roles = tech_roles
                    existing.ops_roles = ops_roles
                    existing.hiring_score = hiring_score
                else:
                    db.add(HiringSignal(
                        ticker=ticker,
                        company=company_name,
                        collection_date=date.today(),
                        total_roles=total_roles,
                        tech_roles=tech_roles,
                        ops_roles=ops_roles,
                        hiring_score=hiring_score,
                    ))

                db.commit()
                time.sleep(3)

            except Exception as e:
                print(f"  ERROR collecting {company_name} ({ticker}): {e}")
                db.rollback()
                continue
    finally:
        db.close()

    print(f"Done. {len(COMPANIES)} companies processed.")
    print("Run the backend and call /simulate to see real hiring scores in action.")


if __name__ == "__main__":
    from services.config import load_env
    load_env()
    main()


    