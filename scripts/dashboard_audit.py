#!/usr/bin/env python3
"""Assert the local dashboard after night-check. Do not print the secret."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = "http://127.0.0.1:8000/dashboard"
REQUIRED_BUTTONS = [
    "I have signed in",
    "Save",
    "Add account",
    "Chat switch",
    "List chats",
    "Login",
    "Logout",
    "Restart browser",
    "Force break",
    "Send pong",
    "New chat",
    "See models",
    "Verify token",
    "Poll now",
    "Copy base URL",
    "Copy API key",
    "Copy model",
    "Write Kimi config",
    "Copy live base",
    "Copy key",
]
NAV_LABELS = [
    "Getting Started",
    "Connection",
    "Accounts",
    "Browser Actions",
    "Models",
    "Telegram",
    "API Reference",
    "Logs",
]


def fail(name: str) -> None:
    print(f"AUDIT FAILED: {name}", file=sys.stderr)
    raise SystemExit(1)


def passed(name: str) -> None:
    print(f"PASS: {name}")


def secret() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from gpt_bridge.ops import read_env_value

    value = read_env_value(ROOT / ".env", "GPT_BRIDGE_INTERNAL_SECRET")
    if not value:
        fail("secret missing from .env. Run make night-check first. Do not paste the secret into chat.")
    return value


def text_of(page, selector: str) -> str:
    return (page.locator(selector).text_content() or "").strip()


def main() -> None:
    value = secret()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("dashboard did not open. Night-check serve must still be running.")
        page.locator("#secret").fill(value)
        page.locator("#save").click()
        try:
            page.locator("#login-banner").filter(has_text="ChatGPT Logged In").wait_for(timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("banner is not ChatGPT Logged In")
        passed("Banner ChatGPT Logged In")
        if text_of(page, "#mast-state") != "Live":
            browser.close()
            fail("top chip is not Live")
        passed("Connection Live chip")
        page.locator("[data-panel='connection']").click()
        expect = {
            "#reachable": "yes",
            "#logged-in": "true",
            "#browser": "ready",
            "#broken": "false",
        }
        for selector, wanted in expect.items():
            got = text_of(page, selector)
            if got != wanted:
                browser.close()
                fail(f"{selector} is {got}, expected {wanted}")
        passed("Connection yes true ready false")
        if "GET /dashboard-data shows logged_in true." not in text_of(page, "#proof"):
            browser.close()
            fail("proof is not logged_in true")
        passed("Proof logged_in true")
        for label in NAV_LABELS + REQUIRED_BUTTONS:
            if page.get_by_role("button", name=label).count() < 1:
                browser.close()
                fail(f"missing button {label}")
        passed("Every required button is visible")
        if "Adrian is the sole owner" not in page.locator(".owner").inner_text():
            browser.close()
            fail("owner line is missing")
        passed("Owner Adrian")
        page.locator("[data-panel='accounts-section']").click()
        owner = page.get_by_role("button", name="Adrian (open)")
        try:
            owner.wait_for(timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("Use account button Adrian (open) is missing")
        owner.click()
        try:
            page.locator("#proof").filter(has_text="POST /v1/accounts/use ok").wait_for(timeout=90000)
            page.locator("#account-status").filter(has_text="Open: Adrian").wait_for(timeout=90000)
            page.locator("#logged-in").filter(has_text="true").wait_for(timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("Use account proof is not POST /v1/accounts/use ok")
        if text_of(page, "#account-status") != "Open: Adrian":
            browser.close()
            fail("account line is not Open: Adrian")
        if text_of(page, "#logged-in") != "true":
            browser.close()
            fail("Logged in did not stay true after Use account")
        passed("Use account POST /v1/accounts/use ok")
        page.locator("#list").click()
        try:
            page.locator("#chats").filter(has_text="https://chatgpt.com/").wait_for(timeout=60000)
        except PlaywrightTimeout:
            try:
                page.locator("#chat").filter(has_text="https://chatgpt.com/").wait_for(timeout=5000)
            except PlaywrightTimeout:
                browser.close()
                fail("List chats did not return a ChatGPT URL")
        blob = text_of(page, "#chats") + "\n" + text_of(page, "#chat")
        match = re.search(r"https://chatgpt\.com/\S+", blob)
        if match is None:
            browser.close()
            fail("chat URL missing")
        url = match.group(0).rstrip(".,)")
        page.locator("#chat-url").fill(url)
        page.locator("#switch").click()
        try:
            page.locator("#proof").filter(has_text="POST /v1/chats/switch ok").wait_for(timeout=90000)
            page.locator("#chat").filter(has_text=url).wait_for(timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("chat switch proof is not POST /v1/chats/switch ok")
        if url not in text_of(page, "#chat"):
            browser.close()
            fail("Chat line did not show the switched URL")
        passed("Chat switch POST /v1/chats/switch ok")
        page.locator("[data-panel='models-section']").click()
        page.locator("#see-models").click()
        model = page.locator("#models button").first
        try:
            model.wait_for(timeout=60000)
        except PlaywrightTimeout:
            browser.close()
            fail("model pick button is missing")
        name = model.inner_text().replace(" (on)", "").strip()
        model.click()
        try:
            page.locator("#proof").filter(has_text="POST /v1/browser-models/select ok").wait_for(timeout=90000)
            page.locator("#model-current").filter(has_text=f"Current: {name}").wait_for(timeout=20000)
        except PlaywrightTimeout:
            browser.close()
            fail("model pick proof is not POST /v1/browser-models/select ok")
        if text_of(page, "#model-current") != f"Current: {name}":
            browser.close()
            fail(f"model line is not Current: {name}")
        page.locator("#see-models").click()
        marked = page.locator("#models button", has_text=f"{name} (on)")
        try:
            marked.wait_for(timeout=60000)
        except PlaywrightTimeout:
            browser.close()
            fail("model button did not show (on)")
        passed("Model pick POST /v1/browser-models/select ok")
        browser.close()
    print("AUDIT PASSED")


if __name__ == "__main__":
    main()
