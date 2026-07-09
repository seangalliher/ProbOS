# AD-1119 — Referent-Grounding Gate (guard G1)

**Target repo:** OSS (`d:\ProbOS`).
**Epic:** Cascade-Confabulation Prevention (`prompts/cascade-confab-prevention-ADs.md`) · issue **#1022**.
**AD numbering:** Highest **landed** AD = **AD-1118**. **AD-1119 is the new top-level** (the first of the three-AD epic; AD-1120/#1023 and AD-1121/#1024 follow and depend on this AD's resolver/verdict API — do **not** build them here).

A default-OFF, additive `ReferentGroundingGate` (cognitive layer) that extracts candidate referents from a group-chat room-seed message, resolves each against ground truth (git objects, the agent registry, ward-room channels) via constructor-injected `typing.Protocol` resolvers, and returns a `{referent → RESOLVED|UNRESOLVED}` verdict plus a gap-regex-safe **honest-absence cue** for the unresolved ones. Wired **observe-only** at exactly **one** seam (`group_chat_fanout`) behind `config.grounding.referent_gate_enabled=False`. **No behavioral change** in this AD (the cue is computed and logged, never injected into an agent's context — that is AD-1120).

---

## Why / context

Live-runtime forensic trace (2026-07-08): the crew ran a multi-agent "Oracle Health Check" investigation into node **`e77acec7`** — a **fabricated** id (not a git object, not in any source file, DB, or artifact). Root cause (mechanism #2 of the trace): **no agent verifies that an identifier/entity exists before reasoning about it.** `e77acec7` would have been caught at first mention by a referent gate. This is the `CASCADE_CONFAB` anti-pattern already coded in `emergence_taxonomy.py` — classified post-hoc, never **prevented**. AD-1119 is the highest-leverage prevention: resolve the referent before the crew builds an investigation on it.

Research basis (absorb, do not re-derive): MAST *task-verification* failure class (arXiv 2503.13657); Chain-of-Verification (arXiv 2309.11495). This AD is the deterministic **guard** half of the defense-in-depth pair; AD-1120 is the behavioral half.

**Grounding pattern this mirrors:** the AD-958c **observe-only** fan-out wiring (`_observe_conversation_corrections`, [src/probos/routers/thread_fanout.py](../src/probos/routers/thread_fanout.py) L898–936) and the AD-981b **honest-absence cue** (`_recall_confidence_note`, [src/probos/cognitive/cognitive_agent.py](../src/probos/cognitive/cognitive_agent.py) L7505).

---

## Pinned design decisions (settled against HEAD — cite these in the build)

### DD-1 — The wiring seam is `group_chat_fanout`, observe-only, at the top (HIGHEST-VALUE decision)
**Seam:** `async def group_chat_fanout(runtime, thread_id, *, captain_body, captain_msg, opener_id=None)` — [thread_fanout.py](../src/probos/routers/thread_fanout.py) **L939**. Insert **one awaited call** immediately after `agent_ids = crew_agent_participants(runtime, thread.participants)` at **thread_fanout.py:972**, before the AD-967 roster build (L973):
```python
    await _observe_referent_grounding(runtime, thread, captain_body)
```
**Why this seam (and not the alternatives):**
- `captain_body` **is** the room-seed / current-turn text (the input the crew reasons on); the seam already has `runtime` (→ registry, ward_room, config) and `thread`. It runs **once per Captain group turn, before any agent is dispatched** — the exact choke point where the confab cascade begins.
- It is **group-scoped** (the confabulation locus). The HTTP entry `append_message` ([routers/threads.py](../src/probos/routers/threads.py) L340) also fires for **1:1** posts → wrong scope. The substrate `ChatThreadStore.append_message`/`create_thread` ([threads/__init__.py](../src/probos/threads/__init__.py) L921/L236) are **substrate layer** → a cognitive gate there is a **layer violation**. `group_chat_fanout` (a cross-cutting router that already imports cognitive helpers) is the correct layer.
- **Observe-only** = mirror `_observe_conversation_corrections` exactly: a module-level `def`/`async def` helper whose **first executable line** is the flag early-return, wrapped in Tier-2 honest-degrade, emitting a structured log per detection and **touching nothing** (`all_replies` is never read or mutated). This is what makes AD-1119 purely additive and lets AD-1120 add the behavioral injection later against this AD's public verdict API.

### DD-2 — Resolver set + the git-object check is a subprocess (there is NO in-process git seam)
`codebase_index.py` is a **pure AST index — it has no git-object API** (verified: no `git`/`cat-file`/`rev-parse`/`subprocess` in the file). Do **not** add one and do **not** touch `codebase_index.py`. The established git pattern in this repo is `asyncio.create_subprocess_exec("git", ...)` (AD-303 builder, AD-434 ships-records). Three concrete resolvers, each honest-degrading to `False` ("this resolver did not confirm") — never raising, never returning `True` on error:
- **`GitObjectResolver`** — `asyncio.create_subprocess_exec("git", "cat-file", "-e", f"{token}^{{object}}", cwd=repo_root, stdout=DEVNULL, stderr=DEVNULL)`; `returncode == 0` → confirmed. `repo_root` is **constructor-injected** (default `Path(__file__).resolve().parents[3]` for `src/probos/cognitive/referent_gate.py` → repo root; overridable so a test injects a real `tmp_path` git repo). A missing git binary / non-repo `cwd` / non-zero exit / timeout → `False` (logged), **not** an exception. `^{object}` matches any object type (blob/tree/commit/tag) and resolves abbreviations + packed objects (a filesystem `.git/objects/` check cannot resolve an 8-char prefix like `e77acec7`).
- **`AgentResolver(registry, callsign_registry)`** — confirmed if ANY of: `registry.get(token) is not None` (agent id — [registry.py](../src/probos/substrate/registry.py) L58 `get(agent_id) -> BaseAgent | None`), `registry.get_by_pool(token)` non-empty (pool — L61), or `callsign_registry.resolve(token) is not None` (crew callsign — [crew_profile.py](../src/probos/crew_profile.py) L711; **existence is liveness-independent** — `resolve` returns the dict even when `agent_id` is `None` for a resting crew member, so `is not None` is the correct existence test).
- **`WardRoomResolver(ward_room)`** — confirmed if `await ward_room.get_channel_by_name(token) is not None` ([ward_room/service.py](../src/probos/ward_room/service.py) L267, `async`). **Guard `ward_room is None`** — `runtime.ward_room` is `WardRoomService | None` and is `None` until `start()` ([runtime.py](../src/probos/runtime.py) L752). `None` → resolver returns `False`.

**Resolution policy:** for each extracted referent, try **all** resolvers in order; **first `True` → RESOLVED**; all `False` → UNRESOLVED. (A hex token could be a git object *or* an agent id; trying all is the forgiving, correct reading of "first resolver that confirms.")

### DD-3 — The gate module is `runtime`-free (DIP); the wiring site builds the resolvers
`src/probos/cognitive/referent_gate.py` imports **nothing** from a higher layer and **never** imports `runtime`. The concrete resolvers take **narrow** constructor deps (`registry`, `callsign_registry`, `ward_room`, `repo_root`) — not `runtime`. A factory `build_default_resolvers(*, registry, callsign_registry, ward_room, repo_root=None) -> list[ReferentResolver]` (in `referent_gate.py`, taking narrow deps) lets the `thread_fanout.py` helper wire it from `runtime.registry` / `runtime.callsign_registry` / `getattr(runtime, "ward_room", None)`. This keeps the gate unit-testable with real fixtures (BF-287) and no `runtime` mock.

### DD-4 — Honest-absence cue is a `@staticmethod`, gap-regex-safe (reuse AD-981b)
Mirror `CognitiveAgent._recall_confidence_note` ([cognitive_agent.py](../src/probos/cognitive/cognitive_agent.py) L7505): a pure `@staticmethod _honest_absence_cue(token: str) -> str` returning a cue the caller (AD-1120) can inject, e.g.:
> `"No ship referent resolves for '<token>'. Treat it as structurally unresolvable: do not build an investigation on it, and do not invent details to make it real. If nothing resolves, the correct finding is that there is no such referent."`

The wording **must not** trip the decomposer capability-gap regex `_CAPABILITY_GAP_RE` ([decomposer.py](../src/probos/cognitive/decomposer.py) L33; `is_capability_gap` L43). Forbidden substrings: `can't`, `cannot`, `unable to`, `lack*`, `don't have`, `no <X> capability|ability|support|way|mechanism|tool`, `not available|supported|possible`, `outside ... scope`. Safe: `"do not"` (with a space), `"no such referent"`, `"structurally unresolvable"`, `"nothing resolves"`. **Returns `""`** when there is nothing to add (no unresolved referents) so nothing is ever emitted spuriously.

### DD-5 — Extraction is a pure function; code spans are stripped first
`extract_referents(text: str) -> list[Referent]` (pure, no I/O, independently unit-tested). Preprocess: **strip fenced ```` ``` ```` blocks and inline `` `code` `` spans first** so a sha inside a code fence is NOT extracted (the AD's explicit negative). Then match, dedupe (first-seen order), cap at 20:
- **hex** — `\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}\b` (the lookahead requires ≥1 `a–f` letter, so a plain decimal like `1234567` is excluded — a git-SHA/node-id shape, not a number).
- **entity** — `\b(?:node(?:\s+id)?|record|entity)\s+([A-Za-z0-9_\-]{2,64})\b` (case-insensitive); capture the token.
- **service** — a conservative "asserted live system" match: a Capitalized word (or a `*_service` snake token) immediately followed by one of `service|membership|telemetry|cluster|node` → capture the leading name. (Deliberately conservative to bound false positives. A **genuine** service name that is a real agent/pool/channel still resolves via the agent/ward-room resolvers; a fabricated one — "Oracle membership" — falls through to UNRESOLVED, which is the intended catch.)

`Referent` = `@dataclass(frozen=True)` `{token: str, kind: str, raw: str}`. `GroundingVerdict` = `@dataclass(frozen=True)` `{results: dict[str, str], unresolved: tuple[str, ...], cues: dict[str, str]}` with a `has_unresolved` property. `async def evaluate(text) -> GroundingVerdict` **never raises** (catastrophic failure → empty verdict, logged); each resolver call is individually wrapped so one raising resolver is treated as `False` and the ref falls through.

---

## Build

1. **`src/probos/cognitive/referent_gate.py` (NEW)** — in this order:
   - `Referent` (frozen) and `GroundingVerdict` (frozen, with `has_unresolved`).
   - `extract_referents(text) -> list[Referent]` — pure, DD-5 (code-span strip + 3 regex kinds + dedupe + cap 20).
   - `class ReferentResolver(typing.Protocol)` — `kind: str` (a label for logging) and `async def resolve(self, token: str) -> bool`.
   - `class GitObjectResolver` / `class AgentResolver` / `class WardRoomResolver` — DD-2 (each honest-degrades to `False`, never raises).
   - `class ReferentGroundingGate` — `__init__(self, resolvers: list[ReferentResolver])` (DIP, DD-3); `async def evaluate(self, text: str) -> GroundingVerdict` (DD-2 policy + DD-4 cue for unresolved); `@staticmethod _honest_absence_cue(token) -> str` (DD-4). `evaluate` never raises.
   - `build_default_resolvers(*, registry, callsign_registry, ward_room, repo_root=None) -> list[ReferentResolver]` — narrow-dep factory (DD-3).
   - Full type annotations on all public methods; structured `logger.warning`/`logger.debug` with context on every honest-degrade.
2. **`src/probos/routers/thread_fanout.py` (MOD)** — add a module-level `async def _observe_referent_grounding(runtime, thread, seed_text) -> None` mirroring `_observe_conversation_corrections` (L898): first line `cfg = getattr(getattr(runtime, "config", None), "grounding", None)` then `if not getattr(cfg, "referent_gate_enabled", False): return`; build the gate via `build_default_resolvers(...)` from `runtime.registry`/`runtime.callsign_registry`/`getattr(runtime, "ward_room", None)`; `verdict = await gate.evaluate(seed_text or "")`; emit one `logger.warning("AD-1119[observe]: unresolved referent thread=%s token=%r cue=%r (observe-only, no behavioral change)", ...)` per `verdict.unresolved`; Tier-2 `try/except → logger.warning + return`. Wire **one** awaited call at **thread_fanout.py:972** (after `agent_ids = ...`, DD-1).
3. **`src/probos/config.py` (MOD)** — add `class GroundingConfig(BaseModel)` mirroring `OSActivityConfig` ([config.py](../src/probos/config.py) L6010): `referent_gate_enabled: bool = Field(default=False, description="AD-1119: consent/enable gate for the referent-grounding gate. Default OFF (byte-identical when off).")`. Mount on `SystemConfig` beside `os_activity`/`device` (~config.py:6051): `grounding: GroundingConfig = Field(default_factory=GroundingConfig)  # AD-1119 (default OFF)`. **No `config/system.yaml` edit** (model default keeps a default install byte-identical).
4. **`tests/test_ad1119_referent_gate.py` (NEW)** — see Acceptance.
5. **Trackers** — `PROGRESS.md` (`**AD-1119 shipped**` line) + `DECISIONS.md` (`### AD-1119` heading) in the same commit.

---

## Acceptance

- **Extraction happy** (`test_extract_finds_hex_entity_service`) — a bare hex, a `node <tok>` / `entity <tok>` phrase, and a `<Name> membership` service span are all extracted with the right `kind` and first-seen order.
- **Extraction negatives** (`test_extract_excludes_code_spans_and_decimals`) — a hex inside a ```` ``` ```` fence and inside inline `` `code` `` is excluded; a plain decimal (`1234567`) is excluded; ordinary prose is excluded; `""` → `[]`.
- **RESOLVED via real git object** (`test_git_resolver_resolves_real_object`) — build a **real** `tmp_path` git repo (`git init`, commit a file), take the real short sha, and assert `GitObjectResolver(repo_root=tmp).resolve(sha)` is `True` and `gate.evaluate` marks it RESOLVED.
- **RESOLVED via real registry/callsign/pool** (`test_agent_resolver_resolves_real_agent`) — a **real** `AgentRegistry()` with a real `BaseAgent` subclass registered; assert the agent id / pool resolves (BF-287: real registry, **no MagicMock**).
- **UNRESOLVED + cue — the headline** (`test_fabricated_hex_unresolved_with_safe_cue`) — `e77acec7` against a real `tmp_path` repo (not an object) + empty real registry + `ward_room=None` → UNRESOLVED, `verdict.cues["e77acec7"]` is non-empty, **and** `is_capability_gap(cue) is False` (import from `probos.cognitive.decomposer` — mirror the AD-981b cue-safety assertion).
- **Resolver honest-degrade** (`test_raising_resolver_does_not_bubble`) — a real tiny `_RaisingResolver` (implements the Protocol, `resolve` raises) → `gate.evaluate` does **not** raise, the ref falls through to UNRESOLVED, and the failure is logged (`caplog`).
- **Git-missing honest-degrade** (`test_git_resolver_non_repo_returns_false`) — `GitObjectResolver(repo_root=<non-repo tmp_path>)` → `resolve` returns `False` (not raise); the hex is UNRESOLVED (proves git-unavailable degrades to unresolved, never crashes, never false-RESOLVED).
- **Default-OFF golden** (`test_observe_off_is_noop`) — with `grounding.referent_gate_enabled=False` (default), `_observe_referent_grounding(runtime, thread, "seed with e77acec7")` returns `None` and builds **no** gate / runs **no** git (assert via a spy `build_default_resolvers` count == 0, or assert zero `AD-1119` log records). The flag-gated first-line early-return **is** the byte-identity guarantee (same shape as `_observe_conversation_corrections`).
- **Flag-ON observe emits, mutates nothing** (`test_observe_on_logs_unresolved`) — flag on + a seed with `e77acec7` → exactly one `AD-1119[observe]` WARNING for the unresolved token, helper returns `None`, no mutation of any passed structure (`caplog`).
- **BF-287 real fixtures** — real `AgentRegistry()`, real `tmp_path` git repo, real `WardRoomService` or `ward_room=None`, real `SystemConfig()` for the flag. The only stubs are **real** Protocol-implementing classes (`_RaisingResolver`, `_SpyResolver`) — no MagicMock at the registry/git/ward-room boundary.
- **Config** (`test_grounding_config_default_off`) — `SystemConfig().grounding.referent_gate_enabled is False`.
- Report the test count and the focused gate result (`-k ad1119`) plus the blast importers (`tests/test_config.py`, a `group_chat_fanout` smoke test if one exists).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** (async hygiene — the awaited helper is not fire-and-forget; layer discipline — the gate module is runtime-free; type annotations; structured logging; DIP resolver injection).

---

## Do NOT build here

- ❌ **AD-1120** (Ground-Before-Collaborate standing order + behavioral cue **injection** into an agent's context). AD-1119 is **observe-only**: compute + log the cue, **never** inject it into any agent's prompt/context, and **do not** add or edit a `config/standing_orders/…` file.
- ❌ **AD-1121** (SelfCheckGPT divergence probe + transcript persistence). No N-sample probe, no transcript persistence, no notification surface.
- ❌ **Do not modify `EmergentDetector` or `emergence_taxonomy.py`** — `CASCADE_CONFAB` stays post-hoc classification; this AD does not fire it.
- ❌ **Do not auto-close / auto-delete / auto-archive** any room or thread on an UNRESOLVED verdict.
- ❌ **No HTTP in agent code / no mesh HTTP.** The `GitObjectResolver` is a **local read-only `git` subprocess**, not HTTP, and not an agent — do not add `httpx`, do not broadcast an `http_fetch` intent.
- ❌ **Do not touch `codebase_index.py`** (no in-process git seam there; the git resolver is standalone).
- ❌ **One seam only** — `group_chat_fanout`. Do not wire into the 1:1 `/chat` path, `append_message` (substrate or router), `create_thread`, or the ward-room fan-out.
- ❌ **Do not change sealed protocols** (`BaseAgent` / `IntentMessage` / `IntentResult`) or alter any prior-AD behavior.
- ❌ **No new top-level AD number** beyond AD-1119. (OSS repo — no pricing/competitive/commercial content.)

---

## Files (verify each at build)

- `src/probos/cognitive/referent_gate.py` **(NEW)** — `Referent`, `GroundingVerdict`, `ReferentResolver` Protocol, `ReferentGroundingGate`, `GitObjectResolver`/`AgentResolver`/`WardRoomResolver`, `extract_referents`, `build_default_resolvers`. **`runtime`-free** (DD-3).
- `src/probos/routers/thread_fanout.py` **(MOD)** — new `async def _observe_referent_grounding(...)` (mirror `_observe_conversation_corrections` L898) + one awaited call at L972.
- `src/probos/config.py` **(MOD)** — `class GroundingConfig` (mirror `OSActivityConfig` L6010) + `grounding` mount on `SystemConfig` (~L6051).
- `tests/test_ad1119_referent_gate.py` **(NEW)** — the Acceptance cases.
- `PROGRESS.md`, `DECISIONS.md` **(MOD)** — AD-1119 entries.
- **No** `config/system.yaml` change.

## Hard-stop conditions (surface to the Architect, do not guess)

- The impl requires a method that does not exist on `AgentRegistry` / `WardRoomService` / `CallsignRegistry` (grep first — all cited signatures are confirmed at HEAD).
- The one-line insertion at thread_fanout.py:972 does not apply cleanly (the file drifted) — re-grep `agent_ids = crew_agent_participants` and place the call immediately after it, before the AD-967 roster build.
- Any temptation to inject the cue into agent context or persist a transcript — that is AD-1120/AD-1121, **stop**.

## Done-when

All Acceptance green; `-k ad1119` green and `tests/test_config.py` unchanged; default-OFF byte-identical (the flag-gated helper early-return); full type annotations on every new public method; the git subprocess is honest-degrading (never raises, never false-RESOLVED); **verify compliance with `.github/copilot-instructions.md`.**
