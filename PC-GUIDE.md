# Put gpt-bridge on your PC

Adrian is the sole owner. This guide is the whole run. The program is already built. Your computer still has to show the window and you still have to sign in. Do not clone GitHub. Do not use WSL. Do not type the password into Git Bash, into this chat, or into the dashboard. Do not send the control secret to anyone. Do not start a tunnel until night-check, the audit, and the 401 check have all passed.

Use Git Bash on the Windows desktop. Open the Start menu, type Git Bash, and open that black window. Do not open Command Prompt, PowerShell, or an Ubuntu app.

## 1. Download

The pass line for this step is that `ls` prints `Makefile`, `scripts/night-check.sh`, and `scripts/dashboard-audit.sh`.

```bash
python3 --version
mkdir -p gpt-bridge
cd gpt-bridge
curl -fL "https://files.manuscdn.com/user_upload_by_module/session_file/310519664075273319/kXDaTUKfPmRwYMcr.tgz" -o gpt-bridge-pc.tgz
tar -xzf gpt-bridge-pc.tgz
rm gpt-bridge-pc.tgz
ls Makefile scripts/night-check.sh scripts/dashboard-audit.sh
```

If `python3 --version` fails and `python --version` works, make a shim in that same window and start the download again:

```bash
mkdir -p "$HOME/bin"
printf '%s\n' '#!/usr/bin/env bash' 'exec python "$@"' > "$HOME/bin/python3"
chmod +x "$HOME/bin/python3"
export PATH="$HOME/bin:$PATH"
python3 --version
```

If `python --version` also fails, install Python 3 from python.org, tick Add python.exe to PATH, close Git Bash, open it again, and start at the top. If `curl` or `tar` is missing, you are not in Git Bash.

You do not install Playwright by hand. The next script does that.

## 2. Start normal Chrome, then night-check

The pass line is `NIGHT-CHECK PASSED` followed by `serve is still running so you can keep using it. pid` and a number.

Close all ordinary Chrome windows first. This bridge uses a separate Chrome profile so it cannot corrupt or lock your everyday Chrome profile. In the first Git Bash window, run:

```bash
cd ~/gpt-bridge
if [[ ! -f .env ]]; then cp .env.example .env; fi
if grep -q '^GPT_BRIDGE_BROWSER_MODE=' .env; then sed -i 's/^GPT_BRIDGE_BROWSER_MODE=.*/GPT_BRIDGE_BROWSER_MODE=attach/' .env; else echo 'GPT_BRIDGE_BROWSER_MODE=attach' >> .env; fi
if grep -q '^GPT_BRIDGE_CDP_URL=' .env; then sed -i 's#^GPT_BRIDGE_CDP_URL=.*#GPT_BRIDGE_CDP_URL=http://127.0.0.1:9333#' .env; else echo 'GPT_BRIDGE_CDP_URL=http://127.0.0.1:9333' >> .env; fi
bash scripts/start-normal-chrome.sh
```

The pass line is:

```text
NORMAL CHROME READY: http://127.0.0.1:9333
```

This is your installed Google Chrome executable, not Playwright's bundled Chromium. It is visible, uses a separate bridge profile, and is reachable only from this PC. Port 9222 remains closed. Leave this Chrome window open. Open a second Git Bash window and run:

```bash
cd ~/gpt-bridge
bash scripts/night-check.sh
```

The script creates a Python folder, installs the packages, and downloads Playwright's Chromium. Leave the window open. The first lines will be `step 1: install`. Pip can print a lot. That is not a failure.

Then it prints:

```text
step 2: login
A Chromium window will open. Sign in yourself in that window.
Do not type the password into this terminal.
Do not press Enter yet. Wait until this terminal prints Logged in. Then press Enter once.
```

A normal Chrome window from the first step is already open. Click that window so it is in front. If it shows ChatGPT's login page, sign in there. If it is already signed in, wait for the terminal to detect it.

If a cookie bar covers the page, click Accept. If the page says Log in, click Log in. Click the email box, type your email, and click Continue. Click the password box, type the password, and click Continue. If ChatGPT asks for a code, type that code in the Chromium window. Stop clicking when the message box at the bottom is visible and you can click inside it. Do not pick a model yet. Do not press Enter in Git Bash yet.

