import os
import re
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


def extract_code(body: str):
    """Extract a 4-digit code from the email body."""
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
        await update.message.reply_text("🚫 Estás bloqueado y no puedes usar este bot.")
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
            "👋 ¡Bienvenido, Admin!\n\n"
            "Usa /help para ver los comandos de usuario.\n"
            "Usa /adminhelp para ver todos los comandos de administrador."
        )
    else:
        await update.message.reply_text(
            "👋 ¡Bienvenido! Nos alegra tenerte aquí.\n\n"
            "Usa /help para ver todos los comandos disponibles y cómo usarlos."
        )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return

    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")

    if not context.args:
        await update.message.reply_text("Uso: /code <dirección de correo>")
        return

    target_email = context.args[0].strip().lower()

    if not db.is_email_registered(target_email):
        await update.message.reply_text(
            f"❌ No hay ninguna cuenta registrada para *{target_email}*.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🔍 Buscando el último código para *{target_email}*…", parse_mode="Markdown")

    try:
        result = fetch_latest_email_for_address(target_email)
        if result is None:
            await update.message.reply_text("⚠️ No se encontró ningún código. Por favor, intenta reenviar el código.", parse_mode="Markdown")
            return

        code_found = extract_code(result["body"])

        if code_found:
            msg = f"✅ *Código:* `{code_found}`"
        else:
            msg = "⚠️ No se encontró ningún código. Por favor, intenta reenviar el código."

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error fetching email: %s", e)
        await update.message.reply_text("⚠️ Ocurrió un error al obtener el correo. Por favor, inténtalo más tarde.")


# ─────────────────────────────────────────────
# Admin commands
# ─────────────────────────────────────────────

async def admin_only(update: Update) -> bool:
    """Return True (and reply) if the user is NOT an admin."""
    if await guard(update):
        return True
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Este comando es solo para administradores.")
        return True
    return False


async def addmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /addmail <correo>")
        return
    email_addr = context.args[0].strip().lower()
    if db.is_email_registered(email_addr):
        await update.message.reply_text(f"ℹ️ {email_addr} ya está registrado.")
        return
    db.add_email(email_addr, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ *{email_addr}* ha sido registrado.", parse_mode="Markdown")


async def removemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /removemail <correo>")
        return
    email_addr = context.args[0].strip().lower()
    if not db.is_email_registered(email_addr):
        await update.message.reply_text(f"❌ {email_addr} no está registrado.")
        return
    db.remove_email(email_addr)
    await update.message.reply_text(f"🗑️ *{email_addr}* ha sido eliminado.", parse_mode="Markdown")


async def listmails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    emails = db.list_emails()
    if not emails:
        await update.message.reply_text("📭 Aún no hay direcciones de correo registradas.")
        return
    lines = [f"• `{e['email']}`" for e in emails]
    await update.message.reply_text("📋 *Correos registrados:*\n" + "\n".join(lines), parse_mode="Markdown")


async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    users = db.list_users()
    if not users:
        await update.message.reply_text("Aún no hay usuarios.")
        return
    lines = []
    for u in users:
        status = "🚫 bloqueado" if u.get("blocked") else "✅ activo"
        lines.append(f"• `{u['telegram_id']}` @{u.get('username','?')} — {status}")
    await update.message.reply_text("👥 *Todos los usuarios:*\n" + "\n".join(lines), parse_mode="Markdown")


async def blockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /blockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID de Telegram no válido.")
        return
    db.set_user_blocked(target_id, blocked=True)
    await update.message.reply_text(f"🚫 El usuario `{target_id}` ha sido bloqueado.", parse_mode="Markdown")


async def unblockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /unblockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID de Telegram no válido.")
        return
    db.set_user_blocked(target_id, blocked=False)
    await update.message.reply_text(f"✅ El usuario `{target_id}` ha sido desbloqueado.", parse_mode="Markdown")


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    text = (
        "🛠️ *Comandos de Administrador*\n\n"
        "/addmail `<correo>` — Registrar una nueva dirección de correo\n"
        "/removemail `<correo>` — Eliminar un correo registrado\n"
        "/listmails — Ver todos los correos registrados\n"
        "/listusers — Ver todos los usuarios del bot\n"
        "/blockuser `<id>` — Bloquear un usuario por su ID de Telegram\n"
        "/unblockuser `<id>` — Desbloquear un usuario\n"
        "/adminhelp — Mostrar este mensaje"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# Help & fallback
# ─────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    text = (
        "📖 *Comandos Disponibles*\n\n"
        "/start — Regístrate y empieza a usar el bot\n"
        "/code `<correo>` — Obtén el último código de 4 dígitos enviado a ese correo\n\n"
        "_Ejemplo:_ `/code tu@dominio.com`\n\n"
        "Si el correo no ha sido registrado por un administrador, recibirás un error."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Comando desconocido. Usa /help para obtener más información.")


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
