"""Tests for the autonomous self-tuning controller and its safety rails."""

import pytest

from engine.strategy.autotune import AutoTuner, clamp_params, TUNABLE_BOUNDS


# ---- guardrails: clamp + whitelist ----

def test_clamp_drops_non_whitelisted_params():
    # Hard risk caps must never come through the AI's tuning path.
    out = clamp_params({"daily_loss_limit": 5.0, "max_exposure": 9999,
                        "max_drawdown_pct": 99, "min_edge": 0.05})
    assert out == {"min_edge": 0.05}


def test_clamp_bounds_values():
    out = clamp_params({"min_edge": 999, "min_model_prob": 0.01,
                        "kelly_fraction": 5.0})
    assert out["min_edge"] == TUNABLE_BOUNDS["min_edge"][1]        # clamped high
    assert out["min_model_prob"] == TUNABLE_BOUNDS["min_model_prob"][0]  # clamped low
    assert out["kelly_fraction"] == TUNABLE_BOUNDS["kelly_fraction"][1]


def test_clamp_ignores_non_numeric_and_nulls():
    out = clamp_params({"min_edge": None, "fee_buffer": "abc", "kelly_fraction": 0.2})
    assert out == {"kelly_fraction": 0.2}


def test_clamp_vol_lookback_is_int():
    out = clamp_params({"vol_lookback_s": 300.9})
    assert out["vol_lookback_s"] == 300 and isinstance(out["vol_lookback_s"], int)


# ---- experiment / evaluate / revert ----

def test_experiment_not_ready_until_min_settles():
    t = AutoTuner(min_eval_settles=10)
    t.start_experiment(prev={"min_edge": 0.04}, changed={"min_edge": 0.06},
                       pnl=0.0, settles=0)
    assert not t.ready_to_eval(5)
    assert t.ready_to_eval(10)


def test_change_that_improves_ev_is_kept():
    t = AutoTuner(min_eval_settles=10)
    t.baseline_ev = 0.0
    t.start_experiment({"min_edge": 0.04}, {"min_edge": 0.06}, pnl=0.0, settles=0)
    # +$20 over 10 settles => EV +2.0/settle, better than baseline 0.
    res = t.evaluate(pnl=20.0, settles=10)
    assert res["decision"] == "keep" and res["revert_to"] is None
    assert t.baseline_ev == pytest.approx(2.0)


def test_change_that_worsens_ev_is_reverted():
    t = AutoTuner(min_eval_settles=10)
    t.baseline_ev = 1.0
    prev = {"min_edge": 0.04}
    t.start_experiment(prev, {"min_edge": 0.10}, pnl=0.0, settles=0)
    # -$5 over 10 settles => EV -0.5/settle, worse than baseline 1.0 => revert.
    res = t.evaluate(pnl=-5.0, settles=10)
    assert res["decision"] == "revert"
    assert res["revert_to"] == prev
    assert t.baseline_ev == pytest.approx(1.0)  # baseline unchanged on revert


def test_history_records_outcomes_for_memory():
    t = AutoTuner(min_eval_settles=2)
    t.start_experiment({"min_edge": 0.04}, {"min_edge": 0.06}, 0.0, 0)
    t.evaluate(10.0, 2)
    assert len(t.recent_outcomes()) == 1
    assert t.recent_outcomes()[0]["changed"] == {"min_edge": 0.06}
