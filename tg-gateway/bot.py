"""
Telegram Dispatch Bot
----------------------
A simple interactive bot with two actions: send a message and edit a message.

Usage — quick commands:
  /send <chat_id> <text>                   send a message to any chat_id
  /edit <chat_id> <message_id> <new text>  edit an existing message

Usage — guided flow:
  /start  → choose Send or Edit → follow the prompts

Run:
  pip install -r bot_requirements.txt
  TELEGRAM_BOT_TOKEN=<token> python bot.py
"""

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ── Conversation states ───────────────────────────────────────────────────────
CHOOSING, SEND_CHAT_ID, SEND_TEXT, EDIT_CHAT_ID, EDIT_MSG_ID, EDIT_TEXT = range(6)

_MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("📤 Send Message", callback_data="action:send")],
    [InlineKeyboardButton("✏️  Edit Message", callback_data="action:edit")],
])


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What do you want to do?", reply_markup=_MAIN_MENU)
    return CHOOSING


async def menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    if action == "send":
        await query.edit_message_text("Enter the <b>chat_id</b> to send to:", parse_mode=ParseMode.HTML)
        return SEND_CHAT_ID

    if action == "edit":
        await query.edit_message_text("Enter the <b>chat_id</b> of the message to edit:", parse_mode=ParseMode.HTML)
        return EDIT_CHAT_ID

    return ConversationHandler.END


# ── Send flow ─────────────────────────────────────────────────────────────────

async def send_get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["chat_id"] = update.message.text.strip()
    await update.message.reply_text("Now enter the <b>message text</b>:", parse_mode=ParseMode.HTML)
    return SEND_TEXT


async def send_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = context.user_data.pop("chat_id", None)
    text = update.message.text
    try:
        msg = await context.bot.send_message(chat_id=int(chat_id), text=text)
        await update.message.reply_text(
            f"✅ Sent to <code>{chat_id}</code>\nmessage_id = <code>{msg.message_id}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_MAIN_MENU,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}", reply_markup=_MAIN_MENU)
    return CHOOSING


# ── Edit flow ─────────────────────────────────────────────────────────────────

async def edit_get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["chat_id"] = update.message.text.strip()
    await update.message.reply_text("Enter the <b>message_id</b> to edit:", parse_mode=ParseMode.HTML)
    return EDIT_MSG_ID


async def edit_get_msg_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["message_id"] = update.message.text.strip()
    await update.message.reply_text("Enter the <b>new message text</b>:", parse_mode=ParseMode.HTML)
    return EDIT_TEXT


async def edit_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = context.user_data.pop("chat_id", None)
    message_id = context.user_data.pop("message_id", None)
    text = update.message.text
    try:
        await context.bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
        )
        await update.message.reply_text(
            f"✅ Edited message <code>{message_id}</code> in chat <code>{chat_id}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=_MAIN_MENU,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}", reply_markup=_MAIN_MENU)
    return CHOOSING


# ── Quick commands (no conversation needed) ───────────────────────────────────

async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /send <chat_id> <message text>"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /send <chat_id> <message text>")
        return
    chat_id, *words = args
    text = " ".join(words)
    try:
        msg = await context.bot.send_message(chat_id=int(chat_id), text=text)
        await update.message.reply_text(
            f"✅ Sent to <code>{chat_id}</code>\nmessage_id = <code>{msg.message_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /edit <chat_id> <message_id> <new text>"""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /edit <chat_id> <message_id> <new text>")
        return
    chat_id, message_id, *words = args
    text = " ".join(words)
    try:
        await context.bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
        )
        await update.message.reply_text(
            f"✅ Edited message <code>{message_id}</code> in chat <code>{chat_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=_MAIN_MENU)
    return CHOOSING


# ── App setup ─────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # Quick one-shot commands
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("edit", cmd_edit))

    # Guided menu-driven conversation
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING:     [CallbackQueryHandler(menu_choice, pattern="^action:")],
            SEND_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_get_chat_id)],
            SEND_TEXT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, send_get_text)],
            EDIT_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_chat_id)],
            EDIT_MSG_ID:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_msg_id)],
            EDIT_TEXT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(conv)

    logger.info("Bot polling started…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
