#!/usr/bin/env bash
# Restart serve after a crash and tell Telegram if a bot is already linked.
# Stops after 5 crashes so a broken loop does not run all night.
set -u
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

alert() {
  python - "$1" <<'PY'
import json
import sys
from pathlib import Path
from urllib import request

text = sys.argv[1]
path = Path("data/telegram.json")
if not path.is_file():
    print("telegram not linked; alert skipped")
    raise SystemExit(0)
state = json.loads(path.read_text(encoding="utf-8"))
token = state.get("bot_token") or ""
chat = state.get("chat_id")
if not token or not chat:
    print("telegram not linked; alert skipped")
    raise SystemExit(0)
body = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
req = request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=body,
    headers={"Content-Type": "application/json"},
)
try:
    request.urlopen(req, timeout=20).read()
    print("telegram alert sent")
except Exception as exc:
    print(f"telegram alert failed: {exc.__class__.__name__}")
PY
}

restarts=0
max_restarts=5
if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null; then
  echo "serve already running on 127.0.0.1:8000"
  existing=""
  if [[ -f logs/night-check.pid ]]; then
    existing=$(tr -d '[:space:]' < logs/night-check.pid)
  fi
  if [[ -n "$existing" ]] && kill -0 "$existing" 2>/dev/null; then
    echo "watching existing pid ${existing}"
    while kill -0 "$existing" 2>/dev/null; do
      sleep 2
    done
    echo "existing serve exited; watchdog will start a new one"
  else
    echo "A server is already answering. Not starting a second copy."
    exit 0
  fi
fi
while true; do
  echo "watchdog starting serve"
  python -m gpt_bridge serve
  code=$?
  restarts=$((restarts + 1))
  echo "watchdog: serve exited ${code} (restart ${restarts} of ${max_restarts})"
  alert "gpt-bridge serve exited with code ${code}. Watchdog restart ${restarts} of ${max_restarts}."
  if [[ "$restarts" -ge "$max_restarts" ]]; then
    alert "gpt-bridge watchdog stopped after ${max_restarts} crashes. Serve is not running."
    echo "WATCHDOG STOPPED after ${max_restarts} crashes"
    exit 1
  fi
  sleep 2
done
