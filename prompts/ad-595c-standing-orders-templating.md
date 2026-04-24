# AD-595c: Standing Orders Templating — Billet-Aware Instructions

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry must be built first)
**Files:** `src/probos/cognitive/standing_orders.py`, `src/probos/startup/finalize.py`, `tests/test_ad595c_billet_templating.py` (NEW)

## Problem

Standing orders reference billets by hardcoded title strings: "the Chief Engineer", "the Chief Science Officer", "the Operations Chief". When agents read these instructions, the titles are abstract — they don't know *who* currently holds that billet. The Data Analyst's orders say "Escalate anomalies to the Chief Science Officer" but the agent doesn't know if that's Meridian, Atlas, or someone else.

After AD-595a gives us `BilletRegistry.resolve()`, standing orders can resolve billet references to current callsigns at composition time, making instructions concrete: "Escalate anomalies to Meridian (Chief Science Officer)".

## Design

Add a **template substitution step** to `compose_instructions()` that processes `{Billet Title}` patterns in standing orders text:

- `{Chief Engineer}` → `LaForge (Chief Engineer)` (if billet filled)
- `{Chief Engineer}` → `Chief Engineer (vacant)` (if billet vacant — explicit signal)

The substitution happens **after** all tiers are loaded and concatenated, as a post-processing pass. This means:
- No changes to standing orders `.md` files are required (existing hardcoded references keep working)
- Authors can optionally wrap billet titles in `{}` for dynamic resolution
- New standing orders written by agents (tier 5) can also use templates

**Template syntax:**
- `{Title}` — matches a billet title (case-insensitive lookup)
- Only processes tokens inside `{}` that match a known billet title
- Non-matching `{tokens}` are left unchanged (safe for markdown, code blocks, etc.)

**Vacant billet UX:** Vacant billets render as `Title (vacant)` — not just the bare title. This gives agents an explicit signal that the billet is empty, so they know to escalate up the chain rather than attempting a message to a non-existent holder.

**Known limitation:** Inline backtick-wrapped billet references (`` `{Chief Engineer}` ``) are detected and skipped. However, multi-backtick inline code spans are not handled. Standing orders authors should avoid putting `{Title}` inside inline code. This is documented in DECISIONS.md.

## What This Does NOT Change

- Standing orders `.md` file contents — no changes to existing files (the builder should NOT edit .md files in config/)
- `compose_instructions()` signature — unchanged (uses module-level `_billet_registry`, no new parameters)
- Standing orders tier hierarchy (1–7) — unchanged
- Personality block building — unchanged
- Directive store integration — unchanged
- Skill catalog integration — unchanged
- `_load_file()` caching — unchanged

---

## Section 1: Add billet template resolution function

**File:** `src/probos/cognitive/standing_orders.py`

### 1a: Add `import re` at module top

Add after the existing stdlib imports (after `import logging`, around line 15):

```python
import re
```

### 1b: Add module-level registry and setter

Add after `clear_cache()` (after line 205) and before `compose_instructions()`:

```python
# Module-level BilletRegistry reference, set at startup (AD-595c).
# Module-level state — assumes single ProbOS runtime per process.
# Tests must save/restore via try/finally.
_billet_registry: "BilletRegistry | None" = None


def set_billet_registry(registry: "BilletRegistry | None") -> None:
    """Wire the BilletRegistry for template substitution (AD-595c).

    Called from finalize.py at startup. Module-level state — single-runtime
    assumption. Tests must save/restore.
    """
    global _billet_registry
    _billet_registry = registry
```

### 1c: Add the resolution function

Add immediately after `set_billet_registry()`:

