import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.db import get_or_create_user, get_user_trades
from bot.analytics import calculate_stats
from bot.export_engine import generate_pdf_report, generate_excel_report
from bot.config import UPLOADS_DIR

logger = logging.getLogger(__name__)

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /export command."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)
    trades = await get_user_trades(user.id, limit=500)

    if not trades:
        msg = "⚠️ <b>No trades found to export.</b> Log some trades first!"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_html(msg)
        return

    text = (
        "📥 <b>Export FX Trading Journal</b>\n\n"
        "Choose your preferred export format below:"
    )

    keyboard = [
        [
            InlineKeyboardButton("📄 Export PDF Report", callback_data="export_pdf"),
            InlineKeyboardButton("📊 Export Excel (.xlsx)", callback_data="export_excel")
        ],
        [
            InlineKeyboardButton("📦 Export Both (PDF + Excel)", callback_data="export_both")
        ]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def export_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback query handler for PDF / Excel export."""
    query = update.callback_query
    if not query or query.data not in ["export_pdf", "export_excel", "export_both"]:
        return
    await query.answer()

    user = query.from_user
    db_user = await get_or_create_user(user.id, user.username, user.first_name)
    trades = await get_user_trades(user.id, limit=500)
    stats = calculate_stats(trades)

    user_info = {
        "first_name": db_user.first_name or user.first_name,
        "username": db_user.username or user.username
    }

    mode = query.data

    if mode in ["export_pdf", "export_both"]:
        await query.message.reply_html("⏳ <i>Generating PDF performance report...</i>")
        pdf_path = str(UPLOADS_DIR / f"FXDiary_Report_{user.id}.pdf")
        if generate_pdf_report(user_info, trades, stats, pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                await query.message.reply_document(
                    document=pdf_file,
                    filename=f"FXDiary_Report_{user.first_name}.pdf",
                    caption="📄 <b>Your FX Trading Performance Report (PDF)</b>",
                    parse_mode="HTML"
                )
        else:
            await query.message.reply_html("❌ Failed to generate PDF report.")

    if mode in ["export_excel", "export_both"]:
        await query.message.reply_html("⏳ <i>Generating Excel spreadsheet...</i>")
        excel_path = str(UPLOADS_DIR / f"FXDiary_Journal_{user.id}.xlsx")
        if generate_excel_report(user_info, trades, stats, excel_path):
            with open(excel_path, "rb") as excel_file:
                await query.message.reply_document(
                    document=excel_file,
                    filename=f"FXDiary_Journal_{user.first_name}.xlsx",
                    caption="📊 <b>Your Complete FX Trading Journal (Excel .xlsx)</b>",
                    parse_mode="HTML"
                )
        else:
            await query.message.reply_html("❌ Failed to generate Excel report.")
