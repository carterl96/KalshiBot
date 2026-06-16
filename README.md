# KalshiBot

AI-assisted trading bot for Kalshi's short-duration crypto markets (15-minute
`KXBTC15M` and hourly `KXBTCD` BTC up/down binaries), with a fast quant core for
pricing/execution, an LLM meta-layer (Claude + Gemini) for strategy and risk
supervision, and a web admin panel to manage everything.

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
                                          WindowManager (scale-in/hedge/exit)
                                                │
                                          Postgres / SQLite (telemetry)
                                          CalibrationTracker (Brier score)
                                          TickCollector (backtest data)
                                                │
                          FastAPI REST + WS  ◄───┘
                                                │
                                   Next.js admin panel (Vercel)
```

- **`engine/`** — Python 3.12 / asyncio / FastAPI trading engine.
  - `auth/` RSA-PSS request signer + rate-limited REST client (exp. backoff + jitter)
  - `data/` Kalshi orderbook WS + Coinbase spot WS + CF Benchmarks BRRNY feed
  - `pricing/` driftless-GBM fair value `P(close past strike)` + rolling vol
  - `strategy/` edge vs live book, order-book imbalance, near-close pinning
  - `risk/` hard caps, fractional-Kelly sizing, drawdown breaker, kill switch
  - `execution/` paper + live order manager + **WindowManager** (multi-order, hedge, exit)
  - `llm/` Claude + Gemini meta-layer: risk dial, regime, strategy, parameter proposals
  - `alerts/` Discord/Slack-compatible webhook alerts on kill/breaker/equity drop
  - `backtest/` BacktestRunner: replay historical Tick snapshots through the pipeline
  - `telemetry/` SQLAlchemy store (SQLite dev, Postgres prod), calibration, proposals
  - `api/` FastAPI control endpoints + live `/api/stream` WebSocket
- **`web/`** — Next.js + Tailwind admin panel (deploy to Vercel).

## Safety model

- The engine **always boots in paper mode.** Live trading requires an explicit
  toggle in the admin panel (with a confirmation modal).
- The risk engine enforces hard caps **server-side**, regardless of what the
  strategy or LLM requests: per-trade, per-window, total-exposure, daily-loss,
  and a drawdown circuit breaker. A global **kill switch** flattens and pauses.

## Phase 2 features

### Multi-order hedging and scaling (WindowManager)

Each 15-minute/hourly window gets a state machine (`engine/execution/window.py`):
- **Scale in** when the edge persists: up to 3 entries per window in the same direction
- **Hedge** when the model turns against us: buy the opposite side when `model_prob_opposite ≥ 0.65`
- **Take profit** in the final 30 seconds when model probability is ≥ 80% in our favour
- **Cut loss** in the final 60 seconds when model probability is ≤ 25% in our favour

### Calibration loop (Brier score)

Every evaluation tick is recorded as a prediction. After settlement, outcomes are
resolved and the Brier score is computed: `mean((model_prob - outcome)²)`. The
Dashboard shows calibration bands, sharpness, and resolution count.

### LLM parameter proposals

Every 10 LLM advisory cycles (~5 minutes), if ≥20 predictions have resolved,
the bot asks Claude/Gemini to review calibration data and recent losses and
propose parameter changes (e.g. "raise min_edge from 0.04 to 0.06"). Proposals
surface in the Controls page as one-click Apply/Dismiss actions.

### Strategy profiles

The LLM's `active_strategy` field actually changes engine behavior:
- `edge` — standard min_edge threshold
- `conservative` — min_edge × 1.5 (requires stronger edge to enter)
- `near_close` — only trade in the final 60 seconds of a window (highest certainty)

### BRRNY hourly settlement

Hourly `KXBTCD` markets settle on the CF Benchmarks Bitcoin Reference Rate NY
(BRRNY), not the live spot price. The engine fetches BRRNY at settlement and
falls back to the Coinbase spot with a warning if the API is unavailable.

### Alerts (Discord/Slack webhook)

Set `ALERT_WEBHOOK_URL` to a Discord/Slack incoming webhook. Alerts fire on:
kill switch, circuit breaker trip, daily loss limit, equity drop >N%, engine
start/stop, and large settlement P&L.

### Backtesting

`POST /api/backtest` replays historical Tick snapshots (spot, sigma, tau, ask,
outcome) through the pricing/risk/execution pipeline and returns P&L, win rate,
and Brier score. The Backtest page in the admin panel provides a UI. The engine
automatically collects live tick data (1 snapshot/minute/side) in the DB for
replay via `GET /api/ticks?series=KXBTC`.

### Tick data export

`GET /api/ticks?ticker=KXBTC-001` or `?series=KXBTC` exports stored book
snapshots with outcomes, ready to paste into the Backtest page.

## Admin Panel (7 pages)

- **Dashboard** — equity curve, P&L, open positions, calibration metrics
- **Markets** — live Kalshi book vs model probability, edge heat-map, open position markers
- **Controls** — start/stop, paper↔live toggle, risk params, AI proposals (one-click apply)
- **AI Log** — source filter, latest LLM guidance card, full decision feed
- **History** — trade log, win rate, cumulative P&L column, CSV export
- **Backtest** — run historical simulations with custom params
- **Setup** — Kalshi credentials, LLM keys, trading params, alert webhook — all in-app

## Local development

### Engine

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r engine/requirements.txt
cp .env.example .env          # fill in values (defaults run in paper/demo)
python -m engine.main         # serves http://localhost:8000
pytest                        # run the test suite (70 tests)
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

## Configuration

You can configure the bot either from the **web Setup page** (recommended) or
via **environment variables** (good for automated deploys).

### Setup page

Sign in → **Setup** tab → enter your Kalshi environment, API Key ID, RSA private
key, optional Claude/Gemini keys, alert webhook URL, and trading parameters →
**Test Kalshi connection** → **Save & apply** (hot-reloads the engine). Secrets
are never sent back to the browser — only masked `•••• set` indicators.

### Environment variables

| Secret | Where | Notes |
| --- | --- | --- |
| `ADMIN_PASSWORD`, `JWT_SECRET` | Railway env | Protect the admin panel. |
| `APP_SECRET` | Railway env | Long random string; encrypts Setup-page secrets. Keep stable. |
| `DATABASE_URL` | Railway env | Postgres plugin URL. |
| `KALSHI_API_KEY_ID` + RSA key | Railway env *or* Setup page | From Kalshi → Account → API. |
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | Railway env *or* Setup page | Optional LLM meta-layer. |
| `ALERT_WEBHOOK_URL` | Railway env *or* Setup page | Discord/Slack webhook for alerts. |

Start on `demo` + paper mode. Once the model shows positive paper P&L across many
windows, switch to `prod` and flip live with tight caps.

## Roadmap

- **Phase 1 (done):** feeds, fair value, edge, risk caps, paper+live execution,
  telemetry, FastAPI + WS, admin panel, deploy config.
- **Phase 2 (done):** multi-order hedging/scaling (WindowManager), calibration
  loop (Brier score), LLM parameter proposals, BRRNY hourly settlement,
  Discord/Slack alerts, strategy profiles, backtesting harness, tick data
  collection, enhanced admin panel (calibration, proposals, history export,
  backtest page).
- **Phase 3:** ensemble/critic LLM tuning, automated backtesting on collected
  ticks, latency optimization, additional crypto markets, multi-user SaaS auth.
