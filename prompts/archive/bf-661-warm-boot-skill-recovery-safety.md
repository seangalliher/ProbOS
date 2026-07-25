# BF-661 — Warm-boot skill recovery safety

**One-line:** Replace BF-656's destructive “missing exact handler” prune with an identity-safe, race-safe quarantine sidecar; execute and attach only source that satisfies the real `SkillBasedAgent` async handler contract.

**Status:** Required revision after implementation review — ready to build only with all requirements below
**Type:** Bug fix — **BF-661** (no new AD)
**GitHub issue:** #1027
**HEAD verified:** `f097f9243fb019d11a828b5fa9f577ad5f9af1b4` (2026-07-10)
**Dependencies:** BF-656, BF-658, AD-161, AD-163
**Estimated tests:** 25–35 additions/updates across the four authorized test files

## Problem

BF-656 deletes persisted skill source whenever warm boot cannot find exact `handle_<filename>`. A reproduced `wanted.py` containing `async def handle_other(...)` was deleted with its descriptor. Git is not a sufficient fallback because AD-161 batches create+delete within the commit debounce.

Implementation review found four additional blockers that are now required scope:

1. skill intent names reach source/descriptor/marker paths without one strict shared validator;
2. marker writes are non-atomic, read shape is under-validated/unbounded, and redaction misses bearer/authorization/secret/credential forms;
3. hash markers lack per-intent serialization and compare-before-act protection against source/marker races;
4. `SkillValidator` claims signature validation but does not prove compatibility with the real `SkillBasedAgent` invocation.

## Contract decisions

### DD-1 — One strict validator owns every persisted-skill name boundary

Define one module-level validator in `src/probos/knowledge/store.py`. Call it before lock lookup or path construction from `store_skill()`, every filename stem in `load_skills()`, the new `load_skill_source()`, all marker APIs, and `remove_skill()`.

It returns the unchanged valid name or raises `ValueError`. **Reject; never trim, normalize, case-fold, slugify, or replace.** Accepted persisted designed-skill names match:

```text
^[a-z][a-z0-9_]*$
```

Also require `f"handle_{intent_name}".isidentifier()` and reject Python keywords for the intent. Preserve existing conventions including `calculate`, `translate_text`, `count_words`, and `get_weather`.

Reject non-string/empty/whitespace names, Windows/UNC/POSIX absolute paths, either separator, any dot/traversal, hyphens, spaces, colons, uppercase, leading digits, Unicode/non-ASCII, and every name incompatible with exact Python `handle_<name>` generation. Invalid direct API calls have zero filesystem, lock-registry, and commit side effects.

`load_skills()` validates each `json_fp.stem` before constructing its companion path. A hostile filename logs a contextual WARNING, remains untouched, and does not prevent valid siblings loading.

This rule is intentionally narrower than generic mesh intent naming (dotted device intents exist) and different from hyphenated AgentSkills.io `SKILL.md` catalog names.

### DD-2 — Three-way source classification remains focused

Before import/exec, call `SkillValidator.validate(source_code, intent_name)` using the live `SelfModConfig`:

1. exact valid skill: load, runtime-verify, clear only its matching stale marker, then attach;
2. provable inert stub: AST contains only module docstring and/or `pass` (comments/whitespace are inert); this is the only auto-prune path;
3. every non-stub validation/import/load/runtime-contract failure: preserve source+descriptor byte-for-byte, quarantine, never execute/attach an alternate handler.

Syntax errors and imports are non-stub. Never infer or rename `handle_other` as `handle_wanted`.

### DD-3 — Marker APIs use explicit expected-hash compare semantics

Markers remain `skill_quarantine/<intent_name>.json` with exactly:

- validated `intent_name`;
- 64-character lowercase-hex `source_sha256`;
- non-empty redacted `reason` (maximum 500 characters);
- redacted `errors` (maximum 20 strings, each maximum 500 characters);
- parseable timezone-aware UTC ISO-8601 `timestamp`.

Required typed APIs:

- `load_skill_source(intent_name: str) -> str | None`
- `load_skill_quarantine(intent_name: str) -> dict[str, Any] | None`
- `quarantine_skill(intent_name: str, *, source_code: str, expected_source_sha256: str, reason: str, errors: list[str]) -> bool`
- `clear_skill_quarantine(intent_name: str, *, expected_source_sha256: str) -> bool`
- `remove_skill(intent_name: str, *, expected_source_sha256: str | None = None) -> bool`

Strictly validate every supplied hash. `quarantine_skill()` returns `False` without mutation when `sha256(source_code)` or the current on-disk source differs from `expected_source_sha256`. `clear_skill_quarantine()` deletes only a valid marker with that hash. Conditional `remove_skill()` deletes source/descriptor and only a matching marker only if current source still has that hash. Explicit administrative removal may omit the hash. Only an actual mutation schedules a commit.

