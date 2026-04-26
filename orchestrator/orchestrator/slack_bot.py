"""Slack bot for Mutirada Agency pipeline."""
import os
import re
import json
import hmac
import hashlib
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException

from .agent_designer import ConversationManager, SessionState


SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")

app = FastAPI(title="Mutirada Slack Bot", version="1.0.0")

configure_manager = ConversationManager()


# ---------------------------------------------------------------------------
# Slack API helpers
# ---------------------------------------------------------------------------

def send_slack_message(channel: str, text: str) -> None:
    """Post a message to a Slack channel."""
    if not SLACK_BOT_TOKEN:
        print(f"[slack] SLACK_BOT_TOKEN not set, skipping message to {channel}: {text}")
        return

    try:
        httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"channel": channel, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[slack] Failed to send message: {e}")


def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature."""
    if not SLACK_SIGNING_SECRET:
        return True  # Skip verification in dev without secret

    if abs(time.time() - float(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{request_body.decode()}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Configure command handlers
# ---------------------------------------------------------------------------

def handle_configure_command(repo_url: str, channel: str, user_id: str) -> None:
    """Handle /configure command."""
    session = configure_manager.start(repo_url, channel, user_id, "slack")

    if session.state == SessionState.ERROR:
        send_slack_message(channel, f"❌ {session.data.get('error')}")
        return

    if session.stack:
        suggested = session.data.get("suggested_commands", {})
        send_slack_message(
            channel,
            f"*{session.data.get('description', session.stack)}* erkannt!\n\n"
            f"Test-Command? Vorschlag: `{suggested.get('test', 'npm test')}`\n"
            f"Antworte mit dem Command oder 'skip'."
        )
    else:
        send_slack_message(channel, "Stack wird analysiert...")


def handle_cancel_command(channel: str, user_id: str) -> None:
    """Handle /cancel command."""
    success = configure_manager.cancel(channel, user_id)
    if success:
        send_slack_message(channel, "✅ Konfiguration abgebrochen.")
    else:
        send_slack_message(channel, "Keine aktive Konfiguration gefunden.")


def handle_help_configure(channel: str) -> None:
    """Handle /help configure."""
    send_slack_message(channel, """*Agent Designer Hilfe*

`/configure <repo-url>` — Pipeline für neues Repo einrichten
`/cancel` — Aktive Konfiguration abbrechen

*Unterstützte Stacks:*
• FastAPI (Python)
• React + Vite
• Shopify App
• Shopware Plugin
""")


def _send_session_response(channel: str, session) -> None:
    """Send appropriate response based on session state."""
    if session.state == SessionState.ASKING_COMMANDS:
        q = session.data.get("current_question", "build")
        send_slack_message(channel, f"{q.title()}-Command?")

    elif session.state == SessionState.ASKING_CONFIRM:
        send_slack_message(
            channel,
            f"*Preview:*\n"
            f"• 9 Agent-Profile für {session.stack}\n"
            f"• Repo: {session.repo_url}\n\n"
            f"Generieren? (ja/nein)"
        )

    elif session.state == SessionState.ASKING_OVERWRITE:
        send_slack_message(
            channel,
            "⚠️ `.claude/agents/` existiert bereits. Überschreiben? (ja/nein)"
        )

    elif session.state == SessionState.COMPLETE:
        send_slack_message(
            channel,
            f"✅ *Konfiguration abgeschlossen!*\n\n"
            f"• Repo: `{session.data.get('repo_name')}`\n"
            f"• Agents: {session.data.get('agents_count')}\n"
            f"• Pfad: `{session.data.get('repo_path')}`\n\n"
            f"Du kannst jetzt Tasks schicken!"
        )

    elif session.state == SessionState.ERROR:
        send_slack_message(channel, f"❌ Fehler: {session.data.get('error')}")


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

def handle_message(event: dict) -> None:
    """Handle incoming Slack message events."""
    text = event.get("text", "")
    channel = event.get("channel", "")
    user_id = event.get("user", "")

    # Check for active configure session first
    session = configure_manager.get_active_session(channel, user_id)
    if session and session.state in (
        SessionState.ASKING_COMMANDS,
        SessionState.ASKING_CONFIRM,
        SessionState.ASKING_OVERWRITE,
    ):
        session = configure_manager.handle_answer(channel, user_id, text)
        _send_session_response(channel, session)
        return

    # Regular message handling (task submission)
    if text:
        send_slack_message(channel, "Nachricht empfangen. Nutze @mutirada configure <repo-url> um eine Pipeline einzurichten.")


# ---------------------------------------------------------------------------
# FastAPI Slack events endpoint
# ---------------------------------------------------------------------------

@app.post("/slack/events")
async def slack_events(request: Request):
    """Handle Slack events API callbacks."""
    body = await request.body()

    # Verify signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)

    # URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})
    event_type = event.get("type")

    # Handle app_mention events
    if event_type == "app_mention":
        text = event.get("text", "").lower()

        if "configure " in text:
            match = re.search(r'configure\s+(https?://\S+)', event.get("text", ""))
            if match:
                repo_url = match.group(1)
                handle_configure_command(repo_url, event["channel"], event["user"])
                return {"ok": True}

        if "cancel" in text:
            handle_cancel_command(event["channel"], event["user"])
            return {"ok": True}

        if "help configure" in text:
            handle_help_configure(event["channel"])
            return {"ok": True}

    # Handle direct messages and channel messages
    if event_type == "message" and not event.get("bot_id"):
        handle_message(event)

    return {"ok": True}


@app.get("/slack/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "mutirada-slack-bot"}
