"""Tests for order-book integrity: crossed-book rejection and REST refresh.

Guards the bug where a stale/desynced WS book (best_yes_bid + best_no_bid > 100)
fed fake prices to pricing and the stop-loss.
"""

from engine.data.kalshi_ws import KalshiWS, OrderBook


def test_healthy_book_prices():
    b = OrderBook()
    # YES bids up to 40, NO bids up to 55 -> not crossed (40 + 55 = 95).
    b.yes = {40: 100, 38: 50}
    b.no = {55: 100, 53: 20}
    assert not b.crossed()
    yb, ya = b.yes_bid_ask()
    assert yb == 40 and ya == 45            # yes_ask = 100 - best_no_bid(55)
    nb, na = b.no_bid_ask()
    assert nb == 55 and na == 60            # no_ask = 100 - best_yes_bid(40)


def test_crossed_book_returns_no_prices():
    b = OrderBook()
    # Stale YES bid at 80 plus NO bid at 64 -> 144 > 100, impossible/crossed.
    b.yes = {80: 100}
    b.no = {64: 100}
    assert b.crossed()
    assert b.yes_bid_ask() == (None, None)
    assert b.no_bid_ask() == (None, None)


def test_rest_refresh_fixes_crossed_book():
    ws = KalshiWS(ws_base="wss://x", signer=None)
    book = ws.book("MKT")
    book.yes = {80: 100}   # stale
    book.no = {64: 100}
    assert book.crossed()
    # Fresh REST snapshot (dollar fixed-point shape) replaces the book wholesale.
    ws.apply_rest_orderbook("MKT", {
        "yes_dollars": [["0.4000", "100.00"], ["0.3800", "50.00"]],
        "no_dollars": [["0.5500", "100.00"]],
    })
    b = ws.book("MKT")
    assert not b.crossed()
    assert b.yes_bid_ask() == (40, 45)


def test_rest_refresh_cents_shape():
    ws = KalshiWS(ws_base="wss://x", signer=None)
    ws.apply_rest_orderbook("MKT", {"yes": [[40, 100]], "no": [[55, 100]]})
    assert ws.book("MKT").yes_bid_ask() == (40, 45)
