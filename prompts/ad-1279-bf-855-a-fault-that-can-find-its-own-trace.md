# AD-1279 — BF-855: a fault that can find its own trace

**A fault row's signature is computed over the untruncated error; the trace it points at is bounded before it is written. When the two disagree, the fault can never be repaired.**

| | |
|---|---|
| **Status** | Ready to build |
| **Closes** | #1325 (BF-855) |
| **Depends on** | AD-1269 (#1257, landed), AD-1257, AD-1173, AD-1151 |
| **Estimated tests** | ≥ 14 new |
| **Baseline** | 25,018 passed, 27 skipped |

---

## 1. Problem

AD-1269 made a fault row's signature the identity computed **once at detection**, over the canonical tool id and the **untruncated** error text. `ToolDefect.__post_init__` ([src/probos/fault_report.py](src/probos/fault_report.py#L228)) says so in capitals — *"ORDER IS LOAD-BEARING"* — because deriving the key after truncation split one detected defect into two durable rows with `occurrences [1, 1]`.

But [repair_verification.find_failing_arguments](src/probos/cognitive/repair_verification.py#L68) **recomputes** that signature from the *persisted trace*, and [build_tool_trace_payload](src/probos/cognitive/swe_harness/agentic_loop.py#L260) head+tail truncates each output at `tool_trace_output_max_chars` before writing it.

When the two disagree, argument recovery returns `None`, and the fault — filed correctly, coalesced correctly, with the right `tool_id`, `observed_as` and signature — can **never enter the AD-1171/AD-1172 repair path**. Verification reports `inconclusive` while holding a trace that would otherwise be usable.

The code already knows. [repair_verification.py](src/probos/cognitive/repair_verification.py#L114) has a `logger.debug` whose comment names this exact asymmetry: *"the one place the AD-1269 truncation asymmetry becomes observable."* It is a diagnostic; nothing depends on it.

### 1.1 The precondition the issue does not state — read this before writing the test

The issue asks for *"a regression test using a digit or hex run with an error longer than `tool_trace_output_max_chars`."* **That is necessary and NOT sufficient.**

[normalise_error](src/probos/fault_report.py#L114) collapses hex runs, then digit runs, and **only then** truncates to `_ERROR_MAX = 2000` ([fault_report.py:55](src/probos/fault_report.py#L55)). Head+tail truncation preserves the head. So if the **collapsed head is already ≥ 2000 chars**, the first 2000 collapsed characters are identical either way and **the two signatures agree**. The defect fires only when the collapsed head is *shorter* than `_ERROR_MAX`.

Measured by execution against the real `build_tool_trace_payload` and the real `find_failing_arguments`, same tool and arguments, on the checked-in config (`config/system.yaml:2422` `tool_result_max_chars: 6000`, `:2430` `tool_trace_output_max_chars: 8192`):

| case | error len | persisted | collapsed head | detector sig | trace sig | recovered |
|---|---|---|---|---|---|---|
| CONTROL short | 38 | 38 | 38 | `a8ce9124caff` | `a8ce9124caff` | **yes** |
| DENSE long (wordy head) | 24,013 | 8,192 | 2,000 | `6b6f2442dae0` | `6b6f2442dae0` | **yes** |
| COLLAPSING long (5,300-digit head) | 17,304 | 8,191 | 62 | `959ed48fa5cb` | `413e32ed0be9` | **NO** |

`_durable_head_tail(8192, 20000)` → head 5,358, tail 2,680. A digit or hex run must sit **in the head** and be long enough to collapse it below 2,000 characters.

> **A first probe attempt built its long error from a repeating pattern, got a collapse-resistant head, and WRONGLY REFUTED THIS ISSUE.** Do not repeat that. A test that puts the digit run in the *body* passes against the **unfixed** code and pins nothing.

The CONTROL row is what makes the third row mean anything: without it, a failing recovery is indistinguishable from a broken harness. Carry all three cases into the test file.

### 1.2 Adjacent: `FaultReportStore.start()` has no exception guard

[`start()`](src/probos/fault_report.py#L559) connects, runs the schema, migrates, and loads the cache with **no `try`**. When `_load_cache` raises — precisely what a missing migration causes — the aiosqlite connection is left open and its worker thread never dies. Measured: **pytest hung indefinitely rather than failing.**

AD-1269's `_migrate_observed_as_column` prevents today's trigger; the fragility is pre-existing and bites any future schema drift. **This is IN SCOPE**, as its own section — see §5 for why.

---

## 2. Decisions

These are the three questions AD-1269 declined to answer (its do-not-build #12: *"`build_tool_trace_payload` keeps writing `asdict(ToolCallRequest)`; adding a second name to the writer would fork provenance across trace generations"*). Recorded here so they are not re-litigated.

### D1 — May a trace entry carry a second identity field? **Yes. `error_signature`, on error entries only.**

The mechanism already exists and does not need inventing. `build_tool_trace_payload`'s own docstring establishes it:

> *"There is no envelope and no version field: readers version by **key presence** (feature detection), which is what a bare array admits."*

and `source_chars` was added exactly that way for BF-760 (#1218). This is that precedent applied a second time, not a new mechanism.

AD-1269's objection was to **forking provenance by adding a second NAME**. A digest is not a name. The entry gains one key, `error_signature`, and gains **no** `tool_id` / `canonical_tool_id` / `observed_as` field — so provenance stays exactly where AD-1269 put it: `name` is what the model used, and the fault row owns the canonical id.

Constraints:
- Emitted **only** when `is_error is True`. Success entries are untouched, so every non-error blob stays byte-identical.
- `output_max_chars == 0` still yields a blob byte-identical to the pre-AD-1151 trace. This falls out — `results_by_id` stays empty, so no result is joined and no signature is written. **Assert it anyway.**
- Determinism (DD-3) is preserved: the value is a pure function of `(canonical tool id, raw output)`. No clock, no I/O.

### D2 — How do readers distinguish trace generations? **Key presence, and the legacy path is retained, not replaced.**

`find_failing_arguments` prefers `entry.get("error_signature")` when it equals the target. **On absence *or* mismatch it falls back to today's recomputation from `entry["output"]`.**

Falling back on *mismatch* — not only on absence — is deliberate. The writer and the detector each canonicalise through an injected resolver that is `None` when there is no registry ([`_tool_id_resolver`](src/probos/cognitive/agentic_dispatch.py#L1432) returns `None` in that case). A skew between the two would otherwise make the field authoritative *and wrong*. Recomputation cannot produce a false positive against a specific 64-bit-plus target except by hash collision, so retaining it is strictly more permissive and costs nothing.

§4 additionally requires that both sites be handed the *same* resolver in production, which makes the skew unreachable rather than merely survivable.

### D3 — Where is the signature computed? **In the writer, calling the existing `error_signature`. One implementation, two call sites.**

`ToolDefect.signature` ([fault_report.py:263](src/probos/fault_report.py#L263)) documents itself as **byte-identical** to `error_signature` ([fault_report.py:145](src/probos/fault_report.py#L145)), and BF-856 already collapsed their hashing onto the shared `_digest` ([fault_report.py:122](src/probos/fault_report.py#L122)) precisely because *"two parallel edits can drift; a shared definition cannot."* A third implementation would reintroduce the risk that helper was added to remove.

So the writer **calls** `error_signature`; it does not reimplement it. Canonicalisation likewise reuses `_canonical_tool_id` ([fault_report.py:285](src/probos/fault_report.py#L285)) rather than a second copy — see §3.1 for the visibility change that makes that legal.

### D4 — Rejected: make the *detector* sign what will be persisted

Argued explicitly so it is not re-proposed. Two reasons, the second decisive.

1. **AD-1269 already measured this and chose against it.** Truncate-then-normalise is a different identity from normalise-then-truncate; it split one defect into two rows in a single turn.

2. **The detector cannot know what will be persisted, even in principle.** Beyond per-output truncation, `build_tool_trace_payload` performs whole-blob tail elision when the blob exceeds `blob_max_bytes` — an entry's output can be replaced by `""` because of *how many other tools were called in the same turn*. Signing the persisted form would make a fault's identity depend on unrelated traffic, so the same fault in a busy turn and a quiet turn would key differently and **AD-1169 coalescing would break**. That is not a trade-off; it is a correctness loss.

The asymmetry is therefore closed by making the **trace carry the detector's identity**, never by moving the detector to the trace's.

---

## 3. Implementation

### 3.1 `src/probos/fault_report.py` — promote the canonicaliser

`_canonical_tool_id` is needed by a second module. Reaching for a private name across a module boundary is a review blocker in this repo, and duplicating it would create the drift D3 exists to prevent.

- Rename `_canonical_tool_id` → **`canonical_tool_id`** (public), keeping the signature and the docstring.
- Update its one internal caller, `detect_tool_defect`'s `_canonical` helper at [fault_report.py:365](src/probos/fault_report.py#L365).
- Do **not** leave a `_canonical_tool_id` alias. Grep first and confirm the caller set is exactly that one site plus tests; update tests that import the private name, and say so in the build report.

Add a full type annotation and keep the existing degrade-to-*observed* behaviour byte-identical.

### 3.2 `src/probos/cognitive/swe_harness/agentic_loop.py` — write the identity

`build_tool_trace_payload` ([L260](src/probos/cognitive/swe_harness/agentic_loop.py#L260)) gains one keyword-only parameter:

```
resolve_tool_id: Callable[[str], str] | None = None,
```

Same shape, same name and the same degradation contract as `detect_tool_defect`'s ([fault_report.py:321](src/probos/fault_report.py#L321)). Default `None` keeps every existing caller — including [test_ad1153_browser_agentic_loop.py:496](tests/test_ad1153_browser_agentic_loop.py) and the `tests/test_ad1151_*` suite — compiling and behaving unchanged except for the new key.

Inside the `if tcr is not None:` branch, after `entry["output_truncated"]` and beside the `source_chars` block ([L372-L378](src/probos/cognitive/swe_harness/agentic_loop.py#L372)):

- Only when `tcr.is_error is True`.
- Canonicalise `call.name` through `canonical_tool_id(name, resolve_tool_id)`, caching per distinct name within the call so a 200-step trace resolves each alias once — mirror `detect_tool_defect`'s `canonical_by_observed` dict.
- Compute `error_signature(tool_id=<canonical>, error_text=<raw, pre-truncation>)` and assign to `entry["error_signature"]`.

> **⚠ COERCION DRIFT — this is the seam, do not get it wrong.**
> The writer builds `original` as `raw if isinstance(raw, str) else str(raw) if raw is not None else ""` — so a `None` output becomes `""`.
> The detector builds `raw_text` as `raw if type(raw) is str else str(raw)` — so a `None` output becomes `"None"`.
> **The signature material must use the DETECTOR's coercion**, or the two disagree on exactly the malformed-result case the writer's own comment says is reachable.
> Compute a separate value for the signature. **Do not change `original`** — it feeds `output_chars` and the persisted output, and changing it is a behaviour change outside this AD.

Cache imports at module scope: `from probos.fault_report import canonical_tool_id, error_signature`. `fault_report` is foundation and stdlib-only (its only non-stdlib import is `probos.storage.sqlite_factory` under `TYPE_CHECKING`), and `agentic_loop` currently imports only `swe_harness.tool_call` and `probos.types` — so this is a downward edge with no cycle. **Verify that by import, not by reading.**

Update the docstring with an `**AD-1279 — error_signature**` paragraph in the same voice as the `**BF-760 — source_chars**` one: what the key is, that it is pre-truncation, that it is error-only, and that readers version by key presence.

### 3.3 `src/probos/cognitive/agentic_dispatch.py` — hand the writer the same resolver

`_persist_tool_trace` ([L2374](src/probos/cognitive/agentic_dispatch.py#L2374)) is called at [L2296](src/probos/cognitive/agentic_dispatch.py#L2296), and `detect_tool_defect` at [L2366](src/probos/cognitive/agentic_dispatch.py#L2366) — the same method, the same scope, with `registry` in scope throughout (used at L1986, L2104, L2367).

- Give `_persist_tool_trace` a keyword-only `resolve_tool_id: Callable[[str], str] | None = None` and forward it into `build_tool_trace_payload`.
- At L2296, pass `_tool_id_resolver(registry)`.
- **Build the resolver ONCE** and use the same object at L2296 and L2367. Two calls to `_tool_id_resolver(registry)` would produce two closures over the same registry — equivalent today, but the point of D2's skew argument is that the writer and the detector cannot disagree, and one object makes that structural rather than incidental.
- Keep the existing honest-degrade `except Exception` around the whole body: a resolver that raises must still produce a trace, because `canonical_tool_id` already degrades to the observed name.

### 3.4 `src/probos/cognitive/repair_verification.py` — read it

In `find_failing_arguments` ([L68](src/probos/cognitive/repair_verification.py#L68)), replace the single signature comparison at [L98](src/probos/cognitive/repair_verification.py#L98):

- Read `entry.get("error_signature")`. If it is a `str` and equals `signature`, the entry matches — **skip recomputation entirely**, which is the whole point when the output is truncated.
- Otherwise fall back to `error_signature(tool_id=tool_id, error_text=raw_text)` exactly as today (D2).
- Keep the `named` / `signed` tallies and both `logger.debug` branches working. Revise the `elif found is None and named` message at [L118](src/probos/cognitive/repair_verification.py#L118) — its comment currently describes this asymmetry as unavoidable, and after this AD it means "a legacy trace, or a genuinely different fault." **Describe the condition; do not quote a forbidden token.**
- Update the docstring's AD-1269 paragraph to record that the trace now carries the identity and recomputation is the legacy path.

---

## 4. Acceptance criteria

1. A fault whose error exceeds `tool_trace_output_max_chars` **and** whose collapsed head is shorter than `_ERROR_MAX` recovers its failing arguments.
2. A legacy trace — entries with **no** `error_signature` key — still resolves by recomputation, unchanged.
3. Success entries carry no `error_signature`; every non-error blob is byte-identical to the pre-AD-1279 blob.
4. `output_max_chars == 0` still yields a blob byte-identical to the pre-AD-1151 trace.
5. The writer and the detector are handed the **same** resolver object in `WorkItemAgenticExecutor.run`.
6. The writer's signature material uses the detector's `None` coercion (§3.2).
7. `FaultReportStore.start()` closes the connection and re-raises when any post-connect step fails (§5).
8. Full repository gate green at **≥ 25,018 passed, 27 skipped** plus the new tests. Report the exact delta.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 5. `FaultReportStore.start()` — in scope, its own section

**Decision: IN this AD, not split out.** Three reasons, the third decisive:

1. It is small — a guard around the post-connect steps.
2. Splitting it costs a new issue against Backlog Burn-Down's discovery budget for something a two-line guard closes.
3. **The measured symptom is that pytest hangs indefinitely rather than failing.** That is a hazard to *this AD's own gate*. Fixing it here protects the run that must prove the rest.

Implementation at [fault_report.py:559](src/probos/fault_report.py#L559): wrap everything after `connect` in `try`; on exception `await self._db.close()` (itself guarded so a failing close cannot mask the original), set `self._db = None`, and **re-raise**.

**Propagate tier, not log-and-degrade.** A store that comes up with an empty cache silently re-files every recurring fault as new — that is a data-integrity failure wearing a degradation costume, and AD-1169's coalescing is the thing it breaks. Per the three-tier table in `.github/copilot-instructions.md`, that is `logger.error(...); raise`.

---

## 6. Tests

New file: `tests/test_ad1279_fault_finds_its_trace.py`. Extend `tests/test_ad1173_repair_verification.py` only where an existing case needs the new key.

### 6.1 The three-case matrix — build it exactly

Drive the **real** `build_tool_trace_payload` and the **real** `find_failing_arguments`. Do not hand-write trace dicts for these three; a hand-built trace cannot reproduce a truncation defect.

| case | construction | must recover, unfixed | must recover, fixed |
|---|---|---|---|
| CONTROL short | short error, no long run | **yes** | yes |
| DENSE long | > 8,192 chars, wordy head, collapsed head ≥ 2,000 | **yes** | yes |
| COLLAPSING long | > 8,192 chars, **≥ 5,400-char digit or hex run at the START** | **no** | **yes** |

The matrix is deliberately single-dimension: DENSE differs from COLLAPSING only in *where the run sits*, and CONTROL differs only in *length*. A fixture that differed on both dimensions at once would pin the conjunction and leave both single-branch mutants alive.

Assert the mechanism, not just the outcome — the COLLAPSING case must additionally assert that its persisted `output` is shorter than the raw error and that recomputing from that output does **not** equal the detector signature. Otherwise a future change that stops truncating would make the test pass for the wrong reason.

### 6.2 Required cases

1. CONTROL / DENSE / COLLAPSING per §6.1.
2. Legacy trace: entries with no `error_signature` recover by recomputation.
3. Mismatched `error_signature` + matching recomputation still recovers (D2 fallback).
4. Success (`is_error=False`) entries carry no `error_signature`.
5. Byte-identity: an all-success payload is byte-identical with and without a resolver.
6. `output_max_chars=0` yields the pre-AD-1151 blob.
7. `resolve_tool_id=None` — writer degrades to the observed name; a non-MCP tool round-trips.
8. A raising resolver still produces a full trace with every call record.
9. MCP alias: writer canonicalises the alias, and a fault filed under the canonical id recovers from a trace whose `name` is the alias.
10. `None` output — writer's signature material matches the detector's (§3.2 coercion).
11. An entry that matches name and signature but has a non-`dict` `arguments` returns `None` and logs the *"no recoverable argument dictionary"* branch, not the other one.
12. `start()` re-raises when `_load_cache` fails, **and** the connection is closed. Assert closure via a fake factory recording `close()`, and give the test a hard timeout so a regression fails rather than hangs.
13. `start()` re-raises when the schema step fails, same closure assertion.
14. `start()` still succeeds and populates the cache on the happy path.

### 6.3 Prove the test fails first

**Before writing the fix**, run the COLLAPSING case against unfixed `HEAD` and paste the failure into the build report. A regression test for a defect this subtle that was never observed failing is not evidence.

### 6.4 Mutation-verify

Acceptance criterion 1 turns on the test discriminating the right dimension, and §1.1 records a probe that got this wrong — so mutation is required here rather than optional.

Rules for this CRLF tree:
- Mutate **in place** with a `.mutbak` sibling; restore in `finally`. A copied tree is inert under an editable install.
- **Binary I/O only.** Text-mode round-tripping rewrites line endings and corrupts the diff.
- **Single-line anchors only.** Multi-line anchors silently match nothing here.
- Run the unmutated **baseline first**; abort if it is already red or every mutant looks killed.
- An anchor that is not found is **INERT, not killed** — say so. A timeout banner is **INVALID, never SURVIVED**.
- Re-derive anchors from the **current** source after any repair round; a repair invalidates prior anchors.
- If a mutant survives, first check whether an earlier guard makes it unreachable. A survivor that cannot be reached is dead code — remove it and say why, rather than leaving a control no test can distinguish.

Required mutants, each with its expected killer:

| # | mutation | killed by |
|---|---|---|
| M1 | drop the `entry["error_signature"]` write | COLLAPSING |
| M2 | reader always recomputes, ignoring the field | COLLAPSING |
| M3 | sign `bounded` instead of the raw output | COLLAPSING |
| M4 | drop the recomputation fallback | legacy-trace case (6.2 #2) |
| M5 | emit `error_signature` on non-error entries too | 6.2 #4 / #5 |
| M6 | writer signs `""` for a `None` output | 6.2 #10 |
| M7 | `start()` guard omits `close()` | 6.2 #12 |
| M8 | `start()` guard swallows instead of re-raising | 6.2 #12 / #13 |

---

## 7. Do NOT build

Named specifically, because each is a step away and tempting.

1. **AD-1240 (#1239)** — retaining the tool's full output value, or referencing an offloaded result from the trace. `build_tool_trace_payload`'s docstring already defers this. Out.
2. **A version field or envelope on the trace blob.** Key presence is the mechanism (D1). Adding a version field forks exactly the provenance AD-1269 protected.
3. **A second NAME on trace entries** — no `tool_id`, `canonical_tool_id` or `observed_as` key. Only the digest. This is the boundary of AD-1269's do-not-build #12 and it stays.
4. **`normalise_error`, `_ERROR_MAX`, `_HEX_RUN_RE`, `_DIGIT_RUN_RE`, `_digest`, `error_signature`, `ToolDefect.signature`.** Changing any collapse rule re-keys every stored fault row.
5. **`tool_trace_output_max_chars` / `tool_result_max_chars` defaults, or `resolve_tool_trace_bounds` clamping.** Widening a cap would mask the defect instead of fixing it.
6. **The elision arithmetic** in `build_tool_trace_payload` — the victim-selection loop and its byte accounting are untouched.
7. **`verify_repair`, the AD-1171/AD-1172 repair path, `SystemQAAgent`, `RedTeamAgent`, `QAAgentPool`.** This AD makes argument recovery *possible*; it does not wire what happens next.
8. **`find_failing_arguments`'s return type.** Still `dict | None`. No result object, no reason codes.
9. **Backfilling or migrating existing persisted traces.** Legacy traces resolve by recomputation, which is the whole point of D2.
10. **`detect_tool_defect`'s tally, threshold or `max()`.** Untouched beyond the §3.1 rename.
11. **`start()`/`stop()` guards on any other store.** `WorkspaceSuggestionStore` was just handled by BF-857; the rest are not this AD.
12. **The `FaultReportStore` schema, `_migrate_observed_as_column`, or the 16-column layout.**

---

## 8. Test-pinning check — do this before editing

Two `?raw`-style and byte-identity suites assert the trace's exact shape:

- `tests/test_ad1151_durable_tool_outputs.py` (~20 call sites; note the determinism pair at ~L720)
- `tests/test_bf760_trace_records_the_tools_length.py` (~L56, L156-L160)

**Grep both for exact-key-set assertions on error entries before changing the writer.** If one asserts a closed key set, updating it is correct — but record *why* inline in the test. Never delete such an assertion, and never weaken a guard to accommodate new code.

Related trap from the same class: a source-scan guard matches **comment text** too. If a comment in the new code names a token some guard forbids, describe the behaviour instead of spelling the token.

---

## 9. Tracking

| File | Update |
|---|---|
| `PROGRESS.md` | AD-1279 entry; BF-855 closed |
| `docs/development/roadmap.md` | Bug Tracker row for BF-855 |
| `DECISIONS.md` (era 5) | AD-1279 with D1-D4, including the D4 rejection |

**Do not stage** `README.md`, `docs/architecture/federation.md`, `docs/development/ad-ledger-snapshot.json`, `docs/development/open-ads-report.md`. They are modified in this tree for unrelated reasons. `roadmap.md` is also currently dirty — stage **only** your own Bug Tracker row, never the file wholesale, and never `git add -A`.

Close #1325 on merge. **Do not write `close`/`closes`/`fixes`/`resolves` + `#N` in any commit body for an issue you are not closing** — GitHub's linker does not understand negation and will close it.

---

## 10. Gate

Focused, during the build:

```powershell
cd d:\ProbOS
$env:PROBOS_DATA_DIR="$env:TEMP\probos_ad1279_focus"
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1279_fault_finds_its_trace.py tests/test_ad1173_repair_verification.py tests/test_ad1151_durable_tool_outputs.py tests/test_bf760_trace_records_the_tools_length.py tests/test_ad1257_defect_follows_failure.py tests/test_bf761_budget_is_spent_on_real_content.py tests/test_ad1153_browser_agentic_loop.py tests/test_ad1203_trace_routes.py -q -p no:randomly
```

Adversarial review once the implementation is stable, repairs applied, **then** the broad gate — run synchronously, no timeout, ~15-19 minutes, and it sits at `[ 99%]` for several of them before the summary:

```powershell
cd d:\ProbOS
$env:PROBOS_DATA_DIR="$env:TEMP\probos_gate_ad1279"
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile
```

Any source or test edit after the gate **invalidates it** — rerun before pushing.

---

## 11. Verified against codebase (2026-08-26, HEAD `c8588b5a`)

```
src/probos/fault_report.py
   55: _ERROR_MAX = 2000
  111: _SIGNATURE_RE = re.compile(r"[0-9a-f]{64}")
  114: def normalise_error(text: Any) -> str:
  122: def _digest(material: str) -> str:
  145: def error_signature(*, tool_id: Any, error_text: Any) -> str:
  228: __post_init__  "ORDER IS LOAD-BEARING"
  263:     def signature(self) -> str:
  285: def _canonical_tool_id(observed, resolve_tool_id) -> str:
  321: def detect_tool_defect(outcome, *, resolve_tool_id=None)
  365:             cached = _canonical_tool_id(observed_name, resolve_tool_id)
  559:     async def start(self) -> None:        <- no try guard
  605:     async def _load_cache(self) -> None:

src/probos/cognitive/swe_harness/agentic_loop.py
   16: from probos.cognitive.swe_harness.tool_call import (
   23: from probos.types import LLMRequest     <- only two import edges
   55: TOOL_TRACE_OUTPUT_MAX_CHARS = 8192
   97: _ELISION_MARKER = (
  104: def truncate_tool_output(
  237: def _durable_head_tail(output_max_chars, original_chars)
  260: def build_tool_trace_payload(
  355:             bounded = truncate_tool_output(
  372:             source_chars = getattr(tcr, "source_chars", None)

src/probos/cognitive/repair_verification.py
   30: from probos.fault_report import error_signature
   68: def find_failing_arguments(entries, *, tool_id, signature, observed_as="")
   98:         if error_signature(tool_id=tool_id, error_text=raw_text) != signature:
  114:         # "the one place the AD-1269 truncation asymmetry becomes observable"

src/probos/cognitive/agentic_dispatch.py
   32: from probos.fault_report import ToolDefect, detect_tool_defect
 1432: def _tool_id_resolver(registry: Any) -> Callable[[str], str] | None:
 2296:         tool_trace_ref = await self._persist_tool_trace(
 2366-2367: tool_defect=detect_tool_defect(
               agentic_result, resolve_tool_id=_tool_id_resolver(registry))
 2374:     async def _persist_tool_trace(
   registry in scope across run(): L1986, L2104, L2367

src/probos/cognitive/swe_harness/tool_call.py
  653: class ToolCallRequest:   name / arguments / id  (asdict source)
  663: class ToolCallResult:    id / output / is_error / source_chars

config/system.yaml
 2422:   tool_result_max_chars: 6000
 2430:   tool_trace_output_max_chars: 8192

Confirmed still open (BF-857 at f55f25df touched WorkspaceSuggestionStore,
not FaultReportStore): fault_report.py start() has no exception guard.
```
