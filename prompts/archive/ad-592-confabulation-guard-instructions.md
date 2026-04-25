# AD-592: Confabulation Guard Instructions

**AD:** 592
**Title:** Confabulation Guard Instructions — Anti-Fabrication Framing in Memory Section
**Type:** Enhancement (cognitive safety)
**Depends on:** None (independent, ships first in AD-590–593 wave)
**Absorbs:** None
**Risk:** Very low — instruction-only change, no algorithmic modifications
**Research:** `docs/research/confabulation-scaling-research.md`

---

## Problem Statement

Agents fabricate specific numbers, durations, measurements, and statistics from memory fragments instead of citing authoritative data or acknowledging uncertainty. Examples:

- Atlas claimed "240+ false alerts/hour" — actual: 2-6/hour (pattern cooldowns cap rates)
- Meridian claimed "2d 22h offline" — actual: 6 minutes (from authoritative orientation)
- When corrected, Meridian said "3 minutes" — still wrong (actual: 6m 19s)

The memory section framing in `_format_memory_section()` tells agents "Do NOT confuse with training knowledge" (line 1978) but says nothing about:
1. Not fabricating specific numeric values from fragments
2. Orientation data having priority over recalled memories
3. Acknowledging uncertainty when exact values aren't in their memories

The AD-568c source authority system calibrates overall trust level (AUTHORITATIVE/SUPPLEMENTARY/PERIPHERAL) but none of the three levels warn against fabricating specifics from fragments.

---

## Design Principles Compliance

- **SOLID (S):** `_format_memory_section()` retains single responsibility — formatting. No new logic, only instruction content changes.
- **SOLID (O):** Source framing is extended via existing `source_framing.authority` field, not by modifying `compute_source_framing()`.
- **Law of Demeter:** No new object traversals. AD-592 reads only `source_framing.authority` (already accessed via `source_framing.header` and `source_framing.instruction`).
- **Fail Fast / Defense in Depth:** Guard instructions are defense-in-depth — they work alongside the scoring fixes in AD-590/591/593, not instead of them.
- **DRY:** Confabulation guard text is defined once per authority tier, not duplicated across call sites. The three call sites for `_format_memory_section()` (DM, WR, proactive) all flow through the same method.

---

## Implementation

### File 1: `src/probos/cognitive/cognitive_agent.py`

**Change 1: Update `_format_memory_section()` — source-framed branch (lines 1967–1974)**

Current code (lines 1967–1974):
```python
if source_framing:
    lines = [
        source_framing.header,
        source_framing.instruction,
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
```

Replace with:
```python
if source_framing:
    lines = [
        source_framing.header,
        source_framing.instruction,
    ]
    # AD-592: Authority-calibrated confabulation guard
    lines.append(self._confabulation_guard(source_framing.authority))
    lines.extend([
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ])
```

**Change 2: Update `_format_memory_section()` — static fallback branch (lines 1976–1982)**

Current code (lines 1976–1982):
```python
else:
    lines = [
        "=== SHIP MEMORY (your experiences aboard this vessel) ===",
        "These are YOUR experiences. Do NOT confuse with training knowledge.",
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
```

Replace with:
```python
else:
    lines = [
        "=== SHIP MEMORY (your experiences aboard this vessel) ===",
        "These are YOUR experiences. Do NOT confuse with training knowledge.",
        self._confabulation_guard(None),
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
```

**Change 3: Add `_confabulation_guard()` method — insert immediately before `_format_memory_section()` (before line 1964)**

```python
@staticmethod
def _confabulation_guard(authority: str | None) -> str:
    """Return AD-592 confabulation guard instruction calibrated by source authority.

    Three tiers of guard strength:
    - AUTHORITATIVE: light touch — memories are high quality, still warn about numbers
    - SUPPLEMENTARY/None: standard guard — warn about numbers + orientation priority
    - PERIPHERAL: strong guard — warn about numbers + orientation priority + uncertainty
    """
    # Import here to avoid circular dependency at module level
    from probos.cognitive.source_governance import SourceAuthority

    base = (
        "IMPORTANT: Do NOT fabricate specific numbers, durations, measurements, or statistics "
        "from these fragments. If an exact value is not in your memories, say you do not have that data."
    )
    orientation_priority = (
        " When orientation or system data conflicts with your memories, "
        "orientation data is authoritative — cite it, do not estimate."
    )

    if authority == SourceAuthority.AUTHORITATIVE:
        # High-quality memories — still guard against number fabrication
        return base
    elif authority == SourceAuthority.PERIPHERAL:
        # Low-quality memories — full guard + uncertainty mandate
        return base + orientation_priority + " State uncertainty explicitly."
    else:
        # SUPPLEMENTARY or no framing (fallback) — standard guard
        return base + orientation_priority
```

### File 2: `tests/test_orientation.py` — no changes needed (stasis tests unaffected)

### File 3: `tests/test_source_governance.py`

**Change: Add `TestConfabulationGuardAD592` test class at end of file.**

Tests to add (7 tests):

