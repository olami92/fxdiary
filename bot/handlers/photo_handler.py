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
from bot.db import get_or_create_user, add_trade, calculate_pips, get_open_user_trades, close_user_trade, add_user_deposit, add_user_withdrawal

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

    if data == "cancel_close_trade":
        context.user_data.pop("pending_close_data", None)
        context.user_data.pop("pending_close_trade", None)
        context.user_data.pop("open_trade_close_flow", None)
        await query.edit_message_text("Trade close cancelled. The open trade was not changed.")
        return

    if data.startswith("open_trade_close:"):
        try:
            trade_id = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            trade_id = 0
        matches = await get_open_user_trades(user.id, trade_id=trade_id)
        if not matches:
            await query.edit_message_text("That open trade is no longer available. Run /open_trade to refresh the list.")
            return
        trade = matches[0]
        context.user_data["open_trade_close_flow"] = {"trade_id": trade.id, "step": "close_price"}
        context.user_data.pop("pending_close_data", None)
        context.user_data.pop("pending_close_trade", None)
        await query.edit_message_text(
            f"Closing <b>{html.escape(trade.symbol)}</b> {trade.trade_type} {trade.volume:g} lots "
            f"(ticket #{html.escape(str(trade.ticket or trade.id))}, entry {trade.open_price:g}).\n\n"
            "Send the <b>closing price</b> for this trade.",
            parse_mode="HTML",
        )
        return

    if data.startswith("choose_close_trade:"):
        close_data = context.user_data.get("pending_close_data")
        try:
            trade_id = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            trade_id = 0
        matches = await get_open_user_trades(
            user.id,
            symbol=close_data.get("symbol") if close_data else None,
            ticket=close_data.get("ticket") if close_data else None,
            trade_id=trade_id,
        )
        if not close_data or not matches:
            context.user_data.pop("pending_close_data", None)
            await query.edit_message_text("That open trade is no longer available to close. No trade was changed.")
            return
        await _show_close_confirmation(query.message, matches[0], close_data, context)
        return

    if data == "confirm_close_trade":
        pending_close = context.user_data.get("pending_close_trade")
        if not pending_close:
            await query.edit_message_text("No trade close is waiting for confirmation.")
            return
        closed = await close_user_trade(
            user.id,
            int(pending_close["trade_id"]),
            float(pending_close["close_price"]),
            float(pending_close["net_profit"]),
        )
        context.user_data.pop("pending_close_trade", None)
        if not closed:
            await query.edit_message_text("This trade has already been closed or is no longer available.")
            return
        await query.edit_message_text(
            f"✅ <b>Trade closed and updated.</b>\n\n"
            f"• <b>Trade:</b> <code>{html.escape(closed.symbol)}</code> {closed.trade_type} {closed.volume:g} lots\n"
            f"• <b>Prices:</b> {closed.open_price:g} → {closed.close_price:g}\n"
            f"• <b>Pips:</b> {closed.pips:+g}\n"
            f"• <b>Net PnL:</b> ${closed.net_profit:+,.2f}",
            parse_mode="HTML",
        )
        return

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
        if message and message.text and user:
            if context.user_data.get("awaiting_deposit"):
                await _complete_deposit(message, user.id, context)
            elif context.user_data.get("awaiting_withdrawal"):
                await _complete_withdrawal(message, user.id, context)
            elif context.user_data.get("open_trade_close_flow"):
                await _handle_open_trade_close_reply(update, context)
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


