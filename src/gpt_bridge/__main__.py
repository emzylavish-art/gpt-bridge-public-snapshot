from __future__ import annotations

import argparse
import asyncio
import re
import sys

from gpt_bridge.config import load_settings
from gpt_bridge.journal import configure_logging
from gpt_bridge.protocol import parse_reply, plan_turn
from gpt_bridge.session import CompletionSession


def main() -> None:
    parser = argparse.ArgumentParser(prog="gpt-bridge", description="Local ChatGPT-to-OpenAI bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Open ChatGPT and wait until the composer is usable")
    sub.add_parser("logout", help="Clear the saved login so you can sign in as another account")

    prove = sub.add_parser("prove", help="Send one prompt and print the reply")
    prove.add_argument("prompt", nargs="?", help="Prompt text")
    prove.add_argument("--file", help="Read the prompt from a file")

    serve = sub.add_parser("serve", help="Run the OpenAI-compatible local API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    sub.add_parser("secret", help="Create GPT_BRIDGE_INTERNAL_SECRET in .env if it is missing")
    sub.add_parser("backup", help="Copy data/profiles into data/backups")
    kimi = sub.add_parser("kimi", help="Write the bridge provider into ~/.kimi-code/config.toml")
    kimi.add_argument("--dry-run", action="store_true", help="Print the result without writing the file")

    args = parser.parse_args()
    settings = load_settings()
    configure_logging(settings.log_dir)
    if args.command == "login":
        asyncio.run(_login(settings))
    elif args.command == "logout":
        asyncio.run(_logout(settings))
    elif args.command == "prove":
        prompt = args.prompt
        if args.file:
            prompt = open(args.file, encoding="utf-8").read()
        if not prompt:
            parser.error("prove requires a prompt or --file")
        raise SystemExit(asyncio.run(_prove(settings, prompt)))
    elif args.command == "serve":
        host = args.host or settings.host
        port = args.port or settings.port
        _serve(settings, host, port)
    elif args.command == "secret":
        _print_secret(settings.home / ".env")
    elif args.command == "backup":
        _print_backup(settings.home)
    elif args.command == "kimi":
        _print_kimi(dry_run=args.dry_run)


def _print_secret(env_path) -> None:
    from gpt_bridge.ops import ensure_internal_secret

    value, created = ensure_internal_secret(env_path)
    if not created:
        print("GPT_BRIDGE_INTERNAL_SECRET is already set. It was not printed again.")
        print("Do not start a tunnel until the dashboard Internal secret field matches it.")
        return
    print("GPT_BRIDGE_INTERNAL_SECRET created in .env.")
    print("Paste this into the dashboard Internal secret field, then restart serve.")
    print("Do not start a tunnel until that field is saved. Do not share this value.")
    print(value)


def _print_backup(home) -> None:
    from gpt_bridge.ops import backup_profiles

    result = backup_profiles(home)
    if not result["copied"]:
        raise SystemExit(f"backup skipped: {result['reason']}")
    print(result["path"])


def _print_kimi(*, dry_run: bool = False) -> None:
    from gpt_bridge.ops import kimi_config_path, write_kimi_config

    result = write_kimi_config(kimi_config_path(), dry_run=dry_run)
    print(result["path"])
    if dry_run:
        print("dry-run; file not written")
        return
    print("written" if result["written"] else "already set")


async def _login(settings) -> None:
    from gpt_bridge.playwright_backend import PlaywrightBackend

    browser = PlaywrightBackend(settings)
    await browser.start()
    try:
        await browser.wait_for_login()
        print(f"Logged in. Profile: {settings.user_data_dir}")
        print(f"Storage state: {settings.storage_state_path}")
        if sys.stdin.isatty():
            input("Pick the model in the browser if you want, then press Enter to close it. ")
    finally:
        await browser.stop()


async def _logout(settings) -> None:
    from gpt_bridge.playwright_backend import PlaywrightBackend

    browser = PlaywrightBackend(settings)
    await browser.start()
    try:
        await browser.logout()
        print("Logged out. The browser is on the login page.")
        print("Sign in as the other account, or run: python -m gpt_bridge login")
        if sys.stdin.isatty():
            input("Press Enter to close the window. ")
    finally:
        await browser.stop()


async def _prove(settings, prompt: str) -> int:
    from gpt_bridge.playwright_backend import PlaywrightBackend

    browser = PlaywrightBackend(settings)
    session = CompletionSession(browser, settings)
    await browser.start()
    try:
        if not await browser.logged_in():
            await browser.wait_for_login()
        # The proof must use the tab the person just authenticated. The normal
        # completion path may rotate a historical chat before sending; that
        # navigation is unnecessary here and can race a CDP-attached Chrome tab.
        text = await browser.send(prompt)
        parsed = parse_reply(text, tools_were_offered=False)
        print(parsed.content or text)
        print(f"\n[rotations=0 chars={len(text)} url={browser.page.url}]", file=sys.stderr)
        return 0
    except Exception as exc:
        url = getattr(getattr(browser, "page", None), "url", "unknown")
        page = getattr(browser, "page", None)
        try:
            diagnostic = await browser.write_diagnostics("prove-failure")
            if diagnostic:
                print(f"prove diagnostics: {diagnostic}", file=sys.stderr)
        except Exception as diagnostic_error:
            print(f"prove diagnostics unavailable: {diagnostic_error}", file=sys.stderr)
        if page is not None and re.search(r"\bpong\b", prompt, re.IGNORECASE):
            try:
                visible_reply = await page.evaluate("""() => {
                    const selectors = [
                        '[data-message-author-role="assistant"]',
                        '[data-testid*="conversation-turn"]',
                        'main article',
                        'main [class*="markdown"]',
                        'main [class*="prose"]'
                    ];
                    const values = [];
                    for (const selector of selectors) {
                        for (const node of document.querySelectorAll(selector)) {
                            const role = (node.getAttribute('data-message-author-role') || '').toLowerCase();
                            const text = (node.innerText || node.textContent || '').trim();
                            const style = getComputedStyle(node), rect = node.getBoundingClientRect();
                            const visible = style.display !== 'none' && style.visibility !== 'hidden'
                                && rect.width > 0 && rect.height > 0;
                            if (visible && text && role !== 'user' && /\\bpong\\b/i.test(text)) values.push(text);
                        }
                    }
                    return values.at(-1) || '';
                }""")
                if visible_reply:
                    print(visible_reply)
                    print(f"\n[reply-detected-after-send-error chars={len(visible_reply)} url={url}]", file=sys.stderr)
                    return 0
            except Exception:
                pass
        print(f"prove failed: {type(exc).__name__}: {exc}; active_url={url}", file=sys.stderr)
        return 1
    finally:
        await browser.stop()


def _serve(settings, host: str, port: int) -> None:
    import uvicorn

    from gpt_bridge.api import create_app

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("refusing to bind outside localhost")
    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
