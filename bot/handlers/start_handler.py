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
        f"3️⃣ Verify & confirm to record it in your <b>Google Sheet</b> and local diary!\n\n"
        f"📊 <b>Commands:</b>\n"
        f"• /connect_sheet <code>&lt;URL or ID&gt;</code> - Link your Google Sheet\n"
        f"• /sheet_info - Check connected Google Sheet status\n"
        f"• /stats - View win rate, PnL & equity curve chart\n"
        f"• /trades - View recent trades & edit history\n"
        f"• /export - Download PDF or Excel report\n"
        f"• /help - Full user guide & setup\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📊 View Analytics", callback_query_data="cmd_stats"),
            InlineKeyboardButton("📄 Connect Sheet", callback_query_data="cmd_connect_sheet_prompt")
        ],
        [
            InlineKeyboardButton("📥 Export PDF/Excel", callback_query_data="cmd_export_prompt"),
            InlineKeyboardButton("📋 My Trades", callback_query_data="cmd_trades_list")
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
        "<b>1. Google Sheet Setup:</b>\n"
        "• Create a Google Sheet and share write access with your bot service account email.\n"
        "• Run <code>/connect_sheet &lt;your_google_sheet_url&gt;</code> to link it.\n\n"
        "<b>2. Uploading Screenshots:</b>\n"
        "• Send any MT5 mobile or desktop trade screenshot directly as an image.\n"
        "• The bot will extract trade fields and ask for confirmation.\n\n"
        "<b>3. Querying & Reports:</b>\n"
        "• Use <code>/stats</code> to view win rate, profit factor, max drawdown, and equity curve.\n"
        "• Use <code>/export</code> to generate a PDF report or Excel spreadsheet.\n\n"
        "Need help? Contact support or check documentation."
    )
    await update.message.reply_html(help_text)
