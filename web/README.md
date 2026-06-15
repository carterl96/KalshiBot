# KalshiBot Admin Panel

Next.js 14 (App Router) + Tailwind admin panel for the KalshiBot engine.

## Pages

- **Dashboard** — equity curve, P&L, cash, open positions (live via WebSocket).
- **Markets** — live Kalshi bid/ask vs the model's fair value and edge, with a
  close-time countdown (the "same pricing as Kalshi" view).
- **Controls** — start/stop, reset breakers, paper↔live toggle (with a
  confirmation modal), kill switch, and the risk-parameter form.
- **AI Log** — quant + LLM decision feed.
- **History** — trade/settlement log.

## Develop

```bash
npm install
cp .env.example .env.local   # point at your engine
npm run dev                  # http://localhost:3000
```

Sign in with the engine's `ADMIN_PASSWORD`.

### Environment

| Var | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_ENGINE_URL` | `http://localhost:8000` | Engine REST base URL |
| `NEXT_PUBLIC_ENGINE_WS` | `ws://localhost:8000` | Engine WebSocket base URL |

## Deploy (Vercel)

Set the project root directory to `web/` and configure
`NEXT_PUBLIC_ENGINE_URL` / `NEXT_PUBLIC_ENGINE_WS` to your Railway engine URL
(use `https://` / `wss://`).
