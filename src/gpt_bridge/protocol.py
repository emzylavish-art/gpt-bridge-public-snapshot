from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


CONTRACT = """You are the reasoning model for a local coding agent. You cannot touch the disk, the shell, or the editor. The agent harness executes tools. You only decide.

Reply with one JSON object and nothing else. No markdown fences. No preamble.

{"content": string or null, "tool_calls": [{"name": string, "arguments": object}]}

Rules:
- Use only tool names from the tool list in this request.
- arguments must be a JSON object, not a string.
- If you need a tool, put it in tool_calls. Keep content short or null.
- If you are answering the user, set tool_calls to [] and put the answer in content.
- Do not invent tool results. Wait for them to come back in a later message.
"""

REPAIR_PROMPT = (
    "Your previous reply was not one JSON object in the required shape. "
    'Reply again with only {"content": string or null, "tool_calls": '
    '[{"name": string, "arguments": object}]}. No markdown fences.'
)


@dataclass
class ParsedReply:
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    needs_repair: bool = False
    raw: str = ""

    @property
    def finish_reason(self) -> str:
        return "tool_calls" if self.tool_calls else "stop"


@dataclass
class TurnPlan:
    full_prompt: str
    delta_prompt: str | None
    continuing: bool
    message_count: int
    messages_fp: str
    tools_fp: str


def _text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                parts.append(str(part))
                continue
            kind = part.get("type")
            if kind in {"text", "input_text", "output_text"} or "text" in part:
                parts.append(str(part.get("text") or ""))
            elif kind in {"image_url", "image", "input_image"}:
                parts.append("[image omitted; this bridge is text-only in v1]")
            else:
                parts.append(json.dumps(part, ensure_ascii=False))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        return tool["function"]
    return tool


def _format_tools(tools: list[dict[str, Any]] | None) -> str:
    if not tools:
        return "(none)"
    blocks: list[str] = []
    for tool in tools:
        fn = _tool_schema(tool)
        name = fn.get("name") or "unknown"
        description = (fn.get("description") or "").strip()
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}
        blocks.append(
            "\n".join(
                [
                    f"- name: {name}",
                    f"  description: {description}",
                    "  parameters: "
                    + json.dumps(parameters, ensure_ascii=False, separators=(",", ":")),
                ]
            )
        )
    return "\n".join(blocks)


def _format_message(index: int, message: dict[str, Any]) -> str:
    role = str(message.get("role") or "unknown")
    header = f"----- message {index} role={role}"
    if message.get("name"):
        header += f" name={message['name']}"
    if message.get("tool_call_id"):
        header += f" tool_call_id={message['tool_call_id']}"
    header += " -----"
    body = _text_from_content(message.get("content"))
    calls = message.get("tool_calls") or []
    call_lines: list[str] = []
    for call in calls:
        fn = call.get("function") or {}
        call_lines.append(
            "tool_call "
            f"id={call.get('id') or ''} "
            f"name={fn.get('name') or call.get('name') or ''} "
            f"arguments={fn.get('arguments') or call.get('arguments') or '{}'}"
        )
    chunks = [header]
    if body:
        chunks.append(body)
    if call_lines:
        chunks.append("\n".join(call_lines))
    if not body and not call_lines:
        chunks.append("(empty)")
    return "\n".join(chunks)


def _format_messages(messages: list[dict[str, Any]], start: int = 0) -> str:
    return "\n\n".join(
        _format_message(index, message) for index, message in enumerate(messages, start)
    )


def _tool_choice_line(tool_choice: Any) -> str:
    if tool_choice is None or tool_choice == "auto":
        return "Tool choice: auto. Call a tool only when it is needed."
    if tool_choice == "none":
        return "Tool choice: none. tool_calls must be an empty array."
    if tool_choice == "required":
        return "Tool choice: required. You must return at least one tool call."
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or tool_choice
        name = fn.get("name")
        if name:
            return f"Tool choice: required. You must call the tool named {name}."
    return "Tool choice: auto. Call a tool only when it is needed."


