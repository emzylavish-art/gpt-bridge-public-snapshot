from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable
from urllib import request as urlrequest
from urllib.error import URLError

log = logging.getLogger("gpt_bridge.telegram")


class TelegramError(Exception):
    pass


def _default_call(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TelegramError(str(exc)) from exc
    if not body.get("ok"):
        raise TelegramError(body.get("description") or "telegram rejected the call")
    return body


class TelegramRelay:
    """A second door to the same bridge. The token stays in data/telegram.json, not in source."""

    def __init__(self, path: Path, call: Callable[..., dict] | None = None):
        self.path = path
        self.call = call or _default_call
        self._state = self._load()

    def status(self) -> dict:
        chat_id = self._state.get("chat_id")
        return {
            "configured": bool(self._state.get("bot_token")),
            "username": self._state.get("username"),
            "chat_id": chat_id,
            "connected": bool(chat_id),
            "start_url": self._start_url(),
            "dashboard_url": self._state.get("dashboard_url") or "",
        }

    def configure(self, token: str, dashboard_url: str = "") -> dict:
        token = token.strip()
        if not token or ":" not in token:
            raise TelegramError("bot token is missing")
        me = self.call(token, "getMe")
        username = me["result"]["username"]
        self._state = {
            "bot_token": token,
            "username": username,
            "chat_id": self._state.get("chat_id"),
            "dashboard_url": dashboard_url.strip(),
            "offset": self._state.get("offset") or 0,
        }
        self._save()
        log.info("telegram bot verified as @%s", username)
        return self.status()

    def poll_once(self) -> dict:
        token = self._state.get("bot_token")
        if not token:
            return {"polled": False, "chat_id": None}
        offset = int(self._state.get("offset") or 0)
        body = self.call(token, "getUpdates", {"offset": offset, "timeout": 0})
        captured = None
        for update in body.get("result") or []:
            offset = max(offset, int(update["update_id"]) + 1)
            captured = self._handle(update) or captured
        self._state["offset"] = offset
        self._save()
        return {"polled": True, "chat_id": self._state.get("chat_id"), "captured": captured}

    def notify(self, kind: str, text: str) -> bool:
        chat_id = self._state.get("chat_id")
        token = self._state.get("bot_token")
        if not chat_id or not token:
            return False
        dashboard = self._state.get("dashboard_url") or ""
        buttons = [
            [{"text": "Restart browser", "callback_data": "restart"}],
            [{"text": "Force break", "callback_data": "force_break"}],
        ]
        if dashboard:
            buttons.append([{"text": "Open dashboard", "url": dashboard}])
        self.call(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": f"{kind}: {text}",
                "reply_markup": {"inline_keyboard": buttons},
            },
        )
        log.info("telegram notice sent kind=%s", kind)
        return True

    def _handle(self, update: dict) -> str | None:
        message = update.get("message") or {}
        text = message.get("text") or ""
        chat = message.get("chat") or {}
        if text.startswith("/start") and chat.get("id"):
            self._state["chat_id"] = chat["id"]
            log.info("telegram chat captured")
            self._reply(chat["id"], "gpt-bridge is linked. Buttons on later messages act on this browser.")
            return "start"
        callback = update.get("callback_query") or {}
        data = callback.get("data")
        if data in {"restart", "force_break"}:
            return data
        return None

    def _reply(self, chat_id, text: str) -> None:
        token = self._state.get("bot_token")
        if token:
            self.call(token, "sendMessage", {"chat_id": chat_id, "text": text})

    def _start_url(self) -> str | None:
        username = self._state.get("username")
        if not username:
            return None
        return f"https://t.me/{username}?start=gptbridge"

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        public = dict(self._state)
        self.path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
