#!/usr/bin/env bash
# Read-only probe. It lists candidate requests. It does not learn, call, or write.
# No session is captured beyond this run, and the developer must approve any later learn.
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  echo "PROBE FAILED: $1" >&2
  exit 1
}

echo "API Anything probe is read-only. It does not learn and it does not call."
echo "Review the candidate list yourself before treating any request as an operation."

if ! command -v api-anything >/dev/null 2>&1; then
  fail "api-anything is not installed. On the PC run: npx -y api-anything setup"
fi

capture=$(api-anything capture "https://chatgpt.com/" --example q=example) || fail "capture did not finish"
printf '%s\n' "$capture" | python3 -c '
import json, re, sys
raw = sys.stdin.read()
raw = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{10,}\b", "[redacted]", raw)
raw = re.sub(r"(?i)(authorization|cookie|set-cookie)([\"=: ]+)[^\"\s,}]+", r"\1\2[redacted]", raw)
try:
    body = json.loads(raw)
except json.JSONDecodeError:
    print(raw)
    raise SystemExit(0)
candidates = body.get("candidates") or []
print(json.dumps({"capture": body.get("capture"), "requests": body.get("requests"), "candidates": candidates}, indent=2))
'
echo "Probe finished. No learn and no call were run. Decide by hand whether this traffic is clean enough."
