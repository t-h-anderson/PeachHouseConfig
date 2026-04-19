import os
import subprocess
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_CHAT_IDS = {int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x.strip()}
DESKTOP_IP = os.environ.get("DESKTOP_IP", "100.74.78.70")
DESKTOP_MAC = os.environ.get("DESKTOP_MAC", "04:D9:F5:D6:25:5D")
DESKTOP_SSH_USER = os.environ.get("DESKTOP_SSH_USER", "tom")


def authorized(update: Update) -> bool:
    chat_id = update.effective_chat.id
    allowed = chat_id in ALLOWED_CHAT_IDS
    if not allowed:
        logging.warning("Rejected message from chat_id=%s (allowed: %s)", chat_id, ALLOWED_CHAT_IDS)
    return allowed


async def cmd_wake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    result = subprocess.run(["wakeonlan", DESKTOP_MAC], capture_output=True, text=True)
    if result.returncode == 0:
        await update.message.reply_text("Wake-on-LAN packet sent. Desktop should boot in ~30s.")
    else:
        await update.message.reply_text(f"Error sending WOL packet:\n{result.stderr}")


async def cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    result = subprocess.run(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-i", "/root/.ssh/id_rsa",
            f"{DESKTOP_SSH_USER}@{DESKTOP_IP}",
            "shutdown /s /t 0",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        await update.message.reply_text("Shutdown command sent. Desktop will power off shortly.")
    else:
        await update.message.reply_text(
            f"Could not reach desktop (offline or SSH not set up).\n{result.stderr.strip()}"
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    # Use tailscale ping instead of ICMP ping — Windows Firewall blocks ICMP
    # but Tailscale's own protocol gets through.
    result = subprocess.run(
        ["tailscale", "ping", "--c", "1", "--timeout", "5s", DESKTOP_IP],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        await update.message.reply_text("Desktop is online.")
    else:
        await update.message.reply_text("Desktop appears to be offline.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "/wake — boot the desktop via Wake-on-LAN\n"
        "/shutdown — shut the desktop down via SSH\n"
        "/status — check if the desktop is online"
    )


async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.info("Received update from chat_id=%s: %s", update.effective_chat.id, update)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("wake", cmd_wake))
    app.add_handler(CommandHandler("shutdown", cmd_shutdown))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.ALL, catch_all))
    app.run_polling()


if __name__ == "__main__":
    main()
