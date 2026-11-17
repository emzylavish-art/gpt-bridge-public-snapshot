# gpt-bridge

A local service that speaks OpenAI chat completions, and a Playwright session behind it that is already logged into ChatGPT. Kimi Code points at the service. Kimi Code reads files, runs commands, and edits code. The model you already pay for only reasons.

This is a local bridge: one visible browser, one active chat at a time, persistent context, no anti-detection layer. You sign in and sign out yourself. Each paid account has its own profile folder. The bridge stores the label only. It does not store passwords, and it does not type them. The API switches chats. It does not switch accounts unless you press the account button. Kimi was dropped unless you ask again. The install sequence is `DEPLOY.md`.

Automating the ChatGPT website is outside the official API. OpenAI's terms restrict automated access, and an account can be limited or closed for it. Use an account you control. This project does not hide the browser or solve challenges. If the site asks you to sign in, you sign in, in the window.

## What each part does

The Playwright layer keeps a Chromium profile on disk, finds the composer, sends the prompt, and returns the assistant text. Restarting the process reuses that profile until you log out.

Chat rotation is the recovery path. A timeout, an empty reply, a stalled generation, or an error banner opens a new chat and resends the full prompt. Retries are capped. Login failure is not rotated away: the service waits for you to sign in.

The FastAPI service exposes `POST /v1/chat/completions` and `GET /health`. Kimi Code streams by default, so the service returns server-sent events as well as ordinary JSON. Usage numbers are a rough character estimate so the agent can compact; ChatGPT's web page does not report tokens.

Kimi Code is the agent. Its config names this process as an `openai` provider on localhost, with any model name and a placeholder key. The model never receives shell or filesystem access. When Kimi Code offers tools, the bridge writes them into the prompt and turns a JSON tool request in the reply back into OpenAI `tool_calls`. Kimi Code then executes those tools itself.

## Build order

Phase 1 proves the browser round trip. Phase 2 proves a forced break recovers. Phase 3 proves the HTTP shape. Phase 4 is the real coding task.

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pip install -e . --no-deps
cp .env.example .env
```

On Windows, activate with `.venv\Scripts\activate`. The browser must be visible the first time. Leave `GPT_BRIDGE_HEADLESS` unset.

### Phase 1 — prompt in, text out

```bash
python -m gpt_bridge login
python -m gpt_bridge prove "Reply with the single word pong"
```

`login` opens ChatGPT and waits until the composer is usable. Sign in there, pick the model you want, and press Enter in the terminal. The first profile is `data/profiles/default`. A copy of the cookies is written beside that profile.

`prove` must print the reply without you touching the browser. If the composer cannot be found, the UI has drifted. Update the selector lists at the top of `src/gpt_bridge/playwright_backend.py`. A screenshot of the failure is saved under `logs/failures/`.

If Google refuses sign-in in bundled Chromium, set `GPT_BRIDGE_CHANNEL=chrome` in `.env` and run `login` again. That uses your installed Chrome. It is still an ordinary browser window, not a stealth layer.

### Phase 2 — rotation

Start the service, then force the active chat to look broken. The next completion must open a new chat and answer anyway.

```bash
python -m gpt_bridge serve
```

In another terminal, with the API up:

```bash
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/v1/debug/break \
  -H "Authorization: Bearer local"
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer local" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-subscription","messages":[{"role":"user","content":"Reply with the single word pong."}]}'
```

`logs/bridge.log` and `logs/rotations.jsonl` should show the rotation. `data/session.json` should point at the new chat URL. A second restart of `serve` should still be you: same profile, no login prompt, and the saved chat URL opened if it still exists.

### Phase 3 — the API shape

The unit tests check the OpenAI body, the stream, and the rotation rule without opening a browser:

```bash
PYTHONPATH=src python3 -m pytest -q
```

Against the live service, the OpenAI Python client should also work:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="local")
print(client.chat.completions.create(
    model="gpt-subscription",
    messages=[{"role": "user", "content": "Reply with the single word pong."}],
).choices[0].message.content)
```

Kimi Code talks to models in streaming mode. Do not turn streaming off to "simplify" the check. The stream sends each tool call in one chunk, with its id and function together, and it never sends an empty `reasoning_content` field. Those two details are what current Kimi Code builds actually parse.

### Phase 4 — Kimi Code

Install Kimi Code, then merge `kimi.config.example.toml` into `~/.kimi-code/config.toml`. Keep any provider you already have. The placeholder key must match `GPT_BRIDGE_API_KEY` (default `local`).

```toml
default_model = "gpt-subscription"

[providers.gpt-subscription]
type = "openai"
base_url = "http://127.0.0.1:8000/v1"
api_key = "local"

[models."gpt-subscription"]
provider = "gpt-subscription"
model = "gpt-subscription"
max_context_size = 128000
capabilities = ["thinking", "tool_use"]
display_name = "GPT subscription"
```

Reload Kimi Code, or run `kimi doctor`, then start it in a project and ask for one small coding task. The browser should move. `logs/prompts.jsonl` should gain one record per model call, including the prompt that crossed this service. Kimi Code executes the tools. The model only returns text.

