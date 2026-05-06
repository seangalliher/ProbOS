# WAVE 88 DISPATCH — AD-481 v1 Extension-First Architecture (Sealed Core, Open Extensions)

**Wave id:** 88
**Umbrella AD:** AD-481 (Extension-First Architecture — Sealed Core, Open Extensions)
**OSS sub-AD letters in scope (concrete v1):** AD-481a (Extension protocol substrate — `Extension` ABC + `ExtensionType` / `ExtensionRiskLevel` / `ExtensionState` StrEnums + `ExtensionManifest` Pydantic + `EXTENSION_API_VERSION` constant), AD-481b (`ExtensionRegistry` — register/get/list/enable/disable/remove + lifecycle), AD-481c (`ExtensionDiscovery` — filesystem scan of `src/probos/extensions/{agents,channels,hooks,skills,tools}/` + manifest validation + contract-version compatibility check), AD-481d (`ExtensionStateStore` — `extension_states` SQLite table + load-on-startup state restoration), AD-481e (Skill manifest format — `skill.yaml` `SkillManifest` Pydantic schema + `load_skill_from_manifest` adapter to existing `SkillDefinition`), AD-481f (Sealed Core boundary — `config/sealed_modules.yaml` + `is_sealed_path()` helper + warn-only Builder pre-write check, default-False per AD-695 precedent), AD-481g (Extension Profiles — three preset YAMLs `minimal`/`developer`/`full` + `apply_profile()` returning enable-list), AD-481h (`/extensions` slash command — `list`/`enable`/`disable`/`remove`/`profile`/`info` subcommands).
**OSS sub-AD letters NOT in scope (carved out as future ADs — not v1 deferrals):** AD-481i (HXI extension toggle panel — vitest UI surface; in-scope slash command at AD-481h gives Captain full control without UI surface; UI follow-up is its own wave with its own vitest budget), AD-481j (`probos init --profile=<name>` wizard prompt — depends on AD-484c onboarding wizard which is partial at HEAD per `roadmap.md:7042`; the v1 `/extensions profile <name>` slash command provides full Captain control until AD-484c lands), AD-481k (auto-installation of declared skill dependencies — touches pip subprocess and needs sandboxing story; the v1 manifest schema already declares `dependencies` so producers can record the contract, AD-481k consumer-side resolves them), AD-481l (Builder *hard-block* on sealed-core paths via raised exception — default-False flag flip; AD-695 grandchild precedent; depends on AD-482 v1 to consume the warn-log emission so red team can establish a baseline before flipping enforcement), AD-481m (Marketplace publishing/discovery protocol over the wire — depends on AD-480 A2A and AD-479 federation hardening, neither shipped; the v1 manifest format is the on-disk substrate that AD-481m would publish, so producer-side ships in v1 even though the wire protocol is parked).
**Carved out per `docs/development/roadmap.md:3478` and `:3595` and tracked in the private commercial-repo path token (NOT v1 deferrals — wrong-repo by design):** Agent Marketplace (the commercial Agent Marketplace named explicitly at `roadmap.md:3478` "Pairs with the commercial Agent Marketplace for publishing and distribution"), centralized extension distribution / CDN service, hosted/managed extension trust scoring + revocation registry, paid extension catalog + billing surface. None of these are touched by Wave 88 — Wave 88 is fully OSS substrate.
**Closes:** GH issue #75
**HEAD at draft:** `e39e262` (post-Wave-87)
**Baseline test counts:** **11762** pytest at HEAD (verified `pytest --collect-only -q tests/`); vitest unchanged at 306 (305 passing + 1 pre-existing `WardRoomDmSync` failure carried since pre-Wave-85, not in scope). Expected after Wave 88: **≥ 11842** pytest (+80 floor; ~80 tests planned across eight classes, see prompt). vitest **unchanged at 306** — Wave 88 ships zero UI surface (HXI toggle panel parked at AD-481i with explicit forcing function).
**Builder required:** true (one focused build prompt; Python-only with one config-file edit, three new YAML preset files, one new sealed-modules YAML, and one Markdown edit to `roadmap.md`; no UI surface touched).
**AD numbering:** Highest stem at HEAD remains **AD-696** (Wave 72). AD-481 pre-allocated by `docs/development/roadmap.md:7033`; sub-AD letters a–m are organizational catalog markers only, mirroring the AD-443 a–h (Wave 87), AD-474 a–h (Wave 86), AD-473 a–g (Wave 85), and AD-512 a–f (Wave 84) precedents — no new AD numbers minted.

