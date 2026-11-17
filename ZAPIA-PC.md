# For Zapia: put this on the PC

Do not connect to the Manus browser. Port 9222 is not exposed, and it must stay closed. That browser cannot be driven by Kimi or by an outside Playwright script.

Run this project on the computer that will show the ChatGPT window. Playwright starts its own Chromium there. The person signs in in that window. The password is not typed by the script.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pip install -e . --no-deps
python -m gpt_bridge login
python -m gpt_bridge prove "Reply with the single word pong."
python -m gpt_bridge serve
```

Leave `serve` running. It listens only on `127.0.0.1:8000`. It refuses `--host 0.0.0.0`.

On that same computer, open `http://127.0.0.1:8000/dashboard`. The key for Kimi Code is `local`. The base URL is `http://127.0.0.1:8000/v1`. Use `kimi.config.example.toml`.

Do not open Chrome’s debug port. Do not point Kimi at this chat’s browser. A phone cannot host the window. Vercel cannot call `127.0.0.1`.
