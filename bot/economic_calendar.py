"""Periodic high-impact economic event alerts tailored to each user's trade history."""

import asyncio
import datetime
import hashlib
import html
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from telegram import Bot

from bot.db import (
    get_most_traded_currencies,
    has_economic_alert_been_sent,
    record_economic_alert,
)

logger = logging.getLogger(__name__)
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CHECK_INTERVAL_SECONDS = 15 * 60
ALERT_WINDOW_MINUTES = 30


def _fetch_calendar() -> List[Dict[str, Any]]:
    response = requests.get(CALENDAR_URL, timeout=20, headers={"User-Agent": "FXDiary/1.0"})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Economic calendar did not return a JSON event list.")
    return [event for event in data if isinstance(event, dict)]


def _event_datetime(event: Dict[str, Any]) -> Optional[datetime.datetime]:
    value = event.get("date")
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _event_currency(event: Dict[str, Any]) -> str:
    value = str(event.get("currency") or event.get("country") or "").strip().upper()
    aliases = {
        "UNITED STATES": "USD", "UNITED STATES OF AMERICA": "USD", "US": "USD", "USA": "USD",
        "EURO AREA": "EUR", "EUROZONE": "EUR", "UNITED KINGDOM": "GBP", "UK": "GBP",
        "JAPAN": "JPY", "CANADA": "CAD", "AUSTRALIA": "AUD", "NEW ZEALAND": "NZD",
        "SWITZERLAND": "CHF", "CHINA": "CNY",
    }
    return aliases.get(value, value)


def _event_key(event: Dict[str, Any], when: datetime.datetime, currency: str) -> str:
    identity = event.get("id") or event.get("event_id") or ""
    if not identity:
        identity = f"{when.isoformat()}|{currency}|{event.get('title') or event.get('event') or ''}"
    return hashlib.sha256(str(identity).encode("utf-8")).hexdigest()


async def check_upcoming_events(bot: Bot) -> None:
    """Fetch once, then alert each matching user once per high-impact event."""
    events = await asyncio.to_thread(_fetch_calendar)
    user_currencies = await get_most_traded_currencies()
    now = datetime.datetime.now(datetime.timezone.utc)

    for event in events:
        if str(event.get("impact") or "").strip().casefold() != "high":
            continue
        currency = _event_currency(event)
        if not currency:
            continue
        scheduled = _event_datetime(event)
        if scheduled is None:
            continue
        seconds_until = (scheduled - now).total_seconds()
        if seconds_until < 0 or seconds_until > ALERT_WINDOW_MINUTES * 60:
            continue

        event_key = _event_key(event, scheduled, currency)
        for telegram_id, currencies in user_currencies.items():
            if currency not in currencies:
                continue
            if await has_economic_alert_been_sent(telegram_id, event_key):
                continue

            minutes_until = max(0, int((seconds_until + 59) // 60))
            event_payload = {
                "type": "high_impact_economic_event",
                "event": str(event.get("title") or event.get("event") or "Economic release"),
                "currency": currency,
                "impact": "High",
                "scheduled_at": scheduled.isoformat().replace("+00:00", "Z"),
                "minutes_until": minutes_until,
                "forecast": event.get("forecast") or None,
                "previous": event.get("previous") or None,
                "source": "Forex Factory calendar",
            }
            message = (
                "🔔 <b>High-impact economic event approaching</b>\n"
                f"<pre>{html.escape(json.dumps(event_payload, ensure_ascii=False, indent=2))}</pre>"
            )
            try:
                await bot.send_message(chat_id=telegram_id, text=message, parse_mode="HTML")
                await record_economic_alert(telegram_id, event_key)
            except Exception:
                logger.exception("Could not send economic alert to Telegram user %s", telegram_id)


async def economic_calendar_alert_loop(bot: Bot) -> None:
    """Run an immediate check, then poll the calendar every 15 minutes."""
    while True:
        try:
            await check_upcoming_events(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Economic calendar check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_economic_calendar_alerts(application) -> asyncio.Task:
    """Start the loop once per bot application and retain a task reference."""
    task = application.bot_data.get("economic_calendar_task")
    if task is None or task.done():
        task = asyncio.create_task(economic_calendar_alert_loop(application.bot))
        application.bot_data["economic_calendar_task"] = task
    return task
