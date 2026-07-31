# AD-1140 — `publish_finding`: agent contribution to the commons (Σ writable) (tools / knowledge)

**Issue: #1061 · Epic #1057 (Σ) · depends on AD-1138 (#1059) and AD-1139 (#1060), both in-tree at HEAD `5f1f5ece`.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1140** (#1061). AD ceiling: AD-1151 assigned (#1076). BF ceiling: BF-677. No new AD, no new BF.**

Give a crew agent one governed verb for putting a finding into the durable commons, so a *different* agent in a *different* session can retrieve it through `oracle_query`. Default-OFF.

This is the write half of Σ. AD-1139 was the read half. It is the first agent-initiated write into a git-backed, semantically-indexed store, so the governance is the deliverable as much as the verb is.

---

## Why / context

`Oracle.write_semantic` (AD-686b, `src/probos/cognitive/oracle_service.py:292`) exists but is for **system artifacts** — its five kinds are `agent` / `skill` / `workflow` / `qa_report` / `event`, dispatched by `getattr(layer, f"index_{kind}")`. There is no kind for "a thing an agent worked out."

`RecordsStore.write_notebook` (`src/probos/knowledge/records_store.py:283`) is the right substrate and has exactly **three** call sites, none of them agent-reachable: `src/probos/proactive.py:3047`, `:4076`, and `src/probos/routers/records.py:106`. Both `proactive.py` sites run in the proactive loop; the router site is a Captain-facing HTTP endpoint. A crew agent inside `AgenticLoop` has no path to any of them.

So today an agent that discovers something useful mid-task has nowhere to put it. That is the missing half of Nooplex §6.2.

**What already works and must be reused, not rebuilt:**

- `write_notebook` → `write_entry` stamps `author` / `classification` / `status` / `created` / `updated` / `revision` into YAML frontmatter and git-commits (`records_store.py:91-190`).
- **AD-1138 indexing is already inside `write_entry`** (`records_store.py:160-183`): when a semantic indexer is attached, every write upserts into the `sk_records` collection. **A publish through `write_notebook` is therefore auto-indexed with zero extra wiring.** Do not add an explicit `index_record` call.
- `check_notebook_similarity` (`records_store.py:381`) is the AD-550 dedup gate — **three layers**: exact-path match (`:419`), staleness, and a **cross-topic fuzzy scan** over the author's own notebook directory capped at `max_scan_entries` (`:483-524`).
- `_safe_path` (`records_store.py:989`) is the traversal guard.

---

## Pinned design decisions

### DD-1 — Governance instrument: department gate + bounds, **not** consensus, **not** a rank floor

An unbounded agent-driven write into a git-backed store is a real abuse surface. The question is *which* control is proportional.

**Consensus: NO.** Three reasons, in order of weight:

1. **Wrong risk class.** ProbOS consensus gates *destructive* operations (`requires_consensus=True` on destructive `IntentDescriptor`s). A publish is additive and fully reversible — git history, `_archived/`, and `publish()` status promotion all exist. The Reversibility Preference axiom says prefer the reversible strategy; this already is one.
2. **No seam exists.** There is no consensus gate on the native tool path. `agentic_dispatch.py` routes consensus only for **MCP** tools via the `McpToolRisk.CONSENSUS` tier (`:356`, `:477-493`). Adding one for a native tool means building a new gate in the dispatch — scope creep, and explicitly out of the epic.
3. **It would not bind the real risk.** The risk is *volume and quality pollution*, not irreversibility. A quorum vote on each individual claim is expensive and would not stop a hundred low-value claims that each pass.

**Rank floor: NO — `ensign: write` upward.** This is the uncomfortable one, so state it plainly: **every crew agent in every department can write to the commons when this flag is on.** A floor at `lieutenant` would make AD-1141 (crew children publishing) dead on arrival, because crew children are ensigns. The bounds in DD-7 are therefore load-bearing — they are the *only* thing standing between a looping agent and an unbounded git repo.

**Department gate: YES — all six.** `allowed_departments=("engineering","science","medical","security","operations","bridge")`, matching AD-1139's grant and for the same two reasons: a commons that excludes half the ship is not a commons, and a narrower grant would corrupt the AD-1143 ablation by measuring "some agents had Σ" instead of "Σ vs no Σ".

**`_GATED_TOOL_IDS`: YES.** Add `"publish_finding"` to the frozenset at `agentic_dispatch.py:79`. Without it, a raw Captain grant lands in `granted_ids` (`:733-736`) and routes around `ToolRegistry.resolve_permission`'s department layer (`registry.py:244-252`), which returns NONE for an out-of-scope department *before* grants are considered. The tool is then re-offered through an explicit `check_permission(..., ToolPermission.WRITE, ...)` call, mirroring the `oracle_ids` block at `:906-919`.

### DD-2 — Every string this tool authors is framed and gap-regex safe

The tool's output is a confirmation, not Σ payload — but it still lands in the agent's context through `AgenticLoop`, which renders tool results as bare content with no consumer-side wrapper. So the same rule applies: framing travels **inline**, in the parenthetical `_ORACLE_DISPOSITION` / `_VISUAL_DISPOSITION` shape (`src/probos/tools/oracle_query_tool.py:87`, `src/probos/perception/working_memory.py:28`).

The confirmation must state: that the claim is durable, that other crew reach it later, and that citing beats narrating.