def compile_prompt(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    reasoning_effort: str | None = None,
    *,
    continuation: bool = False,
) -> str:
    effort = f"\nEffort hint: {reasoning_effort}." if reasoning_effort else ""
    choice = _tool_choice_line(tool_choice)
    if continuation:
        return (
            "Continue the same agent session. The tool list has not changed. "
            "Apply the same JSON reply contract as before.\n"
            f"{choice}{effort}\n\n"
            "New messages since your last reply:\n\n"
            f"{_format_messages(messages)}\n\n"
            "Reply with one JSON object only."
        )
    return (
        f"{CONTRACT}\n"
        f"{choice}{effort}\n\n"
        "===== TOOLS =====\n"
        f"{_format_tools(tools)}\n\n"
        "===== TRANSCRIPT =====\n"
        f"{_format_messages(messages)}\n"
        "===== END TRANSCRIPT =====\n\n"
        "Reply with one JSON object only."
    )


def fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    reasoning_effort: str | None,
    prior: dict[str, Any] | None,
) -> TurnPlan:
    tools = tools or []
    messages_fp = fingerprint(messages)
    tools_fp = fingerprint(tools)
    full = compile_prompt(
        messages,
        tools,
        tool_choice,
        reasoning_effort,
        continuation=False,
    )
    delta = None
    continuing = False
    if prior:
        prior_count = int(prior.get("message_count") or 0)
        prefix = messages[:prior_count]
        continuing = (
            prior.get("tools_fp") == tools_fp
            and prior_count > 0
            and prior_count < len(messages)
            and prior.get("messages_fp") == fingerprint(prefix)
        )
        if continuing:
            delta = compile_prompt(
                messages[prior_count:],
                tools,
                tool_choice,
                reasoning_effort,
                continuation=True,
            )
    return TurnPlan(
        full_prompt=full,
        delta_prompt=delta,
        continuing=continuing,
        message_count=len(messages),
        messages_fp=messages_fp,
        tools_fp=tools_fp,
    )


def _iter_objects(text: str):
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
        index = end


def _is_contract(obj: dict[str, Any]) -> bool:
    if "tool_calls" in obj:
        return True
    return "content" in obj and "parameters" not in obj and "name" not in obj


def _is_bare_call(obj: dict[str, Any]) -> bool:
    return "name" in obj and "arguments" in obj and "parameters" not in obj


def _normalize_call(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    fn = raw.get("function") if isinstance(raw.get("function"), dict) else raw
    name = fn.get("name") or raw.get("name")
    if not name or not isinstance(name, str):
        return None
    arguments = fn.get("arguments", raw.get("arguments", {}))
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        argument_text = json.dumps(parsed, ensure_ascii=False)
    elif isinstance(arguments, dict):
        argument_text = json.dumps(arguments, ensure_ascii=False)
    elif arguments is None:
        argument_text = "{}"
    else:
        return None
    call_id = raw.get("id")
    if not isinstance(call_id, str) or not call_id:
        call_id = f"call_{index}_{fingerprint({'name': name, 'arguments': argument_text})[:12]}"
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": argument_text},
    }


def parse_reply(text: str, *, tools_were_offered: bool) -> ParsedReply:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    contracts = [obj for obj in _iter_objects(stripped) if _is_contract(obj)]
    bare = [obj for obj in _iter_objects(stripped) if _is_bare_call(obj)]
    if contracts:
        chosen = contracts[-1]
        content = chosen.get("content")
        content_text = None if content is None else _text_from_content(content) or None
        calls = []
        for index, raw in enumerate(chosen.get("tool_calls") or []):
            if isinstance(raw, dict):
                normalized = _normalize_call(raw, index)
                if normalized is None:
                    return ParsedReply(
                        content=stripped,
                        needs_repair=True,
                        raw=text,
                    )
                calls.append(normalized)
        return ParsedReply(content=content_text, tool_calls=calls, raw=text)
    if bare and not contracts:
        calls = []
        for index, raw in enumerate(bare):
            normalized = _normalize_call(raw, index)
            if normalized:
                calls.append(normalized)
        if calls:
            return ParsedReply(content=None, tool_calls=calls, raw=text)
    return ParsedReply(
        content=stripped or None,
        needs_repair=tools_were_offered and bool(stripped),
        raw=text,
    )
