from __future__ import annotations

import json
import os
import re
import time
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

# Paginate the bulk pull up to this many pages × 1000 notices.
# 3 pages = 3000 notices, which comfortably covers a 60-day defense-heavy window.
MAX_PAGES = 3
PAGE_SIZE = 1000

# Common corporate suffixes to strip when normalizing names for matching.
_SUFFIX_RE = re.compile(
    r"\s+(corporation|corp\.?|incorporated|inc\.?|company|co\.?|ltd\.?|plc|holdings|"
    r"international|systems|technologies|industries|group|llc|l\.l\.c\.|n\.v\.|"
    r"s\.a\.|ag|se)$",
    re.IGNORECASE,
)


def _normalize_company_name(name: str) -> str:
    """Strip common corporate suffixes to get a matchable name fragment."""
    if not name:
        return ""
    n = name.strip()
    # Strip suffixes iteratively (handles "Lockheed Martin Corporation" → "Lockheed Martin")
    for _ in range(3):
        new_n = _SUFFIX_RE.sub("", n).strip()
        if new_n == n:
            break
        n = new_n
    return n.lower()


def _fetch_page(
    api_key: str,
    posted_from: str,
    posted_to: str,
    offset: int,
) -> tuple[int, list[dict]] | None:
    """Fetch one page of pre-award notices. Returns (totalRecords, page_data) or None on error."""
    for attempt in range(2):
        try:
            response = requests.get(
                SAM_ENDPOINT,
                params={
                    "api_key": api_key,
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "ptype": PREAWARD_PTYPES,
                    "limit": PAGE_SIZE,
                    "offset": offset,
                },
                timeout=30,
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    time.sleep(3)
                    continue
                print(f"SAM page fetch error (offset {offset}): HTTP {response.status_code} {response.text[:120]}")
                return None
            response.raise_for_status()
            payload = response.json()
            return int(payload.get("totalRecords") or 0), payload.get("opportunitiesData", []) or []
        except Exception as e:
            if attempt == 0:
                time.sleep(3)
            else:
                print(f"SAM page fetch exception (offset {offset}): {e}")
                return None
    return None


def _fetch_all_preaward_notices(
    api_key: str,
    posted_from: str,
    posted_to: str,
) -> list[dict] | None:
    """Bulk-fetch all pre-award notices in the date range, paginated.
    Returns the combined list or None if the first page fails entirely.
    Partial results are returned if a later page fails (better than nothing).
    """
    all_notices: list[dict] = []
    first = _fetch_page(api_key, posted_from, posted_to, offset=0)
    if first is None:
        return None
    total, page = first
    all_notices.extend(page)
    if total <= PAGE_SIZE:
        return all_notices

    for page_idx in range(1, MAX_PAGES):
        offset = page_idx * PAGE_SIZE
        if offset >= total:
            break
        result = _fetch_page(api_key, posted_from, posted_to, offset)
        if result is None:
            # Partial data is still useful for the demo
            print(f"SAM partial fetch: got {len(all_notices)} of {total} notices")
            break
        _, page_data = result
        all_notices.extend(page_data)

    return all_notices


def _match_notices_to_company(
    company_name: str,
    notices: list[dict],
) -> list[dict]:
    """Find notices whose title, parent path, or solicitation number mention
    the company. Title-mentions are the highest-signal — sole-source awards,
    follow-on contracts, and J&A notices typically name the vendor in the title.
    """
    norm = _normalize_company_name(company_name)
    if not norm or len(norm) < 4:
        # Skip too-generic names ("J" → would match everything)
        return []
    matches = []
    for n in notices:
        haystack = " ".join([
            (n.get("title") or ""),
            (n.get("fullParentPathName") or ""),
            (n.get("solicitationNumber") or ""),
            (n.get("organizationType") or ""),
        ]).lower()
        if norm in haystack:
            matches.append(n)
    return matches


def _summarize(total: int, opps: list[dict]) -> dict:
    if total == 0 or not opps:
        return {
            "count": total,
            "top_notice": "",
            "top_agency": "",
            "top_notice_url": "",
            "top_deadline": "",
        }
    # Sort by postedDate desc (most recent = most actionable), then prefer
    # real procurements over generic Special Notices for the displayed top.
    sorted_opps = sorted(
        opps,
        key=lambda o: o.get("postedDate") or "",
        reverse=True,
    )
    non_special = [o for o in sorted_opps if (o.get("type") or "") != "Special Notice"]
    top = (non_special or sorted_opps)[0]
    full_path = top.get("fullParentPathName") or ""
    top_agency = full_path.split(".")[1] if "." in full_path else full_path
    return {
        "count": total,
        "top_notice": (top.get("title") or "")[:160],
        "top_agency": top_agency,
        "top_notice_url": top.get("uiLink", ""),
        "top_deadline": (top.get("responseDeadLine") or "")[:10],
    }


def get_pipeline_signals(
    db: Session,
    companies: list[dict],
    cutoff_date: date,
    lookback_days: int = 60,
    max_calls: int = 15,  # kept for signature compatibility; unused in bulk mode
) -> dict[str, dict]:
    """For each company, return SAM.gov pipeline summary by matching
    company names against a bulk pull of pre-award notices.

    API cost: 1-3 calls per (cutoff_date, lookback_days), cached in serp_cache
    under key `sam_opps_bulk:{cutoff_date}:{lookback_days}`. After the first
    successful run, subsequent runs are zero-cost.
    """
    init_db()
    empty = {"count": 0, "top_notice": "", "top_agency": "", "top_notice_url": "", "top_deadline": ""}
    api_key = os.getenv("SAM_API_KEY")
    if not api_key:
        return {c["ticker"]: dict(empty) for c in companies}

    bulk_cache_key = f"sam_opps_bulk:{cutoff_date.isoformat()}:{lookback_days}"
    posted_to = cutoff_date.strftime("%m/%d/%Y")
    posted_from = (cutoff_date - timedelta(days=lookback_days)).strftime("%m/%d/%Y")

    all_notices: list[dict] | None = None
    cached = db.query(SerpCache).filter(SerpCache.query == bulk_cache_key).one_or_none()
    if cached:
        try:
            all_notices = json.loads(cached.response_json)
            print(f"SAM bulk cache hit: {len(all_notices)} notices for {cutoff_date}")
        except Exception:
            all_notices = None

    if all_notices is None:
        all_notices = _fetch_all_preaward_notices(api_key, posted_from, posted_to)
        if all_notices is None:
            print("SAM bulk fetch failed entirely — returning empty pipeline data")
            return {c["ticker"]: dict(empty) for c in companies}
        try:
            db.add(SerpCache(
                query=bulk_cache_key,
                response_json=json.dumps(all_notices),
                created_at=datetime.utcnow(),
            ))
            db.commit()
            print(f"SAM bulk fetched + cached {len(all_notices)} notices for {cutoff_date}")
        except Exception as e:
            print(f"SAM bulk cache write error: {e}")
            db.rollback()

    # Local matching — no more API calls.
    results: dict[str, dict] = {}
    for c in companies:
        ticker = c["ticker"]
        matches = _match_notices_to_company(c["company"], all_notices)
        results[ticker] = _summarize(len(matches), matches)

    return results
