"""Periodic high-impact economic event alerts tailored to each user's trade history."""

import asyncio
import datetime
import hashlib
import html
import json
import logging
import time
from email.utils import parsedate_to_datetime
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
MAX_RETRY_SECONDS = 6 * 60 * 60
_calendar_cache: List[Dict[str, Any]] = []
_next_fetch_at = 0.0
_retry_delay = CHECK_INTERVAL_SECONDS


def _fetch_calendar() -> List[Dict[str, Any]]:
    """Fetch events with a process-local cache and backoff for provider failures."""
    global _calendar_cache, _next_fetch_at, _retry_delay
    now = time.monotonic()
    if now < _next_fetch_at:
        return _calendar_cache

    try:
        response = requests.get(CALENDAR_URL, timeout=20, headers={"User-Agent": "MyFXkeeper/1.0"})
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            delay = max(retry_after or 0, _retry_delay)
            _next_fetch_at = now + delay
            _retry_delay = min(max(_retry_delay * 2, CHECK_INTERVAL_SECONDS), MAX_RETRY_SECONDS)
            logger.warning(
                "Economic calendar provider rate-limited requests (HTTP 429); "
                "using %s cached events and retrying in about %d minutes.",
                len(_calendar_cache), max(1, delay // 60),
            )
            return _calendar_cache

        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Economic calendar did not return a JSON event list.")
        _calendar_cache = [event for event in data if isinstance(event, dict)]
        _next_fetch_at = now + CHECK_INTERVAL_SECONDS
        _retry_delay = CHECK_INTERVAL_SECONDS
        return _calendar_cache
    except Exception as error:
        # Use stale events if the provider is temporarily unavailable. This keeps
        # the alert loop useful without hammering an endpoint that is failing.
        _next_fetch_at = now + _retry_delay
        _retry_delay = min(max(_retry_delay * 2, CHECK_INTERVAL_SECONDS), MAX_RETRY_SECONDS)
        logger.warning(
            "Economic calendar fetch failed (%s); using %s cached events and "
            "retrying in about %d minutes.",
            error, len(_calendar_cache), max(1, (_next_fetch_at - now) // 60),
        )
        return _calendar_cache


def _retry_after_seconds(value: Optional[str]) -> Optional[int]:
    """Parse Retry-After as seconds or an HTTP date."""
    if not value:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=datetime.timezone.utc)
            return max(0, int((retry_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


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
