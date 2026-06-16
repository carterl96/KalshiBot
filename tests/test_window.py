"""Tests for the per-window position state machine."""

import pytest
from engine.execution.window import WindowManager


def make_mgr(**kw):
    defaults = dict(
        max_entries=3,
        hedge_trigger_prob=0.65,
        profit_take_tau_s=30.0,
        profit_take_min_prob=0.80,
        stop_loss_tau_s=60.0,
        stop_loss_max_prob=0.25,
    )
    defaults.update(kw)
    return WindowManager(**defaults)


# ---- entry / scale-in ----

def test_fresh_ticker_can_entry():
    m = make_mgr()
    assert m.can_entry("KXBTC-123", "up") is True


def test_first_entry_recorded_sets_direction():
    m = make_mgr()
    m.record_entry("KXBTC-123", "up")
    assert m.get("KXBTC-123").direction == "up"
    assert m.get("KXBTC-123").entries == 1


def test_can_scale_in_same_direction():
    m = make_mgr()
    m.record_entry("T", "up")
    assert m.can_scale_in("T", "up") is True


def test_cannot_scale_in_opposite_direction():
    m = make_mgr()
    m.record_entry("T", "up")
    assert m.can_scale_in("T", "down") is False


def test_max_entries_blocks_further_buys():
    m = make_mgr(max_entries=2)
    m.record_entry("T", "up")
    m.record_entry("T", "up")
    assert m.can_entry("T", "up") is False
    assert m.can_scale_in("T", "up") is False


def test_entry_label_returns_scale_in_after_first():
    m = make_mgr()
    assert m.entry_label("T", "up") == "entry"
    m.record_entry("T", "up")
    assert m.entry_label("T", "up") == "scale_in"


# ---- hedge ----

def test_should_hedge_when_model_turned():
    m = make_mgr(hedge_trigger_prob=0.65)
    m.record_entry("T", "up")
    # model prob for DOWN side is now 0.70 — above trigger
    assert m.should_hedge("T", opposite_model_prob=0.70) is True


def test_should_not_hedge_when_below_trigger():
    m = make_mgr(hedge_trigger_prob=0.65)
    m.record_entry("T", "up")
    assert m.should_hedge("T", opposite_model_prob=0.60) is False


def test_should_not_hedge_twice():
    m = make_mgr()
    m.record_entry("T", "up")
    m.record_hedge("T")
    assert m.should_hedge("T", opposite_model_prob=0.90) is False


def test_should_not_hedge_without_position():
    m = make_mgr()
    assert m.should_hedge("T", opposite_model_prob=0.90) is False


# ---- exits ----

def test_take_profit_near_close():
    m = make_mgr(profit_take_tau_s=30.0, profit_take_min_prob=0.80)
    m.record_entry("T", "up")
    assert m.should_take_profit("T", "up", model_prob=0.85, tau_seconds=15.0) is True


def test_no_take_profit_wrong_side():
    m = make_mgr()
    m.record_entry("T", "up")
    assert m.should_take_profit("T", "down", model_prob=0.90, tau_seconds=10.0) is False


def test_no_take_profit_too_early():
    m = make_mgr(profit_take_tau_s=30.0)
    m.record_entry("T", "up")
    assert m.should_take_profit("T", "up", model_prob=0.90, tau_seconds=60.0) is False


def test_cut_loss_near_close():
    m = make_mgr(stop_loss_tau_s=60.0, stop_loss_max_prob=0.25)
    m.record_entry("T", "up")
    assert m.should_cut_loss("T", "up", model_prob=0.20, tau_seconds=45.0) is True


def test_no_cut_loss_when_fine():
    m = make_mgr()
    m.record_entry("T", "up")
    assert m.should_cut_loss("T", "up", model_prob=0.50, tau_seconds=45.0) is False


# ---- settle / closed state ----

def test_settle_blocks_new_entries():
    m = make_mgr()
    m.record_entry("T", "up")
    m.settle("T")
    assert m.can_entry("T", "up") is False
    assert m.can_scale_in("T", "up") is False
    assert m.should_hedge("T", 0.90) is False


def test_cleanup_removes_closed_windows():
    import time
    m = make_mgr()
    m.record_entry("T", "up")
    m.settle("T")
    # Force the opened_at to be old
    m.get("T").opened_at = time.time() - 9000
    m.cleanup_old(max_age_s=7200)
    assert "T" not in m._windows