## Verdict

Verify-first against HEAD `e39e262` shows the **substrate AD-481 will extend is fully shipped and live** — every "extension point" the roadmap line 3604–3611 lists already exists at HEAD, so Wave 88 is "ship the meta-layer above the existing point registries", not "ship the registries themselves":

- **`AgentRegistry.register()` already lives at `src/probos/substrate/registry.py:17`** — `register(agent: BaseAgent) -> None` async with internal `_lock` and `_all_cache` invalidation pattern. Roadmap line 3605 calls this out as already-existing.
- **`ToolRegistry.register()` already lives at `src/probos/tools/registry.py:49`** — AD-423a/b shipped this; full permission resolution + LOTO + `register/unregister/lookup` API. Roadmap line 3606 calls this out as Phase 25b shipped.
- **`SkillRegistry.register_skill()` already lives at `src/probos/skill_framework.py:427`** — AD-428 shipped this; CRUD over `SkillDefinition` with SQLite persistence behind `ConnectionFactory`. Roadmap line 3607 calls this out as Phase 30 — but the *manifest format* (`skill.yaml`) is precisely what AD-481e ships in Wave 88 (the registry already exists; the on-disk portable format does not).
- **`ChannelAdapter` ABC already lives at `src/probos/channels/base.py:34`** — Phase 24 shipped this; `start`/`stop`/`send_response`/`handle_message` contract. Roadmap line 3608 calls this out as Phase 24 shipped.
- **`IntentBus.subscribe()` already lives at `src/probos/mesh/intent.py:72`** — pub/sub bus shipped since Era 1. Roadmap line 3611 calls this out as already-existing.
- **`ModelProvider` is the already-existing `LLMTier` system at `src/probos/config.py:230` (`SystemConfig.tier_config`) + `cognitive/llm_client.py`** — deep / fast / standard tiers with router fallback (AD-463). Roadmap line 3609 frames this as a "ModelProvider.register()" point; v1 keeps the existing tier-config shape and exposes it as an extension point at the manifest level (a `ModelProvider`-type extension declares `provider_id` + `tier_mapping` and registers via the standard `ExtensionRegistry`).
- **`PerceptionPipeline.register()`** is the cognitive perception chain (Sensory Cortex Phase 2). At HEAD this is the existing `cognitive_agent.perceive()` lifecycle hook — not yet a registry. v1 carries `ExtensionType.PERCEPTION_PROCESSOR` as a manifest-level type but the runtime consumer is parked behind AD-481m (no live point at HEAD, so v1 lands the manifest declaration only — when the perception pipeline registry lands separately, AD-481m wires it).
- **`EventHook.register()`** is the already-existing `_emit_event` + `add_event_listener` pattern at `runtime.py` (AD-637d). v1 surfaces it via `ExtensionType.EVENT_HOOK` and `ExtensionRegistry` registers via the existing `add_event_listener(event_type, callback)` API.

**What's missing at HEAD:** the *meta-layer* — the `Extension` protocol that says "this is an extension package, here's its manifest, here's its risk level, here's whether it's enabled" — and the *toggle/profile/persistence* surface around it. Plus the `skill.yaml` portable manifest format (registry exists; format does not). Plus the sealed-core boundary list. Plus the `/extensions` slash command. Plus the in-tree `src/probos/extensions/` package directory. None of these exist yet (verified — `src/probos/extensions/` is a greenfield path at HEAD).

