from __future__ import annotations

import secrets
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path

SECRET_KEY = "GPT_BRIDGE_INTERNAL_SECRET"

KIMI_BLOCK = """
[providers.gpt-subscription]
type = "openai"
base_url = "http://127.0.0.1:8000/v1"
api_key = "local"

[models."gpt-subscription"]
provider = "gpt-subscription"
model = "gpt-subscription"
max_context_size = 128000
capabilities = ["thinking", "tool_use"]
display_name = "GPT subscription"
""".strip() + "\n"


def read_env_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("'").strip('"')
    return ""


def ensure_internal_secret(env_path: Path) -> tuple[str, bool]:
    """Return the control secret and whether this call created it. Never logs the value."""
    from_env = os.environ.get(SECRET_KEY, "").strip()
    from_file = read_env_value(env_path, SECRET_KEY)
    if from_env:
        return from_env, False
    if from_file:
        return from_file, False
    value = secrets.token_urlsafe(32)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if env_path.is_file() and env_path.stat().st_size and not env_path.read_text(encoding="utf-8").endswith("\n"):
        prefix = "\n"
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}{SECRET_KEY}={value}\n")
    return value, True


def write_kimi_config(path: Path, *, dry_run: bool = False) -> dict:
    """Add the bridge provider. Keep every other provider block."""
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = original
    if "[providers.gpt-subscription]" not in text or 'base_url = "http://127.0.0.1:8000/v1"' not in text:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + KIMI_BLOCK
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith("default_model"):
            lines.append('default_model = "gpt-subscription"')
            replaced = True
        else:
            lines.append(line)
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    if not replaced:
        text = 'default_model = "gpt-subscription"\n\n' + text
    written = text != original
    if written and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {
        "path": str(path),
        "written": written,
        "dry_run": dry_run,
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key": "local",
        "model": "gpt-subscription",
    }


def kimi_config_path() -> Path:
    return Path.home() / ".kimi-code" / "config.toml"


def backup_profiles(home: Path) -> dict:
    source = home / "data" / "profiles"
    if not source.is_dir():
        return {"copied": False, "reason": "no profiles folder"}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    dest = home / "data" / "backups" / stamp
    shutil.copytree(source, dest)
    return {"copied": True, "path": str(dest)}


def failure_snapshot(log_dir: Path) -> dict:
    folder = log_dir / "failures"
    if not folder.is_dir():
        return {"count": 0, "latest": []}
    files = [path for path in folder.iterdir() if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return {"count": len(files), "latest": [path.name for path in files[:5]]}
