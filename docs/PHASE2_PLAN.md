# KalshiBot — Phase 2 Plan of Attack

Status snapshot (2026-06-19): engine **stopped**, `AUTOSTART=false`, `kalshi_env=prod`,
`llm_enabled=false`. Known open issues carried in: balance drift (bot vs Kalshi),
panic-selling stop-loss, AI token burn / no failover, dev-heavy + non-mobile UI.

## Guiding principle

**Optimize expected value net of fees, not win rate.** A high green rate is an
*output* of selective, high-conviction trading — not a target to chase by
overpaying for favorites. Realistic goal: 65–75% green **while net-profitable**,
achieved via selectivity + the near-settlement regime, not by buying expensive
contracts.

---

## Phase 2A — Strategy & risk intelligence (paper-safe; do first)

Goal: a strategy that wins more often *and* makes money, and a stop-loss that
doesn't panic on noise.

1. **Smarter stop-loss** (replaces pure price stop): — **DONE**
   - DONE: **model-aware** stop — cuts when fair probability deteriorates
     (below floor, or far below entry thesis), not on price wiggles.
   - DONE: **debounce** (N consecutive adverse reads) + post-entry **grace**.
   - DONE: **catastrophe backstop** — wide hard price stop fires immediately.
   - TODO: explicit σ√τ vol-scaling of the stop *distance* (probability-based
     stop already adapts to vol implicitly; explicit scaling is a refinement).
2. **Entry selectivity** (raise green rate while keeping +EV):
   - DONE: minimum model-confidence filter (`min_model_prob`, skips coin-flips).
   - TODO: explicit near-close preference + regime / time-of-day awareness
     (overnight = thin book → require more edge or stand down).
3. **Calibration-driven auto-tuning** of thresholds (min_edge, stop distance,
   min model prob) from realized results. — TODO

## Phase 2B — AI layer (cost-controlled, resilient, adaptive)

4. **Fixed-cadence LLM** calls — DONE: routine 30s call uses cheap models
   (Claude Haiku / Gemini Flash defaults), deep param-review uses a configurable
   (optionally larger) review model, and a **hard daily token budget**
   (`TokenBudget`, resets UTC-daily) the layer self-limits to. Usage surfaced in
   the health snapshot (`llm_usage`).
5. **Provider failover** — DONE: Claude is primary; on error/empty it fails over
   to Gemini (no more always-calling-both, which doubled cost). Token usage is
   parsed from both providers' responses.
   - TODO: confirm it's firing live once keys are configured (watch `llm_usage`).
6. **Regime detection + param proposals** — partial (advise returns a regime;
   proposals run on a cadence). TODO: deterministic de-risk/pause when
   calibration degrades ("strategy stopped working" = regime shift).
7. **Strategy memory**: Postgres performance table (per strategy/regime: win
   rate, EV net of fees, Brier, sample size) + a **"Strategies" tab** showing
   what's actually worked. AI reads a compact summary; proposals surface for
   one-click apply (no blind live RL). — TODO

## Phase 2C — Money-accuracy (gate before going live again)

8. **Balance reconciliation** from Kalshi `get_balance` as ground truth — DONE
   (re-sync after every live fill + every ~30s; kills the $116-vs-$96 drift).
9. **Real fill confirmation** — DONE: parse fill_count + fees from the order
   response; credit only what filled (no phantom positions on a killed FOK).
   NOTE: response field names are defensive guesses — verify against a real
   live order response before trusting in production.
10. **Order throttle** — DONE: per-(ticker,side) cooldown after a rejected
    order so the 0.5s eval loop stops re-sending the same failing order.

## Phase 2D — UX, notifications, SaaS groundwork

11. **UI polish** — DONE: full consumer-fintech redesign (typechecks + builds).
    - responsive shell (mobile), plain-language dashboard, P&L range toggle.
    - Controls: Conservative/Balanced/Aggressive risk presets, raw params behind
      an "Advanced" disclosure, plain-language sections.
    - Markets/History/AI/Backtest/Setup rewritten in plain language with
      "what do these mean?" explainers; new Section/Disclosure/Toggle/Select
      primitives.
    - TODO (future): expose the new strategy knobs (min_model_prob, stop params,
      LLM budget) in the UI; wire Toggle into Setup checkboxes.
12. **Web push notifications** via OneSignal/FCM as a PWA (iOS 16.4+ with
    Add-to-Home-Screen). Alerts: errors, out-of-money, circuit breaker, big
    win/loss. — TODO (needs a OneSignal/FCM account + keys from operator).
13. **SaaS groundwork**: all Kalshi crypto markets → later multi-user/tenancy.
    — TODO

---

## Manual items for the operator

- Make the GitHub repo **private** (Settings → Danger Zone → visibility).
- **Rotate** Anthropic + Gemini API keys (previously exposed in chat + logs).
