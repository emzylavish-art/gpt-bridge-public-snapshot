# gpt-bridge pass or fail

Tick only after `NIGHT-CHECK PASSED`, on `http://127.0.0.1:8000/dashboard`, after Save. Adrian is the sole owner. Do not send the secret.

## Banner and Connection

- [ ] Banner says `ChatGPT Logged In`
- [ ] Top chip says `Live`
- [ ] Bridge reachable `yes`
- [ ] Logged in `true`
- [ ] Browser `ready`
- [ ] Forced broken `false`
- [ ] Proof says `GET /dashboard-data shows logged_in true.`
- [ ] Owner line says `Adrian is the sole owner of this bridge.`

## Buttons

- [ ] I have signed in
- [ ] Save
- [ ] Add account, Chat switch, List chats
- [ ] Login, Logout, Restart browser, Force break, Send pong, New chat
- [ ] See models
- [ ] Verify token, Poll now
- [ ] Copy base URL, Copy API key, Copy model, Write Kimi config, Copy live base, Copy key
- [ ] Sidebar: Getting Started, Connection, Accounts, Browser Actions, Models, Telegram, API Reference, Logs
- [ ] Use account button says `Adrian (open)`

## Three clicks

- [ ] Use account: proof `POST /v1/accounts/use ok`, line `Open: Adrian`, Logged in stays `true`
- [ ] Chat switch: proof `POST /v1/chats/switch ok`, Chat line shows the same `https://chatgpt.com/` URL
- [ ] Model pick: proof `POST /v1/browser-models/select ok`, line `Current:` plus that name, then `(on)` after See models

Fail any box and stop. The automated copy is `make audit` after night-check.