```python
def _resolve_billet_templates(text: str, registry: "BilletRegistry") -> str:
    """Replace {Billet Title} patterns with resolved callsigns.

    - ``{Chief Engineer}`` → ``LaForge (Chief Engineer)`` if billet filled
    - ``{Chief Engineer}`` → ``Chief Engineer (vacant)`` if billet vacant
    - Non-matching ``{tokens}`` are left unchanged

    Only processes tokens that are 2+ chars and don't contain code-like
    characters (=, (, ), <, >, |, backtick) to avoid mangling code blocks
    or markdown. Tokens inside backtick-fenced code blocks or inline
    backtick spans are also skipped.
    """
    def _replace(match: re.Match) -> str:
        token = match.group(1)
        # Skip code-like tokens: contains =, (, ), <, >, |, backtick
        if any(c in token for c in '=()<>|`'):
            return match.group(0)
        # Skip single-char tokens
        if len(token.strip()) < 2:
            return match.group(0)
        # Skip if the match is inside backticks (inline code)
        start = match.start()
        line_start = text.rfind('\n', 0, start) + 1
        prefix = text[line_start:start]
        if '`' in prefix:
            # Count backticks before match on same line — odd count means inside inline code
            if prefix.count('`') % 2 == 1:
                return match.group(0)
        holder = registry.resolve(token.strip())
        if holder is None:
            return match.group(0)  # Not a known billet — leave unchanged
        if holder.holder_callsign:
            return f"{holder.holder_callsign} ({holder.title})"
        return f"{holder.title} (vacant)"  # Vacant — explicit signal

    # Match {content} but NOT inside backtick-fenced code blocks
    # Process line by line, skip lines inside ``` blocks
    lines = text.split('\n')
    in_code_block = False
    result_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_code_block = not in_code_block
            result_lines.append(line)
            continue
        if in_code_block:
            result_lines.append(line)
            continue
        # Process billet templates outside code blocks
        result_lines.append(re.sub(r'\{([^}]+)\}', _replace, line))
    return '\n'.join(result_lines)
```

---

## Section 2: Integrate into `compose_instructions()`

**File:** `src/probos/cognitive/standing_orders.py`

At the end of `compose_instructions()`, just before the `return` statement (line 303), add template resolution:

Current (line 303):
```python
    return "\n\n---\n\n".join(parts)
```

Change to:
```python
    composed = "\n\n---\n\n".join(parts)

    # AD-595c: Resolve billet templates
    if _billet_registry is not None:
        composed = _resolve_billet_templates(composed, _billet_registry)

    return composed
```

---

## Section 3: Wire BilletRegistry at startup

**File:** `src/probos/startup/finalize.py`

In the finalize phase, immediately after the AD-595a BilletRegistry event callback wiring block (after line 96, after `logger.info("AD-595a: BilletRegistry wired")`), add:

```python
    # AD-595c: Wire BilletRegistry into standing orders for template resolution
    if runtime.ontology and runtime.ontology.billet_registry:
        from probos.cognitive.standing_orders import set_billet_registry
        set_billet_registry(runtime.ontology.billet_registry)
        logger.info("AD-595c: Standing orders billet templating wired")
```

**Note:** This uses `runtime.ontology.billet_registry` (the property delegate from AD-595a), NOT `runtime._billet_registry` (which doesn't exist).

---

## Section 4: Update `clear_cache()` docstring

**File:** `src/probos/cognitive/standing_orders.py`

Current (lines 202–205):
```python
def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated)."""
    _load_file.cache_clear()
    _build_personality_block.cache_clear()
```

Change to:
```python
def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated).

    Note: Billet template resolution (AD-595c) is not separately cached —
    it runs as a post-processing pass on each compose_instructions() call.
    compose_instructions() is called per decide() cycle, so the regex cost
    is real (~30KB per agent per cycle). Currently sub-millisecond; if it
    shows up in profiling, add a version-keyed cache.
    """
    _load_file.cache_clear()
    _build_personality_block.cache_clear()
