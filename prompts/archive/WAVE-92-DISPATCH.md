# WAVE 92 DISPATCH — AD-607 v1 Memory Security Framework (extraction & poisoning defense across retrieval / response / privacy layers)

## Wave summary

**Umbrella AD:** AD-607 (Memory Security Framework — three defense layers cataloged in the "AI Meets Brain" survey Section 8 + OWASP LLM Top 10 prompt-injection / data-poisoning, indexed at `docs/development/roadmap.md:5266`–`:5278` + `decisions-era-4-evolution.md:4005`–`:4018`)

**Concrete v1 sub-AD letters built (ten):**

AD-607a (`validate_recall_result(episode, query, anchor_query) -> RecallValidationResult` — new module `src/probos/cognitive/memory_security.py`; observational anomaly gate called from `EpisodicMemory.recall()` at `episodic.py:1508` + `recall_by_anchor_scored()` at `:1610` + `recall_by_anchor()` at `:2584` + `OracleService._query_episodic()` at `oracle_service.py:541`; emits new EventType `MEMORY_RECALL_ANOMALY` per anomalous result; `MemorySecurityConfig.enforce_recall: bool = False` opt-in drops anomalous episodes — default-False per AD-695 + W82 + W88 + W91 default-False precedent),

AD-607b (Provenance integrity — `validate_provenance(episode) -> ProvenanceResult` checks `agent_ids` non-empty, `source` value is in known `MemorySource` enum, `correlation_id` non-empty when `source="direct"`, no slot-id leakage past BF-103 sovereign migration; called from `validate_recall_result` and from `FederationRecallAgent.act()` ingest path at `federation_recall_agent.py:23`; emits `MEMORY_PROVENANCE_GAP`; `enforce_provenance: bool = False` opt-in rejects provenance-broken episodes at recall time),

AD-607c (Content-anchor mismatch detection — `score_anchor_mismatch(episode, anchor_query) -> float` reuses the AD-567c `anchor_dimension_weights` config at `config.py:642` inverted as anomaly signal; mismatch crossing `MemorySecurityConfig.anchor_mismatch_threshold: float = 0.7` flags the episode; observational v1 — emits `MEMORY_ANCHOR_MISMATCH`; consumed by `validate_recall_result` aggregator),

AD-607d (Response-based leakage guard — `check_memory_leakage(response, recalled_episodes, caller_sovereign_id) -> LeakageResult` extends the AD-589 IntrospectiveFaithfulness pipeline at `cognitive_agent.py` post-decision block; flags responses whose claimed-text overlap with episodes outside the caller's `agent_ids` set or above the caller's classification level; new EventType `MEMORY_LEAK_SUSPECTED`; observational v1 — log + episode metadata only, no response mutation),

AD-607e (Cross-shard access control on Oracle — new `MemoryAccessPolicy` enum (`PERMISSIVE` / `OWN_SHARD_ONLY` / `OWN_SHARD_PLUS_PUBLIC`) on `OracleService.query()` at `oracle_service.py:268` via new `caller_sovereign_id: str = ""` + `access_policy: MemoryAccessPolicy = PERMISSIVE` parameters; default `PERMISSIVE` preserves the AD-462c cross-shard recall behavior verbatim; `OWN_SHARD_ONLY` filters episodes whose `agent_ids` does not include caller; `OWN_SHARD_PLUS_PUBLIC` adds episodes with classification `ship`/`fleet` — wired through `MemoryConfig.access_policy` + `MemoryConfig.access_policy_default_caller_required: bool = False`),

AD-607f (Federated-recall inbound sanitization — `FederationRecallAgent.act()` at `federation_recall_agent.py:60` extended to validate every incoming peer-side episode through `validate_recall_result` + `validate_provenance` + a new `validate_inbound_classification(episode) -> bool` gate (drops episodes whose stored classification is `private` or whose content matches the existing `ClassificationGate._DEFAULT_SENSITIVE_PATTERNS` at `classification.py:51`); rejected episodes emit `FEDERATION_EPISODE_REJECTED`; sanitization runs unconditionally — no opt-out — because the receiver always owns its own boundary),