async def open_trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List this Telegram user's open trades and let them start closing one."""
    user = update.effective_user
    if not user or not update.message:
        return
    await get_or_create_user(user.id, user.username, user.first_name)
    trades = await get_open_user_trades(user.id)
    context.user_data.pop("open_trade_close_flow", None)
    if not trades:
        await update.message.reply_text("You have no open trades right now.")
        return
    keyboard = []
    for trade in trades[:90]:
        label = f"#{trade.ticket or trade.id} · {trade.symbol} {trade.trade_type} {trade.volume:g} · {trade.open_price:g}"
        keyboard.append([InlineKeyboardButton(label[:64], callback_data=f"open_trade_close:{trade.id}")])
    await update.message.reply_html(
        f"📂 <b>Your open trades ({len(trades)})</b>\nChoose a trade to close:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record an account deposit and add it to the user's opening capital."""
    user = update.effective_user
    if not user or not update.message:
        return
    await get_or_create_user(user.id, user.username, user.first_name)
    if not context.args:
        context.user_data["awaiting_deposit"] = True
        await update.message.reply_text(
            "How much did you deposit? Send the amount in USD, for example 250 or 250.50.",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Deposit amount in USD"),
        )
        return
    await _complete_deposit(update.message, user.id, context, " ".join(context.args))


async def _complete_deposit(message, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, raw_amount: str = None):
    raw_amount = raw_amount if raw_amount is not None else message.text
    normalized = re.sub(r"^(?:USD\s*|\$\s*)", "", str(raw_amount).strip(), flags=re.IGNORECASE)
    normalized = normalized.replace(",", "")
    if not re.fullmatch(r"\+?(?:\d+(?:\.\d*)?|\.\d+)", normalized):
        await message.reply_text("Please enter a valid positive deposit amount, such as 250 or 250.50.")
        return
    amount = float(normalized)
    if not math.isfinite(amount) or amount <= 0:
        await message.reply_text("Deposit amount must be greater than zero.")
        return
    total_capital = await add_user_deposit(telegram_id, amount)
    context.user_data.pop("awaiting_deposit", None)
    if total_capital is None:
        await message.reply_text("I couldn't find your account. Please run /start and try again.")
        return
    await message.reply_html(
        f"✅ Deposit of <b>${amount:,.2f}</b> recorded.\n"
        f"Your opening capital is now <b>${total_capital:,.2f}</b>. "
        "Your dashboard balance includes this capital and your realized trade P&amp;L."
    )


async def withdrawal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record funds withdrawn from this user's account balance."""
    user = update.effective_user
    if not user or not update.message:
        return
    await get_or_create_user(user.id, user.username, user.first_name)
    if not context.args:
        context.user_data["awaiting_withdrawal"] = True
        await update.message.reply_text(
            "How much did you withdraw? Send the amount in USD, for example 50 or 50.25.",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Withdrawal amount in USD"),
        )
        return
    await _complete_withdrawal(update.message, user.id, context, " ".join(context.args))


async def _complete_withdrawal(message, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, raw_amount: str = None):
    raw_amount = raw_amount if raw_amount is not None else message.text
    normalized = re.sub(r"^(?:USD\s*|\$\s*)", "", str(raw_amount).strip(), flags=re.IGNORECASE).replace(",", "")
    if not re.fullmatch(r"\+?(?:\d+(?:\.\d*)?|\.\d+)", normalized):
        await message.reply_text("Please enter a valid positive withdrawal amount, such as 50 or 50.25.")
        return
    amount = float(normalized)
    if not math.isfinite(amount) or amount <= 0:
        await message.reply_text("Withdrawal amount must be greater than zero.")
        return
    total_withdrawals = await add_user_withdrawal(telegram_id, amount)
    context.user_data.pop("awaiting_withdrawal", None)
    if total_withdrawals is None:
        await message.reply_text("I couldn't find your account. Please run /start and try again.")
        return
    await message.reply_html(
        f"✅ Withdrawal of <b>${amount:,.2f}</b> recorded.\n"
        f"Total withdrawals: <b>${total_withdrawals:,.2f}</b>. "
        "Your dashboard balance now subtracts recorded withdrawals."
    )


async def _handle_open_trade_close_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    flow = context.user_data.get("open_trade_close_flow")
    user = update.effective_user
    if not message or not flow or not user:
        return
    try:
        value = _parse_manual_number(message.text)
        if not math.isfinite(value):
            raise ValueError
        if flow["step"] == "close_price":
            if value <= 0:
                raise ValueError
            flow["close_price"] = value
            flow["step"] = "net_profit"
            await message.reply_text("Now send the realized net PnL (use a negative number for a loss, e.g. -12.50).")
            return
        if flow["step"] == "net_profit":
            trade_matches = await get_open_user_trades(user.id, trade_id=int(flow["trade_id"]))
            if not trade_matches:
                context.user_data.pop("open_trade_close_flow", None)
                await message.reply_text("That trade is no longer open. Run /open_trade to refresh the list.")
                return
            trade = trade_matches[0]
            close_data = {
                "close_price": float(flow["close_price"]),
                "net_profit": value,
            }
            context.user_data.pop("open_trade_close_flow", None)
            await _show_close_confirmation(message, trade, close_data, context, edit_message=False)
    except (ValueError, TypeError):
        prompt = "closing price" if flow.get("step") == "close_price" else "realized net PnL"
        await message.reply_text(f"Please send a valid number for the {prompt}.")


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


async def _show_close_confirmation(message, trade, close_data, context: ContextTypes.DEFAULT_TYPE, edit_message: bool = True):
    close_price = float(close_data["close_price"])
    net_profit = float(close_data["net_profit"])
    pips = calculate_pips(trade.symbol, trade.trade_type, trade.open_price, close_price)
    context.user_data.pop("pending_close_data", None)
    context.user_data["pending_close_trade"] = {
        "trade_id": trade.id,
        "close_price": close_price,
        "net_profit": net_profit,
    }
    text = (
        "🔒 <b>Confirm closing this open trade</b>\n\n"
        f"• <b>Symbol:</b> <code>{html.escape(trade.symbol)}</code> {trade.trade_type}\n"
        f"• <b>Volume:</b> {trade.volume:g} lots\n"
        f"• <b>Entry:</b> {trade.open_price:g}\n"
        f"• <b>Close:</b> {close_price:g}\n"
        f"• <b>Calculated pips:</b> {pips:+g}\n"
        f"• <b>Realized net PnL:</b> ${net_profit:+,.2f}\n"
        f"• <b>Ticket:</b> <code>{html.escape(str(trade.ticket or trade.id))}</code>\n\n"
        "Confirm to update the existing trade."
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Close", callback_data="confirm_close_trade"),
        InlineKeyboardButton("Cancel", callback_data="cancel_close_trade"),
    ]])
    if edit_message:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


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
    is_open = str(trade.get("status", "CLOSED")).upper() == "OPEN"
    pips = calculate_pips(symbol, trade_type, open_price, close_price) if not is_open else 0.0
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
        f"• <b>Close Price:</b> <code>{'Open position' if is_open else close_price}</code>\n"
        f"• <b>Pips:</b> <code>{'Pending close' if is_open else f'{pips:+} pips'}</code>\n"
        f"• <b>Net PnL:</b> <b>{'Not realized' if is_open else f'{pnl_symbol}${abs(pnl):,.2f}'}</b>\n"
        f"• <b>Ticket:</b> <code>{html.escape(str(trade.get('ticket') or 'Auto'))}</code>\n"
        f"• <b>Date/Time:</b> <code>{html.escape(str(trade.get('close_time') or ('Open position' if is_open else 'N/A')))}</code>\n"
        f"• <b>Stop Loss:</b> <code>{html.escape(str(trade.get('sl') or 'Not set'))}</code>\n"
        f"• <b>Take Profit:</b> <code>{html.escape(str(trade.get('tp') or 'Not set'))}</code>\n"
        f"• <b>Status:</b> <code>{html.escape(str(trade.get('status') or 'CLOSED').upper())}</code>\n"
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
        f"✅ <b>Trade review complete.</b>\n\n"
        f"Saved: <b>{saved}</b>\nSkipped: <b>{skipped}</b>",
        parse_mode="HTML",
    )


def _clear_pending_trades(context: ContextTypes.DEFAULT_TYPE):
    for key in ("pending_trades", "current_screenshot", "pending_trade_index", "saved_trade_count", "skipped_trade_count"):
        context.user_data.pop(key, None)
