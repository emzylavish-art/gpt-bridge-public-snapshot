#!/usr/bin/env bash
# Run only after NIGHT-CHECK PASSED. This does not type a password or print the secret.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f .venv/Scripts/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/Scripts/activate
else
  echo "AUDIT FAILED: no virtualenv. Run make night-check first." >&2
  exit 1
fi
python scripts/dashboard_audit.py
