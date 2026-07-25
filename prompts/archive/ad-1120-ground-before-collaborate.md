# AD-1120 — "Ground-Before-Collaborate" standing order + gate (behavioral B2)

**Repo:** OSS (`d:\ProbOS`) · **Layer:** cognitive + config + standing-orders · **Depends on:** AD-1119 (shipped, on disk)
**Tracking issue:** #1023 (pre-assigned) · **Highest landed AD at drafting:** AD-1119 · **Est. tests:** 12–15
**Status:** DRAFT — Architect verified against HEAD 2026-07-09. Awaiting review → Builder.

> One line: when enabled, turn AD-1119's *observed* honest-absence cue into an *injected* one — steer the crew to the "structurally unresolvable" close instead of confabulating on a fabricated referent — plus add the always-on constitutional norm that makes "no such referent" a rewarded finding. Default-OFF → the injection path is byte-identical.

---

## Why

Live-runtime forensics (2026-07-08) traced a crew "Oracle Health Check" that reasoned at length about node `e77acec7` — a **fabricated** id (not a git object, agent, ward-room channel, or in any source/DB). AD-1119 shipped the deterministic guard: it **extracts, resolves, and computes** a gap-clean honest-absence cue for the unresolved referents — but is **observe-only** (logs `AD-1119[observe]` warnings; changes nothing).

AD-1120 closes the behavioral half. The crew *almost* self-corrected (Wesley: *"treat the membership question as structurally unresolvable"*) — but only **after** fabrication. AD-1120 makes grounding a **precondition** and "unresolvable" a **rewarded terminal state**:

1. **Behavioral cue injection (flag-gated).** When a room seed has an unresolved **central** referent, inject AD-1119's honest-absence cue into each dispatched crew agent's context so the LLM is steered to the "do not build an investigation on it" close. Rides the **exact** AD-967 `room_roster` param path.
2. **Standing order (always-on).** A constitutional norm in `ship.md`: no multi-agent investigation proceeds past framing until its central referent is verified; if it does not resolve, the correct, valued finding is "no such referent — structurally unresolvable," and the room closes.

This depends only on AD-1119's shipped verdict/resolver API. It does **not** build the divergence probe or transcript persistence (that is AD-1121).

---

## Pinned DDs (design decisions — do not deviate without escalating)

### DD-1120-1 — Injection = fan-out context via `params`, mirroring AD-967 `room_roster`
Compute the verdict **once** at the fan-out choke point (inside `_observe_referent_grounding`), **return** the selected central cue, and thread it through `group_chat_fanout` → `_fan_one_round(grounding_cue=...)` → `_send_one` → `params["grounding_cue"]` on the `direct_message` `IntentMessage`. A new overridable CognitiveAgent hook `_conversational_grounding_cue_block(observation)` renders it (mirroring `_conversational_room_awareness_protocol`).

**Rejected: agent-side re-extraction.** Injecting inside `cognitive_agent._decide_via_llm` would force the agent to re-extract + **re-resolve** referents (a second git subprocess per agent) with no access to the seed at the choke point. The fan-out already holds `captain_body`, already computes the verdict (AD-1119), and already has the tested `room_roster` param seam — so the cue rides it for free, computed once, threaded through. Cleaner (DRY, single resolve, single seam) and correct (the LLM still does the reasoning; we only add context).

### DD-1120-2 — Central-referent selection (solves carry-forward risk #1: determiner junk)
`GroundingVerdict` carries `.unresolved`/`.cues` but **not** kinds. Re-run `extract_referents(seed_text)` (pure, no I/O — this is **not** a re-resolve; the git subprocesses live in `evaluate`) to build `{token: kind}`. Then:

- **central** = the **first** token in `verdict.unresolved` (seed-appearance order, already preserved) whose `kind ∈ {"hex", "entity"}`, `token.lower() not in _GROUNDING_STOPWORDS`, and (for `hex`) git is available (DD-1120-3).
- Inject `verdict.cues[central]` **verbatim** — it is the AD-1119 wording, already proven `is_capability_gap`-clean (AD-1119 `test_fabricated_hex_unresolved_with_safe_cue`).
- If no token survives → return `None` (no injection).

**Why kind-restrict to `hex`/`entity`:** AD-1119's DD-5 `_SERVICE_RE` matches `Capitalized + node|service|…`, so a sentence-initial determiner (`The node …`) captures token `"The"` (a known AD-1119 conservative-but-noisy behavior, safe for an observe log, **unsafe** to inject). Injection changes behavior, so it must be high-precision: dropping the `service` kind removes the entire determiner-false-positive class **without touching the AD-1119 regex** (out of scope). `_GROUNDING_STOPWORDS` is defense-in-depth for the theoretical `entity` capture (`node the` → `"the"`).

