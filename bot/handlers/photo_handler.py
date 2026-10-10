import os
import logging
import datetime
import html
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.config import UPLOADS_DIR, GEMINI_API_KEY
from bot.ocr_engine import parse_mt5_screenshot
from bot.db import get_or_create_user, add_trade, calculate_pips

logger = logging.getLogger(__name__)

async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming MT5 trade screenshot images."""
    user = update.effective_user
    message = update.message
    if not user or not message or not message.photo:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    status_msg = await message.reply_html("🔍 <i>Analyzing MT5 screenshot with Vision AI...</i>")

    try:
        # Get highest resolution photo
        photo_file = await message.photo[-1].get_file()
        file_name = f"mt5_{user.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        file_path = UPLOADS_DIR / file_name
        await photo_file.download_to_drive(file_path)

        # Parse with Vision AI / OCR engine
        trades = parse_mt5_screenshot(str(file_path), GEMINI_API_KEY)

        if not trades:
            text = (
                "⚠️ <b>No MT5 trade details detected in screenshot.</b>\n\n"
                "Please make sure the screenshot clearly shows the symbol, buy/sell type, prices, or PnL.\n"
                "Or add the trade manually with <code>/manual_trade</code>."
            )
            await status_msg.edit_text(text, parse_mode="HTML")
            return

        # Store every parsed trade and let the user confirm them in sequence.
        context.user_data["pending_trades"] = trades
        context.user_data["current_screenshot"] = str(file_path)
        context.user_data["pending_trade_index"] = 0
        context.user_data["saved_trade_count"] = 0
        context.user_data["skipped_trade_count"] = 0
        await _show_pending_trade(status_msg, context, 0)

    except Exception as e:
        logger.error(f"Photo processing error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Error processing image:</b> {str(e)}", parse_mode="HTML")

async def callback_trade_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback buttons for trade confirmation/editing."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data
    user = query.from_user
    await get_or_create_user(user.id, user.username, user.first_name)

    pending_trades = context.user_data.get("pending_trades")
    screenshot_path = context.user_data.get("current_screenshot")

    if data in ("save_current_trade", "confirm_save_trade"):
        if not pending_trades:
            await query.edit_message_text("⚠️ No pending trade found to save.")
            return

        index = context.user_data.get("pending_trade_index", 0)
        if index >= len(pending_trades):
            await query.edit_message_text("⚠️ No pending trade found to save.")
            return
        trade_data = pending_trades[index]
        trade_data["screenshot_path"] = screenshot_path
        await add_trade(user.id, trade_data)
        context.user_data["saved_trade_count"] = context.user_data.get("saved_trade_count", 0) + 1
        await _advance_pending_trade(query, context, index + 1, len(pending_trades))

    elif data == "skip_current_trade":
        if not pending_trades:
            await query.edit_message_text("⚠️ No pending trades found.")
            return
        index = context.user_data.get("pending_trade_index", 0)
        context.user_data["skipped_trade_count"] = context.user_data.get("skipped_trade_count", 0) + 1
        await _advance_pending_trade(query, context, index + 1, len(pending_trades))

    elif data in ("discard_pending_trades", "discard_pending_trade"):
        _clear_pending_trades(context)
        await query.edit_message_text("❌ Remaining trades discarded.", parse_mode="HTML")


async def _show_pending_trade(message, context: ContextTypes.DEFAULT_TYPE, index: int):
    trades = context.user_data.get("pending_trades", [])
    trade = trades[index]
    symbol = str(trade.get("symbol", "UNKNOWN"))
    trade_type = str(trade.get("trade_type", "BUY"))
    open_price = trade.get("open_price", 0.0)
    close_price = trade.get("close_price", 0.0)
    pips = calculate_pips(symbol, trade_type, open_price, close_price)
    trade["pips"] = pips
    pnl = float(trade.get("net_profit", trade.get("profit", 0.0)))
    pnl_symbol = "🟢 +" if pnl >= 0 else "🔴 -"
    count = len(trades)
    msg_text = (
        f"🎯 <b>Extracted Trade {index + 1} of {count}</b>\n"
        f"───────────────────\n"
        f"• <b>Symbol:</b> <code>{html.escape(symbol)}</code>\n"
        f"• <b>Type:</b> <b>{html.escape(trade_type)}</b>\n"
        f"• <b>Volume (Lots):</b> <code>{trade.get('volume', 0.01)}</code>\n"
        f"• <b>Open Price:</b> <code>{open_price}</code>\n"
        f"• <b>Close Price:</b> <code>{close_price}</code>\n"
        f"• <b>Pips:</b> <code>{pips:+} pips</code>\n"
        f"• <b>Net PnL:</b> <b>{pnl_symbol}${abs(pnl):,.2f}</b>\n"
        f"• <b>Ticket:</b> <code>{html.escape(str(trade.get('ticket') or 'Auto'))}</code>\n"
        f"• <b>Date/Time:</b> <code>{html.escape(str(trade.get('close_time') or 'N/A'))}</code>\n"
        f"───────────────────\n"
        f"Save this trade to your diary or skip to the next one?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Save Trade", callback_data="save_current_trade"),
            InlineKeyboardButton("⏭ Skip Trade", callback_data="skip_current_trade"),
        ],
        [InlineKeyboardButton("❌ Discard Remaining", callback_data="discard_pending_trades")],
    ]
    context.user_data["pending_trade_index"] = index
    await message.edit_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def _advance_pending_trade(message, context: ContextTypes.DEFAULT_TYPE, next_index: int, total: int):
    if next_index < total:
        editable_message = message.message if hasattr(message, "message") else message
        await _show_pending_trade(editable_message, context, next_index)
        return

    saved = context.user_data.get("saved_trade_count", 0)
    skipped = context.user_data.get("skipped_trade_count", 0)
    _clear_pending_trades(context)
    await message.edit_message_text(
        f"✅ <b>Screenshot review complete.</b>\n\n"
        f"Saved: <b>{saved}</b>\nSkipped: <b>{skipped}</b>",
        parse_mode="HTML",
    )


def _clear_pending_trades(context: ContextTypes.DEFAULT_TYPE):
    for key in ("pending_trades", "current_screenshot", "pending_trade_index", "saved_trade_count", "skipped_trade_count"):
        context.user_data.pop(key, None)
