import os
import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Request, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from bot.config import UPLOADS_DIR, GEMINI_API_KEY, HOST, PORT
from bot.db import init_db, get_or_create_user, get_user_trades, add_trade, delete_user_trade, AsyncSessionLocal
from bot.analytics import calculate_stats, generate_equity_chart
from bot.ocr_engine import parse_mt5_screenshot
from bot.export_engine import generate_pdf_report, generate_excel_report

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="FXDiary Dashboard & Web App")

# Mount static and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))

logger = logging.getLogger(__name__)

async def _run_telegram_bot_background(token: str):
    """Run Telegram bot polling in a non-blocking background task."""
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from bot.handlers.start_handler import start_command, help_command
    from bot.handlers.sheet_handler import connect_sheet_command, sheet_info_command
    from bot.handlers.photo_handler import photo_message_handler, callback_trade_action
    from bot.handlers.stats_handler import stats_command
    from bot.handlers.trades_handler import trades_command, manual_trade_command, delete_trade_callback
    from bot.handlers.export_handler import export_command, export_callback_handler
    from bot.main import inline_shortcut_router

    try:
        logger.info("Initializing Telegram Bot in background...")
        bot_app = ApplicationBuilder().token(token).build()
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
        await bot_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Bot active and polling!")
    except Exception as e:
        logger.error(f"Error starting Telegram Bot: {e}", exc_info=True)

@app.on_event("startup")
async def startup_event():
    await init_db()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and token != "YOUR_BOT_TOKEN_HERE":
        asyncio.create_task(_run_telegram_bot_background(token))

@app.get("/", response_class=HTMLResponse)
async def index():
    """Render Web Dashboard homepage."""
    html_file = BASE_DIR / "web" / "templates" / "index.html"
    with open(html_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    return {"status": "ok", "app": "FXDiary"}

@app.get("/api/stats")
async def get_stats(telegram_id: int = 10001):
    """Fetch trading statistics JSON."""
    user = await get_or_create_user(telegram_id, username="web_user", first_name="Trader")
    trades = await get_user_trades(telegram_id, limit=500)
    stats = calculate_stats(trades)
    return JSONResponse(content={
        "user": {
            "name": user.first_name or "Trader",
            "google_sheet_id": user.google_sheet_id,
            "sheet_title": user.sheet_title
        },
        "stats": stats
    })

@app.get("/api/trades")
async def list_trades(telegram_id: int = 10001):
    """Fetch list of recent trades."""
    trades = await get_user_trades(telegram_id, limit=100)
    result = []
    for t in trades:
        result.append({
            "id": t.id,
            "ticket": t.ticket or "-",
            "symbol": t.symbol,
            "trade_type": t.trade_type,
            "volume": t.volume,
            "open_price": t.open_price,
            "close_price": t.close_price,
            "pips": t.pips,
            "profit": t.profit,
            "net_profit": t.net_profit,
            "close_time": t.close_time.strftime("%Y-%m-%d %H:%M") if t.close_time else "-"
        })
    return JSONResponse(content={"trades": result})

@app.post("/api/upload-screenshot")
async def upload_screenshot(file: UploadFile = File(...), telegram_id: int = Form(10001)):
    """Upload and OCR parse an MT5 screenshot from web dashboard."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    file_name = f"web_{telegram_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = UPLOADS_DIR / file_name

    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    trades = parse_mt5_screenshot(str(file_path), GEMINI_API_KEY)
    
    return JSONResponse(content={
        "success": True,
        "screenshot_url": f"/static/uploads/{file_name}",
        "parsed_trades": trades
    })

class ManualTradeRequest(BaseModel):
    telegram_id: int = 10001
    symbol: str
    trade_type: str
    volume: float
    open_price: float
    close_price: float
    profit: float

@app.post("/api/trades")
async def create_trade(trade_req: ManualTradeRequest):
    """Add trade manually from web dashboard."""
    user = await get_or_create_user(trade_req.telegram_id, username="web_user", first_name="Trader")
    trade_data = {
        "symbol": trade_req.symbol.upper(),
        "trade_type": trade_req.trade_type.upper(),
        "volume": trade_req.volume,
        "open_price": trade_req.open_price,
        "close_price": trade_req.close_price,
        "profit": trade_req.profit,
        "net_profit": trade_req.profit,
        "close_time": datetime.datetime.utcnow()
    }
    trade = await add_trade(trade_req.telegram_id, trade_data)
    return JSONResponse(content={"success": True, "trade_id": trade.id})

@app.delete("/api/trades/{trade_id}")
async def delete_trade_endpoint(trade_id: int, telegram_id: int = 10001):
    """Delete trade by ID."""
    success = await delete_user_trade(telegram_id, trade_id)
    return JSONResponse(content={"success": success})

@app.get("/api/export/pdf")
async def download_pdf(telegram_id: int = 10001):
    """Export PDF report."""
    user = await get_or_create_user(telegram_id, username="web_user", first_name="Trader")
    trades = await get_user_trades(telegram_id, limit=500)
    stats = calculate_stats(trades)
    
    pdf_path = str(UPLOADS_DIR / f"FXDiary_Report_{telegram_id}.pdf")
    user_info = {"first_name": user.first_name or "Trader", "username": user.username}
    
    if generate_pdf_report(user_info, trades, stats, pdf_path):
        return FileResponse(pdf_path, filename="FXDiary_Performance_Report.pdf", media_type="application/pdf")
    raise HTTPException(status_code=500, detail="Failed to generate PDF report")

@app.get("/api/export/excel")
async def download_excel(telegram_id: int = 10001):
    """Export Excel spreadsheet."""
    user = await get_or_create_user(telegram_id, username="web_user", first_name="Trader")
    trades = await get_user_trades(telegram_id, limit=500)
    stats = calculate_stats(trades)
    
    excel_path = str(UPLOADS_DIR / f"FXDiary_Journal_{telegram_id}.xlsx")
    user_info = {"first_name": user.first_name or "Trader", "username": user.username}
    
    if generate_excel_report(user_info, trades, stats, excel_path):
        return FileResponse(
            excel_path,
            filename="FXDiary_Trading_Journal.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    raise HTTPException(status_code=500, detail="Failed to generate Excel report")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"--> Binding web.app to 0.0.0.0:{port}...")
    uvicorn.run("web.app:app", host="0.0.0.0", port=port)
