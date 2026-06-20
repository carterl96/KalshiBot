"""Autonomous strategy self-tuning: an LLM-guided online optimizer with rails.

The vision: the AI continuously adapts the strategy itself, rather than a human
hand-tuning parameters. This module is the safety-railed control loop that makes
that possible.

How it stays safe (this is the important part — autonomy over real money):

  * **Whitelist** — the AI may only touch *strategy* knobs (edge thresholds,
    conviction floor, stop levels, Kelly fraction). It can NEVER loosen the hard
    risk caps (daily loss limit, max exposure, max drawdown, per-trade/-window
    sizing) — those stay human-controlled circuit breakers.
  * **Clamp** — every proposed value is clamped to a sane bounded range.
  * **One change at a time, then measure** — after applying a change we run an
    "experiment": hold it for a minimum number of settled windows, then compare
    realized EV (P&L per settled window) against the pre-change baseline.
  * **Auto-revert** — if the change made EV worse, we roll back to the previous
    values. Good changes are kept and become the new baseline. This is a greedy
    hill-climb where the LLM proposes the *direction* and reality is the judge.
  * **Memory** — every experiment's outcome (kept/reverted, EV before/after) is
    logged, so the loop doesn't oscillate and the LLM can be told what already
    failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Tunable strategy parameters and their hard clamp bounds. Anything NOT in here
# is off-limits to the AI (notably the risk caps).
TUNABLE_BOUNDS: dict[str, tuple[float, float]] = {
    "min_edge": (0.01, 0.15),
    "min_model_prob": (0.50, 0.85),
    "fee_buffer": (0.0, 0.05),
    "kelly_fraction": (0.05, 0.50),
    "stop_model_floor": (0.20, 0.45),
    "stop_model_drop": (0.10, 0.40),
    "stop_catastrophe_drop": (0.20, 0.50),
    "vol_lookback_s": (120, 3600),
}

# Which engine object each tunable lives on (so the engine can route updates).
WINDOW_PARAMS = {"stop_model_floor", "stop_model_drop", "stop_catastrophe_drop"}
RISK_PARAMS = {"kelly_fraction"}
# everything else in TUNABLE_BOUNDS lives on Settings


def clamp_params(raw: dict) -> dict:
    """Keep only whitelisted params and clamp each to its safe range.

    Returns a clean dict of {param: value}. Anything outside the whitelist or
    non-numeric is dropped — the AI cannot escape these rails.
    """
    out: dict[str, float] = {}
    for key, lo_hi in TUNABLE_BOUNDS.items():
        if key not in raw or raw[key] is None:
            continue
        try:
            val = float(raw[key])
        except (TypeError, ValueError):
            continue
        lo, hi = lo_hi
        val = min(max(val, lo), hi)
        if key == "vol_lookback_s":
            val = int(val)
        out[key] = val
    return out


@dataclass
class Experiment:
    prev: dict            # values before the change (for revert)
    changed: dict         # the values we applied
    baseline_ev: float    # EV/settle before the change
    cp_pnl: float         # cumulative realized P&L at change time
    cp_settles: int       # settled-window count at change time


@dataclass
class AutoTuner:
    """Stateful, side-effect-free controller. The engine feeds it cumulative
    realized P&L + settled-window count and performs the actual apply/revert."""

    min_eval_settles: int = 10     # windows to observe before judging a change
    revert_margin: float = 0.0     # require EV to be worse by > this to revert
    baseline_ev: float = 0.0       # current rolling EV/settle under the live config
    experiment: Optional[Experiment] = None
    history: list[dict] = field(default_factory=list)

    @staticmethod
    def _ev(pnl: float, settles: int, cp_pnl: float, cp_settles: int) -> Optional[float]:
        d = settles - cp_settles
        return (pnl - cp_pnl) / d if d > 0 else None

    def start_experiment(self, prev: dict, changed: dict, pnl: float, settles: int) -> None:
        self.experiment = Experiment(
            prev=dict(prev), changed=dict(changed),
            baseline_ev=self.baseline_ev, cp_pnl=pnl, cp_settles=settles,
        )

    def ready_to_eval(self, settles: int) -> bool:
        return (
            self.experiment is not None
            and (settles - self.experiment.cp_settles) >= self.min_eval_settles
        )

    def evaluate(self, pnl: float, settles: int) -> dict:
        """Judge the active experiment. Returns a decision dict:
        {"decision": "keep"|"revert", "revert_to": dict|None, "outcome": {...}}.
        Clears the experiment."""
        exp = self.experiment
        assert exp is not None, "evaluate() with no active experiment"
        ev_after = self._ev(pnl, settles, exp.cp_pnl, exp.cp_settles)
        worse = ev_after is not None and ev_after < exp.baseline_ev - self.revert_margin
        decision = "revert" if worse else "keep"
        outcome = {
            "changed": exp.changed,
            "ev_before": round(exp.baseline_ev, 4),
            "ev_after": round(ev_after, 4) if ev_after is not None else None,
            "decision": decision,
        }
        if decision == "keep" and ev_after is not None:
            self.baseline_ev = ev_after
        self.history.append(outcome)
        revert_to = dict(exp.prev) if decision == "revert" else None
        self.experiment = None
        return {"decision": decision, "revert_to": revert_to, "outcome": outcome,
                "ev_after": ev_after}

    def recent_outcomes(self, n: int = 5) -> list[dict]:
        return self.history[-n:]