`max_context_size` is what Kimi Code uses to decide when to compact. 128000 is a starting point. If chats die from length before the agent finishes, lower it so Kimi Code compacts sooner.

## Runtime loop

Kimi Code sends a chat completion. FastAPI compiles the messages and tool schemas into one prompt. If that transcript extends the active chat, only the new tail is typed into the existing thread. If the thread is dead, or the transcript is a different conversation, the service opens a new chat and sends the full prompt. On a send failure it does that again, up to `GPT_BRIDGE_MAX_RETRIES`, and the resent prompt is the full transcript even if the first attempt was a tail. The reply comes back in OpenAI format. Kimi Code acts.

Long prompts are attached as a text file instead of pasted, because the composer turns a long paste into its own attachment and can drop the instruction. The threshold is `GPT_BRIDGE_ATTACH_THRESHOLD`.

## Decisions this tree keeps

OpenAI-compatible HTTP first. One browser window. One active chat at a time. You change the account yourself. The API changes the chat when you ask. Persistent context is mandatory. There is no anti-detection layer. The process binds to `127.0.0.1` only.

## Night-check

On the PC with a screen, `make night-check` is the mandatory first run. It installs, waits for you to sign in, proves `pong`, starts `serve`, marks the chat, and requires the next completion to rotate. It cannot be run from a machine with no display. See `DEPLOY.md`.

## Accounts and chats

While `serve` is running, use the window it already opened. Do not start a second browser on the same profile.

Each account is a label and a folder under `data/profiles/`. Add one with the dashboard or `POST /v1/accounts/add`. Use one with `POST /v1/accounts/use`. `GET /v1/accounts` lists them. A switch during an in-flight completion returns HTTP 409. There is no password field. You type the password in the browser window.

```bash
curl -s -X POST http://127.0.0.1:8000/v1/session/logout -H "Authorization: Bearer local"
```

Sign in in the browser. Then either wait for the next completion, or open the login page again with `POST /v1/session/login`. `GET /v1/session` shows `logged_in`. If the server is stopped, `python -m gpt_bridge logout` and `python -m gpt_bridge login` do the same thing.

To change chats, list the ones in the sidebar and switch, or open a fresh chat. The next completion stays in the chat you picked and sends the full transcript there.

```bash
curl -s http://127.0.0.1:8000/v1/chats -H "Authorization: Bearer local"
curl -s -X POST http://127.0.0.1:8000/v1/chats/new -H "Authorization: Bearer local"
curl -s -X POST http://127.0.0.1:8000/v1/chats/switch \
  -H "Authorization: Bearer local" -H "Content-Type: application/json" \
  -d '{"url":"https://chatgpt.com/c/your-chat-id"}'
```

A completion can also name the chat. Use the header `X-GPT-Bridge-Chat: new` or a `https://chatgpt.com/c/...` URL. Kimi Code does not send that header, so switch from curl before a coding task, or start a new chat between tasks. Only `chatgpt.com` conversation links are accepted.

## Dashboard

`dashboard/index.html` is the control page. Open `http://127.0.0.1:8000/dashboard` on this machine. The public copy is `https://gpt-bridge-eight.vercel.app`. It cannot call `127.0.0.1`. To use the buttons from that page, run the quick tunnel in `DEPLOY.md` and paste the `https` URL into Bridge URL. The PC must stay on. Do not share that URL. The key is the word `local`.

`GET /health` now includes `timestamp`. `GET /dashboard-data` requires `Authorization: Bearer local`. If you set `GPT_BRIDGE_INTERNAL_SECRET`, control routes also require `X-GPT-Bridge-Secret`. Completions do not, because Kimi Code cannot send that header.

## Telegram

No token is stored yet. The relay is ready when you create one. In Telegram, open `@BotFather`, send `/newbot`, copy the token, paste it into the dashboard, and click Verify token. That calls `POST /v1/telegram/config`, which calls `getMe` and returns a start link. Press Start. `GET /v1/telegram/status` then shows `connected: true`. A login-needed event and a forced break each send Restart browser, Force break, and Open dashboard. The token stays in gitignored `data/telegram.json` and in browser storage. It is not written into the HTML or the logs. Exact clicks are in `DEPLOY.md`.

## Zapia

Zapia is closed as an automated host. The record is in `ZAPIA.md`. Do not point the bridge at it. Messaging Zapia is a manual fallback only.

## Saved for later

A VPS with Xvfb is documented in `DEPLOY.md` as a later upgrade. It is not built. Do not bind `0.0.0.0`. Memory across chats and an MCP form are not built. Zapia is not the later host.

## Layout

`src/gpt_bridge/playwright_backend.py` is the browser. `session.py` is rotation. `protocol.py` compiles prompts and parses the JSON contract. `wire.py` builds the OpenAI response. `api.py` is the service. `telegram.py` is the second door. `dashboard/index.html` is the control page. `kimi.config.example.toml` is the provider entry. `DEPLOY.md` is the install sequence.

`CAPABILITIES.md` is the one-page map of what is built, documented, experimental, or blocked. `INTEGRATION.md` describes the API Anything sibling. It is not imported by this package.

Selectors will drift. When a round trip breaks, look at `logs/failures/` and edit the selector lists. That is the maintenance this design expects.
