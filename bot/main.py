import logging
import sys
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)

from bot.config import TELEGRAM_BOT_TOKEN
from bot.db import init_db
from bot.handlers.start_handler import start_command, help_command
from bot.handlers.photo_handler import photo_message_handler, callback_trade_action, manual_entry_message_handler, open_trade_command, deposit_command
from bot.handlers.voice_handler import voice_message_handler
from bot.handlers.stats_handler import stats_command
from bot.handlers.trades_handler import trades_command, manual_trade_command, delete_trade_callback
from bot.handlers.export_handler import export_command, export_callback_handler
from bot.economic_calendar import start_economic_calendar_alerts

# Configure Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def _post_init(application):
    start_economic_calendar_alerts(application)

async def inline_shortcut_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route quick navigation inline buttons from start menu."""
    query = update.callback_query
    if not query:
        return

    data = query.data
    if data == "cmd_stats":
        await stats_command(update, context)
    elif data == "cmd_trades_list":
        await trades_command(update, context)
    elif data == "cmd_export_prompt":
        await export_command(update, context)
    elif data == "cmd_manual_trade_prompt":
        await query.message.reply_html(
            "✏️ <b>Add a trade manually</b>\n\n"
            "Use <code>/manual_trade &lt;Symbol&gt; &lt;BUY/SELL&gt; &lt;Lots&gt; &lt;OpenPrice&gt; &lt;ClosePrice&gt; &lt;NetPnL&gt;</code>."
        )

def main():
    """Start the FXDiary Telegram Bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env file!")
        print("\n❌ ERROR: Please set your TELEGRAM_BOT_TOKEN in .env file before running the bot.\n")
        sys.exit(1)

    # Initialize Database
    asyncio.run(init_db())
    logger.info("Database initialized successfully.")

    # Build Telegram Bot Application
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("trades", trades_command))
    app.add_handler(CommandHandler("open_trade", open_trade_command))
    app.add_handler(CommandHandler("deposit", deposit_command))
    app.add_handler(CommandHandler("manual_trade", manual_trade_command))
    app.add_handler(CommandHandler("export", export_command))

    # Photo Screenshot Handler
    app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_message_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_entry_message_handler))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(callback_trade_action, pattern="^(save_current_trade|skip_current_trade|discard_pending_trades|confirm_save_trade|discard_pending_trade|retry_ocr|manual_entry|confirm_close_trade|cancel_close_trade|choose_close_trade:\\d+|open_trade_close:\\d+)$"))
    app.add_handler(CallbackQueryHandler(delete_trade_callback, pattern="^del_trade_"))
    app.add_handler(CallbackQueryHandler(export_callback_handler, pattern="^export_"))
    app.add_handler(CallbackQueryHandler(inline_shortcut_router, pattern="^cmd_"))

    logger.info("FXDiary Telegram Bot is running... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
