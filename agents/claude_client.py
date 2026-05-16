"""Shared Claude API helpers with retries and JSON extraction."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import anthropic

from config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    LLM_RETRY_BASE_SECONDS,
    MAX_LLM_RETRIES,
)


def _strip_json_fence(text: str) -> str:
    """Remove optional markdown code fences from a model response.

    Args:
        text: Raw assistant text.

    Returns:
        JSON-looking string suitable for json.loads.
    """
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*)\s*```$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped


def call_claude_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call Claude and parse a strict JSON object from the reply.

    Args:
        system_prompt: Full system instructions (no API secrets).
        user_prompt: User message (document excerpts, schemas, etc.).

    Returns:
        Parsed JSON object.

    Raises:
        anthropic.APIError: After retries are exhausted.
        json.JSONDecodeError: If the model output is not valid JSON.
        RuntimeError: If ANTHROPIC_API_KEY is missing.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    attempt = 0
    last_error: Exception | None = None
    while attempt <= MAX_LLM_RETRIES:
        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            blocks = getattr(message, "content", []) or []
            texts = [
                b.text
                for b in blocks
                if getattr(b, "type", None) == "text" and getattr(b, "text", None)
            ]
            raw = "\n".join(texts)
            return json.loads(_strip_json_fence(raw))
        except anthropic.APIError as exc:
            last_error = exc
            attempt += 1
            if attempt > MAX_LLM_RETRIES:
                break
            sleep_for = LLM_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            sleep_for += random.uniform(0, 0.35)
            time.sleep(sleep_for)
        except json.JSONDecodeError:
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Claude call failed without a specific error.")
