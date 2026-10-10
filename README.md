# 📈 FXDiary - Multi-User MT5 Trading Journal Telegram Bot & Google Sheets Sync

**FXDiary** is an automated **MetaTrader 5 (MT5) Trading Journal & Performance Analytics system**. It allows traders to send screenshots of their MT5 trade history directly to a Telegram Bot, which automatically extracts trade details (Symbol, Type, Volume, Open/Close Prices, PnL, Pips) using **Vision AI OCR** and records them seamlessly into their **Google Sheets** and a local database.

It supports **multi-user isolation** (each user can connect their own Google Sheet or export custom PDF/Excel reports) and comes with a **Telegram Mini App / Web Dashboard**.

---

## 🌟 Key Features

1. **📸 MT5 Screenshot OCR (Vision AI)**
   - Automatically parses single-trade details or multi-trade history list screenshots from MT5 mobile or desktop.
   - Extracts ticket #, symbol (e.g. `XAUUSD`, `EURUSD`, `GBPJPY`), trade type (`BUY`/`SELL`), volume (lots), open/close prices, net PnL, and date/time.
   - Auto-calculates pips based on asset class decimal conventions.

2. **📊 Automated Google Sheets Integration**
   - Connect any Google Sheet per user using `/connect_sheet <sheet_url>`.
   - Automatically formats header rows with dark theme styling, bold text, and conditional color highlights (Soft Green for Wins, Soft Red for Losses).

3. **🎯 Comprehensive Performance Analytics**
   - Interactive `/stats` command calculating: Net PnL ($), Win Rate (%), Profit Factor, Total Trades, Wins/Losses/BE counts, Average Win/Loss ($), Max Drawdown, Total Pips, and Best Symbol.
   - Dynamically generates and attaches a dark-mode **Cumulative Equity Curve PnL Chart (.png)** in Telegram.

4. **📥 PDF & Excel (.xlsx) Export Engine**
   - **PDF Report**: Multi-page report generated with `reportlab` featuring brand header, trader profile, 4-card metric summary, secondary stats, and trade history log table.
   - **Excel Workbook**: Styled `.xlsx` workbook using `openpyxl` with conditional formatting, summary dashboard tab, and itemized trade log tab.

5. **🌐 Telegram Mini App & Web Dashboard**
   - Built-in FastAPI + HTML5/CSS3 glassmorphism dashboard.
   - View real-time equity curves, win/loss donut charts, drag-and-drop MT5 screenshots, and manage trade records directly in-browser or inside Telegram as a Mini App.

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
│   ├── gsheet_service.py      # Google Sheets API client & sync manager
│   ├── analytics.py           # Statistical calculations & Matplotlib Equity Chart
│   ├── export_engine.py       # PDF & Excel Report Generator
│   └── handlers/
│       ├── start_handler.py   # /start, /help, registration
│       ├── sheet_handler.py   # /connect_sheet, /sheet_info
│       ├── photo_handler.py   # MT5 Screenshot processing & confirm callbacks
│       ├── stats_handler.py   # /stats, equity chart generator
│       ├── trades_handler.py  # /trades, /manual_trade
│       └── export_handler.py # /export (PDF/Excel download)
├── web/
│   ├── app.py                 # FastAPI backend server & API endpoints
│   ├── static/                # Web Dashboard assets (CSS, JS)
│   └── templates/             # HTML templates (Glassmorphism design)
├── credentials/               # Google Sheets service account credentials
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
- Google Cloud Service Account JSON file for Google Sheets API.

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

# Google Sheets Service Account Credentials path
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/google_credentials.json

# Vision AI API Key for MT5 Screenshot Analysis
GEMINI_API_KEY=AIzaSyYourGeminiApiKeyHere

# Database Path (Defaults to SQLite)
DATABASE_URL=sqlite+aiosqlite:///data/fxdiary.db

# Web App Settings
HOST=0.0.0.0
PORT=8000
WEB_APP_URL=http://localhost:8000
```

---

## 🤖 Google Sheets API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new Project and enable **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account**, generate a **JSON Key**, and save it as `credentials/google_credentials.json`.
4. Copy the service account email (e.g. `fxdiary-service@your-project.iam.gserviceaccount.com`).
5. When users create a Google Sheet, they simply share edit permissions to that email address and run:
   ```
   /connect_sheet https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
   ```

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
| `/connect_sheet <URL>` | Connect your Google Sheet to automatically sync trades |
| `/sheet_info` | Check connected Google Sheet status & web link |
| `/stats` | View performance analytics & equity curve chart PNG |
| `/trades` | View recent trade log history with delete options |
| `/manual_trade` | Log a trade manually without a screenshot |
| `/export` | Download performance report as PDF or Excel (.xlsx) |

---

## ⚖️ License
Distributed under the MIT License. Built for traders worldwide.