Do not add quarantine/reread APIs to `KnowledgeStoreProtocol`; warm boot receives the concrete store.

### DD-4 — All skill/marker operations share per-intent serialization

Maintain a private per-intent `asyncio.Lock` registry on each `KnowledgeStore`. `store_skill()`, paired loading/reread, marker load/write/clear, and remove use the same lock for a name. Validate before lock lookup. Do not hold one global lock across a scan and do not recursively acquire a non-reentrant lock; use private locked helpers. Lock lookup/creation is synchronous before any await.

This is only an in-process guarantee. Expected-hash rereads remain mandatory for external edits.

### DD-5 — Atomic marker publication and strict bounded reads

Publish marker JSON through a unique same-directory temp file (`tempfile.mkstemp(..., dir=marker.parent)` or equivalent), flush, `os.fsync()`, then `os.replace()`. Clean the temp on every failure. Prefer a quarantine-specific helper over changing unrelated generic JSON behavior.

Extend `PIIRedactor` centrally (and `tests/test_pii_redaction.py`) for:

- `Authorization: Bearer <value>` and bare `Bearer <value>`;
- key/value forms for `authorization`, `secret`, `client_secret`, `credential`, and `credentials`;
- existing API-key/token/access-token/refresh-token/password forms;
- `:` or `=` separators, case-insensitively.

On read, validate the complete bounded shape before returning a marker that can suppress execution. Oversized reason/error/list, wrong types, uppercase/non-hex hash, naive/non-UTC timestamp, malformed/torn JSON, or mismatched intent logs a contextual WARNING and returns `None`. Never truncate malformed persisted data into validity on read.

### DD-6 — Warm boot uses at most three stable source snapshots

`load_skills()` output is only the initial candidate. Per intent, use a maximum of three snapshots total (initial plus at most two `load_skill_source()` rereads):

1. compute `observed_hash` for the snapshot;
2. load marker;
3. immediately reread/re-hash before honoring a matching marker; skip only if still stable;
4. validate the stable source;
5. reread/re-hash before prune, quarantine, import/load, marker clear, and attachment as applicable;
6. if bytes change, abandon all decisions/handlers from the old snapshot and retry;
7. after three unstable snapshots, preserve everything, execute/attach/mutate nothing, log one contextual WARNING, and continue.

Warm boot must use the public typed reread API, never private store paths. Stable invalid source calls `quarantine_skill(..., expected_source_sha256=observed_hash)`; stable inert source calls conditional `remove_skill()`. A `False` compare result triggers retry.

For valid source: perform the final pre-load hash check; import; verify the loaded handler; if the initially loaded marker matches `observed_hash`, clear it **before attachment** with that expected hash. If no marker existed, no clear is required. If a matching marker existed but clear returns `False`, reload marker/source: a newer/different marker blocks old attachment; benign concurrent absence may proceed only after source is still stable and no marker now exists. Reread/re-hash after the clear decision and immediately before attachment. Attachment failure stays unhashed/retryable.

The warm-boot callback currently points to `ProbOSRuntime._add_skill_to_agents()`, whose normal design-time path persists the skill again. Authorize a narrow keyword such as `persist: bool = True` on that existing runtime callback and pass `persist=False` only from warm boot, or an equivalent explicit injected restore callback. This prevents source A being rewritten after the final hash check. Default behavior for all existing design-time callers remains byte-identical. Update `src/probos/runtime.py`; add the no-repersist warm-boot assertion in `tests/test_bf656_boot_log_hygiene.py` and the default-persistence assertion in the existing runtime skill coverage in `tests/test_skill_agent.py`.

Invariant: no marker for hash A may be written over source B; clear(A) cannot erase marker B; repaired source cannot be skipped by marker A; code compiled from A cannot attach after source becomes B.

### DD-7 — `SkillValidator` enforces the actual handler call shape

Modify `src/probos/cognitive/skill_validator.py` and its direct suite `tests/test_skill_agent.py`. For the single exact top-level async handler, statically prove compatibility with:

```text
handler(intent, llm_client=<client>)
```

- `intent` is accepted positionally (positional-only, positional-or-keyword, or `*args`);
- `llm_client` is accepted by keyword (exact positional-or-keyword/keyword-only name or `**kwargs`);
- no extra required positional or keyword-only parameter is unsupplied;
- reject keyword-only/missing intent, positional-only `llm_client`, unrelated names without `**kwargs`, and duplicate exact handlers;
- accept `(intent, llm_client=None)`, `(intent, *, llm_client=None)`, `(intent, **kwargs)`, and `(*args, **kwargs)`; `llm_client` need not default because dispatch always supplies it.

Use AST signature data pre-execution. Keep import, forbidden-pattern, and side-effect checks intact.

