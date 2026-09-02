# AD-1256 — Store registry and shared storage lifecycle (declaration slice)

**Issue:** [#1302](https://github.com/seangalliher/ProbOS/issues/1302) · **Epic:** #1324 (AD-1270 platform maturity, Wave 2)
**Drafted against:** `d45ae9c3` (`origin/main`, `0 0` divergence at draft time)
**Mode:** Delegated AD Execution Mode active. The in-envelope decisions below are already made; do not re-open them.

---

## Read this first: three premises are wrong, and one baseline row is false

Everything in this section was measured against the live tree, not recalled. Commands are given so you can re-run them.

### 1. The connection abstraction already exists. You are not building one.

The AD's headline — *"no storage abstraction, 34 bespoke connects, against the repo's own rule"* — is half right. The **rule's target already ships**:

| Thing | Where | Since |
|---|---|---|
| `DatabaseConnection` Protocol | [src/probos/protocols.py](src/probos/protocols.py#L325) | AD-542 |
| `ConnectionFactory` Protocol | [src/probos/protocols.py](src/probos/protocols.py#L362) | AD-542 |
| `SQLiteConnectionFactory` + `default_factory` singleton | [src/probos/storage/sqlite_factory.py](src/probos/storage/sqlite_factory.py) | AD-542 |
| `StorageBackend` ABC + `SQLiteStorageBackend` | [src/probos/infrastructure/storage_backend.py](src/probos/infrastructure/storage_backend.py) | AD-466 |

46 modules under `src/probos` mention `ConnectionFactory`. The canonical store constructor is already a five-plus-instance pattern:

```python
def __init__(self, db_path: str = "", connection_factory: ConnectionFactory | None = None) -> None:
```

**Therefore AD-1256 adds no new connection abstraction.** It adds *declarations* and a *checker*. See Decision 1.

### 2. The db-connect occurrence count is 32, not 31

The task framing said "30 reviewed rows / 31 occurrences". Measured:

```powershell
d:/ProbOS/.venv/Scripts/python.exe -c "import yaml,pathlib,collections; d=yaml.safe_load(pathlib.Path('docs/development/architecture-baseline.yaml').read_text(encoding='utf-8')); db=[r for r in d['violations'] if r['category']=='db-connect']; print(len(db), sum(int(r.get('count',1)) for r in db))"
```

→ **30 rows, 32 occurrences.** Two rows carry `count: 2` — `probos.__main__::_cmd_reset` and `probos.infrastructure.backup::BackupService._backup_one`. Callee split: `sqlite3.connect` 22, `aiosqlite.connect` 8. Use 32.

### 3. #1302's store census is from 2026-08-22 and reads differently today

#1302 says 59 databases declared in `src/`, 36 of 59 with no delete path, 34 connect sites across 23 files. Measured today over `git ls-files src/probos` (915 tracked `.py` files):

| Measure | Today | #1302 (2026-08-22) |
|---|---|---|
| Distinct `*.db` filename literals | **54** | 59 "declared" |
| Modules containing `CREATE TABLE` | **58** | — |
| …of those, with no `DELETE FROM` | **38** | 36 of 59 |
| Modules never mentioning `ConnectionFactory`, but holding `CREATE TABLE` | **18** | — |
| db-connect sites | **30 rows / 32 occurrences** | 34 across 23 files |

Do **not** report the connect figure as a reduction from 34 → 32. The checker collapses call sites per enclosing symbol and resolves import aliases; #1302 counted raw sites. Different instruments, so the delta is unattributable. Report both with their methods.

Two of today's 54 `.db` literals are the same file spelled two ways (`directives.db` and `data/directives.db`; likewise `service_profiles.db` / `data/service_profiles.db`). That is itself a finding for the declaration to resolve — a store has one canonical path.

### 4. RETRACTED — the baseline row is already correct

An earlier revision of this prompt claimed that
`probos.storage.sqlite_factory::SQLiteConnectionFactory.connect` was baselined
`disposition: debt` with a false rationale, and instructed you to fix it.
**That claim is refuted.** The row as committed reads:

```yaml
- category: db-connect
  key: probos.storage.sqlite_factory::SQLiteConnectionFactory.connect
  callee: aiosqlite.connect
  count: 1
  disposition: approved
  owner: AD-1256
  rationale: The ConnectionFactory implementation itself; this is the adapter every other store is meant to route through.
```

Verified against the committed tree, not the worktree:
`git show HEAD:docs/development/architecture-baseline.yaml` shows
`disposition: approved`; `git diff --quiet HEAD -- docs/development/architecture-baseline.yaml`
exits 0, so nothing local is masking it; and
`git log -S'SQLiteConnectionFactory.connect'` shows it shipped that way in
`b70c2026`.

**Do not edit `docs/development/architecture-baseline.yaml` at all in this
slice.** Leave all 30 rows alone.

The one true observation underneath the retracted claim is worth keeping:
`scripts/check_architecture_principles.py` has no approved-adapter exclusion —
`DB_CONNECT_CALLEES = frozenset({"sqlite3.connect", "aiosqlite.connect"})` and
every rendered match becomes a finding, so the adapter is baselined rather than
exempted. `disposition` is reviewer metadata and does not gate:
`compare_to_baseline()` keys on `(category, key, callee)` and compares `count`
and `triggers` only. That is context, not a task.

---

## Scope

Introduce the **declaration layer** for durable stores, and a checker that can fail. Adopt it for **new** stores. Migrate nothing.

`docs/development/platform-maturity-program.md` § *AD-1256 — Store Registry and Shared Storage Lifecycle* says: metadata-only `StoreDescriptor` declarations using the **existing** `ConnectionFactory` seam; begin in inventory-only shadow mode; require every new store to register immediately; *"the registry owns lifecycle metadata and connection creation, not domain queries or one giant database."* This slice delivers the metadata half. Connection creation is already the `ConnectionFactory` seam and stays there.

---

## Decisions (made — implement these, do not re-rank)

### D1 — No new connection abstraction. Adopt the existing `ConnectionFactory` seam by reference.

Ranked:

| Option | Verdict |
|---|---|
| **(a) Declare against the existing `ConnectionFactory` Protocol; add no connection API** | **CHOSEN** |
| (b) A `StoreBase` ABC that stores inherit | Rejected |
| (c) A registry-owned connection pool | Rejected |
| (d) A new `StoreLifecycle` Protocol (`start`/`stop`) beside `ConnectionFactory` | Deferred |

**(a) chosen** because the standing rule the AD quotes is already satisfied by a shipped seam. Adding a second connection abstraction would create two correct answers for one question, which is the defect this AD exists to remove, not an instance of it. DIP and ISP are already satisfied by constructor injection of a narrow Protocol.

**(b) rejected** on three counts. Inheritance couples lifecycle to identity, against the repo's constructor-injection preference. It would force a base-class change on 30 stores, which #1302 puts out of scope. And LSP fails on the real population: the 58 `CREATE TABLE` modules are not one contract — some are synchronous `sqlite3` (`ChatThreadStore._connect`, `WorkingMemoryStore.append`), some async `aiosqlite` (`ActivationTracker.start`), some have `start()/stop()` and some have neither. One ABC over that set would be a lie enforced by the type system.

**(c) rejected** as the service locator the program's Do-Not-Build list names. A registry holding live connections is mutable runtime state keyed by store — precisely the shape AD-1270a's D1 rejected for capabilities (*"the resulting object holds mutable runtime state keyed by capability, which is literally the second runtime registry the program's Do-Not-Build list names"*). It would also relocate WAL and `busy_timeout` semantics for 30 stores in one commit.

**(d) deferred**, with a promotion condition rather than a vague "later": add a `StoreLifecycle` Protocol when **AD-1270c2** (`startup/lifecycle.py`, typed start/stop registrations) has a consumer that would call it. Shipping an unconsumed Protocol now is API surface with no verifier.

### D2 — Declarations live beside their owning module, and the checker runs in **both** directions.

Ranked:

| Option | Verdict |
|---|---|
| (a) Central YAML, like `docs/development/seams/p0-manifest.yaml` | Rejected |
| **(b) `storage_declarations.py` beside each owner, mirroring `maturity_declarations.py`** | **CHOSEN** |
| (c) Class attributes on each store class | Rejected |

**(b) chosen** for consistency with AD-1270a's D1, recorded in [DECISIONS.md](DECISIONS.md#L93): *"hybrid: static declarations beside each owner, and a registry that only resolves them"*, because declarations become **new data files** rather than calls into existing code, so the slice lands with zero production call-site edits. That property is what keeps this slice inside #1302's "not in scope" boundary.

**(a) rejected**: a central YAML puts storage truth outside the package that owns it and rots against code — the seam manifest needed an entire checker (`check_seam_contracts.py`) to stop exactly that. **(c) rejected**: it requires editing 30 store classes (out of scope), and it makes the inventory depend on import order, which is neither deterministic nor `--check`-able — AD-1270a D1's stated reason for rejecting registration-at-import.

**The part AD-1270a does not have, and you must build: an inventory that can fail.** AD-1270a's declarations are opt-in; nothing detects an undeclared capability. An inventory nobody can fail is documentation. So `scripts/check_store_registry.py` runs both directions:

1. **Declared → exists.** Every `owner_module::owner_symbol` resolves by AST against `src/probos/`. Copy `SymbolIndex` from [scripts/check_seam_contracts.py](scripts/check_seam_contracts.py) — AST-only, never `import`, never regex over source text (a dotted path in a docstring must not read as resolved).
2. **Exists → declared.** Any module binding a string constant containing `CREATE TABLE` that no declaration names is an **undeclared store**. AST over `ast.Assign` with an `ast.Constant` string value, *not* a text scan: measured 58 modules match by raw text but only 51 bind a named constant, and `src/probos/config.py` is a pure text false positive.

Detection bound, state it in the module docstring rather than letting a reader assume coverage: 7 modules build `CREATE TABLE` inline at the `execute()` call rather than binding a constant (`builder_specialists.py`, `crew_profile.py`, `directive_store.py`, `commands_directives.py`, `security/audit_log.py`, `service_profile.py`, and `config.py` which is a false positive). Rule 2 catches constants; extend the AST walk to string constants passed directly to an `execute`/`executescript` call so those 6 real ones are seen, and say plainly that a schema assembled by string concatenation or f-string is still out of reach.

### D3 — What gates today, and what is report-only with a named promotion condition.

**Gates now (fails the build):**

| Rule | Why it can fail today |
|---|---|
| Declaration schema validity — blank `owner` / `criticality` / `retention` / `path` is an error | Copies the architecture baseline's deliberate *"a blank owner/rationale/review_by fails `--check` on purpose"* |
| `criticality` outside `{required, optional, feature-gated}` | Closed vocabulary |
| `retention` outside the closed vocabulary, including the explicit `unbounded` | Retention is mandatory **by declaration**; `unbounded` is legal but must be written |
| Duplicate declaration `id`, or two declarations claiming the same canonical `path` | Mirrors `MaturityRegistry.register()` raising on duplicate id |
| Declared → exists (symbol resolution) | A declaration naming a deleted store fails |
| Exists → declared, against a frozen reviewed baseline, symmetric difference | **A new undeclared store fails on day one** |

The exists→declared rule uses the **same shape as `architecture-baseline.yaml`**: today's undeclared stores are frozen into a reviewed list, and symmetric difference means a *new* store fails while the existing 58 do not. That buys the "every new store registers immediately" property the program asks for, without demanding 58 declarations in one slice. A row deleted because the store was declared must be removed from the baseline **in the same commit** — copy that error message verbatim in spirit from `compare_to_baseline()`.

**A new direct connect already fails.** `db-connect` is in `GATING_CATEGORIES` and uses symmetric difference, so a 31st row fails today. Add nothing for it. Say so in the prompt output rather than implying AD-1256 introduced it.

**Report-only, each with a promotion condition:**

| Reported | Why not gating | Promotion condition |
|---|---|---|
| Retention *sufficiency* | Nothing measures growth; `activation_tracker.db` prunes and is still ~986 MB, so "has a delete path" is not evidence | AD-1265/1266 land a size census that can compare declared policy to observed bytes |
| `backup` / `restore` disposition | AD-1265 (backup) and AD-1266 (restore) own these; the field ships, the semantics do not | AD-1266 restores a declared point-in-time unit |
| Migration progress: 30 db-connect debt rows remaining | Shrinking is opportunistic by #1302's own text; a shrink gate would force out-of-scope migrations | The count reaches a reviewed floor of approved adapters only |
| Stores declaring `ConnectionFactory` vs not (18 today) | Same reason | Same |

### D4 — Criticality is inert metadata in this slice. Nothing consumes it.

`required` / `optional` / `feature-gated` is **recorded and not enforced**. No boot path, no startup ordering, no degradation policy, and no error handling reads it. A store declared `required` boots in exactly the way it boots today; the byte-level behaviour of the vessel is unchanged by this slice.

This is a decision, not an omission. BF-756 (#1213) was reverted because moving three stores into a boot path silently made them boot-critical — measured as `DatabaseError: file is not a database` taking down a vessel that had only asked for agent-callable tools. If a *declaration* could change boot behaviour, then a metadata edit becomes a behaviour change and this AD reproduces BF-756's defect by construction. AD-1270a shipped observation-only for the same reason and recorded it: *"nothing reads a row to make a routing, permission, trust or startup decision."*

**Naming hazard — do not wire these together.** `src/probos/degradation/registry.py` already has `ServiceTier` (`ESSENTIAL` / `COGNITIVE` / `NON_ESSENTIAL`), `ServiceClassification` and `ServiceTierRegistry` (AD-459). That is a **load-shedding** tier — what to drop under stress — not boot criticality. They are different axes with a confusable vocabulary. Do not import it, do not map onto it, and note the distinction in the declaration model's docstring.

Promotion condition: a consumer arrives only when **AD-1270c2** owns lifecycle registrations and can act on criticality during startup unwind, in a separately reviewed slice with its own adversarial review.

---

## Build

### New files

| Path | Contents |
|---|---|
| `src/probos/storage/declarations.py` | `StoreDeclaration` frozen dataclass, `StoreCriticality` and `StoreRetention` enums. **Leaf module**: imports nothing from `probos`. |
| `src/probos/storage/registry.py` | `StoreRegistry` (collection only), `DECLARATION_MODULES`, `load_default_store_registry()` |
| `src/probos/<layer>/storage_declarations.py` | `STORE_DECLARATIONS: tuple[StoreDeclaration, ...]` — one module per owning layer, seeded with the stores named below |
| `scripts/check_store_registry.py` | The bidirectional checker |
| `docs/development/store-baseline.yaml` | Frozen reviewed undeclared-store rows |
| `tests/test_ad1256_store_registry.py` | Tests |

### `StoreDeclaration` fields

Required by `platform-maturity-program.md` § AD-1256: owner, roots/paths, criticality, lifecycle owner, retention policy, backup disposition, restore disposition, and reconstruction method where excluded.

```python
id: str                      # stable key, e.g. "tools.action-approvals"
title: str
owner_module: str            # dotted, AST-resolvable against src/probos/
owner_symbol: str            # class name
canonical_path: str          # the ONE spelling, e.g. "action_approvals.db"
criticality: StoreCriticality
lifecycle_owner: str         # dotted symbol that calls start()/stop(), or "unowned"
retention: StoreRetention
retention_note: str          # required when retention is UNBOUNDED
backup: str                  # "included" | "excluded" | "unknown"  (AD-1265 owns semantics)
restore: str                 # "point-in-time" | "reconstructed" | "unknown" (AD-1266)
reconstruction: str          # required when restore == "reconstructed"
notes: str = ""
```

`retention_note` and `reconstruction` are *conditionally* required. A blank one where the enum demands it is an error, not a warning — that is the whole mechanism by which "unbounded, but deliberately and in writing" is enforced.

### Idioms to copy exactly

**Declaration module shape** — [src/probos/tools/maturity_declarations.py](src/probos/tools/maturity_declarations.py) and [src/probos/infrastructure/maturity_declarations.py](src/probos/infrastructure/maturity_declarations.py). Data only; no import of the subsystem being declared.

**Registry shape** — [src/probos/maturity/registry.py](src/probos/maturity/registry.py). Explicit `DECLARATION_MODULES` tuple, **never** a glob or `pkgutil` walk (its docstring states why: globbing yields an empty registry from a wheel; walking imports the whole tree and its side effects). `register()` raises `ValueError` on duplicate id. No module-level singleton. `load_default_store_registry()` log-and-degrades on a broken declaration module, naming what is therefore missing.

**Model shape** — [src/probos/maturity/model.py](src/probos/maturity/model.py). `@dataclass(frozen=True, slots=True)`, `to_dict()` returning a JSON-safe mapping, `str`-valued `Enum`.

**Checker shape** — [scripts/check_architecture_principles.py](scripts/check_architecture_principles.py) and [scripts/check_seam_contracts.py](scripts/check_seam_contracts.py). Every one of these is load-bearing:

- File list from `git ls-files`, never a disk walk. (An untracked `src/probos/infrastructure/restore.py` exists in the working tree right now — another session's in-flight work. It is invisible to `git ls-files` and must stay that way. Do not touch it.)
- AST only, never regex over source text.
- **Accumulate all errors**, never return on the first. Each message names the exact row and the exact command that fixes it.
- Writes nothing under `--check`. The gate wrapper fails the run if preflight mutates the tree.
- `--update-baseline` regenerates rows with blank review fields that then fail `--check` until filled.
- State the detection bounds in the docstring, numbered, the way both existing checkers do.

**Store constructor shape**, for the "new stores must use it" documentation — [src/probos/tools/action_approvals.py](src/probos/tools/action_approvals.py): `ConnectionFactory` injection, `db_path: str = ""` cache-only, WAL + `busy_timeout=5000` + `synchronous=NORMAL`, module-level `_SCHEMA` constant.

### Seed set

Do not declare all 58. Seed **8–12** declarations covering every enum value at least once, chosen so each one is a real answer rather than filler:

- `activation_tracker` — the ~986 MB case. `retention: BOUNDED`, note recording that a 10 % `max_prune_fraction` cap ([activation_tracker.py](src/probos/cognitive/activation_tracker.py#L221)) demonstrably does not catch up. This store is the reason retention is a field.
- `ward_room` — has real retention (`retention_days` / `retention_days_endorsed` / `retention_days_captain`, [ward_room/threads.py](src/probos/ward_room/threads.py#L845)) and ad-hoc dated sidecar copies with no declared lifecycle.
- `chat_threads` and `workforce` — BF-826/#1290's two lock domains. Their notes must record that they are **separately locked on purpose**, so a future consolidation proposal meets a written reason.
- `audit_log` — `retention_days=90` at [security/audit_log.py](src/probos/security/audit_log.py#L28), and one of the inline-schema modules.
- At least one `UNBOUNDED` with a real `retention_note`, one `feature-gated`, and one `restore: reconstructed` with a stated `reconstruction`.

### Also in this commit

Do **not** edit `docs/development/architecture-baseline.yaml`. The row that an earlier revision of this prompt asked you to fix is already correct as committed — see the retraction in § 4. Leave all 30 rows alone.

### Wire into preflight

Add to `_preflight_specs()` in [scripts/run_test_gate.py](scripts/run_test_gate.py#L1079), **after** `architecture-fitness` and before `compile`:

```python
PhaseSpec("store-registry", [python, "-P", "scripts/check_store_registry.py", "--check"]),
```

`PhaseSpec` is real — [scripts/run_test_gate.py:115](scripts/run_test_gate.py#L115). `phantom-api-precheck.ps1` flags it as a phantom because it indexes `src/` only and this class lives under `scripts/`; that is a known false positive on this prompt, not a symbol to go looking for.

Add the currency test that runs `--check` in-process, mirroring how `tests/test_ad1270b_architecture_fitness.py` does it.

---

## Acceptance criteria

- `tests/test_ad1256_store_registry.py`: **45–60 tests**, sized against the shipped comparables (`test_ad1270a_capability_truth.py` 29, `test_ad1270b_seam_contracts.py` 51, `test_ad1270b_architecture_fitness.py` 55).
- **Every gating rule has a firing test AND a not-firing test.** A rule stuck permanently on is a broken checker that looks safe — this is the defect AD-1270f's review found in `uncontexted-test` and it must not recur. Include one benign-baseline test asserting the committed tree produces **zero** errors with every rule simultaneously off.
- A completeness test asserting the set of implemented rule names equals the documented set, so a rule cannot be added without documenting it.
- **Non-vacuity proven by injection, not asserted** — the AD-1270b D1 standard. Inject each of: a declaration naming a nonexistent `owner_symbol`; a declaration with blank `criticality`; `retention: UNBOUNDED` with an empty `retention_note`; two declarations claiming one `canonical_path`; a new `CREATE TABLE` module absent from both the declarations and the baseline; a baseline row whose module no longer exists. Each must be detected, then restored byte-identically.
- A test asserting `src/probos/storage/declarations.py` imports nothing from `probos`, and a parametrized test asserting each `storage_declarations.py` imports only that model — AST-scan the imports, copying [test_model_imports_nothing_from_probos](tests/test_ad1270a_capability_truth.py#L707) and [test_declaration_modules_import_only_the_maturity_model](tests/test_ad1270a_capability_truth.py#L723).
- A test asserting **no production module imports `probos.storage.registry`** — this slice adds no runtime consumer. `git grep` over `src/` must show hits only inside `src/probos/storage/` and the declaration modules.
- A test asserting the declaration model does not import or reference `probos.degradation` (D4's naming hazard).
- `scripts/check_store_registry.py --check` exits 0 on the committed tree; `--update-baseline` on the committed tree produces a byte-identical baseline.
- Full gate green through the canonical wrapper, and the receipt banked per the standing order.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Do not build

- **Do not merge or consolidate any databases.** SQLite's one-writer-per-file is *why* the partitioning exists. BF-826/#1290 depends on an error path escaping a failing resource by writing to a different file with a different lock; a single database makes that fix impossible.
- **Do not change the on-disk layout.** No file moves, no renames, no new directory. The two double-spelled paths (`directives.db` / `data/directives.db`) are resolved *in the declaration*, by recording one canonical spelling — not by moving a file.
- **Do not migrate any existing store's schema.** No `ALTER TABLE`, no new columns, no version bump.
- **Do not migrate the 30 db-connect rows.** Deleting even one requires editing a production store, which is out of scope. The only baseline edit permitted is the single `disposition` correction named above.
- **Do not build a service locator.** The registry holds declarations. It holds no connections, no live stores, no runtime state, and no module-level singleton. It never accepts a `ProbOSRuntime`.
- **Do not let a declaration change boot behaviour.** Nothing in `startup/`, `runtime.py`, or any store constructor may read `criticality`, `retention`, `backup`, or `restore` in this slice. If a declaration edit can alter what the vessel does at boot, the slice has reproduced BF-756 and must be redesigned.
- **Do not add a new connection abstraction, base class, mixin, or pool.** `ConnectionFactory` is the seam. See D1.
- **Do not wire into `degradation.ServiceTier`.**
- **Do not add a startup hook, an API route, a Doctor check, or a slash command.**
- **Do not use regex over source text for detection.** AST only — it is the program's own Do-Not-Build item.
- **Do not implement retention.** No reaper, no prune loop, no size enforcement. Declaration only.

---

## Risks the Builder must be warned about

1. **`RetentionPolicy` is already taken.** `src/probos/ontology/models.py:252` defines `RetentionPolicy`, exported from `probos.ontology` and asserted in `tests/test_public_apis.py:567`. It is knowledge-artifact retention, unrelated. Name yours `StoreRetention`. Verified by `git grep RetentionPolicy -- src/`.

2. **`ServiceTier` / `ServiceClassification` / `ServiceTierRegistry` are taken** by `degradation/registry.py` and mean load-shedding, not boot criticality. See D4.

3. **`StoreRegistry` / `StoreDeclaration` / `StoreCriticality` / `store_declarations` / `storage/registry.py` are free.** Verified: `git grep -n -I -- <name> -- src/ scripts/ tests/ docs/development/` returns **no hits** for each. `StoreDescriptor` appears once, in `platform-maturity-program.md:543`, as the program's requirement — it is a name you may take, but `StoreDeclaration` is more consistent with `CapabilityDeclaration`.

4. **The architecture-fitness baseline is symmetric and will bite you.** Any new `sqlite3.connect` or `aiosqlite.connect` you add — in a test fixture under `src/`, in a helper, anywhere `git ls-files` sees — fails the gate as a `NEW VIOLATION`. Your checker is under `scripts/`, which the architecture checker does not index, so it is safe there. Do not add one under `src/`.

5. **`disposition` does not gate.** `compare_to_baseline()` keys on `(category, key, callee)` and compares `count` and `triggers`. Changing `debt` → `approved` is a metadata correction and will not change the exit code — verify that by running `--check` before and after, and say so in the commit rather than implying you loosened a gate.

6. **Text-scanning for `CREATE TABLE` over-counts.** 58 modules match by raw text; `src/probos/config.py` is a false positive. Only an AST walk over string constants distinguishes them. Your baseline must be generated by the AST path, or you will freeze a false row and then have to explain it.

7. **The gate materializes `HEAD` into a fresh worktree.** A check satisfied by uncommitted work passes locally and fails in the gate. Commit before the broad gate. `scripts/check_architecture_principles.py` measures **11.9 s** cold in a gate worktree versus ~5 s warm locally — budget your checker from the cold figure.

8. **Do not touch `src/probos/infrastructure/restore.py`.** It is untracked, in-flight work from another session (AD-1266 territory). `git ls-files` cannot see it, so your checker will not either, which is correct. Leave it alone; do not `git add` it.

9. **A declaration must never import what it declares.** `maturity_declarations.py` modules import only `probos.maturity.model`. If a storage declaration module imports its store, the declaration becomes a construction and the leaf property dies — and importing 12 store modules at declaration-load time drags their side effects into every `--check`.

10. **`git grep`, not recall, before any absence claim in your build report.** Paste the command.
