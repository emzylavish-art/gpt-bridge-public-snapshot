# Dashboard plan

This is the contract for the control page. A button that is not listed here does not exist. A result that is not listed here has not been proved.

## What is already true

The page file is `dashboard/index.html`. The bridge serves that same file at `http://127.0.0.1:8000/dashboard` when `serve` is running on the computer that shows ChatGPT. The Vercel copy is the same file. It is not a second bridge.

Vercel account in use for this deploy: team `bridge-point2`, user `emzylavish-9373`. The new project must be its own project. It must not be created inside `oak-bridge-capital` and it must not change that project's settings, domains, or environment variables.

The API key shown on the page is the public string `local`. Copying it does not open ChatGPT. It only matches `GPT_BRIDGE_API_KEY` when that value is still the default.

Zapia's Chrome session is not this bridge. A `pong` from Zapia does not make any button on this page work.

## What this page can reach

If the page is opened at `http://127.0.0.1:8000/dashboard` on the computer running `serve`, every button below can call the bridge.

If the page is opened on a `vercel.app` host and the bridge URL is `http://127.0.0.1:8000`, the browser blocks the call. The page must say that in the Reach box. That is a closed fact, not a bug to hide. The key can still be copied. The buttons cannot drive Zapia's Chrome, and they cannot drive a bridge on a private laptop.

Port 9222 stays closed. The page never asks for a Chrome debug port.

## Connection fields

Bridge URL. Saved in this browser as `gpt_bridge_url`. Default `http://127.0.0.1:8000`. Trailing slash is removed before every call.

Internal secret. Saved as `gpt_bridge_secret`. Sent as `X-GPT-Bridge-Secret` only when non-empty. Leave it empty unless `GPT_BRIDGE_INTERNAL_SECRET` is set. Completions do not require this header. Control routes do, when the secret is set.

API base. Shown as `{bridge}/v1`. Copy button copies that string. This is the base a tool uses. Kimi is not required.

API key. The readonly value is `local`. Copy button copies `local` and the proof line says `Copied key local`.

Save writes both stored fields and polls immediately.

## Poll

Every five seconds, and once on load, the page calls `GET /dashboard-data` with `Authorization: Bearer local` and the secret header when set.

Success body used by the page:

- `health.timestamp` fills Health time
- `health.browser` fills Browser
- `health.forced_broken` fills Forced broken
- `health.healthy` fills Healthy
- `session.logged_in` fills Logged in
- `session.chat_url` fills Chat
- `rotations` fills the rotation list, newest first, as `ts reason url`

Proof when logged in: `GET /dashboard-data shows logged_in true.`

Proof when logged out: `GET /dashboard-data shows logged_in false. Sign in in the browser window, then press Login.`

Two failed polls in a row set Browser to `down`. If this browser already has a Telegram token and chat ID from an earlier successful verify, the page sends one Telegram message `bridge down: {error}`. The token is not in the HTML file. A dead bridge cannot send that message itself.

The page also calls `GET /v1/telegram/status` on each successful poll. A Telegram failure does not erase the session card.

`GET /health` is public and includes `timestamp`. The page uses `/dashboard-data` because that one call has session, health, and rotations. `/health` remains the no-key check from a terminal.

## Account and chat buttons

Each button uses `Authorization: Bearer local`. If the secret is saved, it sends that too. The proof line becomes `{path} ok` after a 2xx body, then the page polls again.

Login. `POST /v1/session/login`. Empty body. Opens the login page in the bridge's Chromium. The person types the password in that window. The page never asks for the password. Success is the later poll showing `logged_in true`, not the button press alone.

Logout. `POST /v1/session/logout`. Clears the saved ChatGPT login so another account can be typed in that same window. Do not press this unless a switch of account is intended.

Restart browser. `POST /v1/session/restart`. Stops and starts the bridge Chromium. It does not log out by itself.

Force break. `POST /v1/debug/break`. Expected body includes `broken: true`. The next completion must still return a reply, the bridge log must contain `active chat unhealthy before send`, and the following poll must show `forced_broken false`.

New chat. `POST /v1/chats/new`. Expected body has `chat_url` starting with `https://chatgpt.com/c/`.

List chats. `GET /v1/chats`. The page prints each `title` and `url`. An empty list is a result, not a crash.

Chat switch. `POST /v1/chats/switch` with JSON `{"url":"..."}`. The URL must be `https://chatgpt.com/c/...` or `https://chatgpt.com/uc/...`. Any other host is HTTP 400. The proof of a good switch is the next poll showing that same `chat_url`.

## Proof send

Send pong. `POST /v1/chat/completions` with `{"model":"gpt-subscription","messages":[{"role":"user","content":"Reply with the single word pong."}]}`. The page prints `choices[0].message.content`. A useful reply contains `pong`. HTTP 503 means the composer is not logged in. HTTP 502 means the send failed. This call does not use the internal secret header, because tool clients cannot send that header.

## Telegram

Verify token. `POST /v1/telegram/config` with `{"bot_token":"...","dashboard_url":"<this page url>"}`. Success shows `username` and `start_url`. The token must not appear in the response. The page stores the token only in this browser's local storage so a later bridge-down note can be sent. Skip this until a real BotFather token exists. Do not invent one.

Poll now. `POST /v1/telegram/poll`. After the person presses Start in Telegram, success shows `chat_id`.

Restart and Force break from Telegram are handled by the bridge poller, not by this page. This page does not need a second copy of those buttons for Telegram.

## Last payload

Every call prints the path, HTTP status, and JSON. That is the record when a button fails. Do not replace it with a summary that hides the status.

## Auth failures

No `Authorization` header on `/dashboard-data` is 401 `invalid api key`.

Wrong bearer is 401 `invalid api key`.

Secret set on the bridge, header missing or wrong, is 401 `missing internal secret`.

`/health` and `/v1/chat/completions` do not use the secret header. `/v1/models` uses the bearer key only.

## Deploy

Deploy only the `dashboard/` folder as a new Vercel project named `gpt-bridge-control` on team `bridge-point2`. Framework preset None. No rewrites. Do not set `BRIDGE_UPSTREAM` to `http://127.0.0.1:8000`. The guard function already refuses a localhost upstream.

Environment variables are not required for the static page. Do not put a Telegram bot token or a ChatGPT password in Vercel env to make the buttons work. Those buttons talk to the bridge, and the bridge is not on Vercel.

After deploy, the proof is the public URL opening this same page, the Reach box saying the public page cannot call `127.0.0.1`, and the Copy key button still showing `local`.

## Closed

These are not remaining tasks:

- Another visual theme. The page stays plain.
- A public bind of the bridge. `serve --host 0.0.0.0` must keep exiting with `refusing to bind outside localhost`.
- Attaching Playwright to the Manus or Zapia Chrome on port 9222.
- Pretending Zapia's `pong` means this page is connected.
- Editing `oak-bridge-capital`.
- Inventing a Telegram bot.

## Still required before a button can succeed

`python -m gpt_bridge serve` must be running on a computer that can show Chromium, and the page must be opened on that same computer, or the bridge URL must be a host the page can actually reach. Until then, Copy key works and the other buttons fail in the open. That failure is the correct proof that the page is honest.
