# Deploy

Do these on the computer that will show the ChatGPT window. The phone can read this page. It cannot run the browser. Do not type a password into the terminal or into chat.

## Mandatory first run

Do not skip this. Do not clone the GitHub repo. It is private. Download the public snapshot, open a terminal in that folder, and run:

```bash
make night-check
```

On Windows, use Git Bash on the desktop. Do not use WSL. If `make` is missing, run `bash scripts/night-check.sh`. It stops at the first broken step and prints which one failed.

1. Create `.venv` if needed, `pip install -r requirements.txt`, install this package, and `python -m playwright install chromium`.
2. `python -m gpt_bridge login` headed. A Chromium window opens. Sign in yourself in that window. Press Enter only after the terminal prints `Logged in.`
3. `python -m gpt_bridge prove "Reply with the single word pong"`. It passes only if the reply contains `pong`.
4. `python -m gpt_bridge serve` in the background. It must answer `GET /health`.
5. `GET /health` must say `logged_in` is true.
6. `POST /v1/debug/break` with `Authorization: Bearer local`. This marks the active chat. It does not rotate by itself.
7. `POST /v1/chat/completions` with a short prompt. The reply must be non-empty.
8. The new lines in `logs/bridge.log` must contain `active chat unhealthy before send` and `rotated to `.
9. `GET /health` must then say `forced_broken` is false.

A passing run leaves `serve` running and prints its pid. This check cannot be run from a machine with no display. The developer has to sign in on the PC.

The same sequence by hand, if `make` is not available:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps
python -m playwright install chromium
python -m gpt_bridge login
python -m gpt_bridge prove "Reply with the single word pong"
python -m gpt_bridge serve
```

Leave that window open. Closing it stops the server. `serve` refuses `--host 0.0.0.0`. Then run the health, break, and completion curls from `scripts/night-check.sh`.

## Full sequence from zero

1. Download the public snapshot. Do not clone. Enter that folder.
2. Run `make night-check` and sign in yourself. Do not continue if it fails.
3. Leave `serve` running. The check already proved one completion. Do not restart it.
4. On that same PC, open `http://127.0.0.1:8000/dashboard`. Paste the printed secret into Internal secret and click Save. Account, chat, and model buttons stay hidden until that save succeeds. The key to copy is the word `local`. The OpenAI base is `http://127.0.0.1:8000/v1`. The model id is `gpt-subscription`.
5. Optional: start the Cloudflare quick tunnel below and paste its `https` URL into the dashboard Bridge URL field.
6. Optional: create a BotFather bot and paste the token into the Telegram field. No token is stored until you do that.

## Solution A — Cloudflare quick tunnel

Do not run the tunnel command until `GPT_BRIDGE_INTERNAL_SECRET` is set. Without it, the printed URL plus the key `local` is an open door to the signed-in browser. Control routes accept anyone who can reach the port.

`make night-check` creates the secret in `.env` if it is missing and prints it once. Or, on the PC:

```bash
python -m gpt_bridge secret
```

Paste that value into the dashboard Internal secret field and click Save. Night-check already started serve with the secret loaded. Do not restart that process. Restart only if you created the secret after serve was already running. Confirm a control route without the header is rejected:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"
```

That must print `401`. The same call with `-H "X-GPT-Bridge-Secret: <the value>"` is allowed. Completions still use only `Authorization: Bearer local`, because Kimi Code cannot send the extra header. Do not share the secret or the tunnel URL.

`logs/night-check-secret` is removed when night-check passes or stops. The value stays in `.env`, which is gitignored. Delete `.env` if you retire the computer. A tunnel does not close the completions door. Anyone with the URL and the word `local` can send a completion. The secret gates control routes only. Do not share the URL.

This is the way the public page can reach the PC. The bridge still binds only to `127.0.0.1`. The tunnel is an outbound connection. It is not a public bind.

Install `cloudflared` from Cloudflare's download page, https://developers.cloudflare.com/tunnel/downloads/.

macOS:

```bash
brew install cloudflared
```

Windows: download https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe and run that file. It does not update itself.

Linux amd64:

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb
```