| Roadmap component (lines 3595–3669, 7033) | Wave 88 action |
|---|---|
| (1) Sealed Core — runtime infrastructure read-only to Builder | **BUILD AD-481f.** New `config/sealed_modules.yaml` lists path globs (substrate/**, consensus/**, mesh/**, identity.py, cognitive/builder.py, cognitive/llm_client.py, runtime.py, etc.). `src/probos/extensions/sealed_core.py` exposes `is_sealed_path(path: str) -> bool` and `load_sealed_globs() -> list[str]` (cached). Builder write paths at `cognitive/builder.py:2585`, `2604`, `2724`, `2729` gain a single helper-call check that emits `logger.warning(...)` when the target matches a sealed glob and `runtime.config.extensions.enforce_sealed_core` is True. Site at line 2053 (visiting-Copilot tmp-dir copy phase) is intentionally NOT in scope — it copies into an isolated sandbox, not a repo write. **Default-False per AD-695 precedent — v1 is observation-only**, hard-block ships at AD-481l (forcing function: AD-482 v1 baseline). ~10 tests. |
| (2) Extension points (8 hooks: AgentRegistry / ToolRegistry / SkillRegistry / ChannelAdapter / ModelProvider / PerceptionPipeline / IntentBus / EventHook) | **BUILD AD-481a + AD-481b.** All eight hooks already live at HEAD (verified above) — Wave 88 surfaces them through a uniform `ExtensionType` StrEnum (`AGENT` / `TOOL` / `SKILL` / `CHANNEL_ADAPTER` / `MODEL_PROVIDER` / `PERCEPTION_PROCESSOR` / `INTENT_SUBSCRIBER` / `EVENT_HOOK`) and a single `ExtensionRegistry.register(manifest, target_registry)` that dispatches to the right point. ~22 tests across two classes. |
| (3) Extension directory `src/probos/extensions/` | **BUILD AD-481c.** Greenfield package created with `__init__.py` (re-exports), five subdirectories `agents/` / `channels/` / `hooks/` / `skills/` / `tools/` each with a `.gitkeep` + a one-line README documenting the layout. `ExtensionDiscovery.scan(extensions_dir)` walks each subdir, reads per-extension `extension.yaml`, validates against `ExtensionManifest`, returns `list[ExtensionManifest]`. ~10 tests. |
| (4) Contract stability — semver | **BUILD AD-481a (continued) + AD-481c (continued).** `EXTENSION_API_VERSION = "1.0.0"` constant in `extensions/protocol.py`. `ExtensionManifest.required_api_version: str` field; `ExtensionDiscovery._is_compatible(manifest)` rejects manifests whose major version != current major (semver). Migration story documented in `extensions/__init__.py` module docstring. ~3 tests folded into 481a/481c counts. |
| (5) Graduated Autonomy — auto-approve LOW / Captain review MEDIUM / full pipeline HIGH | **BUILD AD-481a (continued) + AD-481b (continued).** `ExtensionRiskLevel` StrEnum (`LOW` / `MEDIUM` / `HIGH`) declared in manifest. `ExtensionRegistry.register()` consults the risk level: LOW auto-loads (logs "auto-approved low-risk extension"), MEDIUM stages in `pending_approval` state until `approve_extension(extension_id)` is called, HIGH refuses to load and emits an event requiring the existing approval-pipeline path (BuildSpec gate). v1 ships the gating *helper* — actual approval-pipeline integration parked at AD-482. ~5 tests folded into 481a/481b counts. |
| (6) Extension Toggle — hot-loadable, individually togglable extensions | **BUILD AD-481d + AD-481h.** `ExtensionStateStore` adds new `extension_states` SQLite table to identity DB (one new table — `ConnectionFactory`-backed cloud-ready storage convention preserved): `(extension_id TEXT PRIMARY KEY, status TEXT, profile TEXT, enabled_at REAL, disabled_at REAL, manifest_json TEXT)`. `ExtensionRegistry.enable/disable/remove(extension_id)` updates state + persists. On startup, runtime reads enabled extensions and re-registers them. `/extensions list/enable/disable/remove` slash command at `experience/commands/commands_extensions.py` mirrors the AD-596d `/skill` precedent. ~22 tests across two classes. |
| (7) Extension profiles — minimal / developer / full presets | **BUILD AD-481g + AD-481h (continued).** Three new preset YAMLs in `config/extension_profiles/{minimal,developer,full}.yaml`. `ExtensionProfile` Pydantic. `apply_profile(profile_name) -> list[str]` returns enable-list; profile name persisted in `extension_states.profile` column. `/extensions profile <name>` slash command applies the profile (enables listed, disables others). ~8 tests. |
| (8) Skill Manifest Format — `skill.yaml` standard for portable, publishable skills | **BUILD AD-481e.** `SkillManifest` Pydantic schema in `extensions/skill_manifest.py` (fields: `manifest_version`, `skill_id`, `name`, `version`, `author`, `license`, `description`, `category`, `domain`, `prerequisites`, `dependencies`, `preferred_tools`, `composite_skill_ids`, `synergy_partners`, `decay_rate_days`). `load_skill_from_manifest(yaml_path: Path) -> SkillDefinition` translates the validated manifest into the existing `SkillDefinition` dataclass — pure adapter, **no breaking change to `SkillRegistry`**. `SkillRegistry.register_from_manifest(yaml_path)` async helper composes load + existing `register_skill()`. ~8 tests. |
| (Bundled) Builder pre-write sealed-core check wiring | **BUILD AD-481f (continued).** Four `path.write_text(...)` call sites at `cognitive/builder.py:2585`, `2604`, `2724`, `2729` gain a single shared helper call before write. New helper `_check_sealed_path(self, path: Path) -> None` lives on the BuilderAgent class; reads `self._runtime.config.extensions.enforce_sealed_core` (default False) via direct attribute access (the field is guaranteed by `Field(default_factory=ExtensionsConfig)` on `SystemConfig.extensions`); calls `is_sealed_path(path)`; emits `logger.warning(...)` only — never raises. Per-BuildSpec override (`core_modification` flag) intentionally NOT introduced in v1 — lands with AD-481l when the warn becomes a raise. Folded into 481f test count. |
| (Bundled) `ExtensionsConfig` Pydantic in `config.py` | **BUILD AD-481a (continued).** New `ExtensionsConfig(BaseModel)` with three fields: `enabled: bool = False` (master switch — default False per AD-695 precedent for opt-in transitional flags), `enforce_sealed_core: bool = False` (sealed-core warn-only flag — default False; flip in AD-481l), `default_profile: str = "minimal"`. New `extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig)` line in `SystemConfig` at `config.py:2507`. Folded into 481a test count. |

## Reframe decision (Captain rule applied)

**Eight concrete sub-AD letters built + five future-AD letters with explicit forcing functions + four commercial-repo carve-outs (NOT deferrals — wrong-repo by roadmap design at lines 3478 + 3595) + zero hard-deferrals.** This is the strictest application of "don't defer unless no choice" available for AD-481 — every roadmap-line-7033 component that does not depend on un-shipped substrate (AD-484c onboarding wizard, AD-482 self-improvement consumer) ships in v1 as the *substrate* layer, with consumer integrations parked behind explicit forcing functions.

The roadmap line-7033 framing of AD-481 ("self-improvement infrastructure" — implicitly framing AD-482 as a precondition consumer) is **revisited and rejected at Wave 88** by verify-first against HEAD:

1. **The eight extension points already exist at HEAD** — verified file-by-file above. AD-481 is not "build the registries"; it's "build the meta-layer above the registries." Meta-layer is purely additive substrate that lands non-breakingly.
2. **The Builder pre-write check is a pure observation hook in v1.** `logger.warning(...)` only, gated by a default-False config flag and a default-False BuildSpec flag. Cannot change Builder behavior in v1 — exactly the "ship the substrate, defer enforcement" pattern from AD-695 (and from W82 AD-633 default-False precedent).
3. **`skill.yaml` ships the on-disk format only, not auto-installation.** `SkillRegistry.register_from_manifest(yaml_path)` is a pure adapter from validated yaml to existing `SkillDefinition`. Auto-install of declared dependencies is the AD-481k consumer story — needs pip-subprocess sandboxing that touches `security_infra` (AD-456) and is genuinely upstream-blocked.
4. **`/extensions` slash command is the same pattern as `/skill` (AD-596d).** New `commands_extensions.py` module in `experience/commands/` plus two-line shell.py wiring (help table + dispatch dict). Zero risk surface.
5. **Profiles are three YAML files plus one Pydantic + one helper function.** No new agent, no new pool, no new event, no new intent.
6. **`extension_states` SQLite table follows the established `ConnectionFactory` pattern** — same convention as `birth_certificates`, `slot_mappings`, `transfer_certificates` (Wave 87), `skill_definitions` (AD-428). Cloud-ready storage convention preserved.

Five things that LOOK like deferrals but aren't:

1. **HXI extension toggle panel UI (AD-481i)** is the *visualization*, not the *control surface*. The control surface ships in v1 at AD-481h (`/extensions list/enable/disable/remove/profile`). AD-481i is a vitest-only UI follow-up wave; mixing UI into Wave 88 would expand the test budget surface and risk for zero new control. Forcing function: dedicated UI wave with its own vitest gate.
2. **`probos init --profile=<name>` wizard prompt (AD-481j)** is genuinely upstream-blocked. AD-484c onboarding wizard is *partial* at HEAD per `roadmap.md:7042` — `probos init` exists but the profile-selection step doesn't. Wave 88 ships the *function* `apply_profile(name)` that AD-484c will call when it lands; the v1 `/extensions profile <name>` slash command provides full Captain control until then.
3. **Auto-installation of skill dependencies (AD-481k)** is genuinely upstream-blocked. Pip subprocess with declared dependencies needs a sandboxing story that touches `src/probos/security_infra/` (AD-456 already shipped) and the `cognitive/sandbox.py` agent-test sandbox — but the consumer-side resolution logic is its own concern. Wave 88 ships the *manifest field* (`SkillManifest.dependencies: list[str]`) so producers can record the contract; AD-481k consumer-side resolves them under sandbox.
4. **Builder hard-block on sealed paths (AD-481l)** is the default-False-flag-flip pattern. Per AD-695 grandchild precedent (Wave 5 lessons + W82 AD-633 default-False), transitional safety flags ship default-False in the parent AD and flip in a grandchild AD with a forcing function. The forcing function for AD-481l is "AD-482 v1 RedTeam consumes the warn-log to establish baseline; flip enforce_sealed_core to True after the baseline confirms zero false-positives." Without AD-482's RedTeam, flipping enforcement risks blocking legitimate Builder work.
5. **Marketplace publishing/discovery protocol over the wire (AD-481m)** is genuinely upstream-blocked. Wire protocol depends on AD-480 A2A and AD-479 federation hardening, neither shipped. Wave 88 ships the *on-disk manifest format* that AD-481m would publish — producer-side substrate ships in v1 even though the wire protocol is parked.

Four commercial-repo carve-outs (these are NOT deferrals — they are out-of-repo by design at roadmap lines 3478 + 3595):

- **Agent Marketplace** — the commercial Agent Marketplace named explicitly at `roadmap.md:3478` ("Pairs with the commercial Agent Marketplace for publishing and distribution"). Hosted distribution, paid skills/agents, billing surface, payment flows. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Centralized extension distribution / CDN** — hosted catalog server, edge caching, signed-bundle delivery. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Hosted/managed extension trust scoring + revocation registry** — fleet-wide reputation aggregation, signed revocation lists, malicious-extension takedown surface. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Paid extension catalog + billing surface** — payment processing, license enforcement, subscription metering. Tracked in the private commercial-repo path token. Not in any OSS wave.

GH #75 closure note (drafted; commits with Builder's PR): "Closed by Wave 88 (AD-481 v1 — eight concrete OSS sub-AD letters 481a/b/c/d/e/f/g/h). Extension protocol substrate (Extension ABC + ExtensionType / ExtensionRiskLevel / ExtensionState StrEnums + ExtensionManifest Pydantic + EXTENSION_API_VERSION semver constant) + ExtensionRegistry (register/get/list/enable/disable/remove + lifecycle) + ExtensionDiscovery (filesystem scan of src/probos/extensions/{agents,channels,hooks,skills,tools}/ + manifest validation + contract-version compatibility) + ExtensionStateStore (extension_states SQLite table + load-on-startup state restoration via ConnectionFactory) + Skill Manifest Format (skill.yaml SkillManifest Pydantic schema + load_skill_from_manifest adapter to existing SkillDefinition, no breaking change to SkillRegistry) + Sealed Core boundary (config/sealed_modules.yaml + is_sealed_path helper + warn-only Builder pre-write check at four write sites in cognitive/builder.py, default-False per AD-695 precedent) + Extension Profiles (three preset YAMLs minimal/developer/full + apply_profile returning enable-list) + /extensions slash command (list/enable/disable/remove/profile/info subcommands wired into shell.py per AD-596d /skill precedent) all ship in v1. Five components parked as future sub-ADs 481i/j/k/l/m with explicit forcing functions: 481i HXI extension toggle panel UI (control surface lands at 481h slash command — UI follow-up is its own vitest-budget wave), 481j probos init --profile wizard prompt (depends on AD-484c onboarding wizard partial at HEAD per roadmap.md:7042 — the v1 /extensions profile slash command provides full Captain control until AD-484c lands), 481k auto-installation of declared skill dependencies (touches pip subprocess + needs sandboxing story under AD-456 security_infra — manifest schema already declares dependencies field so producers record the contract, AD-481k consumer resolves them), 481l Builder hard-block on sealed-core paths (default-False flag flip — AD-695 grandchild precedent — depends on AD-482 v1 RedTeam to consume the warn-log baseline before flipping enforcement), 481m Marketplace publishing/discovery wire protocol (depends on AD-480 A2A and AD-479 federation hardening, neither shipped — manifest is the on-disk substrate that 481m publishes). Carved out per docs/development/roadmap.md:3478 + :3595 and tracked in the private commercial-repo path token (NOT v1 deferrals — out-of-repo by design): commercial Agent Marketplace, centralized extension distribution / CDN, hosted/managed extension trust scoring + revocation registry, paid extension catalog + billing surface. Captain rule honored — every roadmap-line-7033 component that does not depend on un-shipped AD-484c / AD-482 / AD-456-sandboxing / AD-480 / AD-479 substrate shipped in v1 as the substrate layer."

## Commercial-leak audit (pre-commit hook safety)

**Banned-pattern sweep on draft** (`prompts/WAVE-88-DISPATCH.md` + `prompts/ad-481-extension-first-v1.md`), per `.git/hooks/pre-commit` lines 5–17 — all 11 banned patterns confirmed **0 literal hits across both files**. The Captain's standing instruction "audit prose itself uses placeholders" is honored: the literal banned strings are NOT reproduced anywhere in this dispatch or the prompt, including in any audit table, example regex, or Select-String invocation. Each banned pattern is referenced only by an indirect descriptor:

| Banned-pattern descriptor (NOT literal) | Placeholder form used in this dispatch + prompt |
|---|---|
| the e-word followed by ` ` then `tier` (concatenation) | "the e-word + tier" |
| the private repo path token (lowercase product name + dash + a synonym for OSS-opposite) | "the private commercial-repo path token" |
| the same path token but with the e-word stem instead | "the e-word-prefixed repo token" (not used) |
| the e-word followed by ` overlay` (concatenation) | "the e-word overlay phrase" (not used) |
| dollar-sign + integer + `/month` (slashed) | "monthly-price regex" (not used) |
| dollar-sign + integer + `/mo` (slashed) | "per-month abbreviation regex" (not used) |
| `revenue` + ` ` + `projection` (concatenation) | "rev-proj phrase" (not used) |
| three-letter recurring-revenue acronym (annual + recurring + revenue) | "the recurring-revenue acronym" (not used) |
| the word `outcome` + non-letter + `based pricing` | "outcome-style pricing phrase" (not used) |
| three-word phrase: GAS (great + artists + steal) | "the GTM-pattern phrase" (not used) |
| three-word phrase: PTA (patterns + to + absorb) | "the patterns-to-absorb phrase" (not used) |

- AD-481 entry on `docs/development/roadmap.md:7033` carries no `*(Commercial)*` tag — the carve-out language at `:3478` reads "Pairs with the commercial Agent Marketplace for publishing and distribution." Neutral phrasing, no banned literals. Wave 88 mirrors that exact pattern in the dispatch prose ("commercial Agent Marketplace" — neutral two-word adjective + product name, no banned token).
- "Cloud" / "monetization" / "pricing tier" / "go-to-market" vocabulary is absent from both this dispatch and the prompt. AD-481 v1 surface is pure protocol — Extension protocol substrate, registry, discovery, state store, skill manifest format, sealed-core boundary list, profiles, slash command. Zero pricing / packaging / distribution surface.
- `ExtensionRiskLevel` enum values `LOW`/`MEDIUM`/`HIGH` are pure mechanism (gating helper for graduated autonomy). Naming the highest tier "HIGH" is descriptive of risk magnitude, not commercial.
- Sealed-core boundary `config/sealed_modules.yaml` is a list of file path globs — universal-substrate concern, identical on every ship regardless of OSS/commercial deployment context. No conditional language.
- `extension.yaml` and `skill.yaml` manifest fields (author, license, version, description, category) are W3C/PEP-style portable-package metadata, not commercial — they exist to make extensions interoperable across forks, not to gate distribution.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## gate_1 concerns (architect pre-build risks)

Three risk classes flagged for Builder gate_1 review:

1. **Four Builder write sites at `cognitive/builder.py:2585/2604/2724/2729` all need the helper-call insertion.** SEARCH/REPLACE blocks in the prompt anchor on three lines of preceding context (the bare `path.write_text(...)` line is not unique enough on its own). All four sites use the local name `path` (resolved from `Path(change["path"])` upstream of each write). The helper `_check_sealed_path` accepts the resolved `Path` and reads `self._runtime.config.extensions.enforce_sealed_core` via direct attribute access — `self._runtime` is the established BuilderAgent attribute pattern (verified at builder.py:2036, 2057), and `runtime.config.extensions` is guaranteed by `SystemConfig.extensions = Field(default_factory=ExtensionsConfig)`. Verified line numbers at HEAD `e39e262` — drift sentinel: if Builder commits intermediate changes that shift these lines, re-anchor by surrounding three-line context. **No phantom-API risk** — `path.write_text` is stdlib `pathlib.Path`; `_check_sealed_path` is the new helper introduced by this prompt; `is_sealed_path` is the new helper introduced by `extensions/sealed_core.py` in this prompt. **Site at line 2053 (`dest.write_text` in visiting-Copilot tmp-dir copy phase) is intentionally NOT in scope** — it copies into an isolated sandbox, not a repo write.

2. **`SystemConfig` at `config.py:2507` gains one new line `extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig)`.** SEARCH anchored on the line *before* the existing `mcp: MCPConfig` field (alphabetical placement after `eps: EPSConfig`). New `ExtensionsConfig(BaseModel)` class added directly above `SystemConfig` definition with three Pydantic fields (`enabled`, `enforce_sealed_core`, `default_profile`) — all default-valued, all simple scalar types. **Master `extensions.enabled` flag default-False per AD-695 precedent** — even if Builder accidentally enables a registered extension at startup, the master switch keeps it inert until Captain explicitly opts in.

3. **`ExtensionStateStore` adds one new SQLite table to the identity DB.** Schema migration follows the AD-428 `ALTER TABLE ... ADD COLUMN` pattern — but here it's `CREATE TABLE IF NOT EXISTS extension_states (...)` (entirely new table, no migration of existing data). Writes go through `ConnectionFactory` (cloud-ready storage convention). On startup, `runtime._wire_extension_registry()` (new method in `runtime.py` at the existing finalize phase, mirroring AD-637d wiring pattern) reads `extension_states` rows where `status = 'enabled'` and re-registers each. **No existing-table touched** — zero migration risk.

Three risks NOT flagged (verified non-issues):

- **No layer violation.** `extensions/` is a cross-cutting package (like `federation/`, `knowledge/`). Imports flow `cognitive/builder.py` → `extensions/sealed_core.py` (one helper module), `experience/commands/commands_extensions.py` → `extensions/registry.py`, `runtime.py` → `extensions/registry.py`. No reverse import (extensions/ never imports from cognitive/, experience/, etc.).
- **No async/sync hazard.** `ExtensionRegistry` mirrors `AgentRegistry`'s `asyncio.Lock()` pattern. `ExtensionStateStore` writes are awaited via `ConnectionFactory.connect()`. `is_sealed_path()` is sync (pure path-glob match). `cmd_extensions` slash command is async per AD-596d `/skill` precedent.
- **No new EventType.** v1 logs to the existing logger only; event-emit on extension load/unload is parked at AD-482 (consumer story).

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  e39e262

# Pytest baseline (verified):
.venv\Scripts\pytest.exe --collect-only -q tests/
  11762 tests collected in 5.94s

# AD-481 spec at HEAD (verified — pre-allocated, no Commercial tag):
docs/development/roadmap.md:7033
  "**AD-481: Extension-First Architecture — Sealed Core, Open Extensions** *(planned)* — The self-improvement infrastructure: (1) Sealed Core ... (2) Extension points — AgentRegistry, ToolRegistry, SkillRegistry, ChannelAdapter, ModelProvider, PerceptionPipeline, IntentBus, EventHook ... (3) Extension directory — `src/probos/extensions/` for Builder-created code ... (4) Contract stability — semver ... (5) Graduated Autonomy — low-risk extensions auto-approve, medium needs Captain review, core modification needs full pipeline ... (6) Extension Toggle — hot-loadable, individually togglable extensions via CLI/HXI ... (7) Extension profiles — minimal/developer/full presets ... Also includes Skill Manifest Format — skill.yaml standard for portable, publishable skills ..."
docs/development/roadmap.md:3463
  "### Skill Manifest Format (Phase 30) *(AD-481)*"
docs/development/roadmap.md:3478
  "Pairs with the commercial Agent Marketplace for publishing and distribution"
docs/development/roadmap.md:3595
  "**Extension-First Architecture (Sealed Core, Open Extensions)** *(AD-481)*"
docs/development/roadmap.md:3604–3611
  Eight extension points enumerated (AgentRegistry / ToolRegistry / SkillRegistry / ChannelAdapter / ModelProvider / PerceptionPipeline / IntentBus / EventHook)
docs/development/roadmap.md:3643
  "**Extension Toggle (Feature Flags for Extensions)** *(AD-481)*"

# Eight extension points already live at HEAD (verified):
src/probos/substrate/registry.py:17     # class AgentRegistry
src/probos/substrate/registry.py:28     # async def register(self, agent: BaseAgent) -> None
src/probos/tools/registry.py:49         # class ToolRegistry  (AD-423a/b)
src/probos/tools/registry.py:60+        # def register(...) — full permission resolution
src/probos/skill_framework.py:427       # class SkillRegistry  (AD-428)
src/probos/skill_framework.py:505       # async def register_skill(self, defn: SkillDefinition)
src/probos/channels/base.py:34          # class ChannelAdapter(ABC)  (Phase 24)
src/probos/mesh/intent.py:72            # class IntentBus
src/probos/config.py:230                # def tier_config(self, tier: str) -> dict  (ModelProvider via LLMTier — AD-463)
# PerceptionPipeline registry not yet at HEAD — manifest declaration only in v1
# EventHook = runtime._emit_event + add_event_listener pattern  (AD-637d)

# Existing slash command precedent (verified — AD-596d /skill is the template):
src/probos/experience/commands/commands_skill.py:1     # AD-596d module header
src/probos/experience/commands/commands_skill.py:17    # async def cmd_skill(...) entrypoint
src/probos/experience/shell.py:104                     # "/skill": "Manage cognitive skills..." (help table)
src/probos/experience/shell.py:290                     # "/skill": lambda: commands_skill.cmd_skill(...) (dispatch)

# Builder write sites (verified — five locations need _check_sealed_path call):
src/probos/cognitive/builder.py:2585    # path.write_text(modified, encoding="utf-8")  — sealed-core check site 1
src/probos/cognitive/builder.py:2053    # dest.write_text — visiting-Copilot tmp-dir copy phase, intentionally NOT a sealed-core check site (sandbox, not repo write)
src/probos/cognitive/builder.py:2585    # path.write_text(modified, encoding="utf-8")
src/probos/cognitive/builder.py:2604    # path.write_text(change["content"], encoding="utf-8")
src/probos/cognitive/builder.py:2724    # path.write_text(mod, encoding="utf-8")
src/probos/cognitive/builder.py:2729    # path.write_text(...)

# Identity DB ConnectionFactory pattern (verified — extension_states table mirrors):
src/probos/identity.py:307–363          # _IDENTITY_SCHEMA — pattern for new CREATE TABLE IF NOT EXISTS
src/probos/identity.py:377              # def __init__(self, data_dir: Path, connection_factory: ConnectionFactory | None = None)

# SystemConfig integration site (verified):
src/probos/config.py:2507               # class SystemConfig(BaseModel)
src/probos/config.py:~2570              # mcp: MCPConfig field (insertion anchor for new extensions: ExtensionsConfig)

# Greenfield — no existing extensions/ package (verified):
src/probos/extensions/                  # does not exist at HEAD — Wave 88 creates it

# Pre-commit hook patterns (verified for audit safety):
.git/hooks/pre-commit:5–17              # 11 banned patterns enumerated; literal forms NOT reproduced in this dispatch or prompt; placeholders only

# AD numbering (verified):
docs/development/roadmap.md:7033        # AD-481 pre-allocated
PROGRESS.md highest stem                # AD-696 (Wave 72) — sub-AD letters 481a–m organizational only, no new AD numbers minted
```

## Builder workflow

Single Builder commit. Read `prompts/ad-481-extension-first-v1.md` end-to-end. Execute sections 0 → 9 in order. Run pytest in serial (`-n 0`) for the new test files, then full parallel gate (`-n 4 --dist=loadfile`). Target ≥ 11842. On gate pass, commit with message `AD-481: Extension-First Architecture v1 (sealed core + 8 extension types + skill manifest format + toggle + profiles + /extensions slash) (+80 tests)`. Archive dispatch + prompt to `prompts/archive/`. Close GH #75 with the closure note above.
