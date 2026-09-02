# AD-1185 — A supported `SystemConfig` contract, parsed and booted in CI

**Issue:** [#1121](https://github.com/seangalliher/ProbOS/issues/1121) · **Epic:** #1324 (AD-1270 platform maturity, **Wave 2**)
**Drafted against:** `c5a63b03` (`origin/main`, `git rev-list --left-right --count origin/main...HEAD` → `0 0` at draft time)
**Authority:** [#1121](https://github.com/seangalliher/ProbOS/issues/1121) and [docs/development/platform-maturity-program.md](../docs/development/platform-maturity-program.md) § *Wave 2 — Supported Product and Foundations*
**AD number:** AD-1185 is already allocated by #1121 and named in the program's owner table (line 20). **Do not allocate a new AD number.**
**Mode:** Delegated AD Execution Mode active. The decisions in § *Decisions* are made. Do not re-rank them.

---

## Why this AD is load-bearing

Three later slices cannot meet acceptance without it, per the program doc:

| Consumer | What it needs from AD-1185 | Authority |
|---|---|---|
| AD-1270a supported-profile exercise | *"an inventory over an ad hoc local configuration is not product evidence"* | program doc line 265 |
| AD-1270e1/e2/e3 config extraction | *"Minimal and supported profiles parse and boot unchanged"* | program doc, AD-1270e Acceptance |
| AD-1270c3 runtime services | *"A real runtime boots the AD-1185 supported profile, executes a real `read_file` path"* | program doc line 590 |
| AD-1270g executable README | supported-profile contents as a generator input | program doc line 672 |
| AD-1186 Ship Trials | *"prove the supported product rather than an everything-on laboratory configuration"* | program doc, Outcome 8 |

---

## Read this first — measured facts that change the design

Everything below was measured against `c5a63b03`. Commands are given; re-run any of them.

### 1. `SystemConfig` silently ignores unknown keys. A profile that "parses" proves nothing.

```powershell
d:/ProbOS/.venv/Scripts/python.exe -c "from probos.config import SystemConfig; print(SystemConfig.model_config); c=SystemConfig.model_validate({'nats':{'enabld':True},'typo_section':{'x':1}}); print('nats.enabled =',c.nats.enabled, '| has typo_section:',hasattr(c,'typo_section'))"
```

→ `{}` · `nats.enabled = False | has typo_section: False`

`SystemConfig.model_config` is empty, so Pydantic v2's default `extra="ignore"` applies at **every** level. A `supported` profile that claims to arm `browser_tool.action_dispatch_enabled` but spells it `action_dispatch_enable` parses cleanly through the real `SystemConfig` and ships the feature **off**.

**#1121's acceptance "parsed through the real `SystemConfig`" is necessary and not sufficient.** The loader must reject an unresolvable key *before* `model_validate` discards it. This is the single defect that would make the whole contract unfalsifiable.

### 2. `SystemConfig()` has exactly one environment-dependent default, and it is the byte-identity hazard

```powershell
d:/ProbOS/.venv/Scripts/python.exe -c "import re,pathlib; s=pathlib.Path('src/probos/config.py').read_text(encoding='utf-8'); print('validate_default=True sites:',s.count('validate_default=True')); print([m for m in re.findall(r'os\.environ\.get\(\"([A-Z_]+)\"\)',s)])"
```

→ `validate_default=True sites: 1` · `['PROBOS_LLM_URL', 'XDG_DATA_HOME', 'PROBOS_NATS_ENABLED']`

Only [`NatsConfig.enabled`](../src/probos/config.py#L6117) carries `validate_default=True`, and its `mode="before"` validator at [config.py:6123-6131](../src/probos/config.py#L6123) reads `PROBOS_NATS_ENABLED` at [line 6127](../src/probos/config.py#L6127). `PROBOS_LLM_URL` (line 224) has no `validate_default`, so it never fires for a default; `XDG_DATA_HOME` (line 3605) is read inside the `resolve_archive_db_path` *function*, not a field default, so it cannot reach `model_dump()`.

Measured consequence — SHA-256 of `json.dumps(SystemConfig().model_dump(mode="json"), sort_keys=True, separators=(",",":"))`, in fresh subprocesses:

| `PROBOS_NATS_ENABLED` | default dump sha (first 16) | `nats.enabled` |
|---|---|---|
| unset | `8246174c4f0c9cbe` | `False` |
| unset (repeat) | `8246174c4f0c9cbe` | `False` |
| `false` | `8246174c4f0c9cbe` | `False` |
| **`true`** | **`e953b505e5320b3e`** | **`True`** |

[`tests/conftest.py:24`](../tests/conftest.py#L24) sets `PROBOS_NATS_ENABLED=false` for the whole suite. **A naive byte-identity test therefore passes for the wrong reason** — it passes because conftest's forced value happens to equal the model default, not because the default is environment-independent. On a developer shell exporting `PROBOS_NATS_ENABLED=true` it would fail. Delete the variable in the test.

### 3. The 199-flag census reads differently today, and the delta is unattributable

`SystemConfig` has 192 top-level fields. Walking the nested Pydantic model tree (each model type visited once per path, cycle-guarded) and comparing to `config/system.yaml`:

| Measure | Today (`c5a63b03`) | #1121 (2026-08-03) |
|---|---:|---:|
| Boolean fields reachable from `SystemConfig` | **427** | — |
| …default `False` | **202** | 199 |
| …default `True` | **225** | — |
| Default-`False` armed by `config/system.yaml` | **84** | 80 ("armed locally") |
| Default-`False` not armed | **118** | 119 ("never enabled") |

Both figures are internally consistent (`80+119=199`; `84+118=202`). #1121's instrument is not recorded and its "armed **locally**" may mean the reference vessel's own config rather than the tracked `config/system.yaml`. **Report both with their methods. Do not claim a +3 growth and do not adopt 199.** The instruments differ, so the delta is unattributable.

Reproduce today's numbers with the probe in § *Appendix A*.

Two of #1121's named groups check out exactly, one does not:

- **`federation.*` — 7 default-OFF, matching "all seven".** `a2a.enabled`, `ard.discovery_before_design`, `ard.enabled`, `discovery.multicast_enabled`, `enabled`, `mcp_server.enabled`, `tls.enabled`. (`cluster_monitor.enabled`, `tls.verify_peer`, `validate_remote_results` are default-ON.)
- **`security.memory.enforce_*` — 4 default-OFF, matching "(4)".** `enforce_leak_guard`, `enforce_provenance`, `enforce_recall`, `enforce_store`.
- **`security_infra.*` — 2 default-OFF today, not 3.** Enumerated: `audit_enabled`(T), `audit_persistence_enabled`(T), `credential_tier_enforcement`(**F**), `egress_active_enforcement`(**F**), `egress_deny_by_default`(T), `egress_enabled`(T), `sandbox_enabled`(T), `secrets_persistence_enabled`(T). Record the discrepancy in the manifest; do not silently adopt either number.

All six individually named flags resolve on the live model and are default-`False`: `memory.attention.enabled`, `hooks.enabled`, `qualification.enforcement_enabled`, `native_swe_harness.enabled`, `browser_tool.action_dispatch_enabled`, `dependency.dynamic_install_enabled`.

### 4. `extensions/profiles.py` governs extension IDs and has no production caller — but `minimal` already exists inside `SystemConfig`

[`src/probos/extensions/profiles.py:15`](../src/probos/extensions/profiles.py#L15) defines `_VALID_PROFILES = ("minimal", "developer", "full")`, and `apply_profile()` returns `list[str]` of `enabled_extensions`. Its own docstring records that AD-1215 (#1172) left it with **no production caller**.

The collision is worse than #1121 implies: [`ExtensionsConfig.default_profile: str = "minimal"`](../src/probos/config.py#L6308) puts the token `"minimal"` **inside `SystemConfig`** already, meaning "extension preset". See § *Decision 1* for how this is handled.

### 5. The test/production divergence #1121 asks you to fold in, measured

[`tests/conftest.py:20-25`](../tests/conftest.py#L20) at import time:

```python
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
```

- **NATS.** [`config/system.yaml:2259`](../config/system.yaml#L2259) is `nats.enabled: true`. Production resolves ON; tests resolve OFF via the field validator. Measured: `load_config('config/system.yaml').nats.enabled` is `True` with the variable unset and `False` with it `"false"`.
- **Hugging Face.** `rg 'HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE' src/ scripts/` returns **no matches** — enumeration, not recall. Nothing in ProbOS reads it; `huggingface_hub` does. So the mechanism is entirely outside `SystemConfig`, and production resolves online because nothing sets it.

These are two *different* mechanisms (a config-field validator vs a third-party library env var) and the declaration schema must distinguish them.

### 6. Cost measurements that decide § *Decision 4*

| Operation | Measured |
|---|---:|
| `SystemConfig()` | 0.8 ms |
| `load_config("config/system.yaml")` | 66.9 ms |
| Cold `python -c "import probos.config"` | 370 ms |
| Real `ProbOSRuntime` boot + stop, **cold** | **15.17 s** |
| Real `ProbOSRuntime` boot + stop, warm fixture | **3.98 – 4.24 s** |

Runtime figures from `pytest tests/test_runtime.py::TestRuntimeSubstrate::test_start_and_stop tests/test_runtime.py::TestRuntimeMesh -q -n 0 -p no:randomly --durations=8` → 11 passed in 75.45 s.

---

## Scope

Deliver the **profile contract layer**: versioned profile artifacts, a loader that can reject, a classification + dependency/conflict manifest with a both-directions checker, a declared CI-divergence register, and a real supported-profile boot smoke that runs in the ordinary suite.

**Change no default. Change no existing behaviour. Edit no existing `src/probos/` file except the one line noted in § *Files*.**

---

## Decisions (made — implement these, do not re-rank)

### D1 — Profiles are committed YAML deltas against the **model defaults**, applied by a validating loader

| Option | Verdict |
|---|---|
| **(a) Committed YAML under `config/profiles/`, applied through a loader that pre-validates keys then calls `SystemConfig.model_validate`** | **CHOSEN** |
| (b) A Python module of typed overlays | Rejected |
| (c) Named presets inside `config.py` | Rejected |

**(a) chosen.** The repo's "Pydantic models only / no ad-hoc YAML parsing" rule targets *bypassing the models*, not YAML as a format — [`load_config`](../src/probos/config.py#L7832) is itself `yaml.safe_load` → `SystemConfig.model_validate`, and it is the sanctioned path. A profile is reviewable data, which is what a *versioned contract* has to be. The rule is honoured because the resolved object is a real `SystemConfig` and nothing hand-parses a value.

**(c) rejected** on collision with the very next slice: `config.py` is 7,842 lines, is a `BLAST_RADIUS_PATTERNS` entry in [`scripts/select_tests.py:186`](../scripts/select_tests.py#L186), and AD-1270e1 (same wave) is about to **freeze its schema, field order and dump shape**. Adding presets there guarantees a conflict with e1's golden parity.

**(b) rejected**: a code overlay cannot express "defaults except these twelve" without either restating the model or doing dict merging anyway, and it turns the product contract into a diffable-only-by-programmers artifact.

**Semantics — a profile is a delta against `SystemConfig()`, not against `config/system.yaml`.** Anything a profile omits takes the model default. This is what makes `minimal` expressible as an empty delta and what keeps `config/system.yaml` out of the contract entirely.

**File shape** (two top-level keys, both required):

```yaml
profile:
  id: supported
  version: 1
  description: <one sentence>
  arm: control | product | experiment
overrides:
  browser_tool:
    enabled: true
```

The loader reads `profile:` as metadata and passes **only `overrides:`** to `SystemConfig.model_validate`. It never relies on `extra="ignore"` to swallow the metadata block.

**Key pre-validation (this is the part that makes the contract falsifiable).** Before `model_validate`, walk every leaf path in `overrides` against `SystemConfig.model_fields` recursively and raise `ProfileError` naming the path and the closest valid sibling for any key that does not resolve. Accumulate **all** bad keys into one error, the way the checkers do — do not raise on the first.

**`minimal` byte identity.** `config/profiles/minimal.yaml` carries the metadata block and `overrides: {}`. Assert:

```python
canon = lambda c: hashlib.sha256(
    json.dumps(c.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
assert canon(load_profile("minimal")) == canon(SystemConfig())
```

with `monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)` **inside the test** — see § *Read this first* item 2. Add a second test that sets it to `"true"`, asserts *both* sides move together, and documents in one line that the identity is over the pair, not over a fixed constant. Do **not** hard-code `8246174c4f0c9cbe`; a legitimate default change would then require editing a magic string with no diff explaining it.

### D2 — Classification lives in **one central manifest**, not beside owners, and the checker runs both directions

| Option | Verdict |
|---|---|
| (a) `config_profile_declarations.py` beside owners, mirroring AD-1270a/AD-1256 | Rejected |
| **(b) One reviewed YAML manifest + both-directions checker, mirroring `architecture-baseline.yaml` / `store-baseline.yaml`** | **CHOSEN** |
| (c) `Field(json_schema_extra=...)` on each flag in `config.py` | Rejected |

**(b) chosen, and it deliberately differs from AD-1270a D1 / AD-1256 D2.** Record the reason in `DECISIONS.md`: those AD's declarations describe *modules scattered across the tree*, where "beside the owner" is a real location and a central file would rot. A config flag has no such home — `browser_tool.action_dispatch_enabled` is **declared** in `config.py` and **consumed** somewhere else, so "beside the owner" would require inventing an owner attribution the codebase does not have. And unlike stores or capabilities, the complete denominator is available from one authority at import time (`SystemConfig.model_fields`), so a central manifest **cannot** silently fall behind — the checker enumerates the live model.

**(c) rejected hard.** 202 edits to the highest-blast-radius file, mid-flight against AD-1270e1's schema freeze, and `json_schema_extra` changes the generated JSON schema that e1 is about to pin.

**Taxonomy — exactly the six kinds #1121 names. Do not invent a seventh.**

| `kind` | Meaning | Example |
|---|---|---|
| `consent-gate` | Arming implies a human or legal decision | `os_activity.enabled`, `avatar_telemetry.*` |
| `security-control` | Arming changes an enforcement posture | `security.memory.enforce_*`, `security_infra.credential_tier_enforcement` |
| `optional-integration` | Arming requires an external dependency | `nats.enabled`, `channels.discord.enabled` |
| `research-treatment` | An experimental arm, mutually exclusive by design | ablation/emergence flags |
| `migration-control` | A temporary switch between old and new behaviour | — |
| `product-feature` | A user-facing capability `supported` may include | `approval_inbox.enabled` |

Row schema:

```yaml
- path: browser_tool.action_dispatch_enabled
  kind: product-feature
  profiles: [experimental-browser-dispatch]   # profiles that may arm it; [] = none yet
  evidence_to_promote: "<what must be true before `supported` arms this>"
  external_dependency: null                   # required non-null for optional-integration
  requires: []                                # dotted paths that must also be ON
  conflicts_with: []                          # dotted paths that must be OFF
```

**What gates now (fails the build):**

1. **Every path named by any profile's `overrides`** must have a manifest row, and `product-feature` / `optional-integration` rows named by `supported` must have a non-empty `evidence_to_promote`.
2. **Manifest → model**: every `path` resolves on `SystemConfig`. An unresolvable path is a broken row, not a missing flag.
3. **Model → manifest**: every default-`False` bool reachable from `SystemConfig` is either classified **or** listed in the frozen `unclassified_flags:` baseline. A **new** flag lands in neither and fails on day one.
4. Conflict/dependency violations — see D3.
5. Declared CI divergences still exist — see D5.

**What is report-only, with a named promotion condition:** the ~190 pre-existing unclassified flags. Freeze them as a row-per-path list under one shared `review:` block, copying [`docs/development/store-baseline.yaml`](../docs/development/store-baseline.yaml)'s wording pattern — *"the rows carry no per-row rationale because every row means the same thing; a field that is always the same sentence stops being read."* Promotion condition: `review_by: This list is empty, or every remaining flag has a classification.`

Be plain in the manifest header: **202 flags cannot be triaged in one slice, and pretending otherwise would produce 190 rows of invented rationale.** The property this slice buys is the same one AD-1256 bought — a new flag fails immediately, and the backlog is visible and frozen rather than grandfathered as compliant.

### D3 — Conflicts fail at **profile parse**, in the loader. `config.py` is not edited.

| Option | Verdict |
|---|---|
| (a) `model_validator(mode="after")` on `SystemConfig` | Rejected **now**, promotion condition below |
| (b) External checker only, failing in preflight | Rejected as insufficient |
| **(c) Hard fail in the profile loader + checker proof that no tracked config is affected** | **CHOSEN** |
| (d) A general predicate DSL | Rejected |

**(c) chosen.** #1121 says conflicts fail *at parse*. A profile **is** parsed, and `load_profile("supported")` raises `ProfileConflictError` before returning a `SystemConfig` — so the artifact this AD introduces does fail at parse, which is the acceptance criterion satisfied honestly.

**(a) rejected now** because a validator on the root fires for **every** `SystemConfig(...)` construction: 1,376 test files, three tracked YAMLs, every commercial-overlay import, and every untracked operator config in the field. A previously-working config would begin refusing to boot. That is a behaviour change to the config root, in the same wave that AD-1270e1 is freezing the config root's contract.

**Promotion condition, so this is a decision and not a deferral:** promote to a root `model_validator` when (i) the checker has shown zero declared conflicts firing across `SystemConfig()`, `config/system.yaml`, `config/node-1.yaml` and `config/node-2.yaml`, and (ii) AD-1270e1's golden parity has shipped so a validator addition can be proven not to alter the frozen dump. Record both in the manifest's `promotion:` block.

**(d) rejected**: a predicate language needs its own evaluator, its own grammar tests and its own failure modes. `requires` and `conflicts_with` express everything #1121 names ("mutually exclusive research and security modes"). Two relations, no evaluator.

**How `minimal` and today's configs are proven unaffected — proven, not asserted.** The checker evaluates every declared `requires` / `conflicts_with` against `SystemConfig()`, `config/system.yaml`, `config/node-1.yaml` and `config/node-2.yaml`, and **fails** if any fires. A conflict rule that would break a tracked config cannot be merged. Report the four evaluations in the `--json` output so the property is visible, not implied.

### D4 — CI boot is a **pytest test**; the manifest currency check is a preflight phase

| Option | Verdict |
|---|---|
| **(a) Boot smoke as an ordinary pytest test** | **CHOSEN** for the boot |
| (b) A new preflight phase for the boot | Rejected |
| (c) A separate opt-in script | Rejected |
| **(d) A cheap `config-profiles` preflight phase for the manifest/currency check only** | **CHOSEN**, with a hard cost bail-out |

**(a) chosen for the boot.** Measured: 3.98–4.24 s warm inside the suite, under 16 xdist workers. It runs in every canonical gate by construction.

**(b) rejected on measured cost.** Preflight's budget is 90 s and it currently spends ~31 s, leaving ~59 s. Preflight phases are separate processes, so a boot there pays the **cold** 15.17 s — a quarter of the entire remaining headroom for one check — and it would run *before* pytest, blocking a 16-minute gate on a heavyweight integration path. Preflight is for cheap deterministic structural checks.

**(c) rejected**: an opt-in script CI does not run is the exact "built, tested, inert" defect this program exists to kill. #1121 says *CI boots it*.

**(d) chosen for the manifest check only, with a bail-out you must honour.** It is the same shape as the six shipped phases: cheap, deterministic, whole-tree, and it must fail *before* a 16-minute run when a new flag arrives unclassified. Estimated cost ≈ cold import (370 ms) + model walk + 3–5 YAML loads + AST parse of **one** named test file ≈ 0.6–1.0 s.

**Hard bail-out:** measure the phase with `--durations`-style timing on the pinned host and report the number. **If it exceeds 3.0 s, drop the phase entirely** and keep the checker as a pytest test only (`tests/test_ad1185_config_profiles.py` invoking `main(["--check"])`, the way [`tests/test_config_reference_current.py`](../tests/test_config_reference_current.py) does). Do not spend more than 3 s of a 59 s headroom on this.

If the phase ships, insert it as `"config-profiles"` **immediately after `"config-reference"`** (same authority: `probos.config`) and update the exact-equality assertion at [`tests/test_run_test_gate.py:250-258`](../tests/test_run_test_gate.py#L250). That test breaks deliberately; changing it is the point, and the list must read:

```python
["import-origin", "config-reference", "config-profiles", "ad-ledger",
 "seam-contracts", "architecture-fitness", "store-registry", "compile"]
```

**How the boot is proven to actually run — three independent bindings**, because "it is a test, tests run" is precisely the assumption this program distrusts:

1. The manifest records `smoke_test_node_id: tests/test_ad1185_config_profiles.py::test_supported_profile_boots_and_reads_a_file`. The checker resolves it by **AST over that single file** (copy `SymbolIndex` from [`scripts/check_seam_contracts.py:140`](../scripts/check_seam_contracts.py#L140) and `resolve_symbol` at [:272](../scripts/check_seam_contracts.py#L272)) — a rename or deletion fails.
2. The same check asserts the resolved test carries no `@pytest.mark.skip` / `skipif` / `xfail` decorator. A skipped boot is a non-passing boot; state that in the module docstring.
3. `src/probos/config.py` and `src/probos/runtime.py` are already `BLAST_RADIUS_PATTERNS` in [`scripts/select_tests.py:183-196`](../scripts/select_tests.py#L183), so any config-root or runtime change fails broad to the full gate and the smoke can never be selected away. Add `src/probos/config_profiles.py` and `config/profiles/*` to `BLAST_RADIUS_PATTERNS` in the same commit.

**Boot smoke shape** — model it on the fixture at [`tests/test_runtime.py:12-18`](../tests/test_runtime.py#L12) and the body of [`test_submit_intent_read_file`](../tests/test_runtime.py#L114). Verified signatures: `ProbOSRuntime(config: SystemConfig | None = None, data_dir: str | Path | None = None, ...)` at [runtime.py:511](../src/probos/runtime.py#L511); `async def submit_intent(self, intent: str, params: dict[str, Any] | None = None, urgency: float = 0.5, context: str = "", timeout: float | None = None, ...)` at [runtime.py:3933](../src/probos/runtime.py#L3933).

```
rt = ProbOSRuntime(config=load_profile("supported"), data_dir=tmp_path / "data")
await rt.start()
results = await rt.submit_intent("read_file", params={"path": str(f)}, timeout=5.0)
assert results and all(r.success for r in results)
await rt.stop()
```

Bound it: one boot, one intent, `timeout=5.0`, `tmp_path`. Report the measured duration.

### D5 — CI divergences are declared, checked in both directions, and not "fixed"

The manifest carries a `ci_divergences:` block. Each entry:

```yaml
- id: nats-forced-off-in-tests
  mechanism: config-field-validator      # or: third-party-env
  env_var: PROBOS_NATS_ENABLED
  set_by: tests/conftest.py
  set_to: "false"
  config_path: nats.enabled              # null when the var never reaches SystemConfig
  production_resolution: "config/system.yaml:2259 sets nats.enabled: true"
  rationale: "BF-245 — a real NATS connection in 1,376 test files is a shared external dependency"
```

Checked **both directions**:

- **Declared → real.** Each entry's `env_var` is still `setdefault`-ed at the declared path with the declared value, resolved by AST over `tests/conftest.py` (`ast.Call` on `os.environ.setdefault`, not a text scan). If someone removes the NATS override the declaration goes stale and fails.
- **Real → declared.** Enumerate `os.environ.get(...)` reads in `src/probos/config.py` by AST — measured today as exactly three (`PROBOS_LLM_URL`, `XDG_DATA_HOME`, `PROBOS_NATS_ENABLED`) — and require every one that can reach a **default** (i.e. its field carries `validate_default=True`) to be declared. A fourth environment-dependent default added later fails.

Seed with the two #1121 names. `HF_HUB_OFFLINE` is `mechanism: third-party-env`, `config_path: null`: enumerated with `rg 'HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE' src/ scripts/` → **no matches**, so nothing in ProbOS reads it and the divergence is entirely outside `SystemConfig`. Say that in the row rather than implying the profile controls it.

**This AD does not remove either divergence.** #1121 asks that the profile work *"make that divergence explicit"* — declaring and checking it is the deliverable.

### D6 — Name collision with `extensions/profiles.py`: the ID `minimal` collides unavoidably; everything else deliberately differs

#1121 **binds** the names `minimal` and `supported`, so `minimal` cannot be renamed. And the token already lives inside `SystemConfig` as [`ExtensionsConfig.default_profile: str = "minimal"`](../src/probos/config.py#L6308), naming into the *extension* vocabulary.

Neutralise it by keeping the two systems provably disjoint:

| Axis | Config profiles (this AD) | Extension profiles (AD-481g) |
|---|---|---|
| Directory | `config/profiles/` | `config/extension_profiles/` |
| Loader | `probos.config_profiles` | `probos.extensions.profiles` |
| Vocabulary | `minimal`, `supported`, `experimental-*` | `minimal`, `developer`, `full` |
| Governs | `SystemConfig` fields | extension IDs |

`developer` and `full` are **forbidden** as config-profile IDs — that asymmetry is what lets a reader tell the two sets apart. Pin the disjointness with two tests: `probos.config_profiles` never imports `probos.extensions.profiles` (AST over the module's imports), and never reads `extensions.default_profile`.

### D7 — `supported` v1 is small and evidence-bound, and is **not** a copy of `config/system.yaml`

`config/system.yaml` arms 84 default-OFF flags including `nats.enabled`, `channels.discord.enabled`, `execution.enabled`, `browser_tool.enabled`. It is the reference-vessel operator config, not the product contract.

**Admission rule for `supported` v1 — all four must hold, per flag:**

1. a manifest row with `kind` in `{product-feature, security-control}`;
2. a non-empty `evidence_to_promote` naming an existing test node that proves the flag works;
3. the profile still boots with **no network and no external service** — proven by the D4 smoke, which runs offline;
4. no `requires` / `conflicts_with` violation.

`optional-integration` flags are **excluded from `supported` v1** by rule 3: a flag whose absence blocks boot cannot be in a profile whose acceptance is a CI boot. Record that as the profile's stated bound, with the promotion condition being a declared `degrades_to:` behaviour proven by a test.

Ship **at least one** `experimental-*` profile so the third arm of #1121's three-profile decision is exercised rather than described. One small explicit combination is enough.

Report the resulting `supported` flag count. Do not pad it.

---

## Files

**New:**

| Path | Role |
|---|---|
| `config/profiles/minimal.yaml` | Control arm. `overrides: {}`. |
| `config/profiles/supported.yaml` | The product configuration. |
| `config/profiles/experimental-<name>.yaml` | At least one named treatment. |
| `docs/development/config-profiles.yaml` | Classification + conflict graph + `ci_divergences` + frozen `unclassified_flags` baseline. |
| `src/probos/config_profiles.py` | Loader: `load_profile`, `ProfileError`, `ProfileConflictError`, `PROFILE_IDS`. Imports `probos.config` and stdlib + `yaml` only. |
| `scripts/check_config_profiles.py` | The checker. |
| `tests/test_ad1185_config_profiles.py` | Tests. |

Every one of these paths was enumerated as absent at draft time (`git ls-files -- 'config/profiles*' 'src/probos/config_profiles.py' 'src/probos/profiles*' 'scripts/check_config_profiles.py' 'docs/development/config-profiles*' 'tests/test_ad1185*'` → empty).

**Modified:**

| Path | Change |
|---|---|
| `scripts/select_tests.py` | Add `src/probos/config_profiles.py` and `config/profiles/*` to `BLAST_RADIUS_PATTERNS`. |
| `scripts/run_test_gate.py` | Add the `config-profiles` phase — **only if it measures ≤ 3.0 s**. |
| `tests/test_run_test_gate.py` | Update the exact-equality list — only if the phase ships. |
| `DECISIONS.md`, `PROGRESS.md`, `docs/development/platform-maturity-program.md` | Record the AD; mark Wave 2's "AD-1185 supported profile" delivered. |

**Patterns to copy, by name:**

- Checker skeleton, `--check` / `--json` / `--update-baseline` / `--baseline` / `--src-root` CLI, `git ls-files` indexing, accumulate-all-errors: [`scripts/check_store_registry.py`](../scripts/check_store_registry.py) (see its CLI at lines 1225-1244 and `git ls-files -z` at line 303).
- AST symbol resolution, never regex over source: `SymbolIndex` at [`scripts/check_seam_contracts.py:140`](../scripts/check_seam_contracts.py#L140), `resolve_symbol` at [:272](../scripts/check_seam_contracts.py#L272).
- Frozen reviewed baseline with `schema_version` / `baseline_id` / `tracking_issue` / `review:{owner,rationale,review_by}` and symmetric-difference gating: [`docs/development/store-baseline.yaml`](../docs/development/store-baseline.yaml) and [`docs/development/architecture-baseline.yaml`](../docs/development/architecture-baseline.yaml).
- Generator/checker also run as an ordinary test: [`tests/test_config_reference_current.py`](../tests/test_config_reference_current.py).
- Dotted-path-over-`SystemConfig` vocabulary — reuse it verbatim so AD-1270a's `configured_when` and this manifest's `path` are the same language: `_resolve_configured` in [`src/probos/maturity/report.py`](../src/probos/maturity/report.py#L105).
- Runtime boot + real `read_file`: fixture at [`tests/test_runtime.py:12-18`](../tests/test_runtime.py#L12), body at [:114-128](../tests/test_runtime.py#L114).

---

## Acceptance criteria

- [ ] `config/profiles/{minimal,supported,experimental-*}.yaml` exist, each with a `profile:` metadata block and an `overrides:` block, and each parses through the **real** `SystemConfig`.
- [ ] **`minimal` byte identity asserted**: SHA-256 of the canonicalised `model_dump(mode="json")` of `load_profile("minimal")` equals that of `SystemConfig()`, with `PROBOS_NATS_ENABLED` **deleted** in the test, plus a second test proving both sides move together when it is set to `"true"`. No hard-coded hash constant.
- [ ] The loader **rejects an unresolvable override key** with all bad keys accumulated into one error. A test proves a misspelled nested key raises rather than being silently ignored — the defect described in § *Read this first* item 1.
- [ ] `docs/development/config-profiles.yaml` classifies every flag any profile arms, using **exactly** the six `kind` values, each with `evidence_to_promote`.
- [ ] The checker fails in **both** directions: a manifest row naming a path absent from `SystemConfig`, and a new default-`False` bool present in neither the manifest nor the frozen baseline. Both proved by injection tests that restore byte-identically.
- [ ] `requires` / `conflicts_with` are enforced in the loader and **fail at parse** of a profile. A deliberately-conflicting fixture profile raises `ProfileConflictError`.
- [ ] The checker proves **zero** declared conflicts fire against `SystemConfig()`, `config/system.yaml`, `config/node-1.yaml`, `config/node-2.yaml`, and reports all four in `--json`.
- [ ] `ci_divergences:` declares NATS and Hugging Face with their distinct mechanisms, and is checked both directions (declared→real over `tests/conftest.py`; real→declared over `os.environ.get` reads in `config.py` whose field carries `validate_default=True`).
- [ ] **CI boots the supported profile and runs a bounded smoke workload**: one `ProbOSRuntime` boot from `load_profile("supported")`, one real `read_file` intent, clean `stop()`, offline, in the ordinary suite. Report its measured duration.
- [ ] The smoke's node ID is recorded in the manifest, resolved by AST, and asserted not to be skip/xfail-marked.
- [ ] `src/probos/config_profiles.py` and `config/profiles/*` added to `BLAST_RADIUS_PATTERNS`.
- [ ] `config-profiles` preflight phase added **and its measured cost reported**, or dropped with the measurement given as the reason. If added, `tests/test_run_test_gate.py`'s exact-equality list is updated to the eight-phase list in § *D4*.
- [ ] Two disjointness tests: `probos.config_profiles` imports neither `probos.extensions.profiles` nor reads `extensions.default_profile`; `developer` and `full` are rejected as config-profile IDs.
- [ ] The `security_infra.*` count discrepancy (2 measured vs 3 in #1121) and the 202/199 census discrepancy are **recorded in the manifest header as unattributable instrument deltas**, not silently resolved.
- [ ] **At least 40 new tests** in `tests/test_ad1185_config_profiles.py`. Report the exact count and the focused-run result.
- [ ] Adversarial review by Diff Reviewer on a **different model than wrote the code**, findings repaired before commit.
- [ ] Canonical gate green with a banked receipt; node total predicted before the run and reconciled.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do not build

- **An "everything on" profile**, under any name, including a test fixture that arms every flag "to check parsing". #1121: *mutually exclusive research and security modes exist; it would be actively unsafe.* This is a hard constraint, not a preference.
- **Promotion of flags by one blanket rule.** No "all `*.enabled` become `product-feature`", no "everything armed in `config/system.yaml` enters `supported`". Six kinds, per-flag, with evidence.
- **Any change to any existing default.** Not one `False` becomes `True` in `config.py`.
- **Any edit to `docs/development/architecture-baseline.yaml` or `docs/development/store-baseline.yaml`.** Those are AD-1270b's and AD-1256's frozen rows.
- **Any edit to `config/system.yaml`, `config/node-1.yaml`, `config/node-2.yaml`.** They are inputs the checker reads, not artifacts it maintains.
- **Any edit to `src/probos/config.py`.** No new validator, no `json_schema_extra`, no preset. It is blast-radius and AD-1270e1 is freezing it in this same wave.
- **A root `model_validator` on `SystemConfig`.** Deferred with a promotion condition — see D3.
- A predicate DSL, expression evaluator, or profile-inheritance/`extends` mechanism.
- A runtime consumer. Nothing under `src/probos/` may import `scripts/check_config_profiles.py`; the direction is checker → data, per AD-1270a's D6.
- Reuse or modification of `src/probos/extensions/profiles.py`. It governs extension IDs and has no production caller; leave it alone.
- Removing or "fixing" the NATS or Hugging Face test overrides. Declare them.
- A second config loader. `load_config` stays the entry point for file-path configs; `load_profile` is for profile IDs.

---

## Risks the Builder must be warned about

1. **`extra="ignore"` makes a wrong profile look right.** Measured in § *Read this first* item 1. If you skip the key pre-validation, every acceptance criterion still passes and the contract is worthless. Write that test first.
2. **The byte-identity test can pass for the wrong reason.** `tests/conftest.py:24` forces `PROBOS_NATS_ENABLED=false`, which coincides with the model default. Without `monkeypatch.delenv` the test proves nothing about environment independence and would fail on a shell exporting `true`.
3. **`supported` must boot offline.** `config/system.yaml` arms `nats.enabled`, `channels.discord.enabled`, `execution.enabled`, `browser_tool.enabled`. Copying it would give a profile whose smoke needs a NATS server. `optional-integration` is excluded from v1 by rule (D7 rule 3) for exactly this reason.
4. **Do not put the boot in preflight.** Cold boot measured at 15.17 s against ~59 s of remaining budget, and preflight runs before pytest.
5. **`tests/test_run_test_gate.py` asserts the phase list by exact equality** at lines 250-258. It breaks on purpose. If you drop the phase under the 3 s bail-out, do **not** touch that test.
6. **Staging this prompt adds a `phantom-api` preflight phase.** [`_staged_prompt_paths`](../scripts/run_test_gate.py#L1056) appends a PowerShell phantom-API scan for any staged `prompts/*.md`. Expect it, and expect it to require `pwsh`.
7. **`config.py` is blast-radius.** Any edit fails the selector broad and collides with AD-1270e1. The design deliberately requires zero edits there; if you find yourself needing one, stop and re-read D1/D3.
8. **Never regex over Python source.** The `check_store_registry.py` history is the lesson: a raw-source regex prefilter contradicted the module's own rule and skipped real cases. Both the conftest scan and the `config.py` env scan are AST walks.
9. **An injection test must restore byte-identically.** `.mutbak` sibling, restore in `finally`, and assert the restored bytes equal the original. A leftover injected row poisons the next gate.
10. **A skipped smoke is a failed smoke.** Assert the absence of skip markers rather than trusting a green summary line — a skip count moving is invisible in `passed`.
11. **`minimal` is the ablation control arm.** If a future edit makes `minimal.yaml` non-empty, the byte-identity test is the only thing that catches it. Do not weaken it to accommodate a metadata field; metadata lives under `profile:`, which the loader strips before `model_validate`.

---

## Validation

1. Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1185_config_profiles.py tests/test_run_test_gate.py tests/test_config.py tests/test_config_reference_current.py tests/test_runtime.py -q -n 0 -p no:randomly`
2. Checker directly: `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check` and `--json`.
3. Adversarial review on the staged diff, **different model than wrote the code**, prompt under ~4 KB, scoped to the loader, the checker, and the boot smoke as the consumer.
4. `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1185`; repair everything; commit the reviewed tree.
5. `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1185` — synchronous, no terminal timeout. ~15-19 min; it sits at `[ 99%]` for several minutes, which is normal.
6. Bank the receipt and its manifest/JUnit/collection artifacts into `logs/gates/` and re-verify their hashes from the primary repository **before** removing the worktree or pushing.

---

## Appendix A — the census probe

Reproduces § *Read this first* item 3. Throwaway; delete it before committing.

```python
from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from probos.config import SystemConfig, load_config

def walk(model, prefix, seen, out):
    if model in seen:
        return
    seen = seen | {model}
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}" if prefix else name
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            walk(ann, f"{path}.", seen, out)
        elif ann is bool:
            d = field.default
            if d is PydanticUndefined and field.default_factory is not None:
                d = field.default_factory()
            out.append((path, d))

rows = []
walk(SystemConfig, "", set(), rows)
off = [p for p, d in rows if d is False]

def get(o, p):
    for part in p.split("."):
        o = getattr(o, part, None)
        if o is None:
            return None
    return o

y = load_config("config/system.yaml")
armed = [p for p in off if get(y, p) is True]
print(len(rows), len(off), len(armed), len(off) - len(armed))
```

Expected at `c5a63b03` with `PROBOS_NATS_ENABLED` unset: `427 202 84 118`.