```

---

## Section 5: Tests

**File:** `tests/test_ad595c_billet_templating.py` (NEW)

```python
"""Tests for AD-595c: Standing orders billet template resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.standing_orders import (
    _resolve_billet_templates,
    set_billet_registry,
)


def _make_registry(billets: dict[str, tuple[str, str | None]]) -> MagicMock:
    """Create a mock BilletRegistry.

    billets: {title_or_id: (formal_title, callsign_or_None)}
    """
    from probos.ontology.billet_registry import BilletHolder

    registry = MagicMock()

    def _resolve(title_or_id: str) -> BilletHolder | None:
        key = title_or_id.strip().lower()
        for k, (title, callsign) in billets.items():
            if k.lower() == key:
                return BilletHolder(
                    billet_id=k.lower().replace(" ", "_"),
                    title=title,
                    department="test",
                    holder_agent_type="test_agent",
                    holder_callsign=callsign,
                    holder_agent_id="agent-001" if callsign else None,
                )
        return None

    registry.resolve = MagicMock(side_effect=_resolve)
    return registry


# --- Template resolution ---

class TestBilletTemplateResolution:

    def test_resolve_filled_billet(self):
        """Filled billet resolves to 'Callsign (Title)'."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to the {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Report to the LaForge (Chief Engineer)."

    def test_resolve_vacant_billet(self):
        """Vacant billet resolves to 'Title (vacant)'."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", None)})
        text = "Report to the {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Report to the Chief Engineer (vacant)."

    def test_unknown_token_unchanged(self):
        """Non-billet tokens in {} are left unchanged."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Use {unknown_setting} for config."
        result = _resolve_billet_templates(text, reg)
        assert result == "Use {unknown_setting} for config."

    def test_code_like_tokens_unchanged(self):
        """Tokens with code characters are skipped."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Format: {key=value} and {func()}"
        result = _resolve_billet_templates(text, reg)
        assert result == "Format: {key=value} and {func()}"

    def test_multiple_billets_in_one_line(self):
        """Multiple billet references on one line all resolve."""
        reg = _make_registry({
            "Chief Engineer": ("Chief Engineer", "LaForge"),
            "Chief Science Officer": ("Chief Science Officer", "Meridian"),
        })
        text = "Coordinate between {Chief Engineer} and {Chief Science Officer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Coordinate between LaForge (Chief Engineer) and Meridian (Chief Science Officer)."

    def test_case_insensitive_resolution(self):
        """Billet resolution is case-insensitive."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Ask {chief engineer} for help."
        result = _resolve_billet_templates(text, reg)
        assert result == "Ask LaForge (Chief Engineer) for help."

    def test_code_block_backtick_not_processed(self):
        """Content inside ``` code blocks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to {Chief Engineer}.\n```\n{Chief Engineer}\n```\nEnd."
        result = _resolve_billet_templates(text, reg)
        lines = result.split('\n')
        assert lines[0] == "Report to LaForge (Chief Engineer)."
        assert lines[2] == "{Chief Engineer}"  # Inside code block — unchanged
        assert lines[4] == "End."

    def test_code_block_tilde_not_processed(self):
        """Content inside ~~~ code blocks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to {Chief Engineer}.\n~~~\n{Chief Engineer}\n~~~\nEnd."
        result = _resolve_billet_templates(text, reg)
        lines = result.split('\n')
        assert lines[0] == "Report to LaForge (Chief Engineer)."
        assert lines[2] == "{Chief Engineer}"  # Inside tilde block — unchanged

    def test_inline_backtick_not_processed(self):
        """Content inside inline backticks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Use `{Chief Engineer}` for the reference."
        result = _resolve_billet_templates(text, reg)
        assert result == "Use `{Chief Engineer}` for the reference."

    def test_empty_text(self):
        """Empty text returns empty."""
        reg = _make_registry({})
        assert _resolve_billet_templates("", reg) == ""

    def test_no_templates(self):
        """Text without {} templates passes through unchanged."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "No templates here."
        assert _resolve_billet_templates(text, reg) == text

    def test_single_char_token_skipped(self):
        """Single-char tokens are skipped."""
        reg = _make_registry({})
        text = "Format {x} value."
        assert _resolve_billet_templates(text, reg) == "Format {x} value."

    def test_empty_braces_unchanged(self):
        """Empty braces {} pass through unchanged (regex requires 1+ char)."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Empty {} braces and {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert "{}" in result
        assert "LaForge (Chief Engineer)" in result

    def test_nested_braces_outer_preserved(self):
        """Nested braces {{something}} — inner match occurs, outer brace preserved."""
        reg = _make_registry({})
        text = "Template {{variable}} here."
        result = _resolve_billet_templates(text, reg)
        assert result == "Template {{variable}} here."


# --- set_billet_registry ---

class TestSetBilletRegistry:

    def test_set_billet_registry_stores_reference(self):
        """set_billet_registry stores the registry in module state."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            mock_reg = MagicMock()
            set_billet_registry(mock_reg)
            assert standing_orders._billet_registry is mock_reg
        finally:
            standing_orders._billet_registry = old_reg

    def test_set_billet_registry_none_clears(self):
        """set_billet_registry(None) clears the module state."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            set_billet_registry(MagicMock())
            set_billet_registry(None)
            assert standing_orders._billet_registry is None
        finally:
            standing_orders._billet_registry = old_reg


# --- Integration with compose_instructions ---

class TestComposeIntegration:

    def test_compose_with_billet_registry(self):
        """compose_instructions resolves billets when registry is wired."""
        from probos.cognitive import standing_orders

        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})

        old_reg = standing_orders._billet_registry
        try:
            standing_orders._billet_registry = reg
            result = standing_orders.compose_instructions(
                agent_type="test_agent",
                hardcoded_instructions="Report to {Chief Engineer}.",
            )
            assert "LaForge (Chief Engineer)" in result
        finally:
            standing_orders._billet_registry = old_reg

    def test_compose_without_billet_registry(self):
        """compose_instructions leaves templates when no registry."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            standing_orders._billet_registry = None
            result = standing_orders.compose_instructions(
                agent_type="test_agent",
                hardcoded_instructions="Report to {Chief Engineer}.",
            )
            assert "{Chief Engineer}" in result
        finally:
            standing_orders._billet_registry = old_reg
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595c_billet_templating.py -v

