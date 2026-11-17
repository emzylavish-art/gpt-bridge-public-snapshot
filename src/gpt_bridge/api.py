from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from gpt_bridge.config import Settings, load_settings
from gpt_bridge.chats import ChatTargetError, normalize_chat_target
from gpt_bridge.journal import Journal, configure_logging
from gpt_bridge.ops import failure_snapshot, kimi_config_path, write_kimi_config
from gpt_bridge.protocol import parse_reply
from gpt_bridge.accounts import AccountNameError, AccountRegistry
from gpt_bridge.session import AccountBusy, ChatFailure, CompletionSession, LoginRequired
from gpt_bridge.telegram import TelegramError, TelegramRelay
from gpt_bridge.wire import completion_body, sse_lines

log = logging.getLogger("gpt_bridge.api")
_SECRET_LINE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{10,}\b|Bearer\s+\S+", re.IGNORECASE)


def _tail_lines(path: Path, limit: int = 20) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [_SECRET_LINE.sub("[redacted]", line) for line in lines[-limit:]]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "gpt-subscription"
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    stream: bool = False
    reasoning_effort: str | None = None


class SwitchRequest(BaseModel):
    url: str


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str


class ModelSelect(BaseModel):
    name: str


class TelegramSetup(BaseModel):
    bot_token: str
    dashboard_url: str = ""


