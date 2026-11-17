# gpt-bridge handoff

Copy this whole file. Built means the code is on main and tested. Live means it was fetched from the public URL. A documented command is not a live ChatGPT proof.

Repo: https://github.com/emzylavish-art/gpt-bridge
Branch: main
Adrian is the sole owner. The PC copy is the public snapshot named below. Do not clone.
Public snapshot: https://files.manuscdn.com/user_upload_by_module/session_file/310519664075273319/kXDaTUKfPmRwYMcr.tgz
Public page: https://gpt-bridge-eight.vercel.app
The public page and dashboard/index.html both say Adrian is the sole owner. Do not clone the private repo. Do not use WSL for night-check.
Vercel project: gpt-bridge only. oak-bridge-capital was not opened.
Tests, run at the time of this handoff: 33 passed, no warning. Google rejected Playwright Chromium and also rejected the launched automated Chrome profile with "Couldn't sign you in". The bridge now has an explicit attach mode: the PC starts the installed Chrome executable with a separate bridge profile on localhost CDP port 9333, and Playwright connects to that visible normal-Chrome window. The login waiter selects the signed-in ChatGPT tab and checks URL plus DOM markers. The CLI prove command now sends on the already-open authenticated tab instead of rotating/navigating a historical chat first; failures include the active URL, and night-check explicitly says serve was not started when prove fails. Port 9222 remains closed. The normal-Chrome attach path has not been run on Adrian's PC.
Working tree: clean, matching origin/main.

## What it is

A localhost OpenAI-compatible FastAPI service. One visible Playwright Chromium window drives one ChatGPT account at a time. The person at the computer signs in and types the password in that window. The bridge stores labels and cookies in profile folders. It does not store passwords. There is no password field.

On the computer that runs serve:

- Base: http://127.0.0.1:8000/v1
- Key: the word local
- Model: gpt-subscription

serve refuses every host except 127.0.0.1, localhost, and ::1. Port 9222 stays closed.

## What was built

The FastAPI worker, the Playwright backend, the session lock, and the account registry. One folder per label under data/profiles. A switch during a send returns HTTP 409. A failed send switches chat inside the same request and stops at two tries. Models come from the menu Playwright sees and are reapplied after a rotation. A forced break marks the chat. The next completion logs "active chat unhealthy before send", rotates, answers, and leaves forced_broken false.

Telegram relay code is ready, with Restart browser, Force break, and Open dashboard. No BotFather token was created. make night-check installs, waits for a human sign-in, proves a reply containing pong, starts serve, marks the chat, and requires the next completion to rotate. It stops at the first broken step.

python -m gpt_bridge secret and night-check create GPT_BRIDGE_INTERNAL_SECRET in .env if it is missing and print it once. Completions still use the key local. Control routes require the secret header only after the secret exists. python -m gpt_bridge kimi writes the three client values into ~/.kimi-code/config.toml and keeps other providers. --dry-run does not write the file. make watch restarts serve after a crash. python -m gpt_bridge backup copies profiles. bridge.log rotates. HTTP 502 and 503 bodies include reason and error.code.

API Anything is a sibling checkout, not imported. Its probe was not run against ChatGPT. Zapia is closed as a host. Artemis is not cloned. Do not start it beside serve, because it also uses port 8000.

## Dashboard

One HTML file, copied to dashboard/index.html. No framework. vercel.json is unchanged: no rewrites, no build step.

The page is a sidebar app. Clicking a rail item switches the main panel. On a phone, Menu opens that rail. The order is Getting Started, Connection, Accounts, Browser Actions, Models, Telegram, API Reference, Logs. Each panel has a plain-language guide and the working controls.

Visual system, checked on the live URL at 1440 by 900 and 390 by 844:

- Ground #07060C. Action gold #EFCA7C. Focus ring #FFE3A3.
- Dark text on the gold button is 11.8 to 1. Gold labels on the page are 10.2 to 1. Both clear 4.5.
- Keyboard focus draws the light ring with a dark gap.
- Every button and field is at least 48 pixels. The sign-in button measured 50 pixels tall. Menu measured 50 by 68.
- Neither width falls back to a white page.

## Endpoints

GET /health, GET /v1/health, GET /, GET /dashboard, GET /dashboard-data, GET /v1/session, POST /v1/session/login, POST /v1/session/logout, POST /v1/session/restart, GET /v1/accounts, POST /v1/accounts/add, POST /v1/accounts/use, GET /v1/chats, POST /v1/chats/new, POST /v1/chats/switch, GET /v1/browser-models, POST /v1/browser-models/select, GET /v1/models, POST /v1/debug/break, POST /v1/chat/completions, POST /v1/telegram/config, GET /v1/telegram/status, POST /v1/telegram/poll, POST /v1/kimi/install.

## Commands

make setup, make test, make login, make prove, make serve, make night-check, make watch. Also python -m gpt_bridge login, logout, prove, serve, secret, backup, kimi, and kimi --dry-run.

## Decks

The visual-upgrade deck records the earlier brand pass. The live dashboard deck records the sidebar, the gold system, the contrast and focus fixes, and the 1440 and 390 checks.

## Checked here

Unit tests were run on this machine. ChatGPT was opened in Chromium here earlier. It was not signed in. The page said Log in. No password was typed. No session was saved. Night-check and the dashboard audit have not run on the computer that will show the window.

## Not done

No live sign-in through this bridge. No secret generated on the computer that will show the window. No tunnel. Do not run cloudflared until a control route without the secret header returns 401. No Telegram token. API Anything probe not run. Artemis not started. oak-bridge-capital not touched.

## The only remaining work

Everything that can be built from this session is built. Do these on a computer with a screen, in order.

1. Download the public snapshot. Do not clone. On Windows, use Git Bash. Do not use WSL.
2. cd gpt-bridge
3. bash scripts/night-check.sh
4. Sign in yourself in the Chromium window. Press Enter only after the terminal prints Logged in.
5. Paste the secret into Internal secret and click Save. Then run bash scripts/dashboard-audit.sh. It must print AUDIT PASSED.
6. Confirm the secret before any tunnel. It must print 401. If it does not, stop.

curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"

7. python -m gpt_bridge kimi
8. make watch. If serve is already running, watch attaches. It does not start a second copy.

Optional, later: create a Telegram bot with BotFather and paste the token on the dashboard. Run the API Anything probe read-only. Leave Artemis blocked until adb devices shows a real device.
