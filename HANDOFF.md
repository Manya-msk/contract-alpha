# ContractAlpha — Full Session Handoff

## What we built

ContractAlpha is a government contract intelligence platform built for the **WebDataUnlocked Hackathon** (Bright Data sponsorship track). The core premise: US federal contract award data is public but noisy — we scrape it, find which public companies are winning contracts *before* the market notices, score them on multiple signals, and backtest the resulting portfolio against SPY to validate alpha.

### Pipeline (in order)
1. **Contract discovery** — pull contract awards from the seeded SQLite DB (or live USAspending via Bright Data). Map recipients to public tickers.
2. **Hiring signal** — synthetic job posting growth data per ticker, used as a proxy for operational ramp-up.
3. **Sentiment scoring** — call AI/ML API (`gpt-4o-mini`) with ticker + year, get a -1.0 to 1.0 score based on LLM training knowledge. Results cached in `serp_cache` table.
4. **Scoring** — weighted composite score: 35% contract growth + 25% hiring growth + 25% award size (log-normalized) + 15% sentiment. Signals: BUY > 0.4, HOLD 0.2–0.4, AVOID < 0.2.
5. **Evidence** — Bright Data SERP lookup for contract-related news. Returns up to 3 results per company, cached. Falls back to a placeholder if SERP is unavailable.
6. **Thesis generation** — parallel calls to AI/ML API (`gpt-4o-mini`) asking for 3 analyst-style bullet points per company. Format: `- [observation with number] — [implication for stock]`
7. **Backtest** — buy all BUY-rated tickers equally on cutoff date, hold through horizon, compare to SPY via yfinance.

### Frontend
Next.js 14 + TypeScript + Tailwind + Recharts. Single-page app with:
- Date + horizon controls → Run button
- Scores table with: Ticker, Company, Signal badge, Score, Contracts %, Hiring %, Awards $, Sentiment badge, Trigger award, Thesis (bullet list), Evidence (links + snippets)
- Signal composition bar chart (contract/hiring/award breakdown per company)
- Backtest reveal section — hides actual returns until user clicks "Reveal actual returns"
- Cycling loading message + pulsing skeleton rows while backend is running

---

## All files changed this session

| File | What changed |
|---|---|
| `backend/services/thesis.py` | Model: `llama3-8b-8192` → `gpt-4o-mini`; endpoint → AI/ML API; prompt changed to 3 structured bullet points; parallelized with `ThreadPoolExecutor(max_workers=5)`; added error logging |
| `backend/services/sentiment.py` | Full rewrite — removed all Bright Data SERP code; now calls AI/ML API directly with ticker+year for LLM-based sentiment; parallelized with `ThreadPoolExecutor(max_workers=5)`; cache key: `sentiment_aiml:{ticker}:{cutoff_year}` |
| `backend/services/evidence.py` | `_parse_serp_response` now returns `list[dict]` with up to 3 results instead of a single dict; all fallback assignments updated to single-item lists |
| `backend/main.py` | Evidence fallback default changed to list; sentiment call wrapped in `ThreadPoolExecutor` future |
| `frontend/app/page.tsx` | Added `sentiment_score`, `thesis` to `Score` type; `evidence` type changed to array; Sentiment column (colored badge); Thesis column (bullet list renderer); Evidence column (multi-item with dividers); loading skeleton rows; cycling loading message; table min-w widened to 1400px |
| `HANDOFF.md` | This file |

---

## Current state

### Working
- Full simulation pipeline via `POST /simulate`
- Thesis generation: `gpt-4o-mini` via AI/ML API returning structured 3-bullet output, rendered as bullet list in table
- Sentiment scoring: AI/ML API returning real non-zero floats (verified), cached in SQLite
- Parallel LLM calls: thesis (5 workers) + sentiment (5 workers) fire concurrently
- Backtest vs SPY using yfinance
- Frontend: all columns rendering, skeleton loading, cycling status message
- Evidence column: renders up to 3 SERP results with title links + snippets