def create_app(settings: Settings | None = None, backend=None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_dir)
    journal = Journal(settings.log_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        layer = backend
        if layer is None:
            if settings.mock:
                from gpt_bridge.mock_backend import MockBackend

                layer = MockBackend()
            else:
                from gpt_bridge.playwright_backend import PlaywrightBackend

                layer = PlaywrightBackend(settings)
        app.state.browser = layer
        app.state.journal = journal
        app.state.settings = settings
        relay = TelegramRelay(settings.home / "data" / "telegram.json")
        app.state.relay = relay
        app.state.session = CompletionSession(
            layer,
            settings,
            journal=journal,
            on_event=lambda kind, text: _safe_notify(relay, kind, text),
        )
        registry = AccountRegistry(settings.home / "data" / "profiles")
        registry.adopt_legacy(settings.user_data_dir)
        registry.claim_sole_owner()
        active = registry.active_profile()
        if active is not None and hasattr(layer, "prepare_profile"):
            layer.prepare_profile(active)
        await layer.start()
        poller = asyncio.create_task(_telegram_poll(app))
        try:
            yield
        finally:
            poller.cancel()
            await layer.stop()

    app = FastAPI(title="gpt-bridge", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def bridge_http_error(request: Request, exc: HTTPException):
        reason = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        headers = getattr(exc, "headers", None)
        if exc.status_code in {502, 503}:
            code = "login_required" if exc.status_code == 503 else "chat_failure"
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "detail": reason,
                    "reason": reason,
                    "error": {"message": reason, "type": "bridge_error", "code": code},
                },
                headers=headers,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Completions stay open to the word local so Kimi Code can call them.
    # The internal secret gates control routes only. Do not share a tunnel URL.

    @app.middleware("http")
    async def private_network(request: Request, call_next):
        if request.method == "OPTIONS":
            response = JSONResponse({})
        else:
            response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    def session() -> CompletionSession:
        return app.state.session

    def check_key(request: Request) -> None:
        if not settings.require_api_key:
            return
        header = request.headers.get("authorization", "")
        if header != f"Bearer {settings.api_key}":
            raise HTTPException(status_code=401, detail="invalid api key")

    def check_control(request: Request) -> None:
        check_key(request)
        secret = settings.internal_secret
        if secret and request.headers.get("x-gpt-bridge-secret") != secret:
            raise HTTPException(status_code=401, detail="missing internal secret")

    @app.get("/health")
    @app.get("/v1/health")
    async def health():
        body = await app.state.browser.status()
        body["status"] = "ok" if body.get("browser") != "stopped" else "down"
        body["timestamp"] = _stamp()
        body.setdefault("forced_broken", False)
        body.setdefault("healthy", bool(body.get("logged_in")))
        body["internal_secret_set"] = bool(settings.internal_secret)
        return body

    @app.get("/")
    async def root():
        return {
            "service": "gpt-bridge",
            "health": "/health",
            "completions": "/v1/chat/completions",
            "session": "/v1/session",
            "chats": "/v1/chats",
        }

    @app.get("/v1/session")
    async def session_status(request: Request):
        check_control(request)
        return await app.state.browser.status()

    @app.post("/v1/session/logout")
    async def logout(request: Request):
        check_control(request)
        return await session().logout()

    @app.post("/v1/session/login")
    async def prepare_login(request: Request):
        check_control(request)
        return await session().prepare_login()

    @app.get("/v1/chats")
    async def chats(request: Request):
        check_control(request)
        return await session().list_chats()

    @app.get("/v1/accounts")
    async def accounts(request: Request):
        check_control(request)
        return await session().list_accounts()

    @app.post("/v1/accounts/add")
    async def add_account(body: AccountRequest, request: Request):
        check_control(request)
        try:
            return await session().add_account(body.label)
        except AccountBusy as exc:
            raise HTTPException(status_code=409, detail=exc.reason) from exc
        except AccountNameError as exc:
            raise HTTPException(status_code=400, detail=exc.reason) from exc

    @app.post("/v1/accounts/use")
    async def use_account(body: AccountRequest, request: Request):
        check_control(request)
        try:
            return await session().use_account(body.label)
        except AccountBusy as exc:
            raise HTTPException(status_code=409, detail=exc.reason) from exc
        except AccountNameError as exc:
            raise HTTPException(status_code=404, detail=exc.reason) from exc

    @app.post("/v1/chats/new")
    async def new_chat(request: Request):
        check_control(request)
        try:
            return await session().new_chat()
        except ChatFailure as exc:
            raise HTTPException(status_code=502, detail=exc.reason) from exc

    @app.post("/v1/chats/switch")
    async def switch_chat(body: SwitchRequest, request: Request):
        check_control(request)
        try:
            target = normalize_chat_target(body.url)
        except ChatTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if target in {None, "new"}:
            raise HTTPException(status_code=400, detail="url must be a ChatGPT conversation link")
        try:
            return await session().switch_chat(target)
        except LoginRequired as exc:
            raise HTTPException(status_code=503, detail=exc.reason) from exc
        except ChatFailure as exc:
            raise HTTPException(status_code=502, detail=exc.reason) from exc

    @app.get("/v1/browser-models")
    async def browser_models(request: Request):
        check_control(request)
        return await session().list_models()

    @app.post("/v1/browser-models/select")
    async def select_browser_model(body: ModelSelect, request: Request):
        check_control(request)
        try:
            return await session().select_model(body.name)
        except ChatFailure as exc:
            raise HTTPException(status_code=502, detail=exc.reason) from exc

    @app.get("/v1/models")
    async def models(request: Request):
        check_key(request)
        return {
            "object": "list",
            "data": [
                {
                    "id": "gpt-subscription",
                    "object": "model",
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/debug/break")
    async def force_break(request: Request):
        check_control(request)
        try:
            marked = await session().break_active_chat()
        except ChatFailure as exc:
            raise HTTPException(status_code=502, detail=exc.reason) from exc
        return marked

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatRequest, request: Request):
        check_key(request)
        if not body.messages:
            raise HTTPException(status_code=400, detail="messages is required")
        extra = body.model_extra or {}
        raw_target = request.headers.get("x-gpt-bridge-chat") or extra.get("gpt_bridge_chat")
        try:
            target = normalize_chat_target(raw_target if isinstance(raw_target, str) else None)
        except ChatTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            result, plan = await session().run(
                body.messages,
                body.tools,
                body.tool_choice,
                body.reasoning_effort,
                target,
            )
        except LoginRequired as exc:
            raise HTTPException(status_code=503, detail=exc.reason) from exc
        except ChatFailure as exc:
            raise HTTPException(status_code=502, detail=exc.reason) from exc
        app.state.journal.prompt(
            model=body.model,
            prompt=plan.full_prompt,
            reply=result.text,
            rotations=result.rotations,
            used_delta=result.used_delta,
            stream=body.stream,
        )
        log.info(
            "completion model=%s chars=%s rotations=%s delta=%s stream=%s",
            body.model,
            len(plan.full_prompt),
            result.rotations,
            result.used_delta,
            body.stream,
        )
        parsed = parse_reply(result.text, tools_were_offered=bool(body.tools))
        if body.stream:
            return StreamingResponse(
                sse_lines(parsed, model=body.model, prompt=plan.full_prompt),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(
            completion_body(parsed, model=body.model, prompt=plan.full_prompt)
        )

    @app.get("/dashboard-data")
    async def dashboard_data(request: Request):
        check_control(request)
        status = await app.state.browser.status()
        stamped = {
            **status,
            "status": "ok" if status.get("browser") != "stopped" else "down",
            "timestamp": _stamp(),
            "forced_broken": status.get("forced_broken", False),
            "healthy": status.get("healthy", bool(status.get("logged_in"))),
        }
        return {
            "timestamp": stamped["timestamp"],
            "session": {
                "logged_in": stamped.get("logged_in"),
                "chat_url": stamped.get("chat_url"),
                "status": stamped["status"],
                "browser": stamped.get("browser"),
            },
            "health": stamped,
            "rotations": journal.recent_rotations(),
            "logs": {
                "bridge": _tail_lines(settings.log_dir / "bridge.log"),
                "rotations": _tail_lines(settings.log_dir / "rotations.jsonl"),
            },
            "failures": failure_snapshot(settings.log_dir),
        }

    @app.get("/dashboard")
    async def dashboard_page():
        path = settings.home / "dashboard" / "index.html"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="dashboard file is missing")
        return FileResponse(path)

    @app.post("/v1/session/restart")
    async def restart(request: Request):
        check_control(request)
        return await session().restart_browser()

    @app.post("/v1/telegram/config")
    async def telegram_config(body: TelegramSetup, request: Request):
        check_control(request)
        try:
            return app.state.relay.configure(body.bot_token, body.dashboard_url)
        except TelegramError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/telegram/status")
    async def telegram_status(request: Request):
        check_control(request)
        return app.state.relay.status()

    @app.post("/v1/telegram/poll")
    async def telegram_poll(request: Request):
        check_control(request)
        try:
            result = await asyncio.to_thread(app.state.relay.poll_once)
        except TelegramError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await _act_on_telegram(app, result.get("captured"))
        return app.state.relay.status()

    @app.post("/v1/kimi/install")
    async def kimi_install(request: Request):
        check_control(request)
        return write_kimi_config(kimi_config_path())

    return app


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_notify(relay: TelegramRelay, kind: str, text: str) -> None:
    try:
        relay.notify(kind, text)
    except TelegramError as exc:
        log.info("telegram notice failed: %s", exc)


async def _telegram_poll(app: FastAPI) -> None:
    while True:
        try:
            result = await asyncio.to_thread(app.state.relay.poll_once)
            await _act_on_telegram(app, result.get("captured"))
        except Exception as exc:
            log.info("telegram poll failed: %s", exc)
        await asyncio.sleep(2)


async def _act_on_telegram(app: FastAPI, action: str | None) -> None:
    if action == "restart":
        await app.state.session.restart_browser()
    elif action == "force_break":
        await app.state.session.break_active_chat()
