"""Transcribe Telegram voice notes and extract a trade without inventing values."""

import base64
import json
import logging
import re
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

VOICE_TRADE_PROMPT = """
Listen to this voice note and extract the single trade the user dictated.
Return only a JSON object with these fields:
{
  "symbol": "normalized trading symbol, e.g. EURUSD",
  "trade_type": "BUY or SELL",
  "volume": number or null,
  "open_price": number or null,
  "close_price": number or null,
  "sl": number or null,
  "tp": number or null,
  "profit": number or null,
  "ticket": "string or null",
  "close_time": "YYYY-MM-DD HH:MM:SS or null"
}
Do not guess or infer values that were not spoken. Map 'sold' to SELL and 'bought' to BUY.
If a field is not spoken, use null. Treat a price described as entry, opened, or sold/bought at
as open_price. Treat 'stop' or 'stop loss' as sl, and 'take profit' or 'TP' as tp.
Only use close_price and profit when the speaker explicitly gives an exit/closing price and
realized profit or loss. Do not return markdown or transcript commentary.
"""


def parse_voice_trade(audio_path: str, mime_type: str, api_key: str) -> Dict[str, Any]:
    """Ask Gemini to understand a short voice note and return a normalized trade."""
    if not api_key:
        raise RuntimeError("Voice trade parsing requires GEMINI_API_KEY.")

    with open(audio_path, "rb") as audio_file:
        audio_data = base64.b64encode(audio_file.read()).decode("ascii")

    payload = {
        "contents": [{
            "parts": [
                {"text": VOICE_TRADE_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": audio_data}},
            ]
        }],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    last_error: Optional[str] = None
    for model in ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.8-flash", "gemini-2.5-flash"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json=payload, timeout=45)
            if response.status_code != 200:
                last_error = f"{model} returned HTTP {response.status_code}: {response.text[:160]}"
                continue
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
            parsed = json.loads(text)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else None
            if not isinstance(parsed, dict):
                raise ValueError("No trade was found in the voice note.")
            return _normalize_trade(parsed)
        except ValueError:
            raise
        except Exception as error:
            last_error = str(error)
            logger.warning("Gemini voice parsing with %s failed: %s", model, error)

    raise RuntimeError(last_error or "Voice note could not be analyzed.")


def _normalize_trade(raw: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(raw.get("symbol") or "").upper().replace("/", "").replace(" ", "")
    trade_type = str(raw.get("trade_type") or "").upper().strip()
    if not re.fullmatch(r"[A-Z0-9._-]{3,20}", symbol):
        raise ValueError("I couldn't identify the symbol. Please say a symbol such as EUR/USD.")
    if trade_type not in ("BUY", "SELL"):
        raise ValueError("I couldn't tell whether this was a BUY or SELL trade.")

    def number(key: str) -> Optional[float]:
        value = raw.get(key)
        if value is None or value == "":
            return None
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None

    volume, open_price = number("volume"), number("open_price")
    if volume is None or volume <= 0:
        raise ValueError("I couldn't identify the lot size. Please dictate it, for example 0.5 lots.")
    if open_price is None or open_price <= 0:
        raise ValueError("I couldn't identify the entry price. Please dictate the price again.")

    close_price, profit = number("close_price"), number("profit")
    status = "CLOSED" if close_price is not None and profit is not None else "OPEN"
    return {
        "symbol": symbol,
        "trade_type": trade_type,
        "volume": volume,
        "open_price": open_price,
        "close_price": close_price if close_price is not None else 0.0,
        "sl": number("sl"),
        "tp": number("tp"),
        "profit": profit if profit is not None else 0.0,
        "net_profit": profit if profit is not None else 0.0,
        "pips": 0.0,
        "ticket": str(raw["ticket"]) if raw.get("ticket") is not None else None,
        "close_time": raw.get("close_time"),
        "status": status,
    }