### DD-1120-3 — Resolver-availability gate (solves carry-forward risk #2: git-less deploy)
`GitObjectResolver` honest-degrades to `False` when git is unavailable → on a git-less deploy **every** hex reads UNRESOLVED, which would falsely tell the crew every hex id is fabricated. Gate: probe git **once** via `GitObjectResolver().resolve("HEAD")` (reuses the **shipped** resolver as a positive control — no edit to `referent_gate.py`). Probe only when at least one otherwise-eligible token is `hex`. If the probe is `False` (git absent / non-repo / zero-commit) → **drop `hex` candidates** from selection (fails safe to today's no-injection behavior). `entity` candidates need no git (their agent/ward-room resolvers are in-process and always ran).

### DD-1120-4 — Two-flag dependency + default-OFF byte-identical; preserve the 3 landed AD-1119 tests
`_observe_referent_grounding` **keeps its name** (3 AD-1119 tests call it by name at `tests/test_ad1119_referent_gate.py` L258/289/325 and assert the return). Change only the **return contract** `None → str | None` and add selection **after** the observe loop:

- **Line 1 unchanged:** `if not referent_gate_enabled: return None` (the byte-identity guarantee + the `test_observe_off_is_noop` contract — DO NOT move or alter).
- **Observe loop unchanged:** the `for token in verdict.unresolved: logger.warning("AD-1119[observe]…")` block (the `test_observe_on_logs_unresolved` "exactly 1 warning" contract).
- **New, after the observe loop:** `if not getattr(cfg, "ground_before_collaborate_enabled", False): return None` → then selection (DD-1120-2/3) → return `verdict.cues[central]` or `None`.

Result: AD-1120 fires **only** when **both** `referent_gate_enabled` **and** `ground_before_collaborate_enabled` are `True`. The 3 landed AD-1119 tests all use `SystemConfig()` (B2 defaults `False`) → they hit the new `return None` after the (unchanged) observe log → **stay green**. With B2 off the fan-out gets `grounding_cue=None` → `_send_one` sets no param → **byte-identical**.

### DD-1120-5 — Standing order = always-on `ship.md` addition (not a new file, not flag-gated)
`compose_instructions` loads **only** the four named tier files (`federation.md`, `ship.md`, `{dept}.md`, `{agent}.md` — `standing_orders.py` L144–147); there is **no** auto-discovery. A new `grounding.md` would be a **dead file** unless `standing_orders.py` is modified (scope creep + a hot path with an `@lru_cache`). `ship.md` is Tier-2, loaded ship-wide for every crew agent on every `decide()` (confirmed: the group-chat conversational path seeds `composed = compose_instructions(...)` at `cognitive_agent.py` L2971). So the norm goes into `ship.md` as a new `<!-- category: core_directives -->` section — **always-on constitutional guidance** (the AD-729a `peer_observation.md`/`ship.md` precedent), gap-clean.

**Byte-identity scope:** the default-OFF byte-identical guarantee applies to the **flag-gated cue-injection path** (fan-out param + the new hook). The `ship.md` prose is an always-on constitutional norm and **does** change the composed prompt vs HEAD by design. **Do NOT** write a golden asserting the full agent prompt equals HEAD. (See Risks: this always-on choice is the one judgment call worth the Captain's veto.)

---

## Build

> Grep-anchor every edit — line numbers below are HEAD-at-drafting and will drift. Keep AD-1119's early-return and observe loop untouched.

### Section 1 — `config.py`: add the B2 flag to `GroundingConfig`
In `GroundingConfig` (≈L6035), directly **after** the `referent_gate_enabled` field (≈L6048–6051), add:

```python
    ground_before_collaborate_enabled: bool = Field(
        default=False,
        description=(
            "AD-1120: when True (and referent_gate_enabled is also True), inject the "
            "AD-1119 honest-absence cue for an unresolved CENTRAL room referent into "
            "each dispatched crew agent's context. Default OFF (injection path "
            "byte-identical when off; has no effect unless referent_gate_enabled is on)."
        ),
    )
```

No change to the `SystemConfig.grounding` mount (L6071). Update the `GroundingConfig` class docstring's final parenthetical to note B2 (still additive).

### Section 2 — `thread_fanout.py`: verdict → cue selection → thread through the roster seam
**2a. Imports (≈L36–40).** Extend the `referent_gate` import to add `GitObjectResolver` and `extract_referents`:

```python
from probos.cognitive.referent_gate import (
    GitObjectResolver,
    ReferentGroundingGate,
    build_default_resolvers,
    extract_referents,
)
```

**2b. Module constants (near the other module constants, ≈L55–75).**

```python
# AD-1120: kinds eligible for cue INJECTION. `service` (DD-5) is excluded — its
# Capitalized-word match can capture a sentence-initial determiner ("The node"
# -> "The"), acceptable in an observe log but not as a behavioral cue. Injection
# changes behavior, so it is restricted to the high-precision kinds.
_GROUNDING_INJECT_KINDS = frozenset({"hex", "entity"})
# AD-1120: determiner / stop-word guard (defense-in-depth for an `entity`
# capture like "node the" -> "the"). Lower-cased comparison.
_GROUNDING_STOPWORDS = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "it", "its", "their",
    "our", "your", "his", "her", "node", "record", "entity", "service",
})
```

**2c. Extend `_observe_referent_grounding` (≈L943).** Keep the signature name; change the return annotation to `str | None`; keep the AD-1119 early-return **and** the observe loop **verbatim**; append the B2 gate + selection. New tail (after the existing `for token in verdict.unresolved:` observe loop):

```python
    # AD-1120: behavioral half. Observe-only (return None) unless B2 is enabled.
    if not getattr(cfg, "ground_before_collaborate_enabled", False):
        return None
    return _select_central_cue(verdict, seed_text or "")
```

Add a new module-level pure-ish helper (git probe is the only I/O, once, and only for a hex):

```python
async def _select_central_cue(verdict: Any, seed_text: str) -> str | None:
    """AD-1120: pick the CENTRAL unresolved referent's honest-absence cue, or None.

    ``verdict`` is the AD-1119 ``GroundingVerdict``. Selection (DD-1120-2/3):
    re-extract referents (pure — NOT a re-resolve) for their kinds, keep the
    first unresolved token whose kind is injectable (hex/entity), which is not a
    determiner/stop-word, and — for a hex — only when git is actually available
    (DD-1120-3, so a git-less deploy does not falsely flag every hex). Returns
    ``verdict.cues[token]`` verbatim (gap-clean by AD-1119) or None when nothing
    qualifies. Tier-2 honest-degrade: any failure returns None (no injection).
    """
    try:
        kinds = {r.token: r.kind for r in extract_referents(seed_text)}
    except Exception:
        logger.warning(
            "AD-1120: referent re-extract failed; skipping cue selection",
            exc_info=True,
        )
        return None
    # Candidate tokens in seed order, kind- and stop-word-filtered.
    candidates = [
        t for t in verdict.unresolved
        if kinds.get(t) in _GROUNDING_INJECT_KINDS
        and t.lower() not in _GROUNDING_STOPWORDS
    ]
    if not candidates:
        return None
    # DD-1120-3: probe git ONCE, only if a hex candidate exists.
    git_ok = True
    if any(kinds.get(t) == "hex" for t in candidates):
        try:
            git_ok = await GitObjectResolver().resolve("HEAD")
        except Exception:
            logger.warning(
                "AD-1120: git availability probe failed; treating git as "
                "unavailable (hex cues skipped)", exc_info=True,
            )
            git_ok = False
    for t in candidates:
        if kinds.get(t) == "hex" and not git_ok:
            continue
        return verdict.cues.get(t)
    return None
```

**2d. Capture the return in `group_chat_fanout` (≈L1031).** Change the discarded call into a capture:

```python
    grounding_cue = await _observe_referent_grounding(runtime, thread, captain_body)
```

**2e. Thread `grounding_cue` through both `_fan_one_round` call sites** (round 0 ≈L1123, cascade ≈L1234) — add `grounding_cue=grounding_cue,` alongside the existing `room_roster=room_roster,`.

**2f. `_fan_one_round` (≈L410):** add a keyword-only param `grounding_cue: str | None = None` next to `room_roster` (≈L424). Inside `_send_one`, immediately **after** the AD-967 `if room_roster: params["room_roster"] = room_roster` block (≈L563–564), add:

```python
        # AD-1120: honest-absence cue for an unresolved CENTRAL room referent.
        # Rides the same params dict as room_roster (AD-967); omitted when None
        # (default-OFF / resolved / ineligible) so the fan-out is byte-identical.
        if grounding_cue:
            params["grounding_cue"] = grounding_cue
```

### Section 3 — `cognitive_agent.py`: render the cue (new overridable hook)
**3a.** Add the hook next to the other group blocks (near `_conversational_room_outputs_block` ≈L2495 / `_conversational_room_awareness_protocol` ≈L2608):

```python
    def _conversational_grounding_cue_block(self, observation: dict) -> str:
        """AD-1120: inject the honest-absence cue for an unresolved CENTRAL room
        referent so the LLM is steered to the "structurally unresolvable" close
        instead of confabulating. Gated to the GROUP fan-out path: returns "" unless
        ``params["is_group_chat"]`` AND the fan-out attached a ``grounding_cue``
        (only set when ``ground_before_collaborate_enabled`` + an eligible unresolved
        central referent). The cue is the AD-1119 string verbatim — already
        ``is_capability_gap``-clean. Overridable (Open/Closed). Byte-identical when
        no cue is attached."""
        params = observation.get("params") or {}
        if not params.get("is_group_chat"):
            return ""
        cue = params.get("grounding_cue")
        if not isinstance(cue, str) or not cue.strip():
            return ""
        return "\n\n" + cue.strip()
```

**3b.** Compose it in the conversational branch, immediately **after** the BF-651 `_outputs_proto` block (≈L3226–3228, just before the `else:` at ≈L3229):

```python
            # AD-1120: ground-before-collaborate honest-absence cue. Overridable
            # hook; base returns "" unless this is a group fan-out AND the fan-out
            # attached a grounding_cue (only when ground_before_collaborate_enabled
            # + an eligible unresolved central referent). Steers the LLM to the
            # "structurally unresolvable" close. Byte-identical when off.
            _grounding_proto = self._conversational_grounding_cue_block(observation)
            if _grounding_proto:
                composed += _grounding_proto
```

### Section 4 — `config/standing_orders/ship.md`: the always-on constitutional norm
Append a new section (choose placement near the other `core_directives`). Text MUST pass `is_capability_gap(...) == False` — avoid `can't/cannot/unable to/don't have/lack*/not available|supported|possible/beyond … capabilities/outside … scope`. The following draft is gap-clean (verify with the acceptance test):

```markdown
<!-- category: core_directives -->
## Ground Before You Collaborate

Before the crew builds a multi-agent investigation on an identifier or named
entity — a node id, a git object, an agent, a channel, a service — that referent
must first be verified to exist against ship ground truth. No investigation
proceeds past framing until its central referent is grounded.

If the central referent does not resolve to anything real on the ship, that is not
a dead end to work around — it is the answer. The correct and valued finding is:
"there is no such referent; the question is structurally unresolvable." State that
plainly and close the room. Do not invent details to make an unresolved referent
real, and do not read unrelated memory or telemetry hits as confirmation that it
exists.

A finding of "structurally unresolvable" is a successful outcome. Reaching it
early protects the crew from building a long, confident investigation on something
that was never there.
```

### Section 5 — Tests: `tests/test_ad1120_ground_before_collaborate.py` (NEW)
BF-287 discipline (mirror `tests/test_ad1119_referent_gate.py`): real `AgentRegistry()`, a real `tmp_path` git repo (`_init_git_repo`) for git-available cases, real `SystemConfig()`, `_RealAgent(BaseAgent)`, `SimpleNamespace` runtime, `@_requires_git` where git is exercised. **No MagicMock at the registry/git/ward-room boundary.** Required cases:

1. `test_cue_injected_on_unresolved_hex_central` — both flags on; real tmp git repo (no `e77acec7` object); seed `"Investigate e77acec7 immediately."` → `_observe_referent_grounding(...)` returns a **non-None** cue equal to `verdict.cues["e77acec7"]`; assert `"e77acec7"` in the cue.
2. `test_no_cue_for_determiner_service_token` — both flags on; seed `"The node membership is degraded."` (DD-5 `service` match → token `"The"`) → returns `None` (kind `service` dropped **and** `"the"` in stop-words). Proves the determiner-junk class is not injected.
3. `test_no_hex_cue_when_git_unavailable` — both flags on; monkeypatch so the git probe reports unavailable (e.g. `monkeypatch.setattr(thread_fanout.GitObjectResolver, "resolve", <async False>)`, or point `repo_root` at a non-repo `tmp_path`); seed with a fabricated hex → returns `None` (hex dropped by the availability gate). Proves a git-less deploy does not flag every hex.
4. `test_no_cue_when_central_resolves` — both flags on; register `_RealAgent(agent_id="beef1234")`; drop the git resolver (agent resolver alone) so `beef1234` resolves; seed `"look at beef1234 please"` → returns `None` (resolved → not unresolved).
5. `test_default_off_returns_none_no_param` — `SystemConfig()` (both flags off) → returns `None` (existing `test_observe_off_is_noop` already guards the spy/log side; this asserts the AD-1120 return contract).
6. `test_g1_on_b2_off_still_observe_only` — `referent_gate_enabled=True`, `ground_before_collaborate_enabled=False`; unresolved hex seed → returns `None` (observe-only) and still emits exactly one `AD-1119[observe]` warning. Proves the two-flag dependency and that AD-1120 did not regress the AD-1119 observe path.
7. `test_block_renders_cue_on_group_param` — construct an `observation = {"intent": "direct_message", "params": {"is_group_chat": True, "grounding_cue": "<cue>"}}`; a real minimal `CognitiveAgent` (or `_RealAgent`) `._conversational_grounding_cue_block(observation)` returns a string containing the cue.
8. `test_block_empty_without_param_or_group` — same hook returns `""` when `is_group_chat` is falsy, and `""` when `grounding_cue` is missing/blank (byte-identical when off).
9. `test_cue_is_capability_gap_clean` — `is_capability_gap(cue) is False` for the injected cue.
10. `test_ship_md_section_is_capability_gap_clean` — read the new `ship.md` section text and assert `is_capability_gap(section) is False`. (Load `config/standing_orders/ship.md`, slice the `## Ground Before You Collaborate` section, or assert on the whole file.)
11. `test_ground_before_collaborate_config_default_off` — `SystemConfig().grounding.ground_before_collaborate_enabled is False`.

**Regression gate:** `tests/test_ad1119_referent_gate.py` must stay green unchanged (the 3 `_observe_referent_grounding` call sites rely on B2-default-off → `None`).

### Section 6 — Trackers (additive only)
- `PROGRESS.md`: one AD-1120 entry (files touched, flag, two-flag dependency, byte-identity scope, test count).
- `DECISIONS.md`: `### AD-1120: Ground-Before-Collaborate …` with DD-1120-1…5 summarized. Append-only; do not renumber.

---

## Acceptance criteria

- `_observe_referent_grounding` returns a **non-None** cue **only** when `referent_gate_enabled` **and** `ground_before_collaborate_enabled` are both `True` **and** an eligible unresolved central referent exists; `None` otherwise.
- **Central-referent selection** excludes `service`-kind and determiner/stop-word tokens (a `"The node …"` seed injects nothing).
- **Resolver-availability gate**: with git unavailable, no `hex` cue is injected.
- **Default-OFF byte-identical (injection path)**: with `ground_before_collaborate_enabled=False`, the fan-out attaches no `grounding_cue` param and the new hook returns `""`.
- The injected cue and the `ship.md` section both satisfy `is_capability_gap(text) is False`.
- All three landed `tests/test_ad1119_referent_gate.py` `_observe_referent_grounding` cases stay green **unchanged**.
- Full type annotations on new public/module surfaces; structured logging with context; boundary tests (happy + determiner + git-unavailable + resolved + both-off + G1-on/B2-off).
- New tests in `tests/test_ad1120_ground_before_collaborate.py`; BF-287 real fixtures (real `AgentRegistry`, real `tmp_path` git repo, real `SystemConfig`) — no MagicMock at the substrate boundary.
- `get_errors` clean on all created/modified files.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build (boundaries)

- **AD-1121** — no SelfCheckGPT-style divergence probe, no context-free re-query, no room-transcript persistence.
- **No auto-close / auto-delete / auto-archive of threads.** "The room closes" is *behavioral guidance to the LLM* via the cue + standing order — **not** a code path that terminates, deletes, or archives a thread.
- **No trust-scoring changes** — do not record a trust outcome for a resolved/unresolved referent.
- **No new consensus path**, no new intent, no destructive intent.
- **No edits to `referent_gate.py`** — reuse its shipped public API (`extract_referents`, `GitObjectResolver`, `GroundingVerdict`, `build_default_resolvers`). Do **not** change the AD-1119 DD-5 regexes (the determiner false positive is handled by *selection*, not by re-regexing).
- **No `standing_orders.py` change** — no new loaded tier, no auto-discovery; the norm goes into the already-loaded `ship.md`.
- **No second wiring seam** — the only injection point is `group_chat_fanout` via the AD-967 `room_roster` param path. Do not inject in `cognitive_agent._decide_via_llm`, the 1:1 DM path, or the ward-room path.
- **No HTTP** in agent code; the git probe is the shipped `GitObjectResolver` subprocess only.
- Do not re-run the AD-1119 verdict twice — compute it once in the fan-out and thread the cue through (`extract_referents` re-call for kinds is pure and allowed).

---

## Files

- `src/probos/config.py` **(MOD)** — `GroundingConfig.ground_before_collaborate_enabled`.
- `src/probos/routers/thread_fanout.py` **(MOD)** — import `GitObjectResolver`/`extract_referents`; `_GROUNDING_INJECT_KINDS`/`_GROUNDING_STOPWORDS`; extend `_observe_referent_grounding` return + new `_select_central_cue`; capture return in `group_chat_fanout`; `grounding_cue` param on `_fan_one_round` + `params["grounding_cue"]` in `_send_one` + both call sites.
- `src/probos/cognitive/cognitive_agent.py` **(MOD)** — new `_conversational_grounding_cue_block` hook + compose call after `_outputs_proto`.
- `config/standing_orders/ship.md` **(MOD)** — always-on `## Ground Before You Collaborate` section.
- `tests/test_ad1120_ground_before_collaborate.py` **(NEW)** — cases 1–11 above.
- `PROGRESS.md`, `DECISIONS.md` **(MOD)** — additive AD-1120 entries.

---

## Done when

- `pytest tests/test_ad1120_ground_before_collaborate.py -q -n 0` green.
- `pytest tests/test_ad1119_referent_gate.py -q -n 0` green **unchanged** (regression gate).
- Blast: `pytest tests/test_config.py <thread_fanout test files> tests/test_ad1119_referent_gate.py -q -n 0` green, 0 regressions.
- `get_errors` clean on all created/modified files.
- Default-OFF byte-identity of the injection path demonstrated (a test proving no `grounding_cue` param + hook `""` when the flag is off).

---

## Verified against codebase (2026-07-09)

```
# Injection mechanism (AD-967 room_roster param path)
routers/thread_fanout.py:410   async def _fan_one_round(
routers/thread_fanout.py:424     room_roster: list[str] | None = None,
routers/thread_fanout.py:563-564   if room_roster: params["room_roster"] = room_roster
routers/thread_fanout.py:992   async def group_chat_fanout(
routers/thread_fanout.py:1031    await _observe_referent_grounding(runtime, thread, captain_body)
routers/thread_fanout.py:1037-1040 room_roster built ONCE
routers/thread_fanout.py:1123    room_roster=room_roster,   # round 0
routers/thread_fanout.py:1234    room_roster=room_roster,   # cascade round

# Helper to extend (single caller L1031; called by 3 AD-1119 tests)
routers/thread_fanout.py:943   async def _observe_referent_grounding(runtime, thread, seed_text) -> None
tests/test_ad1119_referent_gate.py:258/289/325  result = await thread_fanout._observe_referent_grounding(...)  # assert result is None (B2 default-off)

# Render seam (cognitive_agent group hooks)
cognitive_agent.py:2971   composed = compose_instructions(...)   # conversational path loads ship.md
cognitive_agent.py:2495   def _conversational_room_outputs_block   # neighbor hook
cognitive_agent.py:2608   def _conversational_room_awareness_protocol  # gating template
cognitive_agent.py:3226-3228  _outputs_proto block  # insert new hook call right after

# Config
config.py:6035   class GroundingConfig(BaseModel)
config.py:6048   referent_gate_enabled: bool = Field(default=False, ...)
config.py:6071   grounding: GroundingConfig = Field(default_factory=GroundingConfig)

# Standing-orders loader (named tiers only — no auto-discovery)
cognitive/standing_orders.py:144-147   ("federation","federation.md"),("ship","ship.md"),("department",…),("agent",…)

# AD-1119 public API reused
cognitive/referent_gate.py   extract_referents(text)->list[Referent(.token/.kind)]; class GitObjectResolver.resolve(token); GroundingVerdict(.unresolved/.cues); build_default_resolvers(*, registry, callsign_registry, ward_room, repo_root=None)

# Capability-gap regex the cue + ship.md must stay clean of
cognitive/decomposer.py:33   _CAPABILITY_GAP_RE ; :43 def is_capability_gap(response)->bool
```
