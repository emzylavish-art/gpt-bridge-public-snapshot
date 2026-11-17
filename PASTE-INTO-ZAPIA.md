Do all of this yourself on the computer that can show a Chromium window. Do not ask the person to run commands. Do not rebuild this project from memory. Do not clone GitHub. The repo is private, and the last clone stopped with: fatal: could not read Username for 'https://github.com': No such device or address. That is an auth stop, not a bridge failure. Do not use an old zip. Do not type an email, password, or one-time code. Do not invent a Telegram token. Do not touch oak-bridge-capital. Do not start Artemis. Do not open port 9222. Do not bind 0.0.0.0. Do not start a tunnel. Do not paste the control secret into chat, GitHub, or Notion.

Step 1. Confirm git is present. If git --version does not print a version, install it, then confirm again. Stop if it still fails.

git --version || { echo "STOP: git --version failed"; exit 1; }

Step 2. Download this exact snapshot. It is commit 2b47604. It attaches to normal Chrome on localhost port 9333. Adrian is the sole owner. Do not clone.

mkdir -p gpt-bridge
cd gpt-bridge
curl -fL "https://files.manuscdn.com/user_upload_by_module/session_file/310519664075273319/kXDaTUKfPmRwYMcr.tgz" -o gpt-bridge-pc.tgz
tar -xzf gpt-bridge-pc.tgz
rm gpt-bridge-pc.tgz

Confirm these files exist: Makefile, scripts/night-check.sh, src/gpt_bridge/api.py, src/gpt_bridge/playwright_backend.py, dashboard/index.html, requirements.txt, requirements-dev.txt. If any are missing, stop and name the missing file.

One visible Chromium window drives one ChatGPT account. While a completion, forced break, or model switch holds the lock, POST /v1/accounts/use returns HTTP 409. Do not switch accounts during a send.

Step 3. Run the first live check. On Windows, use Git Bash on the desktop. Do not use WSL.

Before night-check, confirm this computer can show a window. On Linux, if DISPLAY and WAYLAND_DISPLAY are empty and /tmp/.X11-unix/X0 is missing, stop. Say step 2 login needs a display. Do not retry. A browser-tool ChatGPT session is not the project Chromium window. Do not type the password into that browser tool.

bash scripts/night-check.sh

A Chromium window opens on ChatGPT. The person types the email and password into that window, never into the terminal and never into chat. Do not press Enter until the terminal prints Logged in. Then press Enter once. You do not type the password.

The script installs, waits for that sign-in, proves a reply containing pong, starts serve on 127.0.0.1 only, checks logged_in true, marks the chat, sends one more request, and checks the log for "active chat unhealthy before send" and forced_broken false. If any step fails, it names the step. Stop there. Report the named step and the log lines. Do not continue.

If Chromium fails with EFBIG or "file too large", stop and say step 1 install chromium failed with EFBIG. Do not claim login worked.

Step 4. Hard stop: secret before any tunnel. Do not paste the secret. Run:

curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/v1/debug/break -H "Authorization: Bearer local"

It must print 401. If it does not, stop. Do not run cloudflared. Do not share a tunnel URL. Completions stay Authorization Bearer local. The secret gates control routes only.

Step 5. Hard stop: refuse a public bind. This command must stop and print the refusal. Do not leave a server on 0.0.0.0.

python -m gpt_bridge serve --host 0.0.0.0

Expected text: refusing to bind outside localhost. If it binds, stop and kill it. Do not open port 9222.

Step 6. Write the Kimi config on this computer. It keeps other providers. The browser is ChatGPT. Kimi Code is only the client.

python -m gpt_bridge kimi

Step 7. Keep serve alive. It restarts after a crash, up to five times, then stops.

make watch

Do not start Artemis. It also uses port 8000. Do not invent a Telegram token. Do not say the bridge is ready unless every proof below happened.

Reply with only these fields: git --version, night-check pass or the named failed step, the prove reply, health JSON, the 401 result, the bind-refusal line, the kimi path, the serve pid, and whether make watch is running.
