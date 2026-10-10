import os
import sys
import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from bot.config import TELEGRAM_BOT_TOKEN
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

bot_instance = None
bot_task = None

async def run_telegram_bot_background():
    """Background runner for Telegram Bot so the Web Server port binds instantly."""
    global bot_instance
    token = os.getenv("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.warning("TELEGRAM_BOT_TOKEN not provided. Bot polling will not start.")
        return

    try:
        logger.info("Starting Telegram Bot Polling in background...")
        bot_instance = ApplicationBuilder().token(token).build()

        # Register Handlers
        bot_instance.add_handler(CommandHandler("start", start_command))
        bot_instance.add_handler(CommandHandler("help", help_command))
        bot_instance.add_handler(CommandHandler("connect_sheet", connect_sheet_command))
        bot_instance.add_handler(CommandHandler("sheet_info", sheet_info_command))
        bot_instance.add_handler(CommandHandler("stats", stats_command))
        bot_instance.add_handler(CommandHandler("trades", trades_command))
        bot_instance.add_handler(CommandHandler("manual_trade", manual_trade_command))
        bot_instance.add_handler(CommandHandler("export", export_command))

        bot_instance.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))

        bot_instance.add_handler(CallbackQueryHandler(callback_trade_action, pattern="^(confirm_save_trade|discard_pending_trade)$"))
        bot_instance.add_handler(CallbackQueryHandler(delete_trade_callback, pattern="^del_trade_"))
        bot_instance.add_handler(CallbackQueryHandler(export_callback_handler, pattern="^export_"))
        bot_instance.add_handler(CallbackQueryHandler(inline_shortcut_router, pattern="^cmd_"))

        await bot_instance.initialize()
        await bot_instance.start()
        await bot_instance.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Bot active & polling successfully!")
    except Exception as e:
        logger.error(f"Telegram Bot failed to start: {e}", exc_info=True)

@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: initializes DB and launches bot in background task."""
    global bot_task, bot_instance
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)

    # Launch bot in background task - this allows FastAPI to bind port IMMEDIATELY!
    bot_task = asyncio.create_task(run_telegram_bot_background())

    yield  # Port is open and listening now for Render health check!

    if bot_instance and bot_instance.updater and bot_instance.updater.running:
        try:
            logger.info("Stopping Telegram Bot...")
            await bot_instance.updater.stop()
            await bot_instance.stop()
            await bot_instance.shutdown()
        except Exception as e:
            logger.warning(f"Error during bot shutdown: {e}")

    if bot_task:
        bot_task.cancel()

fastapi_app.router.lifespan_context = lifespan

# Alias for uvicorn
app = fastapi_app

if __name__ == "__main__":
    # Render provides PORT env var (e.g., 10000)
    port_env = os.getenv("PORT", "8000")
    port = int(port_env)
    print(f"\n==========================================")
    print(f"--> Starting FXDiary on 0.0.0.0:{port}...")
    print(f"==========================================\n")
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
