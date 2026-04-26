"""Telegram bot for Mutirada Agency pipeline."""
import json
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Request

from .agent_designer import ConversationManager, SessionState


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

app = FastAPI(title="Mutirada Telegram Bot", version="1.0.0")

configure_manager = ConversationManager()


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

def send_telegram_message(text: str, chat_id: str) -> None:
    """Send a message to a Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"[telegram] TELEGRAM_BOT_TOKEN not set, skipping message to {chat_id}: {text}")
        return

    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[telegram] Failed to send message: {e}")


# ---------------------------------------------------------------------------
# Configure command handlers
# ---------------------------------------------------------------------------

def handle_configure_command_tg(repo_url: str, chat_id: str, user_id: str) -> None:
    """Handle /configure command in Telegram."""
    session = configure_manager.start(repo_url, chat_id, user_id, "telegram")

    if session.state == SessionState.ERROR:
        send_telegram_message(f"❌ {session.data.get('error')}", chat_id)
        return

    if session.stack:
        suggested = session.data.get("suggested_commands", {})
        send_telegram_message(
            f"*{session.data.get('description', session.stack)}* erkannt!\n\n"
            f"Test-Command? Vorschlag: `{suggested.get('test', 'npm test')}`\n"
            f"Antworte mit dem Command oder 'skip'.",
            chat_id
        )
    else:
        send_telegram_message("Stack wird analysiert...", chat_id)


def handle_cancel_command_tg(chat_id: str, user_id: str) -> None:
    """Handle /cancel command."""
    success = configure_manager.cancel(chat_id, user_id)
    if success:
        send_telegram_message("✅ Konfiguration abgebrochen.", chat_id)
    else:
        send_telegram_message("Keine aktive Konfiguration gefunden.", chat_id)


def send_session_response_tg(chat_id: str, session) -> None:
    """Send response based on session state."""
    if session.state == SessionState.ASKING_COMMANDS:
        q = session.data.get("current_question", "build")
        send_telegram_message(f"{q.title()}-Command?", chat_id)

    elif session.state == SessionState.ASKING_CONFIRM:
        send_telegram_message(
            f"*Preview:*\n"
            f"• 9 Agent-Profile für {session.stack}\n"
            f"• Repo: {session.repo_url}\n\n"
            f"Generieren? (ja/nein)",
            chat_id
        )

    elif session.state == SessionState.ASKING_OVERWRITE:
        send_telegram_message(
            "⚠️ `.claude/agents/` existiert bereits. Überschreiben? (ja/nein)",
            chat_id
        )

    elif session.state == SessionState.COMPLETE:
        send_telegram_message(
            f"✅ *Konfiguration abgeschlossen!*\n\n"
            f"• Repo: `{session.data.get('repo_name')}`\n"
            f"• Agents: {session.data.get('agents_count')}\n\n"
            f"Du kannst jetzt Tasks schicken!",
            chat_id
        )

    elif session.state == SessionState.ERROR:
        send_telegram_message(f"❌ Fehler: {session.data.get('error')}", chat_id)


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

def get_help_text_telegram() -> str:
    return """*Mutirada Pipeline Bot* 🤖

*Task erstellen:*
Schreib einfach was du brauchst:
`Mobile Layout im Dashboard fixen`

*Repo konfigurieren:*
`/configure <repo-url>`
`/cancel` - Konfiguration abbrechen

*Status:*
`/status` oder `wie weit?`

*Unterstützte Stacks:*
FastAPI, React, Shopify, Shopware
"""


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

def handle_telegram_message(message: dict) -> None:
    """Handle incoming Telegram message."""
    text = message.get("text", "")
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))

    if not text:
        return

    # Handle /commands
    if text.startswith("/"):
        cmd_parts = text.split(maxsplit=1)
        cmd = cmd_parts[0].lower().split("@")[0]
        arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

        if cmd == "/configure":
            if arg:
                handle_configure_command_tg(arg.strip(), chat_id, user_id)
            else:
                send_telegram_message("Usage: /configure <repo-url>", chat_id)
            return

        if cmd == "/cancel":
            handle_cancel_command_tg(chat_id, user_id)
            return

        if cmd == "/status":
            send_telegram_message("Status-Abfrage noch nicht implementiert.", chat_id)
            return

        if cmd in ("/help", "/start"):
            send_telegram_message(get_help_text_telegram(), chat_id)
            return

        return

    # Check for active configure session
    session = configure_manager.get_active_session(chat_id, user_id)
    if session and session.state in (
        SessionState.ASKING_COMMANDS,
        SessionState.ASKING_CONFIRM,
        SessionState.ASKING_OVERWRITE,
    ):
        session = configure_manager.handle_answer(chat_id, user_id, text)
        send_session_response_tg(chat_id, session)
        return

    # Regular message handling
    if "wie weit" in text.lower() or "status" in text.lower():
        send_telegram_message("Status-Abfrage noch nicht implementiert.", chat_id)
        return

    send_telegram_message(
        "Nachricht empfangen. Nutze /configure <repo-url> um eine Pipeline einzurichten.",
        chat_id
    )


# ---------------------------------------------------------------------------
# FastAPI webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram webhook updates."""
    payload = await request.json()

    message = payload.get("message") or payload.get("edited_message")
    if message:
        handle_telegram_message(message)

    return {"ok": True}


@app.get("/telegram/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "mutirada-telegram-bot"}
