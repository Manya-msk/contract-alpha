# ContractAlpha — Full Session Handoff

## What we built

ContractAlpha is a government contract intelligence platform built for the **WebDataUnlocked Hackathon** (Bright Data sponsorship track). The core premise: US federal contract award data is public but noisy — we scrape it, find which public companies are winning contracts *before* the market notices, score them on multiple signals, and backtest the resulting portfolio against SPY to validate alpha.

### Pipeline (in order)
1. **Contract discovery** — pull contract awards from the seeded SQLite DB (or live USAspending via Bright Data). Map recipients to public tickers. Default: `use_live_contracts=true`.
2. **Hiring signal** — real job posting data from `hiring_signals` DB table (collected via `collect_hiring_data.py`); falls back to synthetic if no DB record found.
3. **Sentiment scoring** — AI/ML API (`gpt-4o-mini`) called with ticker + year, returns -1.0 to 1.0. Results cached in `serp_cache` table with key `sentiment_aiml:{ticker}:{year}`.
4. **Pipeline signal** — SAM.gov pre-award notices (presolicitations, sources sought, J&As) bulk-fetched and matched to companies. Surfaced in UI as pending notice count + top notice link. Cached in `serp_cache` as `sam_opps_bulk:{date}:{days}`. Falls back to hardcoded demo notices when `SAM_API_KEY` is missing or quota exhausted.
5. **Scoring** — 4-signal weighted composite (pipeline surfaced but not scored to avoid demo-mode drift). Signals: BUY > 0.35, HOLD > 0.15, AVOID otherwise.
6. **Evidence** — Bright Data SERP lookup for contract-related news. Returns up to 3 results per company, cached. Falls back to a placeholder if SERP is unavailable.
7. **Thesis generation** — parallel AI/ML API calls (`gpt-4o-mini`) for 3 analyst-style bullet points per company. Format: `- [observation with number] — [implication for stock]`
8. **Backtest** — buy top-3 BUY-rated tickers on cutoff date, hold through horizon, compare to SPY via yfinance.

### Frontend
Next.js 14 + TypeScript + Tailwind + Recharts. Single-page app with:
- Date + horizon controls → Run button
- Scores table with: Ticker, Company, Signal badge, Score, Contracts %, Hiring %, Awards $, Sentiment badge, Pipeline (pending notices + link), Trigger award, Thesis (bullet list), Evidence (links + snippets)
- Signal composition bar chart (contract/hiring/award breakdown per company)
- Backtest reveal section — hides actual returns until user clicks "Reveal actual returns"
- Cycling loading message + pulsing skeleton rows while backend is running

---

## What's implemented and working

| Component | Status |
|---|---|
| `backend/services/sentiment.py` | AI/ML API sentiment scoring (`gpt-4o-mini`), parallelized, cached in SQLite |
| `backend/services/thesis.py` | AI/ML API (`gpt-4o-mini`) generates 3-bullet analyst thesis per company, parallelized with `ThreadPoolExecutor` (2 workers, staggered 0.2s) |
| `backend/services/scoring.py` | 5-signal model: `contract_growth` (relative percentile vs peer median), `hiring_growth`, `award_size` (log-normalized), `sentiment`, `volume_bonus` + `momentum_bonus` |
| `backend/scripts/collect_hiring_data.py` | One-time Bright Data SERP script — scrapes Google Jobs for 14 defense/tech companies, stores real hiring signals in `hiring_signals` SQLite table |
| `backend/models.py` | `HiringSignal` model added (`ticker`, `company`, `collection_date`, `total_roles`, `tech_roles`, `ops_roles`, `hiring_score`) |
| `backend/main.py` | Wires all services together; parallelized LLM calls with `ThreadPoolExecutor`; live USAspending contracts by default (`use_live_contracts=True`) |
| `frontend/app/page.tsx` | Sentiment badge column, thesis bullet points column, 3 evidence links per company, cycling loading message, skeleton rows |

### Scoring weights (current)
- **35%** contract growth (relative percentile — normalized vs peer median so seeded/declining data still produces signal)
- **20%** hiring growth (real data from DB if available, else synthetic)
- **30%** award size (log-normalized total $ awarded — most reliable signal with real USAspending data)
- **15%** sentiment (LLM-estimated, cached)
- **+0.10–0.15** volume bonus for contractors with >$5B or >$10B in total awards
- **+0.10** momentum bonus if absolute contract growth > 0

---

## Current issues

| Issue | Severity |
|---|---|
| `use_live_contracts=true` takes 2–3 minutes — USAspending + Yahoo Finance calls are slow | Medium — no loading feedback during this wait |
| Sentiment 0.0 for some companies — AI/ML API quota or timeout | Medium |
| SAM.gov free-tier quota can exhaust during demo — falls back to 35 hardcoded notices | Low — fallback covers all tracked tickers |

---

## Next steps in priority order

1. **Add Triggerware webhook for BUY signals** — `POST /watch` endpoint takes ticker + webhook URL. When next `/simulate` run changes a ticker's signal from HOLD→BUY or AVOID→BUY, fire the webhook. Store watches in a `watches` SQLite table. Prize-stacking opportunity.

2. **Persist thesis cache in SQLite** — `_thesis_cache` is currently in-process only (resets on backend restart). Add `thesis_cache` key format to `serp_cache` table so re-runs are instant.

3. **Frontend polish** — loading skeleton during the 2–3 min live-data wait; row hover states; CSV download button.

4. **Clean up stray `print` statements** before submission.

