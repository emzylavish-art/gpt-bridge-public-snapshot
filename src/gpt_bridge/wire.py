from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

from gpt_bridge.protocol import ParsedReply


def completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def estimate_tokens(*parts: str) -> int:
    total = sum(len(part) for part in parts)
    return max(1, total // 4) if total else 0


def usage_for(prompt: str, reply: ParsedReply) -> dict[str, int]:
    completion = reply.content or ""
    for call in reply.tool_calls:
        completion += call["function"]["name"] + call["function"]["arguments"]
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(completion)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def message_from(reply: ParsedReply) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": reply.content}
    if reply.tool_calls:
        message["tool_calls"] = reply.tool_calls
        if reply.content is None:
            message["content"] = None
    return message


def completion_body(
    reply: ParsedReply,
    *,
    model: str,
    prompt: str,
    response_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": response_id or completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message_from(reply),
                "finish_reason": reply.finish_reason,
            }
        ],
        "usage": usage_for(prompt, reply),
    }


def _chunk(
    response_id: str,
    model: str,
    created: int,
    delta: dict[str, Any],
    finish_reason: str | None,
) -> dict[str, Any]:
    # Never include reasoning_content. An empty string makes some clients
    # render one token per line. Tool calls are emitted whole, with id and
    # function together, because split name/argument deltas get dropped.
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish_reason}
        ],
    }


def sse_chunks(reply: ParsedReply, *, model: str, prompt: str) -> Iterator[dict[str, Any]]:
    response_id = completion_id()
    created = int(time.time())
    yield _chunk(response_id, model, created, {"role": "assistant"}, None)
    content = reply.content or ""
    step = 80
    for start in range(0, len(content), step):
        yield _chunk(
            response_id,
            model,
            created,
            {"content": content[start : start + step]},
            None,
        )
    for index, call in enumerate(reply.tool_calls):
        yield _chunk(
            response_id,
            model,
            created,
            {
                "tool_calls": [
                    {
                        "index": index,
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["function"]["name"],
                            "arguments": call["function"]["arguments"],
                        },
                    }
                ]
            },
            None,
        )
    yield _chunk(response_id, model, created, {}, reply.finish_reason)
    yield {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
        "usage": usage_for(prompt, reply),
    }


def sse_lines(reply: ParsedReply, *, model: str, prompt: str) -> Iterator[str]:
    for chunk in sse_chunks(reply, model=model, prompt=prompt):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