**Gap-regex constraint.** No authored string may match `_CAPABILITY_GAP_RE` (`src/probos/cognitive/decomposer.py:33-41`, `re.IGNORECASE`). The full forbidden set, read off the live pattern:

`don't have` · `can't` · `cannot` · `unable to` · `no {capability|ability|support|way|mechanism|tool}` (also with `built-in ` / `native ` between) · `not {available|supported|possible}` · **`lack` / `lacks` / `lacking`** · `doesn't {have|support}` · `beyond {my|current} {capabilities|abilities}` · `outside {my|the} {scope|capabilities}`

`lack` is a bare substring match — it is the easiest one to trip and the one most likely to appear in prose about a missing federation transport. Use "do not" (with a space) and positive phrasing. **Assert every module-level string constant against the real imported regex**, not a re-typed copy.

Reference shapes (Builder may improve the wording; the constraints are non-negotiable). **All four — these three plus the DD-4 fleet string — were run against the live `_CAPABILITY_GAP_RE` at HEAD `5f1f5ece` and are clean. If you reword any of them, re-run the check.**

- success — `"(Recorded in Ship's Records as a knowledge claim at {classification} scope. Other crew reach it through a commons query in a later session. Do not narrate this publication; cite the claim if you build on it.)"`
- duplicate — `"(This finding matches an entry already in Ship's Records at {path}. The existing entry stands and nothing further was written. Continue with the task.)"`
- rate-limited — `"(This agent has reached its publication budget for the current hour. The finding stays in working context; publish it again later if it still matters.)"`

### DD-3 — The Knowledge Claim envelope: agent-supplied body, system-owned provenance

**Split.** The claim **text** is the markdown body — so `check_notebook_similarity`'s Jaccard, `RecordsStore.search`'s keyword match, and AD-1138's embedding all see the substance. The **envelope** is YAML frontmatter — so it round-trips through `_parse_document` (`records_store.py:975-990`) and lands whole in AD-1138's `frontmatter_json` sidecar (`semantic.py:403-410`), which makes it queryable.

**Agent-supplied** — the complete `_ALLOWED_KEYS` set, exactly as AD-1139 does it (`oracle_query_tool.py:79`, checked at `:239`):

| Param | Type | Bound |
|---|---|---|
| `title` | str | 1–200 chars, required |
| `claim` | str | 1–`publish_finding_max_content_chars`, required |
| `basis` | str | ≤ 1000 chars, required — *why the agent believes it* |
| `confidence` | float | `0.0 ≤ c ≤ 1.0`, default `0.5` |
| `classification` | str | one of `_CLASSIFICATION_LEVELS`, default `ship` |
| `tags` | list[str] | ≤ 8 entries, each ≤ 32 chars, `^[a-z0-9][a-z0-9-]*$` |

**System-owned** — never accepted from params, stamped by the tool:

| Field | Source | Why not agent-supplied |
|---|---|---|
| `author` | callsign resolved from `context["agent_id"]` | authorship is the whole provenance claim; spoofable authorship makes the envelope worthless |
| `department` | `context["department"]` | feeds AD-554 convergence, which requires ≥2 departments |
| `created` / `updated` / `revision` | `write_entry` (`records_store.py:114-138`) | already system-owned; do not duplicate |
| `claim_id` | `sha256` over canonical `{title, claim, basis}` | content-addressed identity, the mechanism the issue asks for |
| `claim_version` | module constant, `1` | schema version for a later migration |
| `source_node` | injected instance id | the field a fleet transport routes on |
| `session_id` / `work_item_id` | `context["_crew_session_id"]` / `["_crew_work_item_id"]` | task linkage |
| `requested_scope` | see DD-4 | records what the agent asked for when it differs from what was written |
| `contest_state` | literal `"uncontested"` | reserved; nothing flips it in this AD |
| `half_life_days` | config default | **reserved slot, not a live decay** — see below |

**Anti-spoof is enforced by rejection, not by dropping.** `any(key not in _ALLOWED_KEYS for key in params)` ⇒ `error="publish_finding_invalid:parameter"` and **no write**. Silently dropping an `author` key would let an agent believe it stamped provenance it did not.

**`half_life_days` is declared-but-unconsumed and the prompt says so on purpose.** Issue #1061 cites "AD-873 Ebbinghaus decay" as an existing primitive. It is not one for records: AD-873 is the `_composite_recall_score` reranker in `episodic.py` (Generative Agents-style recency/importance/relevance), and there is **no** decay applied to Ship's Records anywhere. Writing `half_life_days` is fine as a reserved slot; **claiming it decays anything is false**. State it as reserved in the field's docstring and in the DECISIONS entry. (This is the AD-1151 lesson: a shipped AD justified itself on a guarantee that did not hold, and the correction cost a whole AD.)

**Round-trip requirement:** every envelope value must be YAML-safe under `yaml.dump` → `yaml.safe_load` — plain `str` / `int` / `float` / `bool` / `list[str]` only. No enums, no dataclasses, no `None` where a reader expects a value. Test the round trip through a real `read_entry`.

### DD-4 — `fleet` is accepted and recorded, is **not** routed, and is written at `ship` scope with `requested_scope: fleet` (LOAD-BEARING)

This is the correction to issue #1061, and it is not cosmetic.

**A `fleet`-classified record is invisible to `oracle_query` at HEAD.** Both Oracle Tier 2 paths query under `_RECORDS_QUERY_SCOPE = "ship"` (`oracle_service.py:67`, used at `:761` and `:794`), and both exclude `fleet`:

