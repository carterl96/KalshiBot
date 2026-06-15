"""Persistence layer: trades, decisions, and equity snapshots.

Uses SQLAlchemy async with a SQLite default (great for local/dev and CI) and
PostgreSQL in production (set DATABASE_URL to a postgresql+asyncpg:// URL on
Railway). Tables are created on startup.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy import Float, Integer, String, Text, select
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
