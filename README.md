# ContractAlpha

Government contract intelligence platform built for the **WebDataUnlocked Hackathon** (Bright Data sponsorship track).

Pulls US federal contract award data, maps recipients to public tickers, scores them on 4 signals (contract growth, hiring, award size, sentiment), surfaces SAM.gov pre-award pipeline notices, generates analyst-style theses via AI, and backtests the resulting portfolio against SPY.

APP URL: https://contract-alpha-pink.vercel.app/

## Signals

| Signal | Source | Weight |
|---|---|---|
| Contract growth (relative to peers) | USAspending.gov via Bright Data | 35% |
| Hiring growth | Bright Data Google Jobs SERP | 20% |
| Award size (log-normalized) | USAspending.gov | 30% |
| Sentiment | AI/ML API `gpt-4o-mini` | 15% |
| Pipeline (pre-award notices) | SAM.gov Opportunities API | displayed, not scored |

Signal thresholds: **BUY** > 0.35 · **HOLD** > 0.15 · **AVOID** otherwise

## Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and fill in env vars (see below)
cp .env.example .env

python seed.py
uvicorn main:app --reload --port 8000
```

### Environment variables (`backend/.env`)

```bash
BRIGHTDATA_ENABLED=true
BRIGHTDATA_SERP_KEY=<your Bright Data SERP key>
BRIGHTDATA_SERP_ZONE=serp_api1
AIML_API_KEY=<your AI/ML API key>
SAM_API_KEY=<your SAM.gov API key>   # free at sam.gov → Account Details → Public API Keys
```

### Key endpoints

- `POST /simulate` — `{ "cutoff_date": "2022-01-01", "horizon_months": 12, "use_live_contracts": true }`
  - `use_live_contracts: true` (default) fetches real USAspending data — takes 2–3 min
  - `use_live_contracts: false` uses seeded DB — returns in ~10s, good for testing
- `GET /signals?cutoff_date=2022-01-01&horizon_months=12`
- `GET /contracts?cutoff_date=2022-01-01`
- `GET /jobs?cutoff_date=2022-01-01`
- `POST /seed` — reseed the SQLite DB with synthetic data

### Fast test (seeded data)

```bash
curl -s -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"cutoff_date":"2022-01-01","horizon_months":12,"use_live_contracts":false}' \
  | python3 -m json.tool | grep -E '"ticker"|"signal"|"score"' | head -30
```

## Frontend

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
# Open http://localhost:3000
```

Select a cutoff date (default: 2022-01-01) and horizon, then click **Run Simulation**. The UI shows a scores table with signal badges, pipeline notices, analyst thesis bullets, evidence links, a signal composition bar chart, and a backtest vs SPY with a reveal button.

## Data collection (one-time)

```bash
# Collect real hiring signals via Bright Data Google Jobs SERP
cd backend && source .venv/bin/activate && python -m scripts.collect_hiring_data
```

Requires `BRIGHTDATA_SERP_KEY`. Results stored in `hiring_signals` SQLite table and used in subsequent scoring runs.

## DB

SQLite file: `backend/contract_alpha.db`

```
contracts       — id, ticker, company, award_date, amount, agency
jobs            — id, ticker, date, open_roles, mfg_roles, eng_roles
serp_cache      — id, query (unique), response_json, created_at
hiring_signals  — id, ticker, company, collection_date, total_roles, tech_roles, ops_roles, hiring_score
```
