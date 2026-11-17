.PHONY: setup test login prove serve night-check watch audit

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements-dev.txt && pip install -e . --no-deps && python -m playwright install chromium

test:
	PYTHONPATH=src python3 -m pytest -q

login:
	PYTHONPATH=src python3 -m gpt_bridge login

prove:
	PYTHONPATH=src python3 -m gpt_bridge prove "$(PROMPT)"

serve:
	PYTHONPATH=src python3 -m gpt_bridge serve

night-check:
	bash scripts/night-check.sh

watch:
	bash scripts/watchdog.sh

audit:
	bash scripts/dashboard-audit.sh