AD-607g (Federated-recall outbound privacy filter — `FederationRecallAgent.act()` outbound path filters episodes BEFORE returning to the requesting peer through `MemoryAccessPolicy` enforcement; new `FederationConfig.memory_access_policy: Literal["public","shared_trust","private"] = "shared_trust"` controls the outbound surface — `public` returns ship/fleet-classified episodes, `shared_trust` adds episodes from peers whose registry trust score exceeds `FederationConfig.shared_trust_min_score: float = 0.5`, `private` returns empty; the default `shared_trust` honors AD-479b ranking surface that W91 already shipped so the filter sources its trust signal from the existing `peer_trust_registry.get_score(peer_node_id)` path),

AD-607h (Store-time prompt-injection detection — `MemorySecurityGate.evaluate_store(episode) -> StoreSecurityDecision` mirrors the existing AD-610 `_storage_gate` slot at `episodic.py:948`; pattern set extends `ClassificationGate._DEFAULT_SENSITIVE_PATTERNS` with new `_PROMPT_INJECTION_PATTERNS` covering known shapes — system-message-override (`(?i)\bignore\s+(all\s+)?previous\s+instructions\b`), role-swap (`(?i)\byou\s+are\s+now\s+a\s+different\s+(agent|assistant)\b`), tool-spoofing (`(?i)\b(call|invoke)\s+tool\s*[:=]\s*[a-z_]+`), reflective-system-prompt-leak (`(?i)\bwhat\s+is\s+your\s+(system\s+)?prompt\b`); `MemorySecurityConfig.enforce_store: bool = False` opt-in drops; observational v1 emits `MEMORY_INJECTION_SUSPECTED`),

AD-607i (Differential-privacy aggregation — `aggregate_with_dp(episodes, *, min_cohort_size=3) -> list[Episode]` pure helper in `memory_security.py`; episodes returned with `user_input` + `dag_summary` blanked when fewer than `min_cohort_size` unique sovereign_ids contributed; `Episode.id`, `timestamp`, `agent_ids` retained; consumed by AD-607g outbound path when `memory_access_policy="public"` to avoid single-source identification across cross-shard responses; v1 wires only the FederationRecallAgent outbound path — local-only `Oracle.query()` callers do not receive DP redaction because they already pass through AD-607e access control),

AD-607j (Slash command `/security memory` — extends `cmd_security` at `src/probos/experience/commands/commands_status.py` with a `memory` subcommand; surfaces per-EventType counters from the new `MemorySecurityRegistry` aggregator (anomaly count, provenance-gap count, anchor-mismatch count, leak-suspected count, injection-suspected count, federation-rejected count, federation-out-DP-redacted count) over a 24h sliding window; existing `/security` subcommands preserved verbatim).

**Future sub-AD letters with explicit forcing functions (three):**

