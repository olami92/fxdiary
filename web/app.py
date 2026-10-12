import os
import sys
import logging
import asyncio
import datetime
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Request, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from bot.config import UPLOADS_DIR, GEMINI_API_KEY, HOST, PORT
from bot.db import init_db, get_or_create_user, get_user_trades, count_user_trades, add_trade, delete_user_trade, AsyncSessionLocal
from bot.analytics import calculate_stats, generate_equity_chart
from bot.ocr_engine import parse_mt5_screenshot
from bot.export_engine import generate_pdf_report, generate_excel_report

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="FXDiary Dashboard & Web App")
SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("TELEGRAM_BOT_TOKEN") or secrets.token_urlsafe(32)
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=os.getenv("RENDER", "") != "")

# Mount static and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))

logger = logging.getLogger(__name__)

async def _run_telegram_bot_background(token: str):
    """Run Telegram bot polling in a non-blocking background task."""
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from bot.handlers.start_handler import start_command, help_command
    from bot.handlers.photo_handler import photo_message_handler, callback_trade_action, manual_entry_message_handler
    from bot.handlers.voice_handler import voice_message_handler
    from bot.handlers.stats_handler import stats_command
    from bot.handlers.trades_handler import trades_command, manual_trade_command, delete_trade_callback
    from bot.handlers.export_handler import export_command, export_callback_handler
    from bot.economic_calendar import start_economic_calendar_alerts
    from bot.main import inline_shortcut_router

    try:
        logger.info("Initializing Telegram Bot in background...")
        bot_app = ApplicationBuilder().token(token).build()
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(CommandHandler("stats", stats_command))
        bot_app.add_handler(CommandHandler("trades", trades_command))
        bot_app.add_handler(CommandHandler("manual_trade", manual_trade_command))
        bot_app.add_handler(CommandHandler("export", export_command))
        bot_app.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
        bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_message_handler))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_entry_message_handler))
        bot_app.add_handler(CallbackQueryHandler(callback_trade_action, pattern="^(save_current_trade|skip_current_trade|discard_pending_trades|confirm_save_trade|discard_pending_trade|retry_ocr|manual_entry|confirm_close_trade|cancel_close_trade|choose_close_trade:\\d+|open_trade_close:\\d+)$"))
        bot_app.add_handler(CallbackQueryHandler(delete_trade_callback, pattern="^del_trade_"))
        bot_app.add_handler(CallbackQueryHandler(export_callback_handler, pattern="^export_"))
        bot_app.add_handler(CallbackQueryHandler(inline_shortcut_router, pattern="^cmd_"))

        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        start_economic_calendar_alerts(bot_app)
        logger.info("Telegram Bot active and polling!")
    except Exception as e:
        logger.warning(f"Telegram Bot polling warning: {e}. If another instance is running, only one can poll at a time.")

@app.on_event("startup")
async def startup_event():
    await init_db()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and token != "YOUR_BOT_TOKEN_HERE":
        asyncio.create_task(_run_telegram_bot_background(token))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render Web Dashboard homepage."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"telegram_bot_username": TELEGRAM_BOT_USERNAME},
    )


def _verified_telegram_user(auth_data: dict) -> dict:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    received_hash = auth_data.get("hash")
    if not bot_token or not received_hash:
        raise HTTPException(status_code=401, detail="Telegram sign-in is not configured.")

    try:
        auth_date = int(auth_data.get("auth_date", 0))
        user_id = int(auth_data.get("id", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid Telegram sign-in data.")

    if user_id <= 0 or auth_date > time.time() + 30 or time.time() - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Telegram sign-in data has expired or is invalid.")

    check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(auth_data.items())
        if key != "hash" and value is not None
    )
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, str(received_hash)):
        raise HTTPException(status_code=401, detail="Telegram sign-in could not be verified.")
    return auth_data


def _verified_mini_app_user(init_data: str) -> dict:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token or not isinstance(init_data, str) or not init_data:
        raise HTTPException(status_code=401, detail="Telegram Mini App sign-in is not available.")

    try:
        if len(init_data) > 8192:
            raise ValueError("sign-in data too large")
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("duplicate fields")
        auth_date = int(fields.get("auth_date", 0))
        user_data = json.loads(fields.get("user", "{}"))
        user_id = int(user_data.get("id", 0))
        received_hash = fields.get("hash", "")
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid Telegram Mini App sign-in data.")

    now = time.time()
    if user_id <= 0 or auth_date > now + 30 or now - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Telegram Mini App sign-in data has expired or is invalid.")

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(fields.items())
        if key != "hash"
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not received_hash or not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram Mini App sign-in could not be verified.")
    return user_data