```python
class TestConfabulationGuardAD592:
    """AD-592: Confabulation guard instructions in memory section framing."""

    def _make_agent(self):
        """Create a minimal CognitiveAgent for testing _format_memory_section."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        return agent

    def _sample_memories(self):
        """Return minimal memory list for format testing."""
        return [{"input": "Pool health at 45%", "source": "direct"}]

    def test_static_fallback_contains_fabrication_guard(self):
        """Memory section without source framing includes confabulation guard."""
        agent = self._make_agent()
        lines = agent._format_memory_section(self._sample_memories())
        text = "\n".join(lines)
        assert "Do NOT fabricate specific numbers" in text

    def test_static_fallback_contains_orientation_priority(self):
        """Static fallback includes orientation authority instruction."""
        agent = self._make_agent()
        lines = agent._format_memory_section(self._sample_memories())
        text = "\n".join(lines)
        assert "orientation data is authoritative" in text

    def test_authoritative_framing_guard_no_orientation_priority(self):
        """AUTHORITATIVE framing includes fabrication guard but not orientation priority."""
        from probos.cognitive.source_governance import SourceAuthority, SourceFraming
        agent = self._make_agent()
        framing = SourceFraming(
            authority=SourceAuthority.AUTHORITATIVE,
            header="=== SHIP MEMORY (verified operational experience) ===",
            instruction="These memories are well-anchored.",
        )
        lines = agent._format_memory_section(self._sample_memories(), source_framing=framing)
        text = "\n".join(lines)
        assert "Do NOT fabricate specific numbers" in text
        assert "orientation data is authoritative" not in text

    def test_supplementary_framing_guard_includes_orientation_priority(self):
        """SUPPLEMENTARY framing includes both fabrication guard and orientation priority."""
        from probos.cognitive.source_governance import SourceAuthority, SourceFraming
        agent = self._make_agent()
        framing = SourceFraming(
            authority=SourceAuthority.SUPPLEMENTARY,
            header="=== SHIP MEMORY (your experiences aboard this vessel) ===",
            instruction="Consider alongside training knowledge.",
        )
        lines = agent._format_memory_section(self._sample_memories(), source_framing=framing)
        text = "\n".join(lines)
        assert "Do NOT fabricate specific numbers" in text
        assert "orientation data is authoritative" in text

    def test_peripheral_framing_guard_includes_uncertainty_mandate(self):
        """PERIPHERAL framing includes full guard with uncertainty mandate."""
        from probos.cognitive.source_governance import SourceAuthority, SourceFraming
        agent = self._make_agent()
        framing = SourceFraming(
            authority=SourceAuthority.PERIPHERAL,
            header="=== SHIP MEMORY (limited recollections) ===",
            instruction="Do not rely heavily on them.",
        )
        lines = agent._format_memory_section(self._sample_memories(), source_framing=framing)
        text = "\n".join(lines)
        assert "Do NOT fabricate specific numbers" in text
        assert "orientation data is authoritative" in text
        assert "State uncertainty explicitly" in text

    def test_guard_precedes_markers(self):
        """Confabulation guard appears before the source/verification markers."""
        agent = self._make_agent()
        lines = agent._format_memory_section(self._sample_memories())
        text = "\n".join(lines)
        guard_pos = text.index("Do NOT fabricate")
        markers_pos = text.index("Markers:")
        assert guard_pos < markers_pos

    def test_guard_after_header_and_instruction(self):
        """Confabulation guard appears after the header/instruction, before markers."""
        from probos.cognitive.source_governance import SourceAuthority, SourceFraming
        agent = self._make_agent()
        framing = SourceFraming(
            authority=SourceAuthority.SUPPLEMENTARY,
            header="=== SHIP MEMORY (your experiences aboard this vessel) ===",
            instruction="Consider alongside training knowledge.",
        )
        lines = agent._format_memory_section(self._sample_memories(), source_framing=framing)
        text = "\n".join(lines)
        header_pos = text.index("SHIP MEMORY")
        guard_pos = text.index("Do NOT fabricate")
        markers_pos = text.index("Markers:")
        assert header_pos < guard_pos < markers_pos
```

---

## Verification

1. Run targeted tests:
   ```
   python -m pytest tests/test_source_governance.py -x -v
   ```

2. Run related test suites for regression:
   ```
   python -m pytest tests/test_provenance_boundary.py tests/test_memory_integrity.py tests/test_ad567b_anchor_recall.py -x -v
   ```

3. Verify no test references the old exact static text "These are YOUR experiences. Do NOT confuse with training knowledge." without the new guard line following it. Search for tests that assert on the old exact text and update if needed.

---

## What This Does NOT Change

- **`compute_source_framing()` in `source_governance.py`** — unchanged. Authority computation is not modified.
- **`_recall_relevant_memories()` in `cognitive_agent.py`** — unchanged. Recall pipeline is not modified (that's AD-590/591/593).
- **`ConfabulationProbe` / `MemoryAbstentionProbe`** — unchanged. These probes should see improved scores from the guard instructions, validating effectiveness.
- **Orientation rendering** — unchanged. BF-144's `"AUTHORITATIVE — cite this, do not estimate"` remains as-is.
- **Standing orders** — unchanged. The guard lives in the memory section framing, not in standing orders, because it applies specifically to episodic memory recall context.
- **Dream pruning / scoring thresholds** — unchanged (AD-593 scope).

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Add `_confabulation_guard()` static method (authority-calibrated). Update both branches of `_format_memory_section()` to include guard text between instruction and markers. |
| `tests/test_source_governance.py` | Add `TestConfabulationGuardAD592` class with 7 tests covering all authority tiers, ordering, orientation priority presence/absence. |

**Estimated test count:** 7 new tests, 0 modified existing tests.
