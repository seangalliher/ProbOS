# BF-202: Era V Transition — Tracking File Archival

**Type:** Documentation / Housekeeping  
**Priority:** High (files are unwieldy, blocking productive use)  
**Status:** Ready for builder

## Context

ProbOS tracking files have grown to the point of being unmanageable:
- `docs/development/roadmap.md` — **7,225 lines**
- `DECISIONS.md` — was 5,117 lines (already archived to `decisions-era-4-evolution.md`, now a 12-line stub)
- `PROGRESS.md` — 63 lines, just needs era table update

Era IV ("Evolution", Phase 30) is complete. Era V ("Civilization", Phases 31-36) is now active.

**Goal:** Archive completed content from roadmap.md, trim the bug tracker, and update era references. Target roadmap.md under ~3,500 lines.

## Pre-Conditions (already done)

- `decisions-era-4-evolution.md` already created in repo root (5,115 lines)
- `DECISIONS.md` already reset to Era V stub with updated Archives line
- These files should NOT be modified by this prompt

## Changes

### Change 1: Archive completed roadmap sections to `roadmap-completed.md`

**File:** `docs/development/roadmap-completed.md` (existing, 428 lines — APPEND to it)

Append a new section header at the end:

```markdown

---

## Era IV Completed Work (Archived 2026-04-17)
```

Then move the following COMPLETE sections from `docs/development/roadmap.md` into this archive file. For each section, cut it from roadmap.md and paste it into roadmap-completed.md. Leave a one-line reference in roadmap.md pointing to the archive.