### Broken / Incomplete
- **Evidence from Bright Data is still the mock fallback** for most companies. Bright Data SERP calls either fail silently or return payloads where `organic` is empty. The `_extract_organic_results` function tries both top-level `organic` and `body.organic` but neither path returns results. Root cause not yet confirmed — likely the Bright Data zone/format mismatch.
- **Sentiment uses LLM knowledge, not real-time news** — this is a deliberate workaround for the broken SERP, but it means sentiment scores reflect LLM training data bias, not actual recent headlines.
- **Job data is synthetic** (seeded from `backend/seed.py`) — no real job posting scraper is connected.
- **Contract data is seeded** — `use_live_contracts=true` triggers a Bright Data discovery flow but it's not fully battle-tested in production.
- **No thesis caching** — every run regenerates all theses (expensive, ~10 API calls). Should add a `thesis_cache` table or reuse `serp_cache` with a `thesis:{ticker}:{cutoff_year}` key.
- **Groq is no longer used** — `GROQ_API_KEY` is still in `.env` but both thesis and sentiment now use AI/ML API. The `debug-thesis` endpoint in `main.py` still references the old `llama3-8b-8192` model.

---

## Next steps in order

1. **Fix Bright Data evidence** — Add `print(payload)` to `_extract_organic_results` to see the raw response shape. The zone may need `data_format: "raw"` instead of `"parsed_light"`, or the response might be at a different key. Fix `_extract_organic_results` to match actual response shape.

2. **Cache thesis generation** — Add cache lookup/write in `generate_theses` using key `thesis:{ticker}:{cutoff_year}`. Store in `serp_cache` table. This prevents ~$0.10 in AI/ML API spend per run.

3. **Real hiring data via Bright Data** ✅ IN PROGRESS — `backend/scripts/collect_hiring_data.py` scrapes Google Jobs via Bright Data SERP for 14 defense/tech companies and stores results in the `hiring_signals` SQLite table. `HiringSignal` model added to `models.py`. `score_companies()` now accepts optional `db` param and uses real `hiring_score` from DB, falling back to synthetic if not found. Run once with:
   ```bash
   cd backend && source .venv/bin/activate && python -m scripts.collect_hiring_data
   ```

4. **Real contract scraping** — The `services/discovery.py` uses Bright Data to hit USAspending.gov. Verify this pipeline end-to-end with `use_live_contracts=true`. Confirm tickers are correctly mapped from recipient names.

5. **Triggerware-style alerts** — Add a `POST /watch` endpoint that takes a ticker and webhook URL. When the next `/simulate` run changes a ticker's signal from HOLD→BUY or AVOID→BUY, fire the webhook. Store watches in a new `watches` SQLite table.

6. **Frontend polish** — Add row hover state to the scores table. Add a "last updated" timestamp to the Agent scores card. Add a download-CSV button for the scores.

7. **Clean up debug artifacts** — Remove the `GET /debug-thesis` endpoint from `main.py`. Remove debug `print` statements from `sentiment.py` and `thesis.py` before submission.

---

## API keys (in `backend/.env`)

| Env var | What it's for |
|---|---|
| `BRIGHTDATA_ENABLED` | Set to `true` to enable live Bright Data SERP calls (evidence + discovery). Set to `false` for seeded mode. |
| `BRIGHTDATA_SERP_KEY` | Bright Data API key for SERP zone requests |
| `BRIGHTDATA_SERP_ZONE` | Bright Data zone name (currently `serp_api1`) |
| `AIML_API_KEY` | AI/ML API key — used for both thesis generation and sentiment scoring via `gpt-4o-mini`. This is the **hackathon prize-eligible** API. |
| `GROQ_API_KEY` | No longer used in production code. Was used before AI/ML API switch. Can be removed from `.env`. |
| `GEMINI_API_KEY` | Not currently used anywhere in the codebase. Reserved for future use. |

---

## How to run

