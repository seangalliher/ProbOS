# WAVE 79 DISPATCH — AD-594d v1 Delivery Pipeline (1-build, full scope)

**Wave id:** 79
**Umbrella AD:** AD-594 (Crew Consultation Protocol)
**Sub-AD in scope:** AD-594d
**Closes:** GH issue #163
**HEAD at draft:** `acf70a8` (post-Wave-78)
**Baseline test count:** 11498 → expected **11523-11528** pytest (Δ ≥ +25, target +25)
**Builder required:** true (one focused build prompt)

## Verdict

Verify-first against HEAD `acf70a8` confirms the AD-594a substrate is fully in place (`consultation/` package, `WorkspaceRegistry`, `delivery.yaml` placeholder at workspace creation, `outputs/` subdirectory, `RecordsStore.write_workspace_file`/`read_workspace_file`/`append_workspace_file` raw-file API, `WorkspaceLifecycleState` 7-state IntEnum). AD-594d v1 is **fully buildable in one wave**. The Captain rule "don't defer unless no choice" is honored: the entire issue-body scope ships in this wave, with PDF rendering deferred behind a `FormatTransformer` Protocol seam (mirroring AD-594a's `InputProcessor`/`PassthroughTextProcessor` pattern — Protocol-seam deferral, not feature deferral).

| Component | Wave 79 action |
|---|---|
| **Format transformation engine** | **BUILD.** `FormatTransformer` Protocol + 3 concrete transformers (`PassthroughTransformer`, `MarkdownToHTMLTransformer` stdlib-only, `JSONToMarkdownTransformer`) + `build_format_transformer` factory. PDF backend deferred behind the Protocol seam. |
| **`DeliveryAdapter` interface** | **BUILD.** `typing.Protocol` with `name` + `async deliver(artifact) -> AdapterResult`. |
| **`LocalFileAdapter`** | **BUILD.** Path-traversal-safe (constructor-injected `allowed_roots`); supports `rollback(uri)` for atomic rollback. |
| **`GitHubAdapter`** | **BUILD.** Pure HTTP via httpx (already a project dep at `pyproject.toml:29`); env-resolved token (default `GITHUB_TOKEN`); `target_hint` shape `"owner/repo:branch:path"`; PUT to GitHub Contents API; injectable `http_post` for testability. No subprocess; no `gh` CLI. |
| **Captain approval gate** | **BUILD.** `DeliveryRequest.requires_approval=True` → `pending_approval` receipt; `pipeline.approve(...)` / `reject(...)` flips state and dispatches/rolls-back. In-pipeline equivalent of `requires_consensus` (which applies to IntentMessage handlers, not service surfaces). |
| **Audit trail** | **BUILD.** Receipts persisted as YAML in `consultations/<id>/delivery.yaml` (overwrite per `delivery_id`; chronological list); journal entries appended for every deliver/approve/reject. Reuses AD-594a's `delivery.yaml` placeholder + `journal.md`. |
| **Partial vs. atomic** | **BUILD.** `DeliveryRequest.atomic` flag. Atomic: first failure aborts + rolls back where adapters support it (LocalFile yes, GitHub no — receipt records asymmetry). Partial: deliver-all-best-effort. |
| **Revision cycle** | **BUILD.** `_ALLOWED_TRANSITIONS` extended (`COMPLETED → CONSULTING` + `COMPLETED → EXECUTING`); `pipeline.revise(workspace_id, target=...)` delegates to `workspace.transition_to()`. |
| **Pydantic config** | **BUILD.** `ConsultationDeliveryConfig` with `enabled=True`, per-adapter enable flags, `local_file_allowed_roots`, `github_token_env`, `default_requires_approval`. Wired adjacent to `consultation_workspaces`. |
| **Finalize wirer** | **BUILD.** `_wire_consultation_delivery` mirrors `_wire_consultation_workspaces` shape; per-adapter try/except so a single bad adapter does not disable the pipeline. |

## Reframe decision (Captain rule applied)

**Full-scope v1 in one wave.** No deferral of v1 surface; PDF backend is a Protocol-seam deferral (not a feature deferral) — same precedent AD-594a established with `InputProcessor`/`PassthroughTextProcessor`. The wave ships:

- Pipeline + adapters + transformers + config + wirer + state-machine extension + receipt persistence + revision cycle in one prompt
- ≥25 focused tests covering: factory, transformers (3), `LocalFileAdapter` happy/error/rollback, `GitHubAdapter` no-token/happy/4xx/target-hint-parse, pipeline register-and-list, deliver-receipt-and-journal, missing-source per-item-error, atomic-rollback, partial-continue, approval gate (pending/approve/reject/unknown), revise (CONSULTING/EXECUTING/invalid-target), AD-594a regression (COMPLETED→ARCHIVED still works), wirer (happy/no-registry/disabled-config)

GH #163 closes cleanly because every line of its scope ships in this wave. The "Commercial Extension" line in the issue body (Loop / OneDrive / Teams / Email / Slack adapters; Yeoman as engagement manager) stays explicitly out-of-scope — those are private-repo deliverables; the OSS surface is exactly Protocol + LocalFileAdapter + GitHubAdapter as the issue body requires.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  acf70a87b1cf08e63c01e7d39a1bf2cae26a4c98

# AD-594a substrate (verified shipped):
src/probos/consultation/__init__.py:1-56
  Module exports WorkspaceRegistry, ConsultationWorkspace, WorkspaceLifecycleState,
  ArtifactType, TEMPLATES, InputProcessor, PassthroughTextProcessor, build_input_processor,
  WorkspaceRef, parse_workspace_refs, render_workspace_refs_md.
src/probos/consultation/workspace.py:43-58
  WorkspaceLifecycleState IntEnum (INITIATED..ARCHIVED) + _ALLOWED_TRANSITIONS adjacency map.
src/probos/consultation/workspace.py:55
  COMPLETED: frozenset({ARCHIVED})  ← extension target for AD-594d revision cycle.
src/probos/consultation/workspace.py:185-191  add_output()
src/probos/consultation/workspace.py:300-310  WorkspaceRegistry.create() writes empty delivery.yaml placeholder.
src/probos/knowledge/records_store.py:890-940
  write_workspace_file / read_workspace_file / append_workspace_file (raw, AD-594a additions).
src/probos/knowledge/records_store.py:64-65
  repo_path property returns Path.

# Config insertion anchor:
src/probos/config.py:2072-2082
  ConsultationWorkspaceConfig (precedent: enabled=True, default-true documented).
src/probos/config.py:2442-2444
  SystemConfig.consultation_workspaces  ← AD-594d adds consultation_delivery adjacent.

# Wirer insertion anchor:
src/probos/startup/finalize.py:631-660
  _wire_consultation_workspaces (template).
src/probos/startup/finalize.py:978-980
  consultation_workspaces invocation in finalize_startup.

# Project deps:
pyproject.toml:29
  "httpx>=0.27"  ← GitHubAdapter can import httpx without adding a new dep.
src/probos/agents/http_fetch.py:34-300
  HttpFetchAgent.async httpx.AsyncClient pattern reference.

# Roadmap status line:
docs/development/roadmap.md:4842
  > - **AD-594d: Delivery Pipeline** *(planned, OSS)* — ...  ← status flip target.

# Test conventions:
tests/test_ad594a_consultation_workspace.py  ← sibling test file (do not modify).
tests/test_ad594_consultation_protocol.py    ← unrelated to AD-594d.

# GH issue:
gh issue view 163
  State: open. Scope: format transform, DeliveryAdapter + LocalFile + GitHub, captain
  approval, audit trail, partial vs atomic, revision cycle. Commercial extension
  explicitly listed as commercial-tier.

# AD numbering:
Stem search across PROGRESS.md + DECISIONS.md + decisions-era-*.md confirms AD-594d
is unused as a stem suffix. Highest stem in trackers: AD-696 (Wave 72).
```

Every concrete claim in this dispatch maps to a grep hit above.

## Captain workflow

1. **Append wave 79 entry to `prompts/wave-plan.yaml`** under id `"79"`, after id `"78"`:
   ```yaml
     - id: "79"
       title: "AD-594d v1 Delivery Pipeline (full-scope)"
       kind: single
       depends_on: ["78"]
       dispatch_prompt: "prompts/WAVE-79-DISPATCH.md"
       prompts_already_drafted: true
       prompt_paths:
         - "prompts/ad-594d-delivery-pipeline-v1.md"
       builder_required: true
       issues_to_close: [163]
       status: pending
       notes: |
         Closes GH #163 (AD-594d Delivery Pipeline). Full v1 scope in one wave
         per Captain rule (don't defer unless no choice). Module shape:
         FormatTransformer Protocol + 3 concrete transformers (Passthrough,
         MarkdownToHTML stdlib-only, JSONToMarkdown), DeliveryAdapter Protocol
         + LocalFileAdapter (allowed_roots-gated + rollback) + GitHubAdapter
         (httpx + env token + injectable http_post for tests), DeliveryPipeline
         orchestrator with approval gate (requires_approval=True ->
         pipeline.approve/reject), atomic vs partial, revision cycle via
         pipeline.revise -> workspace.transition_to. State-machine extension:
         COMPLETED -> CONSULTING and COMPLETED -> EXECUTING added (ARCHIVED
         still allowed). Pydantic ConsultationDeliveryConfig + finalize wirer.
         PDF rendering deferred behind FormatTransformer Protocol seam (mirrors
         AD-594a InputProcessor precedent). Baseline 11498 -> target 11523-11528
         (+25 floor). No HXI surface. No new EventType. No new Intent. OSS only.
   ```
2. **Builder runs `prompts/ad-594d-delivery-pipeline-v1.md`** end-to-end. One commit. Outputs:
   - **New:** `src/probos/consultation/delivery.py`, `tests/test_ad594d_delivery_pipeline.py`
   - **Modified:** `src/probos/consultation/__init__.py`, `src/probos/consultation/workspace.py`, `src/probos/config.py`, `src/probos/startup/finalize.py`, `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, `prompts/wave-plan.yaml`
3. **Pre-commit gate (Builder responsibility):**
   - `pytest tests/ -q -n 4 --dist=loadfile` — collection ≥ 11523 (delta ≥ +25), all green; existing AD-594a tests pass unchanged.
   - `pytest tests/test_ad594d_delivery_pipeline.py -v -n 0` — focused gate, all ≥25 tests pass serially.
   - `pytest tests/test_ad594a_consultation_workspace.py -v -n 0` — AD-594a regression gate (state-machine extension must not break existing transitions).
   - `git status` shows the expected file set; no unrelated modifications.
4. **Update `PROGRESS.md`** (top of "Recent Builder Closures" block) with one Wave 79 entry — paragraph style matching Wave 78's entry.
5. **Update `docs/development/roadmap.md`** line 4842: `*(planned, OSS)*` → `*(complete — Wave 79, OSS; PDF rendering deferred behind FormatTransformer Protocol seam pending consumer)*`. Preserve descriptive prose.
6. **Update `DECISIONS.md`** — append AD-594d v1 entry above AD-594a (line 148) with Problem / Decision / Consequences shape mirroring AD-594a's entry.
7. **Update `prompts/wave-plan.yaml`** id `"79"` entry with `status: done` after Builder gate passes.
8. **Commit:** `Wave 79: AD-594d v1 Delivery Pipeline (full scope; PDF deferred behind Protocol seam) (#163)`.
9. **Archive** `prompts/WAVE-79-DISPATCH.md` and `prompts/ad-594d-delivery-pipeline-v1.md` to `prompts/archive/` after the GH close.
10. **Close GH #163** with verify-first evidence + commit hash + scope-completed checklist (one row per scope bullet from the issue body, all ✓).
11. **Update memory `/memories/session/wave-queue-batch2.md`** with `W79 #163 done (single: AD-594d v1 full-scope; +<actual> tests, baseline 11498)`.

## Hard-stop conditions

1. **Phantom API in implementation.** Every method, attribute, and store anchor asserted in `prompts/ad-594d-delivery-pipeline-v1.md` is verified against HEAD `acf70a8` in the prompt's "Verified Against Codebase" section. If the Builder finds a mismatch (e.g. `RecordsStore.read_workspace_file` returns a different shape, `WorkspaceRegistry.create` does not write `delivery.yaml`, `_ALLOWED_TRANSITIONS` is structured differently), → hard stop, surface to Architect.
2. **Architectural change required.** AD-594d is additive on top of AD-594a. If the Builder concludes a `BaseAgent`/`IntentMessage`/`SystemConfig` protocol change is required (e.g. `requires_consensus` semantics, new `EventType`), → hard stop. Architect re-scopes; the dispatch's "no architectural changes" invariant is a hard line.
3. **Real network in tests.** Any test that imports `httpx` and lets a `GitHubAdapter` call out to `api.github.com` → hard stop. All HTTP must be mocked via the injected `http_post` callable. The dispatch is explicit on this.
4. **PDF backend ships.** Any concrete `MarkdownToPDFTransformer` (or any import of `weasyprint` / `reportlab` / `pdfkit` / `fpdf` / `WeasyPrint` / `xhtml2pdf`) → hard stop. PDF is deferred behind the Protocol seam in v1; v1 ships zero PDF backend.
5. **Subprocess in `GitHubAdapter`.** Any `subprocess.*` / `os.system` / `gh` CLI invocation in `GitHubAdapter` → hard stop. Pure HTTP only.
6. **`LocalFileAdapter` without allowed_roots gate.** Any `LocalFileAdapter` write path that bypasses the `allowed_roots` resolved-prefix check → hard stop. Privilege-escalation prevention is non-negotiable.
7. **EventType emission.** Any new `EventType.DELIVERY_*` value or `runtime.emit_event(...)` call from the pipeline → hard stop. v1 audit lives in `delivery.yaml` + `journal.md` only; events come with a consumer in a follow-up AD.
8. **HXI surface.** Any `routers/*.py` modification, any new `/api/consultation-delivery/*` endpoint, any `ui/src/` modification → hard stop. AD-594d v1 is service-only.
9. **Commercial leak.** Any pricing, revenue, customer-count, professional-services, GTM, or competitive-positioning language introduced into the prompt body, the module, the config docstring, the DECISIONS entry, the roadmap entry, the GH close comment, or any wave artifact → hard stop. The issue body explicitly lists Loop / OneDrive / Teams / Email / Slack adapters and "Yeoman as engagement manager" as commercial — those names must not appear in any OSS deliverable. The OSS surface is exactly the issue's "OSS" line: Protocol + LocalFileAdapter + GitHubAdapter.
10. **Test count drift.** Pytest full gate must report ≥ 11523 collected (delta ≥ +25). Less → hard stop, surface to Architect (likely a test was missed); more → fine, exceed-target is acceptable per Captain rule.
11. **Working-tree drift.** Untracked changes outside the file set listed in step 2 → hard stop. Only `src/probos/consultation/`, `src/probos/config.py`, `src/probos/startup/finalize.py`, `tests/test_ad594d_delivery_pipeline.py`, `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, `prompts/wave-plan.yaml` may be modified.
12. **AD-594a regression.** Any AD-594a test failure (`tests/test_ad594a_consultation_workspace.py`) after the `_ALLOWED_TRANSITIONS` extension → hard stop. The extension is additive (preserves COMPLETED→ARCHIVED inside an enlarged frozenset); the existing transition tests must continue to pass without modification.

## Acceptance criteria

1. `git status` (post-Builder) shows exactly:
   - `?? src/probos/consultation/delivery.py` (new)
   - `?? tests/test_ad594d_delivery_pipeline.py` (new)
   - `M src/probos/consultation/__init__.py`
   - `M src/probos/consultation/workspace.py`
   - `M src/probos/config.py`
   - `M src/probos/startup/finalize.py`
   - `M PROGRESS.md`
   - `M docs/development/roadmap.md`
   - `M DECISIONS.md`
   - `M prompts/wave-plan.yaml`
   No other files.
2. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — ≥ **11523 collected**, all passed (delta ≥ +25 vs baseline 11498).
3. **Focused gate** `pytest tests/test_ad594d_delivery_pipeline.py -v -n 0` — ≥25 tests, all pass.
4. **AD-594a regression gate** `pytest tests/test_ad594a_consultation_workspace.py -v -n 0` — all existing tests pass unchanged.
5. PROGRESS.md Wave 79 entry summarizes the build in one paragraph, matching Wave 78 style.
6. roadmap.md line 4842 status flipped per Captain workflow step 5.
7. DECISIONS.md AD-594d v1 entry inserted above AD-594a (Problem / Decision / Consequences shape).
8. wave-plan.yaml id `"79"` entry committed with `status: done` after gate passes.
9. GH #163 closed with verify-first evidence + commit hash + scope checklist (one row per issue-body bullet, all ✓).
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: SOLID-S (pipeline orchestrates, adapters deliver, transformers convert; no god class); SOLID-D (constructor injection for adapters, transformers, http_post, allowed_roots, clock); Liskov (adapter classes honor `DeliveryAdapter` Protocol; transformer classes honor `FormatTransformer`); three-tier exception handling (tier-2 log-and-degrade for journal/receipt/adapter errors and JSON parse errors; tier-3 propagate for `_safe_path` violations); full type annotations on the public surface; async hygiene (no fire-and-forget tasks; httpx client lifecycle owned by the adapter); structured logging with `"AD-594d: <what> on workspace=<id>"` format; no commercial language; no emoji.
