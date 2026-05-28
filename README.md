# ContractAlpha

Hackathon MVP that finds investment signals in US government contracts and hiring data, then backtests what the model would have bought against real stock returns.

## Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed.py
uvicorn main:app --reload --port 8000
```

Key endpoints:

- `POST /seed`
- `POST /simulate` with `{ "cutoff_date": "2024-01-01", "horizon_months": 12 }`
- `GET /signals?cutoff_date=2024-01-01&horizon_months=12`
- `GET /contracts?cutoff_date=2024-01-01`
- `GET /jobs?cutoff_date=2024-01-01`

Simulation discovery pulls top visible USAspending contract recipients, maps public US equities through Yahoo Finance search, enriches up to five companies with Bright Data SERP evidence when `BRIGHTDATA_ENABLED=true`, and falls back to a broader public defense/infrastructure universe when live APIs are unavailable. Every data path applies the TimeGate cutoff and excludes rows dated after the selected cutoff.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.
