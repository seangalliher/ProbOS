# AD-401: Structured LLM Output Validation with Auto-Retry

## Context

Every CognitiveAgent that expects structured LLM output uses ad-hoc `json.loads()` with manual error handling. There is:
- **Zero retry logic** anywhere in the codebase
- **No OpenAI-style `response_format`** support
- **No shared JSON extraction** — each agent re-implements markdown fence stripping and brace matching

The decomposer is the highest-risk parsing point: every user request flows through it, and a parse failure means a **silent empty response** with no retry.

## Scope — Phase 1: Shared Infrastructure + Decomposer Retrofit

This AD builds the shared validation/retry infrastructure and retrofits the two most critical parsing sites: the **Decomposer** and **CodeReviewer**. Other agents will be migrated in follow-on ADs.

## Part 1: Shared JSON Extraction Utility

### Create `src/probos/utils/json_extract.py`

Extract and generalize the decomposer's `_extract_json()` (currently at `decomposer.py:493-521`) into a shared utility.

```python
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

    # Find first { and do brace-depth matching
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
```

**Key improvement over the existing `_extract_json()`:** The brace-depth matcher now tracks `in_string` and `escape_next` state, so JSON values containing `{` or `}` inside strings don't break extraction.

## Part 2: Retry-on-Parse-Failure Utility

### Add to `src/probos/utils/json_extract.py`

```python
async def complete_with_retry(
    llm_client: Any,
    request: Any,
    parse_fn: callable,
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
```

**Design decisions:**
- `parse_fn` is a callable, not a Pydantic model. This keeps it simple and works with both JSON-based and delimiter-based agents.
- Temperature bumps slightly on retry (0.0 → 0.1 → 0.2) to get a different response, capped at 0.5.
- The error message from the failed parse is sent back to the LLM as feedback.
- `max_retries=1` by default (2 total attempts) — one retry is enough to fix most formatting issues without wasting tokens.

## Part 3: Retrofit the Decomposer

### Modify `src/probos/cognitive/decomposer.py`

**3a.** Replace the inline `_extract_json()` method (lines 493-521) with a call to the shared utility. Keep the method as a thin wrapper for backwards compatibility within the class:

```python
def _extract_json(self, content: str) -> str:
    """Extract JSON from LLM response. Delegates to shared utility."""
    from probos.utils.json_extract import extract_json
    result = extract_json(content)
    return json.dumps(result)  # _parse_response expects a JSON string
```

Wait — that's wasteful (parse then re-serialize). Better approach: refactor `_parse_response()` directly.

**3b.** Refactor `_parse_response()` (lines 437-491) to use `extract_json()` directly:

Replace the current parsing:
```python
json_str = self._extract_json(content)
data = json.loads(json_str)
```

With:
```python
from probos.utils.json_extract import extract_json
data = extract_json(content)
```

**3c.** Add retry to the decomposer's LLM call. In `decompose()`, where the LLM is called (find the `await self._llm_client.complete(request)` call), wrap it with `complete_with_retry()`:

Find the LLM call in `decompose()` and replace:
```python
response = await self._llm_client.complete(request)
# ... followed by _parse_response(response.content, ...)
```

With:
```python
from probos.utils.json_extract import complete_with_retry, extract_json

def _validate_decomposition(content: str) -> dict:
    """Parse and validate decomposition response."""
    data = extract_json(content)
    if not isinstance(data, dict) or "intents" not in data:
        raise ValueError("Response missing 'intents' key")
    if not isinstance(data["intents"], list):
        raise ValueError("'intents' is not a list")
    return data

try:
    data, response = await complete_with_retry(
        self._llm_client,
        request,
        _validate_decomposition,
        max_retries=1,
    )
    # Build TaskDAG from validated data (move existing node-building logic here)
except ValueError as exc:
    logger.warning("Decomposer parse failed after retry: %s", exc)
    return TaskDAG(source_text=source_text)
```

**Important:** Keep all the post-parse validation that currently exists (credential URL rejection, `_CREDENTIAL_PARAMS` check, etc.) — just move it after the retry loop.

