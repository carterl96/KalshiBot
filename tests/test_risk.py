"""Tests for the risk engine: caps, sizing, circuit breaker, kill switch."""

from engine.risk.limits import RiskEngine, RiskParams


def make_engine(**overrides):
    params = RiskParams(
        max_per_trade=20.0, max_per_window=60.0, daily_loss_limit=50.0,
        max_exposure=200.0, max_drawdown_pct=15.0, kelly_fraction=0.25,
    )
    params.update(**overrides)
    return RiskEngine(params)


def test_positive_edge_sizes_a_trade():
    eng = make_engine()
    chk = eng.check(edge=0.10, price_prob=0.5, bankroll=1000.0,
                    window_exposure=0.0, total_exposure=0.0)
    assert chk.ok
    assert chk.quantity >= 1
    assert chk.size_usd <= 20.0 + 1e-9  # capped by max_per_trade


def test_per_trade_cap_enforced():
    eng = make_engine(max_per_trade=5.0)
    chk = eng.check(edge=0.3, price_prob=0.5, bankroll=100000.0,
                    window_exposure=0.0, total_exposure=0.0)
    assert chk.ok
    assert chk.size_usd <= 5.0 + 1e-9


def test_window_cap_blocks_when_full():
    eng = make_engine()
    chk = eng.check(edge=0.2, price_prob=0.5, bankroll=1000.0,
                    window_exposure=60.0, total_exposure=60.0)
    assert not chk.ok


def test_kill_switch_blocks():
    eng = make_engine()
    eng.trip_kill_switch()
    chk = eng.check(edge=0.2, price_prob=0.5, bankroll=1000.0,
                    window_exposure=0.0, total_exposure=0.0)
    assert not chk.ok
    assert "kill" in chk.reason


def test_circuit_breaker_trips_on_drawdown():
    eng = make_engine(max_drawdown_pct=10.0)
    eng.record_equity(1000.0)
    eng.record_equity(880.0)  # 12% drawdown
    assert eng.circuit_broken
    chk = eng.check(edge=0.2, price_prob=0.5, bankroll=880.0,
                    window_exposure=0.0, total_exposure=0.0)
    assert not chk.ok


def test_daily_loss_limit_blocks():
    eng = make_engine(daily_loss_limit=50.0)
    eng.record_realized(-60.0)
    chk = eng.check(edge=0.2, price_prob=0.5, bankroll=940.0,
                    window_exposure=0.0, total_exposure=0.0)
    assert not chk.ok


def test_reset_clears_breakers():
    eng = make_engine()
    eng.trip_kill_switch()
    eng.circuit_broken = True
    eng.reset()
    assert not eng.kill_switched
    assert not eng.circuit_broken
