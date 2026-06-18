"""TradingEngine: the orchestrator that runs the whole pipeline.

Responsibilities:
  * own the market-data feeds (Kalshi WS + Coinbase spot) and vol estimation
  * periodically refresh the tradeable market set and resubscribe
  * on a fast tick, evaluate each active market for edge, size via the risk
    engine, and route orders through the OrderManager (paper or live)
  * detect window close and settle positions
  * snapshot equity and broadcast live state to connected UI clients
  * run the optional LLM meta-layer on a slow timer to adjust the risk dial

The hot path (evaluate -> risk -> order) is fully deterministic and never waits
on the LLM. The LLM loop only mutates an advisory ``risk_dial`` and active
strategy that bias sizing/selection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from engine.alerts import AlertManager
from engine.auth.rest_client import KalshiRestClient
from engine.auth.signer import KalshiSigner
from engine.config import Settings
from engine.data.kalshi_ws import KalshiWS, OrderBook
from engine.data.spot import SpotFeed
from engine.execution.orders import OrderManager
from engine.execution.window import WindowManager
from engine.llm.meta import LLMMetaLayer, MetaGuidance
from engine.markets import MarketInfo, MarketManager
from engine.pricing.model import VolEstimator
from engine.risk.limits import RiskEngine, RiskParams
from engine.strategy.edge import Signal, evaluate
from engine.data.brrny import BRRNYFeed
from engine.data.tick_collector import TickCollector
from engine.telemetry.calibration import CalibrationTracker
from engine.telemetry.store import Store

log = logging.getLogger("engine")

# Map a Kalshi series prefix to the spot product used to price it.
SERIES_TO_PRODUCT = {
    "KXBTC": "BTC-USD",
    "KXETH": "ETH-USD",
}


def product_for_series(series: str) -> str:
    for prefix, product in SERIES_TO_PRODUCT.items():
        if series.startswith(prefix):
            return product
    return "BTC-USD"


class TradingEngine:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.running = False
        self.started_at = time.time()
        self.last_latency_ms = 0.0

        # Live UI broadcast
        self._subscribers: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []

        # Latest evaluated signals for the markets view.
        self.signals: dict[str, Signal] = {}
        self.guidance = MetaGuidance()

        # Phase 2: window state machine + calibration tracker.
        self.window_mgr = WindowManager()
        self.calibration = CalibrationTracker()
        self._llm_proposal_counter = 0   # run proposals every N LLM cycles

        # Alert manager (fires webhooks on kill/breaker/loss events).
        self.alerts = AlertManager(
            webhook_url=settings.alert_webhook_url,
        )

        # Tick collector: persists market snapshots to DB for backtesting.
        self.tick_collector = TickCollector(store, interval_s=60.0)

        # BRRNY feed for hourly market settlement.
        self.brrny = BRRNYFeed()

        # Risk params persist across settings reloads (managed from Controls).
        self.risk = RiskEngine(
            RiskParams(
                max_per_trade=settings.max_per_trade,
                max_per_window=settings.max_per_window,
                daily_loss_limit=settings.daily_loss_limit,
                max_exposure=settings.max_exposure,
                max_drawdown_pct=settings.max_drawdown_pct,
                kelly_fraction=settings.kelly_fraction,
            )
        )

        self._build_from_settings(settings)

    def _build_from_settings(self, settings: Settings) -> None:
        """(Re)construct credential-dependent clients and feeds from settings."""
        self.settings = settings
        self.mode = settings.start_mode

        self.signer = self._build_signer()
        self.rest = KalshiRestClient(settings.rest_base, self.signer)
        self.kalshi_ws = KalshiWS(settings.ws_base, self.signer)
        self.spot = SpotFeed(self._spot_products())
        self.spot.on_tick(self._on_spot)
        self.markets = MarketManager(self.rest, settings.series_list)
        self.vol = {
            p: VolEstimator(settings.vol_lookback_s) for p in self._spot_products()
        }
        self.orders = OrderManager(
            rest=self.rest, mode=self.mode, balance=settings.starting_balance
        )
        self.llm = LLMMetaLayer(
            anthropic_key=settings.anthropic_api_key,
            gemini_key=settings.gemini_api_key,
        )
        self.alerts = AlertManager(webhook_url=settings.alert_webhook_url)

    async def apply_settings(self, settings: Settings) -> None:
        """Swap in new effective settings, rebuilding clients. Restarts the
        engine if it was running so new credentials/feeds take effect."""
        was_running = self.running
        if was_running:
            await self.stop()
        await self.rest.close()
        await self.llm.close()
        await self.alerts.close()
        self._build_from_settings(settings)
        log.info("Settings applied (env=%s, has_creds=%s)",
                 settings.kalshi_env, self.signer is not None)
        if was_running:
            await self.start()
        await self.broadcast_state()

    async def test_connection(self) -> dict:
        """Verify Kalshi credentials by signing a balance request."""
        if self.signer is None:
            return {"ok": False, "detail": "no Kalshi credentials configured"}
        try:
            bal = await self.rest.get_balance()
            return {
                "ok": True,
                "env": self.settings.kalshi_env,
                "balance_usd": round(float(bal.get("balance", 0)) / 100.0, 2),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    # ---- setup helpers ----
    def _build_signer(self) -> Optional[KalshiSigner]:
        pem = self.settings.load_private_key_pem()
        if self.settings.kalshi_api_key_id and pem:
            try:
                return KalshiSigner(self.settings.kalshi_api_key_id, pem)
            except Exception as exc:  # noqa: BLE001
                log.error("failed to load Kalshi signer: %s", exc)
        log.warning("No Kalshi credentials; running with public data only")
        return None

    def _spot_products(self) -> list[str]:
        products = {product_for_series(s) for s in self.settings.series_list}
        return sorted(products) or ["BTC-USD"]

    # ---- lifecycle ----
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        if self.mode == "live":
            await self.orders.sync_live_balance()
            await self.orders.reconcile_live_positions()
        self.spot.start()
        self.kalshi_ws.start()
        await self._refresh_markets()
        self._tasks = [
            asyncio.create_task(self._eval_loop(), name="eval"),
            asyncio.create_task(self._market_refresh_loop(), name="refresh"),
            asyncio.create_task(self._equity_loop(), name="equity"),
            asyncio.create_task(self._settlement_loop(), name="settle"),
            asyncio.create_task(self._llm_loop(), name="llm"),
        ]
        log.info("Engine started in %s mode", self.mode)
        await self.broadcast_state()
        asyncio.create_task(self.alerts.engine_started(self.mode))

    async def stop(self) -> None:
        self.running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        await self.spot.stop()
        await self.kalshi_ws.stop()
        log.info("Engine stopped")
        await self.broadcast_state()
        asyncio.create_task(self.alerts.engine_stopped())

    async def shutdown(self) -> None:
        await self.stop()
        await self.rest.close()
        await self.llm.close()
        await self.alerts.close()
        await self.brrny.close()

    async def set_mode(self, mode: str) -> None:
        if mode not in ("paper", "live"):
            raise ValueError("mode must be paper or live")
        self.mode = mode
        self.orders.mode = mode
        if mode == "live":
            await self.orders.sync_live_balance()
            # Sync the book to real Kalshi positions so stale paper fills don't
            # leak into live trading.
            await self.orders.reconcile_live_positions()
        else:
            self.orders.reset_positions()
        # Reset the per-window state machine so stale entries don't block or
        # confuse the new mode's windows.
        self.window_mgr = WindowManager()
        # Re-baseline drawdown tracking to the new mode's balance so a large
        # paper<->live balance change isn't misread as a drawdown and trips
        # the circuit breaker.
        self.risk.peak_equity = self.orders.equity(self._mark_prices())
        self.risk.circuit_broken = False
        log.warning("Trading mode set to %s", mode)
        await self.broadcast_state()

    def kill_switch(self) -> None:
        """Engage the kill switch: block entries and flatten on next settle."""
        self.risk.trip_kill_switch()
        n_pos = sum(1 for p in self.orders.positions.values() if p.quantity > 0)
        asyncio.create_task(self.alerts.kill_switch(n_pos))
        asyncio.create_task(self._flatten_all())

    def reset_risk(self) -> None:
        self.risk.reset()
        # Re-baseline the drawdown peak to current equity so the breaker does
        # not immediately re-trip on the next equity sample.
        self.risk.peak_equity = self.orders.equity(self._mark_prices())

    async def _flatten_all(self) -> None:
        for key, pos in list(self.orders.positions.items()):
            if pos.quantity <= 0:
                continue
            book = self.kalshi_ws.book(pos.ticker)
            bid = book.yes_bid_ask()[0] if pos.side == "up" else book.no_bid_ask()[0]
            price = (bid / 100.0) if bid else pos.avg_price
            res = await self.orders.sell(pos.ticker, pos.side, pos.quantity, price,
                                         reason="kill switch flatten")
            if res.ok:
                self.risk.record_realized(res.pnl)
                await self._log_trade(res)

    # ---- feed callbacks ----
    def _on_spot(self, product: str, price: float, ts: float) -> None:
        est = self.vol.get(product)
        if est:
            est.add(ts, price)
        # Keep BRRNY spot fallback updated with latest BTC price.
        if product == "BTC-USD":
            self.brrny.set_spot_fallback(price)

    # ---- main loops ----
    async def _eval_loop(self) -> None:
        """Fast evaluation loop: price every active market and act on edge."""
        while self.running:
            t0 = time.perf_counter()
            try:
                await self._evaluate_all()
            except Exception as exc:  # noqa: BLE001
                log.exception("eval loop error: %s", exc)
            self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
            await asyncio.sleep(0.5)

    async def _evaluate_all(self) -> None:
        now = datetime.now(timezone.utc)
        for m in self.markets.active(now):
            product = product_for_series(m.series)
            spot = self.spot.get(product)
            sigma = self.vol[product].sigma_annual() if product in self.vol else 0.0
            if not spot or sigma <= 0:
                continue
            book = self.kalshi_ws.book(m.ticker)
            tau = m.tau_seconds(now)

            # Adjust min_edge per active strategy from the LLM.
            strategy = self.guidance.active_strategy
            if strategy == "conservative":
                effective_min_edge = self.settings.min_edge * 1.5
            elif strategy == "near_close" and tau > 60:
                # near_close profile: skip markets with >60s to close
                continue
            else:
                effective_min_edge = self.settings.min_edge

            # Compute signals for both sides upfront.
            sigs: dict[str, Signal] = {}
            for side in ("up", "down"):
                sig = evaluate(
                    ticker=m.ticker,
                    side=side,
                    spot=spot,
                    strike=m.strike,
                    sigma_annual=sigma,
                    tau_seconds=tau,
                    book=book,
                    min_edge=effective_min_edge,
                    fee_buffer=self.settings.fee_buffer,
                )
                if sig is not None:
                    self.signals[f"{m.ticker}:{side}"] = sig
                    sigs[side] = sig
                    # Record prediction in memory and (deduped) in DB.
                    is_new = self.calibration.pending_count()  # before
                    self.calibration.record_prediction(m.ticker, side, sig.model_prob)
                    if self.calibration.pending_count() > is_new:
                        # A new record was appended — persist to DB.
                        asyncio.create_task(
                            self.store.add_prediction(m.ticker, side, sig.model_prob)
                        )
                    # Persist tick snapshot for backtest data collection.
                    ask_c = round(sig.ask_prob * 100)
                    asyncio.create_task(
                        self.tick_collector.record(
                            ticker=m.ticker, side=side,
                            strike=m.strike, spot=spot or 0.0,
                            sigma=sigma, tau=tau,
                            ask_cents=ask_c, model_prob=sig.model_prob,
                        )
                    )

            # --- Phase 2: exits — trailing take-profit / price stop / near-close ---
            for side, sig in sigs.items():
                pos = self.orders.position(m.ticker, side)
                if pos.quantity > 0:
                    bid_c = book.yes_bid_ask()[0] if side == "up" else book.no_bid_ask()[0]
                    sell_price = (bid_c / 100.0) if bid_c else None
                    reason = self.window_mgr.exit_signal(
                        m.ticker, side, sell_price, pos.avg_price, sig.model_prob, tau
                    )
                    if reason:
                        await self._close_position(m, pos, side, book, reason)

            # --- New entries / scale-ins / hedges ---
            for side, sig in sigs.items():
                if not sig.tradeable:
                    await self._log_skip(m, sig)
                    continue

                opposite = "down" if side == "up" else "up"
                opp_sig = sigs.get(opposite)

                # Hedge: we're in the opposite direction and model has turned.
                if (
                    self.orders.position(m.ticker, opposite).quantity > 0
                    and opp_sig is not None
                    and self.window_mgr.should_hedge(m.ticker, sig.model_prob)
                ):
                    await self._act_on_signal(m, sig, label="hedge")
                    continue

                # Fresh entry or scale-in (same direction).
                if self.window_mgr.can_entry(m.ticker, side) or self.window_mgr.can_scale_in(m.ticker, side):
                    label = self.window_mgr.entry_label(m.ticker, side)
                    await self._act_on_signal(m, sig, label=label)

        # Periodic cleanup of stale window states.
        self.window_mgr.cleanup_old()

    async def _close_position(
        self, market: MarketInfo, pos, side: str, book, reason: str
    ) -> None:
        """Sell an open position early (profit-take or stop-loss)."""
        bid = book.yes_bid_ask()[0] if side == "up" else book.no_bid_ask()[0]
        price = (bid / 100.0) if bid else pos.avg_price
        res = await self.orders.sell(pos.ticker, side, pos.quantity, price, reason=reason)
        if res.ok:
            # Early closes realize P&L too — count it toward the daily total so
            # the daily-loss-limit circuit breaker sees cut-loss exits.
            self.risk.record_realized(res.pnl)
            await self._log_trade(res)
            log.info("[window] closed %s:%s reason=%s pnl≈%.2f",
                     market.ticker, side, reason, res.pnl)

    async def _act_on_signal(self, market: MarketInfo, sig: Signal, label: str = "entry") -> None:
        equity = self.orders.equity(self._mark_prices())
        self.risk.record_equity(equity)
        check = self.risk.check(
            edge=sig.edge,
            price_prob=sig.ask_prob,
            bankroll=self.orders.balance,
            window_exposure=self.orders.window_exposure(market.ticker),
            total_exposure=self.orders.total_exposure(),
        )
        # Apply the advisory LLM risk dial to the quantity.
        qty = int(check.quantity * self.guidance.risk_dial) if check.ok else 0
        action_taken = ""
        if check.ok and qty >= 1:
            res = await self.orders.buy(
                market.ticker, sig.side, qty, sig.ask_prob,
                reason=f"{label}:{sig.reason}",
            )
            if res.ok:
                action_taken = f"{label} {qty} {sig.side}"
                await self._log_trade(res)
                # Record entry in window state machine.
                if label == "hedge":
                    self.window_mgr.record_hedge(market.ticker)
                else:
                    self.window_mgr.record_entry(market.ticker, sig.side)

        await self.store.add_decision(
            ticker=market.ticker,
            decision="tradeable",
            model_prob=sig.model_prob,
            market_price=sig.ask_prob,
            edge=sig.edge,
            action_taken=action_taken or (check.reason if not check.ok else "no size"),
            source="quant",
            detail=f"label={label} imbalance={sig.imbalance:.2f} near_close={sig.near_close}",
        )
        await self._broadcast({"type": "decision", "data": {
            "ticker": market.ticker, "edge": sig.edge, "model_prob": sig.model_prob,
            "action": action_taken, "label": label,
        }})

    async def _log_skip(self, market: MarketInfo, sig: Signal) -> None:
        await self.store.add_decision(
            ticker=market.ticker,
            decision="skip",
            model_prob=sig.model_prob,
            market_price=sig.ask_prob,
            edge=sig.edge,
            action_taken="",
            source="quant",
            detail=sig.reason,
        )

    def _mark_prices(self) -> dict[str, float]:
        marks: dict[str, float] = {}
        for key in self.orders.positions:
            ticker, side = key.split(":")
            book = self.kalshi_ws.book(ticker)
            bid = book.yes_bid_ask()[0] if side == "up" else book.no_bid_ask()[0]
            if bid is not None:
                marks[key] = bid / 100.0
        return marks

    async def _market_refresh_loop(self) -> None:
        while self.running:
            await asyncio.sleep(30)
            try:
                await self._refresh_markets()
            except Exception as exc:  # noqa: BLE001
                log.warning("market refresh loop error: %s", exc)

    async def _refresh_markets(self) -> None:
        tickers = await self.markets.refresh()
        if tickers:
            await self.kalshi_ws.resubscribe(tickers)

    async def _equity_loop(self) -> None:
        was_broken = False
        while self.running:
            equity = self.orders.equity(self._mark_prices())
            self.risk.record_equity(equity)
            # Alert if the circuit breaker just tripped this cycle.
            if self.risk.circuit_broken and not was_broken:
                peak = self.risk.peak_equity
                dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
                asyncio.create_task(self.alerts.circuit_breaker(dd))
            was_broken = self.risk.circuit_broken
            # Equity-drop alert.
            asyncio.create_task(
                self.alerts.check_equity_alert(equity, self.settings.alert_equity_drop_pct)
            )
            await self.store.add_equity(equity)
            await self.broadcast_state()
            await asyncio.sleep(5)

    async def _settlement_loop(self) -> None:
        """Settle positions for markets that have closed."""
        while self.running:
            await asyncio.sleep(5)
            now = datetime.now(timezone.utc)
            for ticker in list({k.split(":")[0] for k in self.orders.positions}):
                info = self.markets.get(ticker)
                if info and info.tau_seconds(now) > 0:
                    continue
                await self._settle_market(ticker, info)

    async def _settle_market(self, ticker: str, info: Optional[MarketInfo]) -> None:
        up_wins: Optional[bool] = None
        try:
            m = (await self.rest.get_market(ticker)).get("market", {})
            result = m.get("result")
            if result in ("yes", "no"):
                up_wins = result == "yes"
        except Exception:  # noqa: BLE001
            pass
        if up_wins is None and info is not None:
            product = product_for_series(info.series)
            # Hourly KXBTCD markets settle on BRRNY; 15-min KXBTC15M on spot.
            is_hourly = "KXBTCD" in info.series.upper()
            if is_hourly:
                ref_price = await self.brrny.settlement_price()
                log.info("Hourly settlement %s using BRRNY/fallback: %.2f (strike=%.2f)",
                         ticker, ref_price or 0.0, info.strike)
            else:
                ref_price = self.spot.get(product)
            if ref_price is not None:
                up_wins = ref_price > info.strike
        if up_wins is None:
            return
        pnl = self.orders.settle(ticker, up_wins)
        self.risk.record_realized(pnl)
        # Resolve calibration predictions and tick snapshots.
        self.calibration.resolve(ticker, up_wins)
        await self.store.resolve_predictions(ticker, up_wins)
        await self.store.resolve_ticks(ticker, up_wins)
        # Mark window closed so state machine resets for next window.
        self.window_mgr.settle(ticker)
        await self.store.add_trade(
            ticker=ticker, side="settle", action="settle", quantity=0,
            price=0.0, mode=self.mode, pnl=pnl, reason=f"up_wins={up_wins}",
        )
        # Alerts: significant settlement P&L.
        if abs(pnl) >= 5.0:
            asyncio.create_task(self.alerts.large_trade_pnl(ticker, pnl))
        # Alert if daily loss limit just became binding.
        if self.risk.realized_today <= -abs(self.risk.params.daily_loss_limit):
            asyncio.create_task(
                self.alerts.daily_loss_limit(abs(self.risk.realized_today))
            )
        await self.broadcast_state()

    async def _llm_loop(self) -> None:
        while self.running:
            await asyncio.sleep(30)
            if not self.llm.enabled:
                continue
            try:
                ctx = self._llm_context()
                self.guidance = await self.llm.advise(ctx)
                await self.store.add_decision(
                    ticker="*", decision="meta",
                    model_prob=0.0, market_price=0.0, edge=0.0,
                    action_taken=f"risk_dial={self.guidance.risk_dial:.2f}",
                    source="llm", detail=self.guidance.note,
                )
                await self.broadcast_state()
                # Every 10 LLM cycles (approx 5 minutes), generate a parameter
                # proposal if we have enough calibration data.
                self._llm_proposal_counter += 1
                if self._llm_proposal_counter % 10 == 0:
                    await self._run_proposal_cycle()
            except Exception as exc:  # noqa: BLE001
                log.warning("llm loop error: %s", exc)

    async def _run_proposal_cycle(self) -> None:
        """Ask the LLM to propose parameter tweaks based on calibration."""
        if self.calibration.resolution_count() < 20:
            return  # not enough data yet
        cal_summary = self.calibration.summary()
        losses = self.calibration.recent_losing_trades(n=20)
        proposal = await self.llm.propose_params(cal_summary, losses)
        if proposal and proposal.get("params"):
            import json
            await self.store.add_proposal(
                description=proposal["description"],
                params_json=json.dumps(proposal["params"]),
                suggested_by=self.guidance.source or "llm",
            )
            log.info("LLM proposal stored: %s", proposal["description"][:80])

    def _llm_context(self) -> dict:
        return {
            "mode": self.mode,
            "balance": round(self.orders.balance, 2),
            "realized_pnl": round(self.orders.realized_pnl, 2),
            "realized_today": round(self.risk.realized_today, 2),
            "open_positions": len(self.orders.positions),
            "recent_edges": [
                round(s.edge, 3) for s in list(self.signals.values())[-10:]
            ],
        }

    # ---- telemetry / broadcast ----
    async def _log_trade(self, res) -> None:
        row = await self.store.add_trade(
            ticker=res.ticker, side=res.side, action=res.action,
            quantity=res.quantity, price=res.price, mode=res.mode, reason=res.reason,
        )
        await self._broadcast({"type": "trade", "data": row})

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self, message: dict) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    async def broadcast_state(self) -> None:
        await self._broadcast({"type": "state", "data": self.state_snapshot()})

    # ---- snapshots for the API ----
    def state_snapshot(self) -> dict:
        marks = self._mark_prices()
        equity = self.orders.equity(marks)
        positions = []
        for key, p in self.orders.positions.items():
            if p.quantity <= 0:
                continue
            cur = marks.get(key, p.avg_price)
            positions.append({
                "ticker": p.ticker, "side": p.side, "quantity": p.quantity,
                "avg_price": round(p.avg_price, 4), "current_price": round(cur, 4),
                "unrealized_pnl": round(p.quantity * (cur - p.avg_price), 2),
            })
        return {
            "mode": self.mode,
            "running": self.running,
            "balance": round(self.orders.balance, 2),
            "equity": round(equity, 2),
            "pnl_today": round(self.risk.realized_today, 2),
            "pnl_total": round(self.orders.realized_pnl, 2),
            "positions": positions,
            "active_strategy": self.guidance.active_strategy,
            "risk_dial": self.guidance.risk_dial,
            "circuit_broken": self.risk.circuit_broken,
            "kill_switched": self.risk.kill_switched,
            "risk_params": self.risk.params.to_dict(),
        }

    def calibration_snapshot(self) -> dict:
        return self.calibration.summary()

    def health_snapshot(self) -> dict:
        return {
            "status": "ok",
            "mode": self.mode,
            "engine_running": self.running,
            "uptime_s": round(time.time() - self.started_at, 1),
            "latency_ms": round(self.last_latency_ms, 2),
            "llm_enabled": self.llm.enabled,
            "has_credentials": self.signer is not None,
            "kalshi_env": self.settings.kalshi_env,
        }

    def markets_snapshot(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        out = []
        for m in self.markets.active(now):
            product = product_for_series(m.series)
            spot = self.spot.get(product)
            book = self.kalshi_ws.book(m.ticker)
            yes_bid, yes_ask = book.yes_bid_ask()
            for side in ("up", "down"):
                sig = self.signals.get(f"{m.ticker}:{side}")
                out.append({
                    "ticker": m.ticker, "series": m.series, "side": side,
                    "strike": m.strike, "spot": spot,
                    "kalshi_bid": yes_bid, "kalshi_ask": yes_ask,
                    "mid": book.mid(),
                    "model_prob": round(sig.model_prob, 4) if sig else None,
                    "edge": round(sig.edge, 4) if sig else None,
                    "time_to_close_s": round(m.tau_seconds(now)),
                })
        return out
