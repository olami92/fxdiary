import os
import re
import json
import logging
import datetime
from typing import List, Dict, Any, Optional
from PIL import Image

# Logging setup
logger = logging.getLogger(__name__)

# Try importing requests for Gemini API REST call
import requests

PROMPT_TEXT = """
You are an expert financial trade screenshot OCR parser. Analyze this MetaTrader 5 (MT5) history screenshot carefully.
Extract all trade records visible in the image.

Return ONLY a valid JSON array of objects with the following fields for each trade:
[
  {
    "ticket": "string or null (e.g. #12345678)",
    "symbol": "string (e.g. EURUSD, XAUUSD, GBPJPY, BTCUSD)",
    "trade_type": "string ('BUY' or 'SELL')",
    "volume": float (lot size e.g. 0.10, 1.00),
    "open_price": float,
    "close_price": float,
    "sl": float or null,
    "tp": float or null,
    "profit": float (currency profit/loss, positive or negative e.g. 150.50 or -45.20),
    "swap": float (default 0.0),
    "commission": float (default 0.0),
    "open_time": "YYYY-MM-DD HH:MM:SS or null",
    "close_time": "YYYY-MM-DD HH:MM:SS or null"
  }
]

Do not include markdown code block ticks ```json ... ``` or extra text outside the JSON array. Output JSON only.
"""

def parse_mt5_screenshot(image_path: str, gemini_api_key: str = "") -> List[Dict[str, Any]]:
    """
    Analyzes an MT5 history screenshot and extracts trade details using Gemini Vision API
    or falls back to local PyTesseract/EasyOCR regex parsing.
    """
    logger.info(f"Analyzing MT5 screenshot: {image_path}")

    # 1. Try Gemini Vision API if key is present
    if gemini_api_key and gemini_api_key != "YOUR_GEMINI_API_KEY_HERE":
        try:
            trades = _parse_with_gemini(image_path, gemini_api_key)
            if trades:
                logger.info(f"Successfully extracted {len(trades)} trades via Gemini Vision AI")
                return trades
        except Exception as e:
            logger.warning(f"Gemini API parsing failed: {e}. Falling back to local OCR engine.")

    # 2. Local Fallback Parsing using Tesseract or EasyOCR
    return _parse_with_local_ocr(image_path)

