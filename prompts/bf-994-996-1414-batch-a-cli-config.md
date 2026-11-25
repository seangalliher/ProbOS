# BF-994 / BF-995 / BF-996 -- #1414 Batch A: CLI and configuration (A1, A2, A3)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-25
**Status:** ready to build. **Base:** the post-B15 tree (B15's head `8447d6ef`, which main holds after the merge); the pairs were drafted against `40f9305f`, and 6.14 and 6.17 are written against B15's tip. **Issue:** #1414 items 2, 3, 4, 5, 6, 7. **Suggested path:** `prompts/bf-994-996-1414-batch-a-cli-config.md`. **Estimated tests:** 3 new files, about 32 cases; 6 existing pins updated, each with its reason inline.

## 1. Problem

- **Item 2.**
  - `_cmd_init` sets `api_format = "ollama" if ":11434" in llm_url else "openai"` (`src/probos/__main__.py:1191`), while init's own Ollama default is `http://localhost:11434/v1` (`:1178-1179`).
  - The client gives every base a trailing slash (`llm_client.py:866`) and posts `api/chat` for the Ollama format (`:2494`), so the request goes to `/v1/api/chat`, which Ollama does not serve. The orchestrator's probe measured this on `40f9305f`.
  - The setup preset and the shipped config both use `/v1` with the OpenAI format.
- **Item 5.** `_render_init_config` (`__main__.py:1065-1098`) writes no timeout, so the 30.0 default applies (`config.py:319`); the shipped `config/system.yaml:33` sets 300.0. Setup's create path reuses the same scaffold (`__main__.py:1284-1291`).
- **Item 4.** `PROBOS_LLM_URL` replaces only the shared URL (`config.py:336-342`), and a tier's own URL wins (`config.py:715`). `docs/getting-started/configuration.md:73` and `docker-compose.yml:14-15` do not say so.
- **Item 6.** `_excerpt` cuts at 197 characters and appends ASCII `...` (`provider_setup.py:378`). `_result` then redacts again (`:388`), so a key of `.` turns the marker into three `<redacted>` (227 characters), and a key like `ab.` is completed across the cut.
- **Item 7.** Setup redacts only the key it is configuring (`__main__.py:1632`, `:1694`, `:1800-1804`). A different API key already in the file, such as the shared `llm_api_key`, prints wherever setup shows text from that file: a retained optional-tier model, or a refusal that quotes the file.
- **Item 3.** `POST /api/config` merges its patch onto `runtime.config.model_dump()` (`routers/config.py:246`) and writes that dump to disk (`:267`). Three consequences:
  - an edit made since boot (by `probos setup`, by hand, or by an earlier save awaiting restart) is reverted;
  - a second save before a restart reverts the first;
  - values the environment set (`PROBOS_LLM_URL`) are written into the file.

## 2. Solution

- **A1.**
  - New helper `_init_api_format` (D1), called from `_cmd_init`.
  - One scaffold line, `llm_timeout_seconds: 300.0` (D2).
  - One rewritten sentence in `configuration.md:73` and an accurate compose comment.
  - Rejected: changing the `CognitiveConfig` default, which would move the facade and profile baselines and every existing config.
- **A2.**
  - `_CUT_MARKER = "\u2026"` and a cut at 199 characters.
  - New `config_text_api_keys`.
  - The eight file-text print sites redact with `(chosen key, *file keys)`, passed through as `_SetupPlan.keys`.
  - Rejected: a Rich console that redacts everything it prints. Rich's highlighter and `escape` change the bytes of a key mid-text, and a short key could break markup at runtime.
- **A3.**
  - `drop_null_sections` in `config.py`, shared with `load_config`.
  - The router merges the patch onto the on-disk mapping, validates the result and writes it (D4).
  - Rejected: comparing a boot-time hash and refusing on mismatch. It needs runtime plumbing and still blocks a legitimate save.

## 3. Decisions

D1 to D7 as stated above this contract; they are recorded in `DECISIONS.md` (6.17).

## 4. Milestones and commit subjects

| M | Slice | Files | Commit subject |
|---|---|---|---|
| M1 | A1 | `src/probos/__main__.py`, `docs/getting-started/configuration.md`, `docker-compose.yml`, `tests/test_ad1135_provider_setup.py` (goldens), new `tests/test_bf994_init_config_reaches_its_api.py` | `init writes the OpenAI format for Ollama's /v1 default, and new configs get the shipped 300 s timeout (#1414 A1)` |
| M2 | A2 | `src/probos/provider_setup.py`, `src/probos/__main__.py`, `tests/test_ad1135_provider_setup.py` (two marker pins), new `tests/test_bf995_setup_redaction.py` | `setup keeps its provider excerpt within 200 characters and hides every API key the existing file holds (#1414 A2)` |
| M3 | A3 | `src/probos/config.py`, `src/probos/routers/config.py`, `src/probos/__main__.py` (setup note), `tests/test_bf908_crew_scope_token.py`, new `tests/test_bf996_hxi_save_on_disk.py` | `an HXI settings save merges its patch onto the config file as it is on disk (#1414 A3)` |
| M4 | artifacts and trackers | `docs/development/config-facade-baseline.yaml` (generated), `tests/test_ad1270e1_config_facade.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` (generated) | `trackers and generated artifacts for #1414 Batch A` |

**Overlap with B15** (from `git diff --stat 40f9305f feat/ad1355-s1-birth-chamber-removal-20261125`):

| File | Shared with B15 | Action on the post-B15 base |
|---|---|---|
| `src/probos/config.py` | yes (B15 deletes line 3947 and an import) | Re-prove 6.10. The `load_config` region is untouched by B15. |
| `docs/development/config-facade-baseline.yaml` | yes | Regenerate after B15 merges (M4). |
| `tests/test_ad1270e1_config_facade.py` | yes (B15 changes the same pins) | 6.14 is written against B15's tip. |
| `PROGRESS.md` | yes (B15 adds an entry at the top) | The 6.16 anchor `# ProbOS Progress` holds. |
| `DECISIONS.md` | yes (B15 adds the "Acclimation S1" entry at the top) | 6.17 is anchored on that heading. |
| ledger pair (`ad-ledger-snapshot.json`, `open-ads-report.md`) | yes | Regenerate after B15 merges (M4). |
| `config-reference.md`, `config-profiles.yaml`, `architecture-baseline.yaml`, `config/system.yaml` | B15 only | This batch moves none of them. |
| `src/probos/__main__.py`, `provider_setup.py`, `routers/config.py`, `docs/getting-started/configuration.md`, `docker-compose.yml`, `tests/test_ad1135_provider_setup.py`, `tests/test_bf908_crew_scope_token.py` | no | Re-prove anyway (cheap). |

## 5. Builder may / may not; Gates

**The Builder may:**
- change only the response body of the mock transport in `test_bf994_init_config_reaches_its_api.py` if the real client's parser rejects it; never the path assertions;
- if `complete()` sends no POST (the `posts` premise fails), drive the request through the client's internal call path instead, using a client built by its own constructor helper, and say why in a one-line comment;
- rewrap a comment to the line length.

**The Builder may not:**
- change any `CognitiveConfig` default or add a config field;
- change `load_config`'s behaviour for any input;
- touch `ui/`, the file-write census row (`tests/fixtures/ad1346_file_write_census.py:175` still holds) or any file B15 owns that is not listed in section 4;
- weaken or delete any existing assertion other than the pins listed (6.4, 6.9, 6.13, 6.14), each of which carries its reason inline;
- add `hasattr` or `getattr` guards;
- write a test that imports a new name at module level.

**Focused gates (interpreter `d:/ProbOS/.venv/Scripts/python.exe`, all `-n 0`):**
- M1: `-m pytest tests/test_bf994_init_config_reaches_its_api.py tests/test_ad1135_provider_setup.py tests/test_ad1135_setup_cli.py tests/test_claude_bootstrap_init_defaults.py "tests/test_distribution.py::TestProbOSInit" -q -n 0`
- M2: `-m pytest tests/test_bf995_setup_redaction.py tests/test_ad1135_provider_setup.py tests/test_ad1135_setup_cli.py tests/test_ad1137_doctor.py -q -n 0`
- M3: `-m pytest tests/test_bf996_hxi_save_on_disk.py tests/test_ad741_config_api.py tests/test_ad741_integration.py tests/test_ad741_secret_redaction.py tests/test_ad1270f_shutdown_grace.py tests/test_ad1356_s4_who_decides.py tests/test_bf908_crew_scope_token.py tests/test_ad1206_repair_issue.py tests/test_ad1137_doctor.py tests/test_ad1151_durable_tool_outputs.py -q -n 0`
- M4: the commands in section 7, then `-m pytest tests/test_ad1270e1_config_facade.py tests/test_ad1184_ad_ledger.py -q -n 0`

**Broad gate:** once, after M4: `scripts/run_test_gate.py --label 1414-batch-a --receipt logs/gates/1414-batch-a.receipt.json`.

**A/B red on the base `40f9305f`:** each new test file is red there for the reason given in its row; the new names are imported inside the tests that use them, so the other rows fail for their own reason, not on import.

## Verified Against Codebase (2026-11-25)

```
src/probos/__main__.py
  1030-1062: _detect_llm_providers; 1039 ("ollama", "http://localhost:11434")
  1065-1098: _render_init_config; 1082-1087 cognitive block, no timeout line
  1140: def _cmd_init; 1177-1181 default_url mapping to /v1; 1189-1191 api_format = "ollama" if ":11434" in llm_url
  1276-1291: _setup_scaffold reuses _render_init_config(api_format="openai", generated_by="probos setup")
  1568-1605: _setup_candidate (1586 refusal = str(exc); 1599 Cannot rewrite; 1601-1604 --force note)
  1627-1636: _setup_shared_url_notes, redact(model, api_key)
  1639-1684: _setup_report; 1659 notes call; 1681-1684 HXI note
  1687-1704: _setup_confirm_write; 1694 redact(..., choice.api_key); 1700 notes call
  1707-1717: _SetupPlan; 1720-1771: _setup_plan (1736-1743 read + Cannot edit); 1774-1815: _cmd_setup (1798-1805 write failure)
src/probos/cognitive/llm_client.py
  268 class OpenAICompatibleClient; 857-874 _build_client (866 rstrip("/") + "/"); 1462 complete; 2383 post("chat/completions"); 2494 post("api/chat")
src/probos/config.py
  9 from typing import Any, Literal; 11 import yaml; 319 llm_timeout_seconds: float = 30.0; 336-342 PROBOS_LLM_URL override
  714-719 tier_config base_url/timeout/api_format fallbacks; 4157-4167 load_config (4166 None-section strip)
config/system.yaml:33  llm_timeout_seconds: 300.0
src/probos/provider_setup.py
  131 ConfigEditRefused; 135 ConfigReplaceFailed(OSError); 183-198 validate_key_transport (191 printable ASCII)
  277 _EXCERPT_MAX_CHARS = 200; 278 _REDACTED; 302-321 redact; 324-328 redact_keys; 331-334 configured_api_keys
  373-378 _excerpt; 381-388 _result; 443 _excerpt's one caller; 492 probe_chat; 576-588 parse_config_text
  720-742 rewrite_with_managed_values (does not call apply_managed_values); 787-813 optional_tier_endpoints; 886 write_config_atomic
src/probos/routers/config.py
  10-11 POST docstring; 34 from probos.config import SystemConfig; 120-128 _deep_merge; 146-161 _write_yaml_atomic
  232-244 secret guard; 246-260 runtime merge + 422; 262-267 config_path 503 + write of model_dump; 280 changed_fields; 286-303 hot reload
src/probos/doctor/checks/llm_check.py:194,208  probe_models / probe_chat (the doctor shows the excerpt too)
ui/src/store/useSettingsStore.ts:196-229  200/422/400/403 branches; 224-228 generic "APPLY failed (status): error"
tests/test_ad1135_provider_setup.py  57-65 _INIT_GOLDENS; 84-105 golden test; 424-425 and 470 endswith("...")
tests/test_bf908_crew_scope_token.py:829-832  asserts the dumped auth.crew_scope_token == ""
tests/test_ad1270e1_config_facade.py  (B15 tip) public_names 309 / owned 296 / len(names) 309 / "names=309"
docs/development/config-facade-baseline.yaml  48-55 surface_counts; 444-445 format_trust/load_config {kind: function, tier: owned}
scripts/check_config_facade.py:1237-1241  facade-symbol-added for a public name with no row
scripts/gen_ad_ledger.py  126-139 status words, 120-char head window; 207-220 a DECISIONS heading with no status word = shipped
scripts/run_test_gate.py:1097-1130  preflight phases
docs/getting-started/configuration.md:73; docker-compose.yml:14-15; Dockerfile:16 (--no-editable), 49-50 (no --config)
```

## Absence Verified (2026-11-25)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Only the init goldens pin the scaffold's bytes | Grep `llm_timeout_seconds\|llm_api_format_fast\|_render_init_config\|_setup_scaffold\|_cmd_init` in `tests/` | `test_ad1135_provider_setup.py:84-105` (bytes); `:137`, `test_ad1135_setup_cli.py:612-636`, `test_distribution.py:978-1044` and `test_claude_bootstrap_init_defaults.py` compare at the YAML or profile level | yes |
| No test calls a setup helper whose signature changes | Grep `_setup_shared_url_notes\|_SetupPlan\|_setup_candidate\|_setup_report\|_setup_confirm_write\|_setup_plan\(` in `tests/` | unrelated hits only (`test_ci_shards.py:815`, `test_ci_shard_pytest_plugin.py:218`) | yes |
| Only two tests pin the `...` marker | Grep `endswith\("\.\.\."\)` in `tests/` | `test_ad1135_provider_setup.py:425`, `:470` | yes |
| `_excerpt` has one caller | Grep `_excerpt\|_EXCERPT_MAX_CHARS` in `src/` | `provider_setup.py:443` (the `stand_down.py` and `continue_or_ask.py` `_excerpt` functions are different ones) | yes |
| No test pins setup's HXI note | Grep `booted with\|settings save\|running HXI` in `tests/` | 2 unrelated hits | yes |
| Only `test_bf908:832` reads a section the on-disk save no longer writes | Read every file-reading POST test: `test_ad741_config_api.py`, `test_ad741_integration.py`, `test_ad741_secret_redaction.py`, `test_ad1270f_shutdown_grace.py:246-308`, `test_ad1356_s4_who_decides.py:112-128`, `test_bf908_crew_scope_token.py:810-832` | only `:832` (`auth`) | yes |
| No profile pins the init scaffold | Grep `_render_init_config\|probos init\|scaffold` in `config-profiles.yaml` and `check_config_profiles.py` | none | yes |
| No cognitive API key has a validation alias | Grep `AliasChoices\(\|validation_alias` in `config.py` | `:2675` only (`warning_chars`) | yes |
| `urlsplit` is not imported in `__main__.py` | Grep `urlsplit\|^from urllib` | none | the helper imports it locally |
| BF-994 to BF-996 are free | Glob `prompts/**/bf-99*`; `git log --all -i --grep "BF-99[4-9]"`; Grep trackers and ledger; `gh issue list --state all --search` | top is `bf-993`; none; none; no title hit | yes |
| The UI needs no change for a 409 | Read `useSettingsStore.ts:196-229` | the generic branch shows the status and `error` | yes |
| The census row holds | Read `tests/fixtures/ad1346_file_write_census.py:175` | "_write_yaml_atomic: a YAML dump of the data it is passed, under a timestamp header" | yes (still that function) |
| `yaml.safe_load` fails only with `YAMLError` | Ran `yaml.safe_load` (PyYAML 6.0.3) on an impossible date, an integer of 10,000 digits and 5,000 nested brackets, and `provider_setup.parse_config_text` on the date and the nesting (2026-11-25) | `ValueError`, `ValueError` and `RecursionError`, none a `YAMLError`; `parse_config_text` lets the same two through, as it did before this batch | no: 6.11's `_read_disk_mapping` catches all three; `parse_config_text` is left alone (blind spot 7) |

## Prior Art and Blind Spots

- **External search:** skipped. This is ProbOS-specific CLI and config plumbing with no outside design question.
- **Blind spots:**
  1. The doctor's provider messages show the new marker, because they also go through `probe_chat`.
  2. U+2026 on a Windows legacy console: setup already prints U+2713, U+2717 and U+26A0 through Rich, so this adds no new encoding risk.
  3. Keys read from the file are not validated. A one- or two-character key will heavily redact setup's file-derived messages, and a key that is part of `<redacted>` can mangle markers. This is cosmetic, and the boot banner already behaves the same way.
  4. A 409 consumes the CSRF token, exactly as a 422 does today.
  5. An HXI save still drops the file's comments (unchanged). Setup's note now says so.
  6. Secrets other than API keys in the file (for example `auth.crew_scope_token`) are out of item 7's scope. Considered, deferred: the doctor's `_secrets` scan could be promoted to a shared helper later.
  7. `provider_setup.parse_config_text` catches only `YAMLError`, so `probos setup` on a file holding an impossible date, an integer of over 4,300 digits or nesting past the recursion limit ends in a traceback instead of `ConfigEditRefused`. That predates this batch and is outside items 6 and 7; it is recorded for the follow-up wave. The HXI save's new reader does not share it (6.11).

## 6. Pairs

### 6.1 `src/probos/__main__.py` (M1)

**P-1**
SEARCH:
```
cognitive:
  default_llm_tier: "fast"
  llm_base_url_fast: "{llm_url}"
```
REPLACE:
```
cognitive:
  default_llm_tier: "fast"
  llm_timeout_seconds: 300.0
  llm_base_url_fast: "{llm_url}"
```

**P-2**
SEARCH:
```
def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
```
REPLACE:
```
def _init_api_format(llm_url: str) -> str:
    """#1414 item 2: ``ollama`` only for an Ollama root (port 11434, no path); ``openai`` for every other URL.

    The client posts ``api/chat`` under an ``ollama`` base and ``chat/completions`` under an ``openai`` one,
    so init's own Ollama default, ``http://localhost:11434/v1``, is Ollama's OpenAI-compatible API. A URL
    whose port does not parse is ``openai``, as it was for any URL without ``:11434``.
    """
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(llm_url)
        port = parts.port
    except ValueError:
        return "openai"
    return "ollama" if port == 11434 and parts.path.strip("/") == "" else "openai"


def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
```

**P-3**
SEARCH:
```
    llm_model = Prompt.ask("  LLM model", default=default_model, console=console)

    api_format = "ollama" if ":11434" in llm_url else "openai"
```
REPLACE:
```
    llm_model = Prompt.ask("  LLM model", default=default_model, console=console)

    api_format = _init_api_format(llm_url)
```

### 6.2 `docs/getting-started/configuration.md` (M1)

U+2014 (EM DASH) occurs once in this SEARCH, after "from the environment". The REPLACE is ASCII.

**P-1**
SEARCH:
```
A few settings can be overridden from the environment — for example `PROBOS_NATS_ENABLED=false` runs without NATS, and `PROBOS_LLM_URL` replaces the shared LLM base URL. ProbOS also loads a `.env` file at startup; see [`.env.example`](https://github.com/seangalliher/ProbOS/blob/main/.env.example). Use `--data-dir DIR` to choose the data directory.
```
REPLACE:
```
A few settings can be overridden from the environment: for example `PROBOS_NATS_ENABLED=false` runs without NATS, and `PROBOS_LLM_URL` replaces the shared LLM base URL (`cognitive.llm_base_url`). A tier that sets its own `llm_base_url_<tier>` keeps that URL, so `PROBOS_LLM_URL` reaches only the tiers without one; a config written by `probos init` sets one for the fast tier, and `probos setup` sets one for the fast, standard and deep tiers. ProbOS also loads a `.env` file at startup; see [`.env.example`](https://github.com/seangalliher/ProbOS/blob/main/.env.example). Use `--data-dir DIR` to choose the data directory.
```

### 6.3 `docker-compose.yml` (M1)

**P-1**
SEARCH:
```
      # LLM config: set your provider URL
      # - PROBOS_LLM_URL=http://ollama:11434/v1
```
REPLACE:
```
      # LLM config: PROBOS_LLM_URL replaces only the shared llm_base_url. With no config
      # file every tier uses it; a config that gives a tier its own llm_base_url_<tier>
      # keeps that URL for the tier.
      # - PROBOS_LLM_URL=http://ollama:11434/v1
```

### 6.4 `tests/test_ad1135_provider_setup.py` (M1)

The lengths below are arithmetic: the new line is 29 bytes, and `openai` is as long as `ollama`. The sha256 values must be measured.

**P-1**
SEARCH:
```
# Captured at 164e575b (contract section 1.4): CRLF -> LF, home.as_posix() -> <HOME>.
_INIT_GOLDENS = [
    ("strict", "https://api.example.com/v1", "model-x", 979,
     "93310b2a62c79becd5e969d256c29515647e2ba2ed1f82442511b17032945a74"),
    ("relaxed", "https://api.example.com/v1", "model-x", 774,
     "05556e840eb18afb9c65ff60b50fe9c6c22950cf3e880b5e7a6cd0ab21182afd"),
    ("strict", "http://localhost:11434/v1", "llama3.1:8b", 982,
     "d07186a043e8ced2e14633faae2614c2b49c71e37ece8593c7a2509c26658aae"),
]
```
REPLACE:
```
# Captured at 164e575b (contract section 1.4): CRLF -> LF, home.as_posix() -> <HOME>.
# Re-captured for #1414 A1: every row gains "  llm_timeout_seconds: 300.0" (+29 bytes), and the Ollama
# /v1 row writes llm_api_format_fast "openai" instead of "ollama" (same length).
_INIT_GOLDENS = [
    ("strict", "https://api.example.com/v1", "model-x", 1008,
     "c3fd4610adc7e9b5a15cb62324bd3b45333ad1ab526cde3cad196d79758fa6a8"),
    ("relaxed", "https://api.example.com/v1", "model-x", 803,
     "f0b1e9c69533a01c74175e234ebff910a99663d0ab8ed08a2c773f6fa9dfc9ce"),
    ("strict", "http://localhost:11434/v1", "llama3.1:8b", 1011,
     "72002a06ed08f9e5f325b6f740f27f902051e58084307806bc8a17325b76e534"),
]
```

### 6.5 `tests/test_bf994_init_config_reaches_its_api.py` new file (M1)

```python
"""BF-994 (#1414 Batch A, slice A1): the config `probos init` writes reaches the API its URL serves.

Item 2: init's Ollama default is Ollama's OpenAI-compatible /v1 API, so it is written with the openai
format; only a bare Ollama root (port 11434, no path) keeps the native format. Item 5: the scaffold that
init and setup's create path share sets llm_timeout_seconds: 300.0, the shipped config/system.yaml value;
an existing file is not given one.
"""
from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from rich.console import Console

import probos.__main__ as main_mod
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import load_config
from probos.types import LLMRequest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEXT_TIERS = ("fast", "standard", "deep")
_ENV = ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_SETUP_OFFLINE = (
    "--provider", "custom", "--base-url", "https://llm.example.test/v1", "--model", "model-x",
    "--skip-validation", "--yes",
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml")
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _no_detection(console: object) -> dict[str, str]:
    raise AssertionError("setup probed for local providers, which this test does not script")


def _init(monkeypatch: pytest.MonkeyPatch, home: Path, detected: dict[str, str], *answers: str) -> dict[str, Any]:
    """Run the real _cmd_init; each prompt takes the next answer, or its own default once none is left."""
    pending = list(answers)
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=StringIO()))
    monkeypatch.setattr(
        "rich.prompt.Prompt.ask", lambda *args, **kwargs: pending.pop(0) if pending else kwargs["default"],
    )
    main_mod._cmd_init(argparse.Namespace(force=True, probos_home=str(home), security_profile="strict"))
    assert not pending  # premise: init asked for every scripted answer
    return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))


def _setup_args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["setup", *argv])


def _timeouts(path: Path) -> dict[str, float]:
    cognitive = load_config(path).cognitive
    return {tier: cognitive.tier_config(tier)["timeout"] for tier in _TEXT_TIERS}


async def _chat_posts(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Send one request through the real client built from ``config_path``; return the paths it POSTed."""
    posts: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request.url.path)
        # One body both formats read: Ollama's native message and the OpenAI choices.
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={
            "model": "m", "message": message, "done": True,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}], "usage": {},
        })

    real_client = httpx.AsyncClient

    class _Recorded(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(answer)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Recorded)
    client = OpenAICompatibleClient(config=load_config(config_path).cognitive)
    try:
        await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    return posts


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("http://localhost:11434/v1", "openai"),
        ("http://localhost:11434/v1/", "openai"),
        ("http://localhost:11434", "ollama"),
        ("http://localhost:11434/", "ollama"),
        ("http://127.0.0.1:8080/v1", "openai"),
        ("http://127.0.0.1:8080", "openai"),
        ("http://localhost:114340/v1", "openai"),
    ],
    ids=["ollama-v1", "ollama-v1-slash", "ollama-root", "ollama-root-slash", "proxy-v1", "other-root", "port-out-of-range"],
)
def test_init_writes_the_format_the_typed_url_serves(
    typed: str, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = _init(monkeypatch, tmp_path / "init", {}, typed, "llama3.1:8b")

    assert written["cognitive"]["llm_base_url_fast"] == typed  # premise: init kept the URL as typed
    assert written["cognitive"]["llm_api_format_fast"] == expected


@pytest.mark.parametrize(
    ("detected", "answers", "url", "path"),
    [
        ({"ollama": "http://localhost:11434"}, (), "http://localhost:11434/v1", "/v1/chat/completions"),
        ({}, ("http://localhost:11434", "llama3.1:8b"), "http://localhost:11434", "/api/chat"),
    ],
    ids=["detected-default", "bare-root"],
)
async def test_the_init_config_reaches_the_api_its_url_serves(
    detected: dict[str, str], answers: tuple[str, ...], url: str, path: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "init"
    written = _init(monkeypatch, home, detected, *answers)
    assert written["cognitive"]["llm_base_url_fast"] == url  # premise: the accepted default, or the typed root

    posts = await _chat_posts(home / "config.yaml", monkeypatch)

    assert posts, "premise: the client sent its request"
    assert posts[0] == path  # before #1414 the detected default posted /v1/api/chat


def test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "init"
    _init(monkeypatch, home, {}, "https://api.example.com/v1", "model-x")
    shipped = yaml.safe_load((_REPO_ROOT / "config" / "system.yaml").read_text(encoding="utf-8"))
    assert shipped["cognitive"]["llm_timeout_seconds"] == 300.0  # premise: the value the scaffold copies

    assert _timeouts(home / "config.yaml") == dict.fromkeys(_TEXT_TIERS, 300.0)


def test_setup_create_path_writes_the_shipped_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    config = tmp_path / "home" / "config.yaml"
    assert not config.exists()  # premise: setup creates it from init's scaffold

    assert main_mod._cmd_setup(_setup_args(*_SETUP_OFFLINE)) == 0

    assert _timeouts(config) == dict.fromkeys(_TEXT_TIERS, 300.0)


def test_setup_on_an_existing_file_adds_no_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    config = tmp_path / "home" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("cognitive:\n  llm_model_fast: old\n", encoding="utf-8")

    assert main_mod._cmd_setup(_setup_args(*_SETUP_OFFLINE)) == 0

    assert "llm_timeout_seconds" not in yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]
    assert load_config(config).cognitive.llm_timeout_seconds == 30.0  # an existing config keeps its default
```

On the base, these rows are red: `ollama-v1`, `ollama-v1-slash`, `port-out-of-range`, `detected-default` (it posts to `/v1/api/chat`), the init-scaffold timeout row and the setup create-path row. These are green on the base and guard against mutants: `ollama-root`, `ollama-root-slash`, `proxy-v1`, `other-root`, `bare-root` and `test_setup_on_an_existing_file_adds_no_timeout`.

### 6.6 `src/probos/provider_setup.py` (M2)

**P-1**
SEARCH:
```
_EXCERPT_MAX_CHARS = 200
_REDACTED = "<redacted>"
```
REPLACE:
```
_EXCERPT_MAX_CHARS = 200
# #1414 item 6: U+2026 marks a cut excerpt. No form of a key setup accepts can hold it: such keys are printable
# ASCII (validate_key_transport) and every form of an ASCII key is ASCII.
_CUT_MARKER = "\u2026"
_REDACTED = "<redacted>"
```

**P-2**
SEARCH:
```
def configured_api_keys(cognitive: CognitiveConfig) -> list[str]:
    """Every API key some tier would send (a tier without its own sends the shared one), longest first."""
    keys = {cognitive.tier_config(tier)["api_key"] for tier in (*TEXT_TIERS, *OPTIONAL_TIERS)}
    return sorted((key for key in keys if key), key=lambda key: (-len(key), key))
```
REPLACE:
```
def configured_api_keys(cognitive: CognitiveConfig) -> list[str]:
    """Every API key some tier would send (a tier without its own sends the shared one), longest first."""
    keys = {cognitive.tier_config(tier)["api_key"] for tier in (*TEXT_TIERS, *OPTIONAL_TIERS)}
    return sorted((key for key in keys if key), key=lambda key: (-len(key), key))


def config_text_api_keys(text: str | None) -> list[str]:
    """Every non-empty ``cognitive.llm_api_key*`` string in config ``text``, longest first; ``[]`` for None.

    #1414 item 7: setup redacts these, as well as the key it is configuring, wherever it prints text read
    from the existing file. They are read without validation, so a file that does not load still names
    its keys. Raises ConfigEditRefused, as parse_config_text does, when ``text`` is not a YAML mapping.
    """
    if text is None:
        return []
    section = parse_config_text(text).get("cognitive")
    if not isinstance(section, dict):
        return []
    keys = {
        value
        for name, value in section.items()
        if str(name).startswith("llm_api_key") and isinstance(value, str) and value
    }
    return sorted(keys, key=lambda key: (-len(key), key))
```

**P-3**
SEARCH:
```
    printable = "".join(ch if ch.isprintable() else " " for ch in redact(text, api_key))
    line = redact(" ".join(printable.split()), api_key)
    return line if len(line) <= _EXCERPT_MAX_CHARS else line[: _EXCERPT_MAX_CHARS - 3] + "..."
```
REPLACE:
```
    printable = "".join(ch if ch.isprintable() else " " for ch in redact(text, api_key))
    line = redact(" ".join(printable.split()), api_key)
    # #1414 item 6: _result redacts the message again. With an ASCII "..." marker a key of "." made the excerpt
    # 227 characters, and a key such as "ab." was completed across the cut; _CUT_MARKER can do neither.
    return line if len(line) <= _EXCERPT_MAX_CHARS else line[: _EXCERPT_MAX_CHARS - 1] + _CUT_MARKER
```

### 6.7 `src/probos/__main__.py` (M2)

**P-1**
SEARCH:
```
def _setup_candidate(
    args: argparse.Namespace,
    console: Console,
    target: Path,
    existing: str | None,
    values: dict[str, str],
) -> str | int:
    """Return the text setup would install (AD-1135 Q2), or print why not and return the exit code."""
```
REPLACE:
```
def _setup_candidate(
    args: argparse.Namespace,
    console: Console,
    target: Path,
    existing: str | None,
    values: dict[str, str],
    keys: tuple[str, ...],
) -> str | int:
    """Return the text setup would install (AD-1135 Q2), or print why not and return the exit code.

    ``keys`` (the chosen key and every one the existing file holds) are redacted from each refusal,
    which can quote the existing file (#1414 item 7).
    """
```

**P-2**
SEARCH:
```
    try:
        return provider_setup.apply_managed_values(scaffold, values)
    except provider_setup.ConfigEditRefused as exc:
        refusal = str(exc)
```
REPLACE:
```
    try:
        return provider_setup.apply_managed_values(scaffold, values)
    except provider_setup.ConfigEditRefused as exc:
        refusal = provider_setup.redact_keys(str(exc), keys)
```

**P-3**
SEARCH:
```
    except provider_setup.ConfigEditRefused as exc:
        console.print(f"[red]Cannot rewrite {escape(str(target))}:[/red] {escape(str(exc))}")
        return 4
```
REPLACE:
```
    except provider_setup.ConfigEditRefused as exc:
        shown = provider_setup.redact_keys(str(exc), keys)
        console.print(f"[red]Cannot rewrite {escape(str(target))}:[/red] {escape(shown)}")
        return 4
```

**P-4**
SEARCH:
```
def _setup_shared_url_notes(console: Console, shared_url_tiers: dict[str, str], api_key: str) -> None:
    """Name each optional tier that kept the shared llm_base_url in place (AD-1135 B7), one line per tier."""
    from rich.markup import escape

    for tier, model in shared_url_tiers.items():
        shown = provider_setup.redact(model, api_key)  # read from the existing file, which can hold the key
```
REPLACE:
```
def _setup_shared_url_notes(console: Console, shared_url_tiers: dict[str, str], keys: tuple[str, ...]) -> None:
    """Name each optional tier that kept the shared llm_base_url in place (AD-1135 B7), one line per tier."""
    from rich.markup import escape

    for tier, model in shared_url_tiers.items():
        # Read from the existing file, which can hold the chosen key or one it already had (#1414 item 7).
        shown = provider_setup.redact_keys(model, keys)
```

**P-5**
SEARCH:
```
    backup: Path | None,
    *,
    api_key: str,
    shared_url_tiers: dict[str, str],
) -> None:
    """Print what setup wrote; of the key, only its presence is ever shown."""
```
REPLACE:
```
    backup: Path | None,
    *,
    api_key: str,
    shared_url_tiers: dict[str, str],
    keys: tuple[str, ...],
) -> None:
    """Print what setup wrote; of the key, only its presence is ever shown."""
```

**P-6**
SEARCH:
```
        console.print(f"  Backup: {escape(str(backup))}")
    _setup_shared_url_notes(console, shared_url_tiers, api_key)
```
REPLACE:
```
        console.print(f"  Backup: {escape(str(backup))}")
    _setup_shared_url_notes(console, shared_url_tiers, keys)
```

**P-7**
SEARCH:
```
def _setup_confirm_write(
    console: Console, target: Path, choice: provider_setup.ProviderChoice, shared_url_tiers: dict[str, str],
) -> bool:
    """Show what would be written, the key only as present or not, and ask the final question (M4)."""
    from rich.markup import escape
    from rich.prompt import Confirm

    shown = {tier: provider_setup.redact(choice.models[tier], choice.api_key) for tier in provider_setup.TEXT_TIERS}
```
REPLACE:
```
def _setup_confirm_write(
    console: Console,
    target: Path,
    choice: provider_setup.ProviderChoice,
    shared_url_tiers: dict[str, str],
    keys: tuple[str, ...],
) -> bool:
    """Show what would be written, the key only as present or not, and ask the final question (M4)."""
    from rich.markup import escape
    from rich.prompt import Confirm

    shown = {tier: provider_setup.redact_keys(choice.models[tier], keys) for tier in provider_setup.TEXT_TIERS}
```

**P-8**
SEARCH:
```
    _setup_shared_url_notes(console, shared_url_tiers, choice.api_key)
```
REPLACE:
```
    _setup_shared_url_notes(console, shared_url_tiers, keys)
```

**P-9**
SEARCH:
```
    candidate: str
    kept: dict[str, provider_setup.TierEndpoint]
    shared_url_tiers: dict[str, str]
```
REPLACE:
```
    candidate: str
    kept: dict[str, provider_setup.TierEndpoint]
    shared_url_tiers: dict[str, str]
    keys: tuple[str, ...]  # the chosen API key and every one the existing file holds (#1414 item 7)
```

**P-10**
SEARCH:
```
    kept: dict[str, provider_setup.TierEndpoint] = {}
    if target.exists():
        try:
            existing, had_bom = provider_setup.read_config_text(target)
            # Not YAML, or optional-tier settings that do not load: exit 4 before anything else, --force included.
            kept = provider_setup.optional_tier_endpoints(existing)
        except provider_setup.ConfigEditRefused as exc:
            console.print(f"[red]Cannot edit {escape(str(target))}:[/red] {escape(str(exc))}")
            return 4
```
REPLACE:
```
    kept: dict[str, provider_setup.TierEndpoint] = {}
    file_keys: tuple[str, ...] = ()
    if target.exists():
        try:
            existing, had_bom = provider_setup.read_config_text(target)
            # Not YAML, or optional-tier settings that do not load: exit 4 before anything else, --force included.
            file_keys = tuple(provider_setup.config_text_api_keys(existing))
            kept = provider_setup.optional_tier_endpoints(existing)
        except provider_setup.ConfigEditRefused as exc:
            shown = provider_setup.redact_keys(str(exc), file_keys)  # #1414 item 7: a refusal can quote the file
            console.print(f"[red]Cannot edit {escape(str(target))}:[/red] {escape(shown)}")
            return 4
```

**P-11**
SEARCH:
```
    choice, listing = chosen
    shared_url_tiers = provider_setup.tiers_using_shared_url(kept)  # B7: these keep the shared URL where it is
    values = provider_setup.managed_values(choice, retain_shared_url=bool(shared_url_tiers))
    candidate = _setup_candidate(args, console, target, existing, values)
```
REPLACE:
```
    choice, listing = chosen
    keys = (choice.api_key, *file_keys)
    shared_url_tiers = provider_setup.tiers_using_shared_url(kept)  # B7: these keep the shared URL where it is
    values = provider_setup.managed_values(choice, retain_shared_url=bool(shared_url_tiers))
    candidate = _setup_candidate(args, console, target, existing, values, keys)
```

**P-12**
SEARCH:
```
    if not args.yes and not _setup_confirm_write(console, target, choice, shared_url_tiers):
        return 1
    return _SetupPlan(target, existing, had_bom, choice, values, candidate, kept, shared_url_tiers)
```
REPLACE:
```
    if not args.yes and not _setup_confirm_write(console, target, choice, shared_url_tiers, keys):
        return 1
    return _SetupPlan(target, existing, had_bom, choice, values, candidate, kept, shared_url_tiers, keys)
```

**P-13**
SEARCH:
```
    except (provider_setup.ConfigEditRefused, OSError) as exc:
        key = plan.choice.api_key  # B9: the target path, and so an OSError that names it, can hold the key
        target = escape(provider_setup.redact(str(plan.target), key))
        console.print(f"[red]Could not write {target}:[/red] {escape(provider_setup.redact(str(exc), key))}")
        if isinstance(exc, provider_setup.ConfigReplaceFailed):
            backup = escape(provider_setup.redact(str(exc.backup), key))
            console.print(f"  It was not replaced; the backup taken first is kept at {backup}")
        return 4
    _setup_report(
        console,
        plan.target,
        plan.existing,
        plan.values,
        backup,
        api_key=plan.choice.api_key,
        shared_url_tiers=plan.shared_url_tiers,
    )
```
REPLACE:
```
    except (provider_setup.ConfigEditRefused, OSError) as exc:
        # B9: the target path, and so an OSError that names it, can hold the key; #1414 item 7: the verify
        # step's refusal can quote the file, which can hold another key.
        keys = plan.keys
        target = escape(provider_setup.redact_keys(str(plan.target), keys))
        console.print(f"[red]Could not write {target}:[/red] {escape(provider_setup.redact_keys(str(exc), keys))}")
        if isinstance(exc, provider_setup.ConfigReplaceFailed):
            backup = escape(provider_setup.redact_keys(str(exc.backup), keys))
            console.print(f"  It was not replaced; the backup taken first is kept at {backup}")
        return 4
    _setup_report(
        console,
        plan.target,
        plan.existing,
        plan.values,
        backup,
        api_key=plan.choice.api_key,
        shared_url_tiers=plan.shared_url_tiers,
        keys=plan.keys,
    )
```

### 6.8 `tests/test_bf995_setup_redaction.py` new file (M2)

```python
"""BF-995 (#1414 Batch A, slice A2): setup's messages show no API key, its own or one the file already holds.

Item 6: the provider excerpt is cut with U+2026, which no form of a key holds, so _result's second
redaction cannot take it past 200 characters. Item 7: wherever setup prints text read from the existing
config, it redacts every cognitive.llm_api_key* value that file holds, as well as the key it is configuring.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import pytest
import yaml

import probos.__main__ as main_mod
from probos import provider_setup as ps

_BASE = "https://llm.example.test/v1"
_CHOSEN = "sk-bf995-chosen-key-4Q7Z"
_OTHER = "sk-bf995-other-secret-9X2W"
_KEY_ENV = "PROBOS_TEST_BF995_KEY"
_ENV = ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_MARKER = "\u2026"


def _no_detection(console: object) -> dict[str, str]:
    raise AssertionError("setup probed for local providers, which this test does not script")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml")
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv(_KEY_ENV, _CHOSEN)


def _setup(*extra: str) -> int:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args([
        "setup", "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV,
        "--model", "model-x", "--skip-validation", "--yes", *extra,
    ])
    return main_mod._cmd_setup(args)


def _existing(tmp_path: Path, *cognitive_lines: str) -> Path:
    config = tmp_path / "home" / "config.yaml"
    config.parent.mkdir(parents=True)
    lines = ["cognitive:", "  llm_base_url: http://127.0.0.1:8080/v1", *cognitive_lines]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _printed(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


def _excerpt_of(api_key: str, body: str) -> str:
    transport = httpx.MockTransport(lambda request: httpx.Response(400, text=body))
    result = ps.probe_chat(_BASE, api_key, "model-x", transport=transport)
    assert result.outcome is ps.ProbeOutcome.REQUEST_REJECTED  # premise: the 400 branch, which shows an excerpt
    return result.message.split("(HTTP 400): ", 1)[1]


def test_the_excerpt_for_a_key_of_dots_stays_at_200_characters() -> None:
    detail = _excerpt_of(".", "." * 300)

    assert (len(detail), detail[-1]) == (200, _MARKER)  # 227 before #1414: _result redacted the "..."
    assert "." not in detail


def test_the_cut_completes_no_key() -> None:
    detail = _excerpt_of("ab.", "x" * 195 + "ab" + "y" * 100)

    assert (len(detail), detail[-1]) == (200, _MARKER)  # before #1414 the cut wrote "ab..." and so the key
    assert "<redacted>" not in detail


@pytest.mark.parametrize("field", ["llm_api_key", "llm_api_key_vision", "llm_api_key_verifier"])
def test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted(
    field: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _existing(tmp_path, f"  {field}: {_OTHER}", f"  llm_model_vision: {_OTHER}")

    assert _setup() == 0

    out = _printed(capsys)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]["llm_model_vision"] == _OTHER  # premise
    assert "vision (model '<redacted>') uses it" in out  # the B7 note names the tier; its model is the file's key
    assert _OTHER not in out


def _refuse_quoting_the_file(*args: object, **kwargs: object) -> object:
    raise ps.ConfigEditRefused(f"the setting quotes {_OTHER}")


@pytest.mark.parametrize(
    ("seam", "extra", "code"),
    [
        ("optional_tier_endpoints", (), 4),
        ("apply_managed_values", (), 4),
        ("apply_managed_values", ("--force",), 0),
    ],
    ids=["reading-the-file", "editing-the-file", "force-rewrite-note"],
)
def test_a_refusal_quoting_the_file_prints_no_key_from_it(
    seam: str, extra: tuple[str, ...], code: int,
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _existing(tmp_path, f"  llm_api_key: {_OTHER}")
    monkeypatch.setattr(ps, seam, _refuse_quoting_the_file)

    assert _setup(*extra) == code

    out = _printed(capsys)
    assert "the setting quotes <redacted>" in out  # premise: the refusal was printed
    assert _OTHER not in out


def test_a_write_failure_quoting_the_file_prints_no_key_from_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _existing(tmp_path, f"  llm_api_key: {_OTHER}")

    def fail(*args: object, **kwargs: object) -> object:
        raise OSError(f"no space left beside {_OTHER}")

    monkeypatch.setattr(ps, "write_config_atomic", fail)

    assert _setup() == 4

    out = _printed(capsys)
    assert "no space left beside <redacted>" in out  # premise: the failure was printed
    assert _OTHER not in out
```

Every row is red on the base. The excerpt rows give 227 and 207 characters. The retained-model row prints the key. The injected rows print it unredacted: the base redacts only the chosen key.

### 6.9 `tests/test_ad1135_provider_setup.py` (M2)

**P-1**
SEARCH:
```
    assert "TAIL-MARKER" not in result.message  # the excerpt is capped
    assert result.message.endswith("...")
```
REPLACE:
```
    assert "TAIL-MARKER" not in result.message  # the excerpt is capped
    assert result.message.endswith("\u2026")  # #1414 item 6: the cut marker is U+2026, not "..."
```

**P-2**
SEARCH:
```
    assert result.message.endswith("...")  # premise: the excerpt was capped
```
REPLACE:
```
    assert result.message.endswith("\u2026")  # premise: the excerpt was capped (#1414 item 6: U+2026 marks the cut)
```

### 6.10 `src/probos/config.py` (M3)

**P-1**
SEARCH:
```
def load_config(path: str | Path) -> SystemConfig:
    """Load and validate system config from a YAML file."""
    path = Path(path)
    if not path.exists():
        return SystemConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    # YAML sections with all values commented out parse as key: None.
    # Remove these so pydantic uses defaults instead of failing validation.
    raw = {k: v for k, v in raw.items() if v is not None}
    return SystemConfig.model_validate(raw)
```
REPLACE:
```
def drop_null_sections(document: dict[str, Any]) -> dict[str, Any]:
    """Return ``document`` without its top-level ``None`` values.

    YAML sections with all values commented out parse as key: None; dropping them lets pydantic use
    the section's defaults instead of failing validation. load_config and the HXI config save
    (routers/config.py, #1414 item 3) share this rule.
    """
    return {k: v for k, v in document.items() if v is not None}


def load_config(path: str | Path) -> SystemConfig:
    """Load and validate system config from a YAML file."""
    path = Path(path)
    if not path.exists():
        return SystemConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return SystemConfig.model_validate(drop_null_sections(raw))
```

### 6.11 `src/probos/routers/config.py` (M3)

**P-1**
SEARCH:
```
- ``POST /api/config`` accepts a sparse patch dict, validates it by
  constructing a fresh :class:`SystemConfig`, persists it to disk, and
```
REPLACE:
```
- ``POST /api/config`` accepts a sparse patch dict, validates it by
  constructing a fresh :class:`SystemConfig`, merges it onto the config
  file as it is on disk (#1414 item 3: an edit made since boot is kept,
  and no value the environment set is written), validates that too,
  persists it, and
```

**P-2**
SEARCH:
```
from probos.config import SystemConfig
from probos.routers.auth import require_crew_scope
```
REPLACE:
```
from probos.config import SystemConfig, drop_null_sections
from probos.routers.auth import require_crew_scope
```

**P-3**
SEARCH:
```
def _write_yaml_atomic(path: str, data: dict) -> None:
    p = Path(path)
```
REPLACE:
```
class _ConfigUnreadable(Exception):
    """The config file cannot be the base of a save; ``str()`` is a reason that quotes none of the file."""


def _read_disk_mapping(path: Path) -> dict[str, Any]:
    """#1414 item 3: the config file's sections as they are on disk; ``{}`` when it does not exist.

    Top-level sections that parse as None (every value commented out) are dropped by the helper
    load_config uses. Raises _ConfigUnreadable when the file cannot be read, is not UTF-8, is not
    YAML or its top level is not a mapping; the reason never quotes the file, since a YAML error's
    own text holds the offending line. PyYAML also fails outside YAMLError: a ValueError for an
    impossible date or an integer of over 4,300 digits, and a RecursionError for deep nesting.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise _ConfigUnreadable("not valid UTF-8 text") from None
    except OSError as exc:
        raise _ConfigUnreadable(f"unreadable ({type(exc).__name__})") from None
    try:
        document = yaml.safe_load(text)
    except (yaml.YAMLError, ValueError, RecursionError):
        raise _ConfigUnreadable("not valid YAML") from None
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise _ConfigUnreadable("not a mapping of config sections")
    return drop_null_sections(document)


def _write_yaml_atomic(path: str, data: dict) -> None:
    p = Path(path)
```

**P-4**
SEARCH:
```
    cfg_path = getattr(runtime, "config_path", None)
    if not cfg_path:
        return JSONResponse(status_code=503, content={"error": "config_path_unavailable"})

    try:
        _write_yaml_atomic(cfg_path, new_cfg.model_dump(mode="json"))
```
REPLACE:
```
    cfg_path = getattr(runtime, "config_path", None)
    if not cfg_path:
        return JSONResponse(status_code=503, content={"error": "config_path_unavailable"})

    # #1414 item 3: merge onto the file as it is now, not onto the config this process booted with, so an
    # edit made since boot (probos setup, a hand edit, an earlier save awaiting restart) is kept and no value
    # the environment set (PROBOS_LLM_URL) is written. No await runs from this read to the write below, so
    # two saves in this process cannot interleave.
    try:
        on_disk = _read_disk_mapping(Path(cfg_path))
    except _ConfigUnreadable as exc:
        logger.warning(
            "AD-741 config save refused (cfg_path=%s): the file is %s; it is unchanged.", cfg_path, exc,
        )
        return JSONResponse(status_code=409, content={"error": "config_unreadable", "reason": str(exc)})
    to_write = _deep_merge(on_disk, patch)
    try:
        SystemConfig.model_validate(to_write)
    except ValidationError as e:
        # loc and type only: a message can quote a value from the file, which may be a secret.
        return JSONResponse(
            status_code=409,
            content={
                "error": "config_invalid",
                "errors": [{"loc": list(err["loc"]), "type": err["type"]} for err in e.errors()],
            },
        )

    try:
        _write_yaml_atomic(cfg_path, to_write)
```

### 6.12 `src/probos/__main__.py` (M3)

**P-1**
SEARCH:
```
    console.print(
        "[dim]Restart any running HXI before saving settings there: a settings save rewrites "
        "this file from the configuration it booted with.[/dim]"
    )
```
REPLACE:
```
    console.print(
        "[dim]A settings save in a running HXI keeps these settings: it merges its changes onto this file "
        "as it is on disk, though it rewrites the file without its comments.[/dim]"
    )
```

### 6.13 `tests/test_bf908_crew_scope_token.py` (M3)

**P-1**
SEARCH:
```
    assert KEYRING_TOKEN not in text
    assert yaml.safe_load(text)["auth"]["crew_scope_token"] == ""
```
REPLACE:
```
    assert KEYRING_TOKEN not in text
    # #1414 item 3: a save writes the file as it was on disk plus its patch, so it writes no auth section at
    # all; before, it wrote the whole in-memory config, whose token field is empty.
    assert "auth" not in yaml.safe_load(text)
```

### 6.15 `tests/test_bf996_hxi_save_on_disk.py` new file (M3)

```python
"""BF-996 (#1414 Batch A, slice A3): an HXI settings save merges its patch onto the config file on disk.

Before, POST /api/config wrote a dump of the configuration the process booted with, so an edit made since
boot (probos setup, a hand edit, an earlier save awaiting restart) was reverted, and a value the
environment set was written into the file. These tests drive the real router over a real file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

import probos.config as config_mod
from probos.api import create_app
from probos.config import CognitiveConfig, SystemConfig, load_config

_ENV_URL = "http://env-only.example.test/v1"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)


def _client(path: Path, config: SystemConfig | None = None) -> tuple[TestClient, MagicMock]:
    # The tests/test_ad741_config_api.py pattern: a real SystemConfig and a real config_path behind a
    # MagicMock runtime; _data_dir is real so create_app makes no directory in the repo root (BF-326).
    runtime = MagicMock()
    runtime.config = config if config is not None else SystemConfig()
    runtime.config_path = str(path)
    runtime._data_dir = path.parent / "data"
    runtime._start_time = 0.0
    return TestClient(create_app(runtime)), runtime


def _save(client: TestClient, patch: dict[str, Any]) -> Any:
    csrf = client.get("/api/config").json()["csrf_token"]
    return client.post("/api/config", json={"patch": patch}, headers={"X-Probos-CSRF": csrf})


def _on_disk(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _empty_file(tmp_path: Path) -> Path:
    path = tmp_path / "system.yaml"
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_a_save_keeps_an_edit_made_to_the_file_after_boot(tmp_path: Path) -> None:
    path = _empty_file(tmp_path)
    client, runtime = _client(path)
    path.write_text("cognitive:\n  llm_model_fast: edited-after-boot\n", encoding="utf-8")  # probos setup, or by hand
    assert runtime.config.cognitive.llm_model_fast != "edited-after-boot"  # premise: booted without it

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 200, response.text
    assert _on_disk(path) == {"cognitive": {"llm_model_fast": "edited-after-boot"}, "system": {"log_level": "DEBUG"}}


def test_two_saves_before_a_restart_keep_both_changes(tmp_path: Path) -> None:
    path = _empty_file(tmp_path)
    client, runtime = _client(path)

    first = _save(client, {"system": {"log_level": "DEBUG"}})
    second = _save(client, {"system": {"name": "Enterprise"}})

    assert (first.status_code, first.json()["restart_required"], second.status_code) == (200, True, 200)
    assert runtime.config.system.log_level == "INFO"  # premise: the first change is not live yet
    assert _on_disk(path) == {"system": {"log_level": "DEBUG", "name": "Enterprise"}}


def test_a_save_writes_no_value_the_environment_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBOS_LLM_URL", _ENV_URL)
    path = _empty_file(tmp_path)
    # SystemConfig() copies the CognitiveConfig built when probos.config was imported, and PROBOS_LLM_URL is read each time a
    # CognitiveConfig is built: the config of a process started with the variable set is built here, after setenv.
    client, runtime = _client(path, SystemConfig(cognitive=CognitiveConfig()))
    assert runtime.config.cognitive.llm_base_url == _ENV_URL  # premise: the booted config holds the env value

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _ENV_URL not in path.read_text(encoding="utf-8")
    assert _on_disk(path) == {"system": {"log_level": "DEBUG"}}


def test_a_save_onto_a_missing_file_writes_only_the_patch(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    client, _ = _client(path)
    assert not path.exists()  # premise

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path) == {"system": {"log_level": "DEBUG"}}
    assert load_config(path).system.log_level == "DEBUG"


def test_a_section_whose_values_are_all_commented_out_does_not_block_a_save(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text("memory:\n  # max_episodes: 10\nsystem:\n  name: Kept\n", encoding="utf-8")
    client, _ = _client(path)
    assert load_config(path).system.name == "Kept"  # premise: load_config drops the empty section

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path) == {"system": {"name": "Kept", "log_level": "DEBUG"}}


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"system: [\n", "not valid YAML"),
        (b"- a\n- b\n", "not a mapping of config sections"),
        (b"system:\n  name: \xff\n", "not valid UTF-8 text"),
        # PyYAML raises a ValueError for the date and a RecursionError for the nesting, not a YAMLError.
        (b"system:\n  name: 2023-13-45\n", "not valid YAML"),
        (b"system: " + b"[" * 5000 + b"]" * 5000 + b"\n", "not valid YAML"),
    ],
    ids=["yaml", "list", "utf-8", "impossible-date", "deep-nesting"],
)
def test_an_unusable_file_is_refused_and_left_as_it_is(data: bytes, reason: str, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (409, {"error": "config_unreadable", "reason": reason})
    assert path.read_bytes() == data
    assert runtime.config.system.log_level == "INFO"


def test_a_file_that_does_not_validate_is_refused_without_quoting_it(tmp_path: Path) -> None:
    data = b"memory:\n  max_episodes: sk-bf996-file-value\n"
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, _ = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "config_invalid"
    assert [error["loc"] for error in body["errors"]] == [["memory", "max_episodes"]]
    assert all(set(error) == {"loc", "type"} for error in body["errors"])
    assert "sk-bf996-file-value" not in response.text
    assert path.read_bytes() == data


def test_a_secret_already_in_the_file_survives_a_save(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text("cloud_pickers:\n  google_drive:\n    client_secret: disk-secret-bf996\n", encoding="utf-8")
    client, runtime = _client(path)
    assert runtime.config.cloud_pickers.google_drive.client_secret != "disk-secret-bf996"  # premise

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path)["cloud_pickers"]["google_drive"]["client_secret"] == "disk-secret-bf996"


def test_drop_null_sections_drops_only_none_and_load_config_uses_it(tmp_path: Path) -> None:
    drop = config_mod.drop_null_sections

    assert drop({"a": None, "b": {}, "c": 0, "d": ""}) == {"b": {}, "c": 0, "d": ""}
    path = tmp_path / "system.yaml"
    path.write_text("memory:\nsystem:\n  name: Kept\n", encoding="utf-8")
    assert load_config(path).system.name == "Kept"
```

On the base:
- Red: the first five rows (the save writes the boot dump); the unusable-file and invalid-file rows (the save returns 200 and rewrites the file); the secret row (the runtime value replaces the disk value); and the `drop_null_sections` row (AttributeError, in that row only).
- Green: the `load_config` half of the last row.

### 6.14 `tests/test_ad1270e1_config_facade.py` (M4; written against B15's tip)

**P-1**
SEARCH:
```
    assert counts["public_names"] == 309  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig
    assert counts["owned"] == 296  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig was owned
```
REPLACE:
```
    # #1414 A3 adds the owned function drop_null_sections, which load_config and the HXI config save share:
    # public_names 309 -> 310, owned 296 -> 297, and the check prints names=310.
    assert counts["public_names"] == 310  # #1414 A3: drop_null_sections
    assert counts["owned"] == 297  # #1414 A3: drop_null_sections is owned
```

**P-2**
SEARCH:
```
    assert len(baseline["names"]) == 309  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (310 -> 309)
```
REPLACE:
```
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig (310 -> 309).
    assert len(baseline["names"]) == 310  # #1414 A3: drop_null_sections (309 -> 310)
```

**P-3**
SEARCH:
```
    assert "names=309" in proc.stdout  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (names=310 -> names=309)
```
REPLACE:
```
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig (names=310 -> names=309).
    assert "names=310" in proc.stdout  # #1414 A3: drop_null_sections (names=309 -> names=310)
```

### 6.16 `PROGRESS.md` (M4)

**P-1**
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-994 (2026-11-25), #1414 -- `probos init` writes the OpenAI format for Ollama's /v1 default, and the scaffold it shares with `probos setup` sets the shipped 300 s LLM timeout.** `_cmd_init` wrote `llm_api_format_fast: ollama` for any URL holding `:11434`, so its own default, `http://localhost:11434/v1`, posted to `/v1/api/chat`. It now writes `ollama` only for an Ollama root (port 11434, no path), and `openai` otherwise. `tests/test_bf994_init_config_reaches_its_api.py::test_the_init_config_reaches_the_api_its_url_serves` sends a request through the real `OpenAICompatibleClient` built from the written file: the detected default posts to `/v1/chat/completions` and a typed root to `/api/chat`. `test_init_writes_the_format_the_typed_url_serves` covers seven URLs, among them a port that does not parse. The scaffold sets `llm_timeout_seconds: 300.0` under `cognitive:`, the value `config/system.yaml` ships, for init (`test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout`) and for setup's create path (`test_setup_create_path_writes_the_shipped_timeout`). An existing file is given no timeout and keeps its default (`test_setup_on_an_existing_file_adds_no_timeout`); the `CognitiveConfig` default stays 30.0. The init byte goldens in `tests/test_ad1135_provider_setup.py` move by the new line and, for the Ollama row, the format word. `docs/getting-started/configuration.md` and the `docker-compose.yml` comment now say that `PROBOS_LLM_URL` replaces only the shared URL and that a tier with its own `llm_base_url_<tier>` keeps it. Mutation census: 6 of 6 killed (rows A1-M1 to A1-M6, run once on the candidate overlay of `dea82930`), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.

**BF-995 (2026-11-25), #1414 -- setup's provider excerpt stays at 200 characters, and setup hides every API key the existing config holds wherever it prints text read from it.** The excerpt's cut marker is U+2026, which no form of a key holds, so the second redaction in `_result` cannot match or complete a key across the cut. A key of `.` gives a 200-character excerpt where it gave 227 (`tests/test_bf995_setup_redaction.py::test_the_excerpt_for_a_key_of_dots_stays_at_200_characters`), and a key the old cut would have completed is not formed (`test_the_cut_completes_no_key`). Setup now redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file (`config_text_api_keys`, read without validation) at the eight sites that print text from that file. A retained optional-tier model that holds the file's shared, vision or verifier key prints as `<redacted>` (`test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted`). A refusal from reading or editing the file, the `--force` note and a write failure print no key from it (`test_a_refusal_quoting_the_file_prints_no_key_from_it`, `test_a_write_failure_quoting_the_file_prints_no_key_from_it`). Two pins in `tests/test_ad1135_provider_setup.py` now expect the new marker. Mutation census: 7 of 7 killed (rows A2-M1 to A2-M7, run once on the candidate overlay of `dea82930`), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.

**BF-996 (2026-11-25), #1414 -- an HXI settings save merges its patch onto the config file as it is on disk, so edits made since boot are kept.** `POST /api/config` wrote a dump of the configuration the process booted with. It now writes the file's own sections plus the patch, with all-commented sections dropped by `drop_null_sections`, the helper `load_config` now shares, and validates that result before writing it. An out-of-band edit and an earlier save awaiting restart both survive (`tests/test_bf996_hxi_save_on_disk.py::test_a_save_keeps_an_edit_made_to_the_file_after_boot`, `test_two_saves_before_a_restart_keep_both_changes`). A value set by `PROBOS_LLM_URL` is not written (`test_a_save_writes_no_value_the_environment_set`). A missing file receives only the patch (`test_a_save_onto_a_missing_file_writes_only_the_patch`), and a secret already in the file stays (`test_a_secret_already_in_the_file_survives_a_save`). A file that cannot be read, is not UTF-8, is not YAML (an impossible date or nesting past the recursion limit included) or is not a mapping answers 409 `config_unreadable` and is left byte for byte (`test_an_unusable_file_is_refused_and_left_as_it_is`). One that does not validate answers 409 `config_invalid` with `loc` and `type` only (`test_a_file_that_does_not_validate_is_refused_without_quoting_it`). The secret-path guard, the runtime 422, `changed_fields` and hot reload are unchanged (`tests/test_ad741_config_api.py`, `tests/test_ad741_integration.py`, `tests/test_ad741_secret_redaction.py`). `tests/test_bf908_crew_scope_token.py` now expects no `auth` section in the written file. The facade baseline gains `drop_null_sections`. Mutation census: 9 of 9 killed (rows A3-M1 to A3-M9, run once on the candidate overlay of `dea82930`), each by its named cases; A3-M10 is a review property. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```

### 6.17 `DECISIONS.md` (M4; anchored on B15's heading)

**P-1**
SEARCH:
```
### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)
```
REPLACE:
```
### BF-994 / BF-995 / BF-996 -- #1414 Batch A: init's provider format and timeout, setup's redaction, the HXI save's base file (2026-11-25, #1414)

- *Scope.* `__main__.py` (`_init_api_format`, the init scaffold, the setup print sites, setup's HXI note), `provider_setup.py` (`_CUT_MARKER`, `config_text_api_keys`), `config.py` (`drop_null_sections`), `routers/config.py`, `docs/getting-started/configuration.md`, `docker-compose.yml`; tests `tests/test_bf994_init_config_reaches_its_api.py`, `tests/test_bf995_setup_redaction.py`, `tests/test_bf996_hxi_save_on_disk.py`. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
- *D1.* `probos init` writes `llm_api_format_fast: ollama` only for an Ollama root (port 11434, empty path); every other URL, init's `/v1` default included, is `openai`. Rejected: always `openai` (a typed root would post to `/chat/completions`), rewriting the typed URL, and the `:11434` substring test.
- *D2.* The scaffold shared by init and setup's create path sets the shared `llm_timeout_seconds: 300.0`; existing files keep what they have, and the `CognitiveConfig` default stays 30.0. Rejected: changing the default (it moves every existing config and the facade and profile baselines).
- *D3.* Setup's excerpt is cut with U+2026 at 200 characters. Setup redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file wherever it prints text from that file; other secrets in the file are out of scope. Rejected: a console that redacts all output (highlighting and markup escaping change a key's bytes, and a short key could break markup).
- *D4.* An HXI save writes the on-disk mapping plus the patch, validated, never a dump of the running config; an unusable file answers 409 `config_unreadable`, an invalid result 409 `config_invalid` with `loc` and `type` only. No await runs between the read and the write. Rejected: refusing a save when the file's hash differs from boot (runtime plumbing, and it blocks a legitimate save).
- *Reversal.* Revert the slice's commit; each slice is independent. The M4 facade baseline row for `drop_null_sections` goes with BF-996.

### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)
```

If 6.17 runs against `40f9305f` instead, anchor on `### BF-992 -- Readers that hold a slot id count episodes under the agent's sovereign id: boot camp, recall probe, profile (2026-11-24, #1324)`.

## 7. Mutation census and generated-artifact commands

| Row | Mutant | Killer |
|---|---|---|
| A1-M1 | the rule reverts to `":11434" in llm_url` | `test_init_writes_the_format_the_typed_url_serves[ollama-v1,ollama-v1-slash,port-out-of-range]`, `test_the_init_config_reaches_the_api_its_url_serves[detected-default]` |
| A1-M2 | always `openai` | `test_init_writes_the_format_the_typed_url_serves[ollama-root,ollama-root-slash]`, `test_the_init_config_reaches_the_api_its_url_serves[bare-root]` |
| A1-M3 | the port check is dropped (any root is `ollama`) | `test_init_writes_the_format_the_typed_url_serves[other-root]` |
| A1-M4 | the scaffold's timeout line is removed | `test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout`, `test_setup_create_path_writes_the_shipped_timeout`, the goldens |
| A1-M5 | the scaffold writes `30.0` | same as A1-M4 |
| A1-M6 | setup's managed values add `llm_timeout_seconds` | `test_setup_on_an_existing_file_adds_no_timeout` |
| A2-M1 | the marker reverts to `"..."` with the cut at -3 | `test_the_excerpt_for_a_key_of_dots_stays_at_200_characters`, `test_the_cut_completes_no_key`, `test_ad1135_provider_setup.py:425,470` |
| A2-M2 | `_CUT_MARKER` is kept but the cut stays at -3 (198 characters) | `test_the_excerpt_for_a_key_of_dots_stays_at_200_characters` (asserts 200), `test_the_cut_completes_no_key` |
| A2-M3 | the shared-URL notes redact only the chosen key | `test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted[*]` |
| A2-M4 | `config_text_api_keys` reads only `llm_api_key` | `test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted[llm_api_key_vision,llm_api_key_verifier]` |
| A2-M5 | `file_keys` is computed after `optional_tier_endpoints` | `test_a_refusal_quoting_the_file_prints_no_key_from_it[reading-the-file]` |
| A2-M6 | `_setup_candidate`'s refusal is not redacted | `test_a_refusal_quoting_the_file_prints_no_key_from_it[editing-the-file,force-rewrite-note]` |
| A2-M7 | the write-failure site redacts only the chosen key | `test_a_write_failure_quoting_the_file_prints_no_key_from_it` |
| A3-M1 | the save writes `new_cfg.model_dump(mode="json")` | `test_a_save_keeps_an_edit_made_to_the_file_after_boot`, `test_two_saves_before_a_restart_keep_both_changes`, `test_a_save_writes_no_value_the_environment_set`, `test_a_save_onto_a_missing_file_writes_only_the_patch`, `test_a_section_whose_values_are_all_commented_out_does_not_block_a_save`, `test_a_secret_already_in_the_file_survives_a_save` |
| A3-M2 | the disk-mapping validation is removed | `test_a_file_that_does_not_validate_is_refused_without_quoting_it` |
| A3-M3 | `_ConfigUnreadable` is treated as `{}` | `test_an_unusable_file_is_refused_and_left_as_it_is[*]` |
| A3-M4 | the router skips `drop_null_sections` | `test_a_section_whose_values_are_all_commented_out_does_not_block_a_save` |
| A3-M5 | the 409 errors include `msg` or `input` | `test_a_file_that_does_not_validate_is_refused_without_quoting_it` |
| A3-M6 | `drop_null_sections` drops every falsy value | `test_drop_null_sections_drops_only_none_and_load_config_uses_it` |
| A3-M7 | the secret guard is moved after the read, or removed | `tests/test_ad741_secret_redaction.py::test_post_config_rejects_secret_field_paths` |
| A3-M8 | a missing file answers 409 | `test_a_save_onto_a_missing_file_writes_only_the_patch` |
| A3-M9 | the YAML `except` clause catches only `yaml.YAMLError` | `test_an_unusable_file_is_refused_and_left_as_it_is[impossible-date,deep-nesting]` |
| A3-M10 | `changed_fields` is computed from the disk diff | no test; Diff Reviewer property A3-5 |

Generated artifacts, in order, at M4, on the post-B15 base (interpreter `d:/ProbOS/.venv/Scripts/python.exe`):

1. `scripts/check_config_facade.py --update-baseline`
   - Expected diff: the row `drop_null_sections: {kind: function, tier: owned}`, `owned` 296 -> 297 and `public_names` 309 -> 310.
   - `canonical_dump_sha256` is unchanged. Measured on the post-B15 oracle: the diff is exactly this.
2. Apply 6.14, 6.16 and 6.17.
3. `scripts/gen_ad_ledger.py`. BF-994, BF-995 and BF-996 rows appear as shipped through the `DECISIONS.md` heading. Measured on the post-B15 oracle: shipped 633 -> 636, the BF list ends `980-996`, the highest BF is BF-996 and the next BF-997.
4. The `--check` runs of `scripts/check_config_facade.py`, `scripts/gen_ad_ledger.py`, `scripts/gen_config_reference.py`, `scripts/check_config_profiles.py`, `scripts/check_architecture_principles.py`, `scripts/check_seam_contracts.py` and `scripts/check_store_registry.py`.
5. `scripts/run_test_gate.py --preflight-only`.

These artifacts do not move: `config-reference.md` (no field), `config-profiles.yaml` (no environment read), `architecture-baseline.yaml` (no new class or database connection), the file-write census (`_write_yaml_atomic` is still the writer).

Preflight phases that fail if a step is missing:
- `config-facade`, if step 1 is skipped after M3 (facade-symbol-added and the count lines);
- `ad-ledger`, if step 3 is skipped after the tracker edits;
- `compile`, on a syntax error;
- `phantom-api`, if this contract is staged with a new name written in `x.y(` form in prose.

## 8. Diff Reviewer brief (per slice) and #1414 landing comment

**A1. Consumers to accept the change:** `OpenAICompatibleClient` (`llm_client.py:866`, `:2383`, `:2494`), `load_config`, and setup's create path (`_setup_scaffold`).
- A1-1: `_cmd_init` writes `ollama` only for port 11434 with an empty or `/` path. Every other URL, including `http://localhost:11434/v1` and a URL whose port does not parse, gets `openai`. The model-default line is unchanged.
- A1-2: the only scaffold change is `llm_timeout_seconds: 300.0` under `cognitive:`. Setup's edit and `--force` paths never add it, and the `CognitiveConfig` default stays 30.0.
- A1-3: the init goldens move only by that line and by the Ollama row's format word; the comment says why.
- A1-4: the docs and the compose comment say `PROBOS_LLM_URL` replaces only the shared URL and that per-tier URLs win. The compose example still ends in `/v1`.

**A2. Consumers:** the operator's terminal and `probos doctor` (which shows the excerpt).
- A2-1: `_excerpt` returns at most 200 characters, ending in U+2026 when cut, and the source holds the `"\u2026"` escape, not the literal character.
- A2-2: `config_text_api_keys` returns every non-empty string under a `cognitive.llm_api_key*` key, without validation. It returns `[]` for None and raises `ConfigEditRefused` for text that is not a mapping, exactly as `parse_config_text` does.
- A2-3: the sites that print text from the existing file redact with the chosen key plus the file's keys:
  - P1 `_setup_plan` "Cannot edit";
  - P2 and P3 `_setup_candidate` "Cannot edit" and "Cannot rewrite";
  - P4 the `--force` note;
  - P5 `_setup_shared_url_notes`, from both the confirm and the report;
  - P6 `_setup_confirm_write`'s models;
  - P7 `_cmd_setup`'s "Could not write";
  - P8 the backup line.
- A2-4: `file_keys` is computed before `optional_tier_endpoints` runs, and the message of the invalid-YAML exit 4 is unchanged.
- A2-5: no site prints a key, and "API key: present / not set" is unchanged.

**A3. Consumers:** the HXI settings store (`ui/src/store/useSettingsStore.ts:196-229`) and the next boot's `load_config`.
- A3-1: what is written equals `_deep_merge(on-disk mapping, patch)`. The on-disk mapping is passed through `drop_null_sections`, the same function `load_config` calls, and is never a dump of `runtime.config`.
- A3-2: that mapping passes `SystemConfig.model_validate` before the write. On failure the answer is 409 `config_invalid` with `loc` and `type` only, and the file and `runtime.config` are unchanged.
- A3-3: a missing file starts from `{}`. A file that cannot be read, is not UTF-8, is not YAML (an impossible date and nesting past the recursion limit included) or is not a mapping answers 409 `config_unreadable` with a fixed reason and is left untouched.
- A3-4: no `await` runs between the disk read and `_write_yaml_atomic`.
- A3-5: the secret guard (400) runs first. The runtime merge and 422, the 503, the runtime-based `changed_fields` and hot reload are unchanged.
- A3-6: `load_config` behaves the same for every input, including the `AttributeError` for a top level that is not a mapping.
- A3-7: no value set by the environment reaches the file.
- A3-8: setup's note no longer says a save rewrites the file from the boot configuration.
- A3-9: the `test_bf908` pin change carries its reason inline.

**#1414 landing comment:**

```
Batch A (CLI and configuration) is merged in <PR #...> (<sha>), gated by <receipt path, receipt sha>.

- [x] Item 2 (init with Ollama posted to /v1/api/chat): BF-994. init writes the openai format for its /v1 default; only an Ollama root (port 11434, no path) keeps ollama. Proof: tests/test_bf994_init_config_reaches_its_api.py, a real OpenAICompatibleClient over a mock transport (POST /v1/chat/completions for the detected default, /api/chat for a typed root).
- [x] Item 5 (30 s timeout in generated configs): BF-994. The scaffold shared by init and setup's create path sets llm_timeout_seconds: 300.0; existing files are unchanged.
- [x] Item 4 (PROBOS_LLM_URL reaches only the shared URL): behaves as documented; docs/getting-started/configuration.md and the docker-compose.yml comment now say a tier with its own llm_base_url_<tier> keeps it. No code change.
- [x] Item 6 (excerpt over 200 characters): BF-995. Cut marker U+2026; a key of "." gives 200 characters (227 before).
- [x] Item 7 (setup redacts only the key being configured): BF-995. Setup redacts every cognitive.llm_api_key* value in the existing file at the eight sites that print text from it. Other secret kinds in the file are out of this item's scope.
- [x] Item 3 (HXI save reverts out-of-band edits): BF-996. The save merges its patch onto the file as it is on disk; an unusable file answers 409 and is left as it is. Proof: tests/test_bf996_hxi_save_on_disk.py through the real router.

Mutation census: A1 6/6, A2 7/7, A3 9/9 killed; A3-M10 is a review property.
Not ticked here: items 1, 8 to 14 (Batches B and C, the item 10 consolidation, item 13 as a limit).
```

The comment ticks items 2, 3, 4, 5, 6 and 7. It does not tick item 1 (shipped earlier in `3f226065`, outside this batch) or items 8 to 14.
