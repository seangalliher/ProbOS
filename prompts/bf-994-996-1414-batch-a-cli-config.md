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
| R1 | A1, A2 (review round 1) | `src/probos/__main__.py`, `src/probos/provider_setup.py`, `tests/test_bf994_init_config_reaches_its_api.py`, `tests/test_bf995_setup_redaction.py`, `PROGRESS.md`, `DECISIONS.md` | `init judges its URL as the client sends it and asks again for one setup refuses; setup redacts any file key and a shown model's repr (#1414 review)` |
| R2 | A3 (review round 1) | `src/probos/routers/config.py`, `tests/test_bf996_hxi_save_on_disk.py`, `PROGRESS.md`, `DECISIONS.md` | `an HXI settings save answers 409 for a file it cannot stat, write back or validate (#1414 A3)` |

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
- R1: `-m pytest tests/test_bf994_init_config_reaches_its_api.py tests/test_bf995_setup_redaction.py tests/test_ad1135_provider_setup.py tests/test_ad1135_setup_cli.py tests/test_claude_bootstrap_init_defaults.py "tests/test_distribution.py::TestProbOSInit" tests/test_ad1137_doctor.py tests/test_ad1137_quickstart_chain.py tests/test_ad1327_verifier_independence.py -q -n 0`
- R2: `-m pytest tests/test_bf996_hxi_save_on_disk.py tests/test_ad741_config_api.py tests/test_ad741_integration.py tests/test_ad741_secret_redaction.py tests/test_bf908_crew_scope_token.py -q -n 0`

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

## 6b. Review round 1: repairs R1 (A1 and A2) and R2 (A3)

Review round 1 (three Diff Reviewers on `gpt-6.1-sol`, one per slice) returned REQUEST CHANGES for all three slices. The decisions below are the Architect's; the pairs follow in sections 6.18 to 6.27. R1 (sections 6.18 to 6.23) applies to the head `93024759` and changes none of A3's files; R2 (sections 6.24 to 6.27) applies on top of R1 and changes none of A1's or A2's.

### R1 decisions (A1 and A2)

Fix five findings, record one with its reach, and reword the trackers.

