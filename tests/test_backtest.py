"""Tests for the backtesting harness."""

import math
import pytest
from engine.backtest.runner import BacktestParams, BacktestRunner, Tick


def make_ticks(n=10, edge_bps=8, outcome=1, tau_start=900.0):
    """Generate synthetic ticks for a single window.

    Parameters
    ----------
    n: int
        Number of evaluation ticks before close.
    edge_bps: int
        Edge in basis points (8 = 8% edge).
    outcome: int
        1 = side resolved YES, 0 = NO.
    tau_start: float
        Seconds to close at the first tick.
    """
    ticks = []
    # spot=51000, strike=50000, sigma=0.50, tau≈15min → model ≈ 0.60
    # ask at 52c gives edge ≈ 0.60 - 0.52 - 0.02 = 0.06
    for i in range(n):
        ticks.append(
            Tick(
                ts=float(i * 30),
                ticker="KXBTC-001",
                side="up",
                strike=50_000.0,
                spot=51_000.0,
                sigma=0.50,
                tau=max(1.0, tau_start - i * (tau_start / n)),
                ask_cents=52,
                outcome=outcome,
            )
        )
    # Closing tick: tau=0
    ticks.append(
        Tick(ts=float(n * 30), ticker="KXBTC-001", side="up",
             strike=50_000.0, spot=51_000.0, sigma=0.50,
             tau=0.0, ask_cents=52, outcome=outcome)
    )
    return ticks


def make_params(**kw):
    defaults = dict(starting_balance=1000.0, min_edge=0.04, fee_buffer=0.02,
                    kelly_fraction=0.25, max_per_trade=50.0, max_per_window=100.0)
    defaults.update(kw)
    return BacktestParams(**defaults)


# ---- basic execution ----

def test_basic_run_returns_result():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    assert result is not None
    assert result.n_trades >= 1


def test_winning_window_positive_pnl():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    assert result.total_pnl > 0


def test_losing_window_negative_pnl():
    ticks = make_ticks(n=5, outcome=0)
    result = BacktestRunner(make_params()).run(ticks)
    assert result.total_pnl < 0


def test_equity_curve_populated():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    assert len(result.equity_curve) > 0


def test_predictions_recorded():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    assert len(result.predictions) > 0


def test_brier_score_computed():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    bs = result.brier_score
    assert bs is not None
    assert 0.0 <= bs <= 1.0


def test_high_min_edge_no_trades():
    ticks = make_ticks(n=10, outcome=1)
    result = BacktestRunner(make_params(min_edge=0.99)).run(ticks)
    assert result.n_trades == 0
    # equity should be unchanged from starting balance
    assert result.total_pnl == pytest.approx(0.0)


def test_max_entries_respected():
    ticks = make_ticks(n=20, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    # Window manager caps at 3 entries per window
    assert result.n_trades <= 3


def test_summary_string_contains_key_fields():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    s = result.summary()
    assert "Trades" in s
    assert "Brier" in s
    assert "P&L" in s


def test_to_dict_has_expected_keys():
    ticks = make_ticks(n=5, outcome=1)
    result = BacktestRunner(make_params()).run(ticks)
    d = result.to_dict()
    for key in ("n_trades", "final_equity", "total_pnl", "pnl_pct",
                 "win_rate", "brier_score", "n_equity_points", "n_predictions"):
        assert key in d


def test_multiple_windows():
    ticks = []
    for window_idx in range(3):
        for i in range(5):
            ticks.append(
                Tick(
                    ts=float(window_idx * 10000 + i * 30),
                    ticker=f"KXBTC-W{window_idx:02d}",
                    side="up",
                    strike=50_000.0,
                    spot=51_000.0,
                    sigma=0.50,
                    tau=max(1.0, 900.0 - i * 180),
                    ask_cents=52,
                    outcome=window_idx % 2,  # alternating win/loss
                )
            )
        ticks.append(
            Tick(ts=float(window_idx * 10000 + 6 * 30), ticker=f"KXBTC-W{window_idx:02d}",
                 side="up", strike=50_000.0, spot=51_000.0, sigma=0.50,
                 tau=0.0, ask_cents=52, outcome=window_idx % 2)
        )
    result = BacktestRunner(make_params()).run(ticks)
    assert result.n_trades >= 2
