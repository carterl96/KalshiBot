"""Persistence layer: trades, decisions, and equity snapshots.

Uses SQLAlchemy async with a SQLite default (great for local/dev and CI) and
PostgreSQL in production (set DATABASE_URL to a postgresql+asyncpg:// URL on
Railway). Tables are created on startup.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy import Float, Integer, String, Text, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    ticker: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))       # up | down
    action: Mapped[str] = mapped_column(String(8))     # buy | sell
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)        # probability price [0,1]
    mode: Mapped[str] = mapped_column(String(8))       # paper | live
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "ts": self.ts, "ticker": self.ticker, "side": self.side,
            "action": self.action, "quantity": self.quantity, "price": self.price,
            "mode": self.mode, "pnl": self.pnl, "reason": self.reason,
        }


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    ticker: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    model_prob: Mapped[float] = mapped_column(Float, default=0.0)
    market_price: Mapped[float] = mapped_column(Float, default=0.0)
    edge: Mapped[float] = mapped_column(Float, default=0.0)
    action_taken: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(16), default="quant")  # quant | llm
    detail: Mapped[str] = mapped_column(Text, default="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "ts": self.ts, "ticker": self.ticker,
            "decision": self.decision, "model_prob": self.model_prob,
            "market_price": self.market_price, "edge": self.edge,
            "action_taken": self.action_taken, "source": self.source,
            "detail": self.detail,
        }


class EquityPoint(Base):
    __tablename__ = "equity_curve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    equity: Mapped[float] = mapped_column(Float)

    def to_dict(self) -> dict[str, Any]:
        return {"ts": self.ts, "equity": self.equity}


class AppSetting(Base):
    """Key/value app configuration written from the Setup page. Secret values
    are stored already-encrypted by the caller."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class MarketTick(Base):
    """One snapshot of a market for backtesting data collection."""

    __tablename__ = "market_ticks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    ts: Mapped[float] = mapped_column(Float, index=True)
    strike: Mapped[float] = mapped_column(Float)
    spot: Mapped[float] = mapped_column(Float)
    sigma: Mapped[float] = mapped_column(Float)
    tau: Mapped[float] = mapped_column(Float)
    ask_cents: Mapped[int] = mapped_column(Integer)
    model_prob: Mapped[float] = mapped_column(Float)
    outcome: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "ticker": self.ticker, "side": self.side,
            "ts": self.ts, "strike": self.strike, "spot": self.spot,
            "sigma": self.sigma, "tau": self.tau, "ask_cents": self.ask_cents,
            "model_prob": self.model_prob, "outcome": self.outcome,
        }


class Prediction(Base):
    """A single model probability prediction, resolved after settlement."""

    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    model_prob: Mapped[float] = mapped_column(Float)
    predicted_at: Mapped[float] = mapped_column(Float, index=True)
    outcome: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "ticker": self.ticker, "side": self.side,
            "model_prob": self.model_prob, "predicted_at": self.predicted_at,
            "outcome": self.outcome, "resolved_at": self.resolved_at,
        }


class Proposal(Base):
    """LLM-generated parameter-tuning proposal surfaced in the admin UI."""

    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    suggested_by: Mapped[str] = mapped_column(String(32), default="llm")
    description: Mapped[str] = mapped_column(Text, default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|applied|dismissed

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "created_at": self.created_at,
            "suggested_by": self.suggested_by, "description": self.description,
            "params_json": self.params_json, "status": self.status,
        }


