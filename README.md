# KalshiBot

AI-assisted trading bot for Kalshi's short-duration crypto markets (15-minute
`KXBTC15M` and hourly `KXBTCD` BTC up/down binaries), with a fast quant core for
pricing/execution, an optional LLM meta-layer (Claude + Gemini) for strategy and
risk supervision, and a web admin panel to manage everything.

> **Reality check:** the goal is **expected value net of fees + spread**, not a
> vanity win-rate. "Zero delay" is impossible — we minimize latency to the WS
> feed + in-process decision (tens of ms). Crypto markets are fairly efficient;
> **validate in paper mode before scaling real capital.**

## Architecture

```
                Coinbase WS (spot)  ─┐
                                     ├─►  Quant core (sub-second, deterministic)
                Kalshi WS (book)   ──┘     fair value → edge → risk caps → order
                                                │
   Claude + Gemini (every ~30s) ──► risk dial   │
        advisory only ───────────────┘          ▼
                                          OrderManager (paper | live)
                                                │
                                          Postgres / SQLite (telemetry)
                                                │
                          FastAPI REST + WS  ◄───┘
                                                │
                                   Next.js admin panel (Vercel)
```

- **`engine/`** — Python 3.12 / asyncio / FastAPI trading engine.
  - `auth/` RSA-PSS request signer + rate-limited REST client
  - `data/` Kalshi order-book WS + Coinbase spot WS
  - `pricing/` driftless-GBM fair value `P(close past strike)` + rolling vol
  - `strategy/` edge vs the live book, order-book imbalance, near-close pinning
  - `risk/` hard caps, fractional-Kelly sizing, drawdown breaker, kill switch
  - `execution/` paper + live order manager with per-window position tracking
  - `llm/` optional Claude + Gemini meta-layer (advisory risk dial / strategy)
  - `telemetry/` SQLAlchemy store (SQLite dev, Postgres prod)
  - `api/` FastAPI control endpoints + live `/api/stream` WebSocket
- **`web/`** — Next.js + Tailwind admin panel (deploy to Vercel).

## Safety model

- The engine **always boots in paper mode.** Live trading requires an explicit
  toggle in the admin panel.
- The risk engine enforces hard caps **server-side**, regardless of what the
  strategy or LLM requests: per-trade, per-window, total-exposure, daily-loss,
  and a drawdown circuit breaker. A global **kill switch** flattens and pauses.

## Local development

### Engine

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r engine/requirements.txt
cp .env.example .env          # fill in values (defaults run in paper/demo)
python -m engine.main         # serves http://localhost:8000
pytest                        # run the test suite
```

The engine runs with **no credentials** against public market data. To place
orders (even on demo) set `KALSHI_API_KEY_ID` and the RSA key.

### Admin panel

```bash
cd web
npm install
cp .env.example .env.local    # point NEXT_PUBLIC_ENGINE_URL at the engine
npm run dev                   # http://localhost:3000
```

## Deployment

- **Engine → Railway** (always-on container). Connect this repo; Railway builds
  the `Dockerfile`. Add a Postgres plugin and set `DATABASE_URL` to its
  `postgresql+asyncpg://…` URL, plus the env vars from `.env.example`.
- **Admin panel → Vercel.** Set root directory to `web/` and the
  `NEXT_PUBLIC_ENGINE_URL` / `NEXT_PUBLIC_ENGINE_WS` env vars to the Railway URL.

## What you need to plug in (when ready)

| Secret | Where | Notes |
| --- | --- | --- |
| `KALSHI_API_KEY_ID` + RSA key | Railway env | From Kalshi → Account → API. Confirm your account is approved for API trading. |
| `ADMIN_PASSWORD`, `JWT_SECRET` | Railway env | Protects the admin panel. |
| `DATABASE_URL` | Railway env | Postgres plugin URL. |
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | Railway env | Optional; enables the LLM meta-layer. |

Start on `KALSHI_ENV=demo` + paper mode. Once the model shows positive
paper P&L across many windows, switch to `prod` and flip live with tight caps.

## Roadmap

- **Phase 1 (done):** feeds, fair value, edge, risk caps, paper+live execution,
  telemetry, FastAPI + WS, admin panel, deploy config.
- **Phase 2:** richer multi-order hedging/scaling, calibration loop (Brier
  score) + LLM-proposed parameter tuning, hourly BRRNY settlement specifics,
  alerts.
- **Phase 3:** backtesting harness on historical order-book data, latency
  tuning, more crypto/markets.