- keyword path — `_CLASSIFICATION_LEVELS.get("fleet", 0) == 3 > _CLASSIFICATION_LEVELS.get("ship", 2) == 2` ⇒ `continue` (`records_store.py:878`);
- semantic path — `build_records_scope_filter("ship")` emits `{"classification": {"$in": ["private","department","ship"]}}` (`semantic.py:82-89`); `fleet` is level 3 and is filtered out at query time.

So writing `classification: fleet` produces a **write-only black hole**: the claim is durable, committed, indexed — and retrievable by nobody on this node, including its author. That directly contradicts the epic's one-sentence outcome.

**Decision:** accept `fleet` in the schema, write `classification: ship`, and stamp `requested_scope: "fleet"` in the envelope. Both values come from `_CLASSIFICATION_LEVELS` — no new vocabulary. The claim is discoverable today; a later federation transport reads `requested_scope` + `source_node` and propagates. "Same verb, different scope" is preserved as an *intent record* rather than as an unreachable write.

For every non-`fleet` classification, `requested_scope` equals `classification` — one code path, no special case in the reader.

**The confirmation must be truthful about this.** `"(Recorded at ship scope and marked for fleet distribution. Crew on this ship reach it now; a fleet transport carries it onward once one is configured.)"` — verified clean under the live `_CAPABILITY_GAP_RE`.

**No node boundary is crossed in this AD.** `federation/` exists (`bridge.py`, `router.py`, `transport.py`, `relay.py`, `peer.py`), and nothing in it is touched, imported, or invoked here.

**Adjacent finding, NOT fixed here.** `RecordsStore.read_entry` says *"ship and fleet are readable by all crew"* (`records_store.py:764`) while `RecordsStore.search(scope="ship")` filters `fleet` out (`:878`). Those two disagree about whether `fleet` is broader or narrower than `ship`. That is a latent defect in the store, it predates this epic, and fixing it changes Tier 2 retrieval for every caller. **Do not fix it in AD-1140.** Note it in the build report; the next free BF is **BF-678** if the Captain wants it filed.

### DD-5 — The write lands in `notebooks/{callsign}/` through `write_notebook`

Rejected alternatives and why:

- **A new `claims/` subdir.** Would need a `_SUBDIRS` edit (`records_store.py:15-25`) plus `initialize()` semantics, and — decisively — it would route **around every curation guard**. `check_notebook_similarity` hard-codes `notebooks/{callsign}/{topic_slug}.md` (`:419`) and globs `notebooks/{callsign}/*.md` (`:484`); `check_cross_agent_convergence` iterates `notebooks/*/` (`:569-580`); `notebook_quality` reads `list_entries("notebooks")` (`notebook_quality.py:217`). A claims dir gets none of them. Silently bypassing the guards is the worse failure.
- **`Oracle.write_semantic`.** Its five kinds are fixed and none fit; adding a sixth is explicitly out of scope per the issue.
- **`RecordsStore.write_entry` directly.** Loses the `notebooks/{callsign}/` path convention that all three guards key on.

`write_notebook`'s `classification` default is `department` (`:290`) — the tool passes `ship` explicitly per epic DD-4, so the store default is not relied on and is not changed.

**AD-1138 indexing is automatic** (see Why / context). Assert it in a test; do not call `index_record`.

### DD-6 — Idempotency: content-addressed slug plus the AD-550 gate, called explicitly

`write_notebook` does **not** call `check_notebook_similarity`. `proactive.py` does, at the call site (`:2926`). So `publish_finding` must call it explicitly — this is the concrete meaning of the issue's "passes through them, not around them."

**Slug:** `f"{slugify(title)[:48]}-{claim_id[:8]}"`, where `claim_id` is the full sha256 and the 8-char prefix matches the `compute_content_hash` convention (`provenance.py:58-60`). Slug charset `^[a-z0-9][a-z0-9-]*$`; a title that slugifies to empty ⇒ reject with `error="publish_finding_invalid:title"`.

Behaviour falls out of the three dedup layers, with no new logic:

| Re-publish shape | Path | Gate layer | Outcome |
|---|---|---|---|
| byte-identical claim | same | Layer 2 exact, similarity `1.0`, fresh | **suppress** — no write, no commit |
| identical but > staleness window | same | Layer 2, stale | **update** — `revision++`, `created` preserved |
| near-identical (Jaccard ≥ threshold) | different | Layer 3 cross-topic scan | **suppress** |
| genuinely new | different | no match | **write** |

**Known bound, state it in the docstring:** Layer 3 scans at most `notebook_max_scan_entries` (default 20) entries updated within `notebook_staleness_hours` (default 72). A publisher exceeding that inside the window can slip a near-duplicate past. The DD-7 rate limit is what keeps the flood below that ceiling; the two bounds are coupled by design.

Dedup failure degrades to **write** (matching `proactive.py:2937-2939`), never to a raised exception.

### DD-7 — Abuse bounds, all enforced and all tested

