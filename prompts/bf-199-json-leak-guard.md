# BF-199: Ward Room JSON Leak Guard

**Priority:** High (user-visible)  
**Related:** BF-172 (proactive intent JSON guard), BF-191 (evaluate intent JSON guard), BF-174 (bracket marker stripping)

## Problem

Raw JSON from the cognitive sub-task chain leaks into Ward Room posts. Observed: Keiko's `[Observation]` post in Medical contained:

```
{"output": "I've noticed an interesting pattern...", "revised": true, "reflection": "The observation..."}
```

instead of the extracted text.

## Root Cause

The reflect sub-task (`cognitive/sub_tasks/reflect.py`) prompts the LLM to return `{"output": "...", "revised": true/false, "reflection": "..."}`. Parse logic at reflect.py:381-410 uses `extract_json()` to extract `parsed["output"]`. When:

1. Reflect's `extract_json` fails on an edge case → fallback returns raw text including JSON (line 394-400)
2. OR compose produces JSON (LLM mode confusion) and reflect is skipped (required=False)

...the raw JSON propagates through the chain result extraction (cognitive_agent.py:1642-1664) to `act()` → `IntentResult.result` → posting boundary.

**Existing guards don't catch this:**
- BF-172 (proactive.py:664-673): only catches `"intents"` JSON
- BF-191 (evaluate.py:295-303): only catches `"intents"/"intent"` JSON
- BF-174 (ward_room_router.py:633-635): bracket marker stripping only
- ward_room_router.py has **zero** JSON guards

## Fix

Add a shared extraction helper and apply it at the two Ward Room posting boundaries.

### 1. Add `sanitize_ward_room_text()` to `src/probos/utils/text_sanitize.py`

Create new file (or add to existing utils if a text utils file exists — check first).

```python
"""BF-199: Sanitize text before Ward Room posting."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# JSON field signatures from cognitive sub-task chain outputs.
# Reflect: {"output": "...", "revised": ..., "reflection": "..."}
# Evaluate: {"pass": ..., "score": ..., "criteria": ..., "recommendation": "..."}
_CHAIN_JSON_SIGNATURES = ('"output"', '"pass"', '"score"', '"criteria"')


def sanitize_ward_room_text(text: str) -> str:
    """Extract human-readable text from potentially JSON-wrapped chain output.

    Defense-in-depth guard at the Ward Room posting boundary.
    If the text looks like leaked chain JSON, extract the readable
    content. Otherwise return as-is.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text

    # Quick check: does this look like chain JSON?
    head = stripped[:200]
    if not any(sig in head for sig in _CHAIN_JSON_SIGNATURES):
        return text

    # Attempt extraction
    try:
        from probos.utils.json_extract import extract_json

        parsed = extract_json(stripped)
    except (ValueError, TypeError):
        return text

    if not isinstance(parsed, dict):
        return text

    # Reflect JSON → extract "output"
    if "output" in parsed and isinstance(parsed["output"], str):
        extracted = parsed["output"].strip()
        if extracted:
            logger.warning(
                "BF-199: Extracted text from leaked reflect JSON (%d → %d chars)",
                len(stripped),
                len(extracted),
            )
            return extracted

    # Evaluate JSON → suppress entirely (not human-readable)
    if "pass" in parsed and "score" in parsed:
        logger.warning("BF-199: Suppressed leaked evaluate JSON (%d chars)", len(stripped))
        return ""

    return text
```

### 2. Apply in `src/probos/proactive.py` at line ~587

After:
```python
        response_text = str(result.result).strip()
```

Add:
```python
        # BF-199: Extract text from leaked chain JSON
        from probos.utils.text_sanitize import sanitize_ward_room_text
        response_text = sanitize_ward_room_text(response_text)
```

### 3. Apply in `src/probos/ward_room_router.py` at line ~589

After:
```python
            response_text = str(result.result).strip()
```

Add:
```python
            # BF-199: Extract text from leaked chain JSON
            from probos.utils.text_sanitize import sanitize_ward_room_text
            response_text = sanitize_ward_room_text(response_text)
```

## Files Changed

| File | Change |
|------|--------|
| `src/probos/utils/text_sanitize.py` | **NEW** — `sanitize_ward_room_text()` shared helper |
| `src/probos/proactive.py` | Add sanitize call after line 587 |
| `src/probos/ward_room_router.py` | Add sanitize call after line 589 |
| `tests/test_bf199_json_leak_guard.py` | **NEW** — tests |

## Tests (`tests/test_bf199_json_leak_guard.py`)

### `sanitize_ward_room_text` unit tests
1. **test_plain_text_passthrough** — Normal text returns unchanged
2. **test_reflect_json_extracts_output** — `{"output": "Hello", "revised": true, "reflection": "..."}` → `"Hello"`
3. **test_evaluate_json_suppressed** — `{"pass": true, "score": 0.8, ...}` → `""`
4. **test_non_chain_json_passthrough** — `{"foo": "bar"}` → unchanged (not chain JSON)
5. **test_malformed_json_passthrough** — `{"output": broken` → unchanged (extract_json fails gracefully)
6. **test_empty_output_field** — `{"output": "", "revised": false}` → unchanged (empty output, keep original)
7. **test_nested_json_in_output** — Output field containing JSON-like text preserved correctly
8. **test_whitespace_prefix** — `  {"output": "text"}` → `"text"` (stripped before check)

### Integration smoke tests
9. **test_proactive_sanitizes_response** — Mock chain returning reflect JSON → Ward Room post gets clean text
10. **test_ward_room_router_sanitizes_response** — Same for ward_room_router path

## Engineering Principles

- **SRP:** Sanitization logic in dedicated utility, not duplicated in two callers
- **DRY:** Shared `sanitize_ward_room_text()` used by both proactive.py and ward_room_router.py
- **Defense in Depth:** Boundary guard at posting layer supplements chain-internal parsing (reflect.py). Multiple layers: reflect parses → chain extraction picks output → posting boundary sanitizes
- **Fail Fast:** Logs warning on JSON leak detection for observability
- **OCP:** `_CHAIN_JSON_SIGNATURES` tuple extensible for future chain output formats

## Deferred

- `experience/commands/session.py:125` and `routers/agents.py:196` also do `str(result.result)` but output to shell, not Ward Room. Lower risk, not included in this fix.
- Root cause in reflect.py fallback path (line 394-400) could be hardened separately — this BF is the boundary guard.

## Builder Instructions

```
Read and execute the build prompt in d:\ProbOS\prompts\bf-199-json-leak-guard.md
```

Run targeted tests after:
```
python -m pytest tests/test_bf199_json_leak_guard.py -v
```