With `serve` already answering on this PC, run:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the `https://` URL that ends in `trycloudflare.com`. Paste it into the Bridge URL field on the dashboard and leave that field saved. The page then calls that URL with `Authorization: Bearer local`.

The PC must stay on. The URL works only while this PC is on, `serve` is running, and this `cloudflared` process is running. Stop `cloudflared` and the URL dies. A new run prints a new hostname.

The printed URL is a public address. The API key is the word `local`. Anyone who has the URL can send completions through the signed-in browser. Do not share the URL. Do not put it in a public chat.

Cloudflare documents that a quick tunnel does not support server-sent events. A streaming client can fail through the tunnel. An ordinary JSON completion still works. The official command shape is `cloudflared tunnel --url`, documented at https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/.

Do not pass `--host 0.0.0.0` to `serve`. Do not open port 9222.

## Watchdog

`make watch` runs `scripts/watchdog.sh`. If `serve` exits, it starts `serve` again and sends a Telegram message when a bot is already linked. After 5 crashes it stops and sends one last alert. It does not print the bot token.

## Nightly profile backup

Copy the account folders. This does not copy `.env` or the Telegram token file.

```bash
python -m gpt_bridge backup
```

A nightly run, with the real project path:

```bash
0 3 * * * cd /path/to/gpt-bridge && .venv/bin/python -m gpt_bridge backup
```

The copies land in `data/backups/`, which is gitignored.

## Solution B — later upgrade, not built

Do not build this now. A later move is a VPS, or an Oracle Cloud free-tier ARM instance, with Xvfb so Chromium has a display. The worker would bind to that machine's private interface only. The public page would reach it only through a Vercel proxy that adds the `X-GPT-Bridge-Secret` header. Never bind `0.0.0.0`. Never open port 9222. The current `serve` command still refuses every host except `127.0.0.1`, `localhost`, and `::1`, so this path is documentation only.

## Dashboard

`dashboard/index.html` is the control page. Open `http://127.0.0.1:8000/dashboard` on the PC. The same file is the public page at `https://gpt-bridge-eight.vercel.app`. That public page cannot call `127.0.0.1`. After the quick tunnel, paste the tunnel URL into Bridge URL. Until then, use the local page for the buttons.

The Vercel project is `gpt-bridge` on team Bridge point. Do not edit oak-bridge-capital. Deploy the `dashboard/` folder with framework preset None. Do not add rewrites.

## Telegram

Ready when a BotFather token exists. No token has been stored. Do not invent one.

1. In Telegram, open `@BotFather`.
2. Send `/newbot`.
3. Send a display name, then a username that ends in `bot`.
4. Copy the token BotFather returns. It looks like a number, a colon, and a secret.
5. On the PC dashboard, paste that token into the Telegram field and click Verify token. The page calls `POST /v1/telegram/config`. The bridge calls Telegram `getMe` and returns a start link.
6. Open the start link, which looks like `https://t.me/<username>?start=gptbridge`, and press Start.
7. Click Poll now, or wait for the poller. That calls `getUpdates` and stores the chat id.
8. `GET /v1/telegram/status` with `Authorization: Bearer local` then shows `connected: true` and the chat id.

A login-needed event and a forced break each send a Telegram message. The buttons are Restart browser, Force break, and Open dashboard. Restart and Force break call back into this browser. Open dashboard is a link.

The token is stored in gitignored `data/telegram.json` and in this browser's local storage. It is not written into the HTML file and it is not written to the logs.

## After the check

Point a client on this PC at `http://127.0.0.1:8000/v1` with key `local` and model `gpt-subscription`. A client on another device can use the tunnel URL plus `/v1` and the same key, with the warning above. Kimi was dropped. Do not configure it unless asked again.

The Zapia host test is recorded in `ZAPIA.md`. Zapia is not the host.