| Bound | Value | Justification |
|---|---|---|
| Per-author rate limit | `publish_finding_max_per_hour = 12` | Each publish is a git commit **and** an embedding upsert. `RecordsConfig.max_episodes_per_hour = 20` is the nearest declared intent; 12 sits under it so a later records-level budget stays the outer bound. |
| Content size | `publish_finding_max_content_chars = 4000` | Exactly `_RECORD_DOC_CHARS` (`semantic.py:25`). Content past 4000 chars is **not embedded** — matching the cap makes "what you publish is what is discoverable" true rather than approximately true. |
| `title` | ≤ 200 chars | Becomes the slug and the record heading. |
| `basis` | ≤ 1000 chars | Provenance, not a second essay. |
| `tags` | ≤ 8, each ≤ 32 chars, `^[a-z0-9][a-z0-9-]*$` | Bounds the `header` string in `index_record` (`semantic.py:396-400`). |
| Callsign | `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` | It becomes a **directory name**. A `/` would nest it out of `check_notebook_similarity`'s flat glob and out of `check_cross_agent_convergence`'s one-level `iterdir`. `_safe_path` blocks traversal but not nesting. Fail closed. |
| Path | `_safe_path` via `write_notebook` (`:293`) | Traversal. |

**Rate-limiter shape:** per-author `deque[float]` of monotonic timestamps on the tool instance (the registry holds one instance), pruned on each call, hard-capped in length so a flood cannot grow it without bound. Over-limit ⇒ framed `output=` with `metadata={"published": False, "reason": "rate_limited"}` and **no write** — not an `error=`, because an `error` can drive a retry loop, and a retry loop is exactly what the limiter exists to absorb.

**Do NOT wire `RecordsConfig.max_episodes_per_hour`.** It is **dead at HEAD** — zero readers in `src/` (grepped; the only live constant is `EpisodicMemory.MAX_EPISODES_PER_HOUR = 20` at `episodic.py:1183`, which throttles Tier 1 episodes and is unrelated). Issue #1061 lists it as the rate-limit mechanism; that is incorrect. Re-animating an episode-named dead field would change behaviour for a future reader who correctly assumes it is dead. AD-1140 adds its own tool-scoped budget so the flag and its bounds live in one place, which is also what the AD-1143 ablation surface needs.

### DD-8 — Sovereignty: no episodic read, no episodic write

`publish_finding` receives the `RecordsStore` and nothing else that touches memory. It must not import, reference, or reach `EpisodicMemory`, `MemoryAccessPolicy`, or any Tier 1 surface. Σ is the commons; **A** — the sovereign per-agent shard — is a different Nooplex letter and is untouched.

Enforce structurally: constructor-inject only `records_store`, a callsign resolver, the bounds, and `source_node`. Assert in a test that the module's import set contains no episodic symbol, and that a publish against a recording episodic double produces **zero** calls.

### DD-9 — Curation interaction: what a flood of published claims does

Stated honestly, because AD-1141 will multiply the volume and someone will need this later:

| Surface | Effect of N published claims |
|---|---|
| **AD-550 dedup** (`check_notebook_similarity`) | Layer 3 reads up to 20 recent files **per publish**. Cost is O(20) file reads per call — bounded. Correctness degrades past 20 recent entries in the window (DD-6). |
| **AD-554 convergence** (`check_cross_agent_convergence`) | **The expensive one.** It reads *every* recent `.md` under `notebooks/*/` on each anchor write. More publishers ⇒ more directories ⇒ more reads. And agents publishing similar claims is exactly the shape that triggers `CONVERGENCE_DETECTED`, a convergence report write, and a bridge alert (`proactive.py:3076-3110`, `bridge_alerts.py:467`). **AD-1140 does NOT call it** — `publish_finding` calls only the AD-550 gate. Wiring convergence detection into the publish path is an AD-1141 decision, and it should be taken deliberately with the alert-volume consequence understood. |
| **AD-555 quality** (`notebook_quality.py:217`) | Aggregates `list_entries("notebooks")`. More entries move the ship-wide quality score; low-value claims drag it toward the `notebook_quality_low_threshold = 0.3` bridge ALERT. This is arguably correct behaviour — a polluted commons *should* score worse. AD-1140 records `dedup_write` / `dedup_suppression` events on the quality engine when one is attached (mirroring `proactive.py:3062-3064`, `:2947-2949`) so the score reflects publications; degrade silently when it is absent. |
| **AD-551 dream consolidation** | Runs offline over the store, so it picks up claims with no wiring — and clusters/merges near-duplicates, which is a net positive. It will also archive non-primary entries into `_archived/`, which removes them from `RecordsStore.search` (`:846`) and therefore from Oracle Tier 2. **Consolidation can retire a published claim.** Correct, and worth stating so nobody reports it as a bug. |
| **`knowledge_linter`** (`lint_all`, gated on `config.lint.enabled` + `records_store`, `startup/dreaming.py:99-103`) | Lints more documents. No structural interaction. |

**Distinguishing tag.** Every published claim carries a reserved tag (e.g. `"finding"`) in addition to agent-supplied tags, so curation and later analysis can separate agent-published claims from proactive-loop notebook entries without parsing frontmatter. Counts against the 8-tag budget as a system tag, not an agent one.

### DD-10 — Default-OFF, byte-identical, registered in the ablation flag set

`agentic_tools.publish_finding_enabled: bool = False` on `AgenticToolsConfig` (`config.py:6036`), beside `oracle_query_enabled` (`:6057`). Off ⇒ startup registers nothing, `registry.get("publish_finding")` is `None`, the offer block is skipped, and `tool_ids` is byte-identical to today.

