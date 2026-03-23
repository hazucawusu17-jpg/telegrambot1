import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv
from db import Database
from mail_client import fetch_latest_email_for_address

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
db = Database()

import re

def extract_code(body: str) -> str | None:
    """Extract a 6-digit code from the email body."""
    match = re.search(r'\b(\d{4})\b', body)
    return match.group(1) if match else None

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return db.is_admin(user_id)


def is_blocked(user_id: int) -> bool:
    return db.is_user_blocked(user_id)


async def guard(update: Update) -> bool:
    """Return True (and reply) if the user is blocked."""
    uid = update.effective_user.id
    if is_blocked(uid):
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return True
    return False


# ─────────────────────────────────────────────
# User commands
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")
    if is_admin(uid):
        await update.message.reply_text(
            "👋 Welcome, Admin!\n\n"
            "Use /help to see user commands.\n"
            "Use /adminhelp to see all admin commands."
        )
    else:
        await update.message.reply_text(
            "👋 Welcome! Glad to have you here.\n\n"
            "Use /help to see all available commands and how to use them."
        )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return

    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")

    if not context.args:
        await update.message.reply_text("Usage: /code <email address>")
        return

    target_email = context.args[0].strip().lower()

    # Check if this email is registered in the bot
    if not db.is_email_registered(target_email):
        await update.message.reply_text(
            f"❌ No account registered for *{target_email}*.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🔍 Searching latest code for *{target_email}*…", parse_mode="Markdown")

    try:
        result = fetch_latest_email_for_address(target_email)
        if result is None:
            await update.message.reply_text(f"📭 No emails found addressed to *{target_email}*.", parse_mode="Markdown")
            return

        code_found = extract_code(result["body"])

        if code_found:
            msg = f"✅ *Code:* `{code_found}`"
        else:
           msg = "⚠️ No code found. Please try resending the code."

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error fetching email: %s", e)
        await update.message.reply_text("⚠️ An error occurred while fetching the email. Please try again later.")



# ─────────────────────────────────────────────
# Admin commands
# ─────────────────────────────────────────────

async def admin_only(update: Update) -> bool:
    """Return True (and reply) if the user is NOT an admin."""
    if await guard(update):
        return True
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ This command is for admins only.")
        return True
    return False


async def addmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /addmail <email>  — register an email address."""
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addmail <email>")
        return
    email_addr = context.args[0].strip().lower()
    if db.is_email_registered(email_addr):
        await update.message.reply_text(f"ℹ️ {email_addr} is already registered.")
        return
    db.add_email(email_addr, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ *{email_addr}* has been registered.", parse_mode="Markdown")


async def removemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /removemail <email>  — unregister an email address."""
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /removemail <email>")
        return
    email_addr = context.args[0].strip().lower()
    if not db.is_email_registered(email_addr):
        await update.message.reply_text(f"❌ {email_addr} is not registered.")
        return
    db.remove_email(email_addr)
    await update.message.reply_text(f"🗑️ *{email_addr}* has been removed.", parse_mode="Markdown")


async def listmails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /listmails  — show all registered email addresses."""
    if await admin_only(update):
        return
    emails = db.list_emails()
    if not emails:
        await update.message.reply_text("📭 No email addresses registered yet.")
        return
    lines = [f"• `{e['email']}`" for e in emails]
    await update.message.reply_text("📋 *Registered emails:*\n" + "\n".join(lines), parse_mode="Markdown")


async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /listusers  — show all users."""
    if await admin_only(update):
        return
    users = db.list_users()
    if not users:
        await update.message.reply_text("No users yet.")
        return
    lines = []
    for u in users:
        status = "🚫 blocked" if u.get("blocked") else "✅ active"
        lines.append(f"• `{u['telegram_id']}` @{u.get('username','?')} — {status}")
    await update.message.reply_text("👥 *All users:*\n" + "\n".join(lines), parse_mode="Markdown")


async def blockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /blockuser <telegram_id>"""
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /blockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID.")
        return
    db.set_user_blocked(target_id, blocked=True)
    await update.message.reply_text(f"🚫 User `{target_id}` has been blocked.", parse_mode="Markdown")


async def unblockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /unblockuser <telegram_id>"""
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unblockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID.")
        return
    db.set_user_blocked(target_id, blocked=False)
    await update.message.reply_text(f"✅ User `{target_id}` has been unblocked.", parse_mode="Markdown")


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /adminhelp  — list all admin commands."""
    if await admin_only(update):
        return
    text = (
        "🛠️ *Admin Commands*\n\n"
        "/addmail `<email>` — Register a new email address\n"
        "/removemail `<email>` — Remove a registered email\n"
        "/listmails — List all registered emails\n"
        "/listusers — List all bot users\n"
        "/blockuser `<id>` — Block a user by Telegram ID\n"
        "/unblockuser `<id>` — Unblock a user\n"
        "/adminhelp — Show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# Unknown command fallback
# ─────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    text = (
        "📖 *Available Commands*\n\n"
        "/start — Register and start using the bot\n"
        "/code `<email>` — Fetch the latest 6-digit code sent to that email address\n\n"
        "_Example:_ `/code you@domain.com`\n\n"
        "If the email address hasn't been registered by an admin, you'll get an error. "
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /help to get more info.")


# ─────────────────────────────────────────────
# App bootstrap
# ─────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("code", code))

    # Admin
    app.add_handler(CommandHandler("addmail", addmail))
    app.add_handler(CommandHandler("removemail", removemail))
    app.add_handler(CommandHandler("listmails", listmails))
    app.add_handler(CommandHandler("listusers", listusers))
    app.add_handler(CommandHandler("blockuser", blockuser))
    app.add_handler(CommandHandler("unblockuser", unblockuser))
    app.add_handler(CommandHandler("adminhelp", adminhelp))

    # Fallback
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
