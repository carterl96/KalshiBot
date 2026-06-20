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


class _FakeRest:
    """Minimal stub mimicking KalshiRestClient for reconcile tests."""

    def __init__(self, positions):
        self._positions = positions
        self.signer = object()  # truthy: pretend we have credentials

    async def get_positions(self, **_):
        return {"market_positions": self._positions}


class _FlakyPositionsRest:
    """get_positions raises — to test that reconcile keeps the current book."""

    def __init__(self):
        self.signer = object()

    async def get_positions(self, **_):
        raise RuntimeError("kalshi 503")


@pytest.mark.asyncio
async def test_reconcile_keeps_book_on_api_error():
    # A transient positions API error must NOT wipe real positions (which would
    # leave them unmanaged on the live account).
    om = OrderManager(rest=_FlakyPositionsRest(), mode="live", balance=100.0)
    om.position("MKT-A", "up").add(10, 0.40)
    await om.reconcile_live_positions()
    assert om.position("MKT-A", "up").quantity == 10  # preserved on error


@pytest.mark.asyncio
async def test_reconcile_live_positions_maps_kalshi_book():
    rest = _FakeRest([
        {"ticker": "MKT-A", "position": 12, "market_exposure": 444},   # long YES
        {"ticker": "MKT-B", "position": -8, "market_exposure": 240},   # long NO
        {"ticker": "MKT-C", "position": 0, "market_exposure": 0},      # flat: skip
    ])
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    # A stale paper position that must be wiped by reconcile.
    await om.buy("STALE", "up", 5, 0.50)
    await om.reconcile_live_positions()

    assert "STALE:up" not in om.positions
    a = om.position("MKT-A", "up")
    assert a.quantity == 12 and a.avg_price == pytest.approx(0.37)  # 444c/12/100
    b = om.position("MKT-B", "down")
    assert b.quantity == 8 and b.avg_price == pytest.approx(0.30)   # 240c/8/100
    assert "MKT-C:up" not in om.positions and "MKT-C:down" not in om.positions


class _CaptureRest:
    """Captures the order payload sent to Kalshi for assertion."""

    def __init__(self):
        self.orders = []
        self.signer = object()

    async def place_order(self, order):
        self.orders.append(order)
        # Echo a full fill so the payload-shape tests still succeed.
        return {"order_id": "abc", "order": {"status": "executed",
                                             "fill_count": order["count"]}}

    async def get_balance(self):
        return {"balance": 10000}


@pytest.mark.asyncio
async def test_live_order_payload_buy_up_is_bid_yes():
    rest = _CaptureRest()
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert res.ok
    o = rest.orders[-1]
    assert o["ticker"] == "MKT" and o["side"] == "bid"
    assert o["count"] == "10.00" and o["price"] == "0.4000"
    assert o["time_in_force"] == "fill_or_kill"
    assert "self_trade_prevention_type" in o


@pytest.mark.asyncio
async def test_live_order_payload_buy_down_is_ask_at_complement():
    rest = _CaptureRest()
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    await om.buy("MKT", "down", 10, 0.04)  # buy NO @0.04 == sell YES @0.96
    o = rest.orders[-1]
    assert o["side"] == "ask" and o["price"] == "0.9600"


@pytest.mark.asyncio
async def test_live_order_payload_sell_up_is_ask_yes():
    rest = _CaptureRest()
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    om.position("MKT", "up").add(10, 0.40)
    await om.sell("MKT", "up", 10, 0.55)
    o = rest.orders[-1]
    assert o["side"] == "ask" and o["price"] == "0.5500"


@pytest.mark.asyncio
async def test_live_order_payload_sell_down_is_bid_at_complement():
    rest = _CaptureRest()
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    om.position("MKT", "down").add(10, 0.30)
    await om.sell("MKT", "down", 10, 0.30)  # sell NO @0.30 == buy YES @0.70
    o = rest.orders[-1]
    assert o["side"] == "bid" and o["price"] == "0.7000"


class _FillRest:
    """Stub returning a controlled order response + balance for fill tests."""

    def __init__(self, resp, balance_cents=10000):
        self._resp = resp
        self._balance_cents = balance_cents
        self.signer = object()

    async def place_order(self, order):
        return self._resp

    async def get_balance(self):
        return {"balance": self._balance_cents}


@pytest.mark.asyncio
async def test_live_fok_no_fill_leaves_no_position():
    # A killed fill_or_kill must not create a phantom position.
    rest = _FillRest({"order": {"status": "canceled", "fill_count": 0}})
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert not res.ok and res.quantity == 0
    assert "no fill" in res.reason
    assert om.position("MKT", "up").quantity == 0


@pytest.mark.asyncio
async def test_live_partial_fill_credits_only_filled():
    rest = _FillRest({"order": {"status": "executed", "fill_count": 6}})
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert res.ok and res.quantity == 6
    assert om.position("MKT", "up").quantity == 6


@pytest.mark.asyncio
async def test_live_fill_parses_fees():
    rest = _FillRest(
        {"order": {"status": "executed", "fill_count": 10, "taker_fees": 35}}
    )
    om = OrderManager(rest=rest, mode="live", balance=100.0)
    res = await om.buy("MKT", "up", 10, 0.40)
    assert res.ok and res.fees == pytest.approx(0.35)


def test_parse_fill_assumes_requested_when_unknown():
    # No recognizable fill field and no terminal status -> assume FOK filled.
    from engine.execution.orders import _parse_fill
    filled, fees = _parse_fill({"order_id": "x"}, requested=10)
    assert filled == 10 and fees == 0.0
    # Explicit cancel -> zero.
    assert _parse_fill({"status": "canceled"}, requested=10) == (0, 0.0)


@pytest.mark.asyncio
async def test_reset_positions_clears_book():
    om = OrderManager(rest=None, mode="paper", balance=100.0)
    await om.buy("MKT", "up", 4, 0.25)
    om.reset_positions()
    assert om.positions == {}


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
