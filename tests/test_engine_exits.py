"""Regression tests for position exits running independently of entry signals.

The bug these guard against: trailing take-profit / stop-loss were only checked
inside the loop over fresh entry signals, so a *held* position with no current
signal never got stopped out and rode to settlement.
"""

from datetime import datetime, timedelta, timezone

import pytest

from engine.config import Settings
from engine.engine import TradingEngine
from engine.markets import MarketInfo
from engine.telemetry.store import Store


async def _make_engine():
    store = Store("sqlite+aiosqlite:///:memory:")
    await store.init()
    eng = TradingEngine(Settings(kalshi_env="demo"), store)
    eng.mode = "paper"
    eng.orders.mode = "paper"
    return eng, store


def _market(ticker="KXBTC15M-TEST"):
    return MarketInfo(
        ticker=ticker,
        series="KXBTC15M",
        strike=60000.0,
        close_time=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_catastrophe_stop_fires_with_no_entry_signal():
    eng, store = await _make_engine()
    try:
        m = _market()
        # Hold a DOWN position bought at 0.57, registered in the window.
        eng.orders.position(m.ticker, "down").add(100, 0.57)
        eng.window_mgr.record_entry(m.ticker, "down")

        # NO bid gaps to 0.20 — a 0.37 drop, past the 0.30 catastrophe stop.
        book = eng.kalshi_ws.book(m.ticker)
        book.no = {20: 50}
        book.yes = {}

        # No signals computed at all — exits must still run.
        await eng._handle_exits(m, book, spot=60000.0, sigma=0.5, tau=300.0)

        assert eng.orders.position(m.ticker, "down").quantity == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_no_cold_feet_on_transient_dip():
    """A moderate price dip with the model thesis intact must NOT panic-sell.

    This is the behavior the old hard price stop got wrong: a thin-book dip
    right after entry would trip an 18c stop even though spot (and thus our
    fair value) was unchanged, then the price recovered.
    """
    eng, store = await _make_engine()
    try:
        m = _market()
        eng.orders.position(m.ticker, "down").add(100, 0.57)
        eng.window_mgr.record_entry(m.ticker, "down", model_prob=0.55)
        # Disable the grace window so we're purely testing the model stop logic.
        eng.window_mgr.stop_grace_s = 0.0

        book = eng.kalshi_ws.book(m.ticker)
        book.no = {45: 50}   # bid dipped 0.12 — noticeable but not catastrophic
        book.yes = {}

        # Spot still at the strike => model prob ~0.5, thesis intact. Many reads.
        for _ in range(20):
            await eng._handle_exits(m, book, spot=60000.0, sigma=0.5, tau=300.0)

        assert eng.orders.position(m.ticker, "down").quantity == 100  # still held
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_trailing_take_profit_fires_with_no_entry_signal():
    eng, store = await _make_engine()
    try:
        m = _market()
        eng.orders.position(m.ticker, "up").add(50, 0.40)
        eng.window_mgr.record_entry(m.ticker, "up")

        book = eng.kalshi_ws.book(m.ticker)
        # YES bid runs up to 0.95 (arms trail), then retraces to 0.85.
        book.yes = {95: 100}
        book.no = {}
        await eng._handle_exits(m, book, spot=60000.0, sigma=0.5, tau=300.0)  # peak 0.95
        assert eng.orders.position(m.ticker, "up").quantity == 50  # still holding at peak

        book.yes = {85: 100}  # retrace 0.10 from peak (> 0.08 trail)
        await eng._handle_exits(m, book, spot=60000.0, sigma=0.5, tau=300.0)
        assert eng.orders.position(m.ticker, "up").quantity == 0  # trailing exit
    finally:
        await store.close()
