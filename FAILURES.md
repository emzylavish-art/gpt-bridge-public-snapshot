# When the bridge stops

The process usually stays up. A stop means this request will not finish, or a machine other than this one cannot reach it. Look at `logs/bridge.log` and `GET /health` before changing anything.

## Login

Stops when the composer never becomes usable. That is an auth URL, a missing browser window, a deleted `data/profile`, or 10 minutes with no sign-in (`GPT_BRIDGE_LOGIN_TIMEOUT_S`, default 600). `login` and `prove` print `timed out waiting for ChatGPT login`. A live request returns HTTP 503. Login is not a chat failure, so rotation will not fix it.

`/health` with `logged_in: false` is the same wall. Headless mode often cannot pass it. If Google rejects the bundled browser, set `GPT_BRIDGE_CHANNEL=chrome` and run `login` again. A request that arrives while you are signing in waits. It does not open a new chat.

## Selector breakage

Stops when the page no longer matches the lists at the top of `src/gpt_bridge/playwright_backend.py`. The usual last reasons are `composer missing`, `send did not start`, `empty reply`, `stalled generation`, `timeout`, or `new chat did not show a composer`. Screenshots land in `logs/failures/`.

A missing New Chat button is not fatal by itself. Rotation falls back to opening `https://chatgpt.com/`. A changed assistant marker is fatal: the reply looks empty, retries burn, and the request dies. A changed Stop button can look like a stall even while text is still arriving. Edit the selector lists. Do not add a stealth layer.

## Forced-break check

`POST /v1/debug/break` with `Authorization: Bearer local` only marks the active chat broken. It does not exit. The next completion must rotate, resend the full prompt, and answer.

The check passed only if `logs/bridge.log` contains `active chat unhealthy before send` and `rotated to `, `data/session.json` says `active chat unhealthy before send`, and `/health` is `forced_broken: false` after that reply. It failed if the break returns 401, the next completion is 502, or `forced_broken` is still true after a successful reply. Leaving it broken with no following request is expected. That is not a failed recovery.

## Retry cap

Default `GPT_BRIDGE_MAX_RETRIES` is 2. A healthy chat gets one send plus two rotate-and-resend attempts. The request then returns HTTP 502 and the log says `chat rotation exhausted`. The server keeps running. Kimi Code stops that step.

Account limits do not heal by opening a chat. `too many requests`, `you've reached our limit`, and `unusual activity` still rotate, then die at the cap. Raising the cap only repeats the same wall. A 502 on one request does not block the next request.

## Localhost-only bind

Default bind is `127.0.0.1:8000`. Another phone, computer, or remote VS Code window cannot connect. That refusal is the design, not a crash. Kimi Code must use `http://127.0.0.1:8000/v1` on this machine. A LAN address, `https`, or a missing `/v1` looks like the bridge is down.

`connection refused` means `serve` is not running, or a second process lost the port. A 401 means the placeholder key does not match `GPT_BRIDGE_API_KEY`. The browser is fine. Do not set the host to `0.0.0.0`. That puts the logged-in session behind a placeholder key.

`python -m gpt_bridge serve --host 0.0.0.0` now exits with `refusing to bind outside localhost`. That is a stop, not a warning.

## Test client warning

A checkout that installed `requirements-dev.txt`, including `httpx2`, runs the suite with no warning. The old warning was Starlette saying `TestClient` wants `httpx2` instead of `httpx`. That warning is from the test client, not from `serve`. If it appears, install `httpx2`. Do not treat it as a bridge failure, and do not ignore it in a fresh test run.

## Log cap

`logs/bridge.log` rotates at 1,000,000 bytes and keeps 3 backups. A full log is not a stop. The newest lines stay in `bridge.log`.

## Error body

HTTP 502 and 503 carry the reason in `detail`, `reason`, and `error.message`. HTTP 503 uses `error.code` `login_required`. HTTP 502 uses `chat_failure`. Kimi Code can read `error.message` and decide the next step. A 502 on one request does not stop the process.

## Dashboard and secret

`GET /dashboard-data` without `Authorization: Bearer local` is 401. If `GPT_BRIDGE_INTERNAL_SECRET` is set, control routes also 401 with `missing internal secret` unless `X-GPT-Bridge-Secret` matches. Completions do not require that header. Kimi Code's OpenAI provider cannot send it, and requiring it would stop every coding task.

A Vercel page cannot prove the bridge by itself. `https://` pages are often blocked from calling `http://127.0.0.1`. Open `http://127.0.0.1:8000/dashboard` on this machine when that happens. The Vercel guard refuses a localhost upstream on purpose.

## Accounts

`GET /v1/accounts` lists labels only. `POST /v1/accounts/add` and `POST /v1/accounts/use` take `{ "label": "work" }`. A `password` field is rejected. The page has no password box. The registry at `data/profiles/registry.json` stores labels. Cookies stay in that account's folder.

A click while a completion holds the lock returns HTTP 409 `completion in flight`. It does not wait and then switch. An unknown label returns HTTP 404. A bad label returns HTTP 400. Neither writes a profile.

New chat for the open account uses the same rotate path as an automatic failure. A sidebar button uses the existing chat-switch path and holds that chat for the next send. There is no second rotator.

## Telegram

No bot token, or a token without a colon, is HTTP 400 on `POST /v1/telegram/config`. Buttons do nothing until `/start` has been captured and `GET /v1/telegram/status` shows `chat_id`. A bridge-down note can only be sent by the open dashboard, because a dead process cannot speak.
