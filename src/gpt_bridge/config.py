from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def browser_candidates() -> dict[str, list[Path]]:
    home = Path.home()
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        program = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        program86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        return {
            "chrome": [
                program / "Google" / "Chrome" / "Application" / "chrome.exe",
                program86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                local / "Google" / "Chrome" / "Application" / "chrome.exe",
            ],
            "msedge": [
                program / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                program86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ],
        }
    if sys.platform == "darwin":
        return {
            "chrome": [Path("/Applications/Google Chrome.app")],
            "msedge": [Path("/Applications/Microsoft Edge.app")],
        }
    return {
        "chrome": [Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable")],
        "msedge": [Path("/usr/bin/microsoft-edge"), Path("/usr/bin/microsoft-edge-stable")],
    }


def installed_browser_channel(
    explicit: str | None = None,
    candidates: dict[str, list[Path]] | None = None,
) -> str | None:
    """Return chrome or msedge when that normal browser is installed.

    Playwright's own Chromium is what Google rejects. This does not hide
    automation or change Google's check. chromium forces the bundled browser.
    """
    chosen = (explicit or "").strip().lower()
    if chosen in {"chromium", "bundled", "none"}:
        return None
    if chosen in {"chrome", "msedge"}:
        return chosen
    if chosen:
        return chosen
    for channel, paths in (candidates or browser_candidates()).items():
        if any(path.exists() for path in paths):
            return channel
    return None


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    api_key: str
    require_api_key: bool
    chatgpt_url: str
    model_slug: str
    home: Path
    user_data_dir: Path
    storage_state_path: Path
    session_path: Path
    log_dir: Path
    headless: bool
    channel: str | None
    browser_mode: str
    cdp_url: str
    reply_timeout_s: float
    stall_timeout_s: float
    stable_seconds: float
    login_timeout_s: float
    max_retries: int
    attach_threshold: int
    mock: bool
    slow_mo_ms: int
    internal_secret: str = ""

    @property
    def new_chat_url(self) -> str:
        base = self.chatgpt_url.rstrip("/") + "/"
        if self.model_slug:
            return f"{base}?model={self.model_slug}"
        return base


def load_settings(home: Path | None = None) -> Settings:
    root = home or Path.cwd()
    _load_dotenv(root / ".env")
    base = Path(os.environ.get("GPT_BRIDGE_HOME", root)).expanduser().resolve()
    channel = installed_browser_channel(os.environ.get("GPT_BRIDGE_CHANNEL"))
    profile = base / "data" / "profile"
    if channel in {"chrome", "msedge"}:
        profile = base / "data" / f"profile-{channel}"
    return Settings(
        host=os.environ.get("GPT_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("GPT_BRIDGE_PORT", "8000")),
        api_key=os.environ.get("GPT_BRIDGE_API_KEY", "local"),
        require_api_key=_flag("GPT_BRIDGE_REQUIRE_API_KEY", True),
        chatgpt_url=os.environ.get("GPT_BRIDGE_CHATGPT_URL", "https://chatgpt.com/"),
        model_slug=os.environ.get("GPT_BRIDGE_MODEL_SLUG", "").strip(),
        home=base,
        user_data_dir=profile,
        storage_state_path=base / "data" / "storage_state.json",
        session_path=base / "data" / "session.json",
        log_dir=base / "logs",
        headless=_flag("GPT_BRIDGE_HEADLESS", False),
        channel=channel,
        browser_mode=os.environ.get("GPT_BRIDGE_BROWSER_MODE", "launch").strip().lower(),
        cdp_url=os.environ.get("GPT_BRIDGE_CDP_URL", "http://127.0.0.1:9333").strip(),
        reply_timeout_s=float(os.environ.get("GPT_BRIDGE_REPLY_TIMEOUT_S", "240")),
        stall_timeout_s=float(os.environ.get("GPT_BRIDGE_STALL_TIMEOUT_S", "45")),
        stable_seconds=float(os.environ.get("GPT_BRIDGE_STABLE_SECONDS", "2")),
        login_timeout_s=float(os.environ.get("GPT_BRIDGE_LOGIN_TIMEOUT_S", "600")),
        max_retries=int(os.environ.get("GPT_BRIDGE_MAX_RETRIES", "2")),
        attach_threshold=int(os.environ.get("GPT_BRIDGE_ATTACH_THRESHOLD", "8000")),
        mock=_flag("GPT_BRIDGE_MOCK", False),
        slow_mo_ms=int(os.environ.get("GPT_BRIDGE_SLOW_MO_MS", "0")),
        internal_secret=os.environ.get("GPT_BRIDGE_INTERNAL_SECRET", "").strip(),
    )