def _parse_with_gemini(image_path: str, api_key: str) -> List[Dict[str, Any]]:
    """Send image to Gemini 2.5/1.5 Flash Vision API via standard REST endpoint."""
    import base64
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    
    encoded_image = base64.b64encode(img_bytes).decode("utf-8")
    
    # Try gemini-1.5-flash or gemini-2.5-flash endpoint
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT_TEXT},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg" if image_path.endswith((".jpg", ".jpeg")) else "image/png",
                            "data": encoded_image
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.95
        }
    }

    response = requests.post(url, json=payload, timeout=25)
    response.raise_for_status()
    data = response.json()
    
    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Clean potential markdown formatting
        cleaned_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
        cleaned_text = re.sub(r"```$", "", cleaned_text, flags=re.MULTILINE).strip()
        
        parsed = json.loads(cleaned_text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return _sanitize_extracted_trades(parsed)
    except Exception as parse_err:
        logger.error(f"Failed to parse Gemini Vision response JSON: {parse_err}")
        return []

def _parse_with_local_ocr(image_path: str) -> List[Dict[str, Any]]:
    """Local fallback parser using EasyOCR / PyTesseract + Heuristic Regex rules."""
    extracted_text = ""

    try:
        import pytesseract
        img = Image.open(image_path)
        extracted_text = pytesseract.image_to_string(img)
    except Exception as e:
        logger.debug(f"PyTesseract not available: {e}")

    if not extracted_text:
        try:
            import easyocr
            reader = easyocr.Reader(['en'], gpu=False)
            results = reader.readtext(image_path, detail=0)
            extracted_text = "\n".join(results)
        except Exception as e:
            logger.debug(f"EasyOCR not available: {e}")

    if not extracted_text:
        logger.warning("No OCR text extracted from image.")
        return []

    logger.debug(f"Extracted OCR text:\n{extracted_text}")
    return _parse_raw_text_heuristics(extracted_text)

def _parse_raw_text_heuristics(text: str) -> List[Dict[str, Any]]:
    """Apply regex pattern matching to extract MT5 trades from raw OCR text."""
    trades = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # MT5 symbol list patterns
    symbols_regex = r"\b([A-Z0-9]{6,8}|XAUUSD|XAGUSD|BTCUSD|ETHUSD|US30|NAS100|GER40|JP225)\b"
    type_lot_regex = r"\b(buy|sell)\s+([0-9]+\.[0-9]{1,2})\b"
    prices_regex = r"([0-9]+\.[0-9]{2,5})\s*[-→–>]\s*([0-9]+\.[0-9]{2,5})"
    profit_regex = r"([+-]?\s*[0-9]+[\.,][0-9]{2})\s*(?:USD|EUR|GBP|\$)?$"

    current_trade: Dict[str, Any] = {}

    for i, line in enumerate(lines):
        line_clean = line.replace(",", ".")
        
        # Check symbol & buy/sell lot
        symbol_match = re.search(symbols_regex, line, re.IGNORECASE)
        type_lot_match = re.search(type_lot_regex, line, re.IGNORECASE)
        
        if symbol_match or type_lot_match:
            if current_trade.get("symbol") and current_trade.get("open_price"):
                trades.append(current_trade)
                current_trade = {}
            
            if symbol_match:
                current_trade["symbol"] = symbol_match.group(1).upper()
            if type_lot_match:
                current_trade["trade_type"] = type_lot_match.group(1).upper()
                current_trade["volume"] = float(type_lot_match.group(2))

        # Check prices (open -> close)
        price_match = re.search(prices_regex, line_clean)
        if price_match:
            current_trade["open_price"] = float(price_match.group(1))
            current_trade["close_price"] = float(price_match.group(2))

        # Check PnL / Profit amount
        pnl_match = re.search(profit_regex, line_clean)
        if pnl_match and ("open_price" in current_trade or "symbol" in current_trade):
            val_str = pnl_match.group(1).replace(" ", "")
            try:
                current_trade["profit"] = float(val_str)
            except ValueError:
                pass

        # Check ticket number #12345678
        ticket_match = re.search(r"#?(\d{7,10})", line)
        if ticket_match and "ticket" not in current_trade:
            current_trade["ticket"] = f"#{ticket_match.group(1)}"

    if current_trade.get("symbol") or current_trade.get("open_price"):
        trades.append(current_trade)

    return _sanitize_extracted_trades(trades)

def _sanitize_extracted_trades(raw_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean and normalize extracted trade fields."""
    sanitized = []
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    for t in raw_trades:
        symbol = str(t.get("symbol", "EURUSD")).upper().strip()
        trade_type = str(t.get("trade_type", "BUY")).upper().strip()
        if trade_type not in ["BUY", "SELL"]:
            trade_type = "BUY"
            
        try:
            volume = abs(float(t.get("volume", 0.01)))
        except (ValueError, TypeError):
            volume = 0.01

        try:
            open_price = abs(float(t.get("open_price", 0.0)))
        except (ValueError, TypeError):
            open_price = 0.0

        try:
            close_price = abs(float(t.get("close_price", 0.0)))
        except (ValueError, TypeError):
            close_price = open_price

        try:
            profit = float(t.get("profit", 0.0))
        except (ValueError, TypeError):
            profit = 0.0

        try:
            swap = float(t.get("swap", 0.0))
        except (ValueError, TypeError):
            swap = 0.0

        try:
            commission = float(t.get("commission", 0.0))
        except (ValueError, TypeError):
            commission = 0.0

        ticket = str(t.get("ticket", "")).strip() or None
        sl = float(t["sl"]) if t.get("sl") is not None else None
        tp = float(t["tp"]) if t.get("tp") is not None else None

        sanitized.append({
            "ticket": ticket,
            "symbol": symbol,
            "trade_type": trade_type,
            "volume": volume,
            "open_price": open_price,
            "close_price": close_price,
            "sl": sl,
            "tp": tp,
            "profit": profit,
            "swap": swap,
            "commission": commission,
            "net_profit": round(profit + swap + commission, 2),
            "open_time": t.get("open_time"),
            "close_time": t.get("close_time") or now_str
        })

    return sanitized