The script sees the message box by itself. Wait until Git Bash prints:

```text
Logged in. Profile:
Storage state:
Pick the model in the browser if you want, then press Enter to close it.
```

Click the Git Bash window. Press Enter once. The Chromium window closes. That is expected. The script opens the window again for the proof, then again for the server. Do not close those later windows.

A passing run then prints these markers, in this order. Other lines, including JSON and a pong reply, appear between them.

```text
step 3: prove
step 3b: control secret
Do not start a tunnel until this secret exists and the dashboard Internal secret field is saved.
CONTROL SECRET CREATED. Paste this into the dashboard Internal secret field.
Do not start a tunnel until that field is saved. Do not share this value.
step 4: serve
step 5: health logged_in
step 6: debug/break
step 7: completion
step 8: log line
step 9: forced_broken false
NIGHT-CHECK PASSED
serve is still running so you can keep using it. pid
The one-time secret print is gone from disk. The value remains in .env only. Shred .env if you retire this machine.
```

The prove reply must contain the word pong. The health JSON must contain `"logged_in": true` and `"internal_secret_set": true`. The break JSON must contain `"broken": true`. The step 8 log text must contain `active chat unhealthy before send` and `rotated to`. The last health JSON must contain `"forced_broken": false`.

If the secret already existed, the secret block says `CONTROL SECRET already set. It was not printed again.` instead of printing the value. Copy it from the `GPT_BRIDGE_INTERNAL_SECRET` line in `.env` on that computer. Do not send it to chat.

If any line starts with `NIGHT-CHECK FAILED`, stop. Do not start a tunnel. Send that line, not the secret.

## 3. Dashboard audit

The pass line is `AUDIT PASSED`. These lines must appear above it, in this order:

```text
PASS: Banner ChatGPT Logged In
PASS: Connection Live chip
PASS: Connection yes true ready false
PASS: Proof logged_in true
PASS: Every required button is visible
PASS: Owner Adrian
PASS: Use account POST /v1/accounts/use ok
PASS: Chat switch POST /v1/chats/switch ok
PASS: Model pick POST /v1/browser-models/select ok
AUDIT PASSED
```

Open `http://127.0.0.1:8000/dashboard` in any browser on that same computer. Do not use the public page for the buttons. The owner line says `Adrian is the sole owner of this bridge.` The banner says `ChatGPT Logged In` only after the secret is saved. Paste the secret into Internal secret and click Save, or let the audit do that paste for you. Then, in the same Git Bash folder:

```bash
bash scripts/dashboard-audit.sh
```

The audit opens the local page, reads the secret from `.env` without printing it, and clicks the controls. It drives the Chromium window that night-check left open. Do not close that window. Do not click Add account. The Use account button is `Adrian (open)`.

If a line starts with `AUDIT FAILED`, stop. The proof line on the page is the reason. Do not send the secret.

## 4. The 401 gate

Do this before any tunnel. The pass line is `401`.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"
```

If it prints anything except `401`, stop. Do not run `cloudflared`. The same call with the secret header is allowed. Completions still use only the word `local`. Do not share a tunnel address.

Also confirm the server refuses a public bind. The pass line contains `refusing to bind outside localhost`.

```bash
python -m gpt_bridge serve --host 0.0.0.0
```

## 5. Kimi

The pass line is a file path, then `written` or `already set`.

```bash
python -m gpt_bridge kimi
```

That writes base `http://127.0.0.1:8000/v1`, key `local`, and model `gpt-subscription` into the Kimi settings file. Other providers stay.

## 6. Watch

The pass line is `serve already running on 127.0.0.1:8000` and `watching existing pid`.

```bash
make watch
```

If `make` is missing:

```bash
bash scripts/watchdog.sh
```

Night-check already started the server. Watch attaches to that process. It does not start a second copy. Leave Git Bash open. Closing it closes Playwright. The computer must stay on.

## After the six pass lines

Kimi Code talks to `http://127.0.0.1:8000/v1` with key `local` and model `gpt-subscription`. Each request lands in the signed-in Chromium window. Adrian is the owner. The open account button stays `Adrian (open)`.

Do not click Add account unless you want a second paid login. A new label opens an empty window and you must sign in again. Do not open port 9222. Do not run Artemis beside this server. Telegram is optional and comes only after these six lines have passed.
