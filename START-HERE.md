# Start here

Do this on the computer that will show the ChatGPT window. Do not type the password into the terminal or into chat. There is no other login. Supabase is not part of this bridge.

1. Download the snapshot. Do not clone. The GitHub repo is private, and a clone stops when this computer has no GitHub login.

```bash
mkdir -p gpt-bridge
cd gpt-bridge
curl -fL "https://files.manuscdn.com/user_upload_by_module/session_file/310519664075273319/kXDaTUKfPmRwYMcr.tgz" -o gpt-bridge-pc.tgz
tar -xzf gpt-bridge-pc.tgz
rm gpt-bridge-pc.tgz
```

On Windows, use Git Bash on the desktop. Do not use WSL. WSL has no window, so night-check stops. If `make` is missing, run `bash scripts/night-check.sh`.

2. Run the first command. This is the only recommended first run.

```bash
bash scripts/night-check.sh
```

A window opens. Sign in yourself in that window. Do not press Enter yet. Wait until the terminal prints `Logged in.` Then press Enter once. A passing run prints `NIGHT-CHECK PASSED` and leaves serve running. Adrian is the sole owner. The open account button is `Adrian (open)`.

3. Open `http://127.0.0.1:8000/dashboard` on that same computer. Paste the printed secret into Internal secret and click Save. Do not send the secret to chat. If you missed the print, copy `GPT_BRIDGE_INTERNAL_SECRET` from `.env` on that computer. Then run:

```bash
bash scripts/dashboard-audit.sh
```

It must print `AUDIT PASSED`. The banner must say ChatGPT Logged In. The public page cannot press these buttons.

4. Do not paste a tunnel URL yet. The public page cannot call `127.0.0.1`, but a tunnel is not the next step. Finish the checklist below first. A tunnel starts only after the 401 check passes.

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Paste the `https` URL into Bridge URL. The PC must stay on. Do not share the URL. The key is still the word `local`.

5. Connect Telegram only if you want it. Open BotFather, send `/newbot`, paste the token, click Verify token, press Start, then Poll now. No token is stored until you do that.

6. Point Kimi Code at it if you use Kimi. On the computer running serve:

```bash
python -m gpt_bridge kimi
```

That writes base `http://127.0.0.1:8000/v1`, key `local`, and model `gpt-subscription` into `~/.kimi-code/config.toml`. Other providers stay. To see the result without writing the file, run `python -m gpt_bridge kimi --dry-run`.

That is the whole start. After this, the dashboard is the guide.

## After the Vercel page shows this layout

Before the steps below, confirm the public page is the new one:

```bash
bash scripts/post-deploy-check.sh
```

That fetches https://gpt-bridge-eight.vercel.app. It passes only if Getting Started is first and all seven sections are present. It stops if Reach, Session, Account and chat, or Proof send is still a heading. If it stops, the deploy did not pick up the new page. Do not continue.

Do these on the computer with a screen. Do not start a tunnel, do not call API Anything against ChatGPT from this chat, and do not start Artemis.

1. Run `bash scripts/night-check.sh`. Sign in yourself in the window. Press Enter only after the terminal prints `Logged in.`
2. Night-check prints `GPT_BRIDGE_INTERNAL_SECRET` once if it created one. Paste that value into the dashboard Internal secret field. Then confirm a control route without the header is rejected:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"
```

That must print `401`. Do not run `cloudflared` until it does.
3. Run `python -m gpt_bridge kimi` to write the Kimi config. Use `--dry-run` first if you want to see the path without writing it.
4. Run `make watch` in a second terminal so serve restarts after a crash.
5. Schedule the nightly profile copy: `python -m gpt_bridge backup`. The cron line is in `DEPLOY.md`.
6. After a failed send or a login block, look at section 7, Logs. HTTP 502 and 503 carry `reason` and `error.code`. A login block is `login_required`. A chat failure is `chat_failure`.
7. Create a bot with BotFather only if you want Telegram. Paste the token on the local dashboard, click Verify token, press Start, then Poll now. `GET /v1/telegram/status` should show `connected: true`.
8. The API Anything probe is read-only. Run `bash scripts/api-anything-probe.sh` yourself if you want the candidate list. Do not learn or call from that output until you have read it.
9. Leave Artemis blocked until `adb devices` shows a phone or emulator in state `device`. Do not clone it while serve is on port 8000.

## Post-deploy checklist

Do this after `bash scripts/post-deploy-check.sh` passes. Do it on the computer with a screen.

1. Run `bash scripts/night-check.sh`. Sign in yourself in the window. Press Enter only after the terminal prints `Logged in.`
2. Confirm a control route without `X-GPT-Bridge-Secret` returns `401` before any tunnel:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"
```

That must print `401`. Do not run `cloudflared` until it does.
3. Run `python -m gpt_bridge kimi`.
4. Run `make watch` in a second terminal.
5. Leave Artemis blocked until `adb devices` shows a device. Do not start it beside serve.

## Everything is built

The remaining list is only human steps. Do these now, in order, on a computer with a screen.

1. Download the public snapshot into a folder named gpt-bridge. Do not clone.
2. `cd gpt-bridge`
3. `bash scripts/night-check.sh`
4. Sign in yourself when the Chromium window opens. Press Enter only after the terminal prints `Logged in.`
5. Confirm the secret works before any tunnel:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"
```

6. It must print `401`. If it does not, stop.
7. Write the Kimi config: `python -m gpt_bridge kimi`
8. Keep the bridge alive: `make watch`

Optional, later: create a Telegram bot with BotFather and paste the token on the dashboard, run the API Anything probe read-only, and leave Artemis blocked until `adb devices` shows a real device.

Already live: https://gpt-bridge-eight.vercel.app and https://github.com/emzylavish-art/gpt-bridge
