"""Active market discovery and metadata for Kalshi crypto strike markets.

Periodically refreshes the set of open markets for the configured series via
REST, extracting each market's strike and close time. Kalshi crypto "strike"
markets resolve YES if the underlying closes above the strike, so a bet on
"up" buys YES and a bet on "down" buys NO of the same market.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from engine.auth.rest_client import KalshiRestClient

log = logging.getLogger("markets")


@dataclass
class MarketInfo:
    ticker: str
    series: str
    strike: float
    close_time: datetime
    title: str = ""

    def tau_seconds(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return max(0.0, (self.close_time - now).total_seconds())


def _parse_close(market: dict) -> Optional[datetime]:
    raw = market.get("close_time") or market.get("expiration_time")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_strike(market: dict) -> Optional[float]:
    for key in ("floor_strike", "cap_strike", "strike"):
        val = market.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _series_of(ticker: str) -> str:
    # Kalshi tickers look like SERIES-YYMMMDDHH-Tstrike; series is before first dash.
    return ticker.split("-", 1)[0] if "-" in ticker else ticker


class MarketManager:
    def __init__(self, rest: KalshiRestClient, series: list[str]):
        self.rest = rest
        self.series = series
        self.markets: dict[str, MarketInfo] = {}

    async def refresh(self, max_per_series: int = 100) -> list[str]:
        """Refresh open markets for configured series. Returns active tickers."""
        found: dict[str, MarketInfo] = {}
        for prefix in self.series:
            try:
                resp = await self.rest.get_markets(
                    series_ticker=prefix, status="open", limit=max_per_series
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("market refresh failed for %s: %s", prefix, exc)
                continue
            for m in resp.get("markets", []):
                ticker = m.get("ticker")
                strike = _parse_strike(m)
                close = _parse_close(m)
                if not ticker or strike is None or close is None:
                    continue
                found[ticker] = MarketInfo(
                    ticker=ticker,
                    series=_series_of(ticker),
                    strike=strike,
                    close_time=close,
                    title=m.get("title", ""),
                )
        self.markets = found
        log.info("Refreshed %d active markets", len(found))
        return list(found.keys())

    def active(self, now: Optional[datetime] = None) -> list[MarketInfo]:
        """Markets not yet closed."""
        return [m for m in self.markets.values() if m.tau_seconds(now) > 0]

    def get(self, ticker: str) -> Optional[MarketInfo]:
        return self.markets.get(ticker)
