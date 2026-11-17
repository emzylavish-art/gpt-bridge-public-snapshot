from __future__ import annotations

import json
import re
from pathlib import Path

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$")
OWNER_LABEL = "Adrian"


class AccountNameError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AccountRegistry:
    """Labels and folder names only. Never cookies, tokens, or passwords."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "registry.json"

    def list_accounts(self) -> dict:
        data = self._load()
        active = data.get("active")
        return {
            "active": active,
            "accounts": [
                {"label": item["label"], "active": item["label"] == active}
                for item in data["accounts"]
            ],
        }

    def add(self, label: str) -> dict:
        clean = self._clean(label)
        data = self._load()
        if any(item["label"].lower() == clean.lower() for item in data["accounts"]):
            raise AccountNameError(f"account already exists: {clean}")
        folder = self.root / _slug(clean)
        folder.mkdir(parents=True, exist_ok=True)
        data["accounts"].append({"label": clean})
        data["active"] = clean
        self._save(data)
        return {"label": clean, "created": True}

    def use(self, label: str) -> Path:
        clean = self._clean(label)
        data = self._load()
        match = next((item for item in data["accounts"] if item["label"].lower() == clean.lower()), None)
        if match is None:
            raise AccountNameError(f"unknown account: {clean}")
        data["active"] = match["label"]
        self._save(data)
        return self.profile_dir(match["label"])

    def profile_dir(self, label: str) -> Path:
        return self.root / _slug(self._clean(label))

    def active_profile(self) -> Path | None:
        active = self._load().get("active")
        if not active:
            return None
        return self.profile_dir(active)

    def adopt_legacy(self, legacy_dir: Path) -> None:
        """Move an already-used single profile into the first account folder.

        The registry still stores only the label. Cookie files stay in the
        profile folder and are not copied into the JSON.
        """

        data = self._load()
        if data["accounts"] or not legacy_dir.is_dir():
            return
        try:
            has_files = any(legacy_dir.iterdir())
        except OSError:
            return
        if not has_files:
            return
        target = self.root / _slug(OWNER_LABEL)
        if target.exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        legacy_dir.rename(target)
        self._save({"active": OWNER_LABEL, "accounts": [{"label": OWNER_LABEL}]})

    def claim_sole_owner(self) -> None:
        """Rename a lone default account to Adrian. Cookie files stay in the folder."""

        data = self._load()
        if data["accounts"] != [{"label": "default"}]:
            return
        old = self.root / "default"
        new = self.root / _slug(OWNER_LABEL)
        if old.exists() and not new.exists():
            old.rename(new)
        self._save({"active": OWNER_LABEL, "accounts": [{"label": OWNER_LABEL}]})

    def _clean(self, label: str) -> str:
        clean = " ".join((label or "").split())
        if not LABEL_RE.fullmatch(clean):
            raise AccountNameError("label must be letters, numbers, spaces, or hyphens")
        return clean

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"active": None, "accounts": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"active": None, "accounts": []}
        accounts = []
        for item in data.get("accounts") or []:
            label = item.get("label") if isinstance(item, dict) else None
            if isinstance(label, str) and LABEL_RE.fullmatch(label):
                accounts.append({"label": label})
        active = data.get("active")
        if not any(item["label"] == active for item in accounts):
            active = None
        return {"active": active, "accounts": accounts}

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        body = {
            "active": data.get("active"),
            "accounts": [{"label": item["label"]} for item in data.get("accounts") or []],
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _slug(label: str) -> str:
    return "-".join(label.lower().split())
