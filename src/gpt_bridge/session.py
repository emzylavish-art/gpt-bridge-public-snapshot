from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from gpt_bridge.config import Settings
from gpt_bridge.protocol import REPAIR_PROMPT, TurnPlan, parse_reply, plan_turn

log = logging.getLogger("gpt_bridge.session")


class ChatFailure(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LoginRequired(Exception):
    def __init__(self, reason: str = "login required"):
        super().__init__(reason)
        self.reason = reason


class AccountBusy(Exception):
    def __init__(self, reason: str = "completion in flight"):
        super().__init__(reason)
        self.reason = reason


class BrowserLayer(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def status(self) -> dict: ...

    async def logged_in(self) -> bool: ...

    async def wait_for_login(self) -> None: ...

    async def healthy(self) -> bool: ...

    async def has_history(self) -> bool: ...

    async def send(self, prompt: str) -> str: ...

    async def rotate(self) -> str: ...

    async def mark_broken(self) -> None: ...


@dataclass
class TurnResult:
    text: str
    rotations: int
    used_delta: bool


class CompletionSession:
    """One browser, one active chat. Failed sends rotate and resend the full prompt."""

    def __init__(self, browser: BrowserLayer, settings: Settings, journal=None, on_event=None):
        self.browser = browser
        self.settings = settings
        self.journal = journal
        self.on_event = on_event
        self.lock = asyncio.Lock()
        self._sending = False
        self._state = self._load_state()
        self._hold_chat = False
        self._login_notice_sent = False

    def _load_state(self) -> dict:
        path = self.settings.session_path
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("session pointer was unreadable; starting fresh")
            return {}

    def _save_state(self) -> None:
        path = self.settings.session_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    async def ensure_login(self) -> None:
        if await self.browser.logged_in():
            self._login_notice_sent = False
            return
        log.info("browser is not logged in; waiting for you to sign in")
        if not self._login_notice_sent:
            self._login_notice_sent = True
            self._emit("login needed", "composer is not usable; sign in in the browser window")
        await self.browser.wait_for_login()

    async def run(
        self,
        messages: list,
        tools: list | None,
        tool_choice,
        reasoning_effort: str | None,
        chat_target: str | None = None,
    ) -> tuple[TurnResult, TurnPlan]:
        async with self.lock:
            self._sending = True
            try:
                return await self._run_locked(messages, tools, tool_choice, reasoning_effort, chat_target)
            finally:
                self._sending = False

    async def _run_locked(
        self,
        messages: list[dict],
        tools: list | None,
        tool_choice,
        reasoning_effort: str | None,
        chat_target: str | None = None,
    ) -> tuple[TurnResult, TurnPlan]:
        if chat_target == "new":
            url = await self.browser.rotate()
            self._clear_pointer(url, "request asked for a new chat")
            self._hold_chat = True
        elif chat_target:
            url = await self.browser.switch_chat(chat_target)
            self._clear_pointer(url, "request switched chat")
            self._hold_chat = True
        plan = plan_turn(
            messages,
            tools,
            tool_choice,
            reasoning_effort,
            self.prior,
        )
        result = await self._deliver(plan)
        parsed = parse_reply(result.text, tools_were_offered=bool(tools))
        if not parsed.needs_repair:
            return result, plan
        log.info("reply was not the tool contract; asking for one JSON repair")
        repair = TurnPlan(
            full_prompt=plan.full_prompt + "\n\n" + REPAIR_PROMPT,
            delta_prompt=REPAIR_PROMPT,
            continuing=True,
            message_count=plan.message_count,
            messages_fp=plan.messages_fp,
            tools_fp=plan.tools_fp,
        )
        repaired = await self._deliver(repair)
        repaired.rotations += result.rotations
        return repaired, plan

    async def complete(self, plan: TurnPlan) -> TurnResult:
        async with self.lock:
            return await self._deliver(plan)

    async def _deliver(self, plan: TurnPlan) -> TurnResult:
        await self.ensure_login()
        used_delta = bool(plan.continuing and plan.delta_prompt)
        if used_delta and not await self.browser.has_history():
            used_delta = False
        held = self._hold_chat
        self._hold_chat = False
        if not held and not used_delta and await self.browser.has_history() and not plan.continuing:
            url = await self.browser.rotate()
            self._clear_pointer(url, "transcript did not continue the active chat")
            await self._reapply_model()
        prompt = plan.delta_prompt if used_delta and plan.delta_prompt else plan.full_prompt
        rotations = 0
        while True:
            try:
                if not await self.browser.healthy():
                    url = await self.browser.rotate()
                    rotations += 1
                    prompt = plan.full_prompt
                    used_delta = False
                    self._clear_pointer(url, "active chat unhealthy before send")
                    log.warning("active chat unhealthy before send")
                    await self._reapply_model()
                text = await self.browser.send(prompt)
                await self._remember(plan)
                return TurnResult(text=text, rotations=rotations, used_delta=used_delta)
            except LoginRequired:
                raise
            except ChatFailure as exc:
                if rotations >= self.settings.max_retries:
                    log.error(
                        "chat rotation exhausted after %s retries: %s",
                        rotations,
                        exc.reason,
                    )
                    raise
                url = await self.browser.rotate()
                rotations += 1
                prompt = plan.full_prompt
                used_delta = False
                self._clear_pointer(url, exc.reason)
                await self._reapply_model()
                log.warning(
                    "rotated to %s after %s; resending full prompt (attempt %s)",
                    url,
                    exc.reason,
                    rotations,
                )

    def _clear_pointer(self, url: str, reason: str) -> None:
        self._state = {
            "chat_url": url,
            "message_count": 0,
            "messages_fp": "",
            "tools_fp": "",
            "last_rotation_reason": reason,
            "rotations": int(self._state.get("rotations") or 0) + 1,
        }
        self._save_state()
        if self.journal is not None:
            self.journal.rotation(reason=reason, url=url or "")
        self._emit("chat rotated", reason)

    def _emit(self, kind: str, text: str) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(kind, text)
        except Exception as exc:
            log.info("event listener failed: %s", exc)

    async def restart_browser(self) -> dict:
        async with self.lock:
            await self.browser.stop()
            await self.browser.start()
            log.info("browser restarted")
            return await self.browser.status()

    async def _remember(self, plan: TurnPlan) -> None:
        status = await self.browser.status()
        self._state.update(
            {
                "chat_url": status.get("chat_url"),
                "message_count": plan.message_count,
                "messages_fp": fingerprint_prefix(plan),
                "tools_fp": plan.tools_fp,
                "full_messages_fp": plan.messages_fp,
            }
        )
        self._save_state()

    async def break_active_chat(self) -> dict:
        async with self.lock:
            await self.browser.mark_broken()
            log.warning("forced break marked the active chat; the next completion rotates")
            self._emit("forced break", "active chat marked; the next completion rotates")
            return {
                "broken": True,
                "changed": False,
                "chat_url": self._state.get("chat_url"),
            }

    async def logout(self) -> dict:
        async with self.lock:
            status = await self.browser.logout()
            self._state = {
                "chat_url": None,
                "message_count": 0,
                "messages_fp": "",
                "tools_fp": "",
                "last_rotation_reason": "logged out",
                "rotations": int(self._state.get("rotations") or 0),
            }
            self._hold_chat = False
            self._save_state()
            log.info("logged out; sign in yourself in the browser window")
            return status

    async def prepare_login(self) -> dict:
        async with self.lock:
            await self.browser.open_login_page()
            status = await self.browser.status()
            log.info("login page is open; sign in yourself in the browser window")
            return status

    async def new_chat(self) -> dict:
        async with self.lock:
            url = await self.browser.rotate()
            self._clear_pointer(url, "operator asked for a new chat")
            await self._reapply_model()
            self._hold_chat = True
            return {"chat_url": url}

    async def switch_chat(self, url: str) -> dict:
        async with self.lock:
            landed = await self.browser.switch_chat(url)
            self._clear_pointer(landed, "operator switched chat")
            self._hold_chat = True
            return {"chat_url": landed}

    async def list_chats(self) -> dict:
        async with self.lock:
            status = await self.browser.status()
            chats = await self.browser.list_chats()
            current = status.get("chat_url") or ""
            listed = list(chats or [])
            if current.startswith("https://chatgpt.com/") and ("/c/" in current or "/uc/" in current):
                if not any(item.get("url") == current for item in listed):
                    listed.insert(0, {"url": current, "title": "Current chat"})
            return {"current": current or None, "chats": listed}

    async def list_models(self) -> dict:
        async with self.lock:
            found = await self.browser.list_models()
            found["selected"] = self._state.get("selected_model")
            return found

    def accounts(self):
        from gpt_bridge.accounts import AccountRegistry

        return AccountRegistry(self.settings.home / "data" / "profiles")

    async def list_accounts(self) -> dict:
        return self.accounts().list_accounts()

    async def add_account(self, label: str) -> dict:
        if self.lock.locked() or self._sending:
            raise AccountBusy("completion in flight")
        async with self.lock:
            if self._sending:
                raise AccountBusy("completion in flight")
            created = self.accounts().add(label)
            await self._open_account(created["label"])
            body = self.accounts().list_accounts()
            body["created"] = created["label"]
            status = await self.browser.status()
            body["logged_in"] = bool(status.get("logged_in"))
            body["chat_url"] = status.get("chat_url")
            return body

    async def use_account(self, label: str) -> dict:
        if self.lock.locked() or self._sending:
            raise AccountBusy("completion in flight")
        async with self.lock:
            if self._sending:
                raise AccountBusy("completion in flight")
            self.accounts().use(label)
            await self._open_account(label)
            status = await self.browser.status()
            return {
                "active": self.accounts().list_accounts()["active"],
                "logged_in": bool(status.get("logged_in")),
                "chat_url": status.get("chat_url"),
            }

    async def _open_account(self, label: str) -> None:
        profile = self.accounts().profile_dir(label)
        self._state = {
            "chat_url": None,
            "message_count": 0,
            "messages_fp": "",
            "tools_fp": "",
            "last_rotation_reason": f"opened account {label}",
            "rotations": int(self._state.get("rotations") or 0),
            "selected_model": self._state.get("selected_model"),
        }
        self._hold_chat = False
        self._save_state()
        await self.browser.use_profile(profile)
        log.info("opened account %s", label)

    async def select_model(self, name: str) -> dict:
        async with self.lock:
            chosen = await self.browser.select_model(name)
            self._state["selected_model"] = chosen.get("selected") or name
            self._save_state()
            return chosen

    async def _reapply_model(self) -> None:
        name = self._state.get("selected_model")
        if not name:
            return
        try:
            await self.browser.select_model(name)
        except Exception as exc:
            log.info("could not reapply model %s: %s", name, exc)

    @property
    def prior(self) -> dict | None:
        if not self._state.get("message_count"):
            return None
        return self._state


def fingerprint_prefix(plan: TurnPlan) -> str:
    """Store the prefix fingerprint that the next request must extend.

    The next request's prefix is the messages we just accepted in full.
    That hash is plan.messages_fp, not a hash of a shorter prefix.
    """

    return plan.messages_fp
