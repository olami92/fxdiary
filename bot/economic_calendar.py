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
    get_all_users,
    has_economic_alert_been_sent,
    record_economic_alert,
)

logger = logging.getLogger(__name__)
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FALLBACK_CALENDAR_URL = "https://www.financecalendar.com/wp-json/fc/v1/calendar"
CHECK_INTERVAL_SECONDS = 15 * 60
ALERT_WINDOW_MINUTES = 30
MAJOR_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
MAX_RETRY_SECONDS = 6 * 60 * 60
_calendar_cache: List[Dict[str, Any]] = []
_next_fetch_at = 0.0
_retry_delay = CHECK_INTERVAL_SECONDS


def _fetch_calendar() -> List[Dict[str, Any]]:
    """Fetch the primary feed, falling back to a second free calendar provider."""
    global _calendar_cache, _next_fetch_at, _retry_delay
    now = time.monotonic()
    if now < _next_fetch_at:
        return _calendar_cache

    try:
        errors = []
        utc_today = datetime.datetime.now(datetime.timezone.utc).date()
        for source, url, params in (
            ("Forex Factory", CALENDAR_URL, None),
            (
                "Finance Calendar",
                FALLBACK_CALENDAR_URL,
                {
                    "from": utc_today.isoformat(),
                    "to": (utc_today + datetime.timedelta(days=7)).isoformat(),
                    "impact": "high",
                    "limit": 500,
                },
            ),
        ):
            try:
                response = requests.get(url, params=params, timeout=20, headers={"User-Agent": "MyFXkeeper/1.0"})
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                    errors.append(f"{source}: HTTP 429")
                    if source == "Forex Factory":
                        _retry_delay = max(_retry_delay, retry_after or 0)
                    continue
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    data = data.get("events", [])
                if not isinstance(data, list):
                    raise ValueError("response was not a JSON event list")
                normalized = [_normalize_event(event) for event in data if isinstance(event, dict)]
                normalized = [event for event in normalized if event]
                if normalized:
                    for event in normalized:
                        event.setdefault("source", source)
                        if source == "Finance Calendar":
                            event.setdefault("url", "https://www.financecalendar.com")
                        else:
                            event.setdefault("url", "https://www.forexfactory.com/calendar")
                    _calendar_cache = normalized
                    _next_fetch_at = now + CHECK_INTERVAL_SECONDS
                    _retry_delay = CHECK_INTERVAL_SECONDS
                    logger.info("Loaded %d economic events from %s.", len(normalized), source)
                    return _calendar_cache
                errors.append(f"{source}: response contained no usable events")
            except Exception as error:
                errors.append(f"{source}: {error}")

        error = "; ".join(errors)
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
    except Exception as error:
        _next_fetch_at = now + _retry_delay
        _retry_delay = min(max(_retry_delay * 2, CHECK_INTERVAL_SECONDS), MAX_RETRY_SECONDS)
        logger.exception("Unexpected economic calendar fetch error: %s", error)
        return _calendar_cache


def _normalize_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map supported provider fields to the common alert-event shape."""
    normalized = dict(event)
    normalized["date"] = event.get("time_utc") or event.get("date") or event.get("datetime")
    normalized["title"] = event.get("title") or event.get("name") or event.get("event")
    normalized["impact"] = str(event.get("impact") or "").strip().casefold().title()
    normalized["forecast"] = event.get("forecast") or event.get("consensus") or event.get("estimate")
    normalized["previous"] = event.get("previous") or event.get("prior")
    normalized["id"] = event.get("id") or event.get("event_id") or event.get("calendarId")
    if event.get("all_day") is True:
        return None
    if not normalized["date"] or not normalized["title"]:
        return None
    return normalized


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
    value = event.get("time_utc") or event.get("date") or event.get("datetime")
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
        "EURO AREA": "EUR", "EUROZONE": "EUR", "EU": "EUR", "GERMANY": "EUR", "FRANCE": "EUR",
        "ITALY": "EUR", "SPAIN": "EUR", "NETHERLANDS": "EUR", "UNITED KINGDOM": "GBP", "UK": "GBP", "BRITAIN": "GBP",
        "JAPAN": "JPY", "CANADA": "CAD", "AUSTRALIA": "AUD", "NEW ZEALAND": "NZD",
        "SWITZERLAND": "CHF", "CHINA": "CNY", "C$": "CAD", "A$": "AUD", "NZ$": "NZD",
    }
    return aliases.get(value, value)


def _event_key(event: Dict[str, Any], when: datetime.datetime, currency: str) -> str:
    identity = event.get("id") or event.get("event_id") or event.get("calendarId") or ""
    if not identity:
        identity = f"{when.isoformat()}|{currency}|{event.get('title') or event.get('event') or ''}"
    return hashlib.sha256(str(identity).encode("utf-8")).hexdigest()


async def check_upcoming_events(bot: Bot) -> None:
    """Alert every registered user about high-impact events for major currencies."""
    events = await asyncio.to_thread(_fetch_calendar)
    users = await get_all_users()
    now = datetime.datetime.now(datetime.timezone.utc)
    if not events:
        logger.warning("Economic calendar check has no events available from either provider.")
        return
    if not users:
        logger.info("Economic alerts are enabled, but there are no registered users yet.")
        return

    for event in events:
        if str(event.get("impact") or "").strip().casefold() != "high":
            continue
        currency = _event_currency(event)
        if currency not in MAJOR_CURRENCIES:
            continue
        scheduled = _event_datetime(event)
        if scheduled is None:
            continue
        seconds_until = (scheduled - now).total_seconds()
        if seconds_until < 0 or seconds_until > ALERT_WINDOW_MINUTES * 60:
            continue

        event_key = _event_key(event, scheduled, currency)
        for user in users:
            telegram_id = user.telegram_id
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
                "source": event.get("source") or "Forex Factory calendar",
            }
            message = (
                "🔔 <b>High-impact economic event approaching</b>\n"
                f"<pre>{html.escape(json.dumps(event_payload, ensure_ascii=False, indent=2))}</pre>\n"
                f"Source: <a href=\"{html.escape(str(event.get('url') or 'https://www.financecalendar.com'), quote=True)}\">"
                f"{html.escape(str(event.get('source') or 'Finance Calendar'))}</a>"
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
