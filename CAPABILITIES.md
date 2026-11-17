# Capabilities

This page is the source of truth for what this stack can and cannot do today. Status is one of: built, documented, experimental, blocked-with-reason.

| Layer | Tool | What it does | Status |
| --- | --- | --- | --- |
| Brain wrapper | gpt-bridge FastAPI worker | Speaks OpenAI chat completions on 127.0.0.1:8000. Proven in tests. Unproven on a live login. | built |
| Browser driver | Playwright backend | Attaches to a visible Chromium window and rotates chats on failure. | built |
| Control surface | Vercel dashboard | Seven labeled sections: Connection, Accounts, Browser Actions, Models, Telegram, API Reference, Logs. | built |
| Tunnel | Cloudflare Tunnel | Documented quick tunnel to the PC. The PC must stay on. The key is the word local. | documented |
| Notifications | Telegram relay | Ready to send Restart browser, Force break, and Open dashboard. Token not yet created. | built |
| Device layer | Artemis | Not cloned. No phone or emulator is attached, so the hardware check waits. | blocked-with-reason |
| Site-to-API learner | API Anything | Sibling directory only. Probe script lists candidates and does not learn or call. | experimental |
| Manual fallback | Zapia | Closed as a host. Messaging Zapia directly remains possible. It does not run this bridge. | blocked-with-reason |

## Artemis

Status: blocked-with-reason. Not cloned. Not installed. Not run. Source, if a device is later attached: https://github.com/google/artemis. License there is Apache 2.0. It stays a separate checkout. Do not import it into the gpt-bridge Python package.

Unblock only when all of these are true:

1. A physical Android phone with USB debugging enabled, or an Android emulator, is attached to the computer that will run Artemis.
2. `adb devices` lists that device with the state `device`. An empty list, `unauthorized`, or `offline` does not unblock it.
3. gpt-bridge is not serving on port 8000 at the same time. The official Artemis console also opens `http://localhost:8000`. Starting both on that port will collide.

First commands after that check passes, from the ARTEMIS README. Do not run them until the device state is `device`.

macOS or Linux:

```bash
adb devices
git clone https://github.com/google/artemis.git
cd artemis
./start.sh
```

Windows PowerShell:

```powershell
adb devices
git clone https://github.com/google/artemis.git
cd artemis
.\start.bat
```

The first proof command in that README, after the start script has prepared the checkout, is:

```bash
uv run artemis run "Open Settings, find Battery and tell me current level" --profile flash
```

None of these commands have been run in this session.
