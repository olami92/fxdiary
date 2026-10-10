import os
import logging
import datetime
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

        # Store pending parsed trades in user_data
        context.user_data["pending_trades"] = trades
        context.user_data["current_screenshot"] = str(file_path)

        # Format parsed result
        trade = trades[0] # Handle first extracted trade
        pnl = trade.get("net_profit", 0.0)
        pnl_symbol = "🟢 +" if pnl >= 0 else "🔴 -"
        pnl_color_str = f"<b>{pnl_symbol}${abs(pnl):,.2f}</b>"
        
        open_price = trade.get("open_price", 0.0)
        close_price = trade.get("close_price", 0.0)
        trade_type = trade.get("trade_type", "BUY")
        symbol = trade.get("symbol", "EURUSD")
        pips = calculate_pips(symbol, trade_type, open_price, close_price)
        trade["pips"] = pips

        msg_text = (
            f"🎯 <b>Extracted MT5 Trade Details:</b>\n"
            f"───────────────────\n"
            f"• <b>Symbol:</b> <code>{symbol}</code>\n"
            f"• <b>Type:</b> <b>{trade_type}</b>\n"
            f"• <b>Volume (Lots):</b> <code>{trade.get('volume', 0.01)}</code>\n"
            f"• <b>Open Price:</b> <code>{open_price}</code>\n"
            f"• <b>Close Price:</b> <code>{close_price}</code>\n"
            f"• <b>Pips:</b> <code>{pips:+} pips</code>\n"
            f"• <b>Net PnL:</b> {pnl_color_str}\n"
            f"• <b>Ticket:</b> <code>{trade.get('ticket') or 'Auto'}</code>\n"
            f"• <b>Date/Time:</b> <code>{trade.get('close_time')}</code>\n"
            f"───────────────────\n"
            f"Would you like to save this trade to your trading diary?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Save to Diary", callback_data="confirm_save_trade"),
                InlineKeyboardButton("✏️ Edit PnL", callback_data="prompt_edit_pnl")
            ],
            [
                InlineKeyboardButton("❌ Discard", callback_data="discard_pending_trade")
            ]
        ]

        await status_msg.edit_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

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
    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    pending_trades = context.user_data.get("pending_trades")
    screenshot_path = context.user_data.get("current_screenshot")

    if data == "confirm_save_trade":
        if not pending_trades:
            await query.edit_message_text("⚠️ No pending trade found to save.")
            return

        trade_data = pending_trades[0]
        trade_data["screenshot_path"] = screenshot_path

        # 1. Save to SQLite DB
        saved_trade = await add_trade(user.id, trade_data)

        saved_note = "✅ <b>Saved to your trading diary.</b>"

        pnl = saved_trade.net_profit
        pnl_symbol = "🟢 +" if pnl >= 0 else "🔴 -"

        done_text = (
            f"{saved_note}\n\n"
            f"📊 <b>Trade Logged:</b> <code>{saved_trade.symbol}</code> {saved_trade.trade_type} {saved_trade.volume} lots\n"
            f"💰 <b>Net PnL:</b> {pnl_symbol}${abs(pnl):,.2f}\n"
            f"📈 <b>Pips:</b> {saved_trade.pips:+} pips"
        )

        context.user_data.pop("pending_trades", None)
        await query.edit_message_text(done_text, parse_mode="HTML")

    elif data == "discard_pending_trade":
        context.user_data.pop("pending_trades", None)
        await query.edit_message_text("❌ Trade discarded.", parse_mode="HTML")