| Finding | Decision | Reason |
|---|---|---|
| A1-F1 | **Fix** | It is a regression with ordinary reach. Init will judge the URL the way the client sends it: `httpx.URL(llm_url.rstrip("/") + "/")` (what `_build_client` builds at `llm_client.py:866`), then port 11434 and `path.strip("/") == ""`. A URL that raises `httpx.InvalidURL` or `ValueError` gets `openai`. |
| A1-F2 | **Fix the init path; record the client part** | Ordinary reach: an operator can type a URL with a query (Azure's `?api-version=`), and init writes a URL the client cannot reach. Option (a): init re-asks for any URL that `provider_setup.normalize_base_url` refuses, which is setup's existing rule (`provider_setup.py:143-164`). The URL is still written as typed, and the module already imports `provider_setup`. Option (b) rejected: `_build_client` sits on every request's path. **Recorded on #1820:** a query in a hand-edited config or in `PROBOS_LLM_URL` still lands in the request's query. Not a regression; the failure is visible because every request fails and the doctor's probe reports it. |
| A2-F1 | **Fix** | It is a regression: setup raises after the file was replaced, where the base exited 0. `_key_forms` becomes total: when `encode("utf-8")` raises, it returns `[api_key]` only, since only the literal can appear in printed text. Side effect: this also covers the boot banner's `redact_keys` at `__main__.py:349-362`, which already raised on such a key. |
| A2-F2 | **Fix** | The key is in the file, not injected, so this does not meet the rule for recording. The repair is one line: redact the raw model, take its `repr`, then redact the `repr` text and print it with no further `repr`. The tests cover a key with quotes, a doubled backslash and a raw backslash. |
| A2-F3 | **Record; reword A2-5** | Not a regression: the base printed the chosen key in the same path lines. The key can only get there through a path the operator gave on their own command line (`--config`, `--probos-home`) or the default under their home directory, so printing it shows them only what they typed. Redacting paths with the file's keys would mangle every path line whenever a file key is one or two characters long (blind spot 3). A2-5 now matches D3's scope. |
| BF-995 tracker wording | **Must change** | "Hides every API key ... wherever it prints text" is not true as written. PROGRESS and DECISIONS D3 now state the scope (messages from the file) and both limits (keys that collide with the marker, and path lines), each recorded on #1820. |

Follow-up items for #1820 from R1, with reach:
1. Config path lines print a key whose text is inside the path. Reach: only the operator's own path argument. Not a regression.
2. A query in a hand-edited `llm_base_url*` or in `PROBOS_LLM_URL` lands in the request's query (`_build_client`). Reach: hand edits. It fails visibly. Not a regression.
3. A key whose text is part of `<redacted>` (for example `ed`) still shows inside each marker. This is blind spot 3, already known and cosmetic.

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-25

**Milestone R1.** It applies to the head `93024759`. Files: `src/probos/__main__.py`, `src/probos/provider_setup.py`, `tests/test_bf994_init_config_reaches_its_api.py`, `tests/test_bf995_setup_redaction.py`, `PROGRESS.md`, `DECISIONS.md`, plus this contract's sections 7 and 8. It changes none of A3's files. Commit subject: `init judges its URL as the client sends it and asks again for one setup refuses; setup redacts any file key and a shown model's repr (#1414 review)`.

**The Builder may:** if the premise line in `test_a_url_the_client_cannot_parse_is_openai` fails, swap `http://localhost:abc/v1` for another URL that `httpx.URL` refuses, keeping the premise line. **The Builder may not:** do anything section 5 forbids, or change any A3 file. If a new setup test exits 4 at the read, that is a hard stop: report it to the Architect.

### R2 decisions (A3)

**Verdict: fix F1, F2 and F3 at router level; for F4, add one census test and reword the trackers.** Nothing is filed as an injected-only follow-up, because all three P2s are regressions. The validator at the root of F2 goes to #1820, since the contract says the Builder may not change `load_config`. No new AD or BF number is needed (the slice stays BF-996), so I did not run `ad_ceiling.py`.

| Finding | Decision | Reason under the convergence rule |
|---|---|---|
| **F1** dump `ValueError` gives 500 | **Fix in the router**, at the catch around `_write_yaml_atomic`: 409 `config_unreadable`, reason `holds a value that cannot be written back` | It is a regression, so it gets fixed whatever its reach. On reach, I disagree that it is ordinary: a hex literal of 3,572 or more digits is a rare edit. **I widened it to the same class** with the same clause: nesting deep enough to break the dump's recursion but not the load's gives `RecursionError` (case below). **Oracle correction (orchestrator, 2026-11-25):** the draft's other candidate, a `!!omap` or `!!pairs` entry, dumps without error (`SafeRepresenter` writes a tuple as a list); the draft's stated contingency applies, so that case and `yaml.YAMLError` are dropped from the clause. The code is `config_unreadable` because the decimal form of the same integer already gets it (your c2). The UI therefore shows the same code for the same value, and the reason quotes nothing. The dump is the first statement of `_write_yaml_atomic` (`routers/config.py:184`), before `mkstemp` at :185, so nothing has been written when it fails. |
| **F2** validator `OverflowError` gives 500 | **Router fix**: `except OverflowError` on the disk validation answers 409 `config_invalid` with `errors: [{"loc": [], "type": "OverflowError"}]`. **The validator is out of scope and becomes a #1820 item.** | It is a regression: the save now validates the file. The shape stays `config_invalid` with `loc`/`type` only, which `test_a_file_that_does_not_validate...:151` already requires. `loc` is empty because pydantic gives none. Changing `agentic.py:803-819` would turn the boot `OverflowError` into a `ValidationError`, which A3-6 and "Builder may not" forbid. The runtime-merge step (`routers/config.py:284`) 500s on the same value in a *patch*. That is base behaviour, A3-5 keeps it unchanged, and it goes to the same #1820 item. |
| **F3** `path.exists()` outside the guard | **Fix in the reader**: move the existence check into the `try`, so `OSError` gives `unreadable (PermissionError)` | It is a regression and injected-only, and the rule fixes every regression. Keeping `Path.exists()` (rather than catching `FileNotFoundError`) keeps "missing" identical to `load_config`'s check (`config.py:4168`). |
| **F4a** A3-M7 "moved" survives | **Split the row**: A3-M7 becomes "removed" (existing killer), and new A3-M15, "moved after the disk read", is killed by `test_a_secret_path_is_refused_before_the_file_is_read` (unreadable file plus secret patch gives 400) | This is a census gap and the test is green on the head by design. A3-5 says the guard runs first. |
| **F4b** PROGRESS "cannot be read" is not backed by a test | **Reword, and add real evidence**: `test_a_directory_at_the_config_path_is_refused_and_left_as_it_is` (real OS read failure, green on the head) and the F3 stat test | This makes the PROGRESS claim true and cited. |

**#1820 follow-up (one item).** `DmAgenticConfig.validate_budget_awareness_thresholds` (`config_models/agentic.py:807-813`) calls `math.isfinite` on an `int`. An integer over about 309 digits raises `OverflowError`, which pydantic does not wrap. Reach:
- **Boot.** `load_config` tracebacks on a hand-edited file, on base and head alike. This is rare: it takes a typo-scale literal.
- **HXI runtime merge.** `routers/config.py:284` returns a 500 for an API caller with crew scope. The UI cannot send such a value: a JS number that large becomes `Infinity`, and `JSON.stringify` writes `null`.

The fix is to raise `ValueError` for a non-float-convertible int. That changes `load_config`'s failure type, so it needs its own slice.

**Oracle measurements (orchestrator, 2026-11-25).**
- A probe of 25 loadable YAML shapes (an orchestrator script, not committed): only an integer of over 4,300 digits written in hex or binary (`ValueError`) and nesting too deep (`RecursionError`) are refused by `yaml.safe_dump`. `!!omap`, `!!pairs`, `!!set`, `!!binary`, timestamps, `.inf`, `.nan`, cyclic aliases, a lone-surrogate string and a NUL string all dump.
- The nesting case: in this environment a flow sequence 360 levels deep loads; in a test body (stack depth 33) the dump fails from 320 levels, in the router from 330; the load did not fail up to 460 levels.
- A validation fuzz (1,912 field paths, 16 loadable values each; an orchestrator script, not committed): the only exception type that escapes `SystemConfig.model_validate` is `OverflowError`, for an integer of over 309 digits in the four float fields `mesh.handler_latency_cognitive_ms`, `mesh.handler_latency_deterministic_ms`, `mesh.handler_latency_network_ms` and `security.memory.correlation_cutoff`. The fifth, `dm_agentic.budget_awareness_thresholds`, is the finding itself: it takes the integer inside a list, which the fuzz did not try. The router clause covers all five; the #1820 item names all five.

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-25

**Milestone R2.** It applies on top of R1 (the head `93024759` plus R1's commit). Files: `src/probos/routers/config.py`, `tests/test_bf996_hxi_save_on_disk.py`, `PROGRESS.md`, `DECISIONS.md`, plus this contract's sections 7 and 8. It changes none of A1's or A2's files. Commit subject: `an HXI settings save answers 409 for a file it cannot stat, write back or validate (#1414 A3)`. **The Builder may not:** do anything section 5 forbids, or change any A1 or A2 file. If a premise line of a new test fails, that is a hard stop: report it to the Architect. The rows A3-M11 to A3-M15 are the orchestrator's.

### 6.18 `src/probos/provider_setup.py` (R1)

**P-1**
SEARCH:
```
def _key_forms(api_key: str) -> list[str]:
    raw = api_key.encode("utf-8")
    forms = {
```
REPLACE:
```
def _key_forms(api_key: str) -> list[str]:
    try:
        raw = api_key.encode("utf-8")
    except UnicodeEncodeError:
        # #1414 review: a key read from the existing file is not validated (config_text_api_keys). One that
        # holds a lone surrogate has no encoded form, so only its literal text can appear in what setup prints.
        return [api_key]
    forms = {
```

### 6.19 `src/probos/__main__.py` (R1)

**P-1**
SEARCH:
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
```
REPLACE:
```
def _init_api_format(llm_url: str) -> str:
    """#1414 item 2: ``ollama`` only for an Ollama root (port 11434, no path); ``openai`` for every other URL.

    The client posts ``api/chat`` under an ``ollama`` base and ``chat/completions`` under an ``openai`` one,
    so init's own Ollama default, ``http://localhost:11434/v1``, is Ollama's OpenAI-compatible API. The path
    is judged as the client sends it (#1414 review): the base with one trailing slash, parsed by httpx, which
    removes dot segments, so ``/v1/..`` and ``/./`` are the root. A URL httpx cannot parse is ``openai``, as
    it was for any URL without ``:11434``.
    """
    import httpx

    try:
        url = httpx.URL(llm_url.rstrip("/") + "/")  # what OpenAICompatibleClient._build_client builds
    except (httpx.InvalidURL, ValueError):
        return "openai"
    return "ollama" if url.port == 11434 and url.path.strip("/") == "" else "openai"
```

**P-2**
SEARCH:
```
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
    from rich.prompt import Prompt

    console = Console()
```
REPLACE:
```
    """Handle ``probos init`` -- interactive Rich TUI wizard (AD-484)."""
    from rich.markup import escape
    from rich.prompt import Prompt

    console = Console()
```

**P-3**
SEARCH:
```
    elif default_url == "http://127.0.0.1:8080":
        default_url = "http://127.0.0.1:8080/v1"
    llm_url = Prompt.ask("  LLM endpoint URL", default=default_url, console=console)
```
REPLACE:
```
    elif default_url == "http://127.0.0.1:8080":
        default_url = "http://127.0.0.1:8080/v1"
    while True:
        llm_url = Prompt.ask("  LLM endpoint URL", default=default_url, console=console)
        try:
            # #1414 review: setup's base-URL rule. A query, for one, would carry the path the client appends
            # (http://localhost:11434?q=1 posts to /?q=1/api/chat). The URL is written as typed.
            provider_setup.normalize_base_url(llm_url)
        except provider_setup.SetupInputError as exc:
            console.print(f"  [red]Invalid endpoint URL:[/red] {escape(str(exc))}")
            continue
        break
```

**P-4**
SEARCH:
```
    for tier, model in shared_url_tiers.items():
        # Read from the existing file, which can hold the chosen key or one it already had (#1414 item 7).
        shown = provider_setup.redact_keys(model, keys)
        console.print(
            f"  Left the shared llm_base_url unchanged because {escape(tier)} (model {escape(repr(shown))}) uses it; "
```
REPLACE:
```
    for tier, model in shared_url_tiers.items():
        # Read from the existing file, which can hold the chosen key or one it already had (#1414 item 7).
        # The raw model is redacted first (repr doubles a backslash in it), then its repr, whose quotes and
        # escapes can complete a key the raw model holds only part of (#1414 review).
        shown = provider_setup.redact_keys(repr(provider_setup.redact_keys(model, keys)), keys)
        console.print(
            f"  Left the shared llm_base_url unchanged because {escape(tier)} (model {escape(shown)}) uses it; "
```

### 6.20 `tests/test_bf994_init_config_reaches_its_api.py` (R1)

**P-1**
SEARCH:
```
def _init(monkeypatch: pytest.MonkeyPatch, home: Path, detected: dict[str, str], *answers: str) -> dict[str, Any]:
    """Run the real _cmd_init; each prompt takes the next answer, or its own default once none is left."""
    pending = list(answers)
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=StringIO()))
```
REPLACE:
```
def _init(
    monkeypatch: pytest.MonkeyPatch, home: Path, detected: dict[str, str], *answers: str,
    output: StringIO | None = None,
) -> dict[str, Any]:
    """Run the real _cmd_init; each prompt takes the next answer, or its own default once none is left."""
    pending = list(answers)
    sink = StringIO() if output is None else output
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=sink, width=200))
```

**P-2**
SEARCH:
```
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
```
REPLACE:
```
        ("http://localhost:11434/v1", "openai"),
        ("http://localhost:11434/v1/", "openai"),
        ("http://localhost:11434/v1/.", "openai"),
        ("http://localhost:11434", "ollama"),
        ("http://localhost:11434/", "ollama"),
        ("http://localhost:11434//", "ollama"),
        ("http://localhost:11434/./", "ollama"),
        ("http://localhost:11434/v1/..", "ollama"),
        ("http://localhost:11434/a/../", "ollama"),
        ("http://127.0.0.1:8080/v1", "openai"),
        ("http://127.0.0.1:8080", "openai"),
    ],
    # #1414 review: dot segments are judged as httpx sends them (/v1/.. is the root); a port that does not
    # parse is now refused by init (test_init_asks_again_for_a_url_setup_would_refuse).
    ids=[
        "ollama-v1", "ollama-v1-slash", "v1-dot", "ollama-root", "ollama-root-slash", "root-double-slash",
        "root-dot", "v1-dotdot", "sub-dotdot", "proxy-v1", "other-root",
    ],
)
```

**P-3**
SEARCH:
```
        ({}, ("http://localhost:11434", "llama3.1:8b"), "http://localhost:11434", "/api/chat"),
    ],
    ids=["detected-default", "bare-root"],
)
```
REPLACE:
```
        ({}, ("http://localhost:11434", "llama3.1:8b"), "http://localhost:11434", "/api/chat"),
        ({}, ("http://localhost:11434/v1/..", "llama3.1:8b"), "http://localhost:11434/v1/..", "/api/chat"),
    ],
    ids=["detected-default", "bare-root", "root-by-dot-segments"],
)
```

**P-4**
SEARCH:
```
    assert posts, "premise: the client sent its request"
    assert posts[0] == path  # before #1414 the detected default posted /v1/api/chat
