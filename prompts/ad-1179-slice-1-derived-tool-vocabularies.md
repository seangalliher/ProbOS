# AD-1179 (slice 1) — derive every schema vocabulary from one named constant

**Kill the BF-701/BF-706 drift class at the layer where it actually lives: the enum, not the schema.**

| | |
|---|---|
| **Issue** | [#1111](https://github.com/seangalliher/ProbOS/issues/1111) — AD-1179 (already allocated; do NOT mint a new AD) |
| **Also ships** | **BF-867** — `mouse_button` has never executed. Repaired here because the Section 3 guard is red without it. |
| **Status** | Ready to build |
| **Dependencies** | none. Siblings AD-1177, AD-1178 already shipped. |
| **Estimated new tests** | ~30 |
| **HEAD verified against** | `6fcde788` |

---

## 1. Problem

### 1a. The class

A tool declares a vocabulary in several places, one of which is the executable gate. The gate can
silently disagree with what the agent was told. Shipped twice already:

- **BF-701** — `BrowserTool` declared its action vocabulary three times (description, schema enum,
  a set literal in `invoke()`). The set held **11** where the other two held 12. `key_type` was
  built completely by AD-1160 and dead from the day it shipped.
- **BF-706** — four verbs governed identically to already-offered ones were withheld. The agent
  needed Ctrl+F, had no verb for it, and typed the literal text `Control+f` into the Captain's
  document.

BF-701 fixed this **for the top-level action of one tool** by deriving all three declarations from
`_AGENT_ACTIONS`. That fix is correct and guarded. Every other vocabulary in the tool surface is
still a hand-written literal.

### 1b. It has already recurred — measured, not inferred

`mouse_button` is on the agent surface, named in the description, listed in the schema enum, and
**fails unconditionally**. Driven through the real dispatcher with the exact dict production
forwards:

```
params passed to handler = {'action': 'mouse_button', 'button': 'left'}
  RAISED: ValueError: mouse_button 'action' must be one of: down, up, click

CONTROL — can the agent reach the branch another way?
  sending {'action': 'down', ...} routes on action='down':
    ValueError: unknown browser action: down

CONTROL — sibling verb from the same BF-706 wave:
  mouse_move OK: {'session_id': 'sess-1', 'x': 5, 'y': 7}
```

`tool.py:490` calls `dispatch_action(session, action, params)` with the **same** dict that carries
the dispatch key. `_action_mouse_button` (`actions.py:949-954`) then reads `params.get("action",
"click")` as its own sub-verb — so it always sees `"mouse_button"`, the `"click"` default is
unreachable, and there is no value the agent can send that both routes to this handler and
satisfies it.

**Why five drift guards missed it.** All five compare the top-level enum to the gate frozenset.
The broken contract is one layer down, inside a handler, on a parameter the schema never declared.

**Why the tests missed it.** Every `mouse_button` test calls `_action_mouse_button` **directly**
with a dict it constructs itself (`test_ad1160_canvas_actions.py:126,142,155,187,198,199,213`;
`test_ad706e_action_vocab_v2.py:150,158`). `dispatch_action` is exercised in tests for `key_type`,
`state`, `click`, `goto`, `screenshot` — enumerated with `rg 'dispatch_action' tests/`, **never for
`mouse_button`**, and no test calls `BrowserTool.invoke` with `action="mouse_button"`. Handler
tested, gate tested, nothing crosses the seam. The canonical half-chain.

**Why BF-706's own guard missed it.** `test_bf706_input_verbs.py:179` —
`test_every_new_verb_has_its_parameters` — is exactly the right guard, written for exactly this
defect ("offering a verb without the parameters it requires is the same defect one layer down").
Its parametrize table carries **one** parameter per verb: `("button", "mouse_button")`. It verified
the parameter that works and never asked whether the handler required a second one.

**Reachability, bounded honestly.** `_BROWSER_LOOP_ACTIONS`
(`agentic_dispatch.py:114` = `{goto, state, extract_text, back, forward, wait}`) excludes
`mouse_button`, so the AD-1153 read-only loop offer never advertises it. It is reachable only by an
agent holding `browser` through a Captain grant, which gets the full 16-verb surface.

### 1c. The census — 9 enums, 7 hand-written

AST-scanned every `enum` literal appearing inside a tool `input_schema`:

| # | Tool | Property | Source today | Gate |
|---|---|---|---|---|
| 1 | `BrowserTool` | `action` | ✅ `list(_AGENT_ACTIONS)` | `_AGENT_ACTION_SET` |
| 2 | `OracleQueryTool` | `kind` | ✅ `[*SIGMA_TIERS, "all"]` | same |
| 3 | `BrowserTool` | `button` | ❌ literal | `actions.py:950` tuple |
| 4 | `BrowserTool` | `direction` | ❌ literal | `actions.py:638` set |
| 5 | `StandingOrdersLookupTool` | `scope` | ❌ literal | `tools.py:375` tuple + an error string + the description prose = **4** restatements |
| 6 | `EventLogQueryTool` | `order` | ❌ literal | `event_log_query_tool.py:139` tuple |
| 7 | `EventLogQueryTool` | `aggregate` | ❌ literal | `:142` tuple **and** `:179` tuple = **3** restatements |
| 8 | `SearchCapabilitiesTool` | `kind` | ❌ literal | `_SPECIFIC_KINDS` + `"all"` |
| 9 | `PublishFindingTool` | `classification` | ❌ literal | `records_store._CLASSIFICATION_LEVELS`, already imported at `:494` for validation and **re-typed** at `:373` for the schema |

Two are already derived. Seven are the BF-701 shape. #9 is the sharpest illustration: the module
comment at `:90` says the vocabulary is *"imported rather than re-typed so the two cannot drift"* —
true of the validator, false of the schema thirty lines below it.

### 1d. Parameter-level drift is NOT the problem

An AST scan of `invoke` bodies (keys read off `params`, alias-tracked, so `.get()` on result and
context dicts do not confound it) across 19 statically-comparable tools found **18 exact matches**
and one benign hit: `_FindMcpToolTool` accepts an undeclared `concept` alias beside the declared
`query`. Extended into the 16 browser action handlers: **zero** undeclared keys, **one** dispatch-key
collision (`mouse_button`).

So the work is at the **enum** layer, not the parameter layer. Scope accordingly.

---

## 2. Decision — option 3, scoped and strengthened. Options 1 and 2 are rejected on measurement.

**Adopt the pattern this repo has already proven twice** (`_AGENT_ACTIONS`, `_ALLOWED_KEYS`): name
each vocabulary once as an ordered module constant, have the schema and the executable gate both
read it, and add generic tests that fail when they cannot.

### Why not option 2 (Pydantic `model_json_schema()`)

Measured against `EditFileTool`'s current schema:

```
+ top-level key 'title' = 'EditFileParams'
~ property 'path'        : pydantic={'title': 'Path', 'type': 'string'}   current={'type': 'string'}
~ property 'replace_all' : pydantic={'anyOf': [{'type':'boolean'},{'type':'null'}], 'default': None, 'title': ...}
                           current={'type': 'boolean'}
key order: pydantic emits properties→required→title→type; current emits type→properties→required
enum-bearing model: emits "$defs" + {"$ref": "#/$defs/Action"} instead of an inline enum
```

Byte-identical: **no**. Semantically identical: **no**.

A normalizer that strips titles, collapses `anyOf`, inlines `$ref` and re-orders keys is itself a
hand-maintained declaration of what the wire shape must be — a new drift surface, in exchange for
removing an old one.

And the `$ref` form is not merely cosmetic. `_narrow_browser_offer` (`agentic_dispatch.py:498`)
reads `parameters.properties.action.enum` directly; a `$ref` gives it no `enum`, it takes its
documented log-and-degrade branch, and **the BF-690 read-only restriction stops being advertised
while the invoke-time guard keeps refusing** — the exact defect BF-690 exists to fix, traded away
for a hypothetical one.

### Why not option 1 (type hints on the invoke signature)

There is nothing to derive from. The AD-423a Tool Protocol fixes the signature at
`invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None)` for all 23 tools
(`tools/protocol.py:126`). Option 1 requires first inventing a typed params model per tool — which
is option 2, reached the long way, with the same emitter problem.

### The argument that decides it

Both 1 and 2 produce a schema **the handler does not consume**. `invoke` would still do
`params.get("path")`, so the derived declaration and the implementation could still disagree — a
derivation nothing validates against is the half-chain shape this repo keeps producing. Making it
load-bearing means rewriting 23 `invoke` bodies to construct the model, which is a behaviour change
the issue puts explicitly out of scope.

Separately: per-property `description` strings are the bulk of every schema's bytes and cannot be
derived from a type at all. Options 1 and 2 **relocate** hand-authoring; they do not remove it.

The named-constant pattern is byte-identical by construction (the constant holds the same strings
in the same order), it makes the schema and the gate read the **same object**, and it is already
the house answer.

---

## 3. Implementation

### Section 0 — BF-867: repair `mouse_button` (blocker)

`src/probos/tools/browser/actions.py`

Add the ordered vocabularies near the other module constants:

```python
# BF-867: the mouse-button vocabularies, ordered, declared once. The schema
# enum, the gate and the error text all read these — see AD-1179.
_MOUSE_BUTTONS: tuple[str, ...] = ("left", "right", "middle")
_MOUSE_PRESSES: tuple[str, ...] = ("down", "up", "click")
_SCROLL_DIRECTIONS: tuple[str, ...] = ("up", "down", "left", "right")
```

Repair the handler. The sub-verb moves to `press`, a parameter the schema declares:

```python
async def _action_mouse_button(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Press, release, or click a specific mouse button at the current position."""
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    button = params.get("button", "left")
    if button not in _MOUSE_BUTTONS:
        raise ValueError(
            "mouse_button 'button' must be one of: " + ", ".join(_MOUSE_BUTTONS)
        )
    # BF-867: read 'press', not 'action'. 'action' is the dispatch key -- it is
    # always "mouse_button" here, so this branch raised on every call and the
    # "click" default was unreachable. The verb was offered and refused for its
    # whole life, which is BF-701 recurring inside BF-706's own fix.
    press = params.get("press", "click")
    if press not in _MOUSE_PRESSES:
        raise ValueError(
            "mouse_button 'press' must be one of: " + ", ".join(_MOUSE_PRESSES)
        )
    ...
    if press == "down":
        ...
    elif press == "up":
        ...
    return {"session_id": session.session_id, "button": button, "press": press}
```

Also point `_action_scroll` (`:638`) at `_SCROLL_DIRECTIONS` — same one-line move, and it is enum #4.

`src/probos/tools/browser/tool.py` — declare the parameter, immediately after `"button"` so the
golden diff is a single insertion:

```python
"press": {
    "type": "string",
    "enum": list(_MOUSE_PRESSES),
    "description": "BF-706/BF-867: 'mouse_button' action — whether to press ('down'), release ('up'), or press-and-release ('click'). Defaults to click.",
},
```

Import `_MOUSE_BUTTONS`, `_MOUSE_PRESSES`, `_SCROLL_DIRECTIONS` from `actions` and use
`list(...)` at the `button` and `direction` enum sites (`tool.py:222,223`).

**Do NOT** accept `action` as a fallback for `press`. A lenient alias is the
`_FindMcpToolTool.concept` shape and it would make the guard in Section 3 unwritable.

### Section 1 — single-source the remaining five enums

Each is: introduce an **ordered tuple** constant whose elements are the current literal in the
current order, point the schema at `list(CONST)`, point the gate at the same constant.

| Tool | Constant | Note |
|---|---|---|
| `StandingOrdersLookupTool` (`swe_harness/tools.py:355`) | `_STANDING_ORDERS_SCOPES = ("ship","department","agent")` | Also build the `:376` error string and the `:354` description from it — currently 4 restatements. |
| `EventLogQueryTool` (`:390`) | `_ORDERS = ("newest_first","oldest_first")` | Gate at `:139`. |
| `EventLogQueryTool` (`:395`) | `_AGGREGATIONS = ("none","cooperation_signature")` | **Two** gates: `:142` and `:179`. Both must read it. |
| `SearchCapabilitiesTool` (`:97`) | `_KINDS = tuple(label for _, label in _AXES) + ("all",)` | See the trap below. |
| `PublishFindingTool` (`:373`) | module-level `from probos.knowledge.records_store import _CLASSIFICATION_LEVELS`, schema uses `list(_CLASSIFICATION_LEVELS)` | Verified: insertion order is `private, department, ship, fleet` — byte-identical to the current literal. The deferred import at `:494` stays as it is. |

**TRAP — do not derive an enum from a `set`.** `_SPECIFIC_KINDS = {"tool","skill","intent"}`
(`search_capabilities_tool.py:43`) is a set. Python string hashing is randomised per process, so
`list(_SPECIFIC_KINDS)` yields a different order on different boots and the wire bytes would vary
run to run. Derive from the ordered `_AXES` tuple and keep `_SPECIFIC_KINDS` (or rebuild it as
`frozenset(_KINDS) - {"all"}`) for membership — the `_AGENT_ACTIONS` / `_AGENT_ACTION_SET` pattern
exactly.

### Section 2 — the byte-identity mechanism

`tests/fixtures/ad1179_tool_definition_golden.json` + `tests/test_ad1179_tool_schema_golden.py`.

**Capture first, refactor second.** Before touching any source, run a throwaway capture that
constructs each tool deterministically, calls the real
`tool_registration_to_llm_definition(reg)` (`swe_harness/tool_call.py:764` — the **only** producer
of the LLM wire shape, with two callers: `agentic_dispatch.py:2253` and `native_builder.py:161`),
and writes:

```python
json.dumps(definition, ensure_ascii=False, separators=(",", ":"))  # per tool_id
```

Order-preserving on purpose: a key reorder must fail. The test reloads the fixture and asserts
string equality per tool.

Two things the harness must handle, or it will not be reproducible:

- **Instance-dependent schemas.** `PublishFindingTool.input_schema` reads
  `self._max_content_chars`; `_FindMcpToolTool.description` names the connected servers;
  `BrowserTool.description` embeds `len(_AGENT_ACTIONS)`. Construct each with pinned values and
  record them in the fixture header so the capture is repeatable.
- **A tool the harness cannot construct must FAIL the test, not be skipped.** A capture that
  silently covers 18 of 23 tools and a capture that covers all 23 look identical from the outside.
  Assert the covered tool_id set equals an explicit expected set.

**The one permitted diff.** Byte identity holds for every tool that is already correct.
`browser` is not: Section 0 adds exactly one property, `press`, immediately after `button`. Record
that single insertion in the test as a named, commented exception with the BF-867 reason inline.
Nothing else in the browser definition may move — the description is already derived from
`_AGENT_ACTIONS` and is unaffected.

### Section 3 — the drift guards

`tests/test_ad1179_schema_vocabulary_guards.py`. Three generic tests over the registered tool set.

**G1 — every schema enum is a named constant, not a literal.** AST-walk each tool module, find the
`enum` values inside `input_schema`, and assert each is a `Call` to `list`/`tuple` over a `Name`
(or a starred unpacking of one), never an `ast.List` of `ast.Constant`. This is the assertion that
makes a future hand-typed enum fail at review time instead of at runtime.

**G2 — no action handler reads the dispatch key.** For `BrowserTool`, for every action in
`_AGENT_ACTIONS`, resolve its `_HANDLERS` entry, AST-walk it, and assert it never reads
`params["action"]` / `params.get("action")`. This is the guard that catches BF-867. It currently
fails on exactly one verb; after Section 0 it passes.
`verify` dispatches outside `_HANDLERS` (via `action_verify` imported directly in `tool.py`) —
the test must **assert it accounted for every action**, naming the ones resolved outside
`_HANDLERS`, so an unresolvable handler is a failure rather than a silent skip.

**G3 — no handler reads an undeclared parameter.** For each tool whose `invoke` reads keys directly
off `params`, assert `keys_read ⊆ set(schema["properties"])`. Scope it to the tools the scan can
analyse and **enumerate the excluded ones by name in the test body with the reason** (delegated key
admission: `_parse_query`, `_validate_input`, the browser action handlers, which G2 covers
separately). A guard whose coverage set is implicit is a guard that quietly shrinks.
This currently fails on `_FindMcpToolTool` (`mcp_workbench.py:740`), which accepts an undeclared
`concept` alias beside the declared `query`. **Remove the alias** — nothing in `src/` sends
`concept` (`rg 'concept' src/probos/cognitive/mcp_workbench.py` and the tool's own callers), and an
undocumented accepted key is the same defect as an undeclared one.

### What each guard catches, and what it does not

The Captain named four shapes. Answering each, without rounding up:

| Shape | Caught? | By what |
|---|---|---|
| **(a)** an enum value the handler rejects | **Yes** | G1 forces both to read one constant, so they cannot differ. Existing `test_bf701:105` / `test_bf706:202` already assert this for the top-level browser action. |
| **(b)** a handler branch with no enum value — the BF-701 shape that shipped dead code | **No — prevented, not detected.** | There is deliberately no "every handler must be offered" rule: `_HANDLERS` registers 20 verbs and 16 are agent-facing, and `test_bf706:128` enforces that the other four stay off. So nothing can *detect* a missing enum entry in general. What G1 does is make the enum and the gate the same object, so a verb cannot be added to one without the other. **The residual gap is a verb added to `_HANDLERS` and to neither** — that stays invisible, by design. |
| **(c)** a required param the handler ignores | **Yes, where the scan applies.** | G3, schema-only direction. Measured `schema-only=[]` across all 19 analysable tools today. Blind to tools that delegate key admission — those are listed by name in the test. |
| **(d)** a param the handler requires that the schema omits | **Yes.** | G3, handler-only direction (`_FindMcpToolTool.concept`) plus G2 for the dispatch-key special case (`mouse_button`). This is the shape that shipped BF-867. |

Two of four caught, one prevented-but-not-detected with the residual gap named, one caught within a
coverage set the test enumerates. Do not describe these as catching all four.

### Section 4 — repoint the tests that pin the old parameter name

Nine assertions construct `_action_mouse_button` params with `"action"`. **Update them, record why
inline, never delete** — a deleted test cannot stop the defect reopening.

- `tests/test_ad1160_canvas_actions.py:126,142,155,187,198,199,213` — swap `"action"` → `"press"`;
  `:129`'s `result == {...}` gains `"press"` in place of `"action"`.
- `tests/test_ad706e_action_vocab_v2.py:150,158-159` — same; the `pytest.raises` match becomes
  `mouse_button 'press'`.
- `tests/test_ad1160_canvas_actions.py:167` (`test_no_handler_references_the_nonexistent_click_button_method`)
  asserts `"click" not in attributes` over the handler's AST. Renaming the variable does not touch
  `mouse.down`/`mouse.up`, so this stays green — **verify it, do not assume it.**
- `tests/test_bf706_input_verbs.py:179` — add `("press", "mouse_button")` to the parametrize table.
  This is the guard that should have caught BF-867 and was one row short.
- `tests/test_bf695_playwright_host.py:797-799` pins `_action_mouse_button`'s Playwright touch
  sites (`mouse.down`, `mouse.up`, `getattr(page, mouse)`). Unchanged by a parameter rename —
  confirm.

---

## 4. Tests to add

| File | Tests | Covers |
|---|---|---|
| `tests/test_bf867_mouse_button_dispatch.py` | ~8 | The headline: `await dispatch_action(session, "mouse_button", {"action": "mouse_button", "button": "left"})` succeeds and presses. **Drive it through `dispatch_action`, with the dispatch key present in the dict** — a direct handler call with a hand-built dict is what hid this for its whole life. Plus `press="down"`/`"up"`, an invalid `press`, the default, and one end-to-end `BrowserTool.invoke(action="mouse_button")`. |
| `tests/test_ad1179_tool_schema_golden.py` | ~4 | Byte identity per tool; explicit coverage-set assertion; the single named `press` exception. |
| `tests/test_ad1179_schema_vocabulary_guards.py` | ~12 | G1/G2/G3 plus one negative control each (a synthetic tool that violates the rule must fail the guard — otherwise the guard is unfalsifiable). |
| `tests/test_ad1179_vocabulary_constants.py` | ~6 | Each of the seven converted enums equals `list(<its constant>)`; the ordered-tuple rule (assert every vocabulary constant is a `tuple`, not a `set` — the hash-randomisation trap). |

**Every guard needs a negative control.** A test that passes on a clean tree and would also pass on
a broken one proves nothing; this repo has shipped that four times. Build a throwaway tool class
that violates each rule and assert the guard fails on it.

---

## 5. What this does NOT change

- No tool is added to or removed from the offered set.
- No tool's behaviour changes **except** `mouse_button`, which currently has none.
- `_AGENT_ACTIONS` / `_AGENT_ACTION_SET` are untouched. This slice generalises that pattern to six
  more vocabularies; it does not replace, wrap, or duplicate it. The five existing browser drift
  guards stay exactly as they are.
- `tool_registration_to_llm_definition` is not modified. It stays a verbatim pass-through.
- No Pydantic model, no schema normalizer, no JSON-Schema emitter.
- `_ALLOWED_KEYS` is **not** rolled out to the other ~19 tools — see slice 2.
- No file outside `src/probos/tools/`, `src/probos/cognitive/swe_harness/tools.py`,
  `src/probos/cognitive/mcp_workbench.py` and `tests/`.

---

## 6. Slice plan

**This is slice 1 of 2.** It is not the whole of AD-1179, and it should not close #1111.

- **Slice 1 (this prompt)** — the enum layer. Boundary: *a vocabulary that appears as an `enum` in
  a tool's `input_schema`.* Nine of them, seven to convert. This is where both demonstrated defects
  live, and the only place a live one exists today.
- **Slice 2 (not yet written)** — the parameter layer. Adopt `_ALLOWED_KEYS` as the convention
  across the ~19 flat-param tools, so `set(schema["properties"]) == _ALLOWED_KEYS` becomes a sound
  one-line assertion everywhere instead of at three tools. Three already have it
  (`oracle_query_tool.py:81`, `event_log_query_tool.py:35`, `publish_finding_tool.py:85`) and all
  three already satisfy the equality — verified by import, so slice 2's guard would pass on day one
  for them and be unwritable for the rest until they are converted.

**AD-1179 is complete when both have shipped.** Slice 2 has no demonstrated defect behind it; it is
prevention, and it should be scheduled on that basis rather than bundled here to make the AD look
finished.

---

## 7. Tracking

- `PROGRESS.md` — prepend after the `# ProbOS Progress` header block (newest-first). One entry for
  AD-1179 slice 1, one for BF-867.
- `DECISIONS.md` — prepend a `### AD-1179 (2026-08-31) — derive schema vocabularies from one
  constant` under the `## Era V — Civilization` preamble, recording the rejection of options 1 and
  2 **with the measured Pydantic delta**, so it is not re-litigated.
- **Editing either file reddens `test_ad1184_ad_ledger` (3 nodes).** Run
  `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and stage
  `docs/development/open-ads-report.md` + `ad-ledger-snapshot.json` in the same commit.
- **Do NOT touch** `docs/development/roadmap.md`, `README.md`,
  `docs/architecture/federation.md`, `.github/copilot-instructions.md`, or anything under
  `scripts/`. Another session is actively committing there. `roadmap.md` is ~100 ADs behind;
  report the mismatch, do not backfill it.
- Comment the outcome on #1111 and **leave it open** for slice 2.

---

## 8. Gate

**The gate now runs through the canonical wrapper. Never `pytest tests/` directly.**

```
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1179-slice1
```

- Its preflight **refuses an uncommittable tree**. Another session is committing to this repo, so
  run in an **isolated linked worktree** with the wrapper's own untracked dependencies copied in.
- Current green baseline: **25,541 passed / 3 failed / 27 skipped** in a linked worktree. The 3 are
  the known `test_phantom_api_precheck_*` artefacts, which pass in the main tree and fail in a
  worktree because they shell out to repo-relative scripts. Verify they are those three, then count
  them as passes.
- Reconcile before reading any log: `baseline_nodes + new_tests == this_run_nodes`.
- Focused runs during coding:
  `d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:randomly`
- The full suite takes ~15-19 minutes and sits at `[ 99%]` for several of them. That is normal.

**Sequence:** capture the golden → focused tests → adversarial review on the staged diff (use a
different model than wrote the code) → repair findings → commit locally → one broad gate → push.

---

## 9. Acceptance criteria

- [ ] `mouse_button` executes. A test drives it **through `dispatch_action`** with the dispatch key
      present in the params dict, and through `BrowserTool.invoke`.
- [ ] All nine schema enums derive from a named ordered constant; a test asserts every vocabulary
      constant is a `tuple`, never a `set`.
- [ ] The gate for each converted vocabulary reads the same constant the schema does — including
      **both** `_AGGREGATIONS` gates and `StandingOrdersLookupTool`'s error string and description.
- [ ] Emitted LLM tool definitions are byte-identical to the captured HEAD golden for every tool,
      with exactly one named exception: `browser` gains the `press` property.
- [ ] The golden test asserts its own coverage set; a tool it could not construct fails it.
- [ ] G1, G2 and G3 each have a negative control that fails on a deliberately-broken synthetic tool.
- [ ] `_FindMcpToolTool`'s undeclared `concept` alias is removed.
- [ ] `_AGENT_ACTIONS` and the five existing browser drift guards are unchanged.
- [ ] The nine tests pinning `_action_mouse_button`'s old `"action"` parameter are **updated with
      the reason inline**, not deleted, and `test_bf706_input_verbs.py:179` gains its missing row.
- [ ] `scripts/gen_ad_ledger.py` re-run and its two artifacts staged in the same commit.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 10. Verified Against Codebase (2026-08-31, HEAD `6fcde788`)

Issue #1111's anchors are from 2026-08-01 and **have all drifted**:

| Issue said | Actually at HEAD |
|---|---|
| `tool_call.py:107` | **`tool_call.py:764`** — `def tool_registration_to_llm_definition`, body at `:776` |
| `CodeExecutionTool.input_schema` `:112` | **`code_execution_tool.py:501`** |
| `UseSkillTool.input_schema` `:78` | `use_skill_tool.py:78` — unchanged |
| `_MESH_TOOL_SPECS` `agentic_dispatch.py:1349` | **`:1361`** |

The 2026-08-03 comment's anchors have also drifted, and one of its claims is now stale:

| Comment said | Actually at HEAD |
|---|---|
| `_AGENT_ACTIONS` `tools/browser/tool.py:104` | **`:106`**; `_AGENT_ACTION_SET` `:111`; enum `:199`; description `:181` |
| `_ALLOWED_KEYS` `oracle_query_tool.py:148` | **`:81`** |
| `_ALLOWED_KEYS` `event_log_query_tool.py:36` | **`:35`** |
| `_ALLOWED_KEYS` `publish_finding_tool.py:121` | **`:85`** |
| "five drift guards", incl. `test_ad1160_canvas_actions.py:548,556` | **Four**, in three files: `test_bf701:105,118`, `test_bf706:202,203`, `test_ad1153:838`. `test_ad1160_canvas_actions.py` no longer references `_AGENT_ACTIONS` at all — the description-count and description-names-every-action assertions moved to `test_bf701:118` and `test_bf706:203`. |
| "no drift was found anywhere else" | **Falsified.** `mouse_button` is live and broken; reproduced above through the real dispatcher. |

Commands run for this review:

```
rg 'input_schema' src/                          -> 31 classes declare one (AST-enumerated)
rg '_ALLOWED_KEYS|_AGENT_ACTIONS' src/          -> 14 hits in 5 files
rg 'tool_registration_to_llm_definition' src/   -> 1 definition, 2 production callers
rg '_action_mouse_button' src/                  -> 2 hits: the def and its _HANDLERS registration
rg 'dispatch_action' tests/                     -> 32 hits; NONE for mouse_button
rg 'mouse_button' tests/                        -> 35 hits; all direct handler calls
AST scan: enum literals inside input_schema     -> 9 total, 7 hand-written
AST scan: params keys read vs schema properties -> 19 tools comparable, 18 exact, 1 alias
AST scan: browser handlers vs dispatch key      -> 1 collision: mouse_button
import probe: set(properties) == _ALLOWED_KEYS  -> True for oracle_query and event_log_query;
                                                   publish_finding confirmed by reading (:85 vs :338)
import probe: list(_CLASSIFICATION_LEVELS)      -> ['private','department','ship','fleet'] (order matches)
pydantic probe: model_json_schema() vs current  -> not byte-identical, not semantically identical
runtime probe: dispatch_action('mouse_button')  -> ValueError, every call
AD/BF ceiling (git log + gh --state all + prompts/) -> AD-1295, BF-866; next free BF-867
```
