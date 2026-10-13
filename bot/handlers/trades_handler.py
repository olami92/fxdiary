import logging
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.db import get_or_create_user, get_user_trades, delete_user_trade, add_trade, DuplicateTradeError

logger = logging.getLogger(__name__)

async def trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /trades command."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)
    trades = await get_user_trades(user.id, limit=20)

    if not trades:
        text = (
            "📋 <b>No trade history logged yet.</b>\n\n"
            "Send an MT5 history screenshot to add trades, or use <code>/manual_trade</code>."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        else:
            await update.message.reply_html(text)
        return

    msg = f"📋 <b>Recent Trade History (Last {len(trades)} trades):</b>\n─────────────────────────────\n"
    keyboard = []

    for idx, t in enumerate(trades[:10], start=1):
        pnl = t.net_profit
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        close_str = t.close_time.strftime("%m/%d %H:%M") if t.close_time else "N/A"
        
        msg += f"<b>{idx}.</b> {pnl_icon} <code>{t.symbol}</code> {t.trade_type} {t.volume} lots | <b>${pnl:+,.2f}</b> ({close_str})\n"
        keyboard.append([
            InlineKeyboardButton(f"🗑️ Delete #{t.id} ({t.symbol})", callback_data=f"del_trade_{t.id}")
        ])

    msg += "─────────────────────────────\n<i>To export your complete journal, run /export.</i>"

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_html(msg, reply_markup=reply_markup)

async def delete_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback for deleting a trade."""
    query = update.callback_query
    if not query or not query.data.startswith("del_trade_"):
        return
    await query.answer()

    trade_id = int(query.data.split("_")[-1])
    user = query.from_user

    success = await delete_user_trade(user.id, trade_id)
    if success:
        await query.edit_message_text(f"✅ Trade #{trade_id} deleted successfully.")
    else:
        await query.edit_message_text(f"❌ Failed to delete trade #{trade_id}.")

async def manual_trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /manual_trade <Symbol> <BUY/SELL> <Lots> <OpenPrice> <ClosePrice> <PnL>."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    if len(context.args) < 6:
        text = (
            "✏️ <b>Manual Trade Entry Usage:</b>\n\n"
            "<code>/manual_trade &lt;Symbol&gt; &lt;Type&gt; &lt;Lots&gt; &lt;OpenPrice&gt; &lt;ClosePrice&gt; &lt;NetPnL&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/manual_trade XAUUSD BUY 0.50 2050.20 2060.20 500.00</code>"
        )
        await update.message.reply_html(text)
        return

    try:
        symbol = context.args[0].upper()
        trade_type = context.args[1].upper()
        volume = float(context.args[2])
        open_price = float(context.args[3])
        close_price = float(context.args[4])
        profit = float(context.args[5])

        trade_data = {
            "symbol": symbol,
            "trade_type": trade_type,
            "volume": volume,
            "open_price": open_price,
            "close_price": close_price,
            "profit": profit,
            "net_profit": profit,
            "close_time": datetime.datetime.utcnow()
        }

        try:
            trade = await add_trade(user.id, trade_data)
        except DuplicateTradeError as error:
            await update.message.reply_text(f"⚠️ {error} No duplicate entry was added.")
            return
        pnl_symbol = "🟢 +" if profit >= 0 else "🔴 -"
        
        await update.message.reply_html(
            f"✅ <b>Manual Trade Logged!</b>\n\n"
            f"• <b>Symbol:</b> <code>{symbol}</code>\n"
            f"• <b>Type:</b> {trade_type} {volume} lots\n"
            f"• <b>Prices:</b> <code>{open_price} → {close_price}</code>\n"
            f"• <b>Net PnL:</b> {pnl_symbol}${abs(profit):,.2f}"
        )
    except Exception as e:
        await update.message.reply_html(f"❌ Invalid arguments format. Error: {str(e)}")
