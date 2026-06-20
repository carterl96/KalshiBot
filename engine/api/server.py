"""FastAPI control + data API and live WebSocket stream for the admin panel.

Public read endpoints expose health, state, markets, trades, decisions and the
equity curve. Control endpoints (start/stop/kill, mode switch, risk params)
require a bearer token obtained from POST /api/login with the admin password.
The /api/stream WebSocket pushes live {type, data} events to the UI.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine.config import get_settings
from engine.engine import TradingEngine
from engine.settings_store import SettingsManager
from engine.telemetry.store import Store

log = logging.getLogger("api")

# Ensure engine INFO logs surface in production (uvicorn launch skips main.py's
# logging setup, otherwise INFO from feeds/markets would be invisible).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

settings = get_settings()
store = Store(settings.database_url)
settings_mgr = SettingsManager(store, settings.app_secret)
engine: TradingEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    await store.init()
    # Build the engine from env settings overlaid with saved operator settings.
    effective = await settings_mgr.effective(settings)
    engine = TradingEngine(effective, store)
    # The AUTOSTART env var is authoritative: it forces a start even if the
    # operator's saved settings default autostart to false.
    if settings.autostart or effective.autostart:
        await engine.start()
    yield
    if engine:
        await engine.shutdown()
    await store.close()


app = FastAPI(title="KalshiBot Engine", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- auth ----
class LoginBody(BaseModel):
    password: str


def make_token() -> str:
    return jwt.encode({"role": "admin"}, settings.jwt_secret, algorithm="HS256")


def require_auth(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="unauthorized")


def get_engine() -> TradingEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="engine not ready")
    return engine


@app.post("/api/login")
async def login(body: LoginBody):
    if body.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="bad password")
    return {"token": make_token()}


# ---- read endpoints ----
@app.get("/api/health")
async def health():
    return get_engine().health_snapshot()


@app.get("/api/state")
async def state():
    return get_engine().state_snapshot()


@app.get("/api/markets")
async def markets():
    return get_engine().markets_snapshot()


@app.get("/api/trades")
async def trades(limit: int = 100):
    return await store.recent_trades(limit)


@app.get("/api/decisions")
async def decisions(limit: int = 100):
    return await store.recent_decisions(limit)


@app.get("/api/equity-curve")
async def equity_curve():
    return await store.equity_curve()


@app.get("/api/risk")
async def get_risk(_: None = Depends(require_auth)):
    return get_engine().risk.params.to_dict()


# ---- control endpoints (auth) ----
class RiskBody(BaseModel):
    max_per_trade: float | None = None
    max_per_window: float | None = None
    daily_loss_limit: float | None = None
    max_exposure: float | None = None
    max_drawdown_pct: float | None = None
    kelly_fraction: float | None = None


class ModeBody(BaseModel):
    mode: str


@app.post("/api/risk")
async def set_risk(body: RiskBody, _: None = Depends(require_auth)):
    eng = get_engine()
    eng.risk.params.update(**body.model_dump(exclude_none=True))
    await eng.broadcast_state()
    return eng.risk.params.to_dict()


@app.post("/api/control/start")
async def control_start(_: None = Depends(require_auth)):
    await get_engine().start()
    return {"ok": True}


@app.post("/api/control/stop")
async def control_stop(_: None = Depends(require_auth)):
    await get_engine().stop()
    return {"ok": True}


@app.post("/api/control/kill")
async def control_kill(_: None = Depends(require_auth)):
    get_engine().kill_switch()
    return {"ok": True}


@app.post("/api/control/reset")
async def control_reset(_: None = Depends(require_auth)):
    get_engine().reset_risk()
    await get_engine().broadcast_state()
    return {"ok": True}


@app.post("/api/control/mode")
async def control_mode(body: ModeBody, _: None = Depends(require_auth)):
    await get_engine().set_mode(body.mode)
    return {"ok": True, "mode": body.mode}


# ---- setup / settings (auth) ----
@app.get("/api/settings")
async def get_settings_view(_: None = Depends(require_auth)):
    """Operator-configurable settings; secrets returned masked."""
    return await settings_mgr.public_view()


@app.post("/api/settings")
async def save_settings(payload: dict, _: None = Depends(require_auth)):
    """Persist settings and hot-apply them to the running engine."""
    await settings_mgr.save(payload)
    effective = await settings_mgr.effective(settings)
    await get_engine().apply_settings(effective)
    return await settings_mgr.public_view()


@app.post("/api/settings/test")
async def test_connection(_: None = Depends(require_auth)):
    """Verify Kalshi credentials currently loaded in the engine."""
    return await get_engine().test_connection()


# ---- calibration ----
@app.get("/api/calibration")
async def get_calibration():
    """Brier score and calibration band data (no auth — read-only stats)."""
    eng = get_engine()
    cal = eng.calibration_snapshot()
    brier_db = await store.brier_score_db()
    return {**cal, "brier_score_db": brier_db}


# ---- proposals ----
class ProposalApplyBody(BaseModel):
    proposal_id: int


@app.get("/api/proposals")
async def list_proposals(_: None = Depends(require_auth)):
    return await store.list_proposals()


@app.post("/api/proposals/{proposal_id}/apply")
async def apply_proposal(proposal_id: int, _: None = Depends(require_auth)):
    """Apply a parameter proposal: update risk params and dismiss the record."""
    import json as _json
    proposals = await store.list_proposals()
    row = next((p for p in proposals if p["id"] == proposal_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="proposal not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="proposal already actioned")
    try:
        params = _json.loads(row["params_json"])
    except Exception:
        raise HTTPException(status_code=400, detail="invalid params JSON")
    eng = get_engine()
    # Route to the right place: strategy knobs (min_edge, stops, kelly…) via the
    # tunable-override path, and any remaining risk caps via risk params.
    applied = eng.apply_param_overrides(params)
    remaining = {k: v for k, v in params.items() if k not in applied}
    if remaining:
        eng.risk.params.update(**remaining)
        applied.update(remaining)
    await store.update_proposal_status(proposal_id, "applied")
    await eng.broadcast_state()
    return {"ok": True, "applied_params": applied}


@app.post("/api/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(proposal_id: int, _: None = Depends(require_auth)):
    ok = await store.update_proposal_status(proposal_id, "dismissed")
    if not ok:
        raise HTTPException(status_code=404, detail="proposal not found")
    return {"ok": True}


# ---- alerts ----
@app.post("/api/alerts/test")
async def test_alert(_: None = Depends(require_auth)):
    eng = get_engine()
    ok = await eng.alerts.test()
    return {"ok": ok, "enabled": eng.alerts.enabled}


# ---- backtest ----
class BacktestBody(BaseModel):
    ticks: list[dict]
    params: dict = {}


@app.get("/api/ticks")
async def get_ticks(
    ticker: str | None = None,
    series: str | None = None,
    limit: int = 5000,
    _: None = Depends(require_auth),
):
    """Export stored market tick snapshots for backtesting.

    Pass ``?ticker=KXBTC-001`` for a specific market or
    ``?series=KXBTC`` for all resolved ticks for a series.
    """
    if ticker:
        return await store.get_ticks(ticker, limit)
    if series:
        return await store.get_ticks_for_series(series, limit)
    raise HTTPException(status_code=422, detail="provide ticker or series query param")


@app.post("/api/backtest")
async def run_backtest(body: BacktestBody, _: None = Depends(require_auth)):
    """Run a backtest over supplied historical ticks.

    The caller provides a list of tick dicts matching the ``Tick`` dataclass
    fields, plus optional params overrides. Returns a summary dict.
    """
    import asyncio as _asyncio
    from engine.backtest.runner import BacktestParams, BacktestRunner, Tick

    try:
        bp = BacktestParams(**body.params) if body.params else BacktestParams()
        tick_objs = [Tick(**t) for t in body.ticks]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Run synchronously in a thread pool so we don't block the event loop.
    loop = _asyncio.get_event_loop()
    result = await loop.run_in_executor(None, BacktestRunner(bp).run, tick_objs)
    return result.to_dict()


# ---- websocket stream ----
@app.websocket("/api/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    eng = get_engine()
    q = eng.subscribe()
    # Send an initial snapshot immediately.
    await ws.send_json({"type": "state", "data": eng.state_snapshot()})
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    finally:
        eng.unsubscribe(q)
