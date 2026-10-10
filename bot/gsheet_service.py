import os
import re
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from bot.config import GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_SERVICE_ACCOUNT_JSON, DEFAULT_GOOGLE_SHEET_ID

logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

_client: Optional[gspread.Client] = None

def get_gspread_client() -> Optional[gspread.Client]:
    """Initialize and return gspread client singleton."""
    global _client
    if _client is not None:
        return _client

    try:
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
            _client = gspread.authorize(creds)
            logger.info("Authenticated Google Sheets API via JSON env string.")
            return _client
        elif os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
            creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SERVICE_ACCOUNT_FILE, SCOPES)
            _client = gspread.authorize(creds)
            logger.info(f"Authenticated Google Sheets API via file: {GOOGLE_SERVICE_ACCOUNT_FILE}")
            return _client
        else:
            logger.warning("Google service account credentials file not found.")
            return None
    except Exception as e:
        logger.error(f"Failed to authenticate Google Sheets API: {e}")
        return None

def extract_sheet_id(url_or_id: str) -> str:
    """Extract 44-character Google Sheet ID from full URL or return ID as-is."""
    if not url_or_id:
        return ""
    url_or_id = url_or_id.strip()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id

def setup_sheet_format(worksheet: gspread.Worksheet):
    """Format sheet header row with dark theme styling and column names."""
    headers = [
        "Date & Time", "Ticket", "Symbol", "Type", "Lots",
        "Open Price", "Close Price", "SL", "TP", "Pips",
        "Profit ($)", "Swap ($)", "Commission ($)", "Net PnL ($)", "Status", "Notes"
    ]
    
    # Check current first row
    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        worksheet.append_row(headers)
        
        # Apply header formatting
        try:
            worksheet.format("A1:P1", {
                "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.23}, # Dark Navy
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "fontSize": 10
                },
                "horizontalAlignment": "CENTER"
            })
            worksheet.freeze(rows=1)
        except Exception as fmt_err:
            logger.warning(f"Could not format header style: {fmt_err}")

async def test_sheet_connection(sheet_id_or_url: str) -> Dict[str, Any]:
    """Test connection to a Google Sheet and return title and worksheet name."""
    client = get_gspread_client()
    if not client:
        return {"success": False, "error": "Service account credentials not configured on bot server."}

    sheet_id = extract_sheet_id(sheet_id_or_url)
    if not sheet_id:
        return {"success": False, "error": "Invalid Google Sheet ID or URL format."}

    try:
        # Run gspread call in thread pool to avoid blocking async loop
        def _connect():
            spreadsheet = client.open_by_key(sheet_id)
            worksheet = spreadsheet.sheet1
            setup_sheet_format(worksheet)
            return {
                "success": True,
                "sheet_id": sheet_id,
                "title": spreadsheet.title,
                "worksheet": worksheet.title
            }

        return await asyncio.to_thread(_connect)
    except gspread.exceptions.APIError as api_err:
        return {"success": False, "error": f"Google Sheets Permission Error. Did you share the sheet with your service account email? ({api_err})"}
    except Exception as e:
        return {"success": False, "error": f"Failed to connect sheet: {str(e)}"}

async def append_trade_to_google_sheet(sheet_id_or_url: str, trade: Dict[str, Any]) -> bool:
    """Append a trade record to the specified user's Google Sheet."""
    client = get_gspread_client()
    if not client:
        logger.warning("Google Sheets client not available for trade sync.")
        return False

    sheet_id = extract_sheet_id(sheet_id_or_url) or DEFAULT_GOOGLE_SHEET_ID
    if not sheet_id:
        return False

    def _append():
        try:
            spreadsheet = client.open_by_key(sheet_id)
            worksheet = spreadsheet.sheet1
            setup_sheet_format(worksheet)

            net_pnl = float(trade.get("net_profit", 0.0))
            status = "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BE")

            row_data = [
                str(trade.get("close_time", "")),
                str(trade.get("ticket", "") or "-"),
                str(trade.get("symbol", "")).upper(),
                str(trade.get("trade_type", "")).upper(),
                float(trade.get("volume", 0.01)),
                float(trade.get("open_price", 0.0)),
                float(trade.get("close_price", 0.0)),
                trade.get("sl") if trade.get("sl") is not None else "-",
                trade.get("tp") if trade.get("tp") is not None else "-",
                float(trade.get("pips", 0.0)),
                float(trade.get("profit", 0.0)),
                float(trade.get("swap", 0.0)),
                float(trade.get("commission", 0.0)),
                net_pnl,
                status,
                str(trade.get("notes", "") or "")
            ]

            worksheet.append_row(row_data, value_input_option="USER_ENTERED")
            logger.info(f"Appended trade {trade.get('symbol')} to Google Sheet {sheet_id}")
            return True
        except Exception as err:
            logger.error(f"Error appending trade to Google Sheet: {err}")
            return False

    return await asyncio.to_thread(_append)
