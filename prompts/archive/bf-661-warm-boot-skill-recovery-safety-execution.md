# BF-661 Builder Execution — Warm-boot skill recovery safety

**GitHub issue:** #1027
**Base:** HEAD `f097f9243fb019d11a828b5fa9f577ad5f9af1b4`
**Scope:** execute only `prompts/bf-661-warm-boot-skill-recovery-safety.md`; all implementation-review blockers are mandatory.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-661-warm-boot-skill-recovery-safety.md`
- all exact modify/reference files below

## Exact files

**Modify only:**

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

No trackers. No commit.

## Non-negotiable contracts

### 1. Identity — reject, never sanitize

- One shared validator runs before lock/path use in store, scan/load, source reread, marker load/write/clear, and remove.
- Accept unchanged ASCII `^[a-z][a-z0-9_]*$`, not a keyword, with `handle_<name>.isidentifier()` true.
- Preserve `calculate`, `translate_text`, `count_words`, `get_weather`.
- Reject empty/non-string, absolute/UNC/POSIX paths, `/`, `\`, any `.`, traversal, hyphen, whitespace, colon, uppercase, leading digit, Unicode/non-ASCII, and incompatible handler names.
- Direct calls raise `ValueError` with zero path, lock-registry, or commit effects. Hostile scan entries warn/skip while valid siblings load.
- Do not change generic mesh intents or AgentSkills.io catalog names.

### 2. Serialization and expected-hash compare

- One per-intent `asyncio.Lock` registry per store serializes store, paired load/reread, marker load/write/clear, and remove.
- Validate before lock lookup; use private locked helpers to avoid recursive acquisition; no global scan lock.
- Marker write/clear and conditional remove take strictly validated expected SHA-256 and return whether mutation happened.
- Quarantine writes only if `sha256(source_code)` and current source both equal expected hash.
- Clear deletes only a valid marker with expected hash.
- Conditional remove deletes only if current source equals expected hash; explicit hashless administrative remove remains.
- Only successful mutation schedules a commit.

### 3. Atomic bounded marker and centralized redaction

- Publish with unique same-directory temp, flush + `os.fsync`, then `os.replace`; clean temp on all failures.
- Strict write/read shape: reason ≤500, errors ≤20 and each ≤500, lowercase 64-hex hash, matching validated name, aware UTC ISO timestamp.
- Malformed/oversized/torn/naive/non-UTC marker warns and returns `None`; it cannot suppress validation.
- Extend central `PIIRedactor` for `Authorization: Bearer`, bare `Bearer`, authorization/secret/client_secret/credential/credentials key-value forms, plus existing token/password/API-key forms. Assert raw marker bytes contain no supplied secret.

### 4. Warm boot — maximum three stable snapshots

- Treat `load_skills()` source as only candidate 1; use at most two public `load_skill_source()` rereads.
- Reread/re-hash before matching-marker skip and before prune, quarantine, import/load, clear, and attach as applicable.
- A change discards old validation/handler decisions and retries. Exhaustion preserves everything and executes/attaches/mutates nothing.
- Stable invalid source uses expected-hash quarantine; stable inert source uses expected-hash remove.
- Valid source: final pre-load hash check, import, post-load check, clear an observed matching stale marker **before attachment**, then reread/re-hash immediately before attach. No-marker success needs no clear; a failed clear requires marker/source reload and only benign current absence may proceed.
- A newer marker survives; old compiled code never attaches after source changes. Attachment failure stays unhashed/retryable.
- Warm boot must not invoke the callback's design-time persistence write after its final source check. Add a default-on `persist` keyword (or equivalent explicit restore callback), pass `False` only from warm boot, assert no-repersist in `tests/test_bf656_boot_log_hygiene.py`, and assert default persistence in `tests/test_skill_agent.py`.
- Warm boot never accesses private store paths.

### 5. Actual handler call shape

`SkillValidator` statically proves compatibility with:

    handler(intent, llm_client=<client>)

- positional-compatible `intent` or `*args`;
- keyword-compatible exact `llm_client` or `**kwargs`;
- no unsupplied required extra positional/keyword-only parameters;
- reject keyword-only/missing intent, positional-only llm_client, unrelated names without kwargs, and duplicate exact handlers;
- accept `(intent, llm_client=None)`, `(intent, *, llm_client=None)`, `(intent, **kwargs)`, `(*args, **kwargs)`.

After load, require `inspect.iscoroutinefunction()` and non-executing `inspect.signature(...).bind(probe_intent, llm_client=None)` before attachment.

### 6. End-to-end proof

Capture restored `Skill`, add it to a real `SkillBasedAgent`, dispatch a real matching `IntentMessage` through `SkillBasedAgent.handle_intent()`, and assert the expected `IntentResult` and injected LLM client. A direct handler call is insufficient.

## Build order

1. Add name/hash validators, lock registry, and validated/serialized persistence+reread seams.
2. Add expected-hash marker/remove APIs and atomic bounded publication.
3. Extend centralized redaction and tests.
4. Enforce validator signature matrix.
5. Implement warm-boot three-snapshot state machine, post-load checks, and no-repersist attachment seam.
6. Add deterministic races and end-to-end dispatch.
7. Run all gates; stop at a failing logical-step gate.

## Required deterministic tests

Use `asyncio.Event` barriers or monkeypatched public seams; **no sleeps**:

1. source changed before matching-marker skip is revalidated;
2. source changed before quarantine prevents old-hash marker;
3. source changed before inert prune is not deleted;
4. source changed after import prevents old handler attachment;
5. clear(A) cannot erase re-quarantine(B);
6. quarantine(A) cannot publish after `store_skill()` writes B;
7. remove serialized with marker write leaves no orphan;
8. three unstable snapshots exhaust with no execute/attach/prune/write/clear;
9. temp-write failure leaves complete old marker or absence, no torn JSON/temp leak;
10. exact restored handler dispatches through real `SkillBasedAgent.handle_intent()`.

Also parameterize every direct skill/marker/remove API over the required invalid-name matrix; prove no path escape/side effect/commit. Add strict malformed-marker tests and full accepted/rejected handler-signature matrix from the main prompt.

## Commands

Use a fresh isolated `PROBOS_DATA_DIR` per command, set `PROBOS_EMBEDDINGS=local`, and remove it afterward.

Focused:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf656_boot_log_hygiene.py tests/test_knowledge_store.py tests/test_skill_agent.py tests/test_pii_redaction.py -q -n 0 -W error::RuntimeWarning

Blast radius:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_self_mod_deps.py tests/test_cognitive_agent_skills.py tests/test_semantic_knowledge.py -q -n 0 -W error::RuntimeWarning

Full serial:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 0

Before handback:

    git diff --check
    git status --short

## Hard stops

Stop if an invalid name reaches a path or is transformed; any non-stub is deleted; expected-hash compare cannot be guaranteed; warm boot needs private store paths; a newer marker can be cleared by old work; imported old code can attach after change; warm boot would re-persist source after its final hash check; signature checking executes the handler or happens after attachment; race tests require sleeps; or DB/config/UI/CLI/sweeper/protocol/tracker scope is needed.

Do not edit trackers. Do not commit. Report exact test counts, commands, pre-existing failures, and every deviation.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