```bash
# Terminal 1 — Backend
cd /path/to/contract-alpha/backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd /path/to/contract-alpha/frontend
npm run dev
# Open http://localhost:3000

# Terminal 3 — Testing
# Quick API test
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"cutoff_date":"2024-01-01","horizon_months":12,"use_live_contracts":false}' \
  | python3 -m json.tool | grep -A1 '"thesis"\|"sentiment_score"' | head -40

# Clear sentiment cache (forces fresh AI/ML API calls)
sqlite3 backend/contract_alpha.db "DELETE FROM serp_cache WHERE query LIKE 'sentiment_aiml:%';"

# Clear evidence cache (forces fresh Bright Data calls)
sqlite3 backend/contract_alpha.db "DELETE FROM serp_cache WHERE query NOT LIKE 'sentiment%';"

# View all cache entries
sqlite3 backend/contract_alpha.db "SELECT query, substr(response_json,1,60) FROM serp_cache;"
```

---

## Key technical decisions

### Why AI/ML API instead of Groq
Groq was the original LLM provider. Switched to AI/ML API because:
1. **Hackathon prize eligibility** — the WebDataUnlocked hackathon has an AI/ML API sponsor track; using their API makes us eligible for that prize.
2. **Model quality** — `gpt-4o-mini` produces better structured output than `llama3-8b-8192` for the bullet-point thesis format.

### Why LLM-based sentiment (no SERP)
Bright Data news SERP (Bright Data zone `serp_api1` with `tbm=nws`) was returning empty `organic` arrays. Rather than debug the zone format before the hackathon deadline, we switched to prompting `gpt-4o-mini` directly with the company name and year. This always returns a non-zero score and doesn't require an external SERP call. Tradeoff: score reflects LLM training bias, not real-time news.

### Why parallel LLM calls
With 10+ companies and sequential Groq/AI/ML API calls at ~1–2s each, the simulation was taking 20–30s. Using `ThreadPoolExecutor(max_workers=5)` in both `generate_theses` and `get_sentiment_scores` drops total LLM time to ~3–5s (bounded by the slowest single call).

### Why SQLite cache
All SERP and sentiment results are cached in the `serp_cache` table (SQLite). This means the second run with the same cutoff date is nearly instant and doesn't burn API credits. Cache keys: `sentiment_aiml:{ticker}:{year}` for sentiment, raw query string for SERP evidence.

### Scoring weights
- 35% contract growth — primary signal (the whole premise of the app)
- 25% hiring growth — operational ramp-up indicator, leads contract execution
- 25% award size — log-normalized total $ awarded, favors larger contract winners
- 15% sentiment — weakest weight because it's currently LLM-estimated, not real-time

### Evidence returns a list, not a single dict
Changed `_parse_serp_response` to return `list[dict]` (up to 3 items) so the frontend can show multiple sources per company. The `Score` TypeScript type has `evidence: {...}[]`. The fallback is always a single-item list.

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
  main.py              — FastAPI app, build_simulation() orchestrates everything
  models.py            — SQLAlchemy models (Contract, Job, SerpCache)
  seed.py              — Seeds DB with synthetic contract + job data
  services/
    backtest.py        — yfinance backtest vs SPY
    config.py          — load_env(), env_bool() helpers
    contracts.py       — Query contracts from DB or live
    discovery.py       — Bright Data live contract discovery → tickers
    evidence.py        — Bright Data SERP for contract evidence (list[dict])
    jobs.py            — Hiring signal computation
    scoring.py         — Weighted composite scoring; uses real hiring_signals from DB if available
  scripts/
    __init__.py        — Empty package marker
    collect_hiring_data.py — One-time Bright Data scraper → hiring_signals table
    sentiment.py       — AI/ML API sentiment (parallel, cached)
    thesis.py          — AI/ML API 3-bullet thesis generation (parallel)
    timegate.py        — Date-gating utilities
frontend/
  app/
    page.tsx           — Main UI (table, chart, backtest reveal)
    globals.css        — Tailwind base styles
    layout.tsx         — Root layout
```
