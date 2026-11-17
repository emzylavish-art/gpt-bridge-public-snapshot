from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("gpt_bridge")
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file = RotatingFileHandler(
        log_dir / "bridge.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file.setFormatter(formatter)
    root.addHandler(stream)
    root.addHandler(file)


class Journal:
    max_bytes = 1_000_000
    backup_count = 3

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_path = log_dir / "prompts.jsonl"
        self.rotation_path = log_dir / "rotations.jsonl"

    def prompt(
        self,
        *,
        model: str,
        prompt: str,
        reply: str,
        rotations: int,
        used_delta: bool,
        stream: bool,
    ) -> None:
        self._append(
            self.prompt_path,
            {
                "ts": _now(),
                "model": model,
                "chars": len(prompt),
                "rotations": rotations,
                "used_delta": used_delta,
                "stream": stream,
                "prompt": prompt,
                "reply": reply,
            },
        )

    def rotation(self, *, reason: str, url: str) -> None:
        self._append(self.rotation_path, {"ts": _now(), "reason": reason, "url": url})

    def recent_rotations(self, limit: int = 20) -> list[dict]:
        if not self.rotation_path.is_file():
            return []
        lines = self.rotation_path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        records.reverse()
        return records

    def _append(self, path: Path, record: dict) -> None:
        self._rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self, path: Path) -> None:
        if not path.is_file() or path.stat().st_size < self.max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{self.backup_count}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backup_count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            target = path.with_name(f"{path.name}.{index + 1}")
            if source.exists():
                source.replace(target)
        path.replace(path.with_name(f"{path.name}.1"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
