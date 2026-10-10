import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.db import get_or_create_user, update_user_sheet
from bot.gsheet_service import test_sheet_connection, extract_sheet_id, get_gspread_client

logger = logging.getLogger(__name__)

async def connect_sheet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /connect_sheet <sheet_url_or_id>."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    if not context.args:
        msg = (
            "⚠️ <b>Please provide your Google Sheet URL or Sheet ID.</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/connect_sheet https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit</code>\n\n"
            "<i>Make sure to grant Edit access to the bot service account!</i>"
        )
        await update.message.reply_html(msg)
        return

    sheet_input = context.args[0].strip()
    sheet_id = extract_sheet_id(sheet_input)

    status_msg = await update.message.reply_html("⏳ <i>Testing connection to Google Sheet...</i>")

    res = await test_sheet_connection(sheet_id)
    if not res["success"]:
        error_msg = res.get("error", "Unknown error")
        
        # Check service account email
        client = get_gspread_client()
        sa_email = "Not Configured"
        if client and hasattr(client.auth, "service_account_email"):
            sa_email = client.auth.service_account_email

        fail_text = (
            f"❌ <b>Connection Failed!</b>\n\n"
            f"<b>Error:</b> {error_msg}\n\n"
            f"📌 <b>Troubleshooting Steps:</b>\n"
            f"1. Open your Google Sheet in browser.\n"
            f"2. Click <b>Share</b> button.\n"
            f"3. Add service account email as <b>Editor</b>:\n"
            f"<code>{sa_email}</code>\n"
            f"4. Try <code>/connect_sheet {sheet_id}</code> again."
        )
        await status_msg.edit_text(fail_text, parse_mode="HTML")
        return

    # Success! Save in DB
    sheet_title = res.get("title", "My Trading Journal")
    await update_user_sheet(user.id, sheet_id, sheet_title)

    success_text = (
        f"✅ <b>Google Sheet Connected Successfully!</b>\n\n"
        f"📊 <b>Sheet Title:</b> <code>{sheet_title}</code>\n"
        f"🆔 <b>Sheet ID:</b> <code>{sheet_id}</code>\n\n"
        f"All future MT5 screenshot trades will now be automatically appended to your sheet!"
    )
    await status_msg.edit_text(success_text, parse_mode="HTML")

async def sheet_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /sheet_info command."""
    user = update.effective_user
    if not user:
        return

    db_user = await get_or_create_user(user.id, user.username, user.first_name)

    if not db_user.google_sheet_id:
        text = (
            "ℹ️ <b>No Google Sheet connected yet.</b>\n\n"
            "Run <code>/connect_sheet &lt;URL&gt;</code> to link your sheet."
        )
        await update.message.reply_html(text)
        return

    sheet_url = f"https://docs.google.com/spreadsheets/d/{db_user.google_sheet_id}/edit"
    text = (
        f"📋 <b>Connected Google Sheet Status:</b>\n\n"
        f"• <b>Sheet Title:</b> {db_user.sheet_title or 'Trading Journal'}\n"
        f"• <b>Sheet ID:</b> <code>{db_user.google_sheet_id}</code>\n"
        f"• <b>Web Link:</b> <a href='{sheet_url}'>Open Google Sheet</a>\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔗 Open in Browser", url=sheet_url)],
        [InlineKeyboardButton("🔌 Disconnect Sheet", callback_query_data="cmd_disconnect_sheet")]
    ]
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
