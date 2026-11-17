#!/usr/bin/env bash
# Fetch the public control page and stop if the old layout is still deployed.
set -euo pipefail

url="https://gpt-bridge-eight.vercel.app"
file=""
if [[ "${1:-}" == "--file" ]]; then
  file="${2:-}"
  if [[ -z "$file" || ! -f "$file" ]]; then
    echo "POST-DEPLOY FAILED: --file needs an existing HTML file" >&2
    exit 1
  fi
elif [[ -n "${1:-}" ]]; then
  url="$1"
fi

tmp=""
if [[ -n "$file" ]]; then
  tmp="$file"
else
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  if ! curl -fsSL "$url" -o "$tmp"; then
    echo "POST-DEPLOY FAILED: could not fetch $url" >&2
    exit 1
  fi
fi

source="$url"
if [[ -n "$file" ]]; then
  source="$file"
fi
python3 - "$tmp" "$source" <<'PY'
import re
import sys
from pathlib import Path

html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
source = sys.argv[2]
headings = re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.I | re.S)
headings = [re.sub(r"<[^>]+>", "", item).strip() for item in headings]
required = [
    "Getting Started",
    "1. Connection",
    "2. Accounts",
    "3. Browser Actions",
    "4. Models",
    "5. Telegram",
    "6. API Reference",
    "7. Logs",
]
old = ["Reach", "Session", "Account and chat", "Proof send"]
missing = [item for item in required if item not in headings]
stale = [item for item in old if item in headings]
if missing or stale or headings[:1] != ["Getting Started"]:
    print(f"POST-DEPLOY FAILED: {source}", file=sys.stderr)
    if headings[:1] != ["Getting Started"]:
        print("Getting Started is not the first section.", file=sys.stderr)
    if missing:
        print("missing: " + ", ".join(missing), file=sys.stderr)
    if stale:
        print("old layout still present: " + ", ".join(stale), file=sys.stderr)
        print("The deploy did not pick up the new page. Stop.", file=sys.stderr)
    raise SystemExit(1)
print("POST-DEPLOY PASSED")
print(source)
print("Getting Started is first.")
print("sections: " + ", ".join(required))
PY
