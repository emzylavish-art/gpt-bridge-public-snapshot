# Zapia host tests

Tested on 2026-11-11 against `https://app.zapia.com/`, signed out. Behavior is the evidence. A sign-in wall is a failed task, not a capability claim.

## Test 1 — browser

Time: 2026-11-11T18:33:52Z. URL stayed `https://app.zapia.com/auth`.

Prompt:

```text
Open https://example.com in a browser, read the page title and the first heading, and report exactly the text you see. Do not describe your capabilities. Do the task and quote the page.
```

Reply at 2026-11-11T18:37:24Z:

```text
Searching the web
Working on your request
Continue your conversation
Sign in to continue seamlessly with Zapia
Continue with Google
Continue with Apple
```

It did not quote a title or a heading. Failed.

## Test 2 — persistence

Time: 2026-11-11T18:38:10Z. Separate URL `https://app.zapia.com/chat`.

Prompt:

```text
Open https://example.com again. Report whether any cookie, tab, or history from a previous Zapia session is present. Then open https://chatgpt.com and report whether a logged-in session exists or the page shows a sign-in screen. Quote only what you observe.
```

Reply at 2026-11-11T18:38:40Z:

```text
Working on your request
Continue your conversation
Sign in to continue seamlessly with Zapia
Continue with Google
Continue with Apple
```

No cookie, tab, history, or ChatGPT page was reported. Failed. No carried browser session was observed.

## Test 3 — outbound request

Time: 2026-11-11T18:38:50Z.

Prompt:

```text
Fetch https://webhook.site/0c861fcb-f6e0-451d-8137-55db47b08319 right now and do not describe whether you can. If you fetched it, quote the response body.
```

Reply:

```text
Working on your request
Continue your conversation
Sign in to continue seamlessly with Zapia
Continue with Google
Continue with Apple
```

The inbox at 2026-11-11T18:39:04Z was `{"data":[],"total":0}`. Nothing landed. Failed.

## Test 4 — server hosting

Time: 2026-11-11T18:39:08Z.

Prompt:

```text
Run a local Python HTTP server on port 8767 and expose it so I can open it. Do the task. If a URL exists, print only that URL.
```

Reply:

```text
Working on your request
Continue your conversation
Sign in to continue seamlessly with Zapia
Continue with Google
Continue with Apple
```

No URL was printed. Failed.

## Result

Zapia did not keep a usable browser, did not show carried state, did not make the outbound call, and did not host a server. It is not the always-on host for this bridge.

## Closed as a host

Zapia is closed as an automated host. The later `pong` replies were Zapia answering in its own browser. They did not start this bridge, and they did not sign this bridge in.

It stays closed for these reasons: the browser closes after ten minutes, Zapier's sixty-four daily runs cannot outrun that timeout, no webhook intake exists, the Chromium download failed with `EFBIG` on Zapia's machine, and no CDP port or external control surface is available. Port 9222 was not exposed. A machine with no display cannot show the login window.

Zapia remains a manual fallback only. The developer messages Zapia directly for occasional answers. No code in this project calls Zapia, and none should be added to make Zapia the host.
