# Build Prompt — AD-863: Decomposer emits capability + department hints per sub-task

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; run the corruption pre-check before you start).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #833.
**Current highest committed AD: AD-862.** This is the first AD of the epic.

> **Specs are leads, not ground truth.** Every file:line and signature below was verified against live HEAD during the Architect verify-first pass. Two spec corrections are baked in (see "Spec corrections" at the end). If anything has drifted since, grep before you change it.

---

## Goal

Give each `WorkItemSpec` an optional `capability` phrase and optional `department` hint so the AD-864 resolver can pick a qualified agent. The decomposer stays a pure NL→DAG mapper; it only *annotates* the kind of work. Persist both hints onto the created `WorkItem.metadata` so AD-864 can read them off the persisted item.

## Files (verified anchors)

- `src/probos/consultation/dispatch.py` — extend frozen `WorkItemSpec` (class at line 47), `to_dict()` (line 77), and the metadata-persistence block inside `ParallelDispatcher.dispatch()` (lines 451–458).
- `src/probos/consultation/llm_decomposer.py` — extend `_SYSTEM_PROMPT` (~line 44), `_build_specs` (~line 209), `_with_deps` (static, ~line 285), `_passthrough` (static, ~line 328).

---

## Changes

### 1. `WorkItemSpec` — two new defaulted fields (dispatch.py:47)

`WorkItemSpec` is a `@dataclass(frozen=True)`. Current field order ends with `expected_output: str | None = None` as the LAST field. Add the two new defaulted fields **AFTER** `expected_output` (defaulted-fields-after-non-defaulted rule — all existing fields are already defaulted, so simply append at the end):

```python
    capability: str | None = None   # AD-863: one-phrase "kind of work" for agent resolution
    department: str | None = None   # AD-863: optional department hint (engineering/science/medical/security/bridge/operations)
```

### 2. `to_dict()` (dispatch.py:77)

The current `to_dict()` returns 10 keys. Add both new fields so it returns 12 keys and round-trips cleanly:

```python
            "capability": self.capability,
            "department": self.department,
```

### 3. `ParallelDispatcher.dispatch()` metadata persistence (dispatch.py:451–458)

The metadata block inside `dispatch()` currently does `metadata.update({... "expected_output": spec.expected_output})`. Add the two hints to that same `metadata.update({...})` call so they land on the persisted `WorkItem.metadata`:

```python
            "capability": spec.capability,
            "department": spec.department,
```

> **CORRECTION (baked in):** the epic spec calls this method `dispatch_workspace`. The real method is **`ParallelDispatcher.dispatch`** at dispatch.py:413; the metadata-persistence block is at lines 451–458. The mirrored `spec.to_dict()` write (line ~466 area) already carries the new keys once step 2 is done — verify it does, don't double-write.

### 4. `_SYSTEM_PROMPT` (llm_decomposer.py:~44)

Extend the per-element key list the prompt requests, adding `"capability"` (a short phrase describing the kind of work — e.g. "web research", "write code", "analyze data") and `"department"` (one of: engineering, science, medical, security, bridge, operations — or `null`). State explicitly: **both hints are advisory; `null` is acceptable; do not invent a department if unsure.**

### 5. `_build_specs` (llm_decomposer.py:~209)

Today `_build_specs` builds `WorkItemSpec(spec_id, title, description, depends_on, expected_output)` and does **not** pass `work_type`/`agent`/`resources`/`metadata`. Add `capability`/`department` parsing using the **same `str | None` normalization already used for `expected_output`** (strip; empty string → `None`; missing key → `None`), and pass both into the `WorkItemSpec(...)` constructor. Do **not** start setting `agent`, `work_type`, or `resources` here — out of scope.

### 6. `_with_deps` (llm_decomposer.py:~285, static)

`_with_deps` reconstructs the full frozen spec. Thread `capability=spec.capability, department=spec.department` through the reconstruction so DAG-repair preserves both hints.

### 7. `_passthrough` (llm_decomposer.py:~328, static)

The honest-degrade fallback carries no hints: `capability=None, department=None`.

---

## Tests — `tests/test_ad863_decomposer_hints.py` (≥6, fake LLM client only)

Use a fake/stub LLM client (fakes are fine for the LLM boundary — BF-287 only forbids MagicMock at substrate/storage boundaries, not the LLM):

1. `capability` + `department` parsed from the raw element and carried onto the resulting `WorkItemSpec`.
2. Missing/`null`/empty `capability` and `department` → `None` (not `""`).
3. `WorkItemSpec.to_dict()` round-trips both new keys.
4. `_with_deps` preserves `capability`/`department` through a DAG-repair reconstruction.
5. `_passthrough` carries `capability=None, department=None`.
6. Backward-compat: a raw element dict with **no** `capability`/`department` keys still builds a valid spec (defaults to `None`).

**Regression (must stay green, run after impl):**
- `tests/test_ad858_llm_decomposer.py`
- any existing `dispatch` spec tests (e.g. `tests/test_ad85*_*dispatch*.py` / `tests/test_consultation_dispatch*.py` — grep `WorkItemSpec` in `tests/` to find them).

Run focused + regression serially:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad863_decomposer_hints.py tests/test_ad858_llm_decomposer.py -q -n 0
```

---

## Do NOT build / change

- The resolver (AD-864). **Do not set `spec.agent`** anywhere in this AD.
- `MarkdownPlanDecomposer` parsing — leave its specs hint-free (defaults carry `None`).
- `work_type`, `resources`, `agent`, or any other currently-unset `_build_specs` field.

## Highest-risk constraints (restated)

- The two new dataclass fields go at the **END** of `WorkItemSpec` (after `expected_output`). Do not insert them mid-list.
- Normalize empty string → `None`, identical to the existing `expected_output` handling. Do not store `""`.
- The metadata persistence lives in `dispatch()` (line 451–458), **not** a method named `dispatch_workspace`.

## Tracking

- Add an AD-863 entry to `PROGRESS.md` (CLOSED on merge) and the epic roadmap.
- Commit impl, then commit any spec-correction note as `docs(AD-863): ...`, then close issue #833.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Spec corrections (file:line evidence)

| Spec claim | Reality | Evidence |
|---|---|---|
| `ParallelDispatcher.dispatch_workspace` persists metadata | Method is `ParallelDispatcher.dispatch`; metadata block at lines 451–458 | dispatch.py:413 (`async def dispatch(`), :451–458 (`metadata.update({...})`) |
| `WorkItemSpec` fields ordering | `expected_output` is the last current field; all fields already defaulted | dispatch.py:47 (class), last field `expected_output: str | None = None` |