---

## How to run

```bash
# Backend
cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
# Open http://localhost:3000

# Re-collect hiring data (run once, requires BRIGHTDATA_SERP_KEY)
cd backend && source .venv/bin/activate && python -m scripts.collect_hiring_data

# Test seeded data (fast)
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"cutoff_date":"2022-01-01","horizon_months":12,"use_live_contracts":false}' \
  | python3 -m json.tool | grep -E '"ticker"|"signal"|"score"' | head -30

# Test live data (slow, 2–3 min)
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"cutoff_date":"2022-01-01","horizon_months":12,"use_live_contracts":true}' \
  | python3 -m json.tool | grep -E '"selected_tickers"|"source"'

# Clear sentiment cache (force fresh LLM calls)
sqlite3 backend/contract_alpha.db "DELETE FROM serp_cache WHERE query LIKE 'sentiment_aiml:%';"

# View all cache entries
sqlite3 backend/contract_alpha.db "SELECT query, substr(response_json,1,60) FROM serp_cache;"
```

---

## API keys (in `backend/.env`)

| Env var | What it's for |
|---|---|
| `BRIGHTDATA_ENABLED` | `true` enables live Bright Data SERP calls (evidence + discovery); `false` for seeded mode |
| `BRIGHTDATA_SERP_KEY` | Bright Data API key for SERP zone requests |
| `BRIGHTDATA_SERP_ZONE` | Bright Data zone name (currently `serp_api1`) |
| `AIML_API_KEY` | AI/ML API key — sentiment scoring via `gpt-4o-mini`. Hackathon prize-eligible. |
| `SAM_API_KEY` | SAM.gov Opportunities API v2 key — pipeline signal (pre-award notices). Falls back to 35 hardcoded demo notices if missing or quota exhausted. |
| `GROQ_API_KEY` | Not currently used — thesis switched to AI/ML API. Can be removed from `.env`. |
| `GEMINI_API_KEY` | Not currently used. Reserved. |

---

## Key technical decisions

### Why relative contract growth ranking
When seeded data generates universal YoY decline, raw `contract_growth` carries no signal — every company is negative so sorting by it doesn't differentiate. The fix: compute the peer-group median growth, then use `(growth - median) / spread` as the input to the score. Companies with less-bad growth rank above companies with worse decline. This works correctly with both seeded and real USAspending data.

### Why AI/ML API for sentiment
Bright Data news SERP (`serp_api1` zone with `tbm=nws`) was returning empty `organic` arrays. Rather than debug the zone format before the hackathon deadline, we switched to prompting `gpt-4o-mini` directly with company name + year. Always returns a non-zero score, no SERP call needed. Tradeoff: score reflects LLM training bias, not real-time news.

### Why AI/ML API for thesis
Both thesis and sentiment use AI/ML API (`gpt-4o-mini`) — single API key, consistent output quality, hackathon prize-eligible. Thesis calls are staggered 0.2s apart with 2 workers to avoid burst rate limiting. Retry logic (2 attempts, 2s sleep) handles transient failures.

### Why SQLite cache
All LLM and SERP results cached in `serp_cache` (key → JSON string). Second run with same cutoff is nearly instant. Cache keys: `sentiment_aiml:{ticker}:{year}` for sentiment, raw query string for SERP evidence.

### Why award_size weight is 0.30
With real USAspending data, total contract dollar volume is the most reliable differentiator between major prime contractors (LMT, RTX, BA) and smaller vendors. Log-normalization prevents single mega-awards from dominating.

### Evidence returns a list, not a single dict
`_parse_serp_response` returns `list[dict]` (up to 3 items). Frontend maps the array. Fallback is always a single-item list.

---

## DB schema

```
contracts       — id, ticker, company, award_date, amount, agency
jobs            — id, ticker, date, open_roles, mfg_roles, eng_roles
serp_cache      — id, query (unique), response_json (text), created_at
hiring_signals  — id, ticker, company, collection_date, total_roles, tech_roles, ops_roles, hiring_score
```

DB file: `backend/contract_alpha.db`

---

## File map

```
backend/
  main.py              — FastAPI app; build_simulation() orchestrates everything; use_live_contracts=True default
  models.py            — SQLAlchemy models: Contract, Job, SerpCache, HiringSignal
  seed.py              — Seeds DB with synthetic contract + job data (updated trend variance)
  services/
    backtest.py        — yfinance backtest vs SPY
    config.py          — load_env(), env_bool() helpers
    contracts.py       — Query contracts from DB or live
    discovery.py       — USAspending API + Yahoo Finance ticker mapping; 3x horizon lookback
    evidence.py        — Bright Data SERP for contract evidence (returns list[dict], up to 3)
    jobs.py            — Hiring signal computation (synthetic fallback)
    opportunities.py   — SAM.gov pre-award pipeline signal; bulk fetch up to 3000 notices; cached; 35-notice demo fallback
    scoring.py         — 5-signal composite; relative contract_growth ranking vs peer median
    sentiment.py       — AI/ML API sentiment (parallel, cached in serp_cache)
    thesis.py          — AI/ML API gpt-4o-mini 3-bullet thesis generation (parallel, in-process cache)
  scripts/
    __init__.py        — Empty package marker
    collect_hiring_data.py — One-time Bright Data SERP scraper → hiring_signals table
frontend/
  app/
    page.tsx           — Main UI: scores table, signal chart, backtest reveal, skeleton loading
    globals.css        — Tailwind base styles
    layout.tsx         — Root layout
```
