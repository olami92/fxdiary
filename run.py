import os
import sys
import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from bot.config import PORT, HOST, TELEGRAM_BOT_TOKEN, GEMINI_API_KEY
from bot.db import init_db
from bot.main import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
    start_command, help_command, connect_sheet_command, sheet_info_command,
    photo_message_handler, callback_trade_action, stats_command, trades_command,
    manual_trade_command, delete_trade_callback, export_command, export_callback_handler,
    inline_shortcut_router
)
from web.app import app as fastapi_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("fxdiary_runner")

@asynccontextmanager
async def lifespan(app):
    """Lifecycle manager to initialize database and run Telegram Bot alongside FastAPI."""
    logger.info("Initializing database...")
    await init_db()

    bot_app = None
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
        logger.info("Starting Telegram Bot Polling in background...")
        bot_app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        # Register Handlers
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(CommandHandler("connect_sheet", connect_sheet_command))
        bot_app.add_handler(CommandHandler("sheet_info", sheet_info_command))
        bot_app.add_handler(CommandHandler("stats", stats_command))
        bot_app.add_handler(CommandHandler("trades", trades_command))
        bot_app.add_handler(CommandHandler("manual_trade", manual_trade_command))
        bot_app.add_handler(CommandHandler("export", export_command))

        bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))

        bot_app.add_handler(CallbackQueryHandler(callback_trade_action, pattern="^(confirm_save_trade|discard_pending_trade)$"))
        bot_app.add_handler(CallbackQueryHandler(delete_trade_callback, pattern="^del_trade_"))
        bot_app.add_handler(CallbackQueryHandler(export_callback_handler, pattern="^export_"))
        bot_app.add_handler(CallbackQueryHandler(inline_shortcut_router, pattern="^cmd_"))

        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Telegram Bot active & listening!")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not provided. Running Web Server only.")

    yield

    if bot_app:
        logger.info("Stopping Telegram Bot...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()

fastapi_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.getenv("PORT", PORT))
    logger.info(f"Starting FXDiary Server on {HOST}:{port}...")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