**Add the dotted path to BOTH dicts in `tests/ablation/sigma_flags.py`** — `SIGMA_OFF["agentic_tools.publish_finding_enabled"] = False` and `SIGMA_ON[...] = True`. The module docstring names AD-1140 as one of exactly two ADs that extend it. Two structural guards in `tests/ablation/test_sigma_harness_structural.py` enforce this: `set(SIGMA_ON) == set(SIGMA_OFF)`, and every dotted path resolves on a live `SystemConfig()` to a `bool`. **Missing the flag turns the ablation's treatment arm into a second control arm** — a silent measurement failure, not a loud one.

Also update the verified-line comment block at `sigma_flags.py:27-33` with the new `config.py` line number.

---

## Build

1. **NEW `src/probos/tools/publish_finding_tool.py`** — `PublishFindingTool`, structural Tool-protocol conformance (no inheritance), `tool_id="publish_finding"`, `ToolType.INFRA_SERVICE`. Mirror `src/probos/tools/oracle_query_tool.py` for module layout, `_ALLOWED_KEYS` validation, `_invalid(code, started)` error helper, bounded output, and the `type(x) is str` strictness style. Constructor: `PublishFindingTool(*, records_store, callsign_resolver, source_node, max_per_hour, max_content_chars, quality_engine=None)`.
2. **`src/probos/knowledge/records_store.py`** — additive keyword-only `extra_frontmatter: dict[str, Any] | None = None` on `write_entry` (`:91`) and pass-through on `write_notebook` (`:283`). Merged into the frontmatter dict **before** `yaml.dump`, and **raising `ValueError`** on any key in the reserved set `{author, classification, status, created, updated, revision, department, topic, tags, metrics}`. Fail-fast tier: silently dropping a reserved key would let a caller believe it stamped provenance that is not there. `None` (the default) ⇒ byte-identical.
3. **Registration** in `src/probos/startup/communication.py` — `_register_publish_finding_tool(...)` mirroring `_register_oracle_query_tool` (`:78-121`): same six `allowed_departments`, `default_permissions` `{"ensign": "write", "lieutenant": "write", "commander": "write", "senior_officer": "write"}`, `provider="records"`, tags `["publish_finding", "records", "knowledge", "write"]`. Called from `init_communication` beside the AD-1139 call (`:585-589`). `init_communication` gains a `records_store` parameter; `runtime.py` passes `self._records_store` at the `init_communication(...)` call (`:2766-2782`) — verified available, it is assigned at `:2498`, well before.
4. **Offer** in `src/probos/cognitive/agentic_dispatch.py` — add `"publish_finding"` to `_GATED_TOOL_IDS` (`:79`); add a `publish_ids` block beside `oracle_ids` (`:906-919`) using `registry.check_permission(agent_id, "publish_finding", ToolPermission.WRITE, agent_department=department, agent_rank=rank)`; add `*publish_ids` to the `tool_ids` dedup list (`:921-926`).
5. **Config** — three fields on `AgenticToolsConfig` (`config.py:6036`): `publish_finding_enabled: bool = False`, `publish_finding_max_per_hour: int = Field(default=12, ge=1, le=100)`, `publish_finding_max_content_chars: int = Field(default=4000, ge=200, le=20000)`. Extend the class docstring the way AD-1139 did.
6. **Ablation flags** — `tests/ablation/sigma_flags.py`, both dicts plus the verified-line comment.
7. **Tests** — `tests/test_ad1140_publish_finding.py` (NEW), ≈28 tests.

---

## Acceptance

**Headline — this is what makes it Σ rather than Ω. It must be a real round trip.**

> Agent **A** (department *science*) publishes a finding. A **new** `SemanticKnowledgeLayer` and a **new** `OracleService` are constructed over the same on-disk paths — standing in for a later session. Agent **B** (department *engineering*, a different callsign) invokes `oracle_query` and receives the claim text, carrying `_ORACLE_DISPOSITION` and a `[source:records confidence:… age:…]` provenance marker.

Run it **twice**: once with `records.semantic_index_enabled=True` (semantic path, real ChromaDB — `tests/test_ad1138_records_semantic_index.py` proves this is feasible in-suite) and once with it `False` (keyword path). Both must round-trip. The keyword variant is the one that proves the capability is not contingent on Chroma being healthy.

**Envelope (DD-3):**
- `read_entry` returns frontmatter containing every system-owned field with the expected values, and a body equal to the claim text — a lossless round trip through `yaml.dump`/`yaml.safe_load`.
- `claim_id` is stable for identical `{title, claim, basis}` and differs when any of the three changes.
- A param dict containing `author`, `claim_id`, `source_node`, `session_id`, `created`, or `revision` is **rejected** with `error="publish_finding_invalid:parameter"` and **nothing is written** (assert the notebooks dir is unchanged).
- `department` in the written frontmatter comes from `context`, and a `department` supplied in params is rejected by the same guard.

**Scope (DD-4):**
- `classification="fleet"` ⇒ written frontmatter has `classification: ship` **and** `requested_scope: fleet`; the claim **is** retrievable through `oracle_query`.
- `classification` in `{private, department, ship}` ⇒ `requested_scope == classification`.
- An unknown classification ⇒ `error="publish_finding_invalid:classification"`, nothing written.
- **A regression guard proving the hole is real:** a record written directly with `classification="fleet"` is **absent** from `RecordsStore.search(q, scope="ship")` and absent from `build_records_scope_filter("ship")`'s permitted list. This test documents *why* DD-4 exists; if a future BF-678 fixes the store, this test goes red and forces the DD to be revisited.
- No module under `src/probos/federation/` is imported or invoked.

