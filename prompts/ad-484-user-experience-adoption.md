# AD-484: User Experience & Adoption Readiness (v1)

**Status:** Ready for builder
**Dependencies:** Builds on the existing CLI at `src/probos/__main__.py` (verified `_cmd_init` at line 542; `argparse` subparsers at line 1077-1127). Reuses `rich` (already a hard dep at `pyproject.toml:25`). No new pyproject deps in v1.
**Estimated tests:** ~10
**Risk:** MEDIUM — most repo-level work doesn't touch runtime semantics. The `probos init` wizard and `probos doctor` diagnostic are user-facing and need clear failure modes.

---

## Problem

ProbOS is a probabilistic agent-native OS runtime, but the install + first-run experience does not match a polished open-source release:

1. **No PyPI publishing config** — `pyproject.toml` has the metadata fields (`name`, `version`, `description`, `classifiers`) but lacks a long-description URL, project URLs, and a release-build trigger. `pip install probos` does not work today.
2. **`probos init` is non-interactive** — `__main__.py:542 _cmd_init` writes a static config and prompts only for two values (LLM URL + model). No `Rich` TUI, no provider auto-detection, no diagnostic banner.
3. **No `probos doctor` diagnostic** — operators cannot quickly verify their environment (config validity, LLM endpoint reachability, NATS connectivity, ChromaDB presence, file-system permissions on `data_dir`).
4. **Quickstart docs missing** — `docs/quickstart.md` and `docs/getting-started.md` do not exist (verified). New users land in the architecture docs without an entry path.

`grep -n "_cmd_doctor\|probos doctor" src/probos/__main__.py` returns no matches today.

The roadmap entry (line 7024) lists 5 capabilities. **v1 ships 3 real-work primitives; 2 deferred to AD-484b** per convention #14.

## Solution Overview

Three repo-level changes:

