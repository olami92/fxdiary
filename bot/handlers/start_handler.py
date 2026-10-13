import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.db import get_or_create_user

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name
    )

    welcome_text = (
        f"👋 <b>Welcome to FXDiary Bot, {user.first_name}!</b>\n\n"
        f"I am your automated <b>MetaTrader 5 (MT5) Trading Journal Assistant</b>.\n\n"
        f"📸 <b>How it works:</b>\n"
        f"1️⃣ Simply send me a <b>screenshot of your MT5 trade history</b>.\n"
        f"2️⃣ My Vision AI will instantly extract the ticket, symbol, lot size, prices, and PnL.\n"
        f"3️⃣ Verify & confirm to save it to your personal trading diary!\n\n"
        f"📊 <b>Commands:</b>\n"
        f"• /stats - View win rate, PnL & equity curve chart\n"
        f"• /trades - View recent trades & edit history\n"
        f"• /open_trade - Choose and close an open trade\n"
        f"• /deposit - Add funds to your opening capital\n"
        f"• /withdrawal - Record funds withdrawn from your account\n"
        f"• /export - Download PDF or Excel report\n"
        f"• /help - Full user guide & setup\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📊 View Analytics", callback_query_data="cmd_stats"),
            InlineKeyboardButton("📋 My Trades", callback_query_data="cmd_trades_list")
        ],
        [
            InlineKeyboardButton("📥 Export PDF/Excel", callback_query_data="cmd_export_prompt"),
            InlineKeyboardButton("✏️ Add Trade", callback_query_data="cmd_manual_trade_prompt")
        ]
    ]

    await update.message.reply_html(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    help_text = (
        "📖 <b>FXDiary Bot User Guide</b>\n\n"
        "<b>Log a trade with a voice note:</b>\n"
        "• Tap the voice-record button, dictate your trade details, then send the recording. No command is needed.\n"
        "• Include the symbol, BUY/SELL direction, lot size, and entry price. You can also say the stop loss and take profit.\n"
        "• For a closed trade, include its closing price and realized profit/loss.\n"
        "• Check the parsed details and tap <b>Save Trade</b> to add it to your diary, or <b>Skip Trade</b> to discard it.\n"
        "• Trades without a closing price and realized PnL are saved as <b>Open</b> positions.\n\n"
        "<b>Close an Open trade by voice:</b>\n"
        "• Say: <i>Close my EURUSD trade at 1.0800 with net profit 25 dollars.</i>\n"
        "• Include the closing price and realized net profit or loss. If multiple open trades match, choose the correct ticket; confirm before the trade is updated.\n\n"
        "<b>Close an Open trade with /open_trade:</b>\n"
        "• Run <code>/open_trade</code>, choose a trade, then send its closing price and realized net PnL. Use a negative amount for a loss. Review and confirm before it is updated.\n\n"
        "<b>Record an account deposit:</b>\n"
        "• Use <code>/deposit 250</code> to add a $250 deposit to your opening capital, or run <code>/deposit</code> and reply with the amount. The dashboard balance updates to include the deposit.\n\n"
        "<b>Record an account withdrawal:</b>\n"
        "• Use <code>/withdrawal 50</code> to record a $50 withdrawal, or run <code>/withdrawal</code> and reply with the amount. The dashboard balance subtracts recorded withdrawals.\n\n"
        "<b>Manual entry:</b>\n"
        "• Tap <b>✏️ Add Trade</b> in the bot menu, or choose <b>Manual Entry</b> if screenshot reading fails.\n"
        "• Fill in the trade template and reply to it. Pips are calculated automatically.\n"
        "• You can also use <code>/manual_trade SYMBOL TYPE LOTS OPEN CLOSE NET_PNL</code>.\n"
        "  Example: <code>/manual_trade EURUSD SELL 0.50 1.0850 1.0800 250.00</code>\n\n"
        "<b>Log from an MT5 screenshot:</b>\n"
        "• Send a screenshot of your MT5 trade history. Review each extracted trade and confirm which ones to save.\n\n"
        "<b>Stats and reports:</b>\n"
        "• <code>/stats</code> — view performance statistics and your equity curve.\n"
        "• <code>/trades</code> — view recent trades.\n"
        "• <code>/open_trade</code> — choose and close one of your open trades.\n"
        "• <code>/deposit</code> — record a deposit and increase your opening capital.\n"
        "• <code>/withdrawal</code> (or <code>/withdraw</code>) — record a withdrawal and reduce your dashboard balance.\n"
        "• <code>/export</code> — generate a PDF or Excel report.\n"
        "• <code>/help</code> — show this guide.\n\n"
        "Need help? Contact support or check documentation."
    )
    if update.message:
        await update.message.reply_html(help_text)
