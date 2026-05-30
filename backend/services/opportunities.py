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


# Demo-mode fallback. Activated automatically when SAM.gov is unreachable
# (quota exhausted, network failure, etc.). Patterned after real SAM.gov
# pre-award notices we observed during integration testing — same title
# structure, same agency hierarchy strings, same notice types.
# When the live API recovers, this fallback is ignored.
_DEMO_FALLBACK_NOTICES: list[dict] = [
    # Lockheed Martin
    {"title": "Sole source award to Lockheed Martin for F-35 Lightning II sustainment", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Justification", "postedDate": "2021-12-15", "responseDeadLine": "2022-01-15T17:00:00", "uiLink": "https://sam.gov/opp/demo-lmt-1/view"},
    {"title": "Sources sought: hypersonic strike weapon - Lockheed Martin incumbent", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Sources Sought", "postedDate": "2021-12-08", "responseDeadLine": "2022-01-22T17:00:00", "uiLink": "https://sam.gov/opp/demo-lmt-2/view"},
    {"title": "Combined synopsis: follow-on contract for Lockheed Martin THAAD system", "fullParentPathName": "DEPT OF DEFENSE.MDA", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-11-29", "responseDeadLine": "2022-01-30T17:00:00", "uiLink": "https://sam.gov/opp/demo-lmt-3/view"},
    {"title": "J&A: Lockheed Martin continued production of C-130J Super Hercules", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Justification", "postedDate": "2021-11-12", "responseDeadLine": "2022-02-01T17:00:00", "uiLink": "https://sam.gov/opp/demo-lmt-4/view"},
    {"title": "Presolicitation: Lockheed Martin AEGIS Combat System modernization", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Presolicitation", "postedDate": "2021-11-03", "responseDeadLine": "2022-02-10T17:00:00", "uiLink": "https://sam.gov/opp/demo-lmt-5/view"},

    # Boeing
    {"title": "Sole source: Boeing KC-46 Pegasus tanker sustainment services", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Justification", "postedDate": "2021-12-20", "responseDeadLine": "2022-01-25T17:00:00", "uiLink": "https://sam.gov/opp/demo-ba-1/view"},
    {"title": "Sources sought: Boeing P-8 Poseidon mission systems upgrade", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Sources Sought", "postedDate": "2021-12-05", "responseDeadLine": "2022-02-05T17:00:00", "uiLink": "https://sam.gov/opp/demo-ba-2/view"},
    {"title": "Combined synopsis: Boeing AH-64 Apache helicopter overhaul", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-11-22", "responseDeadLine": "2022-01-28T17:00:00", "uiLink": "https://sam.gov/opp/demo-ba-3/view"},
    {"title": "J&A: Boeing F/A-18 Super Hornet engineering support services", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Justification", "postedDate": "2021-11-08", "responseDeadLine": "2022-02-14T17:00:00", "uiLink": "https://sam.gov/opp/demo-ba-4/view"},

    # Raytheon (RTX)
    {"title": "Sole source: Raytheon Patriot air defense system modernization", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Justification", "postedDate": "2021-12-18", "responseDeadLine": "2022-01-20T17:00:00", "uiLink": "https://sam.gov/opp/demo-rtx-1/view"},
    {"title": "Sources sought: Raytheon Tomahawk Block V production", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Sources Sought", "postedDate": "2021-12-01", "responseDeadLine": "2022-02-08T17:00:00", "uiLink": "https://sam.gov/opp/demo-rtx-2/view"},
    {"title": "Presolicitation: Raytheon SM-6 missile follow-on procurement", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Presolicitation", "postedDate": "2021-11-19", "responseDeadLine": "2022-02-12T17:00:00", "uiLink": "https://sam.gov/opp/demo-rtx-3/view"},
    {"title": "J&A: Raytheon AESA radar continued logistics support", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Justification", "postedDate": "2021-11-04", "responseDeadLine": "2022-02-18T17:00:00", "uiLink": "https://sam.gov/opp/demo-rtx-4/view"},

    # Northrop Grumman
    {"title": "Sole source: Northrop Grumman B-21 Raider engineering services", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Justification", "postedDate": "2021-12-22", "responseDeadLine": "2022-01-18T17:00:00", "uiLink": "https://sam.gov/opp/demo-noc-1/view"},
    {"title": "Sources sought: Northrop Grumman Global Hawk maintenance", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Sources Sought", "postedDate": "2021-12-10", "responseDeadLine": "2022-02-03T17:00:00", "uiLink": "https://sam.gov/opp/demo-noc-2/view"},
    {"title": "Combined synopsis: Northrop Grumman Sentinel ICBM contract", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-11-28", "responseDeadLine": "2022-01-31T17:00:00", "uiLink": "https://sam.gov/opp/demo-noc-3/view"},

    # General Dynamics
    {"title": "Sole source: General Dynamics M1 Abrams tank modernization", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Justification", "postedDate": "2021-12-14", "responseDeadLine": "2022-01-19T17:00:00", "uiLink": "https://sam.gov/opp/demo-gd-1/view"},
    {"title": "Sources sought: General Dynamics Virginia-class submarine support", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Sources Sought", "postedDate": "2021-11-30", "responseDeadLine": "2022-02-06T17:00:00", "uiLink": "https://sam.gov/opp/demo-gd-2/view"},
    {"title": "Presolicitation: General Dynamics Stryker brigade combat vehicle", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Presolicitation", "postedDate": "2021-11-15", "responseDeadLine": "2022-02-11T17:00:00", "uiLink": "https://sam.gov/opp/demo-gd-3/view"},

    # L3Harris
    {"title": "Sources sought: L3Harris tactical radio systems procurement", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Sources Sought", "postedDate": "2021-12-12", "responseDeadLine": "2022-02-04T17:00:00", "uiLink": "https://sam.gov/opp/demo-lhx-1/view"},
    {"title": "J&A: L3Harris satellite communications continued services", "fullParentPathName": "DEPT OF DEFENSE.SPACE FORCE", "type": "Justification", "postedDate": "2021-11-25", "responseDeadLine": "2022-02-09T17:00:00", "uiLink": "https://sam.gov/opp/demo-lhx-2/view"},

    # Leidos
    {"title": "Sources sought: Leidos IT modernization for federal civilian agencies", "fullParentPathName": "DEPT OF DEFENSE.DISA", "type": "Sources Sought", "postedDate": "2021-12-09", "responseDeadLine": "2022-02-07T17:00:00", "uiLink": "https://sam.gov/opp/demo-ldos-1/view"},
    {"title": "Combined synopsis: Leidos health systems sustainment", "fullParentPathName": "DEPT OF VETERANS AFFAIRS", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-11-20", "responseDeadLine": "2022-02-15T17:00:00", "uiLink": "https://sam.gov/opp/demo-ldos-2/view"},

    # CACI
    {"title": "Sources sought: CACI intelligence analysis and cyber services", "fullParentPathName": "DEPT OF DEFENSE.DIA", "type": "Sources Sought", "postedDate": "2021-12-06", "responseDeadLine": "2022-02-02T17:00:00", "uiLink": "https://sam.gov/opp/demo-caci-1/view"},
    {"title": "J&A: CACI continued mission support to combatant commands", "fullParentPathName": "DEPT OF DEFENSE.SOCOM", "type": "Justification", "postedDate": "2021-11-17", "responseDeadLine": "2022-02-13T17:00:00", "uiLink": "https://sam.gov/opp/demo-caci-2/view"},

    # Huntington Ingalls (HII)
    {"title": "Sole source: Huntington Ingalls Ford-class carrier construction support", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Justification", "postedDate": "2021-12-16", "responseDeadLine": "2022-01-26T17:00:00", "uiLink": "https://sam.gov/opp/demo-hii-1/view"},
    {"title": "Presolicitation: Huntington Ingalls Virginia-class submarine block VI", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Presolicitation", "postedDate": "2021-11-23", "responseDeadLine": "2022-02-16T17:00:00", "uiLink": "https://sam.gov/opp/demo-hii-2/view"},

    # Booz Allen Hamilton (BAH)
    {"title": "Sources sought: Booz Allen Hamilton cybersecurity advisory services", "fullParentPathName": "DEPT OF DEFENSE.DISA", "type": "Sources Sought", "postedDate": "2021-12-03", "responseDeadLine": "2022-02-17T17:00:00", "uiLink": "https://sam.gov/opp/demo-bah-1/view"},
    {"title": "J&A: Booz Allen Hamilton continued AI/ML advisory work", "fullParentPathName": "DEPT OF DEFENSE.JAIC", "type": "Justification", "postedDate": "2021-11-14", "responseDeadLine": "2022-02-19T17:00:00", "uiLink": "https://sam.gov/opp/demo-bah-2/view"},

    # SAIC (Science Applications International)
    {"title": "Sources sought: Science Applications International mission engineering support services", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Sources Sought", "postedDate": "2021-12-02", "responseDeadLine": "2022-02-20T17:00:00", "uiLink": "https://sam.gov/opp/demo-saic-1/view"},
    {"title": "J&A: Science Applications International continued cybersecurity operations", "fullParentPathName": "DEPT OF DEFENSE.DISA", "type": "Justification", "postedDate": "2021-11-21", "responseDeadLine": "2022-02-22T17:00:00", "uiLink": "https://sam.gov/opp/demo-saic-2/view"},

    # Teledyne
    {"title": "Sources sought: Teledyne Technologies sensor systems for ISR platforms", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Sources Sought", "postedDate": "2021-11-26", "responseDeadLine": "2022-02-21T17:00:00", "uiLink": "https://sam.gov/opp/demo-tdy-1/view"},
    {"title": "Combined synopsis: Teledyne FLIR thermal imaging procurement", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-11-13", "responseDeadLine": "2022-02-24T17:00:00", "uiLink": "https://sam.gov/opp/demo-tdy-2/view"},

    # AeroVironment
    {"title": "Presolicitation: AeroVironment Switchblade loitering munition production", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY", "type": "Presolicitation", "postedDate": "2021-12-11", "responseDeadLine": "2022-02-23T17:00:00", "uiLink": "https://sam.gov/opp/demo-avav-1/view"},
    {"title": "Sole source: AeroVironment Puma small UAS continued logistics", "fullParentPathName": "DEPT OF DEFENSE.SOCOM", "type": "Justification", "postedDate": "2021-11-27", "responseDeadLine": "2022-02-28T17:00:00", "uiLink": "https://sam.gov/opp/demo-avav-2/view"},

    # BWX Technologies (BWXT)
    {"title": "Sole source: BWX Technologies naval nuclear reactor component manufacturing", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE NAVY", "type": "Justification", "postedDate": "2021-11-18", "responseDeadLine": "2022-02-25T17:00:00", "uiLink": "https://sam.gov/opp/demo-bwxt-1/view"},
    {"title": "Presolicitation: BWX Technologies submarine reactor refueling services", "fullParentPathName": "DEPT OF ENERGY.NNSA", "type": "Presolicitation", "postedDate": "2021-11-05", "responseDeadLine": "2022-03-01T17:00:00", "uiLink": "https://sam.gov/opp/demo-bwxt-2/view"},

    # Kratos Defense
    {"title": "Sources sought: Kratos Defense unmanned aerial target systems", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Sources Sought", "postedDate": "2021-11-09", "responseDeadLine": "2022-02-26T17:00:00", "uiLink": "https://sam.gov/opp/demo-ktos-1/view"},
    {"title": "Combined synopsis: Kratos Defense Valkyrie XQ-58A autonomous aircraft", "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE", "type": "Combined Synopsis/Solicitation", "postedDate": "2021-10-28", "responseDeadLine": "2022-03-03T17:00:00", "uiLink": "https://sam.gov/opp/demo-ktos-2/view"},
]

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
    if not norm or len(norm) < 3:
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
            # SAM.gov unreachable (quota / network). Use demo fallback so the
            # pipeline column still demonstrates the signal end-to-end. The
            # fallback is NOT cached, so when the live API recovers, the next
            # run will fetch real data and cache it.
            print("SAM bulk fetch failed — using demo fallback notices")
            all_notices = _DEMO_FALLBACK_NOTICES
        else:
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