class Store:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, future=True)
        self.session: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def add_trade(self, **kw) -> dict:
        kw.setdefault("ts", time.time())
        async with self.session() as s:
            row = Trade(**kw)
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def add_decision(self, **kw) -> dict:
        kw.setdefault("ts", time.time())
        async with self.session() as s:
            row = Decision(**kw)
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def add_equity(self, equity: float, ts: Optional[float] = None) -> None:
        async with self.session() as s:
            s.add(EquityPoint(ts=ts or time.time(), equity=equity))
            await s.commit()

    async def recent_trades(self, limit: int = 100) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(select(Trade).order_by(Trade.ts.desc()).limit(limit))
            return [r.to_dict() for r in res.scalars().all()]

    async def recent_decisions(self, limit: int = 100) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(
                select(Decision).order_by(Decision.ts.desc()).limit(limit)
            )
            return [r.to_dict() for r in res.scalars().all()]

    async def equity_curve(self, limit: int = 1000) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(
                select(EquityPoint).order_by(EquityPoint.ts.desc()).limit(limit)
            )
            rows = [r.to_dict() for r in res.scalars().all()]
            return list(reversed(rows))

    # ---- market ticks (backtest data) ----

    async def add_tick(self, **kw) -> None:
        async with self.session() as s:
            s.add(MarketTick(**kw))
            await s.commit()

    async def resolve_ticks(self, ticker: str, up_wins: bool) -> None:
        now = time.time()
        async with self.session() as s:
            res = await s.execute(
                select(MarketTick)
                .where(MarketTick.ticker == ticker)
                .where(MarketTick.outcome.is_(None))
            )
            for row in res.scalars().all():
                row.outcome = (
                    1 if (row.side == "up" and up_wins) or (row.side == "down" and not up_wins) else 0
                )
            await s.commit()

    async def get_ticks(self, ticker: str, limit: int = 5000) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(
                select(MarketTick)
                .where(MarketTick.ticker == ticker)
                .order_by(MarketTick.ts.asc())
                .limit(limit)
            )
            return [r.to_dict() for r in res.scalars().all()]

    async def get_ticks_for_series(self, series_prefix: str, limit: int = 10000) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(
                select(MarketTick)
                .where(MarketTick.ticker.like(f"{series_prefix}%"))
                .where(MarketTick.outcome.is_not(None))
                .order_by(MarketTick.ts.asc())
                .limit(limit)
            )
            return [r.to_dict() for r in res.scalars().all()]

    # ---- predictions ----

    async def add_prediction(self, ticker: str, side: str, model_prob: float) -> None:
        async with self.session() as s:
            s.add(Prediction(
                ticker=ticker, side=side, model_prob=model_prob,
                predicted_at=time.time(),
            ))
            await s.commit()

    async def resolve_predictions(self, ticker: str, up_wins: bool) -> int:
        """Set outcome on all unresolved predictions for ``ticker``.

        Returns the number of records updated.
        """
        now = time.time()
        async with self.session() as s:
            # Load unresolved predictions for this ticker.
            res = await s.execute(
                select(Prediction)
                .where(Prediction.ticker == ticker)
                .where(Prediction.outcome.is_(None))
            )
            rows = res.scalars().all()
            for row in rows:
                row.outcome = (
                    1 if (row.side == "up" and up_wins) or (row.side == "down" and not up_wins) else 0
                )
                row.resolved_at = now
            await s.commit()
            return len(rows)

    async def recent_predictions(self, limit: int = 200) -> list[dict]:
        async with self.session() as s:
            res = await s.execute(
                select(Prediction)
                .where(Prediction.outcome.is_not(None))
                .order_by(Prediction.predicted_at.desc())
                .limit(limit)
            )
            return [r.to_dict() for r in res.scalars().all()]

    async def brier_score_db(self, n: int = 200) -> Optional[float]:
        rows = await self.recent_predictions(n)
        if not rows:
            return None
        errors = [(r["model_prob"] - r["outcome"]) ** 2 for r in rows]
        return round(sum(errors) / len(errors), 4)

    # ---- proposals ----

    async def add_proposal(
        self,
        description: str,
        params_json: str,
        suggested_by: str = "llm",
    ) -> dict:
        async with self.session() as s:
            row = Proposal(
                created_at=time.time(),
                suggested_by=suggested_by,
                description=description,
                params_json=params_json,
                status="pending",
            )
            s.add(row)
            await s.commit()
            return row.to_dict()

    async def list_proposals(self, status: Optional[str] = None) -> list[dict]:
        async with self.session() as s:
            q = select(Proposal).order_by(Proposal.created_at.desc())
            if status:
                q = q.where(Proposal.status == status)
            res = await s.execute(q)
            return [r.to_dict() for r in res.scalars().all()]

    async def update_proposal_status(self, proposal_id: int, status: str) -> bool:
        async with self.session() as s:
            row = await s.get(Proposal, proposal_id)
            if row is None:
                return False
            row.status = status
            await s.commit()
            return True

    async def get_app_settings(self) -> dict[str, str]:
        async with self.session() as s:
            res = await s.execute(select(AppSetting))
            return {r.key: r.value for r in res.scalars().all()}

    async def set_app_settings(self, values: dict[str, str]) -> None:
        async with self.session() as s:
            for key, value in values.items():
                row = await s.get(AppSetting, key)
                if row is None:
                    s.add(AppSetting(key=key, value=value))
                else:
                    row.value = value
            await s.commit()
