# AD-838 — Wire office document-creation intents end-to-end (PPTX / DOCX / XLSX) with output-path honoring + NL content generation

**Status:** Ready
**Dependencies:** AD-755 (office agents + `OfficeSkillsConfig`), AD-211–215 (`DependencyResolver` — context only, not modified here)
**Estimated tests:** 9 pytest
**Current highest AD:** AD-837 (next sequential top-level: AD-838)

## Problem

A Captain request like *"create a report and save it as a PowerPoint file"* does **not**
produce a usable file today, even though every primitive exists. Three gaps in the AD-755
office-skills path:

1. **Intent → method dispatch is missing.** `PptxAgent` / `DocxAgent` / `XlsxAgent`
   ([`skill_framework.py:27/130/216`](../src/probos/skill_framework.py)) declare
   `intent_descriptors` (`pptx_create`, `docx_create`, `xlsx_update`, …) so the decomposer
   advertises and can route them, but they never override `handle_intent` and register no
   `Skill` objects. They inherit
   [`SkillBasedAgent.handle_intent`](../src/probos/substrate/skill_agent.py#L74), which only
   dispatches to entries in `self._skills` — which is **empty** for these agents. So a
   `pptx_create` intent reaches the agent and returns `None` → the agent **declines** → the
   intent fails/escalates instead of building anything. `create_pptx` / `create_docx` are
   only ever called directly from tests
   ([`test_office_agents.py:86`](../tests/test_office_agents.py)), never from the running mesh.

2. **The requested filename/location is ignored.**
   [`create_pptx`](../src/probos/skill_framework.py#L183) and
   [`create_docx`](../src/probos/skill_framework.py#L93) save to a random
   `tempfile.NamedTemporaryFile(suffix=".pptx")` path. There is no parameter for "save it as
   `Q2-report.pptx`" or to a chosen folder — the Captain would get an orphan temp file, not
   the file they asked for.

3. **No NL → content synthesis.** `create_pptx` takes a pre-structured
   `slides: list[dict]` (title + bullets); `create_docx` takes `content: list[str]`. Neither
   authors a report from a natural-language brief. The office agents *are* constructed with
   `llm_client=llm_client`
   ([`agent_fleet.py:289`](../src/probos/startup/agent_fleet.py#L289)) but the create methods
   never use it.

### Note on "can it just pip-install a library when needed?" (Captain question)

ProbOS **already has** dynamic dependency installation: `DependencyResolver`
([`cognitive/dependency_resolver.py`](../src/probos/cognitive/dependency_resolver.py),
AD-211–215) detects missing imports via AST, asks for approval, and installs via `uv add`,
gated on the `allowed_imports` whitelist. **But** it only runs inside the self-modification
pipeline (`self_mod.py` step 2b) when an agent/skill is *designed* at runtime — pre-built
agents like the office agents never pass through it. For PowerPoint specifically **no install
is needed**: `python-pptx` (plus `python-docx`, `openpyxl`) are already hard dependencies
([`pyproject.toml:50-52`](../pyproject.toml)). This AD therefore does **not** touch the
resolver; it wires the already-installed capability. Extending `DependencyResolver` to the
non-designed/tool-acquisition path is out of scope (forward marker **AD-838c**).

## Solution

Wire the existing create/summarize/update methods to their intents, honor an output path,
and add an LLM-backed content path so a bare NL brief yields a real deck/doc. No new
third-party dependency. No change to the decomposer, consensus, or `DependencyResolver`.

### Section 1 — Intent → method dispatch on the office agents

File: `src/probos/skill_framework.py`

Override `handle_intent` on `DocxAgent`, `PptxAgent`, and `XlsxAgent` to map the declared
intent names to their existing methods, returning a proper `IntentResult`. Unknown intents
return `None` (decline) — preserving the `_BundledMixin`/broadcast self-deselect contract so
these agents do not hijack unrelated intents on the bus.

- `DocxAgent`: `docx_summarize` → `summarize_docx`, `docx_create` → `create_docx`,
  `docx_revise` → `revise_docx`.
- `PptxAgent`: `pptx_summarize` → `summarize_pptx`, `pptx_create` → `create_pptx`.
- `XlsxAgent`: `xlsx_read_range` → `read_xlsx_range`, `xlsx_update` → `update_xlsx`.

Each handler pulls typed params from `intent.params`, calls the method, and wraps the
returned path/summary in `IntentResult(success=True, ...)` with the output path surfaced in
the result payload so the shell/HXI can report *where* the file landed. Missing required
params → `IntentResult(success=False, error=...)` (boundary validation), never a raw raise.

### Section 2 — Honor an output path / filename

File: `src/probos/skill_framework.py` + `src/probos/config.py`

- Add `output_path: str | None = None` to `create_docx` and `create_pptx`. When provided,
  save there (expand `~`, create parent dirs); when `None`, save to a per-format default
  filename (slugified from `title`, e.g. `q2-review.pptx`) under a configured output
  directory.
- Add `output_dir: str = "~/.probos/output"` to `OfficeSkillsConfig`
  ([`config.py:4919`](../src/probos/config.py#L4919)) with the same `~`-expansion validator
  as `template_dir`. Default boots zero-config.
- The `handle_intent` handlers read `intent.params.get("output_path")` and pass it through.
  Retain the random-tempfile behavior **only** as the fallback when neither `output_path` nor
  a resolvable `output_dir` is available (regression-safe for the existing direct-call tests,
  which pass neither).

### Section 3 — NL content synthesis for create intents

File: `src/probos/skill_framework.py`

When `pptx_create` / `docx_create` arrives with a `prompt`/`brief` param (NL request) but
**no** structured `slides`/`content`, use `self._llm_client` to synthesize the structure:

- New private helper `_synthesize_slides(brief, title) -> list[dict]` (PPTX) and
  `_synthesize_paragraphs(brief, title) -> list[str]` (DOCX): a single strict-JSON-output LLM
  call (await-aware, mirrors the existing `summarize_docx` LLM guard at
  [`skill_framework.py:54`](../src/probos/skill_framework.py#L54)). On no LLM / parse failure
  → honest-degrade to a single title slide / one-paragraph stub (Tier-2 log-and-degrade,
  never raise). Structured `slides`/`content` params, when present, bypass synthesis entirely
  (deterministic path unchanged).

This is what lets *"create a report and save it as a PowerPoint"* decompose to
`pptx_create{title, prompt, output_path}` and produce a real, populated deck at the requested
location.

## Tests

New file: `tests/test_ad838_office_create_wiring.py`

1. **`pptx_create` dispatch** — `handle_intent(IntentMessage(intent="pptx_create", params={...}))`
   produces a readable deck; `IntentResult.success` and the result payload carries the path.
2. **`docx_create` dispatch** — same shape for DOCX.
3. **`xlsx_update` dispatch** — round-trips a cell write through `handle_intent`.
4. **Unknown intent declines** — office agent `handle_intent` for an unrelated intent returns
   `None` (broadcast self-deselect preserved).
5. **`output_path` honored** — create with explicit `output_path`; file exists at exactly that
   path.
6. **Default output dir** — create with no `output_path`; file lands under
   `OfficeSkillsConfig.output_dir` with a slugified name.
7. **NL synthesis populates slides** — `pptx_create` with `prompt` + no `slides`, mock LLM
   returning JSON; deck contains the synthesized slide titles/bullets.
8. **NL synthesis honest-degrade** — `pptx_create` with `prompt`, `_llm_client=None`; produces
   a valid single-slide deck (no raise).
9. **Missing required param** — `pptx_create` with no `title` → `IntentResult(success=False)`,
   no exception.

Run: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad838_office_create_wiring.py -v -n 0`

## What This Does NOT Change

- No change to `DependencyResolver` / `self_mod.py` (the dynamic-install path is already
  shipped for designed agents; office deps are pre-bundled). Forward marker **AD-838c**.
- No change to the decomposer, consensus gating, trust, or routing.
- No change to `summarize_*` / `revise_docx` behavior beyond being reachable via
  `handle_intent`.
- No SharePoint/OneDrive upload of the produced file (AD-755 commercial routing seam) —
  forward marker **AD-838b**.
- No new third-party dependency.

## Tracking

- `PROGRESS.md` — add AD-838 entry on completion.
- `decisions-era-5-unification.md` — append AD-838: office create intents wired end-to-end,
  output-path honoring, NL content synthesis. Note the dynamic-install answer (resolver
  already exists for designed agents; office deps pre-bundled).
- Forward markers: **AD-838b** (route produced file to OneDrive/SharePoint via AD-755 seam),
  **AD-838c** (extend `DependencyResolver` to the tool-acquisition/non-designed path so a
  capability needing an un-bundled package can request install with approval).

## Acceptance Criteria

1. A `pptx_create` / `docx_create` / `xlsx_update` intent dispatched on the mesh produces a
   real file (no longer declines).
2. An explicit `output_path` is honored; absent one, the file lands under
   `OfficeSkillsConfig.output_dir` with a slugified name.
3. A NL `prompt` with no structured content yields an LLM-populated deck/doc, with
   honest-degrade to a stub when no LLM is available.
4. `tests/test_ad838_office_create_wiring.py` passes (9 tests).
5. Zero-config boot unchanged; existing `tests/test_office_agents.py` direct-call tests still
   pass.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
