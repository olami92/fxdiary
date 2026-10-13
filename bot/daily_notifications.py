"""Cron entry point for daily trade reminders, no-log notices, and summaries.

Schedule this module every 15 minutes. It sends the morning reminder at 09:00
and the end-of-day notice/summary at 23:00 in each user's configured timezone.
"""

import asyncio
import datetime
import html
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import Bot

from bot.config import TELEGRAM_BOT_TOKEN
from bot.db import (
    engine,
    get_all_users,
    get_user_trades_logged_between,
    has_economic_alert_been_sent,
    init_db,
    record_economic_alert,
)

logger = logging.getLogger(__name__)
REMINDER_HOUR = 9
END_OF_DAY_HOUR = 23
CRON_WINDOW_MINUTES = 15


def _user_timezone(value: str) -> datetime.tzinfo:
    try:
        return ZoneInfo(value or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Invalid user timezone %r; using UTC.", value)
        return datetime.timezone.utc


def _daily_key(kind: str, day: datetime.date) -> str:
    return f"daily_{kind}:{day.isoformat()}"


async def _send_once(bot: Bot, user_id: int, event_key: str, message: str) -> bool:
    if await has_economic_alert_been_sent(user_id, event_key):
        return False
    try:
        await bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")
        await record_economic_alert(user_id, event_key)
        return True
    except Exception:
        logger.exception("Could not send daily notification to Telegram user %s", user_id)
        return False


def _daily_summary(trades, day: datetime.date) -> str:
    closed = [trade for trade in trades if str(trade.status or "CLOSED").upper() != "OPEN"]
    open_count = len(trades) - len(closed)
    wins = sum(1 for trade in closed if float(trade.net_profit or 0) > 0)
    losses = sum(1 for trade in closed if float(trade.net_profit or 0) < 0)
    net_pnl = sum(float(trade.net_profit or 0) for trade in closed)
    pnl_text = f"{'+' if net_pnl >= 0 else '−'}${abs(net_pnl):,.2f}"
    symbols = sorted({str(trade.symbol).upper() for trade in trades if trade.symbol})
    symbols_text = ", ".join(html.escape(symbol) for symbol in symbols) or "—"
    return (
        f"📊 <b>Daily trade summary · {day:%b %d, %Y}</b>\n\n"
        f"• Trades logged: <b>{len(trades)}</b>\n"
        f"• Closed: <b>{len(closed)}</b>  ·  Open: <b>{open_count}</b>\n"
        f"• Wins: <b>{wins}</b>  ·  Losses: <b>{losses}</b>\n"
        f"• Realized net P&amp;L: <b>{pnl_text}</b>\n"
        f"• Symbols: <b>{symbols_text}</b>"
    )


async def run_daily_notifications(now_utc: datetime.datetime = None) -> dict:
    """Send only notifications due in the current 15-minute cron window."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to send daily notifications.")
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

    await init_db()
    users = await get_all_users()
    counts = {"reminders": 0, "no_log_notices": 0, "summaries": 0}
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        for user in users:
            zone = _user_timezone(user.timezone)
            local_now = now_utc.astimezone(zone)
            if local_now.minute >= CRON_WINDOW_MINUTES:
                continue

            local_day = local_now.date()
            if local_now.hour == REMINDER_HOUR:
                event_key = _daily_key("reminder", local_day)
                message = (
                    "📝 <b>Daily trade journal reminder</b>\n\n"
                    "Remember to log today’s trades in MyFXkeeper. You can send a trade screenshot, "
                    "use a voice note, or enter it manually in the bot."
                )
                if await _send_once(bot, user.telegram_id, event_key, message):
                    counts["reminders"] += 1

            elif local_now.hour == END_OF_DAY_HOUR:
                start_local = datetime.datetime.combine(local_day, datetime.time.min, tzinfo=zone)
                end_local = start_local + datetime.timedelta(days=1)
                trades = await get_user_trades_logged_between(
                    user.telegram_id,
                    start_local.astimezone(datetime.timezone.utc),
                    end_local.astimezone(datetime.timezone.utc),
                )
                if not trades:
                    event_key = _daily_key("no_logs", local_day)
                    message = (
                        f"⏰ <b>No trades logged for {local_day:%b %d}.</b>\n\n"
                        "If you traded today, remember to add those trades to your MyFXkeeper journal."
                    )
                    if await _send_once(bot, user.telegram_id, event_key, message):
                        counts["no_log_notices"] += 1
                else:
                    event_key = _daily_key("summary", local_day)
                    if await _send_once(bot, user.telegram_id, event_key, _daily_summary(trades, local_day)):
                        counts["summaries"] += 1

    logger.info("Daily notifications completed: %s", counts)
    return counts


async def _run_and_dispose():
    try:
        await run_daily_notifications()
    finally:
        await engine.dispose()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run_and_dispose())


if __name__ == "__main__":
    main()