async def _require_dashboard_user(request: Request):
    user_id = request.session.get("telegram_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Please sign in with Telegram.")
    return await get_or_create_user(
        int(user_id),
        username=request.session.get("username"),
        first_name=request.session.get("first_name"),
    )


@app.post("/api/auth/telegram")
async def telegram_login(request: Request):
    auth_data = await request.json()
    user_data = _verified_telegram_user(auth_data)
    request.session.clear()
    request.session["telegram_id"] = int(user_data["id"])
    request.session["username"] = user_data.get("username")
    request.session["first_name"] = user_data.get("first_name")
    user = await _require_dashboard_user(request)
    return {"id": user.telegram_id, "first_name": user.first_name, "username": user.username}


@app.post("/api/auth/telegram-miniapp")
async def telegram_mini_app_login(request: Request):
    payload = await request.json()
    user_data = _verified_mini_app_user(payload.get("init_data") if isinstance(payload, dict) else None)
    request.session.clear()
    request.session["telegram_id"] = int(user_data["id"])
    request.session["username"] = user_data.get("username")
    request.session["first_name"] = user_data.get("first_name")
    user = await _require_dashboard_user(request)
    return {"id": user.telegram_id, "first_name": user.first_name, "username": user.username}


@app.get("/api/auth/me")
async def current_dashboard_user(request: Request):
    user = await _require_dashboard_user(request)
    return {"id": user.telegram_id, "first_name": user.first_name, "username": user.username}


@app.post("/api/auth/logout")
async def telegram_logout(request: Request):
    request.session.clear()
    return {"success": True}

@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    return {"status": "ok", "app": "FXDiary"}

@app.get("/api/stats")
async def get_stats(request: Request):
    """Fetch trading statistics JSON."""
    user = await _require_dashboard_user(request)
    trades = await get_user_trades(user.telegram_id, limit=500)
    stats = calculate_stats(trades)
    return JSONResponse(content={
        "user": {"name": user.first_name or "Trader"},
        "stats": stats
    })

@app.get("/api/trades")
async def list_trades(request: Request, page: int = Query(1, ge=1)):
    """Fetch one page of the signed-in user's trade history."""
    user = await _require_dashboard_user(request)
    page_size = 20
    total_trades = await count_user_trades(user.telegram_id)
    total_pages = max(1, (total_trades + page_size - 1) // page_size)
    page = min(page, total_pages)
    trades = await get_user_trades(
        user.telegram_id, limit=page_size, offset=(page - 1) * page_size
    )
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
            "status": t.status,
            "pips": t.pips,
            "profit": t.profit,
            "net_profit": t.net_profit,
            "close_time": t.close_time.strftime("%Y-%m-%d %H:%M") if t.close_time else "-"
        })
    return JSONResponse(content={
        "trades": result,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_trades": total_trades,
            "total_pages": total_pages,
        },
    })

@app.post("/api/upload-screenshot")
async def upload_screenshot(request: Request, file: UploadFile = File(...)):
    """Upload and OCR parse an MT5 screenshot from web dashboard."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    user = await _require_dashboard_user(request)
    telegram_id = user.telegram_id

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
    symbol: str
    trade_type: str
    volume: float
    open_price: float
    close_price: float
    profit: float

@app.post("/api/trades")
async def create_trade(trade_req: ManualTradeRequest, request: Request):
    """Add trade manually from web dashboard."""
    user = await _require_dashboard_user(request)
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
    trade = await add_trade(user.telegram_id, trade_data)
    return JSONResponse(content={"success": True, "trade_id": trade.id})

@app.delete("/api/trades/{trade_id}")
async def delete_trade_endpoint(trade_id: int, request: Request):
    """Delete trade by ID."""
    user = await _require_dashboard_user(request)
    success = await delete_user_trade(user.telegram_id, trade_id)
    return JSONResponse(content={"success": success})

@app.get("/api/export/pdf")
async def download_pdf(request: Request):
    """Export PDF report."""
    user = await _require_dashboard_user(request)
    telegram_id = user.telegram_id
    trades = await get_user_trades(telegram_id, limit=500)
    stats = calculate_stats(trades)
    
    pdf_path = str(UPLOADS_DIR / f"FXDiary_Report_{telegram_id}.pdf")
    user_info = {"first_name": user.first_name or "Trader", "username": user.username}
    
    if generate_pdf_report(user_info, trades, stats, pdf_path):
        return FileResponse(pdf_path, filename="FXDiary_Performance_Report.pdf", media_type="application/pdf")
    raise HTTPException(status_code=500, detail="Failed to generate PDF report")

@app.get("/api/export/excel")
async def download_excel(request: Request):
    """Export Excel spreadsheet."""
    user = await _require_dashboard_user(request)
    telegram_id = user.telegram_id
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