**3d.** Delete the now-unused `_extract_json()` method from the Decomposer class.

## Part 4: Retrofit the Code Reviewer

### Modify `src/probos/cognitive/code_reviewer.py`

Replace the inline JSON parsing (lines 142-155) with:

```python
from probos.utils.json_extract import extract_json

try:
    data = extract_json(text)
    result.approved = data.get("approved", False)
    result.issues = data.get("issues", [])
    result.suggestions = data.get("suggestions", [])
    result.summary = data.get("summary", "")
except (ValueError, json.JSONDecodeError):
    # Text-based fallback (existing logic)
    result.approved = "no issues" in text.lower() or "looks good" in text.lower()
    result.summary = text[:500]
```

No retry needed here — the text fallback is fine for code review.

## Part 5: Retrofit the Research Agent

### Modify `src/probos/cognitive/research.py`

Replace the inline JSON parsing (line 151) with:

```python
from probos.utils.json_extract import extract_json_list

try:
    queries = extract_json_list(response.content)
    return [str(q) for q in queries[:3]]
except (ValueError, json.JSONDecodeError, TypeError):
    return []
```

## What NOT to Change (Yet)

- **Builder `act()`** — uses delimiter-based parsing (`===FILE:===`), not JSON. Different problem, different solution (future AD).
- **Architect `act()`** — uses delimiter-based parsing (`===PROPOSAL===`). Same.
- **Scout `act()`** — uses delimiter-based parsing (`===SCOUT_REPORT===`). Same.
- **Surgeon `act()`** — low traffic, already handles failures gracefully. Can be migrated later.
- **Bundled agents** — low priority, already have text fallbacks.
- **`response_format` on LLMRequest** — desirable but requires Copilot proxy changes. Future AD.

## Files Modified/Created

| File | Change |
|------|--------|
| `src/probos/utils/json_extract.py` | **NEW** — shared `extract_json()`, `extract_json_list()`, `complete_with_retry()` |
| `src/probos/cognitive/decomposer.py` | Retrofit `_parse_response()` to use shared utility + add retry to `decompose()` |
| `src/probos/cognitive/code_reviewer.py` | Retrofit JSON parsing to use shared utility |
| `src/probos/cognitive/research.py` | Retrofit JSON parsing to use shared utility |

## Testing

### New tests in `tests/test_json_extract.py`:

1. **`extract_json` — clean JSON:** `'{"key": "value"}' → {"key": "value"}`
2. **`extract_json` — markdown fences:** ` ```json\n{"key": "value"}\n``` ` → parse succeeds
3. **`extract_json` — preamble text:** `"Here is the result: {\"key\": \"value\"}"` → parse succeeds
4. **`extract_json` — think blocks:** `"<think>reasoning</think>{\"key\": \"value\"}"` → parse succeeds
5. **`extract_json` — braces in strings:** `'{"code": "if (x) { y }"}'` → parse succeeds (the key improvement)
6. **`extract_json` — no JSON:** `"just plain text"` → raises ValueError
7. **`extract_json_list` — JSON array:** `'["a", "b", "c"]'` → ["a", "b", "c"]
8. **`complete_with_retry` — success first try:** Mock LLM returns valid JSON → parsed immediately, no retry
9. **`complete_with_retry` — success on retry:** Mock LLM returns garbage first, valid JSON second → parsed on retry
10. **`complete_with_retry` — all failures:** Mock LLM returns garbage both times → raises ValueError
11. **`complete_with_retry` — retry prompt includes error:** Verify the retry request prompt contains the parse error message

### Regression: run full suite
```
uv run pytest tests/ --tb=short
```

All 2779+ tests should pass.

## Commit Message

```
Add structured LLM output validation with auto-retry (AD-401)

Shared json_extract utility: extract_json() with string-aware brace
matching, extract_json_list(), complete_with_retry() with parse-error
feedback to LLM. Retrofit decomposer (highest-risk parsing — every user
request), code_reviewer, and research agent. One retry on parse failure
with temperature bump and error feedback. Eliminates silent empty
responses from malformed LLM output.
```