After load, warm boot additionally requires `inspect.iscoroutinefunction(handler)` and a non-executing `inspect.signature(handler).bind(probe_intent, llm_client=None)` (or equivalent). Decorator/rebinding that produces a sync, non-callable, or bind-incompatible object is quarantined under the stable observed hash and never attached.

### DD-8 — End-to-end acceptance goes through `SkillBasedAgent.handle_intent()`

Capture the restored `Skill`, add it to a real `SkillBasedAgent`, dispatch a real matching `IntentMessage`, and assert `await agent.handle_intent(...)` returns the expected `IntentResult` and receives the agent's LLM client keyword. Direct handler invocation or `iscoroutinefunction` alone is not acceptance.

## Implementation sections

### Section 1 — Identity and serialization foundation

Modify `src/probos/knowledge/store.py`: shared name/hash validators, per-intent lock registry, validated/serialized store/load/reread/marker/remove APIs, zero-side-effect rejection, hostile-filename skip.

### Section 2 — Atomic, bounded, redacted marker

Modify `src/probos/knowledge/store.py`, `src/probos/security/pii_redaction.py`, `tests/test_knowledge_store.py`, and `tests/test_pii_redaction.py`: atomic same-directory publication, cleanup, strict shape, centralized redaction, expected-hash compare results.

### Section 3 — Actual handler contract

Modify `src/probos/cognitive/skill_validator.py` and `tests/test_skill_agent.py`: accepted/rejected AST signature matrix; preserve generated underscore conventions.

### Section 4 — Stable warm-boot state machine

Modify `src/probos/warm_boot.py`, `src/probos/runtime.py`, and `tests/test_bf656_boot_log_hygiene.py`: inert detector, maximum-three-snapshot retry, compare-before-act, clear-before-attach, post-load async/bind check, preserve/quarantine non-stubs, retryable attachment failures, and a warm-boot no-repersist callback path whose default remains persistence-on.

### Section 5 — Deterministic race coverage

Use `asyncio.Event` barriers or monkeypatched public methods; no sleeps. Required races:

1. source changes between initial load and matching-marker skip: repaired source is revalidated;
2. source changes after validation but before quarantine write: old marker is not written;
3. source changes before inert prune: changed source is not deleted;
4. source changes after import but before attachment: old handler is not attached;
5. clear(hash A) versus re-quarantine(hash B): B survives;
6. quarantine(hash A) versus `store_skill()` source B: marker A is not published for B;
7. explicit remove versus marker write: no orphan marker;
8. three consecutive changes exhaust retry bound with no execution/attachment/destructive mutation;
9. temp-write failure leaves prior complete marker or absence, never torn JSON, and cleans temp;
10. exact restored skill dispatches through real `SkillBasedAgent.handle_intent()`.

## Required test matrix

### Identity/path safety

- Accept `calculate`, `translate_text`, `count_words`, `get_weather`, and digits after the first character.
- Reject `""`, whitespace, `.`, `..`, `a..b`, `/tmp/x`, `C:\\tmp\\x`, `\\\\server\\share`, `a/b`, `a\\b`, `my-skill`, `my skill`, `1skill`, uppercase, colon, Unicode/non-ASCII.
- Parameterize every direct skill/marker/remove API; assert no internal/external path effects, lock entry, or commit.
- A hostile descriptor filename is skipped without aborting a valid sibling.

### Marker integrity/redaction

- Atomic round trip preserves source+descriptor bytes.
- Write bounds: reason ≤500, errors ≤20, each ≤500.
- Strict read rejects oversized fields/list, wrong types, uppercase/non-hex hash, missing fields, naive/non-UTC timestamp, malformed/torn JSON.
- Raw marker bytes contain none of the supplied bearer/authorization/secret/client-secret/credential/token/password/API-key values.
- Failed compare-and-act does not schedule a commit.

### Handler/recovery

- Full accepted/rejected signature matrix from DD-7.
- Decorated/rebound sync or bind-incompatible runtime handler is rejected post-load.
- Comment-only stub prunes once; mismatched/syntax/import/forbidden/load failures remain byte-for-byte recoverable.
- Stable marker suppresses retry; changed exact source clears stale marker before attach.
- All ten deterministic cases above.
- Success dispatches through real `SkillBasedAgent.handle_intent()`.

## Do Not Build

