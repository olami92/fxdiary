import asyncio
import os
import sys
import datetime

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bot.db import init_db, get_or_create_user, add_trade, get_user_trades
from bot.analytics import calculate_stats, generate_equity_chart
from bot.export_engine import generate_pdf_report, generate_excel_report
from bot.config import DATA_DIR, UPLOADS_DIR

async def run_tests():
    print("[+] Starting FXDiary core test suite...")
    
    # 1. Init Database
    await init_db()
    print("[+] Database initialized successfully.")

    # 2. Add Test User & Trades
    test_user_id = 999999
    user = await get_or_create_user(test_user_id, username="trader_test", first_name="Alex")
    print(f"[+] Created test user: {user.first_name} (ID: {user.telegram_id})")

    # Sample MT5 Trades
    sample_trades = [
        {"symbol": "XAUUSD", "trade_type": "BUY", "volume": 0.50, "open_price": 2045.50, "close_price": 2055.50, "profit": 500.00, "net_profit": 495.00, "pips": 100.0, "close_time": datetime.datetime.utcnow() - datetime.timedelta(days=3)},
        {"symbol": "EURUSD", "trade_type": "SELL", "volume": 1.00, "open_price": 1.0880, "close_price": 1.0830, "profit": 500.00, "net_profit": 490.00, "pips": 50.0, "close_time": datetime.datetime.utcnow() - datetime.timedelta(days=2)},
        {"symbol": "GBPJPY", "trade_type": "BUY", "volume": 0.20, "open_price": 190.50, "close_price": 189.50, "profit": -200.00, "net_profit": -205.00, "pips": -100.0, "close_time": datetime.datetime.utcnow() - datetime.timedelta(days=1)},
        {"symbol": "XAUUSD", "trade_type": "SELL", "volume": 0.30, "open_price": 2060.00, "close_price": 2040.00, "profit": 600.00, "net_profit": 595.00, "pips": 200.0, "close_time": datetime.datetime.utcnow()}
    ]

    for t in sample_trades:
        await add_trade(test_user_id, t)

    trades = await get_user_trades(test_user_id)
    print(f"[+] Retreived {len(trades)} trades from DB.")

    # 3. Analytics Calculation
    stats = calculate_stats(trades)
    print(f"[+] Analytics Results: Win Rate = {stats['win_rate']}%, Net PnL = ${stats['total_net_pnl']}, Profit Factor = {stats['profit_factor']}")

    # 4. Generate Equity Chart
    chart_file = str(DATA_DIR / "test_equity.png")
    chart_ok = generate_equity_chart(trades, chart_file)
    print(f"[+] Equity Chart generated: {chart_ok} at {chart_file}")

    # 5. Export PDF & Excel Reports
    pdf_file = str(UPLOADS_DIR / "test_report.pdf")
    excel_file = str(UPLOADS_DIR / "test_journal.xlsx")
    
    user_info = {"first_name": "Alex", "username": "trader_test"}
    pdf_ok = generate_pdf_report(user_info, trades, stats, pdf_file)
    excel_ok = generate_excel_report(user_info, trades, stats, excel_file)

    print(f"[+] PDF Report generated: {pdf_ok} at {pdf_file}")
    print(f"[+] Excel Report generated: {excel_ok} at {excel_file}")
    
    assert stats["total_trades"] == 4
    assert stats["wins"] == 3
    assert stats["losses"] == 1
    assert pdf_ok is True
    assert excel_ok is True
    print("\n[=== ALL TESTS PASSED SUCCESSFULLY! ===]")

if __name__ == "__main__":
    asyncio.run(run_tests())