1. **PyPI publishing readiness** — extend `pyproject.toml` with `[project.urls]`, `[tool.setuptools.dynamic]` for README, and a `Development Status :: 4 - Beta` upgrade. Add `MANIFEST.in` if missing. Verify `pyproject.toml` builds with `python -m build` (manual at Builder time).
2. **`probos init` Rich TUI wizard** — rewrite `_cmd_init` to use `rich.prompt.Prompt` and `rich.panel.Panel`. Auto-detect three providers: local Ollama (`http://localhost:11434`), Copilot proxy (`http://127.0.0.1:8080`), and Anthropic API (env `ANTHROPIC_API_KEY`). On success, run a diagnostic preview ("Connectivity OK", "Suggested first command: `probos`").
3. **`probos doctor` diagnostic command** — new subparser. Checks (in order): (1) config file present + parseable; (2) `data_dir` writable; (3) LLM tier endpoints reachable (reuses `_create_llm_client`'s connectivity probe); (4) NATS reachable when `config.nats.enabled`; (5) ChromaDB import-able (lazy). Each check prints a `[green]✓[/green]` or `[red]✗[/red]` row; final summary "All checks passed" or "N issues — see above". Exits with non-zero status when any check fails.
4. **Quickstart docs** — add `docs/quickstart.md` (5-minute path: install, init, run, first conversation), `docs/getting-started.md` (orientation: what ProbOS is, how it differs from a single-agent assistant, links to the deeper architecture docs). Stdlib-only Markdown, no static-site-generator change.

This is **repo-level UX work layered on the existing CLI surface.** AD-484 does NOT modify runtime semantics, does NOT introduce new event types, does NOT add new pyproject deps.

**v1 scope (no-theater discipline; convention #7 + #14):**

- **PyPI publishing readiness** — real `pyproject.toml` extension; `pip install probos` works after first publish.
- **`probos init` TUI wizard** — real Rich prompts + real provider auto-detection.
- **`probos doctor` diagnostic** — real connectivity checks reusing existing primitives.
- **Quickstart docs** — real Markdown files.

**Two wholesale-deferred to AD-484b:**

- **Homebrew formula** — requires Homebrew tap repo + release pipeline. Out of scope.
- **`probos demo` mock mode** — requires demo-content scaffolding (mock NL inputs, expected responses). Defer until `MockLLMClient` exposes a stable demo interface.
- **HXI Holographic Glass Panels** — UI work; out of scope for repo-readiness.
- **Browser Automation (Playwright BrowseAgent)** — runtime work; deferred to AD-484c.

---

## Section 0: Event Types

**No new EventTypes.** AD-484 is repo-level + CLI work; runtime semantics are unchanged.

> Verify-first: `grep -n "EventType" docs/development/roadmap.md:7024` shows no event-type listing for AD-484. The roadmap entry's "(1) Distribution & Packaging, (2) Onboarding Wizard, (3) Quickstart Documentation" capabilities are non-runtime; no events fire.

---

## Section 1: PyPI publishing readiness

**File:** `pyproject.toml`

SEARCH:
```toml
classifiers = [
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
```

REPLACE:
```toml
classifiers = [
    "Development Status :: 4 - Beta",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: System :: Distributed Computing",
]

[project.urls]
Homepage = "https://github.com/seangalliher/ProbOS"
Documentation = "https://github.com/seangalliher/ProbOS/blob/main/docs/quickstart.md"
Repository = "https://github.com/seangalliher/ProbOS"
Issues = "https://github.com/seangalliher/ProbOS/issues"
```

> Verify-first: `pyproject.toml:14 readme = "README.md"` exists; the long-description-content-type is auto-derived. `[project.urls]` is the canonical PyPI metadata block.

**File:** `MANIFEST.in` (new)

```
include README.md LICENSE
recursive-include src/probos *.py
recursive-include config *.yaml *.yml
graft docs/quickstart.md
graft docs/getting-started.md
prune tests
prune .github
```

> Builder note: verify `LICENSE` exists at repo root via `Test-Path LICENSE` before drafting; the dispatch confirms Apache-2.0 license declaration in `pyproject.toml:10`. If LICENSE is missing, the Builder skips the `include LICENSE` line and surfaces a recommendation.

---

## Section 2: `probos init` Rich TUI wizard

**File:** `src/probos/__main__.py`

Rewrite `_cmd_init` (currently at line 542). v1 adds:
- `rich.prompt.Prompt` for input collection
- Provider auto-detection probes
- Diagnostic preview after config write

SEARCH (`__main__.py:542-606`, the entire `_cmd_init` body):
```python
def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` — create ~/.probos/ with default config."""
    console = Console()
    home = Path(args.probos_home) if args.probos_home else _probos_home()
    ...
    console.print("ProbOS initialized. Run [bold]probos serve[/bold] to start.")
```

REPLACE:
```python
def _detect_llm_providers(console: Console) -> dict[str, str]:
    """Probe known providers and return reachable endpoints.

    Returns a dict mapping provider name -> URL when reachable; empty otherwise.
    """
    import httpx

    detected: dict[str, str] = {}
    candidates = [
        ("ollama", "http://localhost:11434"),
        ("copilot-proxy", "http://127.0.0.1:8080"),
    ]
    for name, url in candidates:
        try:
            with httpx.Client(base_url=url, timeout=1.5) as client:
                # Ollama: GET /api/version. Copilot proxy: GET /v1/models.
                probe_path = "/api/version" if name == "ollama" else "/v1/models"
                resp = client.get(probe_path)
                if resp.status_code < 500:
                    detected[name] = url
        except Exception:
            continue

    if os.environ.get("ANTHROPIC_API_KEY"):
        detected["anthropic"] = "https://api.anthropic.com"

    return detected


def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
    from rich.panel import Panel
    from rich.prompt import Prompt

    console = Console()
    home = Path(args.probos_home) if args.probos_home else _probos_home()

    if (home / "config.yaml").exists() and not args.force:
        console.print(
            f"[yellow]Config already exists at {home / 'config.yaml'}[/yellow]\n"
            f"Use [bold]--force[/bold] to overwrite."
        )
        return

    console.print(
        Panel.fit(
            "[bold blue]ProbOS Init[/bold blue]\n"
            "Setting up your ProbOS configuration.",
            border_style="blue",
        )
    )
    console.print()

    # Auto-detect providers
    console.print("  [dim]Detecting LLM providers...[/dim]")
    detected = _detect_llm_providers(console)
    for name, url in detected.items():
        console.print(f"  [green]\u2713[/green] {name}: {url}")
    if not detected:
        console.print("  [yellow]\u26a0[/yellow] No local LLM providers detected.")

    # Prompt for endpoint with detected default
    default_url = next(iter(detected.values()), "http://127.0.0.1:8080/v1")
    if default_url == "http://localhost:11434":
        default_url = "http://localhost:11434/v1"
    elif default_url == "http://127.0.0.1:8080":
        default_url = "http://127.0.0.1:8080/v1"
    llm_url = Prompt.ask("  LLM endpoint URL", default=default_url, console=console)

    # Prompt for model with sensible default per provider
    if "ollama" in detected.values().__class__.__name__ or ":11434" in llm_url:
        default_model = "llama3.1:8b"
    else:
        default_model = "claude-sonnet-4-20250514"
    llm_model = Prompt.ask("  LLM model", default=default_model, console=console)

    api_format = "ollama" if ":11434" in llm_url else "openai"

    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    (home / "notes").mkdir(exist_ok=True)

    config_content = f"""\
# ProbOS Configuration -- generated by `probos init`
system:
  name: "ProbOS"
  version: "0.1.0"
  log_level: "WARNING"

cognitive:
  default_llm_tier: "fast"
  llm_base_url_fast: "{llm_url}"
  llm_api_key_fast: ""
  llm_model_fast: "{llm_model}"
  llm_api_format_fast: "{api_format}"

self_mod:
  enabled: true

knowledge:
  enabled: true
  repo_path: "{(home / 'knowledge').as_posix()}"

utility_agents:
  enabled: true
"""
    (home / "config.yaml").write_text(config_content, encoding="utf-8")

    console.print()
    console.print(f"  [green]\u2713[/green] Created [bold]{home}[/bold]")
    console.print(f"  [green]\u2713[/green] Config: [dim]{home / 'config.yaml'}[/dim]")
    console.print(f"  [green]\u2713[/green] Data dir: [dim]{home / 'data'}[/dim]")
    console.print()
    console.print(
        Panel.fit(
            "Run [bold]probos doctor[/bold] to verify your setup.\n"
            "Run [bold]probos[/bold] to start the interactive shell.",
            title="Next steps",
            border_style="green",
        )
    )
```

> Verify-first: `Console`, `Panel` imports already exist at `__main__.py:26-29`. `Prompt` is added at the top of `_cmd_init` to keep the import scoped.

---

## Section 3: `probos doctor` diagnostic command

**File:** `src/probos/__main__.py`

Add a new `_cmd_doctor` function next to `_cmd_init` and register a `doctor` subparser.

After the `_cmd_init` rewrite (Section 2), insert:

```python
def _cmd_doctor(args: argparse.Namespace) -> int:
    """Handle ``probos doctor`` -- diagnostic check (AD-484).

    Returns the number of failed checks (0 = healthy, non-zero = issues).
    """
    console = Console()
    failures: list[str] = []

    console.print("[bold blue]ProbOS Doctor[/bold blue]\n")

    # Check 1: config file present + parseable
    home = _probos_home()
    config_path = home / "config.yaml"
    if not config_path.exists():
        console.print("  [red]\u2717[/red] config.yaml not found at " + str(config_path))
        console.print("    Run [bold]probos init[/bold] to create one.")
        failures.append("missing_config")
    else:
        try:
            from probos.config import load_config
            cfg = load_config(config_path)
            console.print(f"  [green]\u2713[/green] Config: {config_path}")
        except Exception as exc:
            console.print(f"  [red]\u2717[/red] Config invalid: {exc}")
            failures.append("invalid_config")
            cfg = None

    # Check 2: data_dir writable
    data_dir = _default_data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".probos_doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        console.print(f"  [green]\u2713[/green] Data dir writable: {data_dir}")
    except Exception as exc:
        console.print(f"  [red]\u2717[/red] Data dir not writable: {data_dir} ({exc})")
        failures.append("data_dir_not_writable")

    # Check 3: LLM tier endpoints reachable (if config loaded)
    if cfg is not None:
        try:
            client = OpenAICompatibleClient(config=cfg.cognitive)
            connectivity = asyncio.run(client.check_connectivity())
            asyncio.run(client.close())
            for tier in ("fast", "standard", "deep"):
                tc = cfg.cognitive.tier_config(tier)
                if connectivity.get(tier):
                    console.print(
                        f"  [green]\u2713[/green] LLM {tier}: {tc['model']} reachable"
                    )
                else:
                    console.print(
                        f"  [yellow]\u26a0[/yellow] LLM {tier}: {tc['base_url']} unreachable"
                    )
                    failures.append(f"llm_{tier}_unreachable")
        except Exception as exc:
            console.print(f"  [yellow]\u26a0[/yellow] LLM connectivity probe failed: {exc}")
            failures.append("llm_probe_error")

    # Check 4: NATS reachable when enabled
    if cfg is not None and getattr(cfg, "nats", None) and cfg.nats.enabled:
        try:
            asyncio.run(_check_nats(cfg, console))
            console.print("  [green]\u2713[/green] NATS reachable")
        except Exception as exc:
            console.print(f"  [yellow]\u26a0[/yellow] NATS check error: {exc}")
            failures.append("nats_check_error")

    # Check 5: ChromaDB import-able
    try:
        import chromadb  # noqa: F401
        console.print("  [green]\u2713[/green] ChromaDB import OK")
    except Exception as exc:
        console.print(f"  [yellow]\u26a0[/yellow] ChromaDB import failed: {exc}")
        failures.append("chromadb_missing")

    console.print()
    if failures:
        console.print(f"[red]{len(failures)} issue(s):[/red] {', '.join(failures)}")
    else:
        console.print("[green]All checks passed.[/green]")
    return len(failures)
```

Register the subparser. SEARCH (around `__main__.py:1102` where `init_parser` is created):

```python
    init_parser = subparsers.add_parser("init", help="Create ~/.probos/ config")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    init_parser.add_argument("--probos-home", type=str, default=None, help="Custom config directory")
```

REPLACE:

```python
    init_parser = subparsers.add_parser("init", help="Create ~/.probos/ config")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config")
    init_parser.add_argument("--probos-home", type=str, default=None, help="Custom config directory")

    # AD-484: probos doctor -- diagnostic check
    subparsers.add_parser("doctor", help="Run a diagnostic check on the ProbOS environment")
```

Then in the `main()` dispatch (around `__main__.py:1140-1160`), find the `if args.command == "init":` block and add the doctor branch:

SEARCH (the existing init dispatch):
```python
    if args.command == "init":
        _cmd_init(args)
        return
```

REPLACE:
```python
    if args.command == "init":
        _cmd_init(args)
        return

    if args.command == "doctor":
        # AD-484: doctor returns non-zero exit code on failure
        import sys
        sys.exit(_cmd_doctor(args))
        return
```

> Verify-first: `_default_data_dir`, `_probos_home`, `OpenAICompatibleClient`, `_check_nats` are all already imported in the module (verified at `__main__.py:32-34, 38, 224`).

---

## Section 4: Quickstart docs

**File:** `docs/quickstart.md` (new)

```markdown
# ProbOS Quickstart -- 5 Minutes to First Conversation

This guide gets you from zero to talking with the ship's crew in five minutes.

## Prerequisites

- Python 3.12+
- ~500MB disk space
- One LLM endpoint (one of: local Ollama, GitHub Copilot proxy, Anthropic API key)

## Install

```bash
pip install probos
```

Or from source:

```bash
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
pip install -e .
```

## Initialize

```bash
probos init
```

ProbOS will detect available LLM providers and prompt you for an endpoint and
model. The defaults are sensible.

## Diagnostic check

```bash
probos doctor
```

This reports config, data-dir writability, LLM reachability, NATS (if enabled),
and ChromaDB. Resolve any red `x` marks before continuing.

## First conversation

```bash
probos
```

You will land in the interactive shell. Try:

```
> What can you do?
```

The Ship's Computer will respond. Try a slash command:

```
> /agents
```

This lists the registered crew. Each agent represents a domain capability.

## Next

- [Getting Started](getting-started.md) -- what ProbOS is and how it differs.
- [Architecture Overview](architecture/overview.md) -- the layered design.
- [Agent Concepts](agents/concepts.md) -- how the crew works.
```

**File:** `docs/getting-started.md` (new)

```markdown
# Getting Started with ProbOS

## What ProbOS Is

ProbOS is a probabilistic agent-native OS runtime -- a coordinated mesh of
domain agents that handle natural-language work via consensus voting,
Bayesian trust, and Hebbian-learned routing.

Unlike a single-agent assistant, ProbOS:

- **Decomposes** your request into a directed-acyclic graph of typed intents.
- **Routes** each intent to the agent best suited to handle it (learned weights).
- **Gates** destructive operations behind multi-agent consensus voting.
- **Records** every step in episodic memory for replay and continuous learning.

## Why It's Different

- **Agent-native**: every component is an autonomous agent. There is no central
  scheduler. Agents self-organize via capability matching.
- **Probabilistic consensus**: destructive ops require multi-agent quorum
  voting with confidence weighting and Shapley attribution.
- **Bayesian trust**: each agent carries a Beta(alpha, beta) reputation that
  the runtime updates after every interaction.
- **Self-modification**: capability gaps trigger LLM-based agent design,
  static analysis, and probationary trust before promotion.

## Where Things Live

- `~/.probos/config.yaml` -- your runtime configuration.
- `~/.probos/data/` -- episodic memory, trust DB, and runtime state.
- `~/.probos/knowledge/` -- the agent's knowledge repository.

## Next

- [Quickstart](quickstart.md) -- 5-minute install + first conversation.
- [Architecture Overview](architecture/overview.md) -- the layered design.
- [Agent Concepts](agents/concepts.md) -- how the crew works.
```

> Builder note: these files are stdlib-only Markdown. No static-site-generator change. Repository links use the canonical `seangalliher/ProbOS` URL (verified by reading the existing `pyproject.toml` author and the `git remote -v` URL).

---

## Tests

**File:** `tests/test_ad484_ux_adoption.py`

10 tests:

1. `test_pyproject_classifiers_includes_beta` -- read `pyproject.toml`, parse, confirm `Development Status :: 4 - Beta` present.
2. `test_pyproject_includes_project_urls` -- the `[project.urls]` table has `Homepage`/`Repository`/`Issues`.
3. `test_manifest_in_present_at_repo_root` -- `Path("MANIFEST.in").exists()`.
4. `test_quickstart_doc_present` -- `Path("docs/quickstart.md").exists()` and contains `"probos init"` and `"probos doctor"`.
5. `test_getting_started_doc_present` -- `Path("docs/getting-started.md").exists()` and contains `"probabilistic agent-native"`.
6. `test_doctor_subparser_registered` -- `argparse` parse `["doctor"]` resolves; `args.command == "doctor"`.
7. `test_detect_llm_providers_returns_dict` -- monkeypatch `httpx.Client` to return 200 from a fake URL; `_detect_llm_providers` returns `{"ollama": ...}` or similar. The function must NOT raise on connection errors.
8. `test_detect_llm_providers_anthropic_env_var` -- monkeypatch `os.environ["ANTHROPIC_API_KEY"]`; result includes `"anthropic"`.
9. `test_doctor_returns_nonzero_on_missing_config` -- monkeypatch `_probos_home` to a temp dir without `config.yaml`; `_cmd_doctor(args)` returns >= 1.
10. `test_doctor_returns_zero_on_clean_setup` -- `tmp_path`-based config + `tmp_path/data` writable + monkeypatched LLM connectivity returning all-true; `_cmd_doctor` returns 0.

Each test uses `MagicMock`/`monkeypatch`/`tmp_path`. No new pyproject deps.

---

## What This Does NOT Change

- Runtime semantics (`runtime.py`, `process_natural_language`, `intent_bus`) are unchanged.
- `_create_llm_client`, `_check_nats`, `_ensure_ollama` (existing primitives) are unchanged. AD-484 reuses them via `_cmd_doctor`.
- Existing `serve`, `reset` subparsers unchanged.
- **Homebrew formula deferred to AD-484b.** No `Formula/probos.rb` shipped.
- **`probos demo` mock mode deferred to AD-484b.**
- **HXI Holographic Glass Panels deferred to AD-484c.** UI work; out of scope.
- **Browser Automation (Playwright BrowseAgent) deferred to AD-484c.**
- AD-484 introduces NO new EventTypes, NO new pyproject dependencies, NO runtime attribute changes.

---

## Tracking

- `PROGRESS.md`: add `AD-484 CLOSED. UX & Adoption Readiness v1 (PyPI metadata + probos init TUI + probos doctor + quickstart docs) ...`
- `docs/development/roadmap.md`: flip AD-484 status from `*(planned)*` to `*(partial - v1 ships PyPI metadata + init wizard + doctor + docs; Homebrew/demo/HXI/Playwright deferred to AD-484b/c)*` near line 7024.
- `DECISIONS.md`: optional entry recording the v1-3-of-5 scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `pyproject.toml`: ~13 lines added (classifiers + project.urls).
- `MANIFEST.in`: ~6 lines (new).
- `src/probos/__main__.py`: ~150 lines added (rewritten _cmd_init + new _cmd_doctor + subparser + dispatch + _detect_llm_providers).
- `docs/quickstart.md`: ~50 lines (new).
- `docs/getting-started.md`: ~40 lines (new).
- `tests/test_ad484_ux_adoption.py`: ~210 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

Note: Section 2's REWRITE of `_cmd_init` deletes ~64 lines while adding ~95. Net positive but each edit shows substantial deletion in `git diff --cached --stat` for `__main__.py`. **Expected: ~70 deletions on `__main__.py` from the `_cmd_init` rewrite.** This is below the 200-deletion threshold but worth noting; Builder must confirm the rewrite is faithful (every existing `_cmd_init` behavior preserved) before committing.

---

## Acceptance Criteria

- All 10 tests pass under `pytest tests/test_ad484_ux_adoption.py -v -n 0`.
- Full parallel gate non-decreasing.
- `pyproject.toml` builds cleanly with `python -m build` (manual verification).
- `probos init` runs end-to-end (manual verification: ~/.probos/config.yaml created with Rich-formatted output).
- `probos doctor` runs end-to-end and returns non-zero exit code on a missing config (manual verification).
- `docs/quickstart.md` and `docs/getting-started.md` are valid Markdown.
- No new HARD pyproject deps; reuses `rich` (`pyproject.toml:25`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "_cmd_init\|_cmd_doctor\|probos doctor" src/probos/__main__.py
  542: def _cmd_init(args: argparse.Namespace) -> None:
  (no _cmd_doctor today; AD-484 introduces it)

grep -n "rich>=" pyproject.toml
  25:     "rich>=13.0",
  (already a hard dep; AD-484 reuses, no new deps)

ls docs/
  index.md, agents/, architecture/, design/, development/, ...
  (no quickstart.md or getting-started.md today)

grep -n "Console\|Panel\|Prompt" src/probos/__main__.py
  26: from rich.console import Console
  27: from rich.panel import Panel
  28: from rich.table import Table
  29: from rich.text import Text
  (Prompt is NOT imported today; AD-484 adds the scoped import)

grep -n "OpenAICompatibleClient\|_check_nats\|_default_data_dir\|_probos_home" src/probos/__main__.py
  32: from probos.cognitive.llm_client import MockLLMClient, OpenAICompatibleClient
  38: def _default_data_dir() -> Path:
  55: def _probos_home() -> Path:
  185: async def _create_llm_client(config, console: Console):
  224: async def _check_nats(config, console: Console) -> None:
  (all available for reuse in _cmd_doctor)

grep -n "init_parser\|serve_parser\|reset_parser" src/probos/__main__.py
  1102: init_parser = subparsers.add_parser("init", ...)
  1107: serve_parser = subparsers.add_parser("serve", ...)
  1120: reset_parser = subparsers.add_parser("reset", ...)
  (subparser pattern; AD-484 adds doctor between init and serve)

grep -n "version\s*=\|name\s*=" pyproject.toml
  6: name = "probos"
  7: version = "0.1.0"
  (PyPI metadata; AD-484 extends classifiers + adds project.urls)
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: no new runtime attributes. ✅
- #2 stdlib-only: yes; reuses Rich. ✅
- #3 Coordinator-then-dispatch: 3-of-5 deliverables ship; 2 deferred (Homebrew + demo) at draft time. ✅
- #4 Superset-filter: existing `_cmd_init` rewrite preserves all behavior. ✅
- #5 init_<phase>: N/A (CLI-time, not runtime startup). ✅
- #6 Verify-first: footer above. ✅
- #7 No-theater: real Rich prompts, real connectivity probes, real exit codes. No deferred deliverable is mentioned in Section 0/1/2/3 v1 scope. ✅
- #14 Aggressive pre-deferral: Homebrew, demo, HXI, Playwright all wholesale-deferred at draft time. ✅
