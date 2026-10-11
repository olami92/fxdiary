# 📈 FXDiary - Multi-User MT5 Trading Journal

**FXDiary** is an automated **MetaTrader 5 (MT5) Trading Journal & Performance Analytics system**. Traders send screenshots of their MT5 trade history to a Telegram bot, which extracts trade details using Vision AI OCR and stores them in the database. Each user can sign in to a private dashboard with Telegram.

It supports **multi-user isolation** through Telegram sign-in, with each user accessing their own dashboard, trade history, and PDF/Excel exports. Trades are stored in the database.

---

## 🌟 Key Features

1. **📸 MT5 Screenshot OCR (Vision AI)**
   - Automatically parses single-trade details or multi-trade history list screenshots from MT5 mobile or desktop.
   - Extracts ticket #, symbol (e.g. `XAUUSD`, `EURUSD`, `GBPJPY`), trade type (`BUY`/`SELL`), volume (lots), open/close prices, net PnL, and date/time.
   - Auto-calculates pips based on asset class decimal conventions.

2. **🎯 Comprehensive Performance Analytics**
   - Interactive `/stats` command calculating: Net PnL ($), Win Rate (%), Profit Factor, Total Trades, Wins/Losses/BE counts, Average Win/Loss ($), Max Drawdown, Total Pips, and Best Symbol.
   - Dynamically generates and attaches a dark-mode **Cumulative Equity Curve PnL Chart (.png)** in Telegram.

3. **📥 PDF & Excel (.xlsx) Export Engine**
   - **PDF Report**: Multi-page report generated with `reportlab` featuring brand header, trader profile, 4-card metric summary, secondary stats, and trade history log table.
   - **Excel Workbook**: Styled `.xlsx` workbook using `openpyxl` with conditional formatting, summary dashboard tab, and itemized trade log tab.

4. **🌐 Telegram Login & Private Dashboard**
   - Built-in FastAPI + HTML5/CSS3 dashboard with Telegram sign-in.
   - Each signed-in user can view their own equity curve, win/loss chart, and trade history.

---

## 📂 Project Structure

```
fxdiary/
├── bot/
│   ├── __init__.py
│   ├── main.py                # Telegram Bot Entry Point & Handlers
│   ├── config.py              # Environment & Configuration Loader
│   ├── db.py                  # SQLAlchemy Database models & Async Session
│   ├── ocr_engine.py          # Vision AI (Gemini) + Local OCR MT5 parser
│   ├── analytics.py           # Statistical calculations & Matplotlib Equity Chart
│   ├── export_engine.py       # PDF & Excel Report Generator
│   └── handlers/
│       ├── start_handler.py   # /start, /help, registration
│       ├── photo_handler.py   # MT5 Screenshot processing & confirm callbacks
│       ├── stats_handler.py   # /stats, equity chart generator
│       ├── trades_handler.py  # /trades, /manual_trade
│       └── export_handler.py # /export (PDF/Excel download)
├── web/
│   ├── app.py                 # FastAPI backend server & API endpoints
│   ├── static/                # Web Dashboard assets (CSS, JS)
│   └── templates/             # HTML templates (Glassmorphism design)
├── data/                      # Local SQLite DB & uploaded screenshots
├── .env.example               # Environment template
├── requirements.txt           # Python dependencies list
├── test_app.py                # Core verification test suite
└── README.md                  # Comprehensive documentation
```

---

## 🚀 Quick Setup & Installation

### 1. Prerequisites
- **Python 3.10+** installed on your system.
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather).
- (Recommended) Free Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/) for Vision AI screenshot parsing.

### 2. Environment Setup

```bash
# 1. Clone repository or navigate to folder
cd c:/Users/USER/Documents/fxdiary

# 2. Create Python virtual environment
python -m venv venv

# 3. Activate virtual environment
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

### 3. Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your keys:

```ini
# Telegram Bot Token from @BotFather
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyZ
TELEGRAM_BOT_USERNAME=your_bot_username_without_at
SESSION_SECRET=use_a_long_random_secret

# Vision AI API Key for MT5 Screenshot Analysis
GEMINI_API_KEY=AIzaSyYourGeminiApiKeyHere

# Database Path (Defaults to SQLite)
DATABASE_URL=sqlite+aiosqlite:///data/fxdiary.db

# Web App Settings
HOST=0.0.0.0
PORT=8000
WEB_APP_URL=http://localhost:8000
```

For Telegram dashboard sign-in, set `TELEGRAM_BOT_USERNAME` to the bot username without `@` and set a long, random `SESSION_SECRET`. In @BotFather, link the dashboard's domain to the same bot with `/setdomain`. Set the same variables in Render's environment settings.

### Supabase database on Render

The app uses SQLite locally by default. To keep production data across Render deploys without a paid Render disk, create a Supabase project and copy its PostgreSQL connection string. In Supabase, choose **Connect** and use the **Session pooler** connection string when available. In Render, open the `fxdiary` service's **Environment** settings and set `DATABASE_URL` to that connection string. Keep it private; do not commit it to GitHub. The app converts standard `postgres://` and `postgresql://` URLs to SQLAlchemy's async PostgreSQL driver automatically. On startup, it creates the app tables if they do not already exist.

Supabase's free project has database size and inactivity limits; check its current plan details. Existing SQLite records are not copied automatically, so export/import them before switching if you need to preserve data already stored in a database.

---

## 💻 Running the Application

### Running the Telegram Bot:
```bash
.\venv\Scripts\python.exe -m bot.main
```

### Running the Web Dashboard / API Server:
```bash
.\venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:8000` in your browser to view the interactive dashboard!

### Running the Verification Test Suite:
```bash
.\venv\Scripts\python.exe test_app.py
```

---

## 📱 Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message, user registration & feature menu |
| `/help` | Detailed user guide & setup instructions |
| `/stats` | View performance analytics & equity curve chart PNG |
| `/trades` | View recent trade log history with delete options |
| `/manual_trade` | Log a trade manually without a screenshot |
| `/export` | Download performance report as PDF or Excel (.xlsx) |

---

## ⚖️ License
Distributed under the MIT License. Built for traders worldwide.
