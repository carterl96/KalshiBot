"""Per-window position state machine for multi-order hedging and scaling.

Each 15-minute (or hourly) market window gets a ``WindowState`` that tracks
how many entries we have taken, which direction our main bet is, whether we
have hedged the opposite side, and whether the window is closed.

Decision logic exposed to the engine:

* ``can_entry``      — is this the first entry for this window/side?
* ``can_scale_in``   — can we add more contracts in the same direction?
* ``should_hedge``   — should we buy the opposite side to reduce risk?
* ``should_take_profit`` — lock in gains near close (model confident, τ small)?
* ``should_cut_loss``    — exit early near close (model against us, τ small)?
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("window")


@dataclass
class WindowState:
    ticker: str
    opened_at: float = field(default_factory=time.time)
    direction: str = ""       # "up" | "down" | "" (empty = no position yet)
    entries: int = 0          # total entries taken (both directions combined)
    hedged: bool = False      # have we opened the opposite-side hedge?
    closed: bool = False      # True once settled / flattened
    peak_price: dict = field(default_factory=dict)  # side -> highest sell-price seen


class WindowManager:
    """Tracks per-window position state and emits scaling/hedging/exit signals.

    Parameters
    ----------
    max_entries:
        Maximum number of buy orders per window across all sides.  Prevents
        runaway averaging into a losing trade.
    hedge_trigger_prob:
        Model probability for the OPPOSITE side above which we consider hedging
        our open position.  E.g. 0.65 means: if we're long "up" and the model
        now thinks "down" has a 65% chance, we buy NO to hedge.
    profit_take_tau_s:
        Seconds before close where we consider locking in gains.
    profit_take_min_prob:
        Model probability (in our favour) above which we take profit near close.
    stop_loss_tau_s:
        Seconds before close where we consider cutting a losing position.
    stop_loss_max_prob:
        Model probability (in our favour) below which we cut near close.
    """

    def __init__(
        self,
        max_entries: int = 3,
        hedge_trigger_prob: float = 0.65,
        profit_take_tau_s: float = 30.0,
        profit_take_min_prob: float = 0.80,
        stop_loss_tau_s: float = 60.0,
        stop_loss_max_prob: float = 0.25,
        trail_arm_gain: float = 0.15,
        trail_distance: float = 0.08,
        stop_loss_drop: float = 0.18,
    ):
        self.max_entries = max_entries
        self.hedge_trigger_prob = hedge_trigger_prob
        self.profit_take_tau_s = profit_take_tau_s
        self.profit_take_min_prob = profit_take_min_prob
        self.stop_loss_tau_s = stop_loss_tau_s
        self.stop_loss_max_prob = stop_loss_max_prob
        # Trailing take-profit: arm once the sell-price runs `trail_arm_gain`
        # above entry, then exit if it retraces `trail_distance` from its peak.
        self.trail_arm_gain = trail_arm_gain
        self.trail_distance = trail_distance
        # Price stop-loss: cut if the sell-price falls `stop_loss_drop` below entry.
        self.stop_loss_drop = stop_loss_drop
        self._windows: dict[str, WindowState] = {}

    # ---- accessor ----

    def get(self, ticker: str) -> WindowState:
        return self._windows.setdefault(ticker, WindowState(ticker=ticker))

    def settle(self, ticker: str) -> None:
        w = self._windows.get(ticker)
        if w:
            w.closed = True
            log.debug("[window] %s marked closed", ticker)

    # ---- entry decisions ----

    def can_entry(self, ticker: str, side: str) -> bool:
        """True if we have NO position yet in this window (fresh entry)."""
        w = self.get(ticker)
        if w.closed or w.entries >= self.max_entries:
            return False
        return w.direction == "" or w.direction == side

    def can_scale_in(self, ticker: str, side: str) -> bool:
        """True if we already have a position and can add more in same direction."""
        w = self.get(ticker)
        if w.closed or w.entries >= self.max_entries:
            return False
        return w.direction == side and w.entries > 0

    def entry_label(self, ticker: str, side: str) -> str:
        """Return 'entry' or 'scale_in' for logging."""
        return "scale_in" if self.get(ticker).direction == side else "entry"

    # ---- hedge decision ----

    def should_hedge(self, ticker: str, opposite_model_prob: float) -> bool:
        """Should we buy the opposite-side contract to reduce downside?

        ``opposite_model_prob`` is the model's probability for the side
        OPPOSITE to our current direction.  We hedge if this has risen
        above ``hedge_trigger_prob`` and we haven't hedged yet.
        """
        w = self.get(ticker)
        if w.closed or w.hedged or w.direction == "":
            return False
        if w.entries >= self.max_entries:
            return False
        return opposite_model_prob >= self.hedge_trigger_prob

    # ---- exit decisions ----

    def should_take_profit(
        self, ticker: str, side: str, model_prob: float, tau_seconds: float
    ) -> bool:
        """Lock in gains near window close when model is strongly in our favour."""
        w = self.get(ticker)
        if w.closed or w.direction != side:
            return False
        return (
            tau_seconds <= self.profit_take_tau_s
            and model_prob >= self.profit_take_min_prob
        )

    def should_cut_loss(
        self, ticker: str, side: str, model_prob: float, tau_seconds: float
    ) -> bool:
        """Cut a losing position near window close when model is against us."""
        w = self.get(ticker)
        if w.closed or w.direction != side:
            return False
        return (
            tau_seconds <= self.stop_loss_tau_s
            and model_prob <= self.stop_loss_max_prob
        )

    def exit_signal(
        self,
        ticker: str,
        side: str,
        sell_price: Optional[float],
        entry_price: float,
        model_prob: float,
        tau_seconds: float,
    ) -> Optional[str]:
        """Decide whether to close a held position *now*, at any point in the
        window — not just near close.

        Priority:
          1. ``trailing_take_profit`` — armed once the bid has run far enough
             above entry; fires when it retraces ``trail_distance`` from peak.
          2. ``stop_loss`` — bid has fallen ``stop_loss_drop`` below entry.
          3. ``take_profit`` / ``cut_loss`` — original near-close model exits.
        Returns the reason string, or ``None`` to keep holding.
        """
        w = self.get(ticker)
        if w.closed or w.direction != side or w.entries == 0:
            return None

        if sell_price is not None:
            peak = max(w.peak_price.get(side, 0.0), sell_price)
            w.peak_price[side] = peak
            # Trailing take-profit (only after a real run-up above entry).
            armed = peak >= entry_price + self.trail_arm_gain
            if armed and sell_price <= peak - self.trail_distance:
                return "trailing_take_profit"
            # Hard price stop-loss.
            if sell_price <= entry_price - self.stop_loss_drop:
                return "stop_loss"

        # Backstop: original near-close, model-confidence exits.
        if self.should_take_profit(ticker, side, model_prob, tau_seconds):
            return "take_profit"
        if self.should_cut_loss(ticker, side, model_prob, tau_seconds):
            return "cut_loss"
        return None

    # ---- record actions ----

    def record_entry(self, ticker: str, side: str) -> None:
        w = self.get(ticker)
        if w.direction == "":
            w.direction = side
        w.entries += 1
        log.debug("[window] %s entry #%d side=%s", ticker, w.entries, side)

    def record_hedge(self, ticker: str) -> None:
        w = self.get(ticker)
        w.hedged = True
        w.entries += 1
        log.debug("[window] %s hedge recorded", ticker)

    def cleanup_old(self, max_age_s: float = 7200.0) -> None:
        """Drop closed/stale window states to prevent memory growth."""
        now = time.time()
        stale = [
            t for t, w in self._windows.items()
            if w.closed and (now - w.opened_at) > max_age_s
        ]
        for t in stale:
            del self._windows[t]
