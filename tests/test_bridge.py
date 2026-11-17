from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpt_bridge.config import Settings
from dataclasses import replace
from gpt_bridge.chats import ChatTargetError, normalize_chat_target
from gpt_bridge.protocol import fingerprint, parse_reply, plan_turn
from gpt_bridge.session import ChatFailure, CompletionSession
from gpt_bridge.telegram import TelegramRelay
from gpt_bridge.wire import sse_chunks


def settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8000,
        api_key="local",
        require_api_key=True,
        chatgpt_url="https://chatgpt.com/",
        model_slug="",
        home=tmp_path,
        user_data_dir=tmp_path / "profile",
        storage_state_path=tmp_path / "storage_state.json",
        session_path=tmp_path / "session.json",
        log_dir=tmp_path / "logs",
        headless=True,
        channel=None,
        browser_mode="launch",
        cdp_url="http://127.0.0.1:9333",
        reply_timeout_s=5,
        stall_timeout_s=2,
        stable_seconds=0.1,
        login_timeout_s=1,
        max_retries=2,
        attach_threshold=8000,
        mock=True,
        slow_mo_ms=0,
    )


class ScriptedBrowser:
    def __init__(self, script: list[str]):
        self.script = list(script)
        self.prompts: list[str] = []
        self.rotations = 0
        self.broken = False
        self.history = False
        self.url = "https://chatgpt.com/"
        self.models = ["GPT-6.1 Sol", "Luna"]
        self.selected_model = "GPT-6.1 Sol"
        self.opened: list[str] = []
        self._logged_in = True

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def status(self) -> dict:
        return {
            "browser": "scripted",
            "logged_in": self._logged_in,
            "chat_url": self.url,
            "healthy": not self.broken,
        }

    async def logged_in(self) -> bool:
        return self._logged_in

    async def use_profile(self, profile_dir) -> None:
        from pathlib import Path

        path = Path(profile_dir)
        self.opened.append(str(path))
        self._logged_in = (path / "signed-in").exists()
        self.url = self.url if self._logged_in else "https://chatgpt.com/auth/login"

    async def wait_for_login(self) -> None:
        return None

    async def healthy(self) -> bool:
        return not self.broken

    async def has_history(self) -> bool:
        return self.history and not self.broken

    async def mark_broken(self) -> None:
        self.broken = True

    async def rotate(self) -> str:
        self.rotations += 1
        self.broken = False
        self.history = False
        self.url = f"https://chatgpt.com/c/rotated-{self.rotations}"
        return self.url

    async def switch_chat(self, url: str) -> str:
        self.url = url
        self.history = True
        self.broken = False
        return url

    async def logout(self) -> dict:
        self.history = False
        self.url = "https://chatgpt.com/"
        return await self.status()

    async def open_login_page(self) -> None:
        self.url = "https://chatgpt.com/"

    async def list_chats(self) -> list[dict]:
        return [{"url": "https://chatgpt.com/c/sidebar", "title": "Sidebar"}]

    async def list_models(self) -> dict:
        return {
            "current": self.selected_model,
            "models": [
                {"name": name, "selected": name == self.selected_model}
                for name in self.models
            ],
        }

    async def select_model(self, name: str) -> str:
        match = next((item for item in self.models if item.lower() == name.strip().lower()), None)
        if match is None:
            raise ChatFailure(f"model not in the menu: {name}")
        self.selected_model = match
        return {"selected": match, "current": match}

    async def send(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.script:
            raise ChatFailure("script exhausted")
        action = self.script.pop(0)
        if action.startswith("fail:"):
            raise ChatFailure(action.split(":", 1)[1])
        if action.startswith("ok:"):
            action = action.split(":", 1)[1]
        self.history = True
        self.url = "https://chatgpt.com/c/active"
        return action


def test_parse_contract_and_fenced_tool_call():
    parsed = parse_reply(
        '```json\n{"content": null, "tool_calls": [{"name": "Read", "arguments": {"path": "a.py"}}]}\n```',
        tools_were_offered=True,
    )
    assert parsed.needs_repair is False
    assert parsed.tool_calls[0]["function"]["name"] == "Read"
    assert json.loads(parsed.tool_calls[0]["function"]["arguments"]) == {"path": "a.py"}
    assert parsed.tool_calls[0]["id"].startswith("call_")
    assert parsed.finish_reason == "tool_calls"


def test_parse_prose_with_tools_requests_repair():
    parsed = parse_reply("I will read the file now.", tools_were_offered=True)
    assert parsed.needs_repair is True
    assert parsed.content == "I will read the file now."


def test_parse_prose_without_tools_is_content():
    parsed = parse_reply("hello", tools_were_offered=False)
    assert parsed.needs_repair is False
    assert parsed.content == "hello"


def test_continuation_plan_sends_only_the_new_tail():
    tools = [{"type": "function", "function": {"name": "Read", "parameters": {}}}]
    first = [{"role": "user", "content": "look at main.py"}]
    plan = plan_turn(first, tools, "auto", None, None)
    assert plan.continuing is False
    prior = {
        "message_count": plan.message_count,
        "messages_fp": plan.messages_fp,
        "tools_fp": plan.tools_fp,
    }
    second = first + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "function": {"name": "Read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "print('hi')"},
    ]
    follow = plan_turn(second, tools, "auto", "high", prior)
    assert follow.continuing is True
    assert follow.delta_prompt is not None
    assert "New messages" in follow.delta_prompt
    assert "print('hi')" in follow.delta_prompt
    assert "look at main.py" not in follow.delta_prompt
    assert fingerprint(first) == prior["messages_fp"]


def test_sse_tool_call_is_whole_and_has_no_empty_reasoning():
    parsed = parse_reply(
        '{"content": "checking", "tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}',
        tools_were_offered=True,
    )
    chunks = list(sse_chunks(parsed, model="gpt-subscription", prompt="prompt"))
    blob = json.dumps(chunks)
    assert "reasoning_content" not in blob
    tool_chunks = [
        chunk
        for chunk in chunks
        if chunk["choices"] and chunk["choices"][0]["delta"].get("tool_calls")
    ]
    call = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["id"]
    assert call["function"]["name"] == "Bash"
    assert call["function"]["arguments"] == '{"command": "ls"}'
    assert chunks[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_failure_rotates_and_resends_the_same_full_prompt(tmp_path: Path):
    asyncio.run(_failure_rotates(tmp_path))


async def _failure_rotates(tmp_path: Path):
    browser = ScriptedBrowser(
        ["fail:timeout", '{"content": "recovered", "tool_calls": []}']
    )
    session = CompletionSession(browser, settings(tmp_path))
    messages = [{"role": "user", "content": "say recovered"}]
    result, plan = await session.run(messages, None, None, None)
    assert result.rotations == 1
    assert result.text.startswith("{")
    assert browser.prompts == [plan.full_prompt, plan.full_prompt]
    assert "timeout" in session._state["last_rotation_reason"]


def test_broken_chat_resends_full_transcript_not_the_delta(tmp_path: Path):
    asyncio.run(_broken_chat_resends_full(tmp_path))


def test_second_turn_sends_only_the_new_tail(tmp_path: Path):
    asyncio.run(_second_turn_sends_tail(tmp_path))


async def _second_turn_sends_tail(tmp_path: Path):
    browser = ScriptedBrowser(
        [
            '{"content": "first", "tool_calls": []}',
            '{"content": "second", "tool_calls": []}',
        ]
    )
    session = CompletionSession(browser, settings(tmp_path))
    first = [{"role": "user", "content": "start"}]
    await session.run(first, None, None, None)
    second = first + [{"role": "user", "content": "continue"}]
    result, _plan = await session.run(second, None, None, None)
    assert result.used_delta is True
    assert result.rotations == 0
    assert "New messages" in browser.prompts[-1]
    assert "start" not in browser.prompts[-1]
    assert "continue" in browser.prompts[-1]


async def _broken_chat_resends_full(tmp_path: Path):
    browser = ScriptedBrowser(
        [
            '{"content": "first", "tool_calls": []}',
            '{"content": "second", "tool_calls": []}',
        ]
    )
    session = CompletionSession(browser, settings(tmp_path))
    tools = [{"type": "function", "function": {"name": "Read", "parameters": {}}}]
    first = [{"role": "user", "content": "start"}]
    await session.run(first, tools, "auto", None)
    await session.break_active_chat()
    second = first + [{"role": "user", "content": "continue"}]
    result, plan = await session.run(second, tools, "auto", None)
    assert result.used_delta is False
    assert browser.rotations == 1
    assert browser.prompts[-1] == plan.full_prompt
    assert "continue" in browser.prompts[-1]
    assert "===== TRANSCRIPT =====" in browser.prompts[-1]


def test_retries_are_capped(tmp_path: Path):
    asyncio.run(_retries_are_capped(tmp_path))


def test_force_break_marks_the_chat_and_the_next_completion_rotates(tmp_path: Path, caplog):
    asyncio.run(_force_break_marks_then_rotates(tmp_path, caplog))


async def _force_break_marks_then_rotates(tmp_path: Path, caplog):
    browser = ScriptedBrowser(
        [
            '{"content": "first", "tool_calls": []}',
            '{"content": "pong", "tool_calls": []}',
        ]
    )
    session = CompletionSession(browser, settings(tmp_path))
    await session.run([{"role": "user", "content": "start"}], None, None, None)
    with caplog.at_level(logging.WARNING, logger="gpt_bridge.session"):
        marked = await session.break_active_chat()
        assert marked["broken"] is True
        assert marked["changed"] is False
        assert browser.rotations == 0
        result, _plan = await session.run(
            [{"role": "user", "content": "Reply with the single word pong"}],
            None,
            None,
            None,
        )
    assert result.rotations == 1
    assert browser.rotations == 1
    assert browser.broken is False
    assert session._state["last_rotation_reason"] == "active chat unhealthy before send"
    assert "active chat unhealthy before send" in caplog.text


def test_model_pick_uses_only_names_the_browser_sees(tmp_path: Path):
    from gpt_bridge.api import create_app

    browser = ScriptedBrowser(['{"content": "pong", "tool_calls": []}'])
    app = create_app(settings(tmp_path), backend=browser)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer local"}
        listed = client.get("/v1/browser-models", headers=headers)
        assert listed.status_code == 200
        names = [item["name"] for item in listed.json()["models"]]
        assert names == ["GPT-6.1 Sol", "Luna"]
        chosen = client.post("/v1/browser-models/select", headers=headers, json={"name": "Luna"})
        assert chosen.status_code == 200
        assert chosen.json()["selected"] == "Luna"
        missing = client.post("/v1/browser-models/select", headers=headers, json={"name": "not-a-model"})
        assert missing.status_code == 502
        assert missing.json()["reason"]
        assert missing.json()["error"]["message"] == missing.json()["reason"]
        assert missing.json()["error"]["code"] == "chat_failure"


def test_secret_backup_kimi_and_failure_banner(tmp_path: Path):
    from gpt_bridge.api import create_app
    from gpt_bridge.journal import configure_logging
    from gpt_bridge.ops import backup_profiles, ensure_internal_secret, write_kimi_config
    from logging.handlers import RotatingFileHandler

    env = tmp_path / ".env"
    first, created = ensure_internal_secret(env)
    again, created_again = ensure_internal_secret(env)
    assert created is True
    assert created_again is False
    assert again == first
    assert "GPT_BRIDGE_INTERNAL_SECRET" not in __import__("logging").getLogger("gpt_bridge").handlers.__repr__()

    profiles = tmp_path / "data" / "profiles" / "work"
    profiles.mkdir(parents=True)
    (profiles / "note.txt").write_text("keep", encoding="utf-8")
    copied = backup_profiles(tmp_path)
    assert copied["copied"] is True
    assert (Path(copied["path"]) / "work" / "note.txt").read_text(encoding="utf-8") == "keep"

    kimi = tmp_path / "kimi.config.toml"
    kimi.write_text('default_model = "other"\n\n[providers.other]\ntype = "openai"\n', encoding="utf-8")
    written = write_kimi_config(kimi)
    text = kimi.read_text(encoding="utf-8")
    assert written["written"] is True
    assert "[providers.other]" in text
    assert 'base_url = "http://127.0.0.1:8000/v1"' in text
    assert 'api_key = "local"' in text
    assert 'default_model = "gpt-subscription"' in text
    assert write_kimi_config(kimi)["written"] is False

    untouched = tmp_path / "missing-kimi.toml"
    preview = write_kimi_config(untouched, dry_run=True)
    assert preview["dry_run"] is True
    assert preview["written"] is True
    assert not untouched.exists()
    assert preview["base_url"] == "http://127.0.0.1:8000/v1"
    assert preview["api_key"] == "local"
    assert preview["model"] == "gpt-subscription"

    configure_logging(tmp_path / "logs")
    root = __import__("logging").getLogger("gpt_bridge")
    rotating = [handler for handler in root.handlers if isinstance(handler, RotatingFileHandler)]
    assert rotating and rotating[0].maxBytes == 1_000_000
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)

    (tmp_path / "logs" / "failures").mkdir()
    (tmp_path / "logs" / "failures" / "1-composer-missing.png").write_bytes(b"png")
    app = create_app(settings(tmp_path), backend=ScriptedBrowser([]))
    with TestClient(app) as client:
        body = client.get("/dashboard-data", headers={"Authorization": "Bearer local"}).json()
    assert body["failures"]["count"] == 1
    assert "composer-missing" in body["failures"]["latest"][0]
    page = (Path(__file__).resolve().parents[1] / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "Selector breakage" in page
    assert "Write Kimi config" in page
    assert "Do not start a tunnel" in page


def test_accounts_keep_separate_profiles_and_block_a_busy_switch(tmp_path: Path):
    asyncio.run(_accounts_keep_separate_profiles(tmp_path))


async def _accounts_keep_separate_profiles(tmp_path: Path):
    from gpt_bridge.session import AccountBusy

    browser = ScriptedBrowser(['{"content": "pong", "tool_calls": []}'])
    session = CompletionSession(browser, settings(tmp_path))
    await session.add_account("work")
    await session.add_account("home")
    work = session.accounts().profile_dir("work")
    marker = work / "keep-me"
    marker.write_text("untouched", encoding="utf-8")
    (session.accounts().profile_dir("home") / "signed-in").write_text("yes", encoding="utf-8")
    used = await session.use_account("home")
    assert used["active"] == "home"
    assert used["logged_in"] is True
    assert browser.opened[-1].endswith("home")
    assert marker.read_text(encoding="utf-8") == "untouched"
    changed = await session.new_chat()
    assert changed["chat_url"] == "https://chatgpt.com/c/rotated-1"
    assert browser.rotations == 1
    await session.lock.acquire()
    try:
        with pytest.raises(AccountBusy):
            await session.use_account("work")
    finally:
        session.lock.release()
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert session.accounts().list_accounts()["active"] == "home"


def test_account_routes_reject_a_password_and_an_unknown_label(tmp_path: Path):
    from gpt_bridge.api import create_app

    browser = ScriptedBrowser(['{"content": "pong", "tool_calls": []}'])
    app = create_app(settings(tmp_path), backend=browser)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer local"}
        listed = client.get("/v1/accounts", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["accounts"] == []
        added = client.post("/v1/accounts/add", headers=headers, json={"label": "work"})
        assert added.status_code == 200
        assert added.json()["active"] == "work"
        secret = client.post(
            "/v1/accounts/add",
            headers=headers,
            json={"label": "other", "password": "do-not-store"},
        )
        assert secret.status_code == 422
        missing = client.post("/v1/accounts/use", headers=headers, json={"label": "missing"})
        assert missing.status_code == 404
        chats = client.get("/v1/chats", headers=headers)
        assert chats.status_code == 200
        assert chats.json()["chats"][0]["title"] == "Sidebar"
        registry = (tmp_path / "data" / "profiles" / "registry.json").read_text(encoding="utf-8")
        assert "password" not in registry
        assert "do-not-store" not in registry


async def _retries_are_capped(tmp_path: Path):
    cfg = settings(tmp_path)
    cfg = Settings(**{**cfg.__dict__, "max_retries": 1})
    browser = ScriptedBrowser(["fail:empty reply", "fail:empty reply"])
    session = CompletionSession(browser, cfg)
    with pytest.raises(ChatFailure) as caught:
        await session.run([{"role": "user", "content": "x"}], None, None, None)
    assert caught.value.reason == "empty reply"
    assert len(browser.prompts) == 2


def test_api_returns_openai_shape_and_streams(tmp_path: Path):
    from gpt_bridge.api import create_app

    browser = ScriptedBrowser(
        ['{"content": "pong", "tool_calls": []}', '{"content": "streamed", "tool_calls": []}']
    )
    app = create_app(settings(tmp_path), backend=browser)
    with TestClient(app) as client:
        denied = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        assert denied.status_code == 401
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["logged_in"] is True
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer local"},
            json={"model": "gpt-subscription", "messages": [{"role": "user", "content": "ping"}]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "pong"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert "reasoning_content" not in json.dumps(body)
        streamed = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer local"},
            json={
                "model": "gpt-subscription",
                "stream": True,
                "messages": [{"role": "user", "content": "again"}],
            },
        )
        assert streamed.status_code == 200
        assert "data: [DONE]" in streamed.text
        assert "reasoning_content" not in streamed.text
        log = (tmp_path / "logs" / "prompts.jsonl").read_text(encoding="utf-8")
        assert "ping" in log


def test_chat_target_accepts_only_your_conversation_links():
    assert normalize_chat_target("new") == "new"
    assert normalize_chat_target(" https://chatgpt.com/c/abc ") == "https://chatgpt.com/c/abc"
    assert normalize_chat_target("https://www.chatgpt.com/uc/abc") == "https://chatgpt.com/uc/abc"
    with pytest.raises(ChatTargetError):
        normalize_chat_target("https://evil.example/c/abc")
    with pytest.raises(ChatTargetError):
        normalize_chat_target("https://chatgpt.com/")


def test_requested_new_chat_is_not_immediately_rotated_away(tmp_path: Path):
    asyncio.run(_requested_new_chat(tmp_path))


async def _requested_new_chat(tmp_path: Path):
    browser = ScriptedBrowser(['{"content": "fresh", "tool_calls": []}'])
    browser.history = True
    session = CompletionSession(browser, settings(tmp_path))
    result, plan = await session.run(
        [{"role": "user", "content": "start clean"}],
        None,
        None,
        None,
        "new",
    )
    assert browser.rotations == 1
    assert result.rotations == 0
    assert browser.prompts == [plan.full_prompt]
    assert session._state["last_rotation_reason"] == "request asked for a new chat"


def test_api_switches_only_a_chatgpt_conversation(tmp_path: Path):
    from gpt_bridge.api import create_app

    browser = ScriptedBrowser(['{"content": "ok", "tool_calls": []}'])
    app = create_app(settings(tmp_path), backend=browser)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer local"}
        listed = client.get("/v1/chats", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["chats"][0]["url"].startswith("https://chatgpt.com/c/")
        opened = client.post("/v1/chats/new", headers=headers)
        assert opened.status_code == 200
        assert opened.json()["chat_url"].startswith("https://chatgpt.com/c/")
        rejected = client.post(
            "/v1/chats/switch",
            headers=headers,
            json={"url": "https://evil.example/c/nope"},
        )
        assert rejected.status_code == 400
        switched = client.post(
            "/v1/chats/switch",
            headers=headers,
            json={"url": "https://chatgpt.com/c/kept"},
        )
        assert switched.status_code == 200
        assert switched.json()["chat_url"] == "https://chatgpt.com/c/kept"
        logged_out = client.post("/v1/session/logout", headers=headers)
        assert logged_out.status_code == 200
        assert logged_out.json()["logged_in"] is True or logged_out.json()["chat_url"]


def test_open_chat_is_listed_when_the_sidebar_is_empty(tmp_path: Path):
    from gpt_bridge.api import create_app

    browser = ScriptedBrowser([])
    browser.url = "https://chatgpt.com/c/open"

    async def empty() -> list[dict]:
        return []

    browser.list_chats = empty
    app = create_app(settings(tmp_path), backend=browser)
    with TestClient(app) as client:
        body = client.get("/v1/chats", headers={"Authorization": "Bearer local"}).json()
    assert body["current"] == "https://chatgpt.com/c/open"
    assert body["chats"] == [{"url": "https://chatgpt.com/c/open", "title": "Current chat"}]


def test_dashboard_data_requires_the_key_and_stamps_health(tmp_path: Path):
    from gpt_bridge.api import create_app

    app = create_app(settings(tmp_path), backend=ScriptedBrowser([]))
    with TestClient(app) as client:
        assert client.get("/dashboard-data").status_code == 401
        body = client.get("/dashboard-data", headers={"Authorization": "Bearer local"}).json()
        assert body["session"]["logged_in"] is True
        assert body["health"]["timestamp"]
        assert body["health"]["status"] == "ok"
        assert "rotations" in body
        health = client.get("/health").json()
        assert health["timestamp"]
        assert "forced_broken" in health


def test_dashboard_tails_twenty_log_lines_and_hides_tokens(tmp_path: Path):
    from gpt_bridge.api import create_app

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    lines = [f"2026-11-11T00:00:{i:02d}Z line {i}" for i in range(30)]
    lines.append("token 123456:abcdefghijklmnopqrstuvwxyz")
    (log_dir / "bridge.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (log_dir / "rotations.jsonl").write_text(
        "\n".join(
            json.dumps({"ts": f"2026-11-11T00:00:{i:02d}Z", "reason": f"r{i}", "url": "https://chatgpt.com/"})
            for i in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    app = create_app(settings(tmp_path), backend=ScriptedBrowser([]))
    with TestClient(app) as client:
        body = client.get("/dashboard-data", headers={"Authorization": "Bearer local"}).json()
    bridge = body["logs"]["bridge"]
    assert len(bridge) == 20
    assert bridge[0].endswith("line 11")
    assert "abcdefghijklmnopqrstuvwxyz" not in json.dumps(body)
    assert "[redacted]" in bridge[-1]
    assert len(body["logs"]["rotations"]) == 3
    assert "2026-11-11T00:00:02Z" in body["logs"]["rotations"][-1]


def test_dashboard_sections_stay_in_order():
    text = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    dashboard = (Path(__file__).resolve().parents[1] / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert text == dashboard
    titles = [
        "1. Connection",
        "2. Accounts",
        "3. Browser Actions",
        "4. Models",
        "5. Telegram",
        "6. API Reference",
        "7. Logs",
    ]
    positions = [text.index(title) for title in titles]
    assert positions == sorted(positions)
    assert "Passwords are never stored" in text
    assert "Force break marks the chat" in text
    assert "never appears in this page" in text
    assert "gpt-subscription" in text
    assert "Getting Started" in text
    assert "I have signed in" in text
    assert "make night-check" in text
    assert "ChatGPT Logged In" in text
    assert "ChatGPT Not Logged In" in text
    assert "123456:" not in text
    assert "git clone https://github.com/emzylavish-art/gpt-bridge.git" not in text
    assert "missing internal secret" in text
    assert "Do not clone" in text
    assert "Adrian is the sole owner" in text
    assert "Adrian (open)" in text
    assert 'id="nav-toggle"' in text
    assert 'data-panel="getting-started"' in text
    assert 'data-panel="logs"' in text


def test_control_route_rejects_a_missing_internal_secret(tmp_path: Path):
    from gpt_bridge.api import create_app

    locked = replace(settings(tmp_path), internal_secret="gate")
    app = create_app(locked, backend=ScriptedBrowser([]))
    with TestClient(app) as client:
        denied = client.get("/dashboard-data", headers={"Authorization": "Bearer local"})
        assert denied.status_code == 401
        allowed = client.get(
            "/dashboard-data",
            headers={"Authorization": "Bearer local", "X-GPT-Bridge-Secret": "gate"},
        )
        assert allowed.status_code == 200


def test_telegram_verification_captures_start_without_logging_the_token(tmp_path: Path):
    from gpt_bridge.api import create_app

    calls = []

    def fake(token, method, payload=None):
        calls.append(method)
        assert token == "123:abc"
        if method == "getMe":
            return {"ok": True, "result": {"username": "bridge_bot"}}
        if method == "getUpdates":
            return {
                "ok": True,
                "result": [{"update_id": 7, "message": {"text": "/start", "chat": {"id": 42}}}],
            }
        return {"ok": True, "result": {}}

    app = create_app(settings(tmp_path), backend=ScriptedBrowser([]))
    with TestClient(app) as client:
        app.state.relay = TelegramRelay(tmp_path / "data" / "telegram.json", call=fake)
        headers = {"Authorization": "Bearer local"}
        bad = client.post("/v1/telegram/config", headers=headers, json={"bot_token": "nope"})
        assert bad.status_code == 400
        verified = client.post(
            "/v1/telegram/config",
            headers=headers,
            json={"bot_token": "123:abc", "dashboard_url": "http://127.0.0.1:8000/dashboard"},
        )
        assert verified.status_code == 200
        assert verified.json()["username"] == "bridge_bot"
        assert verified.json()["start_url"] == "https://t.me/bridge_bot?start=gptbridge"
        assert "123:abc" not in verified.text
        assert verified.json()["connected"] is False
        polled = client.post("/v1/telegram/poll", headers=headers)
        assert polled.status_code == 200
        assert polled.json()["chat_id"] == 42
        assert polled.json()["connected"] is True
        assert "getMe" in calls


def test_serve_refuses_a_public_bind_and_the_tunnel_stays_on_localhost(tmp_path: Path):
    from gpt_bridge.__main__ import _serve

    text = (Path(__file__).resolve().parents[1] / "DEPLOY.md").read_text(encoding="utf-8")
    assert "cloudflared tunnel --url http://127.0.0.1:8000" in text
    assert "The PC must stay on" in text
    assert "Never bind `0.0.0.0`" in text
    with pytest.raises(SystemExit, match="refusing to bind outside localhost"):
        _serve(settings(tmp_path), "0.0.0.0", 8000)


def test_forced_break_and_login_needed_push_telegram_buttons(tmp_path: Path, caplog):
    asyncio.run(_telegram_buttons(tmp_path, caplog))


async def _telegram_buttons(tmp_path: Path, caplog):
    sent = []
    token = "123456:not-written-to-logs"

    def fake(got_token, method, payload=None):
        assert got_token == token
        sent.append((method, payload))
        if method == "getMe":
            return {"ok": True, "result": {"username": "bridge_bot"}}
        return {"ok": True, "result": {}}

    relay = TelegramRelay(tmp_path / "data" / "telegram.json", call=fake)
    relay.configure(token, "http://127.0.0.1:8000/dashboard")
    relay._state["chat_id"] = 42
    browser = ScriptedBrowser(['{"content": "pong", "tool_calls": []}'])
    browser._logged_in = False
    session = CompletionSession(
        browser,
        settings(tmp_path),
        on_event=lambda kind, text: relay.notify(kind, text),
    )
    with caplog.at_level(logging.INFO):
        await session.ensure_login()
        marked = await session.break_active_chat()
    assert marked["broken"] is True
    notices = [
        payload
        for method, payload in sent
        if method == "sendMessage" and payload and "reply_markup" in payload
    ]
    assert len(notices) == 2
    labels = [
        [button["text"] for row in payload["reply_markup"]["inline_keyboard"] for button in row]
        for payload in notices
    ]
    assert labels == [
        ["Restart browser", "Force break", "Open dashboard"],
        ["Restart browser", "Force break", "Open dashboard"],
    ]
    assert notices[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "restart"
    assert notices[0]["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == "force_break"
    assert notices[0]["reply_markup"]["inline_keyboard"][2][0]["url"] == "http://127.0.0.1:8000/dashboard"
    assert notices[0]["text"].startswith("login needed:")
    assert notices[1]["text"].startswith("forced break:")
    assert token not in caplog.text
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert token not in html


def test_prompt_journal_rotates_at_one_megabyte(tmp_path: Path):
    from gpt_bridge.journal import Journal

    journal = Journal(tmp_path)
    journal.max_bytes = 80
    journal.prompt(model="gpt-subscription", prompt="a" * 40, reply="b" * 40, rotations=0, used_delta=False, stream=False)
    journal.prompt(model="gpt-subscription", prompt="c" * 40, reply="d" * 40, rotations=0, used_delta=False, stream=False)
    assert (tmp_path / "prompts.jsonl.1").is_file()
    current = (tmp_path / "prompts.jsonl").read_text(encoding="utf-8")
    assert '"prompt": "' + ("c" * 40) in current
    assert "a" * 40 not in current


def test_legacy_profile_is_adopted_as_adrian(tmp_path: Path):
    from gpt_bridge.accounts import AccountRegistry

    legacy = tmp_path / "profile"
    legacy.mkdir()
    (legacy / "storage_state.json").write_text("{}", encoding="utf-8")
    registry = AccountRegistry(tmp_path / "profiles")
    registry.adopt_legacy(legacy)
    body = registry.list_accounts()
    assert body["active"] == "Adrian"
    assert body["accounts"] == [{"label": "Adrian", "active": True}]
    assert (tmp_path / "profiles" / "adrian").is_dir()
    assert not legacy.exists()


def test_a_lone_default_account_is_renamed_to_adrian(tmp_path: Path):
    from gpt_bridge.accounts import AccountRegistry

    root = tmp_path / "profiles"
    old = root / "default"
    old.mkdir(parents=True)
    (old / "storage_state.json").write_text("{}", encoding="utf-8")
    registry = AccountRegistry(root)
    registry._save({"active": "default", "accounts": [{"label": "default"}]})
    registry.claim_sole_owner()
    body = registry.list_accounts()
    assert body["active"] == "Adrian"
    assert (root / "adrian" / "storage_state.json").is_file()
    assert not old.exists()


def test_installed_chrome_is_used_instead_of_playwright_chromium(tmp_path: Path):
    from gpt_bridge.config import installed_browser_channel

    chrome = tmp_path / "chrome.exe"
    chrome.write_text("x", encoding="utf-8")
    edge = tmp_path / "missing-edge.exe"
    candidates = {"chrome": [chrome], "msedge": [edge]}
    assert installed_browser_channel(None, candidates) == "chrome"
    assert installed_browser_channel("chromium", candidates) is None
    assert installed_browser_channel("msedge", candidates) == "msedge"


def test_chrome_login_uses_a_fresh_profile_folder(tmp_path: Path, monkeypatch):
    from gpt_bridge.config import load_settings

    monkeypatch.setenv("GPT_BRIDGE_HOME", str(tmp_path))
    monkeypatch.setenv("GPT_BRIDGE_CHANNEL", "chrome")
    loaded = load_settings(tmp_path)
    assert loaded.channel == "chrome"
    assert loaded.user_data_dir == tmp_path / "data" / "profile-chrome"
    assert loaded.user_data_dir != tmp_path / "data" / "profile"


def test_attach_mode_uses_local_chrome_cdp(tmp_path: Path, monkeypatch):
    from gpt_bridge.config import load_settings

    monkeypatch.setenv("GPT_BRIDGE_HOME", str(tmp_path))
    monkeypatch.setenv("GPT_BRIDGE_BROWSER_MODE", "attach")
    monkeypatch.setenv("GPT_BRIDGE_CDP_URL", "http://127.0.0.1:9333")
    loaded = load_settings(tmp_path)
    assert loaded.browser_mode == "attach"
    assert loaded.cdp_url == "http://127.0.0.1:9333"


def test_cli_prove_sends_on_existing_signed_in_tab(monkeypatch, capsys):
    import gpt_bridge.playwright_backend as backend_module
    from gpt_bridge.__main__ import _prove

    class FakePage:
        url = "https://chatgpt.com/c/already-open"

    class FakeBrowser:
        def __init__(self, settings):
            self.page = FakePage()
            self.sent = []
            self.rotated = False

        async def start(self):
            return None

        async def stop(self):
            return None

        async def logged_in(self):
            return True

        async def send(self, prompt):
            self.sent.append(prompt)
            return "pong"

    fake = FakeBrowser(None)
    monkeypatch.setattr(backend_module, "PlaywrightBackend", lambda settings: fake)
    result = asyncio.run(_prove(settings(Path("/tmp")), "Reply with pong"))
    assert result == 0
    assert fake.sent == ["Reply with pong"]
    assert fake.rotated is False
    assert "pong" in capsys.readouterr().out


def test_cli_prove_accepts_visible_pong_when_send_waiter_errors(monkeypatch, capsys):
    import gpt_bridge.playwright_backend as backend_module
    from gpt_bridge.__main__ import _prove

    class FakePage:
        url = "https://chatgpt.com/c/already-open"

        async def evaluate(self, script):
            return "pong"

    class FakeBrowser:
        def __init__(self, settings):
            self.page = FakePage()

        async def start(self):
            return None

        async def stop(self):
            return None

        async def logged_in(self):
            return True

        async def send(self, prompt):
            raise RuntimeError("reply selector timed out")

    monkeypatch.setattr(backend_module, "PlaywrightBackend", FakeBrowser)
    result = asyncio.run(_prove(settings(Path("/tmp")), "Reply with pong"))
    assert result == 0
    captured = capsys.readouterr()
    assert "pong" in captured.out
    assert "reply-detected-after-send-error" in captured.err


def test_composer_state_fixture_reports_disabled_stale_view(tmp_path: Path):
    from gpt_bridge.playwright_backend import PlaywrightBackend

    class FixturePage:
        async def evaluate(self, script):
            assert "getBoundingClientRect" in script
            return {
                "tag": "TEXTAREA",
                "text": "",
                "value_length": 0,
                "visible": True,
                "disabled": True,
                "focused": False,
                "box": {"x": 10, "y": 20, "width": 400, "height": 40},
                "user_nodes": 3,
                "title": "ChatGPT",
                "errors": [],
                "url": "https://chat.openai.com/c/stale",
            }

    backend = PlaywrightBackend(settings(tmp_path))
    backend.page = FixturePage()
    state = asyncio.run(backend._composer_state())
    assert state["disabled"] is True
    assert state["focused"] is False
    assert state["url"].startswith("https://chat.openai.com/")


def test_assistant_text_probe_includes_visible_markdown_fallback(tmp_path: Path):
    from gpt_bridge.playwright_backend import PlaywrightBackend

    class FixturePage:
        async def evaluate(self, script):
            assert 'main [class*="markdown"]' in script
            assert 'getBoundingClientRect' in script
            return ["pong"]

    backend = PlaywrightBackend(settings(tmp_path))
    backend.page = FixturePage()
    texts = asyncio.run(backend._assistant_texts())
    assert texts == ["pong"]
