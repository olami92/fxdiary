import os
import logging
import datetime
import html
import math
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
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
    context.user_data["failed_screenshot_file_id"] = message.photo[-1].file_id
    context.user_data.pop("awaiting_manual_entry", None)

    status_msg = await message.reply_html("🔍 <i>Analyzing MT5 screenshot with Vision AI...</i>")
    file_path = None

    try:
        # Get highest resolution photo
        photo_file = await message.photo[-1].get_file()
        file_name = f"mt5_{user.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        file_path = UPLOADS_DIR / file_name
        await photo_file.download_to_drive(file_path)
        context.user_data["current_screenshot"] = str(file_path)

        # Parse with Vision AI / OCR engine
        trades = parse_mt5_screenshot(str(file_path), GEMINI_API_KEY)

        if not trades:
            await _show_ocr_failure(status_msg)
            return

        await _queue_extracted_trades(trades, str(file_path), status_msg, context)

    except Exception as e:
        logger.error(f"Photo processing error: {e}", exc_info=True)
        if file_path:
            context.user_data["current_screenshot"] = str(file_path)
        await _show_ocr_failure(status_msg, "The screenshot could not be analyzed. Retry or enter the trade manually.")

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

    if data == "retry_ocr":
        await query.edit_message_text("🔄 <i>Retrying screenshot analysis...</i>", parse_mode="HTML")
        try:
            if not screenshot_path or not Path(screenshot_path).is_file():
                file_id = context.user_data.get("failed_screenshot_file_id")
                if not file_id:
                    raise FileNotFoundError("The original screenshot is no longer available.")
                photo_file = await context.bot.get_file(file_id)
                screenshot_path = str(UPLOADS_DIR / f"retry_{user.id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
                await photo_file.download_to_drive(screenshot_path)
                context.user_data["current_screenshot"] = screenshot_path
            trades = parse_mt5_screenshot(screenshot_path, GEMINI_API_KEY)
        except Exception as e:
            logger.error(f"OCR retry failed: {e}", exc_info=True)
            trades = []
        if trades:
            await _queue_extracted_trades(trades, screenshot_path, query.message, context)
        else:
            await _show_ocr_failure(query.message, "The screenshot could not be read. Retry or enter the trade manually.")

    elif data == "manual_entry":
        context.user_data["awaiting_manual_entry"] = True
        await query.edit_message_text("📝 <b>Manual trade entry</b>\n\nReply to the template below. Pips will be calculated automatically.", parse_mode="HTML")
        await query.message.reply_text(
            _manual_entry_template(),
            parse_mode="HTML",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Fill in the trade details"),
        )

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


async def manual_entry_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse and save a manually completed trade template."""
    message = update.message
    user = update.effective_user
    if not message or not message.text or not user or not context.user_data.get("awaiting_manual_entry"):
        return

    fields = {}
    for line in message.text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lstrip("•*- ").casefold()] = value.strip()

    required = ("symbol", "type", "volume (lots)", "open price", "close price", "net pnl")
    if any(not fields.get(label) for label in required):
        await _reply_manual_entry_error(message, "Please fill in all required fields and reply again.")
        return

    try:
        symbol = fields["symbol"].upper().strip()
        if not re.fullmatch(r"[A-Z0-9._-]{3,20}", symbol):
            raise ValueError("Enter a valid symbol, such as EURUSD.")
        trade_type = fields["type"].upper().strip()
        if trade_type not in ("BUY", "SELL"):
            raise ValueError("Type must be BUY or SELL.")
        volume = _parse_manual_number(fields["volume (lots)"])
        open_price = _parse_manual_number(fields["open price"])
        close_price = _parse_manual_number(fields["close price"])
        net_profit = _parse_manual_number(fields["net pnl"])
        if not all(math.isfinite(value) for value in (volume, open_price, close_price, net_profit)):
            raise ValueError("Enter valid numbers for volume, prices, and net PnL.")
        if volume <= 0 or open_price <= 0 or close_price <= 0:
            raise ValueError("Volume and prices must be greater than zero.")
    except ValueError as e:
        await _reply_manual_entry_error(message, str(e))
        return

    ticket = fields.get("ticket", "").strip()
    trade_data = {
        "symbol": symbol,
        "trade_type": trade_type,
        "volume": volume,
        "open_price": open_price,
        "close_price": close_price,
        "profit": net_profit,
        "net_profit": net_profit,
        "pips": calculate_pips(symbol, trade_type, open_price, close_price),
        "ticket": None if ticket.casefold() in ("", "auto", "none", "n/a", "optional") else ticket,
        "close_time": fields.get("date/time", "").strip() or datetime.datetime.utcnow(),
        "screenshot_path": context.user_data.get("current_screenshot"),
    }
    await get_or_create_user(user.id, user.username, user.first_name)
    saved = await add_trade(user.id, trade_data)
    context.user_data.pop("awaiting_manual_entry", None)
    await message.reply_html(
        f"✅ <b>Trade saved to your diary.</b>\n\n"
        f"• <b>Symbol:</b> <code>{html.escape(saved.symbol)}</code> {saved.trade_type}\n"
        f"• <b>Net PnL:</b> ${saved.net_profit:+,.2f}\n"
        f"• <b>Pips:</b> {saved.pips:+}"
    )


def _parse_manual_number(value: str) -> float:
    normalized = value.replace("−", "-")
    match = re.search(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", normalized)
    if not match:
        raise ValueError("Enter valid numbers for volume, prices, and net PnL.")
    return float(match.group(0).replace(",", ""))


def _manual_entry_template() -> str:
    return (
        "<b>Manual Trade Template</b>\n"
        "Copy this template, fill in the values, then reply with it:\n\n"
        "• <b>Symbol:</b>\n"
        "• <b>Type:</b> BUY or SELL\n"
        "• <b>Volume (Lots):</b>\n"
        "• <b>Open Price:</b>\n"
        "• <b>Close Price:</b>\n"
        "• <b>Pips:</b> Auto-calculated\n"
        "• <b>Net PnL:</b>\n"
        "• <b>Ticket:</b> optional\n"
        "• <b>Date/Time:</b> YYYY-MM-DD HH:MM:SS (optional)"
    )


async def _reply_manual_entry_error(message, error: str):
    await message.reply_text(
        f"⚠️ {html.escape(error)}\n\n{_manual_entry_template()}",
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Correct the trade details"),
    )


async def _show_ocr_failure(message, explanation: str = "The screenshot did not contain readable trade details."):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Retry", callback_data="retry_ocr"),
        InlineKeyboardButton("✍️ Manual Entry", callback_data="manual_entry"),
    ]])
    await message.edit_text(
        f"❌ <b>Failed to generate result.</b>\n\n{html.escape(explanation)}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def _queue_extracted_trades(trades, screenshot_path: str, message, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pending_trades"] = trades
    context.user_data["current_screenshot"] = screenshot_path
    context.user_data["pending_trade_index"] = 0
    context.user_data["saved_trade_count"] = 0
    context.user_data["skipped_trade_count"] = 0
    context.user_data.pop("awaiting_manual_entry", None)
    await _show_pending_trade(message, context, 0)


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