AD-607k (ML-based extraction-attack classifier — supervised model trained on adversarial query corpus distinguishing benign-recall queries from extraction-style probes; v1 ships pattern-based detection only because no labeled adversarial corpus exists at HEAD and red-team campaigns at `red_team_lead.py` haven't yet generated enough flagged events to bootstrap one; forcing function: 90 days of `MEMORY_RECALL_ANOMALY` event accumulation under v1 + AD-466-style red-team campaign generates enough labeled data to train),

AD-607l (Hardware-attested memory bank via TEE / SGX / SEV-SNP — protects against host-level memory-bank tampering via attestation reports anchored to `EpisodicMemory.store()` + `seal_*` operations; v1 ships software-level provenance integrity only because TEE infra requires CPU + kernel + cloud-platform support outside a public-OSS-runtime's zero-config promise; forcing function: hosted deployment wave that explicitly opts into a TEE platform),

AD-607m (Cross-fleet privacy-budget tracking — fleet-wide differential-privacy ε-budget accountant tracking total privacy expenditure across federated recalls per requesting fleet; v1 ships per-call DP redaction only; forcing function: cross-fleet operations becoming a deployed surface beyond single-cluster federation — this is the hosted-multi-tenant carve-out path, not a public-runtime concern).

**Commercial-repo carve-outs (NOT v1 deferrals — out-of-repo by roadmap design):** hosted memory-security-as-a-service offering centralized adversarial-query corpus + ML-classifier model distribution (per `roadmap.md:3478` + `:4111`), fleet-wide compliance + audit trail aggregation across customer fleets (per `roadmap.md:4095` fleet-dashboard line + `:4111` cross-fleet line), customer-isolation memory-classification overlay built on the v1 `MemoryAccessPolicy` enum (per `roadmap.md:3595` + `:4111`). Tracked in the private commercial-repo path token. The audit text in this dispatch + the per-AD prompt + the wave-plan entry uses descriptor-only language only — pre-commit-hook simulation `Select-String -Path prompts/WAVE-92-DISPATCH.md, prompts/ad-607-memory-security-framework-v1.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern across all 11 banned-pattern descriptors.

## AD numbering

Highest stem at HEAD remains **AD-696** (Wave 72 — verified 2026-05-07 by `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern '\bAD-(\d+)' -AllMatches` returning the maximum at 696 / 695 / 694). AD-607 is pre-allocated at `docs/development/roadmap.md:5266`–`:5278` + `decisions-era-4-evolution.md:4005` (the AD-605–610 absorption batch). Sub-AD letters a–m are organizational catalog markers only, mirroring the AD-479 a–m (Wave 91), AD-480 a–m (Wave 89), AD-481 a–m (Wave 88), AD-443 a–h (Wave 87), AD-474 a–h (Wave 86) precedents — no new AD numbers minted by this wave.

## Verify-first against HEAD `255c52a`

The substrate AD-607 v1 will extend is fully shipped and live — every component AD-607 v1 needs already exists at HEAD, so Wave 92 is "ship the security overlay above the existing memory + federation surfaces", not "ship the surfaces themselves":

- **`EpisodicMemory.recall(query, k)` already exists at `src/probos/cognitive/episodic.py:1508`** — AD-607a hook at the bottom of the loop body filters `episodes` through `validate_recall_result` after the existing relevance-threshold + composite-score filters; observational mode appends an event per result without mutating the returned list when `enforce_recall=False`.
- **`EpisodicMemory.recall_by_anchor_scored(...)` already exists at `episodic.py:1610`** + **`recall_by_anchor(...)` at `:2584`** — AD-607a second hook mirrors the recall path on both methods; the existing 6-channel anchor scoring at `:2196` (`recall_for_agent_scored`) supplies the score signal AD-607c inverts as the anomaly score.
- **`EpisodicMemory.store(episode)` already exists at `episodic.py:942`** — AD-607h hook at line `:948` mirrors the existing AD-610 `_storage_gate` slot pattern verbatim; the new `MemorySecurityGate` slot is set via a public `EpisodicMemory.set_security_gate(gate)` setter, identical pattern to `set_storage_gate(gate)` at `:692` + `set_anomaly_window_manager(manager)` at `:707`.
- **`OracleService.query(query_text, *, agent_id, intent_type, k_per_tier, tiers)` already exists at `oracle_service.py:268`** — AD-607e adds two optional kwargs (`caller_sovereign_id: str = ""`, `access_policy: MemoryAccessPolicy = PERMISSIVE`) without changing the existing signature; the new policy filter applies to the merged result list at the bottom of `query()` after the per-tier aggregation, and to `_query_episodic()` at `:541` where the existing `target_agent_ids` filter already gates by sovereign shard so the `OWN_SHARD_ONLY` mode reuses that path.
- **`FederationRecallAgent.act(plan)` already exists at `src/probos/agents/federation_recall_agent.py:60`** — AD-607f extends the path that calls local `EpisodicMemory.recall()` to filter results through `MemoryAccessPolicy` (outbound, AD-607g) BEFORE returning, and the path that aggregates incoming peer responses to validate each through `validate_recall_result` (inbound, AD-607f); AD-607i DP redaction wraps the outbound list when `memory_access_policy="public"`.
- **`source_governance.classify_retrieval_strategy()` already exists at `src/probos/cognitive/source_governance.py:60`** — AD-607a `validate_recall_result` is a sibling pure function in the same module-or-new-`memory_security.py`-module; the dispatch decision keeps it as a NEW module (`memory_security.py`) per Single Responsibility — security defense is a separate concern from source governance even though both observe recall results.
- **`source_governance.check_faithfulness()` already exists at `source_governance.py:419`** — AD-607d `check_memory_leakage` is a NEW pure function in `memory_security.py` that consumes the existing AD-589 `_check_introspective_faithfulness` results plus the recalled-episode list to produce a leakage finding; the consumer hook is in `cognitive_agent.py` alongside the existing AD-589 post-decision block.
- **`ClassificationGate` + `_DEFAULT_SENSITIVE_PATTERNS` already exist at `src/probos/security/classification.py:64` + `:51`** — AD-607f reuses `ClassificationGate.check_disclosure(content, src_class, dst_class)` to test inbound federated episodes for leak-pattern markers; AD-607h uses the same pattern-list infrastructure (`register_pattern`) to layer prompt-injection patterns on top.
- **AD-589 IntrospectiveFaithfulness post-decision pipeline already exists** at `src/probos/cognitive/cognitive_agent.py` (the `_check_introspective_faithfulness` method block) — AD-607d slots into the same post-decision block as a sibling check; the existing `Counselor` plumbing + episode-metadata pattern handles event emission and side effects identically.
- **`Episode.agent_ids` + `Episode.source` + `Episode.correlation_id` fields already exist at `src/probos/types.py:439`–`:464`** — AD-607b provenance integrity check operates entirely on existing Episode fields, no schema change required.
- **`MemoryConfig` already at `src/probos/config.py:601`** — AD-607a/b/c/e/h add fields onto an existing model rather than creating a new model; the `Field(default_factory=...)` + `field_validator` patterns at `:643`–`:651` are the precedent AD-607 follows.
- **`FederationConfig` already at `src/probos/config.py:872`** — AD-607g adds `memory_access_policy` + `shared_trust_min_score` + `dp_min_cohort_size` fields onto the existing model; the W91 precedent `min_peer_trust_score: float = 0.0` at `:911` is the placement target.
- **`SecurityConfig` already at `src/probos/config.py:1687`** — AD-607 adds a child `MemorySecurityConfig` model containing the four `enforce_*` flags (recall/provenance/store/leak) + the `anchor_mismatch_threshold` knob + the DP cohort-size; `SecurityConfig.memory: MemorySecurityConfig = Field(default_factory=MemorySecurityConfig)`.
- **`commands_status.cmd_security` exists at `src/probos/experience/commands/commands_status.py`** — the same dispatcher pattern AD-479i used for `/federation routing` is the AD-607j precedent; existing `/security` subcommands are preserved verbatim.
- **No `MEMORY_*` security EventType exists at HEAD** — `Select-String -Path src/probos/events.py -Pattern 'MEMORY_(RECALL_ANOMALY|PROVENANCE_GAP|ANCHOR_MISMATCH|LEAK_SUSPECTED|INJECTION_SUSPECTED)|FEDERATION_EPISODE_REJECTED'` returns zero matches; the seven new EventTypes (`MEMORY_RECALL_ANOMALY`, `MEMORY_PROVENANCE_GAP`, `MEMORY_ANCHOR_MISMATCH`, `MEMORY_LEAK_SUSPECTED`, `MEMORY_INJECTION_SUSPECTED`, `FEDERATION_EPISODE_REJECTED`, `FEDERATION_RECALL_DP_REDACTED`) are collision-free.
- **AD-610 `_storage_gate` slot at `episodic.py:948`** is the canonical extension point for the AD-607h store-time path; the existing `evaluate(episode) -> {action, reason, duplicate_of}` shape is mirrored exactly so the two gates compose without coupling.
- **`MemorySource` enum exists** — `Select-String -Path src/probos/types.py -Pattern '^class MemorySource'` confirms the AD-541 `MemorySource` enum is the value set AD-607b validates against (`{"direct", "introspection", "designed", "federated", "imported"}` per existing memory-integrity ADs).

## Reframe decision — no reframe

**Ten concrete sub-AD letters built + three future-AD letters with explicit forcing functions + three commercial-repo carve-outs (NOT deferrals — wrong-repo by roadmap design at lines 3478 + 3595 + 4095 + 4111) + zero hard-deferrals.** This is the strictest application of "don't defer unless no choice" available for AD-607 — every survey-Section-8 + roadmap.md:5266 component that does not depend on un-shipped substrate ships in v1, with the three deferred letters parked behind explicit upstream blockers:

1. **Retrieval-based defense layer (#1 of survey Section 8 taxonomy)** ships in v1 as AD-607a + AD-607b + AD-607c — anomaly gate + provenance integrity + anchor mismatch. The pattern-based detection v1 ships covers every category cataloged in survey Section 8.1 except ML-classifier-driven extraction detection, which is parked as AD-607k with a labeled-corpus forcing function.
2. **Response-based defense layer (#2 of survey Section 8 taxonomy)** ships in v1 as AD-607d — leak-suspected guard slotting alongside the existing AD-589 IntrospectiveFaithfulness block. The roadmap.md:5278 design call to "extend confabulation guard" lands here unchanged.
3. **Privacy-based defense layer (#3 of survey Section 8 taxonomy)** ships in v1 as AD-607e + AD-607f + AD-607g + AD-607i — Oracle access control + federated-recall inbound sanitization + federated-recall outbound privacy filter + DP aggregation. The roadmap.md:5278 design call to "differential privacy on aggregated recall results, data sanitization on federated episode exchange" lands here in full. Hardware-attested storage (AD-607l) is genuinely-upstream-blocked because TEE/SGX support is platform infrastructure outside a public-OSS-runtime's zero-config boot promise.
4. **Operator surface (zero-config diagnostic visibility)** ships in v1 as AD-607j — `/security memory` slash subcommand surfacing the seven new EventType counters. Without operator visibility the security framework would be silent and unverifiable, which is the worst-of-both-worlds default. AD-607j keeps v1 honest.
5. **Store-time defense (poisoning attack surface — survey Section 8.2 catalog)** ships in v1 as AD-607h — pattern-based prompt-injection detection mirroring the existing AD-610 `_storage_gate` slot. The pattern list is intentionally tightly-scoped (4 default patterns) — false-positive-tolerant patterns are intentionally NOT in the default set; callers register them via `MemorySecurityGate.register_pattern(name, regex)` per the AD-530 v1 + W91 default-pattern precedent.

The only honest hard-deferrals (AD-607k / AD-607l / AD-607m) all have crisp upstream blockers documented above. Captain rule "don't defer unless no choice" satisfied — the unblocked-substrate carve-out is empty.

## Files

- `prompts/WAVE-92-DISPATCH.md` (this file)
- `prompts/ad-607-memory-security-framework-v1.md` (the per-AD prompt — ten implementation sections + tests + tracker updates)
- `prompts/wave-plan.yaml` (W92 entry appended)

## Wave-92 baseline + targets

- **HEAD:** `255c52a` (Wave 91 archive: AD-479 federation hardening — closed #73). Captain reference HEAD `255c52a` matches origin/main exactly; no upstream BF commits between Captain HEAD and this draft HEAD.
- **Baseline pytest:** 11963.
- **Target pytest:** ≥ 12035 (+72 floor; ~75 tests planned across ten classes — TestRecallAnomalyValidation ~8, TestProvenanceIntegrity ~7, TestAnchorMismatch ~6, TestMemoryLeakageGuard ~8, TestOracleAccessPolicy ~10, TestFederationInboundSanitization ~8, TestFederationOutboundPrivacy ~8, TestPromptInjectionStoreGate ~8, TestDifferentialPrivacyAggregation ~6, TestSecurityMemorySlashCommand ~6 — plus ~3 startup/runtime wiring tests on the new `MemorySecurityRegistry`).
- **Issue closed:** `#183 — AD-607: Memory Security Framework — Extraction & Poisoning Defense` (single issue; no children).

## Banned-pattern audit on this dispatch + the per-AD prompt + this audit prose itself

11 patterns checked, descriptor-only language used throughout: "the e-word + tier phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The audit text itself does NOT contain literal forms of any banned pattern — descriptor-only references throughout. Pre-commit-hook simulation `Select-String -Path prompts/WAVE-92-DISPATCH.md, prompts/ad-607-memory-security-framework-v1.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern (run as the per-pass review action below).

## Captain rule alignment

- **Don't defer unless no choice:** ten concrete sub-AD letters ship in v1; three future sub-AD letters parked with crisp upstream blockers (labeled-adversarial-corpus / TEE-platform-infra / cross-fleet hosted surface); three commercial carve-outs are out-of-repo by roadmap design (NOT v1 deferrals). Reframe decision: no reframe — every roadmap.md:5278 design-bullet ships, every survey Section 8 defense layer ships, and the operator-visibility surface (607j) is included to keep v1 honest.
- **Verify-first:** every concrete claim above has an explicit grep-evidence line in the per-AD prompt's `## Verified Against Codebase` footer. Sixteen grep-anchored claims confirm extension-point existence at HEAD `255c52a`.
- **`.github/copilot-instructions.md` compliance:** AD-607a + AD-607b + AD-607c + AD-607d are pure observation functions (no destructive intent — `requires_consensus` not applicable); the new `MemorySecurityGate.evaluate_store` slot in AD-607h follows the AD-610 `_storage_gate` precedent. AD-607e + AD-607g respect the layer-discipline rule (cognitive imports from cognitive; federation imports from cognitive only). AD-607f Federation inbound runs `CodeValidator`-equivalent classification gating on incoming episodes, preserving the warm-boot security rule's spirit at the federation boundary. New EventTypes follow the AD-527 typed-events pattern. New Pydantic config fields follow the AD-432 default-factory rule.
- **Close #183 cleanly:** issue closed at end of W92 with the canonical paragraph in Section 12 of the per-AD prompt; no children minted; the three future sub-AD letters are tracked as part of the umbrella close note (forcing-function language only — NOT a "remaining work" backlog).
- **No commercial leak:** descriptor-only audit, banned-pattern scan returns zero hits across both files + this dispatch.

## Build groups

W92 is a single-prompt wave — `ad-607-memory-security-framework-v1.md` is the only build prompt. Builder cycle ships ten sections in order (607a → 607b → 607c → 607d → 607e → 607f → 607g+607i → 607h → 607j; 607g and 607i ship together in Section 7 because the federated outbound privacy filter and the DP aggregator are tightly coupled — the DP helper is consumed only by the outbound public path) with a focused per-section pytest gate after each section, then a full parallel gate at the end before commit.

## Hard-stop conditions

Standard W87 / W89 / W91 set, plus W92-specific:

- **W92-1:** AD-607h prompt-injection patterns produce >5% false-positive rate on existing legitimate test fixtures (e.g., test cases that contain "ignore previous" as natural English) — Builder must NOT loosen the patterns; instead surface as architectural decision back to Architect (probable resolution: tighten pattern context windows, leave default `enforce_store=False`).
- **W92-2:** AD-607e `OWN_SHARD_ONLY` access policy breaks an existing test that relied on cross-shard recall as the default — Builder must NOT change the default away from `PERMISSIVE`; instead make the failing test pass an explicit `access_policy=` kwarg if the test legitimately wants the new behavior, or leave it on `PERMISSIVE` if cross-shard was the intended setup.
- **W92-3:** AD-607f federation inbound rejects every test peer episode in `tests/test_ad479_federation_hardening.py` — Builder must NOT loosen the validator; instead update the test fixtures to produce episodes whose `agent_ids` + `source` + `correlation_id` are populated such that they pass provenance-integrity (this is a fixture-quality issue, not a security-framework defect).
- **W92-4:** AD-607i DP redaction blanks `Episode.user_input` on episodes that downstream tests assert on by content — Builder must wire DP redaction ONLY through the AD-607g federated outbound path (NOT through local `Oracle.query()` or local `EpisodicMemory.recall()`) so local consumer tests see episodes verbatim.

## Build group dependency DAG

Within the single prompt, sub-AD letters have a partial order — Builder ships them in this order to keep each per-section gate green without back-references:

```
607a (memory_security.py + validate_recall_result + new EventType + MemorySecurityConfig) ──┬──> 607b (provenance integrity uses 607a EventType infra)
                                                                                              ├──> 607c (anchor mismatch uses 607a aggregator + EventType)
                                                                                              └──> 607d (leakage guard uses 607a + cognitive_agent.py block)

607b + 607c + 607d ──> 607e (Oracle access control uses 607b/c/d aggregator outputs in test assertions)

607e ──> 607f (federation inbound uses 607a/b/c gates verbatim)
       └─> 607g (federation outbound uses 607e MemoryAccessPolicy enum)
       └─> 607i (DP aggregator consumed by 607g outbound path)

607f + 607g + 607i ──> 607j (slash command surfaces all 7 EventType counters from 607a-i)

607a ──> 607h (store-time gate is parallel-safe — Builder may ship anywhere after 607a's EventType module exists; placed late to keep test additions co-located in the test file's natural order)
```

## Per-commit quality gates

| Gate | Command | When |
|---|---|---|
| Per-section focused gate | `pytest tests/test_ad607_memory_security.py::TestRecallAnomalyValidation -v -n 0` (substitute class name per section) | After each of the ten sub-AD letters builds |
| Cross-cutting integration gate | `pytest tests/test_ad607_memory_security.py tests/test_ad479_federation_hardening.py tests/test_ad589_introspective_faithfulness.py -q -n 0` | After 607f + 607g + 607j ship |
| Full parallel gate | `pytest tests/ -q -n 4 --dist=loadfile` | Before commit, after all ten sections complete |

## Wave-specific reminders for known false positives

- **MagicMock + `iscoroutinefunction` (BF-254 pattern):** AD-607d's hook into AD-589's existing post-decision block uses `asyncio.iscoroutinefunction()` to test whether the leakage check is async — Builder must NOT switch to `hasattr(...) and await ...` because tests will use `MagicMock` for the `EpisodicMemory` dependency.
- **Public-name-promotion mock pattern (BF-252/253):** if Builder needs to set both a public `recall_validator` attribute and a legacy `_recall_validator` slot during transition (the W91 promotion pattern), tests should set BOTH names on the mock to mirror the intended migration.
- **AD-595a unified Pydantic config + `field_validator` ordering:** AD-607's config-field additions land in `MemoryConfig` + `FederationConfig` + `SecurityConfig` + a new child `MemorySecurityConfig` — Builder must place the `field_validator` decorators directly below the corresponding field declarations and use `mode="after"` for cross-field invariants (e.g., DP min cohort >= 1 when `memory_access_policy="public"`).
- **Test isolation with `_storage_gate` / `_recall_validator` slots:** the AD-610 `_storage_gate` slot pattern requires test cleanup — Builder must ensure each test sets `episodic._security_gate = None` in teardown (mirror the existing `_storage_gate` test pattern) so cross-test pollution does not break order-independence.
- **AD-462f cross-AD test reference (W73 → W92):** the existing `MemoryRef` + `recent_for_agent` infrastructure shipped in W73 is consumed by AD-607j's slash-command counter aggregation, which means Builder must NOT touch `recent_for_agent` semantics — only consume the existing 24h-window counter pattern.

## Tracker updates

- **`PROGRESS.md` (line 2 — test count):** flip from 11963 → 12035 (or whatever Builder ships ≥ 12035).
- **`docs/development/roadmap.md:5266`–`:5278` AD-607 entry:** flip from `*(planned, OSS)*` to `*(complete, OSS)*` + append the ten-letter sub-AD breakdown + the three forcing-function future-AD letters + the three commercial carve-outs descriptor.
- **`decisions-era-4-evolution.md`:** append a new `### AD-607` section before AD-636 with the standard rationale + sub-AD-letter table + grep-anchored verify-first footer.
- **`prompts/wave-plan.yaml`:** append the W92 entry per the W91 precedent (id "92" + depends_on `["91"]` + dispatch_prompt + prompt_paths + issues_to_close [183] + status pending + the 600-word `notes:` block summarizing the same content as this dispatch).
- **`gh issue close 183`:** with the canonical paragraph in Section 12 of the per-AD prompt — single-issue close, no children.

## Captain HEAD reconciliation

Captain reference HEAD = `255c52a` (origin/main). This draft HEAD = `255c52a`. Match: no reconciliation required for verify-first.

---

**Wave 92 ready for Builder dispatch after 4 review passes complete and architect commits the draft.**
