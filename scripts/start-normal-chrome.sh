#!/usr/bin/env bash
set -euo pipefail

port="${GPT_BRIDGE_CDP_PORT:-9333}"
profile="${GPT_BRIDGE_CHROME_USER_DATA_DIR:-$HOME/.gpt-bridge-chrome}"
url="${GPT_BRIDGE_CHATGPT_URL:-https://chatgpt.com/}"

if [[ "$port" == "9222" ]]; then
  echo "REFUSING port 9222; use 9333 or another localhost-only port" >&2
  exit 1
fi

chrome=""
for candidate in \
  "/c/Program Files/Google/Chrome/Application/chrome.exe" \
  "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
  "$LOCALAPPDATA/Google/Chrome/Application/chrome.exe"; do
  if [[ -n "${candidate:-}" && -f "$candidate" ]]; then
    chrome="$candidate"
    break
  fi
done

if [[ -z "$chrome" ]]; then
  echo "Chrome executable not found. Install Google Chrome, then rerun." >&2
  exit 1
fi

mkdir -p "$profile"
echo "Starting normal Chrome on localhost CDP port $port."
echo "Chrome profile: $profile"
"$chrome" --remote-debugging-address=127.0.0.1 --remote-debugging-port="$port" --user-data-dir="$profile" --no-first-run --no-default-browser-check "$url" >/tmp/gpt-bridge-chrome.log 2>&1 &
echo $! > /tmp/gpt-bridge-chrome.pid
sleep 2
curl -fsS "http://127.0.0.1:$port/json/version" >/dev/null
echo "NORMAL CHROME READY: http://127.0.0.1:$port"
echo "Leave this Chrome window open. Start night-check in another Git Bash window."
