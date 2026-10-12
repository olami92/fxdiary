"""Telegram voice-note handler for spoken trade entry."""

import asyncio
import datetime
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.config import GEMINI_API_KEY, UPLOADS_DIR
from bot.db import get_or_create_user
from bot.handlers.photo_handler import _queue_extracted_trades
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
