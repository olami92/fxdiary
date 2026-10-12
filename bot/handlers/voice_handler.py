"""Telegram voice-note handler for spoken trade entry."""

import asyncio
import datetime
import logging
from pathlib import Path

import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.config import GEMINI_API_KEY, UPLOADS_DIR
from bot.db import get_or_create_user, get_open_user_trades
from bot.handlers.photo_handler import _queue_extracted_trades, _show_close_confirmation
from bot.voice_engine import parse_voice_trade

logger = logging.getLogger(__name__)


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    if not message or not user or not (message.voice or message.audio):
        return

    await get_or_create_user(user.id, user.username, user.first_name)
    media = message.voice or message.audio
    mime_type = (media.mime_type or ("audio/ogg" if message.voice else "audio/mpeg")).split(";")[0]
    extension = ".ogg" if "ogg" in mime_type or message.voice else ".audio"
    voice_path = UPLOADS_DIR / f"voice_{user.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
    status_message = await message.reply_text("🎙️ Listening to your trade details…")

    try:
        telegram_file = await media.get_file()
        await telegram_file.download_to_drive(voice_path)
        trade = await asyncio.to_thread(parse_voice_trade, str(voice_path), mime_type, GEMINI_API_KEY)
        if trade.get("action") == "CLOSE_EXISTING":
            await _begin_voice_close(trade, user.id, status_message, context)
        else:
            await _queue_extracted_trades([trade], None, status_message, context)
    except ValueError as error:
        await _show_voice_failure(status_message, str(error))
    except Exception as error:
        logger.warning("Voice trade parsing failed for Telegram user %s: %s", user.id, error, exc_info=True)
        await _show_voice_failure(
            status_message,
            "I couldn't understand that voice note. Please try again clearly, or use Manual Entry.",
        )
    finally:
        try:
            Path(voice_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temporary voice file %s", voice_path)


async def _show_voice_failure(message, explanation: str):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✍️ Manual Entry", callback_data="manual_entry"),
    ]])
    await message.edit_text(
        f"❌ <b>Failed to generate result.</b>\n\n{explanation}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def _begin_voice_close(close_data, telegram_id: int, message, context: ContextTypes.DEFAULT_TYPE):
    open_trades = await get_open_user_trades(
        telegram_id,
        symbol=close_data["symbol"],
        ticket=close_data.get("ticket"),
    )
    if not open_trades:
        ticket = close_data.get("ticket")
        ticket_description = f" with ticket #{html.escape(str(ticket).lstrip('#'))}" if ticket else ""
        await message.edit_text(
            f"I couldn't find an open <b>{html.escape(close_data['symbol'])}</b> trade"
            f"{ticket_description}.\n\n"
            "No trade was changed. Check the symbol or ticket, or log the trade first.",
            parse_mode="HTML",
        )
        return

    if len(open_trades) == 1:
        await _show_close_confirmation(message, open_trades[0], close_data, context)
        return

    context.user_data["pending_close_data"] = close_data
    context.user_data.pop("pending_close_trade", None)
    keyboard = []
    for trade in open_trades[:8]:
        label = f"#{trade.ticket or trade.id} · {trade.trade_type} {trade.volume:g} lots · entry {trade.open_price:g}"
        keyboard.append([InlineKeyboardButton(label[:64], callback_data=f"choose_close_trade:{trade.id}")])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel_close_trade")])
    await message.edit_text(
        f"I found {len(open_trades)} open <b>{html.escape(close_data['symbol'])}</b> trades. Which one should I close?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
