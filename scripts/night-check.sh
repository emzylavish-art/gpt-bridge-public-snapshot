#!/usr/bin/env bash
# Mandatory first run on the PC that can show a Chromium window.
# This session cannot run it: there is no display, and the developer signs in.
# The script does not type a password.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p logs

serve_pid=""

fail() {
  echo "NIGHT-CHECK FAILED: $1" >&2
  if [[ -n "$serve_pid" ]]; then
    kill "$serve_pid" >/dev/null 2>&1 || true
    wait "$serve_pid" >/dev/null 2>&1 || true
  fi
  rm -f logs/night-check-secret
  exit 1
}

echo "step 1: install"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    python3() { python "$@"; }
  elif command -v py >/dev/null 2>&1; then
    python3() { py -3 "$@"; }
  else
    fail "step 1 install could not find python3"
  fi
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv || fail "step 1 install could not create .venv"
fi
# shellcheck disable=SC1091
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate || fail "step 1 install could not activate .venv"
elif [[ -f .venv/Scripts/activate ]]; then
  source .venv/Scripts/activate || fail "step 1 install could not activate .venv"
else
  fail "step 1 install could not activate .venv"
fi
python -m pip install -r requirements.txt || fail "step 1 install requirements.txt"
python -m pip install -e . --no-deps || fail "step 1 install package"
python -m playwright install chromium || fail "step 1 install chromium"

if [[ ! -t 0 ]]; then
  fail "step 2 login needs a terminal so you can sign in and press Enter"
fi

if [[ "$(uname -s)" == "Linux" && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && ! -S /tmp/.X11-unix/X0 ]]; then
  fail "step 2 login needs a display. This shell cannot open the Chromium sign-in window. A separate browser-tool session does not count."
fi

export GPT_BRIDGE_HEADLESS=0

echo "step 2: login"
browser=$(python -c "from gpt_bridge.config import load_settings; print(load_settings().channel or 'playwright-chromium')")
echo "Opening ${browser}. Sign in yourself in that window."
echo "Do not click Continue with Google if the page says this browser may not be secure."
echo "Close that Google tab. Use the email box on the ChatGPT page. A code from your phone is fine."
echo "Do not type the password into this terminal."
echo "Do not press Enter yet. Wait until this terminal prints Logged in. Then press Enter once."
python -m gpt_bridge login || fail "step 2 login"

echo "step 3: prove"
if ! prove_reply=$(python -m gpt_bridge prove "Reply with the single word pong"); then
  fail "step 3 prove; serve was not started because the authenticated-tab proof failed"
fi
printf '%s\n' "$prove_reply"
case "$prove_reply" in
  *pong*|*Pong*|*PONG*) ;;
  *) fail "step 3 prove did not reply pong" ;;
esac

echo "step 3b: control secret"
echo "Do not start a tunnel until this secret exists and the dashboard Internal secret field is saved."
created=$(python - <<'PY'
from pathlib import Path
from gpt_bridge.ops import ensure_internal_secret
value, created = ensure_internal_secret(Path(".env"))
path = Path("logs/night-check-secret")
path.write_text(value, encoding="utf-8")
path.chmod(0o600)
print("created" if created else "existing")
PY
) || fail "step 3b control secret"
secret=$(cat logs/night-check-secret)
export GPT_BRIDGE_INTERNAL_SECRET="$secret"
if [[ "$created" == "created" ]]; then
  echo "CONTROL SECRET CREATED. Paste this into the dashboard Internal secret field."
  echo "Do not start a tunnel until that field is saved. Do not share this value."
  echo "$secret"
else
  echo "CONTROL SECRET already set. It was not printed again."
  echo "Do not start a tunnel until the dashboard Internal secret field matches it."
fi

echo "step 4: serve"
python -m gpt_bridge serve > logs/night-check-serve.log 2>&1 &
serve_pid=$!
echo "$serve_pid" > logs/night-check.pid
ready=0
for _ in $(seq 1 180); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$serve_pid" >/dev/null 2>&1; then
    fail "step 4 serve exited before /health answered"
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  fail "step 4 serve did not answer /health"
fi

echo "step 5: health logged_in"
curl -sf http://127.0.0.1:8000/health > logs/night-check-health.json || fail "step 5 health did not answer"
python - <<'PY' || fail "step 5 health logged_in is not true"
import json
body = json.load(open("logs/night-check-health.json", encoding="utf-8"))
print(json.dumps(body))
if body.get("logged_in") is not True:
    raise SystemExit(1)
if body.get("internal_secret_set") is not True:
    raise SystemExit("internal secret was not loaded")
PY

echo "step 6: debug/break"
curl -sf -X POST http://127.0.0.1:8000/v1/debug/break \
  -H "Authorization: Bearer local" \
  -H "X-GPT-Bridge-Secret: ${secret}" \
  > logs/night-check-break.json || fail "step 6 debug/break"
python - <<'PY' || fail "step 6 debug/break did not mark the chat"
import json
body = json.load(open("logs/night-check-break.json", encoding="utf-8"))
print(json.dumps(body))
if body.get("broken") is not True:
    raise SystemExit(1)
PY

offset=0
if [[ -f logs/bridge.log ]]; then
  offset=$(wc -c < logs/bridge.log)
fi

echo "step 7: completion"
completion_code=$(curl -sS -o logs/night-check-completion.json -w "%{http_code}" --max-time 300 \
  -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer local" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-subscription","messages":[{"role":"user","content":"Reply with the single word pong"}]}') \
  || fail "step 7 completion did not answer"
if [[ "$completion_code" != "200" ]]; then
  echo "HTTP $completion_code" >&2
  cat logs/night-check-completion.json >&2 || true
  fail "step 7 completion returned HTTP $completion_code"
fi
python - <<'PY' || fail "step 7 completion did not answer"
import json
body = json.load(open("logs/night-check-completion.json", encoding="utf-8"))
choices = body.get("choices") or []
content = ""
if choices:
    content = ((choices[0].get("message") or {}).get("content") or "")
print(content)
if not str(content).strip():
    raise SystemExit(1)
PY

echo "step 8: log line"
python - "$offset" <<'PY' || fail "step 8 log does not contain active chat unhealthy before send"
import sys
offset = int(sys.argv[1])
raw = open("logs/bridge.log", "rb").read()
chunk = raw[offset:].decode("utf-8", "replace")
print(chunk)
if "active chat unhealthy before send" not in chunk:
    raise SystemExit(1)
if "rotated to " not in chunk:
    raise SystemExit(2)
PY

echo "step 9: forced_broken false"
curl -sf http://127.0.0.1:8000/health > logs/night-check-health-after.json || fail "step 9 health did not answer"
python - <<'PY' || fail "step 9 forced_broken is not false"
import json
body = json.load(open("logs/night-check-health-after.json", encoding="utf-8"))
print(json.dumps(body))
if body.get("forced_broken") is not False:
    raise SystemExit(1)
PY

echo "NIGHT-CHECK PASSED"
echo "serve is still running so you can keep using it. pid ${serve_pid}"
echo "stop it with: kill ${serve_pid}"
rm -f logs/night-check-secret
echo "The one-time secret print is gone from disk. The value remains in .env only. Shred .env if you retire this machine."
