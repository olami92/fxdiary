import sys
import site
user_site = site.getusersitepackages()
if user_site and user_site not in sys.path:
    sys.path.insert(0, user_site)

import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, BigInteger, Text, Boolean, select, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.config import DATABASE_URL

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    google_sheet_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    last_active: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    trades: Mapped[List["Trade"]] = relationship("Trade", back_populates="user", cascade="all, delete-orphan")

class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True, nullable=False)
    ticket: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    trade_type: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY or SELL
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)  # Lots
    open_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    close_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # Gross PnL
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    net_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pips: Mapped[float] = mapped_column(Float, default=0.0)
    open_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    close_time: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="CLOSED")
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_to_sheet: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="trades")

engine_options = {"echo": False, "pool_pre_ping": True}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    # Supabase's transaction pooler may reuse connections across transactions.
    # Disabling asyncpg's per-connection prepared statement cache keeps that safe.
    engine_options["connect_args"] = {"statement_cache_size": 0}

engine = create_async_engine(DATABASE_URL, **engine_options)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_trade_status_column)

def _ensure_trade_status_column(connection):
    """Add trade status to databases created before open voice entries existed."""
    columns = {column["name"] for column in inspect(connection).get_columns("trades")}
    if "status" not in columns:
        connection.execute(text("ALTER TABLE trades ADD COLUMN status VARCHAR(12) NOT NULL DEFAULT 'CLOSED'"))

async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> User:
    """Retrieve existing user or create a new user entry."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                created_at=datetime.datetime.utcnow()
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Update last_active and name if changed
            updated = False
            if username and user.username != username:
                user.username = username
                updated = True
            if first_name and user.first_name != first_name:
                user.first_name = first_name
                updated = True
            user.last_active = datetime.datetime.utcnow()
            if updated:
                await session.commit()
                await session.refresh(user)
        return user

async def update_user_sheet(telegram_id: int, google_sheet_id: str, sheet_title: str = None):
    """Link a Google Sheet ID to a user profile."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()
        if user:
            user.google_sheet_id = google_sheet_id
            if sheet_title:
                user.sheet_title = sheet_title
            await session.commit()
            return True
        return False

def parse_datetime_safe(val: Any, default_now: bool = False) -> Optional[datetime.datetime]:
    """Parse dates from string or date objects safely into datetime.datetime."""
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.date):
        return datetime.datetime.combine(val, datetime.time.min)
    if isinstance(val, str) and val.strip():
        val_str = val.strip()
        for fmt in [
            "%Y-%m-%d %H:%M:%S",
            "%Y.%m.%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y.%m.%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y.%m.%d",
        ]:
            try:
                return datetime.datetime.strptime(val_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.datetime.fromisoformat(val_str.replace("Z", "+00:00"))
        except Exception:
            pass
    if default_now:
        return datetime.datetime.utcnow()
    return None

async def add_trade(telegram_id: int, trade_data: Dict[str, Any]) -> Trade:
    """Save a new trade to the database."""
    async with AsyncSessionLocal() as session:
        # Calculate pips if missing
        open_price = float(trade_data.get("open_price", 0.0))
        close_price = float(trade_data.get("close_price", 0.0))
        symbol = str(trade_data.get("symbol", "UNKNOWN")).upper()
        trade_type = str(trade_data.get("trade_type", "BUY")).upper()
        
        pips = trade_data.get("pips")
        if pips is None or pips == 0.0:
            pips = calculate_pips(symbol, trade_type, open_price, close_price)

        gross_profit = float(trade_data.get("profit", 0.0))
        swap = float(trade_data.get("swap", 0.0))
        commission = float(trade_data.get("commission", 0.0))
        net_profit = trade_data.get("net_profit", gross_profit + swap + commission)

        ticket_raw = trade_data.get("ticket")
        ticket_str = str(ticket_raw) if ticket_raw is not None else None

        open_time = parse_datetime_safe(trade_data.get("open_time"), default_now=False)
        close_time = parse_datetime_safe(trade_data.get("close_time"), default_now=True)

        trade = Trade(
            user_id=telegram_id,
            ticket=ticket_str,
            symbol=symbol,
            trade_type=trade_type,
            volume=float(trade_data.get("volume", 0.01)),
            open_price=open_price,
            close_price=close_price,
            sl=trade_data.get("sl"),
            tp=trade_data.get("tp"),
            profit=gross_profit,
            swap=swap,
            commission=commission,
            net_profit=net_profit,
            pips=pips,
            open_time=open_time,
            close_time=close_time,
            status=str(trade_data.get("status", "CLOSED")).upper(),
            screenshot_path=trade_data.get("screenshot_path"),
            notes=trade_data.get("notes"),
            synced_to_sheet=trade_data.get("synced_to_sheet", False)
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
        return trade

async def get_user_trades(telegram_id: int, limit: int = 100, offset: int = 0) -> List[Trade]:
    """Retrieve trades for a specific user ordered by latest."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade)
            .where(Trade.user_id == telegram_id)
            .order_by(Trade.close_time.desc(), Trade.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

async def count_user_trades(telegram_id: int) -> int:
    """Return the total number of trades belonging to one user."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count(Trade.id)).where(Trade.user_id == telegram_id)
        )
        return int(result.scalar_one())

async def delete_user_trade(telegram_id: int, trade_id: int) -> bool:
    """Delete a trade by ID for a user."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade).where(Trade.id == trade_id, Trade.user_id == telegram_id)
        )
        trade = result.scalars().first()
        if trade:
            await session.delete(trade)
            await session.commit()
            return True
        return False

def calculate_pips(symbol: str, trade_type: str, open_price: float, close_price: float) -> float:
    """Calculate pip difference based on symbol pip scale."""
    if open_price <= 0 or close_price <= 0:
        return 0.0
    
    diff = close_price - open_price if trade_type.upper() == "BUY" else open_price - close_price
    sym = symbol.upper()

    if "JPY" in sym:
        pip_size = 0.01
    elif "XAU" in sym or "GOLD" in sym:
        pip_size = 0.1  # 1 pip = 0.10 in Gold
    elif "BTC" in sym or "US30" in sym or "NAS100" in sym or "GER40" in sym:
        pip_size = 1.0  # 1 pip = 1 index point
    else:
        pip_size = 0.0001  # Standard FX pair

    return round(diff / pip_size, 1)
