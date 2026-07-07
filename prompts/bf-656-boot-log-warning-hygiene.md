# BF-656: boot-log hygiene — eliminate two benign-but-recurring WARNINGs that fire on every boot for permanent/deterministic conditions

**One-line:** Two WARNINGs fire on *every* boot for conditions that are permanent (not transient), so they are pure log noise that trains operators to ignore warnings. **(A)** the AD-423a ontology seed registers a no-op `codebase_query` placeholder that the real AD-544 native `CodebaseQueryTool` then legitimately replaces → one `probos.tools.registry — Replacing existing tool registration: codebase_query` every boot; **(B)** two stale 6/22 test-artifact skills (`new_capability`, `test_skill`) have no `handle_<name>` function so warm boot can *never* restore them → one `probos.warm_boot — Warm boot: no handler function for skill …` per skill, forever. Fix each at its root: **(A)** remove the graduated `codebase_query` entry from the ontology taxonomy (the real tool supersedes it); **(B)** prune a *definitively* un-restorable skill from the knowledge store on the no-handler branch only.

**Status:** Ready to build
**Type:** BF (bug fix) — assign **BF-656** (verified next free; highest shipped is **BF-655**; `git grep "BF-656"`/`"BF-657"` empty. Do NOT mint a new AD — one shared backend BF sequence.)
**Keep as ONE BF-656 (two well-separated parts), do NOT split into BF-657.** Rationale: both are "boot-log hygiene," each is a ~2–8 line surgical fix in a *disjoint* subsystem, GitHub issue **#1019** is already titled BF-656 covering *both* warnings, and splitting would fragment the tracker + require a second issue. The spec keeps **Part A** (ontology/tool-registry) and **Part B** (warm-boot/knowledge-store) fully independent with separate edits and test classes, so the Builder MAY land them as two commits under the one BF if cleaner.
**GitHub issue:** seangalliher/ProbOS#1019
**Branch:** `main` (HEAD `4e0bb1cd`)
**Dependencies:** none (aligns AD-423a taxonomy seed with the AD-544 native tools; adds a `KnowledgeStore.remove_skill` mirroring `remove_agent`)
**Estimated tests:** ~7 new (one new file `tests/test_bf656_boot_log_hygiene.py`) + 1 obsolete-contract assertion updated in `tests/test_ontology_ops_comms_resources.py`
**Target files:**
- `config/ontology/resources.yaml` (Part A — remove the `codebase_query` `tool_capabilities` entry; add a one-line "graduated to AD-544 native tool" note) — **tracked repo config, committable**
- `tests/test_ontology_ops_comms_resources.py` (Part A — one assertion `>= 7` → `>= 6`)
- `src/probos/knowledge/store.py` (Part B — add `remove_skill(intent_name)` mirroring `remove_agent`)
- `src/probos/warm_boot.py` (Part B — on the no-handler branch: prune + INFO log instead of WARNING)
- `tests/test_bf656_boot_log_hygiene.py` (new — Part A + Part B test classes)

> **Do NOT stage `config/system.yaml`** (Captain local). `config/ontology/resources.yaml` **is** a tracked repo file — confirmed committable. The two stale skill artifacts live under `data/knowledge/skills/` which is **gitignored** (`git check-ignore data/knowledge/skills/test_skill.py` returns the path) and the knowledge store is its **own** git repo (`data/knowledge/.git` exists) — the prune commits there, never the OSS tree.

---

## 1. Problem

Every `probos serve` boot emits these two WARNINGs, both for **permanent** conditions (not transient failures the operator can act on):

```
probos.tools.registry — Replacing existing tool registration: codebase_query
probos.warm_boot — Warm boot: no handler function for skill new_capability
probos.warm_boot — Warm boot: no handler function for skill test_skill
```

Neither indicates a real problem — the end state is correct in all three cases (the real `codebase_query` tool wins; the stale skills are correctly skipped). But because they recur on *every* boot for conditions that can never change on their own, they are noise that erodes the signal value of the WARNING level (per the ProbOS logging standard, a WARNING means "degraded operation — something failed but the system compensated"; a deterministic, self-corrected, permanent condition is not warning-worthy).

---

## 2. Root cause (verified against HEAD `4e0bb1cd` — exact cites)

### Part A — `Replacing existing tool registration: codebase_query`

Two boot steps register a tool with `tool_id="codebase_query"`, and `ToolRegistry.register` is last-write-wins with a WARNING on any pre-existing id:

1. **AD-423a ontology seed** ([src/probos/startup/communication.py](../src/probos/startup/communication.py#L454)):
   - [communication.py L454](../src/probos/startup/communication.py#L454): `# --- AD-423a: Seed tool registry from ontology tool capabilities ---`
   - [L459](../src/probos/startup/communication.py#L459): `for tc in ontology.get_tool_capabilities():` — loops the ontology tool capabilities and registers **each** as a **no-op** `DirectServiceAdapter` (`handler=_noop_handler`, [L469](../src/probos/startup/communication.py#L469); `_noop_handler` defined at [L29](../src/probos/startup/communication.py#L29)) via `tool_registry.register(adapter, provider=tc.provider, tags=[tc.id, tc.provider])` ([L475-478](../src/probos/startup/communication.py#L475)).
   - `get_tool_capabilities()` ([src/probos/ontology/service.py L272-275](../src/probos/ontology/service.py#L272)) returns **only** the `tool_capabilities` list from the loader — **not** `knowledge_sources`.
2. **AD-544 native SWE tools** ([src/probos/startup/finalize.py](../src/probos/startup/finalize.py#L1451)):
   - `_wire_native_swe_harness` ([finalize.py L1451](../src/probos/startup/finalize.py#L1451), called at [L4236](../src/probos/startup/finalize.py#L4236)) calls `register_native_swe_tools(registry, runtime)` ([L1482](../src/probos/startup/finalize.py#L1482)).
   - `register_native_swe_tools` ([src/probos/cognitive/swe_harness/tools.py L604](../src/probos/cognitive/swe_harness/tools.py#L604)) registers **12** native tools ([L629-641](../src/probos/cognitive/swe_harness/tools.py#L629)): `read_file, list_files, codebase_query, codebase_find_callers, codebase_find_tests, codebase_get_imports, codebase_read_source, standing_orders_lookup, system_self_model, write_file, edit_file, run_command`. `CodebaseQueryTool(runtime)` is registered with `read_perms` (`ensign→read`) ([L633, L646](../src/probos/cognitive/swe_harness/tools.py#L633)).

3. **The collision + warning** ([src/probos/tools/registry.py L92](../src/probos/tools/registry.py#L92)):
   - `ToolRegistry.register` ([L92](../src/probos/tools/registry.py#L92)) — `if tool.tool_id in self._tools:` ([L111](../src/probos/tools/registry.py#L111)) → `logger.warning("Replacing existing tool registration: %s", tool.tool_id)` ([L113](../src/probos/tools/registry.py#L113)), then last-write-wins.

**Why exactly one warning, only `codebase_query`:** the seeded ontology `tool_capabilities` are the **7** entries in [config/ontology/resources.yaml L49-90](../config/ontology/resources.yaml#L49): `codebase_query` (L50-54), `ward_room_post`, `ward_room_endorse`, `ward_room_reply`, `self_modification`, `knowledge_query`, `episodic_recall`. (The `episodic_memory`/`ship_records`/`knowledge_store` under [`knowledge_sources:` L92](../config/ontology/resources.yaml#L92) are a **separate** key and are **never** seeded — `get_tool_capabilities()` ignores them.) Intersecting those 7 ids with the 12 native SWE tool ids yields **exactly one**: `codebase_query`. So the real AD-544 tool correctly replaces the AD-423a no-op placeholder → one WARNING, and the end state (real tool wins, all crew keep `read` access) is fine. **Pure noise.**

**The taxonomy/registry tension (documented):** [resources.yaml L44-47](../config/ontology/resources.yaml#L44) header says *"Tool capabilities — conceptual taxonomy … not a runtime registry. AD-423 (Tool Registry) will implement the runtime version."* But the AD-423a seed **does** register these taxonomy entries as runtime tools. `codebase_query` is the one taxonomy entry that has since **graduated** to a real runtime tool (AD-544) — so the placeholder is now redundant *and* colliding.

### Part B — `Warm boot: no handler function for skill …`

- Warm-boot skill restore ([src/probos/warm_boot.py](../src/probos/warm_boot.py#L165)): the `restore()` method (class `WarmBootService`, [L17](../src/probos/warm_boot.py#L17); entrypoint `async def restore` [L49](../src/probos/warm_boot.py#L49)) step 4 ([L165](../src/probos/warm_boot.py#L165)):
  - [L167](../src/probos/warm_boot.py#L167): `skills = await ks.load_skills()`; gated on [L168](../src/probos/warm_boot.py#L168) `if skills and self._config.self_mod.enabled:` (so these warnings only fire when self-mod is enabled).
  - [L172](../src/probos/warm_boot.py#L172): `for intent_name, source_code, descriptor_dict in skills:` — compiles the source in a temp module, then `handler = getattr(module, f"handle_{intent_name}", None)`.
  - [L202](../src/probos/warm_boot.py#L202): `if handler is None: logger.warning("Warm boot: no handler function for skill %s", intent_name)` then `continue`. **This is the no-handler branch — a PERMANENT condition** (source parsed/exec'd fine, but there is no `handle_<name>` function; retrying every boot can never succeed).
  - [L224](../src/probos/warm_boot.py#L224): the **outer** `except Exception as e: logger.warning("Warm boot: skill %s restore failed: %s", intent_name, e)` — this catches **transient/recoverable** errors (a source that fails `exec_module`: SyntaxError, ImportError, top-level raise). The inner compile block ([L188-207](../src/probos/warm_boot.py#L188)) has only a `finally` (temp-file cleanup), **no `except`**, so an exec failure propagates to this outer handler. **This path must NOT prune** — the error may be environment-transient.

- **Confirmed artifacts** (live instance, `data/knowledge/skills/`): only two persisted skills exist, each a 12-byte `# test skill` stub with **no** `handle_<name>` function and a `created_at` monotonic value (`33071.062`) marking them as 6/22 test debris:
  - `new_capability.py` (12 B) + `new_capability.json`
  - `test_skill.py` (12 B) + `test_skill.json`
  A 12-byte comment source **exec's cleanly** → `getattr` returns `None` → the **no-handler** branch (L202) → they can NEVER restore → warn every boot forever.

- **Store patterns to mirror** ([src/probos/knowledge/store.py](../src/probos/knowledge/store.py)):
  - `_SUBDIRS` includes `"skills"` ([L28](../src/probos/knowledge/store.py#L28)); skills are file-backed at `{repo_path}/skills/{intent_name}.{py,json}`.
  - `store_skill` ([L223-229](../src/probos/knowledge/store.py#L223)) writes `.py`+`.json` then `_schedule_commit(f"Store skill {intent_name}")`.
  - `load_skills` ([L231-249](../src/probos/knowledge/store.py#L231)) globs `skills/*.json`, requires a matching `.py`.
  - `remove_agent` ([L211-217](../src/probos/knowledge/store.py#L211)) — the exact pattern to mirror: `py_path.unlink(missing_ok=True); json_path.unlink(missing_ok=True); await self._schedule_commit(f"Remove agent {agent_type}")`.
  - **`KnowledgeStore.remove_skill` does NOT exist** (`git grep "remove_skill" -- src` shows it only on `CognitiveAgent`/`SkillCatalog`/`SkillBasedAgent`, not `KnowledgeStore`). New method.

---

## 3. Fix design

### Part A — remove the graduated `codebase_query` taxonomy entry (chosen: candidate **(a) MINIMAL**)

**Edit A1 — `config/ontology/resources.yaml`.** Delete the `codebase_query` entry ([L50-54](../config/ontology/resources.yaml#L50)) from `tool_capabilities`. In its place add a single comment recording *why*, e.g.:

```yaml
tool_capabilities:
  # NOTE (BF-656): `codebase_query` removed here — it graduated to the real
  # AD-544 native CodebaseQueryTool (tool_id "codebase_query", registered by the
  # SWE harness at boot with ensign→read perms). Keeping the placeholder made the
  # AD-423a seed register a no-op adapter that the real tool then legitimately
  # replaced, emitting "Replacing existing tool registration: codebase_query"
  # every boot. The remaining entries have no native tool yet, so they stay.
  - id: ward_room_post
    ...
```

- **No production-code change for Part A.** The AD-423a seed loop ([communication.py L459](../src/probos/startup/communication.py#L459)) and `ToolRegistry.register` ([registry.py L92](../src/probos/tools/registry.py#L92)) are **untouched**: the seed now iterates 6 capabilities instead of 7, so there is simply no `codebase_query` placeholder to collide with. The `"tool-registry started (%d tools)"` count log ([communication.py](../src/probos/startup/communication.py)) shows one fewer seeded tool — harmless.
- **Access preserved:** the real `CodebaseQueryTool` (tool_id `codebase_query`, `read_perms` `ensign→read`) is still registered by `register_native_swe_tools` — verified `test_ad544_native_tools.py::test_codebase_query_tool_metadata` (L55-57) pins `t.tool_id == "codebase_query"` and L115 pins it in the native list. All crew keep read access.
- **The `ToolRegistry` replace-warning guard stays 100% intact** for genuine accidental duplicate registrations — nothing about the guard changes, so real dupes still warn (Part A test #A3 proves this).

**Edit A2 — `tests/test_ontology_ops_comms_resources.py` (obsolete-contract, one line).** `TestToolCapabilities::test_all_capabilities` asserts `len(tc) >= 7` ([L199](../tests/test_ontology_ops_comms_resources.py#L199)); with `codebase_query` removed there are 6 → change to `>= 6` (and update the inline comment/count). The sibling `test_filtered_capabilities` uses `>= 4`/`>= 2` and the partition invariant `len(all_crew)+len(lt_plus) == len(all)` — after removal: all_crew 5→4, lt_plus 2, `4+2 == 6` ✓ still holds; and `TestResourcesSchemaLoading::test_load_resources_yaml` asserts `> 0` ✓ still holds. **Only the one `>= 7` assertion is obsolete.**

**Why (a) over (b) [the "tag placeholders + downgrade the log to debug when replacing a known placeholder" option]:**
- **Behavior-preserving + root-cause:** the placeholder is genuinely redundant (the real tool exists), so removing it *fixes* the collision rather than *silencing* it. (b) preserves dead weight (a no-op adapter for a tool that already has a real implementation) and merely hides the log.
- **Guard integrity:** (a) leaves `ToolRegistry.register`'s replace-warning **entirely unchanged**, so the accidental-collision guard is 100% intact for all *other* ids. (b) adds an `is_placeholder`/provider-tag concept + a conditional log-level branch inside `register`, which risks masking a *future real* collision if the tag is ever misapplied.
- **Minimal + DRY + convention:** (a) = 1 config edit + 1 test-line edit, zero production code. (b) = new config/tag plumbing on the hot registration path + a new conditional. ProbOS convention favors the minimal, behavior-preserving change that keeps the safety guard intact.
- **Aligns the taxonomy with reality:** resources.yaml's own header calls it a "conceptual taxonomy … not a runtime registry." Removing the one entry that graduated to a real runtime tool resolves the taxonomy/seed tension; the remaining 6 (no native tool yet) legitimately stay as taxonomy + no-op seed.

### Part B — prune a definitively un-restorable skill (chosen: candidate **(a) PRUNE / self-cleaning**)

**Edit B1 — `src/probos/knowledge/store.py`: add `KnowledgeStore.remove_skill`** mirroring `remove_agent` ([L211-217](../src/probos/knowledge/store.py#L211)) exactly:

```python
async def remove_skill(self, intent_name: str) -> None:
    """Delete skill files and commit removal (mirrors remove_agent)."""
    py_path = self._repo_path / "skills" / f"{intent_name}.py"
    json_path = self._repo_path / "skills" / f"{intent_name}.json"
    py_path.unlink(missing_ok=True)
    json_path.unlink(missing_ok=True)
    await self._schedule_commit(f"Remove skill {intent_name}")
```
Place it in the "Skill persistence" block (right after `load_skills`, which ends ~[L249](../src/probos/knowledge/store.py#L249)). Full type annotation on the public surface; docstring notes the mirror.

**Edit B2 — `src/probos/warm_boot.py`: prune ONLY on the no-handler branch** ([L202](../src/probos/warm_boot.py#L202)). Replace the WARNING+`continue` with a self-cleaning prune + INFO log:

```python
if handler is None:
    # BF-656: a source that parses/exec's fine but has no handle_<name>
    # function can NEVER restore — a PERMANENT condition. Prune it from the
    # knowledge store so it stops being retried (and re-warned) every boot.
    # Do NOT prune on the transient exec-failure path (outer except below):
    # a SyntaxError/ImportError/top-level raise may be environment-recoverable.
    logger.info(
        "Warm boot: skill %s has no handle_%s function (permanent); "
        "pruning from knowledge store",
        intent_name, intent_name,
    )
    try:
        await ks.remove_skill(intent_name)
    except Exception as prune_err:  # log-and-degrade — never block boot on a prune
        logger.warning(
            "Warm boot: failed to prune un-restorable skill %s: %s",
            intent_name, prune_err,
        )
    continue
```
- **Surgical:** the change is confined to the existing `if handler is None:` branch. The outer `except` at [L224](../src/probos/warm_boot.py#L224) (transient exec failures) is **untouched** → those still log "restore failed" as a WARNING and are **never** pruned.
- The prune is wrapped in its own `try/except` (log-and-degrade tier): a prune failure must never abort the warm-boot restore loop.
- `time` is already imported ([L10](../src/probos/warm_boot.py#L10)); no new imports.

**Why (a) over (b) [downgrade the no-handler WARNING→DEBUG, leave artifacts]:**
- **Root-cause vs symptom:** (a) removes the dead artifacts so the condition *stops existing* — the warning never recurs because there is nothing left to retry. (b) leaves `new_capability`/`test_skill` on disk to be re-loaded and re-skipped on every boot forever, and they re-surface the instant an operator sets log level to DEBUG for diagnostics.
- **Safety of the boot-time data mutation** (the only argument for (b)): the prune is safe because — (1) it triggers **only** on the permanent no-handler condition, **never** on transient exec errors (Part B test #B4 proves a `SyntaxError`/`ImportError` skill is NOT pruned); (2) it mutates only **gitignored runtime state** under `data/knowledge/` (verified `git check-ignore`), never the OSS tracked tree; (3) it commits to the knowledge store's **own** git repo (`data/knowledge/.git` exists) via the existing `_schedule_commit` — warm-boot restore is already a boot-time data operation, so a prune-commit is in-band; (4) it mirrors the trusted, existing `remove_agent` pattern (DRY); (5) it is wrapped in log-and-degrade so a prune failure can't block boot.
- **Convention:** ProbOS favors self-healing (dreaming consolidation, self-mod pruning). A self-cleaning store is the durable fix; the INFO prune log replaces the old WARNING with a one-time, actionable "pruned X" record.

---

## 4. What this does NOT change (boundaries)

- **Do NOT** modify `ToolRegistry.register` ([registry.py L92-137](../src/probos/tools/registry.py#L92)) — the replace-warning guard stays intact for real accidental dupes. (Part A is config + one test line only.)
- **Do NOT** modify the AD-423a seed loop in `communication.py` ([L454-478](../src/probos/startup/communication.py#L454)) or `_noop_handler` — removing the yaml entry is sufficient.
- **Do NOT** touch the AD-544 native SWE tools (`swe_harness/tools.py`, `finalize.py` wiring) — the real `codebase_query` tool and its perms are unchanged.
- **Do NOT** remove or alter any **other** `tool_capabilities` entry (`ward_room_*`, `self_modification`, `knowledge_query`, `episodic_recall`) or **any** `knowledge_sources` entry — they have no native tool yet and legitimately stay.
- **Do NOT** change the warm-boot transient `except` at [L224](../src/probos/warm_boot.py#L224), the skill compile logic ([L188-207](../src/probos/warm_boot.py#L188)), the `self_mod.enabled` gate ([L168](../src/probos/warm_boot.py#L168)), or any other restore step (trust/routing/agents/episodes/workflows/QA).
- **Do NOT** prune on any path other than `handler is None`. A transient exec failure must be retried on a future boot.
- **Do NOT** stage `config/system.yaml`. **Do NOT** commit the `data/knowledge/skills/*` artifacts (gitignored) — the running instance's prune removes them from the knowledge repo at next boot; no OSS-tree change.
- **Do NOT** touch `DECISIONS.md` (BF, not an AD). No emoji; logs only.

---

## 5. Existing tests — keep green; obsolete-contract audit

| Test file | Exercises | Effect of this fix |
|---|---|---|
| `tests/test_ontology_ops_comms_resources.py` | `TestToolCapabilities::test_all_capabilities` asserts `len(tc) >= 7`; `test_filtered_capabilities` asserts `>= 4`/`>= 2` + partition invariant | **`>= 7` is OBSOLETE** → update to `>= 6` (Edit A2). Filtered + partition assertions **stay green** (all_crew 5→4 `>=4` ✓; `4+2==6` ✓). `test_load_resources_yaml` (`> 0`) green. |
| `tests/test_ad544_native_tools.py` | `test_codebase_query_tool_metadata` (L55-57) pins native `tool_id=="codebase_query"`; L115 pins it in the 12-tool list | **Green** — the real tool is untouched (this is the access-preservation guarantee). |
| `tests/test_ad423a_tool_foundation.py` | `ToolPreference(tool_id="codebase_query")` (L151-152, 430, 440) — the preference dataclass, NOT the ontology taxonomy | **Green** — unrelated to resources.yaml. |
| `tests/test_ad885_acm_unified_lens.py` | registers a `_StubTool("codebase_query")` into the registry (L211/284) | **Green** — uses a stub, not the ontology seed. |
| `tests/test_copilot_adapter.py` | `_handle_codebase_query` adapter method | **Green** — unrelated. |
| `routers/ontology.py::get_ontology_resources` (`/api/ontology/resources`, L213) | serializes `get_tool_capabilities()` | Response now lists 6 tool_capabilities (was 7). **No test asserts `codebase_query` is present in this response** (grep confirms). If the Builder finds a UI/API test pinning `codebase_query` in the ontology resources payload, repoint it — none found. |
| (Part B) no `test_warm_boot.py` exists | — | No test seeds a no-handler skill or asserts the "no handler function" WARNING → **no obsolete contract for Part B.** `test_bf656_boot_log_hygiene.py` is the first coverage of the prune path. |

**No test asserts the ontology exposes `codebase_query`, and no test asserts the no-handler WARNING fires.** The only obsolete assertion is the single `>= 7` count.

---

## 6. Test plan

New file `tests/test_bf656_boot_log_hygiene.py`, two classes.

### Part A — `class TestCodebaseQueryNoBootWarning`

1. **`test_ontology_no_longer_exposes_codebase_query`** — load the ontology against `config/ontology/resources.yaml` (mirror the `service` fixture in `test_ontology_ops_comms_resources.py`); assert **no** `ToolCapability` has `id == "codebase_query"`, and `len(get_tool_capabilities()) == 6`. (Positive contract: the collision source is gone.)
2. **`test_native_codebase_query_tool_preserves_access`** — assert `CodebaseQueryTool(<stub runtime>).tool_id == "codebase_query"` (access preserved; the real tool still owns the id). May reuse the `test_ad544_native_tools.py` construction pattern.
3. **`test_registry_replace_guard_still_warns_for_real_dupes`** (GUARD PRESERVED) — with `caplog` at WARNING: build a `ToolRegistry`; register a `_StubTool("dupe_id")` twice; assert `"Replacing existing tool registration: dupe_id"` **is** logged. Proves fix (a) leaves the accidental-collision guard fully intact.
4. **`test_seeding_ontology_then_registering_codebase_query_does_not_warn`** (HEADLINE / warning-no-longer-fires) — with `caplog` at WARNING: build a `ToolRegistry`; seed it from `get_tool_capabilities()` exactly as the AD-423a loop does (a `DirectServiceAdapter(tool_id=tc.id, handler=_noop_handler, …)` per capability); then register a real-tool stand-in `_StubTool("codebase_query")` (mirrors AD-544 registering the native tool); assert **NO** `"Replacing existing tool registration: codebase_query"` appears in `caplog`. **Pre-fix this WOULD warn** (codebase_query was seeded) — this is the direct regression guard.

### Part B — `class TestUnrestorableSkillPruned`

5. **`test_remove_skill_deletes_files_and_commits`** — construct a real `KnowledgeStore` on `tmp_path` (mirror the fixture in the existing knowledge-store tests), `await store_skill("gone", "# x\n", {...})`, assert both `skills/gone.py` + `.json` exist; `await remove_skill("gone")`; assert **both** files are deleted. (Unit test for the new method.)
6. **`test_no_handler_skill_is_pruned_and_not_re_warned`** (HEADLINE) — construct a `WarmBootService` (class at [warm_boot.py L17](../src/probos/warm_boot.py#L17); keyword-only deps) with a **real** `KnowledgeStore` on `tmp_path` and minimal fakes for the other deps (`trust_network`/`hebbian_router` fakes whose `load_*` return empty; `episodic_memory=None`; `workflow_cache=None`; `config` = real `SystemConfig` with `self_mod.enabled=True`; `add_skill_to_agents_fn` = recording `AsyncMock`; `register_designed_agent_fn`/`create_designed_pool_fn` = fakes; `qa_reports={}`; `pools={}`). Seed the store via `store_skill` with a **no-handler** skill `nohandler` (source `"# no handler\n"`). `await service.restore()`. Assert: `skills/nohandler.py`+`.json` are **gone**; `caplog` contains the INFO "pruning" line for `nohandler`; `caplog` does **NOT** contain `"no handler function"` (old WARNING removed).
7. **`test_valid_skill_restores_and_is_not_pruned`** — same harness, seed `valid_skill` (source `"def handle_valid_skill(**k):\n    return 'ok'\n"`). `await service.restore()`. Assert: `add_skill_to_agents_fn` was awaited with a `Skill` named `valid_skill`; the files **remain** (not pruned); no prune log for it.
8. **`test_transient_exec_error_skill_is_not_pruned`** (SAFETY — transient must survive) — same harness, seed `broken_skill` (source `"import definitely_not_a_real_module_bf656\n"` → raises `ModuleNotFoundError` in `exec_module` → hits the **outer** `except`). `await service.restore()`. Assert: the files **remain** (NOT pruned); `caplog` contains the `"skill broken_skill restore failed"` WARNING; `remove_skill` was **not** invoked for it. Proves the prune is scoped to the permanent no-handler case only.

> Tests 6–8 may share one parametrized fixture seeding all three skills in a single `restore()` and asserting all three outcomes, if the Builder finds that cleaner — but keep the three assertions distinct.

**Gate commands** (Python; isolated data dir to avoid live-instance lock contention):
```
$env:PROBOS_DATA_DIR = (New-Item -ItemType Directory -Force -Path "$env:TEMP\probos_bf656_$(Get-Random)").FullName
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf656_boot_log_hygiene.py tests/test_ontology_ops_comms_resources.py tests/test_ad544_native_tools.py -q -n 0
# then a focused sweep of the touched-adjacent suites:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad423a_tool_foundation.py tests/test_ontology.py -q -n 0
```

---

## 7. Tracking

- **`PROGRESS.md`**: add a `**BF-656 shipped**` line at the top, mirroring the BF-655 line format (`LOCAL (Captain decides push)`), summarizing both parts: (A) removed the graduated `codebase_query` ontology `tool_capabilities` entry so the AD-423a seed no longer collides with the AD-544 native tool (real tool + crew read access unchanged; `ToolRegistry` replace-guard untouched); (B) warm boot now prunes a *definitively* un-restorable skill (no `handle_<name>` — a permanent condition) from the knowledge store via a new `KnowledgeStore.remove_skill` (mirrors `remove_agent`), scoped strictly to the no-handler branch (transient exec failures still retried, never pruned).
- **`docs/development/roadmap.md`**: BF rows **stopped at BF-624** — per the BF-652/654/655 precedent, **skip** the roadmap Bug Tracker row.
- **`DECISIONS.md`**: **not touched** (BF, not an AD).
- Close/comment `seangalliher/ProbOS#1019` on ship (`gh` CLI, `--repo seangalliher/ProbOS`; commit body `closes #1019`).
- Do **NOT** stage `config/system.yaml`. `config/ontology/resources.yaml` **is** committable.

---

## 8. Acceptance criteria

1. **Part A:** `config/ontology/resources.yaml` no longer contains a `codebase_query` `tool_capabilities` entry (replaced by a BF-656 explanatory comment); `get_tool_capabilities()` returns 6; the real AD-544 `codebase_query` native tool + its `ensign→read` perms are unchanged (crew access preserved); seeding the ontology then registering `codebase_query` emits **no** `"Replacing existing tool registration: codebase_query"` (test #A4); the `ToolRegistry` replace-warning still fires for genuine dupes (test #A3).
2. **Part B:** `KnowledgeStore.remove_skill` deletes `.py`+`.json` and schedules a commit (test #B5); warm boot prunes a no-handler skill and logs the prune at INFO (no `"no handler function"` WARNING remains — test #B6); a valid skill still restores and is not pruned (test #B7); a transient exec-error skill is **not** pruned and still logs "restore failed" (test #B8).
3. The one obsolete assertion (`test_all_capabilities` `>= 7` → `>= 6`) is updated; `test_ad544_native_tools`, `test_ad423a_tool_foundation`, `test_ontology_ops_comms_resources` (updated), and the new `test_bf656_boot_log_hygiene` all pass under `-n 0` with an isolated `PROBOS_DATA_DIR`.
4. No change to `ToolRegistry.register`, the AD-423a seed loop, the AD-544 native tools, the warm-boot transient `except`, or any other `tool_capabilities`/`knowledge_sources` entry.
5. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Verify-first checklist (grep/read evidence @ HEAD `4e0bb1cd`, 2026-07-07)

```
# BF ceiling
PROGRESS.md:3                          **BF-655 shipped …**  (highest; BF-656/657 free — git grep empty)
git log --oneline -1                   4e0bb1cd  BF-655 …  (closes #1018)
issue #1019                            titled "BF-656: …" (two boot warnings)

# Part A — codebase_query collision
startup/communication.py:29            async def _noop_handler(**kwargs: Any) -> None:
startup/communication.py:454           # --- AD-423a: Seed tool registry from ontology tool capabilities ---
startup/communication.py:459           for tc in ontology.get_tool_capabilities():
startup/communication.py:469           handler=_noop_handler,
startup/communication.py:475-478       tool_registry.register(adapter, provider=tc.provider, tags=[tc.id, tc.provider])
ontology/service.py:272-275            get_tool_capabilities() -> only self._loader.tool_capabilities (NOT knowledge_sources)
config/ontology/resources.yaml:49      tool_capabilities:
config/ontology/resources.yaml:50-54   - id: codebase_query … provider: ship_computer / available_to: all_crew   ← REMOVE
config/ontology/resources.yaml:92      knowledge_sources:  (episodic_memory/ship_records/knowledge_store — NEVER seeded)
tools/registry.py:92                    def register(
tools/registry.py:111                   if tool.tool_id in self._tools:
tools/registry.py:113                   logger.warning("Replacing existing tool registration: %s", tool.tool_id)
startup/finalize.py:1451                def _wire_native_swe_harness(
startup/finalize.py:1482                count = register_native_swe_tools(registry, runtime)
startup/finalize.py:4236                _wire_native_swe_harness(runtime=…, config=…, tool_executor=…)
swe_harness/tools.py:604                def register_native_swe_tools(registry, runtime) -> int   # 12 tools
swe_harness/tools.py:629-641            entries = [ReadFileTool, ListFilesTool, CodebaseQueryTool, …, RunCommandTool]  (only codebase_query overlaps the 7 ontology ids)
swe_harness/tools.py:633                (CodebaseQueryTool(runtime), read_perms)     # ensign→read preserved
routers/ontology.py:213                 "tool_capabilities": [asdict(t) for t in ont.get_tool_capabilities()]
tests/test_ontology_ops_comms_resources.py:199   assert len(tc) >= 7   ← OBSOLETE → >= 6  (filtered >=4/>=2 at L205-206 + partition invariant stay green: all_crew 5→4, 4+2==6)
tests/test_ad544_native_tools.py:55-57,115         native codebase_query id pinned (access preserved)
# (no test asserts the ONTOLOGY exposes codebase_query; the other codebase_query test hits are ToolPreference/stub/adapter)

# Part B — stale un-restorable skills
warm_boot.py:17                         class WarmBootService:
warm_boot.py:49                         async def restore(self) -> None:
warm_boot.py:165                        # 4. Skills -> compile + attach to SkillBasedAgent
warm_boot.py:167                        skills = await ks.load_skills()
warm_boot.py:168                        if skills and self._config.self_mod.enabled:
warm_boot.py:172                        for intent_name, source_code, descriptor_dict in skills:
warm_boot.py:188-207                    inner compile block (finally only, NO except) — exec errors propagate outward
warm_boot.py:202                        if handler is None: logger.warning("Warm boot: no handler function for skill %s", …); continue   ← PRUNE HERE
warm_boot.py:224                        except Exception as e: logger.warning("Warm boot: skill %s restore failed: %s", …)   ← TRANSIENT (do NOT prune)
knowledge/store.py:28                    _SUBDIRS = (…, "skills", …)
knowledge/store.py:211-217              async def remove_agent(self, agent_type) → unlink .py+.json + _schedule_commit   ← MIRROR
knowledge/store.py:225-229              async def store_skill(intent_name, source, descriptor)
knowledge/store.py:231-249              async def load_skills() -> [(intent_name, source, descriptor)]
# KnowledgeStore.remove_skill ABSENT (git grep: only on CognitiveAgent/SkillCatalog/SkillBasedAgent)
data/knowledge/skills/new_capability.{py,json}   12-byte "# test skill" stub, no handle_new_capability  (gitignored)
data/knowledge/skills/test_skill.{py,json}       12-byte stub, no handle_test_skill  (gitignored)
git check-ignore data/knowledge/skills/test_skill.py   → path returned (IGNORED in OSS tree)
Test-Path data/knowledge/.git          → True (knowledge store = own git repo; prune commits there)
```
```