**Idempotency (DD-6):**
- Publishing byte-identical content twice ⇒ second call returns the duplicate confirmation, `metadata["published"] is False`, and **exactly one** file exists.
- Near-identical content (Jaccard ≥ threshold, different `claim_id`) ⇒ suppressed by Layer 3.
- Genuinely different content ⇒ two files.
- `check_notebook_similarity` raising ⇒ the write proceeds (degrade-to-write), with a contextual warning.

**Bounds (DD-7):**
- The 13th publish in an hour is refused, framed, with no write; the counter is per-author (a second author is unaffected).
- Over-length `claim`, `title`, `basis`, a 9th tag, a malformed tag, and `confidence` outside `[0,1]` each ⇒ `error="publish_finding_invalid:<field>"`, nothing written.
- A callsign resolving to `""`, to `a/b`, or to `..` ⇒ refused, nothing written.
- The rate-limiter deque does not grow without bound under a burst.

**Sovereignty (DD-8):**
- A publish against a recording episodic double produces **zero** `store` / `recall` / `recall_for_agent_scored` calls.
- `publish_finding_tool.py` imports no episodic symbol (assert over the module's resolved imports, not a text grep of the source).

**Framing (DD-2):**
- Every module-level authored string, and every rendered `ToolResult.output` across success / duplicate / rate-limited / fleet / refusal, is clean under the **real imported** `_CAPABILITY_GAP_RE`.
- The success output carries the disposition framing.

**Governance (DD-1):**
- Registered with all six departments and `write` at every rank; an agent in an unlisted department does not receive the tool (silent, no error).
- `"publish_finding" in _GATED_TOOL_IDS`, and a raw Captain grant for an out-of-department agent does **not** surface the tool.
- Real `ToolRegistry` + real `ToolPermissionStore` throughout, per BF-287 — no mock at the registry boundary, because the department + rank gate is exactly what a mock would paper over. Follow `tests/test_ad1139_oracle_query_tool.py`'s fixture shape.

**Indexing (DD-5):**
- With a semantic indexer attached, one publish produces one `sk_records` upsert whose metadata carries `classification`, `author`, `department`, and a `frontmatter_json` that decodes to the full envelope.

**Default-OFF (DD-10):**
- Flag `False` ⇒ `registry.get("publish_finding") is None` and `WorkItemAgenticExecutor.run`'s `tool_ids` is byte-identical to today.
- `write_entry(..., extra_frontmatter=None)` produces byte-identical output to today — assert against a literal recomputation, not a golden file.
- `set(SIGMA_ON) == set(SIGMA_OFF)` and every path resolves to a `bool` (the existing structural guards cover this; run them).

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Validation plan — targeted only

**The full suite takes ~21 minutes and must NOT be run.**

- **Focused:** `tests/test_ad1140_publish_finding.py -q -n 0`
- **Adjacent, ONCE, after the focused gate is green:**
  `tests/test_ad1139_oracle_query_tool.py tests/test_ad1138_records_semantic_index.py tests/test_records_store.py tests/test_ad550_notebook_dedup.py tests/test_ad552_notebook_self_repetition.py tests/test_ad555_notebook_quality.py tests/test_ad722d_records_auto_write.py tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad1129_eventlog_query_tool.py -q -n 0`
- **Ablation guard, ONCE:** `tests/ablation/test_sigma_harness_structural.py -q -n 0`

Why these exactly (each path grepped and confirmed to exist):

| Suite | What it pins |
|---|---|
| `test_ad1139_oracle_query_tool.py` | The read half of the round trip, `_GATED_TOOL_IDS`, and the `tool_ids` assembly this AD extends. |
| `test_ad1138_records_semantic_index.py` | `index_record`, `build_records_scope_filter`, and the real-ChromaDB fixture the headline test reuses. |
| `test_records_store.py` | `write_entry` / `write_notebook` / `read_entry` / `search` — the surface step 2 modifies. |
| `test_ad550_notebook_dedup.py` | `check_notebook_similarity`'s three layers, which DD-6 depends on unchanged. |
| `test_ad552/ad555` | The frontmatter fields (`revision`, `created`, `metrics`) that `extra_frontmatter` must not collide with. |
| `test_ad722d_records_auto_write.py` | An existing automated writer into the same store. |
| `test_bf675_oracle_tier5_sovereignty.py` | The sovereignty boundary DD-8 must not move. |
| `test_ad1129_eventlog_query_tool.py` | The `_GATED_TOOL_IDS` / governed-registration pattern being extended. |
| `ablation/test_sigma_harness_structural.py` | The two `sigma_flags.py` guards. |

If `test_ad550_notebook_dedup.py` or `test_records_store.py` goes red, **stop and surface it** — a red there means step 2 changed existing write behaviour, which DD-10 forbids.

---

## Do NOT build here

❌ **Wiring the crew loop to publish automatically — that is AD-1141 (#1062).** This AD ships the verb and its governance; nothing calls it from `crew_executor.py`. ❌ Crew-child compaction (AD-1142, #1063). ❌ The ablation harness (AD-1143 — **shipped**; only its flag dict is touched). ❌ Any change to `_CLASSIFICATION_LEVELS` or the classification model. ❌ Any change to `_RECORDS_QUERY_SCOPE` or Oracle Tier 2 retrieval semantics. ❌ Fixing the `search` / `read_entry` `fleet` disagreement (DD-4 — note it, do not fix it). ❌ Federation transport, routing, or any import from `src/probos/federation/`. ❌ Anything touching the episodic shard, `MemoryAccessPolicy`, or `OWN_SHARD_PLUS_PUBLIC`. ❌ A sixth kind on `Oracle.write_semantic`. ❌ Calling `check_cross_agent_convergence` from the publish path (DD-9 — an AD-1141 decision). ❌ Signing the claim (deferred past AD-1144, #1069). ❌ A Captain approval workflow for publications. ❌ Wiring `RecordsConfig.max_episodes_per_hour`. ❌ Editing `config/system.yaml` (skip-worktree `S`, Captain-local). ❌ Changing the 14-key `crew_execution` evidence set (`crew_executor.py:622`) or adding a `SubtaskResult` field (`crew_finalizer.py:1909`) — epic DD-6; publications live in Ship's Records only. ❌ A new AD or BF number.

---

## Files (verify each at build)

- `src/probos/tools/publish_finding_tool.py` (NEW).
- `src/probos/knowledge/records_store.py` — `write_entry` + `write_notebook`, additive `extra_frontmatter` only.
- `src/probos/startup/communication.py` — `_register_publish_finding_tool` + the `init_communication` signature.
- `src/probos/runtime.py` — pass `records_store=self._records_store` into `init_communication`.
- `src/probos/cognitive/agentic_dispatch.py` — `_GATED_TOOL_IDS` + the offer block.
- `src/probos/config.py` — three `AgenticToolsConfig` fields.
- `tests/ablation/sigma_flags.py` — both dicts + the comment block.
- `tests/test_ad1140_publish_finding.py` (NEW).

---

## Builder checks (unverifiable from the spec — confirm before relying on them)

1. **Does `context` reach `Tool.invoke` with `department`, `_crew_session_id`, and `_crew_work_item_id`?** `_AGENTIC_EXTRA_CONTEXT_KEYS` (`agentic_dispatch.py:59-68`) lists them, and `oracle_query_tool.py:230-232` reads only `agent_id` — so the wider set is **unproven at the tool boundary**. If `department` is absent, resolve it the way `_resolve_agentic_identity` does (`agentic_dispatch.py:120-126`) rather than accepting it from params. If session/work-item ids are absent, write `""` and say so in the envelope docstring — do **not** fabricate linkage.
2. **Callsign resolution.** `write_notebook` wants a **callsign**, not a slot `agent_id`. `proactive.py:2905` uses `getattr(agent, 'callsign', '') or agent.agent_type`. Wire a resolver from the `AgentRegistry` already passed to `init_communication`; do not reach through `runtime`.
3. **`RecordsStore` test fixture cost.** `initialize()` runs `git init` unconditionally when `.git` is absent (`:76-88`). Match whatever `tests/test_records_store.py` already does; if it sets `auto_commit=False`, follow it so the suite stays fast.
4. **`source_node`.** `index_record` accepts `source_node` (`semantic.py:368`) but `write_entry`'s indexing call does **not** pass it (`:164-173`), so it is `""` for every record today. Put the instance id in the *envelope frontmatter*; do not widen the indexing call in this AD.
5. **Quality-engine handle.** `proactive.py` reaches it as `getattr(self._runtime, '_notebook_quality_engine', None)`. Constructor-inject it into the tool instead (DIP); wire it at registration if it exists at that point in startup, and degrade silently to `None` if it does not.

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` · `DECISIONS.md`.

The AD-1140 entry must record: the DD-4 `fleet` correction and **why** (Tier 2 excludes `fleet`, so a faithful write is a black hole); that `half_life_days` is a **reserved, unconsumed** slot and AD-873 is an episodic reranker rather than a records decay; that `RecordsConfig.max_episodes_per_hour` is dead and deliberately left dead; and the `search` / `read_entry` `fleet` disagreement as an open observation (BF-678 if filed).

---

## Done-when

Both headline round trips green (semantic **and** keyword, across freshly constructed service objects); envelope round-trip lossless; anti-spoof rejection proven with no write; `fleet` dual-stamp proven **and** the Tier 2 exclusion pinned by a regression guard; dedup suppression proven on both the exact and cross-topic layers; every bound in DD-7 proven with nothing written; sovereignty proven by zero episodic calls; every authored string clean under the real `_CAPABILITY_GAP_RE`; department gate + `_GATED_TOOL_IDS` proven against a real registry; default-OFF byte-identity proven for both `tool_ids` and `write_entry`; `sigma_flags.py` carrying the new path with both structural guards green; focused + adjacent + ablation gates green; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-25, HEAD `5f1f5ece`)

```
src/probos/knowledge/records_store.py
   15: _SUBDIRS = (                                  # "notebooks" present; no "claims"
   28: _CLASSIFICATION_LEVELS = {                    # private:0 department:1 ship:2 fleet:3
   91:     async def write_entry(                     # no extra-frontmatter param today
  111:         if classification not in _CLASSIFICATION_LEVELS:
  114:         now = datetime.now(timezone.utc).isoformat()
  160:         # AD-1138: keep the semantic index current  <-- indexing lives INSIDE write_entry
  165:             await self._semantic_indexer.index_record(
  283:     async def write_notebook(
  290:         classification: str = "department",     # epic DD-4 overrides to "ship"
  293:         self._safe_path(path)
  381:     async def check_notebook_similarity(
  419:         exact_path = f"notebooks/{callsign}/{topic_slug}.md"    # Layer 2
  483:         # --- Layer 3: Cross-topic scan ---
  484:         notebook_dir = self._repo_path / "notebooks" / callsign
  530:     async def check_cross_agent_convergence(
  569:         notebooks_dir = self._repo_path / "notebooks"
  735:     async def read_entry(
  764:             # ship and fleet are readable by all crew        <-- disagrees with :878
  854:     async def search(self, query: str, scope: str = "ship") -> list[dict]:
  878:                 if _CLASSIFICATION_LEVELS.get(doc_class, 0) > _CLASSIFICATION_LEVELS.get(scope, 2):
  989:     def _safe_path(self, user_path: str) -> Path:

src/probos/cognitive/oracle_service.py
   67: _RECORDS_QUERY_SCOPE = "ship"                  # module constant; fleet is level 3
  292:     async def write_semantic(self, kind, /, **fields)   # 5 kinds, none fit a finding
  726:     async def _query_records(self, query_text, *, k)
  761:         raw = await self._records_store.search(query_text, scope=_RECORDS_QUERY_SCOPE)
  794:             records_scope=_RECORDS_QUERY_SCOPE,

src/probos/knowledge/semantic.py
   25: _RECORD_DOC_CHARS = 4000                       # justifies max_content_chars = 4000
   42: def build_records_scope_filter(
   82:     permitted = [label for label, level in _CLASSIFICATION_LEVELS.items() if level <= scope_level]
  135:     COLLECTIONS = {  ... "records": "sk_records" }
  357:     async def index_record(
  368:         source_node: str = "",                 # never populated by write_entry today
  440:     async def search( ... include_episodes=True, records_scope=None )

src/probos/tools/oracle_query_tool.py
   57: SIGMA_TIERS: tuple[str, ...] = (...)
   79: _ALLOWED_KEYS = frozenset({"query", "kind"})   # the anti-spoof pattern to mirror
   87: _ORACLE_DISPOSITION: str = "(These entries come from ..."
  230:         if type(context) is dict and type(context.get("agent_id")) is str:
  239:         if any(type(key) is not str or key not in _ALLOWED_KEYS for key in raw):

src/probos/cognitive/agentic_dispatch.py
   59: _AGENTIC_EXTRA_CONTEXT_KEYS = frozenset({ "agent_id", "department", "rank", ... })
   79: _GATED_TOOL_IDS = frozenset({"event_log_query", "oracle_query"})
  120:         resolved_department = ontology.get_agent_department(agent_type)
  356:     - ``CONSENSUS`` -> routed through ``consensus_invoke``   # MCP tools ONLY
  733:             granted_ids = [ ... if not g.is_restriction and g.tool_id not in _GATED_TOOL_IDS ]
  906:         oracle_ids: list[str] = []
  912:             if registry.check_permission(agent_id, "oracle_query", ToolPermission.READ, ...)
  923:                 *granted_ids, *mesh_ids, ... *event_log_ids, *oracle_ids,

src/probos/startup/communication.py
   78: def _register_oracle_query_tool(                # the shape to mirror
  585:     _register_oracle_query_tool(tool_registry=..., enabled=..., oracle=oracle)

src/probos/runtime.py
 2498:         self._records_store = cog.records_store        # BEFORE communication
 2764:         from probos.startup.communication import init_communication
 2782:             oracle=self.oracle,                        # AD-1139

src/probos/config.py
 3362: class RecordsConfig(BaseModel):
 3369:     max_episodes_per_hour: int = 20  # Rate limit for notebook writes   <-- DEAD
 3400:     semantic_index_enabled: bool = False           # AD-1138
 5835:     default_classification: Literal["ship", ...] = "ship"   # CreativeExpression
 6036: class AgenticToolsConfig(BaseModel):  # AD-1072
 6057:     oracle_query_enabled: bool = False             # AD-1139

src/probos/cognitive/decomposer.py
   33: _CAPABILITY_GAP_RE = re.compile(               # includes bare `lack(?:s|ing)?`

src/probos/tools/protocol.py
   29: class ToolPermission(str, Enum):               # NONE < OBSERVE < READ < WRITE < FULL

src/probos/knowledge/notebook_quality.py
  217:             entries = await records_store.list_entries("notebooks")

tests/ablation/sigma_flags.py
   27: #   config.py:3400  semantic_index_enabled ... / :6057 oracle_query_enabled
   34: SIGMA_OFF: dict[str, Any] = { 2 keys }
   39: SIGMA_ON:  dict[str, Any] = { 2 keys }
```

**Negative greps (claims that depend on an absence):**

```
rg "max_episodes_per_hour" src/            -> config.py:3369 (decl) ; episodic.py:1183,2473
                                              (EpisodicMemory.MAX_EPISODES_PER_HOUR, unrelated)
                                              ZERO readers of the RecordsConfig field.
rg "write_notebook" src/                   -> records_store.py:283 (def)
                                              proactive.py:3047, :4076 ; routers/records.py:106
                                              -> no agent-reachable call site.
rg "check_notebook_similarity" src/        -> records_store.py:381 (def) ; proactive.py:2926, :4049
                                              -> the CALLER gates, not write_notebook.
rg "AD-873" src/                           -> no hit in src/ ; only decision/roadmap prose,
                                              where it is _composite_recall_score (episodic).
                                              No records-level decay exists.
```
