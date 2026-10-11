import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Google Credentials
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "credentials" / "google_credentials.json")
)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
DEFAULT_GOOGLE_SHEET_ID = os.getenv("DEFAULT_GOOGLE_SHEET_ID", "").strip()

# AI Vision API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Database configuration. SQLite is used locally unless DATABASE_URL points to
# an external PostgreSQL database (for example, Supabase).
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
CREDENTIALS_DIR = BASE_DIR / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "fxdiary.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}")

# Supabase gives a standard PostgreSQL URL. Use SQLAlchemy's asyncpg driver and
# accept the common postgres:// / postgresql:// URL forms from hosted providers.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgresql://"):]

# asyncpg expects `ssl`, while some dashboard-provided URLs use libpq's
# `sslmode` parameter.
if DATABASE_URL.startswith("postgresql+asyncpg://") and "sslmode=" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("sslmode=", "ssl=", 1)

# Web App Settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WEB_APP_URL = os.getenv("WEB_APP_URL", f"http://localhost:{PORT}")