# Existing standing orders tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "standing_order" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595c CLOSED. Standing orders billet templating. compose_instructions() now resolves {Billet Title} patterns to current callsigns via BilletRegistry: {Chief Engineer} → LaForge (Chief Engineer). Vacant billets render as Title (vacant). Code blocks and inline backticks excluded from processing. 18 new tests. Depends on AD-595a.
```

### DECISIONS.md
Add entry:
```
**AD-595c: Post-processing template substitution for billet references.** Standing orders `.md` files can use `{Billet Title}` syntax to reference billets dynamically. Resolution happens as a post-processing pass in `compose_instructions()`, after all tiers are concatenated. Existing hardcoded references ("the Chief Engineer") still work — template syntax is opt-in. Filled billets render as `Callsign (Title)`, vacant billets render as `Title (vacant)` — giving agents an explicit signal to escalate up the chain rather than messaging a non-existent holder. Code blocks (``` and ~~~) and inline backtick spans are excluded from processing. Known limitation: multi-backtick inline code spans (``` ``code`` ```) are not handled; authors should avoid `{Title}` inside inline code. The substitution runs per compose_instructions() call (called each decide() cycle) without caching — currently sub-millisecond on ~30KB text; if profiling shows cost, add version-keyed cache. Module-level `_billet_registry` state follows existing standing_orders.py module pattern (file caches are also module-scoped). No changes to existing standing orders files — this just enables future use.
```

### docs/development/roadmap.md
Update AD-595c status from `planned` to `complete` in the sub-AD list.
