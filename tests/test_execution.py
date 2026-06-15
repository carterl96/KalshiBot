"""Tests for paper-mode execution, position tracking, and settlement."""

import pytest

from engine.execution.orders import OrderManager
from engine.strategy.edge import evaluate
from engine.data.kalshi_ws import OrderBook


@pytest.mark.asyncio
async def test_paper_buy_and_settle_win():
    om = OrderManager(rest=None, mode="paper", balance=100.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert res.ok
    assert om.balance == pytest.approx(96.0)  # 10 * 0.40 spent
    pos = om.position("MKT", "up")
    assert pos.quantity == 10 and pos.avg_price == pytest.approx(0.40)

    pnl = om.settle("MKT", up_wins=True)
    # 10 contracts pay $1 each = $10; cost was $4 -> pnl +6
    assert pnl == pytest.approx(6.0)
    assert om.balance == pytest.approx(106.0)


@pytest.mark.asyncio
async def test_paper_settle_loss():
    om = OrderManager(rest=None, mode="paper", balance=100.0)
    await om.buy("MKT", "up", 10, 0.40)
    pnl = om.settle("MKT", up_wins=False)
    assert pnl == pytest.approx(-4.0)
    assert om.balance == pytest.approx(96.0)


@pytest.mark.asyncio
async def test_insufficient_balance_rejected():
    om = OrderManager(rest=None, mode="paper", balance=1.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert not res.ok
    assert "balance" in res.reason


@pytest.mark.asyncio
async def test_sell_closes_position_with_pnl():
    om = OrderManager(rest=None, mode="paper", balance=100.0)
    await om.buy("MKT", "down", 10, 0.30)
    res = await om.sell("MKT", "down", 10, 0.50)
    assert res.ok
    assert om.realized_pnl == pytest.approx(2.0)  # 10 * (0.50 - 0.30)


def test_exposure_tracking():
    om = OrderManager(rest=None, mode="paper", balance=100.0)
    om.position("MKT", "up").add(10, 0.40)
    om.position("MKT", "down").add(5, 0.20)
    assert om.window_exposure("MKT") == pytest.approx(4.0 + 1.0)
    assert om.total_exposure() == pytest.approx(5.0)


def _book_with(yes=None, no=None):
    b = OrderBook()
    b.apply_snapshot(yes or [], no or [])
    return b


def test_edge_detected_when_underpriced():
    # Spot well above strike -> model_prob(up) high. If YES ask is cheap, edge.
    book = _book_with(no=[[40, 100]])  # no_bid 40 -> yes_ask 60
    sig = evaluate(
        ticker="MKT", side="up", spot=105.0, strike=100.0,
        sigma_annual=0.5, tau_seconds=600, book=book,
        min_edge=0.04, fee_buffer=0.02,
    )
    assert sig is not None
    assert sig.model_prob > 0.6
    assert sig.tradeable == (sig.edge >= 0.04)


def test_no_signal_without_book():
    book = OrderBook()  # empty
    sig = evaluate(
        ticker="MKT", side="up", spot=105.0, strike=100.0,
        sigma_annual=0.5, tau_seconds=600, book=book,
        min_edge=0.04, fee_buffer=0.02,
    )
    assert sig is None
