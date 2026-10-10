import os
import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.db import get_or_create_user, get_user_trades
from bot.analytics import calculate_stats, generate_equity_chart
from bot.config import DATA_DIR

logger = logging.getLogger(__name__)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /stats command."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)
    trades = await get_user_trades(user.id, limit=500)

    if not trades:
        msg = (
            "📊 <b>No trade records found yet!</b>\n\n"
            "Send an MT5 screenshot or use <code>/manual_trade</code> to log your first trade."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_html(msg)
        return

    stats = calculate_stats(trades)

    pnl = stats["total_net_pnl"]
    pnl_symbol = "🟢 +" if pnl >= 0 else "🔴 -"
    
    text = (
        f"📊 <b>FXDiary Performance Analytics</b>\n"
        f"─────────────────────────────\n"
        f"💰 <b>Net PnL:</b> {pnl_symbol}${abs(pnl):,.2f}\n"
        f"🎯 <b>Win Rate:</b> <b>{stats['win_rate']}%</b>\n"
        f"⚡ <b>Profit Factor:</b> <code>{stats['profit_factor']}</code>\n"
        f"📈 <b>Total Pips:</b> <code>{stats['total_pips']} pips</code>\n\n"
        f"🔢 <b>Trade Count:</b> {stats['total_trades']} (<b>{stats['wins']}W</b> / <b>{stats['losses']}L</b> / <b>{stats['breakeven']}BE</b>)\n"
        f"✅ <b>Avg Win:</b> +${stats['avg_win']:,.2f}\n"
        f"❌ <b>Avg Loss:</b> -${stats['avg_loss']:,.2f}\n"
        f"🔻 <b>Max Drawdown:</b> -${stats['max_drawdown']:,.2f}\n"
        f"⭐ <b>Best Symbol:</b> <code>{stats['best_symbol']}</code>\n"
        f"🏆 <b>Best Trade:</b> +${stats['best_trade']:,.2f}\n"
        f"─────────────────────────────"
    )

    # Generate Equity Curve Chart
    chart_path = DATA_DIR / f"equity_{user.id}.png"
    chart_created = generate_equity_chart(trades, str(chart_path))

    keyboard = [
        [
            InlineKeyboardButton("📥 Download PDF Report", callback_data="export_pdf"),
            InlineKeyboardButton("📊 Export Excel Sheet", callback_data="export_excel")
        ]
    ]

    if update.callback_query:
        # Edit text or answer query
        await update.callback_query.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
        if chart_created and os.path.exists(chart_path):
            with open(chart_path, "rb") as f:
                await update.callback_query.message.reply_photo(photo=f, caption="📈 <i>Cumulative Equity PnL Curve</i>", parse_mode="HTML")
    else:
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
        if chart_created and os.path.exists(chart_path):
            with open(chart_path, "rb") as f:
                await update.message.reply_photo(photo=f, caption="📈 <i>Cumulative Equity PnL Curve</i>", parse_mode="HTML")
