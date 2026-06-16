"""Alert system: fire webhook notifications on significant trading events.

Supports any Discord/Slack-compatible incoming webhook URL. Events are fired
for:
  * kill_switch         — kill switch engaged
  * circuit_breaker     — drawdown circuit breaker tripped
  * daily_loss_limit    — daily loss limit reached, entries halted
  * engine_started      — engine started (mode)
  * engine_stopped      — engine stopped
  * low_equity          — equity dropped > threshold% from last alert
  * large_pnl           — significant positive or negative P&L trade

If no webhook URL is configured the alerts are logged at WARNING level instead.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("alerts")

DISCORD_MAX_LEN = 1900  # Discord message cap (2000 minus buffer)


@dataclass
class AlertManager:
    webhook_url: str = ""
    bot_name: str = "KalshiBot"
    _last_equity_alert: float = field(default=0.0, repr=False)
    _last_equity_value: float = field(default=0.0, repr=False)
    _client: httpx.AsyncClient = field(
        default_factory=lambda: httpx.AsyncClient(timeout=10.0), repr=False
    )

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def fire(self, event_type: str, detail: str, level: str = "info") -> None:
        """Send an alert. ``level`` is 'info', 'warning', or 'critical'."""
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(level, "ℹ️")
        msg = f"{icon} **{self.bot_name}** · `{event_type}`\n{detail}"
        msg = msg[:DISCORD_MAX_LEN]

        log.warning("[alert] %s: %s", event_type, detail)
        if not self.enabled:
            return
        try:
            await self._client.post(
                self.webhook_url,
                json={"content": msg, "username": self.bot_name},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("alert webhook failed: %s", exc)

    # ---- named event helpers ----

    async def kill_switch(self, positions_count: int) -> None:
        await self.fire(
            "kill_switch",
            f"Kill switch engaged — {positions_count} position(s) being flattened.",
            "critical",
        )

    async def circuit_breaker(self, drawdown_pct: float) -> None:
        await self.fire(
            "circuit_breaker",
            f"Drawdown circuit breaker tripped at {drawdown_pct:.1f}% from peak. Entries halted.",
            "critical",
        )

    async def daily_loss_limit(self, loss: float) -> None:
        await self.fire(
            "daily_loss_limit",
            f"Daily loss limit reached (realized: ${loss:.2f}). Entries halted for today.",
            "warning",
        )

    async def engine_started(self, mode: str) -> None:
        await self.fire(
            "engine_started",
            f"Engine started in **{mode.upper()}** mode.",
            "info",
        )

    async def engine_stopped(self) -> None:
        await self.fire("engine_stopped", "Engine stopped.", "info")

    async def check_equity_alert(
        self, equity: float, threshold_pct: float = 5.0
    ) -> None:
        """Fire if equity has dropped more than ``threshold_pct``% since last alert.

        Also initialises the baseline on first call.
        """
        if self._last_equity_value <= 0:
            self._last_equity_value = equity
            return
        drop_pct = (self._last_equity_value - equity) / self._last_equity_value * 100.0
        now = time.time()
        # Throttle: at most one equity alert per 10 minutes.
        if drop_pct >= threshold_pct and (now - self._last_equity_alert) > 600:
            self._last_equity_alert = now
            await self.fire(
                "low_equity",
                f"Equity dropped {drop_pct:.1f}% to ${equity:.2f}.",
                "warning",
            )
        # Reset baseline only if equity has recovered above previous high.
        if equity > self._last_equity_value:
            self._last_equity_value = equity

    async def large_trade_pnl(self, ticker: str, pnl: float) -> None:
        direction = "gain" if pnl > 0 else "loss"
        level = "info" if pnl > 0 else "warning"
        await self.fire(
            f"trade_{direction}",
            f"Settlement on {ticker}: ${pnl:+.2f} ({direction}).",
            level,
        )

    async def test(self) -> bool:
        """Send a test alert; returns True on success."""
        try:
            await self.fire("test", "Alert webhook is working correctly.", "info")
            return True
        except Exception:  # noqa: BLE001
            return False
