from __future__ import annotations


class MockBackend:
    """Returns a fixed reply. It does not talk to ChatGPT."""

    def __init__(self):
        self.broken = False
        self.prompts: list[str] = []
        self.url = "mock://chat"
        self.models = ["GPT-6.1 Sol", "GPT-6.1 Terra", "Luna"]
        self.selected_model = "GPT-6.1 Sol"
        self.profile_dir = None
        self.opened: list[str] = []
        self._logged_in = True

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def status(self) -> dict:
        return {
            "browser": "mock",
            "logged_in": self._logged_in,
            "chat_url": self.url,
            "healthy": not self.broken,
            "forced_broken": self.broken,
        }

    async def logged_in(self) -> bool:
        return self._logged_in

    async def use_profile(self, profile_dir) -> None:
        from pathlib import Path

        self.profile_dir = Path(profile_dir)
        self.opened.append(str(self.profile_dir))
        self._logged_in = (self.profile_dir / "signed-in").exists()
        self.url = "mock://chat" if self._logged_in else "mock://login"
        self.prompts.clear()
        self.broken = False

    async def wait_for_login(self) -> None:
        return None

    async def healthy(self) -> bool:
        return not self.broken

    async def has_history(self) -> bool:
        return bool(self.prompts) and not self.broken

    async def mark_broken(self) -> None:
        self.broken = True

    async def rotate(self) -> str:
        self.broken = False
        self.prompts.clear()
        self.url = "mock://chat/new"
        return self.url

    async def logout(self) -> dict:
        self.prompts.clear()
        self.broken = False
        self.url = "mock://logged-out"
        return await self.status()

    async def open_login_page(self) -> None:
        self.url = "mock://login"

    async def list_chats(self) -> list[dict]:
        return [{"url": "https://chatgpt.com/c/mock", "title": "Mock chat"}]

    async def list_models(self) -> dict:
        return {
            "current": self.selected_model,
            "models": [
                {"name": name, "selected": name == self.selected_model}
                for name in self.models
            ],
        }

    async def select_model(self, name: str) -> dict:
        from gpt_bridge.session import ChatFailure

        match = next((item for item in self.models if item.lower() == name.strip().lower()), None)
        if match is None:
            raise ChatFailure(f"model not in the menu: {name}")
        self.selected_model = match
        return {"selected": match, "current": match}

    async def switch_chat(self, url: str) -> str:
        self.url = url
        self.broken = False
        return url

    async def send(self, prompt: str) -> str:
        from gpt_bridge.session import ChatFailure

        if self.broken:
            raise ChatFailure("marked broken")
        self.prompts.append(prompt)
        return json_echo(prompt)


def json_echo(prompt: str) -> str:
    import json

    preview = prompt[-180:].replace("\n", " ")
    return json.dumps(
        {
            "content": f"mock reply. prompt tail: {preview}",
            "tool_calls": [],
        },
        ensure_ascii=False,
    )
