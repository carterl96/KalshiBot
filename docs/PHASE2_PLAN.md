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
   min model prob) from realized results. — TODO (sweep tool now exists; needs
   real data to tune against).

### Profit validation (the actual money lever) — partly DONE

No feature makes money if the core edge isn't real. Status:
- DONE: backtest runner now faithfully replays the **production** strategy
  (min_model_prob filter + model-aware exits) and charges **realistic Kalshi
  fees** (`engine/execution/fees.py`). Reports net P&L, fees, and **EV/trade**.
- DONE: parameter **sweep** (`engine/backtest/sweep.py`) ranks configs by
  EV/trade; **synthetic generator** (`engine/backtest/synthetic.py`) validates
  the machinery converts a known edge into profit net of fees and stands down
  with no edge. (`python -m engine.backtest.sweep`)
- **BLOCKER → real data**: we have NO stored ticks (engine has been off). The
  zero-risk way to get them is a **paper run** (engine on, paper mode): it
  collects ticks + calibration. Then backtest/sweep on real data tells us if a
  profitable config exists and what it is. Until then, profitability is unproven.
- KEY QUESTION the data answers: is our `fair_prob` (GBM + realized vol)
  better-calibrated than Kalshi's implied price? If not, there's no edge to
  harvest after fees, and the fix is the **pricing model**, not more features.

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
6. **Autonomous self-tuning** — DONE: the AI now adapts the strategy itself
   (`engine/strategy/autotune.py`), no manual clicks. Closed loop:
   propose (Gemini-primary) → clamp to safe bounds → apply → run an
   "experiment" for N settled windows → compare realized EV/settle vs the
   pre-change baseline → **auto-revert if worse, keep if better**. Outcomes are
   logged as the AI's memory and fed back into the next proposal so it doesn't
   repeat reverted changes.
   - Rails: AI may only touch whitelisted strategy knobs (edge, conviction,
     stops, Kelly); it can NEVER loosen hard risk caps. Auto-applies in paper;
     live requires `llm_autotune_live` opt-in.
   - Also fixed a latent bug: manual "apply proposal" only updated risk params,
     so strategy knobs (min_edge etc.) silently did nothing — now routed via the
     same `apply_param_overrides` path.
7. **Strategy memory**: autotune outcomes are logged (decisions, source=
   "autotune") and surfaced in the state snapshot (`autotune.recent_outcomes`).
   - TODO: a dedicated **"Strategies" tab** visualizing this history + per-regime
     performance. (Backend signal now exists.)

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
