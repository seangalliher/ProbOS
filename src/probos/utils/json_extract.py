"""Robust JSON extraction from LLM responses.

Handles common LLM output quirks: markdown code fences, <think> blocks,
preamble text before JSON, trailing text after JSON.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_json(content: str) -> dict[str, Any]:
    """Extract and parse a JSON object from LLM response text.

    Handles:
    - Markdown ```json ... ``` code fences
    - <think>...</think> reasoning blocks (qwen, reasoning models)
    - Preamble text before JSON ("Here is the result: {...}")
    - Trailing text after JSON
    - Nested braces within JSON strings

    Returns the parsed dict.
    Raises ValueError if no valid JSON object can be extracted.
    """
    # Strip <think>...</think> blocks
    cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

    # Try markdown code fence extraction first
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass  # Fall through to other methods

    # Try the full cleaned content as JSON
    stripped = cleaned.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Find first { and do brace-depth matching (string-aware)
    brace_start = cleaned.find("{")
    if brace_start >= 0:
        depth = 0
        in_string = False
        escape_next = False
        for i in range(brace_start, len(cleaned)):
            ch = cleaned[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = cleaned[brace_start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass  # Keep looking

    raise ValueError(f"No valid JSON object found in response ({len(content)} chars)")


def extract_json_list(content: str) -> list[Any]:
    """Extract and parse a JSON array from LLM response text.

    Same extraction logic as extract_json() but expects a list.
    Raises ValueError if no valid JSON array can be extracted.
    """
    cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

    # Try markdown code fence
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
    if code_block:
        try:
            result = json.loads(code_block.group(1).strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Try raw content
    stripped = cleaned.strip()
    if stripped.startswith("["):
        try:
            result = json.loads(stripped)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON array found in response ({len(content)} chars)")


async def complete_with_retry(
    llm_client: Any,
    request: Any,
    parse_fn: Any,
    max_retries: int = 1,
    *,
    retry_prompt: str = "",
) -> tuple[Any, Any]:
    """Call the LLM and validate the response. Retry on parse failure.

    Args:
        llm_client: The LLM client to use for completion.
        request: The LLMRequest to send.
        parse_fn: A callable that takes the response content string
                  and returns the parsed result. Should raise ValueError
                  or json.JSONDecodeError on failure.
        max_retries: Maximum number of retries on parse failure (default 1).
        retry_prompt: Additional instruction appended to the prompt on retry.
                      If empty, a default message is used.

    Returns:
        (parsed_result, llm_response) tuple. parsed_result is the output
        of parse_fn. llm_response is the raw LLMResponse.

    Raises:
        ValueError: If all attempts fail to produce parseable output.
    """
    last_error = None

    for attempt in range(1 + max_retries):
        response = await llm_client.complete(request)

        if response.error:
            last_error = ValueError(f"LLM error: {response.error}")
            continue

        try:
            parsed = parse_fn(response.content)
            return parsed, response
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "LLM output parse failed (attempt %d/%d): %s",
                attempt + 1, 1 + max_retries, exc,
            )

            if attempt < max_retries:
                # Build retry prompt with error feedback
                error_feedback = retry_prompt or (
                    "\n\nYour previous response could not be parsed. "
                    f"Error: {exc}\n"
                    "Please respond with ONLY a valid JSON object, "
                    "no markdown fences, no preamble text."
                )
                # Clone request with appended error feedback
                from probos.types import LLMRequest
                request = LLMRequest(
                    prompt=request.prompt + error_feedback,
                    system_prompt=request.system_prompt,
                    tier=request.tier,
                    temperature=min(request.temperature + 0.1, 0.5),
                    max_tokens=request.max_tokens,
                )

    raise last_error or ValueError("All parse attempts failed")
