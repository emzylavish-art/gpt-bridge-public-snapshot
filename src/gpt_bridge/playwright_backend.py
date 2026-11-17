from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import time

from gpt_bridge.config import Settings
from gpt_bridge.session import ChatFailure, LoginRequired

log = logging.getLogger("gpt_bridge.browser")

# Selectors drift when ChatGPT ships a new composer. Keep the fallbacks here.
SELECTORS = {
    "composer": [
        "#prompt-textarea",
        "textarea[name='prompt-textarea']",
        "div#prompt-textarea",
        "[contenteditable='true'][role='textbox']",
        "[contenteditable='true']",
        "textarea",
    ],
    "send": [
        "[data-testid='send-button']",
        "button[aria-label='Send prompt']",
        "button[aria-label='Send message']",
    ],
    "stop": [
        "[data-testid='stop-button']",
        "button[aria-label='Stop streaming']",
        "button[aria-label='Stop generating']",
    ],
    "new_chat": [
        "[data-testid='create-new-chat-button']",
        "a[aria-label='New chat']",
        "button[aria-label='New chat']",
    ],
    "close": [
        "button[data-testid='close-button']",
        "button[aria-label='Close']",
    ],
}

ERROR_PHRASES = (
    "something went wrong",
    "network error",
    "too many requests",
    "unusual activity",
    "unable to load",
    "conversation not found",
    "failed to load",
    "an error occurred while",
    "you've reached our limit",
    "you’ve reached our limit",
)

AUTH_HINTS = ("/auth", "auth.openai.com", "/login")
CHAT_HOSTS = ("chatgpt.com", "chat.openai.com")


class PlaywrightBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile_dir = settings.user_data_dir
        self.storage_state_path = settings.storage_state_path
        self._playwright = None
        self._context = None
        self._browser = None
        self._attached = False
        self.page = None
        self._force_broken = False
        self._history = False

    def prepare_profile(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self.storage_state_path = profile_dir / "storage_state.json"

    async def use_profile(self, profile_dir: Path) -> None:
        if self.settings.browser_mode == "attach":
            raise RuntimeError("attach mode uses the currently open normal Chrome profile; sign out and sign in there")
        await self.stop()
        self.prepare_profile(profile_dir)
        self._history = False
        self._force_broken = False
        await self.start()
        if not await self.logged_in() and self.page is not None:
            await self.page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded")
        log.info("opened account profile %s", profile_dir.name)

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install -r requirements.txt "
                "&& python -m playwright install chromium"
            ) from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        if self.settings.browser_mode == "attach":
            log.info("attaching to normal Chrome at %s", self.settings.cdp_url)
            self._browser = await self._playwright.chromium.connect_over_cdp(self.settings.cdp_url)
            if not self._browser.contexts:
                raise RuntimeError("normal Chrome has no browser context at the configured CDP URL")
            self._context = self._browser.contexts[0]
            self._attached = True
            chat_pages = [
                page for page in self._context.pages
                if _is_chat_url(page.url) and not _is_auth_url(page.url)
            ]
            if not chat_pages:
                chat_pages = [page for page in self._context.pages if _is_chat_url(page.url)]
            self.page = chat_pages[-1] if chat_pages else (self._context.pages[-1] if self._context.pages else await self._context.new_page())
            await self._select_foreground_page()
            self._history = self._url_is_chat(self.page.url)
            log.info("attached to normal Chrome at %s", self.page.url)
            return
        kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.settings.headless,
            "viewport": {"width": 1280, "height": 800},
            "slow_mo": self.settings.slow_mo_ms,
        }
        if self.settings.channel:
            kwargs["channel"] = self.settings.channel
            log.info("opening installed %s", self.settings.channel)
        else:
            log.info("opening Playwright Chromium; Google sign-in is rejected in this browser")
        self._context = await self._playwright.chromium.launch_persistent_context(**kwargs)
        await self._restore_cookies_if_profile_is_fresh()
        self.page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        await self.page.goto(self._startup_url(), wait_until="domcontentloaded")
        self._history = self._url_is_chat(self.page.url)
        log.info("browser open at %s", self.page.url)

    async def stop(self) -> None:
        await self._save_storage_state()
        if self._context is not None:
            if not self._attached:
                await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self.page = None
        self._context = None
        self._browser = None
        self._attached = False
        self._playwright = None

    async def status(self) -> dict:
        if self.page is None:
            return {"browser": "stopped", "logged_in": False, "chat_url": None}
        return {
            "browser": "ready",
            "logged_in": await self.logged_in(),
            "chat_url": self.page.url,
            "healthy": await self.healthy(),
            "forced_broken": self._force_broken,
        }

    async def logged_in(self) -> bool:
        if self.page is None:
            return False
        if _is_auth_url(self.page.url):
            return False
        try:
            return bool(await self.page.evaluate("""() => {
                const visible = (el) => {
                    if (!el) return false;
                    const s = getComputedStyle(el), r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const composer = [...document.querySelectorAll(
                    '#prompt-textarea, textarea[name="prompt-textarea"], textarea, [contenteditable="true"]'
                )].some(visible);
                const account = [...document.querySelectorAll(
                    '[data-testid*="account"], [aria-label*="Account"], a[href*="/settings"], button[aria-label*="profile"]'
                )].some(visible);
                const path = location.pathname;
                const chat = path.startsWith('/c/') || path.startsWith('/share/');
                const body = (document.body?.innerText || '').toLowerCase();
                const login = /\b(log in|sign up|continue with google)\b/.test(body);
                return composer || account || (chat && !login);
            }"""))
        except Exception:
            return await self._composer_visible()

    async def wait_for_login(self) -> None:
        if self.page is None:
            raise LoginRequired("browser is not started")
        deadline = time.monotonic() + self.settings.login_timeout_s
        log.info("sign in in the browser window; waiting up to %ss", self.settings.login_timeout_s)
        warned = False
        while time.monotonic() < deadline:
            await self._dismiss_overlays()
            if self._attached and self._context is not None:
                pages = [p for p in self._context.pages if _is_chat_url(p.url)]
                signed_pages = [p for p in pages if not _is_auth_url(p.url)]
                if signed_pages:
                    self.page = signed_pages[-1]
                    await self._select_foreground_page()
            url = self.page.url or ""
            if not warned and "accounts.google.com" in url and "rejected" in url:
                print(
                    "Google rejected this browser. Close that tab. "
                    "On the ChatGPT page, do not click Continue with Google. "
                    "Use the email box. A code from your phone is fine. Do not click Try again."
                )
                warned = True
            if await self.logged_in():
                await self._save_storage_state()
                print(f"Logged in. Profile: {self.profile_dir}")
                log.info("login detected")
                return
            await asyncio.sleep(1)
        if self._attached and self.page is not None:
            try:
                title = await self.page.title()
                body = (await self.page.locator("body").inner_text())[:300].replace("\n", " ")
                print(f"CDP shows a ChatGPT page but marker detection failed: url={self.page.url!r} title={title!r} body={body!r}")
            except Exception:
                print("CDP shows a browser page, but marker detection failed before login timeout.")
        raise LoginRequired("timed out waiting for ChatGPT login")

    async def healthy(self) -> bool:
        if self._force_broken or self.page is None:
            return False
        if not await self.logged_in():
            return False
        banner = await self._error_banner()
        return banner is None

    async def has_history(self) -> bool:
        if self.page is None:
            return False
        if self._url_is_chat(self.page.url):
            return True
        texts = await self._assistant_texts()
        return bool(texts) or self._history

    async def mark_broken(self) -> None:
        self._force_broken = True

    async def rotate(self) -> str:
        if self.page is None:
            raise ChatFailure("browser is not started")
        self._force_broken = False
        clicked = await self._click_first("new_chat")
        if clicked:
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                log.info("new chat click did not navigate; opening a fresh url")
                await self.page.goto(self.settings.new_chat_url, wait_until="domcontentloaded")
        else:
            await self.page.goto(self.settings.new_chat_url, wait_until="domcontentloaded")
        await self._dismiss_overlays()
        if not await self._wait_for_composer(20):
            raise ChatFailure("new chat did not show a composer")
        self._history = False
        log.info("rotated to %s", self.page.url)
        return self.page.url

    async def logout(self) -> dict:
        if self.page is not None:
            await self.page.goto("https://chatgpt.com/auth/logout", wait_until="domcontentloaded")
        if self._context is not None:
            await self._context.clear_cookies()
        if self.page is not None:
            await self.page.evaluate(
                """() => {
                    try { localStorage.clear(); } catch (err) {}
                    try { sessionStorage.clear(); } catch (err) {}
                }"""
            )
            await self.page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded")
        self._history = False
        self._force_broken = False
        if self.settings.storage_state_path.exists():
            self.settings.storage_state_path.unlink()
        if self.storage_state_path.exists() and self.storage_state_path != self.settings.storage_state_path:
            self.storage_state_path.unlink()
        log.info("logged out; the login page is open for another account")
        return await self.status()

    async def list_models(self) -> dict:
        current = await self._current_model_label()
        if self.page is None:
            return {"current": None, "models": [], "reason": "browser is not started"}
        if not await self._open_model_menu():
            return {"current": current, "models": [], "reason": "model menu did not open"}
        models = await self.page.locator(
            "[role='menuitemradio'], [role='menuitem'], [role='option']"
        ).evaluate_all(
            """(nodes) => {
                const seen = new Set();
                const out = [];
                for (const node of nodes) {
                    const name = (node.innerText || '').trim().split('\\n')[0].slice(0, 80);
                    if (!name || seen.has(name)) continue;
                    seen.add(name);
                    out.push({
                        name,
                        selected: node.getAttribute('aria-checked') === 'true'
                            || node.getAttribute('data-state') === 'checked',
                    });
                }
                return out;
            }"""
        )
        await self.page.keyboard.press("Escape")
        return {"current": current, "models": models}

    async def select_model(self, name: str) -> dict:
        target = (name or "").strip()
        if not target:
            raise ChatFailure("model name is required")
        if self.page is None:
            raise ChatFailure("browser is not started")
        if not await self._open_model_menu():
            raise ChatFailure("model menu did not open")
        items = self.page.locator("[role='menuitemradio'], [role='menuitem'], [role='option']")
        count = await items.count()
        chosen = None
        for index in range(count):
            item = items.nth(index)
            text = ((await item.inner_text()) or "").strip().split("\n")[0]
            if text.lower() == target.lower():
                chosen = item
                target = text
                break
        if chosen is None:
            await self.page.keyboard.press("Escape")
            raise ChatFailure(f"model not in the menu: {name}")
        await chosen.click()
        log.info("selected model %s", target)
        return {"selected": target, "current": await self._current_model_label()}

    async def _open_model_menu(self) -> bool:
        if self.page is None:
            return False
        buttons = self.page.locator("button[aria-haspopup='menu']")
        count = await buttons.count()
        for index in range(count):
            button = buttons.nth(index)
            text = ((await button.inner_text()) or "").strip()
            if not text or text in {"+", "Add", "Attach"}:
                continue
            await button.click()
            try:
                await self.page.locator(
                    "[role='menuitemradio'], [role='menuitem'], [role='option']"
                ).first.wait_for(state="visible", timeout=2500)
                return True
            except Exception:
                await self.page.keyboard.press("Escape")
        return False

    async def _current_model_label(self) -> str | None:
        if self.page is None:
            return None
        buttons = self.page.locator("button[class*='composer-pill']")
        count = await buttons.count()
        for index in range(count):
            text = ((await buttons.nth(index).inner_text()) or "").strip().split("\n")[0]
            if text and text not in {"+", "Add", "Attach"}:
                return text[:80]
        return None

    async def open_login_page(self) -> None:
        if self.page is None:
            raise LoginRequired("browser is not started")
        await self.page.goto(self.settings.chatgpt_url, wait_until="domcontentloaded")
        await self._dismiss_overlays()

    async def list_chats(self) -> list[dict]:
        if self.page is None:
            return []
        return await self.page.evaluate(
            """() => {
                const seen = new Set();
                const chats = [];
                for (const link of document.querySelectorAll('a[href*="/c/"], a[href*="/uc/"]')) {
                    const url = link.href || '';
                    if (!url || seen.has(url)) continue;
                    if (!url.startsWith('https://chatgpt.com/')) continue;
                    seen.add(url);
                    const title = (link.innerText || link.getAttribute('aria-label') || '')
                        .trim()
                        .split('\\n')[0]
                        .slice(0, 120);
                    chats.push({url, title: title || url});
                    if (chats.length >= 40) break;
                }
                return chats;
            }"""
        )

    async def switch_chat(self, url: str) -> str:
        if self.page is None:
            raise ChatFailure("browser is not started")
        await self.page.goto(url, wait_until="domcontentloaded")
        await self._dismiss_overlays()
        if _is_auth_url(self.page.url):
            raise LoginRequired("login required")
        if not await self._wait_for_composer(20):
            raise ChatFailure("switched chat did not show a composer")
        self._history = True
        self._force_broken = False
        log.info("switched to %s", self.page.url)
        return self.page.url

    async def send(self, prompt: str) -> str:
        try:
            return await self._send(prompt)
        except (ChatFailure, LoginRequired):
            raise
        except Exception as exc:
            await self._screenshot("send-exception")
            raise ChatFailure(f"browser error: {exc}") from exc

    async def _send(self, prompt: str) -> str:
        if self.page is None:
            raise ChatFailure("browser is not started")
        if _is_auth_url(self.page.url):
            raise LoginRequired()
        await self._select_foreground_page()
        try:
            await self.page.bring_to_front()
        except Exception as exc:
            log.warning("could not bring attached ChatGPT tab to front: %s", exc)
        await self._log_cookie_names("prove/send")
        await self._dismiss_overlays()
        if not await self._wait_for_composer(20):
            raise ChatFailure("composer missing")
        before_state = await self._composer_state()
        log.info("send probe before: %s", before_state)
        if not before_state.get("visible") or before_state.get("disabled") or before_state.get("readonly"):
            raise ChatFailure(f"composer not interactive: {before_state}")
        banner = await self._error_banner()
        if banner:
            raise ChatFailure(f"error text: {banner}")
        before = await self._assistant_texts()
        await self._insert_prompt(prompt)
        await self._submit()
        await asyncio.sleep(1)
        after_state = await self._composer_state()
        log.info("send probe after: %s", after_state)
        if _is_auth_url(self.page.url):
            raise LoginRequired("ChatGPT session expired or was redirected during send")
        if (
            after_state.get("user_nodes", 0) <= before_state.get("user_nodes", 0)
        ):
            log.warning("send probe unchanged; refocusing composer and retrying once")
            composer = await self._composer()
            if composer is not None:
                await composer.click()
            await self._insert_prompt(prompt)
            await self._submit()
            await asyncio.sleep(1)
            retry_state = await self._composer_state()
            log.info("send probe retry after: %s", retry_state)
        if not await self._generation_started(before):
            await self._screenshot("send-did-not-start")
            raise ChatFailure("send did not start")
        text = await self._wait_for_reply(len(before))
        self._history = True
        self._force_broken = False
        await self._save_storage_state()
        return text

    async def _insert_prompt(self, prompt: str) -> None:
        if len(prompt) >= self.settings.attach_threshold:
            await self._attach_prompt(prompt)
            return
        composer = await self._composer()
        if composer is not None:
            try:
                is_contenteditable = await composer.evaluate(
                    "el => el.isContentEditable || el.getAttribute('contenteditable') === 'true'"
                )
                await composer.click()
                if is_contenteditable:
                    await self.page.keyboard.press("ControlOrMeta+A")
                    await self.page.keyboard.press("Backspace")
                    await self.page.keyboard.insert_text(prompt)
                else:
                    await composer.fill(prompt)
            except Exception:
                log.info("composer fill failed; trying insertText")
        if await self._composer_length() >= min(len(prompt), 8):
            return
        await self.page.evaluate(
            """(text) => {
                const el = document.querySelector('#prompt-textarea')
                    || document.querySelector("textarea[name='prompt-textarea']")
                    || document.querySelector("[contenteditable='true']");
                if (!el) return;
                el.focus();
                if (el.isContentEditable) {
                    el.textContent = text;
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
                } else {
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    document.execCommand('insertText', false, text);
                }
            }""",
            prompt,
        )
        if await self._composer_length() >= min(len(prompt), 8):
            return
        log.info("composer insert was short; attaching the prompt as a file")
        await self._attach_prompt(prompt)

    async def _attach_prompt(self, prompt: str) -> None:
        outgoing = self.settings.log_dir / "outgoing"
        outgoing.mkdir(parents=True, exist_ok=True)
        path = outgoing / f"prompt-{int(time.time())}.txt"
        path.write_text(prompt, encoding="utf-8")
        file_input = self.page.locator("input[type='file']").first
        if not await file_input.count():
            raise ChatFailure("composer rejected the prompt and no file input was found")
        await file_input.set_input_files(str(path))
        note = (
            "Read the attached transcript file and follow the instructions inside it. "
            "Reply with one JSON object only, no markdown fences."
        )
        await self.page.evaluate(
            """(text) => {
                const el = document.querySelector('#prompt-textarea')
                    || document.querySelector("textarea[name='prompt-textarea']");
                if (!el) return;
                el.focus();
                document.execCommand('insertText', false, text);
            }""",
            note,
        )
        await asyncio.sleep(0.5)

    async def _submit(self) -> None:
        if await self._click_first("send"):
            return
        await self.page.keyboard.press("Enter")

    async def _generation_started(self, before: list[str]) -> bool:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if await self._stop_visible():
                return True
            texts = await self._assistant_texts()
            if len(texts) > len(before) or (texts and texts != before):
                return True
            await asyncio.sleep(0.25)
        return False

    async def _wait_for_reply(self, previous_count: int) -> str:
        deadline = time.monotonic() + self.settings.reply_timeout_s
        last_text = ""
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            banner = await self._error_banner()
            if banner:
                await self._screenshot("error-banner")
                raise ChatFailure(f"error text: {banner}")
            texts = await self._assistant_texts()
            current = texts[-1] if len(texts) > previous_count else ""
            if current != last_text:
                last_text = current
                last_change = time.monotonic()
            stop_visible = await self._stop_visible()
            quiet = time.monotonic() - last_change
            if stop_visible and quiet >= self.settings.stall_timeout_s and last_text:
                await self._screenshot("stalled")
                raise ChatFailure("stalled generation")
            if (
                not stop_visible
                and not last_text
                and quiet >= self.settings.stable_seconds
                and time.monotonic() - last_change >= self.settings.stable_seconds
            ):
                await self._screenshot("empty-reply")
                raise ChatFailure("empty reply")
            if not stop_visible and last_text and quiet >= self.settings.stable_seconds:
                return last_text
            await asyncio.sleep(0.4)
        await self._screenshot("timeout")
        raise ChatFailure("timeout")

    async def _assistant_texts(self) -> list[str]:
        return await self.page.evaluate(
            """() => {
                const selectors = [
                    '[data-message-author-role="assistant"]',
                    '[data-testid*="conversation-turn"] [data-message-author-role="assistant"]',
                    'main article',
                    'main [class*="markdown"]',
                    'main [class*="prose"]'
                ];
                const seen = new Set();
                const texts = [];
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        const role = (node.getAttribute('data-message-author-role') || '').toLowerCase();
                        const text = (node.innerText || node.textContent || '').trim();
                        const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                        const visible = style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                        if (!visible || !text || role === 'user' || seen.has(text)) continue;
                        seen.add(text);
                        texts.push(text);
                    }
                }
                return texts;
            }"""
        )

    async def _error_banner(self) -> str | None:
        texts = await self.page.evaluate(
            """() => [...document.querySelectorAll('[role="alert"], [data-testid*="error"]')]
                .map(node => (node.innerText || '').trim())
                .filter(text => text && text.length < 400)"""
        )
        for text in texts:
            lowered = text.lower()
            if any(phrase in lowered for phrase in ERROR_PHRASES):
                return text[:240]
        return None

    async def _composer_visible(self) -> bool:
        return await self._composer() is not None

    async def _composer(self):
        for selector in SELECTORS["composer"]:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    async def _composer_length(self) -> int:
        return await self.page.evaluate(
            """() => {
                const el = document.querySelector('#prompt-textarea')
                    || document.querySelector("textarea[name='prompt-textarea']")
                    || document.querySelector("[contenteditable='true']")
                    || document.querySelector("textarea");
                if (!el) return 0;
                return ((el.innerText || el.value || '')).trim().length;
            }"""
        )

    async def _composer_state(self) -> dict:
        return await self.page.evaluate(
            """() => {
                const selectors = ['#prompt-textarea', 'textarea[name="prompt-textarea"]',
                    '[contenteditable="true"]', 'textarea'];
                let el = null;
                let fallback = null;
                for (const selector of selectors) {
                    for (const candidate of document.querySelectorAll(selector)) {
                        if (!fallback) fallback = candidate;
                        const candidateStyle = getComputedStyle(candidate), candidateRect = candidate.getBoundingClientRect();
                        if (candidateStyle.display !== 'none' && candidateStyle.visibility !== 'hidden'
                            && candidateRect.width > 0 && candidateRect.height > 0) {
                            el = candidate;
                            break;
                        }
                    }
                    if (el) break;
                }
                el = el || fallback;
                const visible = (node) => {
                    if (!node) return false;
                    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden'
                        && rect.width > 0 && rect.height > 0;
                };
                const rect = el ? el.getBoundingClientRect() : null;
                const value = el ? (el.value || el.innerText || el.textContent || '') : '';
                return {
                    tag: el ? el.tagName : null,
                    text: value.trim().slice(0, 200),
                    value_length: value.length,
                    visible: visible(el),
                    disabled: Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true')),
                    readonly: Boolean(el && (el.readOnly || el.getAttribute('aria-readonly') === 'true')),
                    focused: Boolean(el && document.activeElement === el),
                    box: rect ? {x: rect.x, y: rect.y, width: rect.width, height: rect.height} : null,
                    user_nodes: document.querySelectorAll('[data-message-author-role="user"], [data-testid*="conversation-turn"]').length,
                    title: document.title,
                    errors: [...document.querySelectorAll('[role="alert"], [data-testid*="error"], [data-radix-toast-viewport] *')]
                        .map(node => (node.innerText || '').trim()).filter(Boolean).slice(-5),
                    url: location.href
                };
            }"""
        )

    async def write_diagnostics(self, label: str = "browser-failure") -> Path | None:
        if self.page is None:
            return None
        try:
            dom = await self.page.content()
            cookies = await self._cookie_summary()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = self.settings.log_dir / f"{label}-{stamp}.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "<!-- active_url=" + self.page.url + " cookies=" + json.dumps(cookies) + " -->\n" + dom,
                encoding="utf-8",
            )
            log.warning("wrote %s diagnostics: url=%s cookies=%s", label, self.page.url, cookies)
            return path
        except Exception as exc:
            log.warning("could not write %s diagnostics: %s", label, exc)
            return None

    async def _cookie_summary(self) -> list[dict]:
        if self._context is None:
            return []
        try:
            cookies = await self._context.cookies()
            now = time.time()
            return [
                {
                    "name": str(cookie.get("name")),
                    "domain": str(cookie.get("domain", "")),
                    "expired": bool(cookie.get("expires", -1) not in (-1, 0) and cookie.get("expires", -1) <= now),
                }
                for cookie in cookies
                if cookie.get("name")
            ]
        except Exception as exc:
            log.warning("could not inspect prove-time cookies: %s", exc)
            return []

    async def _cookie_names(self) -> list[str]:
        return [cookie["name"] for cookie in await self._cookie_summary()]

    async def _log_cookie_names(self, phase: str) -> None:
        summary = await self._cookie_summary()
        log.info("%s cookies (names/expiry only): %s", phase, summary)

    async def _wait_for_composer(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            await self._dismiss_overlays()
            if await self._composer_visible():
                return True
            await asyncio.sleep(0.3)
        return False

    async def _select_foreground_page(self) -> None:
        """Prefer the focused visible ChatGPT tab over CDP page ordering."""
        if self._context is None:
            return
        candidates = [
            page for page in self._context.pages
            if _is_chat_url(page.url) and not _is_auth_url(page.url)
        ]
        if not candidates:
            return
        ranked = []
        for page in candidates:
            try:
                state = await page.evaluate(
                    "() => ({visible: document.visibilityState === 'visible', focused: document.hasFocus()})"
                )
            except Exception:
                state = {"visible": False, "focused": False}
            ranked.append((bool(state.get("focused")), bool(state.get("visible")), page))
        ranked.sort(key=lambda item: (item[0], item[1]))
        chosen = ranked[-1][2]
        if chosen is not self.page:
            log.info("selected foreground ChatGPT tab: %s", chosen.url)
        self.page = chosen
        try:
            await self.page.bring_to_front()
        except Exception as exc:
            log.debug("could not foreground ChatGPT tab: %s", exc)

    async def _stop_visible(self) -> bool:
        for selector in SELECTORS["stop"]:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _click_first(self, group: str) -> bool:
        for selector in SELECTORS[group]:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible() and await locator.is_enabled():
                    await locator.click()
                    return True
            except Exception:
                continue
        return False

    async def _dismiss_overlays(self) -> None:
        for _ in range(3):
            clicked = await self._click_first("close")
            if not clicked:
                return
            await asyncio.sleep(0.2)

    async def _screenshot(self, label: str) -> None:
        if self.page is None:
            return
        folder = self.settings.log_dir / "failures"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{int(time.time())}-{label}.png"
        try:
            await self.page.screenshot(path=str(path), full_page=True)
            log.info("saved failure screenshot %s", path)
        except Exception as exc:
            log.info("could not save screenshot: %s", exc)

    async def _save_storage_state(self) -> None:
        if self._context is None:
            return
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._context.storage_state(path=str(self.storage_state_path))
        except Exception as exc:
            log.info("could not write storage state: %s", exc)

    async def _restore_cookies_if_profile_is_fresh(self) -> None:
        cookies = self.profile_dir / "Default" / "Cookies"
        if cookies.exists() or not self.storage_state_path.is_file():
            return
        try:
            state = json.loads(self.storage_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        raw = state.get("cookies") or []
        if raw and self._context is not None:
            try:
                await self._context.add_cookies(raw)
                log.info("restored %s cookies from storage state", len(raw))
            except Exception as exc:
                log.info("could not restore cookies: %s", exc)

    def _startup_url(self) -> str:
        if self.settings.session_path.is_file():
            try:
                saved = json.loads(self.settings.session_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                saved = {}
            url = saved.get("chat_url") or ""
            if url.startswith("https://chatgpt.com/"):
                self._history = True
                return url
        return self.settings.new_chat_url

    @staticmethod
    def _url_is_chat(url: str) -> bool:
        return "/c/" in url or "/uc/" in url


def _is_auth_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in AUTH_HINTS)


def _is_chat_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(host in lowered for host in CHAT_HOSTS)