- Do not auto-rename/sanitize/normalize/slugify/move/rewrite names, source, descriptors, or handlers.
- Do not attach `handle_other` as `wanted` or delete any non-stub failure.
- Do not add UI, CLI, repair workflow, sweeper, database, migration, config, or cross-process locking.
- Do not change generic mesh-intent naming, AgentSkills.io catalog naming, designed-agent restore, trust, routing, episodes, workflows, or QA restore.
- Do not widen `KnowledgeStoreProtocol`.
- Do not edit `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, or issue text.

## Files

**Modify:**

- `src/probos/knowledge/store.py`
- `src/probos/warm_boot.py`
- `src/probos/runtime.py`
- `src/probos/cognitive/skill_validator.py`
- `src/probos/security/pii_redaction.py`
- `tests/test_bf656_boot_log_hygiene.py`
- `tests/test_knowledge_store.py`
- `tests/test_skill_agent.py`
- `tests/test_pii_redaction.py`

**Reference only:**

- `src/probos/substrate/skill_agent.py`
- `src/probos/cognitive/skill_designer.py`
- `src/probos/cognitive/self_mod.py`
- `src/probos/config.py`
- `src/probos/protocols.py`
- `src/probos/shutdown_integrity.py`

## Test commands

Set a unique isolated `PROBOS_DATA_DIR` for each command and `PROBOS_EMBEDDINGS=local`.

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf656_boot_log_hygiene.py tests/test_knowledge_store.py tests/test_skill_agent.py tests/test_pii_redaction.py -q -n 0 -W error::RuntimeWarning
    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_self_mod_deps.py tests/test_cognitive_agent_skills.py tests/test_semantic_knowledge.py -q -n 0 -W error::RuntimeWarning
    d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 0

## Acceptance criteria

1. One strict shared validator rejects unsafe/non-canonical names before path/lock/side effects and preserves existing valid conventions.
2. Store/load/reread/marker/remove operations share per-intent serialization without recursive deadlock.
3. Marker publication is unique sibling temp + flush + `fsync` + `os.replace`, with cleanup and no torn JSON.
4. Marker reads trust only bounded exact shape (20 errors, 500 characters per reason/error, lowercase SHA-256, aware UTC timestamp).
5. Central redaction covers bearer/authorization/secret/client-secret/credential and existing token/password/API-key forms.
6. Marker write/clear and conditional remove use expected-hash compare semantics; stale operations cannot overwrite/erase newer state.
7. Warm boot uses at most three snapshots and rehashes before skip/mutate/load/clear/attach; exhaustion preserves without execution.
8. A stale marker clears before attachment; a newer marker survives and blocks old attachment.
9. Warm-boot attachment does not call the design-time persistence write; the existing runtime callback still persists by default for all normal callers.
10. Only inert source auto-deletes; every non-stub failure remains recoverable.
11. Static and post-load checks prove compatibility with `handler(intent, llm_client=<client>)`.
12. Restored skill dispatch succeeds through real `SkillBasedAgent.handle_intent()`.
13. Deterministic race tests cover all ten listed cases without sleeps.
14. No database/config/UI/CLI/sweeper/protocol/tracker/unrelated scope.
15. Focused, blast-radius, and full serial gates pass with exact counts reported.
16. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop conditions

Stop if an invalid name reaches path construction or is sanitized; any non-stub is deleted; compare-before-act cannot be guaranteed; warm boot needs private store paths; a newer marker can be cleared by old work; old imported code can attach after source changes; signature checking happens after attachment; deterministic races need sleeps; or DB/config/UI/CLI/sweeper/protocol/tracker scope is required.

## Verified Against Codebase (2026-07-10, HEAD f097f924)

- `src/probos/knowledge/store.py:253,261` — store and scan derive paths directly from unvalidated names/stems.
- `src/probos/knowledge/store.py:288,333,356,364` — marker/remove APIs have no expected-hash compare result.
- `src/probos/knowledge/store.py:995` — generic JSON write is direct `write_text`, not atomic replace.
- `src/probos/security/pii_redaction.py:17-19` — current token regex lacks bearer/authorization/secret/credential forms.
- `src/probos/shutdown_integrity.py:104-124` — sibling temp + `fsync` + `os.replace` precedent exists.
- `src/probos/warm_boot.py:190-363` — one initial hash, matching-marker skip, and marker clear after attachment; no bounded reread state machine.
- `src/probos/startup/cognitive_services.py:501-511` wires the warm-boot callback from `add_skill_to_agents_fn`; `src/probos/runtime.py:4921-4964` shows `_add_skill_to_agents()` always persists through `store_skill()` today.
- `src/probos/cognitive/skill_validator.py:17-23,52-65` — docstring claims signature validation; implementation checks only exact async name.
- `src/probos/substrate/skill_agent.py:74-83` — live call is `await skill.handler(intent, llm_client=self._llm_client)`.
- `src/probos/cognitive/skill_designer.py:42-56,133-135` — exact `handle_<intent_name>` generation.
- `src/probos/runtime.py:5110-5135,4963` — extraction requests snake_case and persistence stores `skill.name` unchanged.
- Live valid conventions: `translate_text`/`summarize_text`, `calculate`/`manage_todo`, `get_weather`/`get_news` in utility agents.
- `tests/test_skill_agent.py:251+` is the direct validator suite and currently lacks a signature matrix.