```
REPLACE:
```
    assert posts, "premise: the client sent its request"
    assert posts[0] == path  # before #1414 the detected default posted /v1/api/chat


@pytest.mark.parametrize(
    ("refused", "reason"),
    [
        ("http://localhost:11434?q=1", "must not have a query or fragment"),
        ("http://localhost:11434/v1?q=1", "must not have a query or fragment"),
        ("http://localhost:114340/v1", "is not a valid URL"),
    ],
    ids=["root-query", "v1-query", "port-out-of-range"],
)
def test_init_asks_again_for_a_url_setup_would_refuse(
    refused: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = "http://localhost:11434/v1"
    output = StringIO()

    written = _init(monkeypatch, tmp_path / "init", {}, refused, accepted, "llama3.1:8b", output=output)

    # A query would carry the path the client appends (/?q=1/api/chat); setup's rule refuses it.
    assert written["cognitive"]["llm_base_url_fast"] == accepted
    assert reason in " ".join(output.getvalue().split())


def test_a_url_the_client_cannot_parse_is_openai() -> None:
    unparsable = "http://localhost:abc/v1"
    with pytest.raises(httpx.InvalidURL):
        httpx.URL(unparsable)  # premise: the parse the client and init's rule share fails

    assert main_mod._init_api_format(unparsable) == "openai"
```

### 6.21 `tests/test_bf995_setup_redaction.py` (R1)

**P-1**
SEARCH:
```
def _setup(*extra: str) -> int:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args([
        "setup", "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV,
        "--model", "model-x", "--skip-validation", "--yes", *extra,
    ])
```
REPLACE:
```
def _setup(*extra: str, yes: bool = True) -> int:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args([
        "setup", "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV,
        "--model", "model-x", "--skip-validation", *(("--yes",) if yes else ()), *extra,
    ])
```

**P-2**
SEARCH:
```
    assert _setup() == 4

    out = _printed(capsys)
    assert "no space left beside <redacted>" in out  # premise: the failure was printed
    assert _OTHER not in out
```
REPLACE:
```
    assert _setup() == 4

    out = _printed(capsys)
    assert "no space left beside <redacted>" in out  # premise: the failure was printed
    assert _OTHER not in out


def test_redact_keys_hides_a_key_with_no_utf8_form() -> None:
    lone = "\ud800"
    with pytest.raises(UnicodeEncodeError):
        lone.encode("utf-8")  # premise: no UTF-8 form, so no percent-encoded or base64 form either

    assert ps.redact_keys(f"model {lone} here", [lone, _OTHER]) == "model <redacted> here"


@pytest.mark.parametrize("yes", [True, False], ids=["report", "confirm-and-report"])
def test_a_key_with_no_utf8_form_is_hidden_and_setup_completes(
    yes: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A YAML escape gives the vision key and the retained model a lone surrogate; config_text_api_keys keeps it.
    config = _existing(tmp_path, '  llm_api_key_vision: "\\uD800"', '  llm_model_vision: "\\uD800"')
    asked: list[str] = []

    def confirm(prompt: str, *args: object, **kwargs: object) -> bool:
        asked.append(prompt)
        return True

    monkeypatch.setattr("rich.prompt.Confirm.ask", confirm)

    assert _setup(yes=yes) == 0  # before the review, setup raised UnicodeEncodeError after replacing the file

    out = _printed(capsys)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]["llm_model_vision"] == "\ud800"  # premise
    assert len(asked) == (0 if yes else 1)  # premise: only the final question, and only without --yes
    assert out.count("vision (model '<redacted>') uses it") == (1 if yes else 2)


_FILE_SECRET = "sk-bf995-file-secret-N9Q4"


@pytest.mark.parametrize(
    ("key", "key_yaml", "model_yaml", "note"),
    [
        (f"'{_FILE_SECRET}'", f"\"'{_FILE_SECRET}'\"", _FILE_SECRET, "model <redacted>"),
        ("sk-bf995-file\\\\N9Q4", "sk-bf995-file\\\\N9Q4", "sk-bf995-file\\N9Q4", "model '<redacted>'"),
        ("sk-bf995-file\\N9Q4", "sk-bf995-file\\N9Q4", "sk-bf995-file\\N9Q4", "model '<redacted>'"),
    ],
    ids=["quoted", "doubled-backslash", "raw-backslash"],
)
def test_a_shown_model_never_completes_a_file_key(
    key: str, key_yaml: str, model_yaml: str, note: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # quoted and doubled-backslash: the model's repr adds the quotes or the second backslash and so forms the key;
    # raw-backslash: only the raw redaction finds the key, since repr doubles its backslash.
    config = _existing(tmp_path, f"  llm_api_key_vision: {key_yaml}", f"  llm_model_vision: {model_yaml}")
    assert ps.config_text_api_keys(config.read_text(encoding="utf-8")) == [key]  # premise: the file holds the key

    assert _setup() == 0

    out = _printed(capsys)
    assert f"vision ({note}) uses it" in out
    assert key not in out
```

### 6.22 `PROGRESS.md` (R1)

**P-1**
SEARCH:
```
**BF-994 (2026-11-25), #1414 -- `probos init` writes the OpenAI format for Ollama's /v1 default, and the scaffold it shares with `probos setup` sets the shipped 300 s LLM timeout.** `_cmd_init` wrote `llm_api_format_fast: ollama` for any URL holding `:11434`, so its own default, `http://localhost:11434/v1`, posted to `/v1/api/chat`. It now writes `ollama` only for an Ollama root (port 11434, no path), and `openai` otherwise. `tests/test_bf994_init_config_reaches_its_api.py::test_the_init_config_reaches_the_api_its_url_serves` sends a request through the real `OpenAICompatibleClient` built from the written file: the detected default posts to `/v1/chat/completions` and a typed root to `/api/chat`. `test_init_writes_the_format_the_typed_url_serves` covers seven URLs, among them a port that does not parse. The scaffold sets `llm_timeout_seconds: 300.0` under `cognitive:`, the value `config/system.yaml` ships, for init (`test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout`) and for setup's create path (`test_setup_create_path_writes_the_shipped_timeout`). An existing file is given no timeout and keeps its default (`test_setup_on_an_existing_file_adds_no_timeout`); the `CognitiveConfig` default stays 30.0. The init byte goldens in `tests/test_ad1135_provider_setup.py` move by the new line and, for the Ollama row, the format word. `docs/getting-started/configuration.md` and the `docker-compose.yml` comment now say that `PROBOS_LLM_URL` replaces only the shared URL and that a tier with its own `llm_base_url_<tier>` keeps it. Mutation census: 6 of 6 killed (rows A1-M1 to A1-M6, run once on the candidate overlay of `dea82930`), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```
REPLACE:
```
**BF-994 (2026-11-25), #1414 -- `probos init` writes the OpenAI format for Ollama's /v1 default, and the scaffold it shares with `probos setup` sets the shipped 300 s LLM timeout.** `_cmd_init` wrote `llm_api_format_fast: ollama` for any URL holding `:11434`, so its own default, `http://localhost:11434/v1`, posted to `/v1/api/chat`. It now writes `ollama` only for an Ollama root as the client sends it (port 11434, an empty path once the base has its trailing slash and httpx has removed dot segments, so `/v1/..` is a root), and `openai` otherwise, a URL httpx cannot parse included (`test_a_url_the_client_cannot_parse_is_openai`). Init also asks again for a URL that setup's base-URL rule refuses: a query, for one, would carry the path the client appends (`test_init_asks_again_for_a_url_setup_would_refuse`). `tests/test_bf994_init_config_reaches_its_api.py::test_the_init_config_reaches_the_api_its_url_serves` sends a request through the real `OpenAICompatibleClient` built from the written file: the detected default posts to `/v1/chat/completions`, and a typed root and a root written as `/v1/..` to `/api/chat`. `test_init_writes_the_format_the_typed_url_serves` covers eleven URLs, among them roots written with dot segments or a double slash. The scaffold sets `llm_timeout_seconds: 300.0` under `cognitive:`, the value `config/system.yaml` ships, for init (`test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout`) and for setup's create path (`test_setup_create_path_writes_the_shipped_timeout`). An existing file is given no timeout and keeps its default (`test_setup_on_an_existing_file_adds_no_timeout`); the `CognitiveConfig` default stays 30.0. The init byte goldens in `tests/test_ad1135_provider_setup.py` move by the new line and, for the Ollama row, the format word. `docs/getting-started/configuration.md` and the `docker-compose.yml` comment now say that `PROBOS_LLM_URL` replaces only the shared URL and that a tier with its own `llm_base_url_<tier>` keeps it. A query in a hand-edited base URL still reaches the client and is recorded on #1820. Mutation census: 9 of 9 killed (rows A1-M1 to A1-M9, run once on the candidate overlay of `dea82930` after the review repairs), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```

**P-2**
SEARCH:
```
**BF-995 (2026-11-25), #1414 -- setup's provider excerpt stays at 200 characters, and setup hides every API key the existing config holds wherever it prints text read from it.** The excerpt's cut marker is U+2026, which no form of a key holds, so the second redaction in `_result` cannot match or complete a key across the cut. A key of `.` gives a 200-character excerpt where it gave 227 (`tests/test_bf995_setup_redaction.py::test_the_excerpt_for_a_key_of_dots_stays_at_200_characters`), and a key the old cut would have completed is not formed (`test_the_cut_completes_no_key`). Setup now redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file (`config_text_api_keys`, read without validation) at the eight sites that print text from that file. A retained optional-tier model that holds the file's shared, vision or verifier key prints as `<redacted>` (`test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted`). A refusal from reading or editing the file, the `--force` note and a write failure print no key from it (`test_a_refusal_quoting_the_file_prints_no_key_from_it`, `test_a_write_failure_quoting_the_file_prints_no_key_from_it`). Two pins in `tests/test_ad1135_provider_setup.py` now expect the new marker. Mutation census: 7 of 7 killed (rows A2-M1 to A2-M7, run once on the candidate overlay of `dea82930`), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```
REPLACE:
```
**BF-995 (2026-11-25), #1414 -- setup's provider excerpt stays at 200 characters, and setup hides every API key the existing config holds in the messages it prints from that file.** The excerpt's cut marker is U+2026, which no form of a key holds, so the second redaction in `_result` cannot match or complete a key across the cut. A key of `.` gives a 200-character excerpt where it gave 227 (`tests/test_bf995_setup_redaction.py::test_the_excerpt_for_a_key_of_dots_stays_at_200_characters`), and a key the old cut would have completed is not formed (`test_the_cut_completes_no_key`). Setup now redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file (`config_text_api_keys`, read without validation) at the eight sites that print text from that file. A retained optional-tier model that holds the file's shared, vision or verifier key prints as `<redacted>` (`test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted`). A refusal from reading or editing the file, the `--force` note and a write failure print no key from it (`test_a_refusal_quoting_the_file_prints_no_key_from_it`, `test_a_write_failure_quoting_the_file_prints_no_key_from_it`). A key with no UTF-8 form, such as a lone surrogate written as a YAML escape, is matched by its literal text; before the review, setup ended in a traceback after replacing the file (`test_a_key_with_no_utf8_form_is_hidden_and_setup_completes`, `test_redact_keys_hides_a_key_with_no_utf8_form`). The B7 note redacts a retained model before and after `repr`, whose quotes and backslash escapes could otherwise complete a key (`test_a_shown_model_never_completes_a_file_key`). Two limits are recorded on #1820: a key whose text is part of the `<redacted>` marker, such as `ed`, still shows inside each marker, and the lines that print the config's own path show it as given. Two pins in `tests/test_ad1135_provider_setup.py` now expect the new marker. Mutation census: 10 of 10 killed (rows A2-M1 to A2-M10, run once on the candidate overlay of `dea82930` after the review repairs), each by its named cases. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```

### 6.23 `DECISIONS.md` (R1)

**P-1**
SEARCH:
```
- *D1.* `probos init` writes `llm_api_format_fast: ollama` only for an Ollama root (port 11434, empty path); every other URL, init's `/v1` default included, is `openai`. Rejected: always `openai` (a typed root would post to `/chat/completions`), rewriting the typed URL, and the `:11434` substring test.
```
REPLACE:
```
- *D1.* `probos init` writes `llm_api_format_fast: ollama` only for an Ollama root as the client sends it (port 11434, an empty path once the base has its trailing slash and httpx has removed dot segments); every other URL, init's `/v1` default included, is `openai`, as is one httpx cannot parse. Init asks again for a URL that setup's base-URL rule (`normalize_base_url`) refuses: a query, for one, would carry the path the client appends. Rejected: always `openai` (a typed root would post to `/chat/completions`), rewriting the typed URL, the `:11434` substring test, a path test on the URL as typed (`/v1/..` is the root to httpx), and repairing the client's base-URL join for a query (it sits on every request's path; a hand-edited query is recorded on #1820).
```

**P-2**
SEARCH:
```
- *D3.* Setup's excerpt is cut with U+2026 at 200 characters. Setup redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file wherever it prints text from that file; other secrets in the file are out of scope. Rejected: a console that redacts all output (highlighting and markup escaping change a key's bytes, and a short key could break markup).
```
REPLACE:
```
- *D3.* Setup's excerpt is cut with U+2026 at 200 characters. Setup redacts its chosen key and every `cognitive.llm_api_key*` value in the existing file in each message it prints from that file; a key with no UTF-8 form is matched by its literal text, and a model shown with `repr` is redacted before and after it. Two limits are recorded on #1820: a key whose text is part of the `<redacted>` marker shows inside each marker, and the lines that print the config path show it as given. Other secrets in the file are out of scope. Rejected: a console that redacts all output (highlighting and markup escaping change a key's bytes, and a short key could break markup), and redacting the path lines with the file's keys (the path is the operator's own argument or the default under the home directory, and a one- or two-character key would mangle every path setup prints).
```

### 6.24 `src/probos/routers/config.py` (R2)

**P-1**
SEARCH:
```
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
```
REPLACE:
```
    load_config uses. Raises _ConfigUnreadable when the file cannot be checked for or read, is not
    UTF-8, is not YAML or its top level is not a mapping; the reason never quotes the file, since a
    YAML error's own text holds the offending line. PyYAML also fails outside YAMLError: a ValueError
    for an impossible date or an integer of over 4,300 digits, and a RecursionError for deep nesting.
    The existence check is load_config's own, inside the OSError guard: Path.exists() lets an EACCES
    from stat through.
    """
    try:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
```

**P-2**
SEARCH:
```
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
    except OSError as ex:
```
REPLACE:
```
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
    except OverflowError as exc:
        # pydantic wraps only ValueError and AssertionError. A float field, or the math.isfinite of
        # budget_awareness_thresholds, raises this for an integer too large for a float, with no loc;
        # load_config raises the same on such a file at boot (#1820).
        logger.warning(
            "AD-741 config save refused (cfg_path=%s): validating the file raised %s; it is unchanged.",
            cfg_path, type(exc).__name__,
        )
        return JSONResponse(
            status_code=409,
            content={"error": "config_invalid", "errors": [{"loc": [], "type": type(exc).__name__}]},
        )

    try:
        _write_yaml_atomic(cfg_path, to_write)
    except (ValueError, RecursionError) as exc:
        # The dump, _write_yaml_atomic's first statement, runs before any file is opened. It refuses values the file
        # can hold and load_config accepts: an integer of over 4,300 decimal digits (a YAML hex literal loads) and
        # nesting deeper than the dump's recursion allows. The patch, parsed from JSON, holds neither, so the file
        # is named.
        logger.warning(
            "AD-741 config save refused (cfg_path=%s): the dump raised %s; the file is unchanged.",
            cfg_path, type(exc).__name__,
        )
        return JSONResponse(
            status_code=409, content={"error": "config_unreadable", "reason": "holds a value that cannot be written back"},
        )
    except OSError as ex:
```

### 6.25 `tests/test_bf996_hxi_save_on_disk.py` (R2)

**P-1**
SEARCH:
```
def test_drop_null_sections_drops_only_none_and_load_config_uses_it(tmp_path: Path) -> None:
    drop = config_mod.drop_null_sections

    assert drop({"a": None, "b": {}, "c": 0, "d": ""}) == {"b": {}, "c": 0, "d": ""}
    path = tmp_path / "system.yaml"
    path.write_text("memory:\nsystem:\n  name: Kept\n", encoding="utf-8")
    assert load_config(path).system.name == "Kept"
```
REPLACE:
```
def test_drop_null_sections_drops_only_none_and_load_config_uses_it(tmp_path: Path) -> None:
    drop = config_mod.drop_null_sections

    assert drop({"a": None, "b": {}, "c": 0, "d": ""}) == {"b": {}, "c": 0, "d": ""}
    path = tmp_path / "system.yaml"
    path.write_text("memory:\nsystem:\n  name: Kept\n", encoding="utf-8")
    assert load_config(path).system.name == "Kept"


@pytest.mark.parametrize(
    ("data", "refusal"),
    [
        # int() of a hex string has no digit limit, str() of the result does (3,600 hex digits = 4,335 decimal).
        (b"x: 0x" + b"f" * 3600 + b"\n", ValueError),
        # The composer recurses two frames a level, the representer three: 360 levels load but do not dump.
        (b"x: " + b"[" * 360 + b"]" * 360 + b"\n", RecursionError),
    ],
    ids=["hex-int", "nesting"],
)
def test_a_file_holding_a_value_the_dump_refuses_is_refused_and_left_as_it_is(
    data: bytes, refusal: type[BaseException], tmp_path: Path,
) -> None:
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    assert load_config(path).system.log_level == "INFO"  # premise: the file boots (an unknown section is ignored)
    with pytest.raises(refusal):  # premise: PyYAML loads the value but cannot dump it
        yaml.safe_dump(yaml.safe_load(data))
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_unreadable", "reason": "holds a value that cannot be written back"},
    )
    assert path.read_bytes() == data
    assert list(tmp_path.glob("*.tmp")) == []  # the dump runs before a temporary file is made
    assert runtime.config.system.log_level == "INFO"


def test_a_file_a_validator_cannot_check_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    data = b"dm_agentic:\n  budget_awareness_thresholds: [" + b"9" * 400 + b"]\n"
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    # premise: math.isfinite on a 400-digit int raises OverflowError, which pydantic does not wrap, so there is no loc;
    # load_config raises the same at boot (#1820).
    with pytest.raises(OverflowError):
        SystemConfig.model_validate(yaml.safe_load(data))
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_invalid", "errors": [{"loc": [], "type": "OverflowError"}]},
    )
    assert path.read_bytes() == data
    assert runtime.config.system.log_level == "INFO"


def test_a_config_path_the_os_will_not_stat_is_refused_and_left_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "system:\n  name: Kept\n"
    path = tmp_path / "system.yaml"
    path.write_text(text, encoding="utf-8")
    client, runtime = _client(path)
    # Injected: a config path under a directory the process cannot search. Path.exists() ignores ENOENT, ENOTDIR,
    # EBADF and ELOOP only, so the EACCES from stat reaches its caller.
    real_exists = Path.exists

    def exists(self: Path, *args: Any, **kwargs: Any) -> bool:
        if self == path:
            raise PermissionError(13, "Permission denied")
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(PermissionError):  # premise: the injected denial reaches Path.exists' caller
        path.exists()

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_unreadable", "reason": "unreadable (PermissionError)"},
    )
    assert path.read_text(encoding="utf-8") == text
    assert runtime.config.system.log_level == "INFO"


def test_a_directory_at_the_config_path_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.mkdir()
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 409, response.text
    assert response.json()["error"] == "config_unreadable"
    # A real OS read failure: Windows raises PermissionError for a directory, POSIX IsADirectoryError.
    assert response.json()["reason"] in {"unreadable (PermissionError)", "unreadable (IsADirectoryError)"}
    assert path.is_dir()
    assert runtime.config.system.log_level == "INFO"


def test_a_secret_path_is_refused_before_the_file_is_read(tmp_path: Path) -> None:
    data = b"system: [\n"  # unreadable: a guard that ran after the read would answer 409 config_unreadable
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, _ = _client(path)

    response = _save(client, {"cloud_pickers": {"google_drive": {"client_secret": "new-secret"}}})

    assert (response.status_code, response.json()) == (
        400, {"error": "secret_field_readonly", "blocked": ["cloud_pickers.google_drive.client_secret"]},
    )
    assert path.read_bytes() == data
```

### 6.26 `PROGRESS.md` (R2)

**P-1**
SEARCH:
```
**BF-996 (2026-11-25), #1414 -- an HXI settings save merges its patch onto the config file as it is on disk, so edits made since boot are kept.** `POST /api/config` wrote a dump of the configuration the process booted with. It now writes the file's own sections plus the patch, with all-commented sections dropped by `drop_null_sections`, the helper `load_config` now shares, and validates that result before writing it. An out-of-band edit and an earlier save awaiting restart both survive (`tests/test_bf996_hxi_save_on_disk.py::test_a_save_keeps_an_edit_made_to_the_file_after_boot`, `test_two_saves_before_a_restart_keep_both_changes`). A value set by `PROBOS_LLM_URL` is not written (`test_a_save_writes_no_value_the_environment_set`). A missing file receives only the patch (`test_a_save_onto_a_missing_file_writes_only_the_patch`), and a secret already in the file stays (`test_a_secret_already_in_the_file_survives_a_save`). A file that cannot be read, is not UTF-8, is not YAML (an impossible date or nesting past the recursion limit included) or is not a mapping answers 409 `config_unreadable` and is left byte for byte (`test_an_unusable_file_is_refused_and_left_as_it_is`). One that does not validate answers 409 `config_invalid` with `loc` and `type` only (`test_a_file_that_does_not_validate_is_refused_without_quoting_it`). The secret-path guard, the runtime 422, `changed_fields` and hot reload are unchanged (`tests/test_ad741_config_api.py`, `tests/test_ad741_integration.py`, `tests/test_ad741_secret_redaction.py`). `tests/test_bf908_crew_scope_token.py` now expects no `auth` section in the written file. The facade baseline gains `drop_null_sections`. Mutation census: 9 of 9 killed (rows A3-M1 to A3-M9, run once on the candidate overlay of `dea82930`), each by its named cases; A3-M10 is a review property. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```
REPLACE:
```
**BF-996 (2026-11-25), #1414 -- an HXI settings save merges its patch onto the config file as it is on disk, so edits made since boot are kept.** `POST /api/config` wrote a dump of the configuration the process booted with. It now writes the file's own sections plus the patch, with all-commented sections dropped by `drop_null_sections`, the helper `load_config` now shares, and validates that result before writing it. An out-of-band edit and an earlier save awaiting restart both survive (`tests/test_bf996_hxi_save_on_disk.py::test_a_save_keeps_an_edit_made_to_the_file_after_boot`, `test_two_saves_before_a_restart_keep_both_changes`). A value set by `PROBOS_LLM_URL` is not written (`test_a_save_writes_no_value_the_environment_set`). A missing file receives only the patch (`test_a_save_onto_a_missing_file_writes_only_the_patch`), and a secret already in the file stays (`test_a_secret_already_in_the_file_survives_a_save`). A file that is not UTF-8, is not YAML (an impossible date or nesting past the recursion limit included) or is not a mapping answers 409 `config_unreadable` and is left byte for byte (`test_an_unusable_file_is_refused_and_left_as_it_is`). So does a config path the OS will not stat (`test_a_config_path_the_os_will_not_stat_is_refused_and_left_as_it_is`, the denial injected) or read (`test_a_directory_at_the_config_path_is_refused_and_left_as_it_is`), and a file holding a value the YAML dump refuses: an integer of over 4,300 decimal digits written in hex, or nesting too deep to dump (`test_a_file_holding_a_value_the_dump_refuses_is_refused_and_left_as_it_is`). One that does not validate answers 409 `config_invalid` with `loc` and `type` only (`test_a_file_that_does_not_validate_is_refused_without_quoting_it`). One whose validation raises `OverflowError` (an integer too large for a float in `dm_agentic.budget_awareness_thresholds`) answers 409 `config_invalid` with one entry whose `loc` is empty (`test_a_file_a_validator_cannot_check_is_refused_and_left_as_it_is`); the validator, which stops `load_config` at boot on the same file, is a #1820 item. The secret-path guard still runs before the file is read (`test_a_secret_path_is_refused_before_the_file_is_read`); it, the runtime 422, `changed_fields` and hot reload are unchanged (`tests/test_ad741_config_api.py`, `tests/test_ad741_integration.py`, `tests/test_ad741_secret_redaction.py`). `tests/test_bf908_crew_scope_token.py` now expects no `auth` section in the written file. The facade baseline gains `drop_null_sections`. Mutation census: 14 of 14 killed (rows A3-M1 to A3-M9 and A3-M11 to A3-M15, run once on the candidate overlay of `dea82930` after the review repairs), each by its named cases; A3-M10 is a review property. Contract `prompts/bf-994-996-1414-batch-a-cli-config.md`.
```

### 6.27 `DECISIONS.md` (R2)

**P-1**
SEARCH:
```
- *D4.* An HXI save writes the on-disk mapping plus the patch, validated, never a dump of the running config; an unusable file answers 409 `config_unreadable`, an invalid result 409 `config_invalid` with `loc` and `type` only. No await runs between the read and the write. Rejected: refusing a save when the file's hash differs from boot (runtime plumbing, and it blocks a legitimate save).
- *Reversal.* Revert the slice's commit; each slice is independent. The M4 facade baseline row for `drop_null_sections` goes with BF-996.

### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)
```
REPLACE:
```
- *D4.* An HXI save writes the on-disk mapping plus the patch, validated, never a dump of the running config; an unusable file answers 409 `config_unreadable` (one the OS will not stat or read, and one holding a value the YAML dump refuses, included), an invalid result 409 `config_invalid` with `loc` and `type` only, and a validator's `OverflowError` 409 `config_invalid` with one entry, `loc` empty. No await runs between the read and the write. Rejected: refusing a save when the file's hash differs from boot (runtime plumbing, and it blocks a legitimate save); making the `budget_awareness_thresholds` validator raise `ValueError` in this batch (it changes `load_config`'s boot failure on such a file, which this batch keeps; #1820).
- *Reversal.* Revert the slice's commit; each slice is independent. The M4 facade baseline row for `drop_null_sections` goes with BF-996.

### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)
```

## 6c. Verified Against Codebase and Absence Verified (review round 1 repairs, 2026-11-25)

### R1 (the head `93024759`)

**Verified against the head `93024759` (rva1, 2026-11-25)**
```
src/probos/__main__.py
  1141-1155 _init_api_format (urlsplit, parts.path.strip("/"))
  1159-1162 _cmd_init docstring, "from rich.prompt import Prompt", console = Console()
  1196-1200 default_url mapping; 1200 llm_url = Prompt.ask("  LLM endpoint URL", ...)
  1655-1659 _setup_shared_url_notes: shown = redact_keys(model, keys); escape(repr(shown))
  1679, 1684, 1693-1697, 1776 path displays (recorded, not changed)
  54 from probos import provider_setup; 65 import httpx (TYPE_CHECKING); 1035 local import httpx
src/probos/provider_setup.py
  143-164 normalize_base_url (152-153 query/fragment refusal; 157-158 "is not a valid URL")
  284-293 _key_forms (285 api_key.encode("utf-8")); 327-331 redact_keys; 340-357 config_text_api_keys
src/probos/cognitive/llm_client.py:866  normalized = tc["base_url"].rstrip("/") + "/"
tests/test_bf994_init_config_reaches_its_api.py  47-57 _init; 101-113 format rows; 123-129 e2e rows; 141-142
tests/test_bf995_setup_redaction.py  42-49 _setup; 52-57 _existing; 136-140 last lines
tests/test_ad1135_setup_cli.py:1596-1611  init asks exactly two prompts with a valid URL (unaffected)
tests/test_claude_bootstrap_init_defaults.py:33,48,61,73 and tests/test_distribution.py:987-1041  feed valid URLs or defaults
```

**Absence verified (2026-11-25)**

| Claim | Run | Found | Holds |
|---|---|---|---|
| The only `repr` in setup's file-text prints is the B7 note | Grep `repr\(` in `__main__.py`, `provider_setup.py` | `__main__.py:1659`; `provider_setup.py:544` (probe text, redacted afterwards by `_result`) | yes |
| `_key_forms` is the only encode on the redaction path | Grep `\.encode\(\|quote\(\|quote_plus\(` in the same files | `provider_setup.py:285, 288, 289` (inside `_key_forms`), `:928` (the file write) | yes |
| No test pins `redact` raising on a surrogate | Grep `UnicodeEncodeError\|ud800` in `tests/` | no hit in any `provider_setup` or setup test | yes |
| Redaction consumers reached by R1 | Grep `redact_keys\|_key_forms\|carries_key` in `tests/` | `test_ad1135_provider_setup.py`, `test_ad1135_setup_cli.py`, `test_ad1137_doctor.py`, `test_ad1137_quickstart_chain.py`, `test_ad1327_verifier_independence.py` | in the focused command |

### R2 (the head `93024759` plus R1)

- `routers/config.py`:
  - :162 `if not path.exists():` sits before the `try` at :164.
  - :172 the reader's `except (yaml.YAMLError, ValueError, RecursionError)`.
  - :184 `body = yaml.safe_dump(...)` comes before :185 `mkstemp`.
  - :315 is `except ValidationError` only.
  - :327 is `except OSError` only.
  - :32 `import yaml`.
- `config_models/agentic.py:810` `math.isfinite(item)`; `config.py:4016` `dm_agentic: DmAgenticConfig`.
- `config.py:4168` `load_config` uses `path.exists()`.
- `useSettingsStore.ts:224-228` shows `body.error ?? 'unknown'` for any other status.
- `test_ad741_secret_redaction.py:76-88` gives the secret path `cloud_pickers.google_drive.client_secret` and `blocked`.

#### Absence Verified (2026-11-25)
- CLAIM: no test pins the changed router lines by reading source. RUN: Grep `routers/config\.py` in `tests/`. FOUND: `test_ad741_config_api.py:179` (a `MagicMock` sentinel only), the census fixture `:175` (writer description, unchanged), and `test_ad1151...:769,789` (prose). HOLDS: yes.
- CLAIM: no existing test sends a `ValueError` through `_write_yaml_atomic`. RUN: Grep `write_failed|safe_dump|OverflowError|exists` in `tests/test_ad741*.py`. FOUND: only `yaml.safe_dump({})` fixture writes. HOLDS: yes.

Prior-art search was skipped: this is ProbOS router plumbing with no outside analogue.

## 7. Mutation census and generated-artifact commands

| Row | Mutant | Killer |
|---|---|---|
| A1-M1 | the rule reverts to `":11434" in llm_url` | `test_init_writes_the_format_the_typed_url_serves[ollama-v1,ollama-v1-slash,v1-dot]`, `test_the_init_config_reaches_the_api_its_url_serves[detected-default]` (R1: rerun, killer list changed) |
| A1-M2 | always `openai` | `test_init_writes_the_format_the_typed_url_serves[ollama-root,ollama-root-slash]`, `test_the_init_config_reaches_the_api_its_url_serves[bare-root]` |
| A1-M3 | the port check is dropped (any root is `ollama`) | `test_init_writes_the_format_the_typed_url_serves[other-root]` |
| A1-M4 | the scaffold's timeout line is removed | `test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout`, `test_setup_create_path_writes_the_shipped_timeout`, the goldens |
| A1-M5 | the scaffold writes `30.0` | same as A1-M4 |
| A1-M6 | setup's managed values add `llm_timeout_seconds` | `test_setup_on_an_existing_file_adds_no_timeout` |
| A1-M7 | `_init_api_format` judges `urlsplit(llm_url).path`, the URL as typed | `test_init_writes_the_format_the_typed_url_serves[root-dot,v1-dotdot,sub-dotdot]`, `test_the_init_config_reaches_the_api_its_url_serves[root-by-dot-segments]` |
| A1-M8 | `_cmd_init` takes the first URL without `normalize_base_url` | `test_init_asks_again_for_a_url_setup_would_refuse[*]` |
| A1-M9 | `_init_api_format`'s `except` clause is removed | `test_a_url_the_client_cannot_parse_is_openai` |
| A2-M1 | the marker reverts to `"..."` with the cut at -3 | `test_the_excerpt_for_a_key_of_dots_stays_at_200_characters`, `test_the_cut_completes_no_key`, `test_ad1135_provider_setup.py:425,470` |
| A2-M2 | `_CUT_MARKER` is kept but the cut stays at -3 (198 characters) | `test_the_excerpt_for_a_key_of_dots_stays_at_200_characters` (asserts 200), `test_the_cut_completes_no_key` |
| A2-M3 | the shared-URL notes redact only the chosen key | `test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted[*]` |
| A2-M4 | `config_text_api_keys` reads only `llm_api_key` | `test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted[llm_api_key_vision,llm_api_key_verifier]` |
| A2-M5 | `file_keys` is computed after `optional_tier_endpoints` | `test_a_refusal_quoting_the_file_prints_no_key_from_it[reading-the-file]` |
| A2-M6 | `_setup_candidate`'s refusal is not redacted | `test_a_refusal_quoting_the_file_prints_no_key_from_it[editing-the-file,force-rewrite-note]` |
| A2-M7 | the write-failure site redacts only the chosen key | `test_a_write_failure_quoting_the_file_prints_no_key_from_it` |
| A2-M8 | `_key_forms` lets `UnicodeEncodeError` through | `test_redact_keys_hides_a_key_with_no_utf8_form`, `test_a_key_with_no_utf8_form_is_hidden_and_setup_completes[*]` |
| A2-M9 | the B7 note prints the `repr` of the redacted model without redacting it again (the head's line) | `test_a_shown_model_never_completes_a_file_key[quoted,doubled-backslash]` |
| A2-M10 | the B7 note redacts only the `repr` text | `test_a_shown_model_never_completes_a_file_key[raw-backslash]` |
| A3-M1 | the save writes `new_cfg.model_dump(mode="json")` | `test_a_save_keeps_an_edit_made_to_the_file_after_boot`, `test_two_saves_before_a_restart_keep_both_changes`, `test_a_save_writes_no_value_the_environment_set`, `test_a_save_onto_a_missing_file_writes_only_the_patch`, `test_a_section_whose_values_are_all_commented_out_does_not_block_a_save`, `test_a_secret_already_in_the_file_survives_a_save` |
| A3-M2 | the disk-mapping validation is removed | `test_a_file_that_does_not_validate_is_refused_without_quoting_it` |
| A3-M3 | `_ConfigUnreadable` is treated as `{}` | `test_an_unusable_file_is_refused_and_left_as_it_is[*]` |
| A3-M4 | the router skips `drop_null_sections` | `test_a_section_whose_values_are_all_commented_out_does_not_block_a_save` |
| A3-M5 | the 409 errors include `msg` or `input` | `test_a_file_that_does_not_validate_is_refused_without_quoting_it` |
| A3-M6 | `drop_null_sections` drops every falsy value | `test_drop_null_sections_drops_only_none_and_load_config_uses_it` |
| A3-M7 | the secret guard is removed | `tests/test_ad741_secret_redaction.py::test_post_config_rejects_secret_field_paths` |
| A3-M8 | a missing file answers 409 | `test_a_save_onto_a_missing_file_writes_only_the_patch` |
| A3-M9 | the YAML `except` clause catches only `yaml.YAMLError` | `test_an_unusable_file_is_refused_and_left_as_it_is[impossible-date,deep-nesting]` |
| A3-M10 | `changed_fields` is computed from the disk diff | no test; Diff Reviewer property A3-5 |
| A3-M11 | the write's dump clause (`ValueError`, `RecursionError`) is removed | `test_a_file_holding_a_value_the_dump_refuses_is_refused_and_left_as_it_is[*]` |
| A3-M12 | the write's dump clause catches only `ValueError` | `test_a_file_holding_a_value_the_dump_refuses_is_refused_and_left_as_it_is[nesting]` |
| A3-M13 | the disk validation's `OverflowError` clause is removed | `test_a_file_a_validator_cannot_check_is_refused_and_left_as_it_is` |
| A3-M14 | `path.exists()` runs before the reader's `try` again | `test_a_config_path_the_os_will_not_stat_is_refused_and_left_as_it_is` |
| A3-M15 | the secret guard is moved after the disk read | `test_a_secret_path_is_refused_before_the_file_is_read` |

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
- A1-1: `_cmd_init` writes `ollama` only when the URL, given one trailing slash and parsed by httpx as the client does (dot segments removed), has port 11434 and an empty or slash-only path. Every other URL, including `http://localhost:11434/v1` and `/v1/.`, and a URL httpx cannot parse, gets `openai`. The model-default line is unchanged.
- A1-2: the only scaffold change is `llm_timeout_seconds: 300.0` under `cognitive:`. Setup's edit and `--force` paths never add it, and the `CognitiveConfig` default stays 30.0.
- A1-3: the init goldens move only by that line and by the Ollama row's format word; the comment says why.
- A1-4: the docs and the compose comment say `PROBOS_LLM_URL` replaces only the shared URL and that per-tier URLs win. The compose example still ends in `/v1`.
- A1-5: init asks for the endpoint URL again, printing setup's reason, for any URL `provider_setup.normalize_base_url` refuses (a query or fragment, credentials, whitespace, a scheme other than http(s), no host, a port that does not parse or is 0), and writes the URL as typed once one passes.

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
- A2-5: no message setup prints from text it read from the existing file shows a key, and "API key: present / not set" is unchanged. Out of scope, recorded on #1820: the lines that print the target path, and a key whose text is part of `<redacted>`.
- A2-6: `_key_forms` never raises: a key with no UTF-8 form yields its literal text only, and every other key yields the same five forms as before.
- A2-7: `_setup_shared_url_notes` redacts the model, then redacts the `repr` of the result, and prints that with no further `repr`.

**A3. Consumers:** the HXI settings store (`ui/src/store/useSettingsStore.ts:196-229`) and the next boot's `load_config`.
- A3-1: what is written equals `_deep_merge(on-disk mapping, patch)`. The on-disk mapping is passed through `drop_null_sections`, the same function `load_config` calls, and is never a dump of `runtime.config`.
- A3-2: that mapping passes `SystemConfig.model_validate` before the write. On failure the answer is 409 `config_invalid` with `loc` and `type` only, and the file and `runtime.config` are unchanged. An `OverflowError` from a validator, which pydantic does not wrap, answers 409 `config_invalid` with the one entry `{"loc": [], "type": "OverflowError"}`; the validator itself is a #1820 item.
- A3-3: a missing file starts from `{}`. A file whose existence check or read raises `OSError`, that is not UTF-8, is not YAML (an impossible date and nesting past the recursion limit included) or is not a mapping answers 409 `config_unreadable` with a fixed reason and is left untouched. So does a file holding a value `yaml.safe_dump` refuses (`ValueError` or `RecursionError` from the dump, which runs before any file is opened), with the reason `holds a value that cannot be written back`.
- A3-4: no `await` runs between the disk read and `_write_yaml_atomic`.
- A3-5: the secret guard (400) runs first. The runtime merge and 422, the 503, the runtime-based `changed_fields` and hot reload are unchanged.
- A3-6: `load_config` behaves the same for every input, including the `AttributeError` for a top level that is not a mapping.
- A3-7: no value set by the environment reaches the file.
- A3-8: setup's note no longer says a save rewrites the file from the boot configuration.
- A3-9: the `test_bf908` pin change carries its reason inline.

**#1414 landing comment:**

```
Batch A (CLI and configuration) is merged in <PR #...> (<sha>), gated by <receipt path, receipt sha>.

- [x] Item 2 (init with Ollama posted to /v1/api/chat): BF-994. init writes the openai format for its /v1 default; only an Ollama root as the client sends it (port 11434, an empty path once dot segments are removed) keeps ollama, and init asks again for a URL setup's rule refuses, such as one with a query. Proof: tests/test_bf994_init_config_reaches_its_api.py, a real OpenAICompatibleClient over a mock transport (POST /v1/chat/completions for the detected default, /api/chat for a typed root and for /v1/..).
- [x] Item 5 (30 s timeout in generated configs): BF-994. The scaffold shared by init and setup's create path sets llm_timeout_seconds: 300.0; existing files are unchanged.
- [x] Item 4 (PROBOS_LLM_URL reaches only the shared URL): behaves as documented; docs/getting-started/configuration.md and the docker-compose.yml comment now say a tier with its own llm_base_url_<tier> keeps it. No code change.
- [x] Item 6 (excerpt over 200 characters): BF-995. Cut marker U+2026; a key of "." gives 200 characters (227 before).
- [x] Item 7 (setup redacts only the key being configured): BF-995. Setup redacts every cognitive.llm_api_key* value in the existing file at the eight sites that print text from it, a key with no UTF-8 form and a model shown with repr included. Other secret kinds in the file are out of this item's scope; the config path lines and a key that is part of the <redacted> marker are recorded on #1820.
- [x] Item 3 (HXI save reverts out-of-band edits): BF-996. The save merges its patch onto the file as it is on disk; a file it cannot stat, read, parse, validate or write back answers 409 and is left as it is. Proof: tests/test_bf996_hxi_save_on_disk.py through the real router. The budget_awareness_thresholds validator's OverflowError, which also stops a boot, is a #1820 item.

Mutation census: A1 9/9, A2 10/10, A3 14/14 killed; A3-M10 is a review property.
Not ticked here: items 1, 8 to 14 (Batches B and C, the item 10 consolidation, item 13 as a limit).
```

The comment ticks items 2, 3, 4, 5, 6 and 7. It does not tick item 1 (shipped earlier in `3f226065`, outside this batch) or items 8 to 14.