**Sections to archive (all content between the ### header and the next ### or ## header):**

From the **Team Details** area — these completed team sections have self-contained subsections that are complete:

1. **### Notebook Quality Pipeline (AD-550–555)** — starts around line 2798. All 6/6 ADs COMPLETE.
2. **### Emergence Metrics — Collaborative Intelligence Measurement (AD-557)** — starts around line 2852. Complete.
3. **### Trust Cascade Dampening (AD-558)** — starts around line 2875. Complete.
4. **### Provenance Tracking — Intelligence-Grade Source Attribution (AD-559)** — starts around line 2895. Absorbed by AD-567d, complete.
5. **### Science Department Expansion — Analytical Pyramid (AD-560)** — starts around line 2901. Complete.

From the **Backlog** area — completed individual AD sections:

6. **### Ward Room Social Fabric (AD-453)** — line ~4120. Done.
7. **### Communications Command Center (AD-485)** — line ~4124. Done.
8. **### Memory Anchoring (AD-567)** — line ~4286. All sub-ADs complete.
9. **### Adaptive Source Governance (AD-568)** — line ~4350. All 5 sub-ADs complete.
10. **### Observation-Grounded Crew Intelligence Metrics (AD-569)** — line ~4382. Complete.
11. **### Anchor-Indexed Episodic Recall (AD-570)** — line ~4497. Complete.
12. **### Captain Engagement Priority (AD-572)** — line ~4556. Complete.
13. **### Unified Agent Working Memory (AD-573)** — line ~4568. Complete.
14. **### DM Reply Agent Notification (AD-574)** — line ~4578. Complete.
15. **### Unified Self-Awareness (AD-575)** — line ~4584. Complete.
16. **### LLM Unavailability Awareness (AD-576)** — line ~4590. Complete.
17. **### Temporal Sequence Precision (AD-577)** — line ~4596. Complete.
18. **### Alert Resolution Feedback Loop (AD-580)** — line ~4648. Complete.
19. **### Memory Competency Probes — LongMemEval-Inspired (AD-582)** — line ~4656. Complete.
20. **### Wrong Convergence Detection (AD-583)** — line ~4682. Complete.
21. **### Observable State Verification + Convergence Source Tracing (AD-583f/583g)** — line ~4697. Complete.
22. **### Metacognitive Architecture Awareness (AD-587 / AD-588 / AD-589)** — line ~4755. COMPLETE.
23. **### Confabulation Scaling Mitigation (AD-590 / AD-591 / AD-592 / AD-593)** — line ~4781. COMPLETE.
24. **### Importance Scoring at Encoding (AD-598)** — line ~5093. Complete.
25. **### Enhanced Embedding — Content + Anchor Metadata Concatenation (AD-605)** — line ~5219. Complete.
26. **### 3D Memory Graph Visualization (AD-611)** — line ~5307. Complete.
27. **### Ward Room HXI Performance (AD-613)** — line ~5321. Complete.
28. **### DM Conversation Termination (AD-614)** — line ~5329. Complete.
29. **### Ward Room Database Performance Hardening (AD-615)** — line ~5339. Complete.
30. **### Ward Room Router Hot Path Optimization (AD-616)** — line ~5349. Complete.
31. **### LLM Rate Governance (AD-617/617b)** — line ~5359. Complete.
32. **### Counselor Cross-Department Awareness (AD-619)** — line ~5387. Complete.
33. **### DM Rendering + Thread Depth + DM Tag Robustness (AD-612)** — line ~5946. Complete.

From the **Waves** area — completed wave/pipeline sections:

34. **### Cognitive Self-Regulation Wave (AD-502–506)** — line ~6024. COMPLETE 7/7.
35. **### Memory Provenance & Knowledge Integration (AD-540)** — line ~6052. This is a large section that includes the AD-541 lineage subsections. All pillars CLOSED. Archive the entire section through to the next ### header.
36. **### Wave 4: Code Review Closure (AD-527, BF-079/085–088)** — line ~6436. All items done.
37. **### Wave 6: Codebase Quality — Scorecard Audit (AD-542, BF-089–094)** — line ~6518. COMPLETE.
38. **### Workforce Scheduling Engine (AD-496–498)** — line ~6843. All 3 core ADs complete.

From the **Cold-Start Wave** — completed entries only:

39. In the **### Cold-Start Wave (AD-638–640)** section (line ~7015): archive the AD-638 and AD-640 entries (done/complete), keep AD-639 (scoped) and AD-641 (design) entries in place.

**What to leave behind in roadmap.md for each archived section:**
Replace each removed section with a single line:
```
*Archived to [roadmap-completed.md](roadmap-completed.md) — [section title]*
```

### Change 2: Trim Bug Tracker

**File:** `docs/development/roadmap.md`

The bug tracker section starts at line ~7030 with `## Bug Tracker`.

**Keep only:**
- The header, description, and table header row (`| BF | Summary | Severity | Status |` and `|----|---------|----------|--------|`)
- **Open bugs:** BF-041, BF-106, BF-201
- **Recently closed (last week):** BF-199, BF-200, BF-193, BF-190, BF-191, BF-189, BF-186, BF-185, BF-187

**Archive everything else** (BF-001 through BF-188, excluding the ones listed as recently closed above) to `roadmap-completed.md` under a new section:

```markdown

---

## Bug Tracker — Closed Issues (Era IV)

| BF | Summary | Severity | Status |
|----|---------|----------|--------|
[all closed bug rows here]
```

### Change 3: Update PROGRESS.md

**File:** `PROGRESS.md` (63 lines, repo root)

In the Development Eras table (line ~9), change:

```
| [**Era IV: Evolution**](DECISIONS.md) | 30 | The Ship Evolves | Active |
| Era V: Civilization | 31-36 | The Ship Becomes a Society | Planned |
```

to:

```
| [**Era IV: Evolution**](decisions-era-4-evolution.md) | 30 | The Ship Evolves | Complete |
| [**Era V: Civilization**](DECISIONS.md) | 31-36 | The Ship Becomes a Society | Active |
```

Note: Era IV link now points to the archive file, Era V link points to current DECISIONS.md.

## Verification

1. `roadmap.md` should be significantly shorter (target: under ~3,500 lines)
2. `roadmap-completed.md` should have all archived content
3. No content should be lost — everything archived, not deleted
4. All open bugs (BF-041, BF-106, BF-201) still appear in roadmap.md bug tracker
5. All recently closed bugs still appear in roadmap.md bug tracker
6. PROGRESS.md era table reflects Era IV Complete, Era V Active
7. `decisions-era-4-evolution.md` should NOT be modified (already done)
8. `DECISIONS.md` should NOT be modified (already done)

## Files Modified

| File | Action |
|------|--------|
| `docs/development/roadmap.md` | Remove completed sections (replace with archive references), trim bug tracker |
| `docs/development/roadmap-completed.md` | Append all archived sections and closed bugs |
| `PROGRESS.md` | Update era table |

## NOT Modified (already done)

| File | Status |
|------|--------|
| `DECISIONS.md` | Already reset to Era V stub — DO NOT TOUCH |
| `decisions-era-4-evolution.md` | Already created — DO NOT TOUCH |
