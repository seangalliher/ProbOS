# AD-1337 S1 (#1560): one owner masks every known credential value in text or a tool result as `<secret:NAME>`; no seam calls it yet

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21 (rev2)

**Status:** oracle-proven twice.
- **Draft:** 67 passed.
- **rev1:** 74 passed; F1 fixed, where the environment source had dropped a secret starting with `/`.
- **rev2:** adds six tests for the mutation campaign's real survivors and the text fixes.

Batch 1 is S1, S2 and S3: one PR and one broad gate. Every commit and the PR say `Refs #1560`. #1560 closes only after S4 (batch 2, the per-run vault values) has landed and every acceptance line holds. S1 must not merge alone (it is built, tested and inert). Decision: consult `4bb6d748`, recorded on #1560 (comment 7064966284) and refined here in D1 to D3. No Captain condition.

**Base:** `origin/main` `5d8a5eb4` (PR #1845 merged). AD-1360 touched none of S1's files.

**Line endings:** `credential_store.py`, `PROGRESS.md` and `DECISIONS.md` are `i/lf w/crlf`. The SEARCH blocks are LF; match and write each file with its own endings. The two new files are LF and ASCII only. No SEARCH contains a character outside ASCII.

**Milestones** (one Builder delegation each; the Builder applies the pairs and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then 7.2 (new module), then C1 to C4 | HIGH | **Shared contract:** a security control and a new public function in `credential_store.py`. One full review by the GPT Diff Reviewer. |
| M2 | TR1, TR2, then the ledger (7.4 to 7.6) | LOW | Delta |

- **Commit subjects:**
  - M1: `Add the secret masker and the credential store's value read for it`
  - M2: `Record the secret masker in the status and decisions entries`
- **Effort:** about 25 Builder tool calls for M1 and 12 for M2.

## 0. Premises (this tree)

| P | Premise | Evidence |
|---|---|---|
| P1 | Store state | `credential_store.py:84-99` (`_specs`, `_cache`, `_store`, `crew_scope`). `_load_store` (`:144-161`) is idempotent, so a concurrent first call at worst repeats the same writes. |
| P2 | `rotate` | `:168-213`. It writes `_store[name]` and pops `_cache` (`:195-197`). It returns False without writing when the spec's env var is set (`:187-193`). |
| P3 | `get` | `:269-342`. Department gate `:292-299`, tier gate `:304-320`, cache on success `:338-340`. `_log_access` (`:395-410`) runs on every path. |
| P4 | Resolution chain | `_resolve` (`:344-382`): config, env, aliases, store, CLI (`subprocess.run` at `:372`). `_resolve_config_key` is at `:384-393`. |
| P5 | Crew-scope token | `CrewScopeKeyring.token(config)` at `crew_scope.py:338-342` and `configured_crew_scope_token` at `:99-107` are pure reads. |
| P6 | SRP gate | `CredentialStore` has 15 direct methods (`:73-425`). A 16th fails `check_architecture_principles.py --check` (`:187-188`, `:568`; the gating categories are at `:158-165`). |
| P7 | BF-890's rule | `command_env.py:51-57` (words, segments); `_is_credential_shaped` at `:85-91`; the public `env_name_refusal` at `:94-104`. |
| P8 | `ToolResult` | `tools/protocol.py:80-91` is a frozen dataclass with `output`, `error`, `duration_ms` and `metadata`. Subclasses add kw-only fields. Two have a `__post_init__` that type-checks their own fields (`delegation_evidence.py:224-229`, `publish_finding_tool.py:135-140`); see also `swe_harness/tools.py:256-296`. |
| P9 | Layers | `security` and `tools` are unmapped in `tests/test_layer_boundaries.py:16-27`. |
| P10 | Construction | `runtime.credential_store = CredentialStore(` is at `runtime.py:740`. `finalize.py:4690-4715` sets `_store_path` after construction, so `_load_store` stays unloaded until then (`:146`). |

## 1. Problem

Nothing masks a known credential value in tool output (#1560). The masking needs one owner that S2's producer seam and S3's render seam both call. That owner must:
- read the store without side effects;
- read the environment by a rule that does not rewrite ordinary text (on 2026-11-21, BF-890's rule matched 5 of 89 names in the orchestrator's shell, and 4 of them were not secrets);
- follow rotation.

## 2. Overview

| Part | Change |
|---|---|
| `security/secret_masking.py` (new) | `SecretMasker.mask_text`, `.mask_result`; `SecretRegistry`, `SecretHandle`; `EnvSecretSource`, `env_name_is_mask_shaped`; `secret_forms`, `secret_label`; `MaskOutcome`, `MaskedResult`; constants |
| `credential_store.py` | `_last_resolved` (set by `get` on success, popped by `rotate`); module function `masked_credential_values(store)` |

**Heavier designs rejected:**
- A method on `CredentialStore`: it trips the SRP gate (P6).
- One regex alternation over every pattern: 389 ms on 1 MiB with 50 values (E1), against 27 ms for the prefilter.
- Leftmost-wins regex substitution: it leaves the tail of an overlapping longer value visible (D3).
- Deciding paths by value (`os.path.isabs`): it drops a real secret starting with `/`, and the result depends on the platform and the Python version (F1).
- Entropy detection: Do Not Build.
- An off switch: consult Q6.

## 3. Consumers checked

| Changed | Consumers | Result |
|---|---|---|
| `get` records `_last_resolved` | `repair_issue.py:134-138` (the `Credentials` protocol); `commands_status.py:191-197` (`list_credentials` -> `available` -> `get`); `tests/test_credential_store.py` (clears `_cache` at `:45`, `:85`, `:131`); `test_ad456c_per_tier_credentials.py`; `test_bf908_crew_scope_token.py:650-679` | Additive. The return value, the access rows, the events and both gates are unchanged. |
| `rotate` pops `_last_resolved` | `test_ad456_security_infrastructure.py:62-118`; the BF-908 rotate case at `:676-679`; `tests/fixtures/ad1346_file_write_census.py:211` (the write is unchanged) | Additive |
| New `masked_credential_values` | Its only caller is `SecretMasker` (pinned by N31). No new subprocess: `ad1346_effect_census.py:139` and `test_bf892_spawn_env_guard.py:95` still count 1, in `_resolve`. No new event-log pair (`test_ad1195_eventlog_pair_freeze.py:130`). | Census unchanged |
| BF-908's property that the keyring token never leaves through `get`, `list_credentials` or `rotate` | The function returns the token to the masker, which turns it into patterns and never hands it out. `test_bf908...:664-671` still holds. | Unchanged. The new reader is named in its docstring and in DECISIONS. |
| BF-890 | `command_env.py` is not edited. The mirror test `test_bf890_command_env.py:441-448` compares `operations.py` with `command_env`, which is untouched. N22 and N23 import the public `env_name_refusal`. Every name the new rule accepts, BF-890 also refuses (oracle O7). | Unchanged |
| Config facade and profiles | No field is added. | None |
| Architecture check | No new class over its bounds; `CredentialStore` stays at 15 methods; no layer, db-connect or unowned-task finding. | `--check` passes (O8) |

**Not checked:** a live boot, and the vessel's `.env`, traces or store. S1 reads none of them.

## 4. Decisions

- **D1 (store read).** `masked_credential_values(store)` returns `(name, value)` pairs from five sources: each spec's config value; its env var and aliases (`.strip()`, as `_resolve` does); every JSON-store entry; `_last_resolved`; and the crew-scope token, only when it is a non-empty `str`. It runs no CLI, writes no access row and applies no gate. It is a module function because of P6. N31 pins its only caller.
- **D2 (environment names).** `env_name_is_mask_shaped` narrows BF-890's rule: every name it accepts, BF-890 also refuses (N22). It decides by name only, never by value.
  1. **Not masked, checked first:** a name whose last `_` segment is a path word (`FILE`, `PATH`, `SOCK`, `SOCKET`, `DIR`, `DIRECTORY`), or the whole name `PWD` or `GOOGLE_APPLICATION_CREDENTIALS`.
  2. **Then masked:**
     - a name containing `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `PASSPHRASE`, `CREDENTIAL` or `APIKEY`;
     - a whole segment `PAT`, `PASS`, `PWD`, `DSN`, `CREDS` or `AUTH`;
     - `KEY` or `KEYS` as the last segment, or right after `API`, `ACCESS`, `PRIVATE`, `SIGNING`, `ENCRYPTION`, `MASTER`, `CLIENT`, `ACCOUNT`, `SERVICE` or `LICENSE`.
  3. **Dropped from BF-890's rule:** `SESSION`, `COOKIE` and `PRIVATE`; `AUTH` inside a longer word; `KEY` anywhere else; the `PROBOS_` prefix rule.
  4. **Not added:** a UUID exclusion, because some tokens are UUIDs and `*_SESSION_ID` is already excluded by name. No excluded-names tuple beyond the two path names, because the rule already excludes E2's four false positives and N23 pins them.
  5. **Why not by value (F1):** a base64-alphabet secret starts with `/` about one time in 64, and `os.path.isabs("/x")` is True on Windows under Python 3.12. The worst case of a name-only rule is cosmetic over-masking of a path held under a secret-shaped name whose last segment is not a path word.

  Each value is labelled `env:NAME`.
- **D3 (substitution).** A prefilter (`form in text`) keeps only the forms present. Every occurrence of each present form is found, overlapping ones included. Overlapping spans are merged into one span, labelled with the longest occurrence; on a tie the earlier start wins, then the smaller label. Spans that only touch stay separate.
- **D4 (forms).** For the whole value and its CRLF-to-LF variant:
  - JSON-escaped, both with and without ASCII escaping;
  - URL-encoded from the value's UTF-8 bytes with `quote(safe="")`, `quote(safe="/")` and `quote_plus`, each in upper-hex and lower-hex;
  - base64 of the UTF-8 bytes, standard and URL-safe: the padded full encoding, the unpadded one, and `utf8[a:]` cut to a multiple of 3 bytes for `a` in 0, 1 and 2.

  For a multi-line value, each stripped line also counts, except PEM fence lines. A form shorter than the floor is dropped, and a value shorter than the floor has no forms.
- **D5 (results).** `mask_result` masks `output` and a `str` `error`. It walks only exact `dict` (values, never keys), `list` and `tuple`, within `max_depth` and `max_nodes`; other types are left to the render seam (S3). `metadata` is never touched. On a hit it uses `dataclasses.replace`; with no hit it returns the same object.
- **D6 (sources and precedence).** Each pass reads the store, then the registry, then the environment, and strips every value. The first source to name a value wins; within a source, the smaller name wins. The pattern table is rebuilt only when the content of the value set changes.
- **D7 (failure).** The pass fails closed. `mask_text` returns `MASKING_FAILED_TEXT`; `mask_result` returns a plain `ToolResult(error=MASKING_FAILED_TEXT, duration_ms=..., metadata=...)`; both set `failed=True`. One ERROR line names `type(exc).__name__` only, with no traceback. A wrong input type raises `TypeError` before the pass, because it is a caller bug.
- **D8 (not measured).** The floor (8), `max_depth` (32) and `max_nodes` (10,000) are module constants and constructor arguments. The oracle measured the cost of a pass (O6), not the bounds.

## 5. Tests: new file `tests/test_ad1337_secret_masking.py` (84 cases)

| N | Case | Base | After M1 |
|---|---|---|---|
| N1-N8 | Forms: raw and JSON; URL [3]; base64 at every alignment [12]; floor; nested; overlapping; multi-line; idempotent | collection error | pass |
| N9-N10 | Golden identity (`is`) with no values, and with values but no match | error | pass |
| N11-N16 | `mask_result`: str, error and metadata; containers; other types; subclass; bounds; defaults and bad arguments | error | pass |
| N17-N19 | Fail closed and its log line; the `unnamed` label; source precedence | error | pass |
| N20-N21 | Registry release; registry across threads | error | pass |
| N22-N25 | Masked names [16]; names not masked, path names included [16]; the source decides by name and keeps a `/`-prefixed secret; the live environment is read on each pass | error | pass |
| N26-N31 | Each store source; a CLI-only value is kept; no CLI and no access row; rotation; a rotation the env refuses; the only caller | error | pass |
| N32-N37 | Padded store and registry values; a non-ASCII value in five forms [5]; an unpadded whole base64; a `MagicMock` config gives no values; the `floor` argument; a form found only across the NUL join | error | pass |

- **Base:** collection error, `ImportError: cannot import name 'masked_credential_values' from 'probos.credential_store'`.
- **After M1:** 84 passed. The focused gate is in section 12.

## 6. What S2, S3 and S4 need from S1 (no redesign)

| Need | S1 API | Shape | Threads | Raises |
|---|---|---|---|---|
| Build once (S2, in `finalize.py`) | `SecretMasker(*, credential_store: CredentialStore, registry: SecretRegistry, env_source: EnvSecretSource, floor=8, max_depth=32, max_nodes=10_000)` | No optional source, so there is no empty masker. S2 sets `runtime.secret_registry = SecretRegistry()` and `runtime.secret_masker`. | any | `TypeError` for a source that is not the real type (a `MagicMock` too); `ValueError` for a bound under 1 |
| Producer seam (S2) | `masker.mask_result(result) -> MaskedResult(result, names, failed)` | `result is` the input when nothing matched; the subclass and its fields are kept. On failure: a plain `ToolResult` with `error == MASKING_FAILED_TEXT`, the same `duration_ms` and `metadata`, and `failed=True`. | any thread; it can run in `asyncio.to_thread` (cost: O6) | `TypeError` for a non-`ToolResult`; nothing else |
| Render seam (S3) | `masker.mask_text(text) -> MaskOutcome(text, names, failed)` | `text is` the input when nothing matched; on failure, `MASKING_FAILED_TEXT` and `failed=True` | any | `TypeError` for a non-`str` |
| Event (S2) | `names` | A frozenset of labels, each matching `[A-Za-z0-9_.:-]{1,64}` or else `unnamed`; never a value | - | - |
| Priming (S2) | `credential_store.get("github", requester="secret_masking")` | Fills `_last_resolved`; writes one honest access row; respects both gates | run in a worker thread (it runs the CLI) | unchanged |
| S4 (batch 2) | `runtime.secret_registry.register(name, value) -> SecretHandle`; `handle.release()` (repeatable; also a context manager) | S4 registers `vault:<site>` and `mcp:<server>` and releases them on session close or disconnect. A value under the floor is accepted but not masked. | locked | `TypeError` for a non-`str` name or value |

## 7. The contract

### 7.1 New file `tests/test_ad1337_secret_masking.py` (M1, written first)

```python
"""AD-1337 S1 (#1560): the secret masker and the credential store's value read.

Proves, with a real CredentialStore on a tmp file, a real SecretRegistry, an EnvSecretSource over a dict the test
builds, and real ToolResult values:
- N1-N8: the forms of a value, the floor, nested and overlapping occurrences, multi-line values, idempotence;
- N9-N10: the same objects come back when nothing matches, with no values and with values;
- N11-N16: mask_result over strings, containers, other types, subclasses and its bounds; bad arguments;
- N17-N19: a failing pass withholds the output; labels; which source names a shared value;
- N20-N21: the registry;
- N22-N25: the environment source decides by name only, and its rule only narrows BF-890's;
- N26-N31: masked_credential_values: each source, no CLI and no access row, rotation, its only caller;
- N32-N37: padded values, a non-ASCII value, an unpadded base64, a config double, the floor argument, and a form
  found only across the join of a result's strings.
Does not prove: any seam (AD-1337 S2, S3), the masking event (S2), or the cost of a pass (the orchestrator's probe).
No test reads the process environment's values: every environment is a dict the test builds.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote, quote_plus

import pytest

from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.security import secret_masking
from probos.security.secret_masking import (
    DEFAULT_FLOOR,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    MASKING_FAILED_TEXT,
    EnvSecretSource,
    MaskOutcome,
    SecretMasker,
    SecretRegistry,
    env_name_is_mask_shaped,
    secret_forms,
)
from probos.tools.protocol import ToolResult

TOKEN = "tok-Q7f2Lx9Pz4Wm8Rk3"
BUILTIN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "PROBOS_DISCORD_TOKEN", "LLM_API_KEY")


@pytest.fixture(autouse=True)
def _no_builtin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The built-in specs read these names; each test sets the ones it needs."""
    for name in BUILTIN_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_cli(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """No test runs gh: the CLI step fails as if gh were not installed, and records the call."""
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: Any) -> None:
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("probos.credential_store.subprocess.run", _run)
    return calls


def _store(directory: Path, entries: dict[str, str] | None = None, **kwargs: Any) -> CredentialStore:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "secrets.json"
    if entries is not None:
        path.write_text(json.dumps(entries), encoding="utf-8")
    return CredentialStore(store_path=path, **kwargs)


def _masker(
    store: CredentialStore,
    *,
    registry: SecretRegistry | None = None,
    environ: dict[str, str] | None = None,
    **kwargs: Any,
) -> SecretMasker:
    return SecretMasker(
        credential_store=store,
        registry=registry if registry is not None else SecretRegistry(),
        env_source=EnvSecretSource(environ if environ is not None else {}),
        **kwargs,
    )


@dataclasses.dataclass(frozen=True)
class _TypedResult(ToolResult):
    evidence: str = dataclasses.field(kw_only=True)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise TypeError("typed evidence required")


# -- N1 to N8: forms ----------------------------------------------------------------------------------------------


def test_raw_and_json_escaped_forms_are_masked(tmp_path: Path) -> None:
    value = 'pa"ss\\word-7Kq2'
    masker = _masker(_store(tmp_path, {"db": value}))
    out = masker.mask_text(f"raw={value} json={json.dumps({'p': value})}")
    assert value not in out.text and json.dumps(value)[1:-1] not in out.text
    assert out.text.count("<secret:db>") == 2
    assert out.names == frozenset({"db"}) and out.failed is False


URL_VALUE = "k>>> j??? m-secret"


@pytest.mark.parametrize(
    "encoded",
    [quote(URL_VALUE, safe=""), quote(URL_VALUE, safe="").lower(), quote_plus(URL_VALUE)],
    ids=["upper-hex", "lower-hex", "plus"],
)
def test_url_encoded_forms_are_masked(tmp_path: Path, encoded: str) -> None:
    assert encoded != URL_VALUE  # premise: the form differs from the raw value
    assert _masker(_store(tmp_path, {"url": URL_VALUE})).mask_text(f"u={encoded}").text == "u=<secret:url>"


B64_VALUE = "k>>>j???m-secret-99"


@pytest.mark.parametrize("encode", [base64.b64encode, base64.urlsafe_b64encode], ids=["standard", "urlsafe"])
@pytest.mark.parametrize("prefix", [b"", b"a", b"ab", b"Bearer ", b"x-access-token:", b"abcd"])
def test_base64_forms_at_every_alignment(tmp_path: Path, encode: Any, prefix: bytes) -> None:
    raw = B64_VALUE.encode("utf-8")
    assert base64.b64encode(raw) != base64.urlsafe_b64encode(raw)  # premise: the two alphabets differ here
    stream = encode(prefix + raw + b"!tail").decode("ascii")
    skip = (-len(prefix)) % 3
    aligned = raw[skip:]
    core = encode(aligned[: len(aligned) - len(aligned) % 3]).decode("ascii")
    assert core in stream  # premise: the aligned core is in the encoded stream
    out = _masker(_store(tmp_path, {"b64": B64_VALUE})).mask_text(f"header {stream} end")
    assert "<secret:b64>" in out.text
    assert core not in out.text


def test_the_floor_is_eight_characters(tmp_path: Path) -> None:
    seven, eight = "Zq7#kP2", "Zq7#kP2w"
    assert len(seven) == DEFAULT_FLOOR - 1 and len(eight) == DEFAULT_FLOOR
    assert secret_forms(seven) == frozenset()
    text = f"a {seven} b {base64.b64encode(seven.encode('utf-8')).decode('ascii')} c"
    assert _masker(_store(tmp_path / "seven", {"short": seven})).mask_text(text).text is text
    assert _masker(_store(tmp_path / "eight", {"exact": eight})).mask_text(f"a {eight} b").text == "a <secret:exact> b"


def test_an_occurrence_inside_another_is_one_placeholder(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"long": "outer-SECRET-value-77", "short": "SECRET-value"}))
    out = masker.mask_text("x outer-SECRET-value-77 y SECRET-value z")
    assert out.text == "x <secret:long> y <secret:short> z"
    assert out.names == frozenset({"long", "short"})


def test_overlapping_occurrences_are_masked_as_one_span(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"left": "1234567890ab", "right": "90abcdefghij"}))
    out = masker.mask_text("[1234567890abcdefghij]")
    assert out.text == "[<secret:left>]"
    assert out.names == frozenset({"left", "right"})


PEM = (
    "-----BEGIN PRIVATE KEY-----\r\n"
    "MIIBVQIBADANBgkqhkiG9w0BAQEFAASC\r\n"
    "AT8wggE7AgEAAkEAq1w2e3r4t5y6u7i8\r\n"
    "-----END PRIVATE KEY-----"
)


def test_a_multi_line_value_is_masked_whole_and_by_line(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"pem": PEM}))
    assert masker.mask_text(f"a {PEM.replace(chr(13) + chr(10), chr(10))} b").text == "a <secret:pem> b"
    assert masker.mask_text("line AT8wggE7AgEAAkEAq1w2e3r4t5y6u7i8 only").text == "line <secret:pem> only"
    fence = "-----BEGIN PRIVATE KEY----- is a header"
    assert masker.mask_text(fence).text is fence


def test_masking_twice_changes_nothing_more(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    once = masker.mask_text(f"t={TOKEN} b={base64.b64encode(TOKEN.encode('utf-8')).decode('ascii')}")
    assert once.text == "t=<secret:github> b=<secret:github>"
    twice = masker.mask_text(once.text)
    assert twice.text is once.text and twice.names == frozenset()


# -- N9, N10: the golden identity ---------------------------------------------------------------------------------


def test_with_no_values_the_same_objects_come_back(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path))
    text = "nothing secret here " * 100
    result = ToolResult(output={"k": ["v", ("w",)]}, error="e", metadata={"m": 1})
    assert masker.mask_text(text).text is text
    masked = masker.mask_result(result)
    assert masked[0] is result and masked.names == frozenset() and masked.failed is False


def test_with_values_and_no_match_the_same_objects_come_back(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("vault:x", "vault-value-0001")
    masker = _masker(_store(tmp_path, {"github": TOKEN}), registry=registry, environ={"HF_TOKEN": "hf-env-value-123"})
    text = "no credential in this line"
    result = ToolResult(output=["a", {"b": ("c",)}], error="plain error")
    assert masker.mask_text(text).text is text
    assert masker.mask_result(result)[0] is result


# -- N11 to N16: mask_result --------------------------------------------------------------------------------------


def test_output_and_error_strings_are_masked_and_metadata_is_not(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    metadata = {"echo": TOKEN}
    result = ToolResult(output=f"out {TOKEN}", error=f"err {TOKEN}", duration_ms=5.0, metadata=metadata)
    masked = masker.mask_result(result)
    assert masked.result.output == "out <secret:github>" and masked.result.error == "err <secret:github>"
    assert masked.result.metadata is metadata and masked.result.duration_ms == 5.0
    assert masked.names == frozenset({"github"}) and masked.failed is False
    assert result.output == f"out {TOKEN}"  # the input is not changed


def test_container_values_are_masked_keys_and_types_kept(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    untouched = ["plain"]
    output = {"a": [f"x{TOKEN}", untouched], "b": (TOKEN, 3), TOKEN: "key stays", "n": None}
    masked = masker.mask_result(ToolResult(output=output)).result.output
    assert masked == {"a": ["x<secret:github>", ["plain"]], "b": ("<secret:github>", 3), TOKEN: "key stays", "n": None}
    assert type(masked["b"]) is tuple and masked["a"][1] is untouched
    assert output["a"][0] == f"x{TOKEN}"


def test_other_output_types_are_left_to_the_render_seam(tmp_path: Path) -> None:
    class Shown:
        def __repr__(self) -> str:
            return TOKEN

    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    for output in (Shown(), TOKEN.encode("utf-8"), OrderedDict(k=TOKEN)):
        result = ToolResult(output=output)
        assert masker.mask_result(result)[0] is result


def test_a_subclass_keeps_its_type_and_fields(tmp_path: Path) -> None:
    masked = _masker(_store(tmp_path, {"github": TOKEN})).mask_result(_TypedResult(output=TOKEN, evidence="ev")).result
    assert type(masked) is _TypedResult and masked.evidence == "ev" and masked.output == "<secret:github>"


def test_the_walk_stops_at_its_depth_and_node_bounds(tmp_path: Path) -> None:
    def nest(depth: int, leaf: str) -> Any:
        value: Any = leaf
        for _ in range(depth):
            value = [value]
        return value

    store = _store(tmp_path, {"github": TOKEN})
    deep = _masker(store, max_depth=3)
    assert deep.mask_result(ToolResult(output=nest(3, TOKEN))).result.output == nest(3, "<secret:github>")
    too_deep = ToolResult(output=nest(4, TOKEN))
    assert deep.mask_result(too_deep)[0] is too_deep
    wide = _masker(store, max_nodes=3).mask_result(ToolResult(output=[TOKEN, TOKEN, TOKEN])).result.output
    assert wide == ["<secret:github>", "<secret:github>", TOKEN]


def test_the_unmeasured_defaults_and_bad_arguments(tmp_path: Path) -> None:
    assert (DEFAULT_FLOOR, DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES) == (8, 32, 10_000)
    store = _store(tmp_path)
    for bad in (
        {"credential_store": MagicMock(), "registry": SecretRegistry(), "env_source": EnvSecretSource({})},
        {"credential_store": store, "registry": MagicMock(), "env_source": EnvSecretSource({})},
        {"credential_store": store, "registry": SecretRegistry(), "env_source": MagicMock()},
    ):
        with pytest.raises(TypeError):
            SecretMasker(**bad)
    for bound in ("floor", "max_depth", "max_nodes"):
        with pytest.raises(ValueError):
            _masker(store, **{bound: 0})
    with pytest.raises(TypeError):
        _masker(store).mask_text(b"bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _masker(store).mask_result({"output": "x"})  # type: ignore[arg-type]


# -- N17 to N19: failure, labels, precedence ----------------------------------------------------------------------


def test_a_failing_pass_withholds_and_logs_only_the_exception_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise(_store: CredentialStore) -> tuple[tuple[str, str], ...]:
        raise RuntimeError(f"boom {TOKEN}")

    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise)
    caplog.set_level(logging.DEBUG)
    assert masker.mask_text(f"t {TOKEN}") == MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
    masked = masker.mask_result(_TypedResult(output=TOKEN, evidence="ev", duration_ms=2.0, metadata={"op": 1}))
    assert type(masked.result) is ToolResult and masked.result.output is None and masked.failed is True
    assert masked.result.error == MASKING_FAILED_TEXT and masked.result.duration_ms == 2.0
    assert masked.result.metadata == {"op": 1}
    assert "RuntimeError" in caplog.text
    assert TOKEN not in caplog.text and "boom" not in caplog.text


def test_a_name_that_is_not_a_plain_label_is_shown_as_unnamed(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("bad name!", TOKEN)
    out = _masker(_store(tmp_path), registry=registry).mask_text(TOKEN)
    assert out.text == "<secret:unnamed>" and out.names == frozenset({"unnamed"})


def test_the_store_names_a_value_the_environment_also_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    assert _masker(_store(tmp_path), environ={"GH_TOKEN": TOKEN}).mask_text(TOKEN).text == "<secret:github>"


# -- N20, N21: the registry ---------------------------------------------------------------------------------------


def test_a_registered_value_is_masked_until_released(tmp_path: Path) -> None:
    registry = SecretRegistry()
    masker = _masker(_store(tmp_path), registry=registry)
    handle = registry.register("vault:site", TOKEN)
    assert masker.mask_text(TOKEN).text == "<secret:vault:site>"
    handle.release()
    handle.release()
    assert masker.mask_text(TOKEN).text == TOKEN
    with registry.register("vault:site", TOKEN):
        assert masker.mask_text(TOKEN).text == "<secret:vault:site>"
    first, second = registry.register("a", TOKEN), registry.register("b", TOKEN)
    first.release()
    assert masker.mask_text(TOKEN).text == "<secret:b>"
    second.release()
    assert registry.values() == ()
    with pytest.raises(TypeError):
        registry.register("n", 123)  # type: ignore[arg-type]


def test_the_registry_is_safe_across_threads() -> None:
    registry = SecretRegistry()

    def churn() -> None:
        for index in range(200):
            registry.register(f"n{index}", f"value-{index:04d}-xyz").release()

    threads = [threading.Thread(target=churn) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert registry.values() == ()


# -- N22 to N25: the environment ----------------------------------------------------------------------------------

MASKED_NAMES = (
    "PROBOS_DISCORD_TOKEN", "HF_TOKEN", "OPENAI_API_KEY", "OPENAI_API_KEY_2", "STRIPE_KEY", "AWS_SECRET_ACCESS_KEY",
    "DB_PASSWORD", "DB_PASS", "DB_PWD", "SENTRY_DSN", "MY_APIKEY", "GPG_PASSPHRASE", "NPM_PAT", "BASIC_AUTH",
    "GOOGLE_CREDENTIALS_JSON", "FILE_ENCRYPTION_KEY",
)
# E2 (2026-11-21): the first four matched BF-890's rule in the orchestrator's shell and are not secrets. The last
# five name a path (F1): the rule decides by name, so a secret that starts with "/" is still masked (N24).
UNMASKED_NAMES = (
    "GIT_CONFIG_KEY_0", "GIT_CONFIG_KEY_1", "GIT_CONFIG_KEY_2", "COPILOT_AGENT_SESSION_ID", "PROBOS_PROFILE",
    "GIT_AUTHOR_EMAIL", "AZURE_AUTHORITY_HOST", "COOKIE_DOMAIN", "KEYBOARD_LAYOUT", "MONKEY_PATCH", "PRIVATE_NOTES",
    "DB_PASSWORD_FILE", "SSH_AUTH_SOCK", "PWD", "GOOGLE_APPLICATION_CREDENTIALS", "TOKEN_DIR",
)


@pytest.mark.parametrize("name", MASKED_NAMES)
def test_credential_names_are_masked(name: str) -> None:
    assert env_name_is_mask_shaped(name)
    assert env_name_refusal(name) == "credential_shaped"  # the rule only narrows BF-890's


@pytest.mark.parametrize("name", UNMASKED_NAMES)
def test_identifier_config_and_path_names_are_not_masked(name: str) -> None:
    assert not env_name_is_mask_shaped(name)
    assert env_name_refusal(name) == "credential_shaped"  # BF-890 still keeps each out of a child's environment


def test_the_environment_source_decides_by_name_and_strips_values(tmp_path: Path) -> None:
    session = "0f8fad5b-d9cb-469f-a165-70867728950e"
    environ = {
        "PROBOS_DISCORD_TOKEN": "discord-env-token-1",
        "HF_TOKEN": "  padded-token-1  ",
        "DEPLOY_TOKEN": "/fake-token+slash/value-01",
        "DB_PASSWORD_FILE": "/run/secrets/db-password",
        "PWD": "/home/user/project",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "COPILOT_AGENT_SESSION_ID": session,
        "PROBOS_PROFILE": "supported",
    }
    assert sorted(EnvSecretSource(environ).values()) == [
        ("env:DEPLOY_TOKEN", "/fake-token+slash/value-01"),
        ("env:HF_TOKEN", "padded-token-1"),
        ("env:PROBOS_DISCORD_TOKEN", "discord-env-token-1"),
    ]
    masker = _masker(_store(tmp_path), environ=environ)
    text = f"credential.helper supported /run/secrets/db-password /home/user/project {session}"
    assert masker.mask_text(text).text is text
    assert masker.mask_text("discord-env-token-1").text == "<secret:env:PROBOS_DISCORD_TOKEN>"
    assert masker.mask_text("key=/fake-token+slash/value-01").text == "key=<secret:env:DEPLOY_TOKEN>"


def test_the_default_source_reads_the_environment_on_each_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = {"AD1337_PROBE_TOKEN": "probe-env-value-42"}
    monkeypatch.setattr(secret_masking, "os", SimpleNamespace(environ=fake))
    masker = SecretMasker(credential_store=_store(tmp_path), registry=SecretRegistry(), env_source=EnvSecretSource())
    assert masker.mask_text("probe-env-value-42").text == "<secret:env:AD1337_PROBE_TOKEN>"
    fake.clear()
    assert masker.mask_text("probe-env-value-42").text == "probe-env-value-42"


# -- N26 to N31: the store's values -------------------------------------------------------------------------------


def test_every_store_source_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "alias-github-token-1")
    config = SimpleNamespace(
        channels=SimpleNamespace(discord=SimpleNamespace(token="discord-config-token-1")),
        auth=SimpleNamespace(crew_scope_token="crew-scope-token-123"),
    )
    store = _store(tmp_path, {"custom": "json-store-value-1"}, config=config)
    assert sorted(masked_credential_values(store)) == [
        ("crew_scope", "crew-scope-token-123"),
        ("custom", "json-store-value-1"),
        ("discord", "discord-config-token-1"),
        ("github", "alias-github-token-1"),
    ]


def test_a_value_only_the_cli_gave_is_kept_after_its_cache_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="cli-only-token-77\n")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _gh)
    store = _store(tmp_path, cache_ttl=0.0)
    assert ("github", "cli-only-token-77") not in masked_credential_values(store)
    assert calls == []
    assert store.get("github", requester="test") == "cli-only-token-77"
    assert ("github", "cli-only-token-77") in masked_credential_values(store)
    assert calls == [["gh", "auth", "token"]]


async def test_reading_the_values_runs_no_command_and_writes_no_access_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, Any]] = []

    class _Log:
        async def log(self, **fields: Any) -> None:
            rows.append(fields)

    def _forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("masked_credential_values ran a command")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _forbidden)
    monkeypatch.setenv("AD1337_GATED_TOKEN", "gated-env-token-9")
    store = _store(tmp_path, {"custom": "json-store-value-1"}, event_log=_Log())
    store.set_tier_enforcement(True)
    store.register(CredentialSpec(name="gated", env_var="AD1337_GATED_TOKEN", min_tier="unrestricted"))
    pairs = masked_credential_values(store)
    await asyncio.sleep(0)
    assert rows == []
    assert ("gated", "gated-env-token-9") in pairs and ("custom", "json-store-value-1") in pairs
    assert store.get("discord", requester="control") is None  # control: a get writes a row
    await asyncio.sleep(0)
    assert len(rows) == 1


def test_a_rotated_value_is_masked_and_the_old_one_is_not(tmp_path: Path) -> None:
    store = _store(tmp_path, {"github": "old-github-token-1"})
    masker = _masker(store)
    assert store.get("github", requester="test") == "old-github-token-1"
    assert masker.mask_text("old-github-token-1").text == "<secret:github>"
    assert store.rotate("github", "new-github-token-2") is True
    assert masker.mask_text("new-github-token-2").text == "<secret:github>"
    assert masker.mask_text("old-github-token-1").text == "old-github-token-1"


def test_a_rotation_the_environment_refuses_keeps_that_value_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "env-github-token-3")
    store = _store(tmp_path)
    assert store.rotate("github", "unused-token-44") is False
    masker = _masker(store)
    assert masker.mask_text("env-github-token-3").text == "<secret:github>"
    assert masker.mask_text("unused-token-44").text == "unused-token-44"


def test_the_secret_masker_is_the_only_reader_of_the_values() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "probos"
    found = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "masked_credential_values" in path.read_text(encoding="utf-8", errors="replace")
    )
    assert found == ["credential_store.py", "security/secret_masking.py"]


# -- N32 to N37: padded, non-ASCII and unpadded values; a config double; the floor argument; the join ------------


def test_padded_store_and_registry_values_are_masked_by_their_core(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("vault:pad", "  padded-vault-value-1  ")
    masker = _masker(_store(tmp_path, {"github": " padded-store-token-1\n"}), registry=registry)
    out = masker.mask_text("a padded-store-token-1 b padded-vault-value-1 c")
    assert out.text == "a <secret:github> b <secret:vault:pad> c"


UNICODE_VALUE = 'p\u00e4ss"w\u00f6rd-\u00dcn\u00ef-9Kq'
UNICODE_FORMS = (
    UNICODE_VALUE,
    json.dumps(UNICODE_VALUE)[1:-1],
    json.dumps(UNICODE_VALUE, ensure_ascii=False)[1:-1],
    quote(UNICODE_VALUE, safe=""),
    base64.b64encode(UNICODE_VALUE.encode("utf-8")).decode("ascii"),
)


@pytest.mark.parametrize("form", UNICODE_FORMS, ids=["raw", "json-ascii", "json-utf8", "url", "base64"])
def test_a_non_ascii_value_is_masked_in_every_form(tmp_path: Path, form: str) -> None:
    assert len(set(UNICODE_FORMS)) == 5  # premise: the five forms are distinct strings
    assert _masker(_store(tmp_path, {"uni": UNICODE_VALUE})).mask_text(f"v={form};").text == "v=<secret:uni>;"


def test_an_unpadded_whole_base64_value_is_masked_whole(tmp_path: Path) -> None:
    raw = B64_VALUE.encode("utf-8")
    assert len(raw) % 3 != 0  # premise: the full encoding is padded, so the unpadded one differs
    unpadded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert _masker(_store(tmp_path, {"b64": B64_VALUE})).mask_text(f"t={unpadded}").text == "t=<secret:b64>"


def test_a_config_double_gives_no_values(tmp_path: Path) -> None:
    assert masked_credential_values(_store(tmp_path, config=MagicMock())) == ()


def test_the_floor_argument_is_used(tmp_path: Path) -> None:
    low = _masker(_store(tmp_path / "low", {"five": "Zq7#k"}), floor=5)
    assert low.mask_text("a Zq7#k b").text == "a <secret:five> b"
    high = _masker(_store(tmp_path / "high", {"twelve": "Zq7#kP2wLm9x"}), floor=13)
    text = "a Zq7#kP2wLm9x b"
    assert high.mask_text(text).text is text


def test_a_form_found_only_across_the_join_leaves_the_result_as_it_is(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"nul": "nul\x00value-123"}))
    result = ToolResult(output=["nul", "value-123"])
    masked = masker.mask_result(result)
    assert masked.result is result and masked.names == frozenset() and masked.failed is False
```

### 7.2 New file `src/probos/security/secret_masking.py` (M1)

```python
"""AD-1337 (#1560): the one owner that masks known credential values in tool output before a model sees them.

``SecretMasker`` replaces every form of every known value with ``<secret:NAME>``. It reads three sources again on
every pass, so a rotated value is masked from the next pass on and a released one no longer is:

1. ``probos.credential_store.masked_credential_values``: what the credential store can name. No CLI command runs
   and no access row is written.
2. ``SecretRegistry``: a value ProbOS hands to a tool for one session, masked until its ``SecretHandle`` is released.
3. ``EnvSecretSource``: the environment's values under a name ``env_name_is_mask_shaped`` accepts. That rule only
   narrows BF-890's (``execution/command_env.py``, unchanged) and decides by name alone: a git config key name, a
   session id or a path is not a secret, and masking one would rewrite ordinary text.

``secret_forms`` gives the forms of one value: raw, JSON-escaped (with and without ASCII escapes), URL-encoded from
its UTF-8 bytes (both hex cases, ``quote_plus``) and base64 of its UTF-8 bytes (standard and URL-safe, padded and
unpadded, and at each of the three byte alignments a value can have inside a longer encoded stream; at most two
bytes at each end of an aligned occurrence stay visible). A value shorter than the floor, and a form shorter than
it, are not masked. Overlapping occurrences are replaced as one span.

Nothing here logs, emits or returns a value. A pass that fails is fail-closed: the caller gets
``MASKING_FAILED_TEXT`` instead of the text or the output, and one ERROR line names the exception type only. The
seams that call this module, and the masking event, are AD-1337 S2 and S3.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple
from urllib.parse import quote, quote_plus

from probos.credential_store import CredentialStore, masked_credential_values
from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

#: Not measured (AD-1337 consult 4bb6d748, Q3): the shortest value, and the shortest form of one, that is masked.
DEFAULT_FLOOR: int = 8
#: Not measured: how deep, and over how many nodes, ``mask_result`` walks a container output. Past either bound a
#: value is left as it is here, and the render seam (AD-1337 S3) masks the text the model is shown.
DEFAULT_MAX_DEPTH: int = 32
DEFAULT_MAX_NODES: int = 10_000

#: What the caller gets instead of the text or the output when a pass fails.
MASKING_FAILED_TEXT: str = "tool output withheld: secret masking failed"
#: The label shown for a source name that is not a plain label.
UNNAMED_LABEL: str = "unnamed"

#: A name whose last ``_`` segment is one of these names a path, not a secret (``DB_PASSWORD_FILE``,
#: ``SSH_AUTH_SOCK``). Decided by name, never by value: a secret can start with ``/``.
MASK_PATH_SEGMENTS: tuple[str, ...] = ("FILE", "PATH", "SOCK", "SOCKET", "DIR", "DIRECTORY")
#: Whole names that hold a path although they match a word below.
MASK_PATH_NAMES: tuple[str, ...] = ("PWD", "GOOGLE_APPLICATION_CREDENTIALS")
#: A name containing one of these words names a secret.
MASK_NAME_WORDS: tuple[str, ...] = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASSPHRASE", "CREDENTIAL", "APIKEY")
#: Short forms that count only as a whole ``_``-separated segment (``AUTH``, but not ``AUTHOR``).
MASK_NAME_SEGMENTS: tuple[str, ...] = ("PAT", "PASS", "PWD", "DSN", "CREDS", "AUTH")
#: ``KEY`` counts as the last segment (``STRIPE_KEY``) or right after a qualifier (``OPENAI_API_KEY_2``), and never
#: elsewhere: ``GIT_CONFIG_KEY_0`` holds a git config key name.
MASK_KEY_SEGMENTS: tuple[str, ...] = ("KEY", "KEYS")
MASK_KEY_QUALIFIERS: tuple[str, ...] = (
    "API", "ACCESS", "PRIVATE", "SIGNING", "ENCRYPTION", "MASTER", "CLIENT", "ACCOUNT", "SERVICE", "LICENSE",
)

_LABEL_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_UPPER_HEX_RE = re.compile(r"%[0-9A-F]{2}")
_PEM_FENCES: tuple[str, ...] = ("-----BEGIN", "-----END")


class MaskOutcome(NamedTuple):
    """``mask_text``'s answer: the text (the same object when nothing matched), the labels masked, and whether the
    pass failed (``text`` is then ``MASKING_FAILED_TEXT``)."""

    text: str
    names: frozenset[str]
    failed: bool


class MaskedResult(NamedTuple):
    """``mask_result``'s answer: the result (the same object when nothing matched), the labels masked, and whether
    the pass failed (``result`` is then a plain ``ToolResult`` whose error is ``MASKING_FAILED_TEXT``)."""

    result: ToolResult
    names: frozenset[str]
    failed: bool


def env_name_is_mask_shaped(name: str) -> bool:
    """Whether the environment variable ``name`` holds a value to mask (a narrowing of BF-890's rule, by name)."""
    upper = name.upper()
    segments = upper.split("_")
    if segments[-1] in MASK_PATH_SEGMENTS or upper in MASK_PATH_NAMES:
        return False
    if any(word in upper for word in MASK_NAME_WORDS):
        return True
    if any(segment in MASK_NAME_SEGMENTS for segment in segments):
        return True
    last = len(segments) - 1
    return any(
        segment in MASK_KEY_SEGMENTS
        and (index == last or (index > 0 and segments[index - 1] in MASK_KEY_QUALIFIERS))
        for index, segment in enumerate(segments)
    )


def secret_label(name: object) -> str:
    """``name`` when it is a plain label (``[A-Za-z0-9_.:-]{1,64}``), else ``UNNAMED_LABEL``."""
    return name if isinstance(name, str) and _LABEL_RE.fullmatch(name) else UNNAMED_LABEL


def secret_forms(value: str, floor: int = DEFAULT_FLOOR) -> frozenset[str]:
    """Every form of ``value`` that is masked; empty when ``value`` is shorter than ``floor``."""
    if len(value) < floor:
        return frozenset()
    wholes = {value, value.replace("\r\n", "\n")}
    forms: set[str] = set(wholes)
    if "\n" in value or "\r" in value:
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped.startswith(_PEM_FENCES):
                forms.add(stripped)
    for whole in wholes:
        forms.add(json.dumps(whole)[1:-1])
        forms.add(json.dumps(whole, ensure_ascii=False)[1:-1])
        for quoted in (quote(whole, safe=""), quote(whole, safe="/"), quote_plus(whole)):
            forms.add(quoted)
            forms.add(_UPPER_HEX_RE.sub(lambda match: match.group(0).lower(), quoted))
        raw = whole.encode("utf-8")
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            full = encode(raw).decode("ascii")
            forms.add(full)
            forms.add(full.rstrip("="))
            for shift in (0, 1, 2):
                aligned = raw[shift:]
                aligned = aligned[: len(aligned) - len(aligned) % 3]
                if aligned:
                    forms.add(encode(aligned).decode("ascii"))
    return frozenset(form for form in forms if len(form) >= floor)


def _present(patterns: tuple[tuple[str, str], ...], text: str) -> tuple[tuple[str, str], ...]:
    return tuple(item for item in patterns if item[0] in text)


def _substitute(text: str, patterns: tuple[tuple[str, str], ...], names: set[str]) -> str:
    """``text`` with every occurrence of every pattern replaced; ``text`` itself when none occurs."""
    present = _present(patterns, text)
    if not present:
        return text
    spans: list[tuple[int, int, str]] = []
    for form, label in present:
        start = text.find(form)
        while start >= 0:
            spans.append((start, start + len(form), label))
            start = text.find(form, start + 1)
    spans.sort(key=lambda span: (span[0], span[0] - span[1], span[2]))
    pieces: list[str] = []
    cursor = index = 0
    while index < len(spans):
        start, end, label = spans[index]
        longest = end - start
        names.add(label)
        index += 1
        while index < len(spans) and spans[index][0] < end:
            other_start, other_end, other_label = spans[index]
            names.add(other_label)
            if other_end - other_start > longest:
                longest, label = other_end - other_start, other_label
            end = max(end, other_end)
            index += 1
        pieces.append(text[cursor:start])
        pieces.append(f"<secret:{label}>")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _log_failure(exc: Exception) -> None:
    # AD-1337: the type name only, and no traceback, so no value or pattern can reach a log.
    logger.error("AD-1337: secret masking failed (%s); the output is withheld", type(exc).__name__)


class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""

    __slots__ = ("_registry", "_key")

    def __init__(self, registry: SecretRegistry, key: int) -> None:
        self._registry = registry
        self._key = key

    def release(self) -> None:
        """Stop masking this registration's value (another registration of the same value stays)."""
        self._registry._release(self._key)

    def __enter__(self) -> SecretHandle:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class SecretRegistry:
    """Values ProbOS hands to a tool for one session, masked while registered. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, tuple[str, str]] = {}
        self._next_key = 0

    def register(self, name: str, value: str) -> SecretHandle:
        """Mask ``value`` under ``name`` until the returned handle is released."""
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("SecretRegistry.register takes a str name and a str value")
        with self._lock:
            key = self._next_key
            self._next_key += 1
            self._entries[key] = (name, value)
        return SecretHandle(self, key)

    def values(self) -> tuple[tuple[str, str], ...]:
        """``(name, value)`` for every live registration."""
        with self._lock:
            return tuple(self._entries.values())

    def _release(self, key: int) -> None:
        with self._lock:
            self._entries.pop(key, None)


class EnvSecretSource:
    """The environment's values under a name ``env_name_is_mask_shaped`` accepts, read on every call.

    ``environ`` is for tests; ``None`` reads ``os.environ`` at each call. The name alone decides: a value is never
    judged by its shape, so a secret starting with ``/`` is kept. Each name is ``env:NAME``.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ

    def values(self) -> tuple[tuple[str, str], ...]:
        """``(env:NAME, value)`` for each masked name with a non-empty stripped value."""
        source = os.environ if self._environ is None else self._environ
        pairs: list[tuple[str, str]] = []
        for name, value in list(source.items()):
            if not env_name_is_mask_shaped(name):
                continue
            stripped = value.strip()
            if stripped:
                pairs.append((f"env:{name}", stripped))
        return tuple(pairs)


class SecretMasker:
    """AD-1337: replaces every form of every known credential value with ``<secret:NAME>``.

    One per runtime (built by AD-1337 S2). ``mask_text`` and ``mask_result`` may run on any thread: the registry is
    locked, the store's dicts are copied before they are read, and the pattern table is replaced whole.
    """

    def __init__(
        self,
        *,
        credential_store: CredentialStore,
        registry: SecretRegistry,
        env_source: EnvSecretSource,
        floor: int = DEFAULT_FLOOR,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> None:
        if not isinstance(credential_store, CredentialStore):
            raise TypeError("SecretMasker needs the runtime's CredentialStore")
        if not isinstance(registry, SecretRegistry):
            raise TypeError("SecretMasker needs a SecretRegistry")
        if not isinstance(env_source, EnvSecretSource):
            raise TypeError("SecretMasker needs an EnvSecretSource")
        if min(floor, max_depth, max_nodes) < 1:
            raise ValueError("floor, max_depth and max_nodes must each be at least 1")
        self._credential_store = credential_store
        self._registry = registry
        self._env_source = env_source
        self._floor = floor
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._table: tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]] | None = None

    def mask_text(self, text: str) -> MaskOutcome:
        """Replace every form of every known value in ``text``. ``TypeError`` for anything but a ``str``."""
        if not isinstance(text, str):
            raise TypeError("mask_text takes a str")
        try:
            names: set[str] = set()
            masked = _substitute(text, self._patterns(), names)
            return MaskOutcome(masked, frozenset(names), False)
        except Exception as exc:  # AD-1337 D7: fail closed
            _log_failure(exc)
            return MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)

    def mask_result(self, result: ToolResult) -> MaskedResult:
        """Mask ``result.output`` (strings in exact dicts, lists and tuples, within the bounds) and a ``str`` error.

        ``metadata`` is never touched; a subclass keeps its type and fields. ``TypeError`` for a non-``ToolResult``.
        """
        if not isinstance(result, ToolResult):
            raise TypeError("mask_result takes a ToolResult")
        try:
            patterns = self._patterns()
            if not patterns:
                return MaskedResult(result, frozenset(), False)
            texts: list[str] = []

            def collect(text: str) -> str:
                texts.append(text)
                return text

            self._map_strings(result.output, collect, 0, [0])
            if isinstance(result.error, str):
                texts.append(result.error)
            present = _present(patterns, "\x00".join(texts))
            if not present:
                return MaskedResult(result, frozenset(), False)
            names: set[str] = set()
            output = self._map_strings(result.output, lambda text: _substitute(text, present, names), 0, [0])
            error = result.error
            if isinstance(error, str):
                error = _substitute(error, present, names)
            # Reachable only when a form that contains NUL matched across the NUL join above and in no single
            # string: nothing changed, so the same object is returned.
            if output is result.output and error is result.error:
                return MaskedResult(result, frozenset(), False)
            return MaskedResult(dataclasses.replace(result, output=output, error=error), frozenset(names), False)
        except Exception as exc:  # AD-1337 D7: fail closed
            _log_failure(exc)
            withheld = ToolResult(error=MASKING_FAILED_TEXT, duration_ms=result.duration_ms, metadata=result.metadata)
            return MaskedResult(withheld, frozenset(), True)

    def _values(self) -> tuple[tuple[str, str], ...]:
        """``(value, label)`` for every value; the first source to name it wins: the store, the registry, the env."""
        chosen: dict[str, str] = {}
        for pairs in (
            masked_credential_values(self._credential_store),
            self._registry.values(),
            self._env_source.values(),
        ):
            for name, value in sorted(pairs):
                stripped = value.strip()
                if stripped:
                    chosen.setdefault(stripped, secret_label(name))
        return tuple(sorted(chosen.items()))

    def _patterns(self) -> tuple[tuple[str, str], ...]:
        """``(form, label)``, longest first; rebuilt only when the values differ from the last pass's."""
        values = self._values()
        cached = self._table
        if cached is not None and cached[0] == values:
            return cached[1]
        forms: dict[str, str] = {}
        for value, label in values:
            for form in secret_forms(value, self._floor):
                forms.setdefault(form, label)
        patterns = tuple(sorted(forms.items(), key=lambda item: (-len(item[0]), item[0])))
        self._table = (values, patterns)
        return patterns

    def _map_strings(self, value: Any, apply: Callable[[str], str], depth: int, visited: list[int]) -> Any:
        """``value`` with ``apply`` run on each string inside exact dicts, lists and tuples, within the bounds.

        Returns ``value`` itself when no string changed. Dict keys are not rewritten, so two keys cannot collide.
        """
        visited[0] += 1
        if visited[0] > self._max_nodes:
            return value
        if isinstance(value, str):
            return apply(value)
        if depth >= self._max_depth:
            return value
        kind = type(value)
        if kind is dict:
            items = [(key, self._map_strings(item, apply, depth + 1, visited)) for key, item in value.items()]
            if all(new is old for (_, new), old in zip(items, value.values())):
                return value
            return dict(items)
        if kind is list or kind is tuple:
            mapped = [self._map_strings(item, apply, depth + 1, visited) for item in value]
            if all(new is old for new, old in zip(mapped, value)):
                return value
            return kind(mapped)
        return value
```

### 7.3 `src/probos/credential_store.py` (M1)

**C1.** SEARCH:
```
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        self._cache_ttl = cache_ttl
```
REPLACE:
```
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        # AD-1337: the last value get() resolved for each name, kept past the cache's TTL so a value only the CLI
        # gives stays maskable (masked_credential_values below). rotate() drops the name's entry.
        self._last_resolved: dict[str, str] = {}
        self._cache_ttl = cache_ttl
```

**C2.** SEARCH:
```
        self._store[name] = value
        # Invalidate cache so next get(...) resolves fresh.
        self._cache.pop(name, None)
```
REPLACE:
```
        self._store[name] = value
        # Invalidate cache so next get(...) resolves fresh.
        self._cache.pop(name, None)
        self._last_resolved.pop(name, None)  # AD-1337: the old value is no longer masked
```

**C3.** SEARCH:
```
        # Cache if found
        if value:
            self._cache[name] = (value, time.monotonic() + self._cache_ttl)
```
REPLACE:
```
        # Cache if found
        if value:
            self._cache[name] = (value, time.monotonic() + self._cache_ttl)
            self._last_resolved[name] = value  # AD-1337: kept past the TTL for the secret masker
```

**C4.** SEARCH:
```
        return results


def crew_scope_token(runtime: Any) -> str:
```
REPLACE:
```
        return results


def masked_credential_values(store: CredentialStore) -> tuple[tuple[str, str], ...]:
    """AD-1337 (#1560): every credential value ``store`` can name, as ``(name, value)`` pairs, for the secret masker.

    Each spec's configured value, its environment variable and aliases, every JSON-store entry, the last value
    ``get`` resolved for each name, and the crew-scope token. No CLI command runs, no access row is written and no
    department or tier gate applies, because nothing here is handed to a requester:
    ``probos.security.secret_masking.SecretMasker`` turns the values into patterns and never returns them. It is
    this function's only caller in ``src`` (pinned by ``tests/test_ad1337_secret_masking.py``). A module function,
    not a method: ``CredentialStore`` is at the 15-method SRP review trigger. Safe from a worker thread: each dict
    is copied before it is read, and ``_load_store`` is idempotent, so a concurrent first call at worst repeats the
    same writes.
    """
    pairs: list[tuple[str, str]] = []
    for spec in list(store._specs.values()):
        if spec.config_key and store._config:
            configured = store._resolve_config_key(spec.config_key)
            if configured:
                pairs.append((spec.name, configured))
        for env_name in (spec.env_var, *spec.env_var_aliases):
            if env_name:
                env_value = os.environ.get(env_name, "").strip()
                if env_value:
                    pairs.append((spec.name, env_value))
    store._load_store()
    pairs.extend((name, value) for name, value in dict(store._store).items() if value.strip())
    pairs.extend(dict(store._last_resolved).items())
    crew_scope = store.crew_scope.token(store._config)
    if isinstance(crew_scope, str) and crew_scope.strip():
        pairs.append(("crew_scope", crew_scope.strip()))
    return tuple(pairs)


def crew_scope_token(runtime: Any) -> str:
```

### 7.4 `PROGRESS.md` (M2)

**TR1.** SEARCH (the whole line `:1`; it occurs once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1337 S1 (2026-11-21), #1560 -- the secret masker: one owner replaces every known credential value in text or a tool result with `<secret:NAME>`; no seam calls it yet.** New `probos/security/secret_masking.py`: `SecretMasker.mask_text` and `.mask_result`, `SecretRegistry` (values masked until their handle is released) and `EnvSecretSource`. The environment rule narrows BF-890's and decides by name alone: `*_TOKEN` is masked (also a value starting with `/`); `GIT_CONFIG_KEY_*`, `COPILOT_AGENT_SESSION_ID`, `PROBOS_PROFILE`, `PWD` and names ending in `_FILE`, `_PATH`, `_SOCK` or `_DIR` are not. `credential_store.masked_credential_values(store)` reads what the store can name with no CLI run and no access row; `get` keeps the last value it resolved and `rotate` drops it. Measured by `tests/test_ad1337_secret_masking.py` (84 cases): raw, JSON, URL and base64 forms at every byte alignment are masked, for a non-ASCII value too, and an unpadded whole base64; a padded stored or registered value is masked by its core; a 7-character value is not masked and an 8-character one is, and the floor argument moves that line; overlapping values become one placeholder; with no values, or no match, the same text and result objects come back; a rotated value is masked on the next pass and the old one is not; a failing pass withholds the output and logs only the exception type. Not measured: the default floor (8) and the walk bounds (32, 10,000). The seams are AD-1337 S2 and S3, in the same PR. Open items ad-1337 R1 to R3 of #1820. Contract `prompts/ad-1337-s1-secret-masker.md`.
```

### 7.5 `DECISIONS.md` (M2)

**TR2.** SEARCH: the whole line `:1661`, which occurs once and is ASCII:
```
### AD-1360 -- a direct episode's AD-492 correlation id is checked once, when it is stored, against an in-process registry of issued cycle ids; the rule that reads the record ships off (S1, 2026-11-20, #1828)
```
REPLACE:
```markdown
### AD-1337 -- known credential values are masked in tool output before a model or an offloaded copy sees them (2026-11-21, #1560)

- *Owner (S1).* `probos/security/secret_masking.py`: `SecretMasker.mask_text` and `.mask_result` replace every form of every known value with `<secret:NAME>`. Three sources are read on every pass and every value is stripped: `credential_store.masked_credential_values(store)` (spec config values, their env vars and aliases, the JSON store, the last value `get` resolved, the crew-scope token), `SecretRegistry` (values handed to a tool for one session) and `EnvSecretSource`. The first source to name a value labels it.
- *Forms.* Raw; JSON-escaped with and without ASCII escapes; URL-encoded from the UTF-8 bytes in both hex cases and `quote_plus`; base64 of the UTF-8 bytes, standard and URL-safe, padded and unpadded, at the three byte alignments (the GitHub Actions runner's encoders), so at most two bytes at each end of an aligned occurrence stay visible; each line of a multi-line value except PEM fences. The floor (8 characters for a value and for a form) is unmeasured. Overlapping occurrences become one span.
- *Environment names.* A narrowing of BF-890's rule (every name it accepts, BF-890 also refuses; BF-890's code is unchanged), decided by name alone. On 2026-11-21 BF-890's rule matched 5 of 89 names in the orchestrator's shell with `PROBOS_DISCORD_TOKEN` set, and 4 were not secrets (three `GIT_CONFIG_KEY_*` and a session id); the new rule matches only the token. `KEY` counts only as the last segment or after a qualifier; `SESSION`, `COOKIE`, `PRIVATE` and `AUTH` inside a longer word do not count. Names ending in `_FILE`, `_PATH`, `_SOCK`, `_SOCKET`, `_DIR` or `_DIRECTORY`, and the names `PWD` and `GOOGLE_APPLICATION_CREDENTIALS`, are paths. A value is never judged by its shape: an absolute-path test dropped a secret starting with `/` (about one base64 key in 64) and depends on the platform and the Python version.
- *Store read.* A module function, not a method: `CredentialStore` has 15 direct methods, and the architecture check gates above 15. No CLI, no access row, no gate, because nothing is handed to a requester; its only caller is pinned. A crew-scope token that is not a `str` (a test double's config) is skipped. `rotate` drops the old value at once; an env value that overrides the store stays masked, because it is still the effective value.
- *Fail closed.* A failing pass withholds the output (`tool output withheld: secret masking failed`) and logs the exception type only. No off switch: with no values, the output is the same object.
- *Measured.* `tests/test_ad1337_secret_masking.py` (84 cases), including a non-ASCII value in five forms, padded and unpadded values, and the floor argument. On the oracle, `mask_text` over 1 MiB with 50 values and no hit took 22 ms, and `mask_result` over 10,000 short strings with 50 values took 12.7 ms. A 30,000-case merge fuzz left no form behind and kept every uncovered character. Not measured: the walk bounds (32, 10,000).
- *Not the issue's decision 2 as written.* `ToolExecutor.invoke` alone misses `DispatchToolExecutor`'s non-protected path and exception text (consult 4bb6d748). S2 adds the producer seam, and S3 adds the render seam, the routes and the census, each as bullets here. BF-896's session tools run inside the Copilot SDK and are not masked; AD-1335 must pass its shell output through `mask_text`.
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
- *Residual.* #1820 items ad-1337 R1 to R3. *Reversal.* Revert the AD-1337 commits.

### AD-1360 -- a direct episode's AD-492 correlation id is checked once, when it is stored, against an in-process registry of issued cycle ids; the rule that reads the record ships off (S1, 2026-11-20, #1828)
```

### 7.6 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit the regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. Add no `roadmap.md` row (this is an AD). `docs/research/openhands-absorption.md:33` becomes "built by AD-1337" in S3, not here, because S1 is inert.

## 8. Issue texts (post after the batch merges)

**8.1 #1560, decision 2 amended:**
> **Decision 2, amended (AD-1337; consult 4bb6d748; PR #...).** Tool output is masked by one owner, `SecretMasker` (`probos/security/secret_masking.py`), at two seams:
> - the producer seam in `ToolExecutor._invoke_once`, right after the registry returns, which covers the direct, broker and `DispatchToolExecutor` paths and every post-hook;
> - the render seam in `AgenticLoop`, which covers the AD-1240 offloaded copy, exception text and custom reprs.
>
> `ToolExecutor.invoke` alone was not enough: `DispatchToolExecutor.invoke` skips it on its non-protected path, and an exception's text never passes a `ToolResult`. `reply_pipeline`'s direct browser call is masked before its episode is written, and a census test fails on any new route that skips both seams. `run_python` and `run_command` are registry tools, so both seams cover them. BF-896's session tools run inside the Copilot SDK and are confined by its permission policy. AD-1337 does not mask them; AD-1335 must pass its shell output through `mask_text` before handing it to the SDK.

**8.2 #1557 (AD-1335), an added acceptance line:**
> - [ ] Shell output the build session receives passes through `SecretMasker.mask_text` (`probos/security/secret_masking.py`, AD-1337) before it reaches the Copilot SDK. A test plants a stored credential value in a command's output and asserts the SDK receives `<secret:NAME>`.

**8.3 New items on #1820 (no new issue):**
- **ad-1337 R1** (Medium).
  - *Reach:* a per-tier LLM key set only in the YAML config and echoed by a tool, for example `run_command` reading the config file (BF-890 notes it is not a file boundary).
  - *Evidence:* `config.py:346-537`; `provider_setup.configured_api_keys` (`:331-334`) is a ready reader.
  - *Gap:* the key is masked only when it is also in the environment or the store.
- **ad-1337 R2** (Low).
  - *Reach:* a secret held only in the environment under a name that neither BF-890 nor the mask rule names:
    - `*_CONNECTION_STRING` (`AZURE_STORAGE_CONNECTION_STRING`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `SERVICEBUS_CONNECTION_STRING`);
    - `*_WEBHOOK_URL`;
    - `*_HEADERS` (`OTEL_EXPORTER_OTLP_HEADERS`);
    - `*_URL` or `*_URI` with credentials in the user-information part (`DATABASE_URL`, `REDIS_URL`, `MONGODB_URI`);
    - `GIT_CONFIG_VALUE_n` (an `http.extraheader`).
  - *Evidence:* the orchestrator's 135-name table (2026-11-21): 79 names hold a secret and the rule masks 70; BF-890 refuses none of these 9, so an operator may declare each for a child.
  - *Gap:* a value under such a name is masked only when it is also in the store or the registry. The names the mask rule narrowed away (`SESSION`, `COOKIE`, `PRIVATE`, `KEY` in a middle position) are named here too.
  - *Pointer:* widening belongs with BF-890's list (the child-environment policy), so both stay one policy and the narrowing invariant holds.
- **ad-1337 R3** (Low).
  - *Reach:* a value under nested or other encodings (base64 of base64, gzip, hex), or split across output chunks.
  - *Evidence:* consult Q3; hackerdna's double-base64 leak.
  - *Gap:* not masked; entropy detection is Do Not Build.

## 9. What this does NOT change

- `command_env.py` (BF-890's rule and code), `PIIRedactor`, `provider_setup.redact`.
- `get`'s return value, access rows, events and gates; `rotate`'s return values, writes and events; `list_credentials`; `available`; `crew_scope_token`.
- Any executor, loop, route, event type or config field. No seam is wired (S2, S3).
- `finalize.py`'s late private writes to `_store_path` and `_emit_event` (`:4693-4696`).

## 10. Mutation rows (one campaign on the M1 candidate; restore between rows)

| Row | Mutant | Killed by |
|---|---|---|
| M1 | `len(value) < floor` -> `<=` | N4 |
| M2 | delete the value-floor line in `secret_forms` | N4 (the 7-character value's base64) |
| M3 | shifts `(0, 1, 2)` -> `(0, 2)` | N3 `ab` [2] |
| M3b | shifts -> `(0, 1)` | N3 `a`, `Bearer `, `abcd` |
| M4 | encoders -> `(base64.b64encode,)` | N3 urlsafe |
| M5 | drop the lower-hex `forms.add` | N2 lower-hex |
| M5b | drop `quote_plus(whole)` | N2 plus |
| M6 | inner merge condition -> `False` | N6 |
| M11 | `masked_credential_values` calls `store.get(spec.name)` per spec | N28 |
| M12 | drop C2's pop | N29 |
| M12b | drop C3's added line | N27 |
| M13a | first early return in `mask_result` (`if not patterns:`) returns `MaskedResult(dataclasses.replace(result), frozenset(), False)` | N9 |
| M13b | final guard `if output is result.output and error is result.error:` -> `if False:` | N37 |
| M15 | `env_name_is_mask_shaped` returns `env_name_refusal(name) == "credential_shaped"` | N23 [16] |
| M16 | delete the path-name check (`if segments[-1] in MASK_PATH_SEGMENTS ...`) | N23 (`DB_PASSWORD_FILE`, `SSH_AUTH_SOCK`, `PWD`, `GOOGLE_APPLICATION_CREDENTIALS`, `TOKEN_DIR`), N24 |
| M16b | `EnvSecretSource.values` also drops a value when `os.path.isabs(stripped)` | N24 (`DEPLOY_TOKEN`) |
| M16c | path check on any segment: `any(segment in MASK_PATH_SEGMENTS for segment in segments)` | N22 `FILE_ENCRYPTION_KEY` |
| M16d | `PWD` excluded as a segment: `"PWD" in segments` | N22 `DB_PWD` |
| M17 | the `KEY` clause -> `segment in MASK_KEY_SEGMENTS` | N23 `GIT_CONFIG_KEY_*` |
| M20 | drop the crew-scope append | N26 |
| M21 | `SecretHandle.release` body -> `pass` | N20 |
| M23 | `mask_text`'s `except` returns `MaskOutcome(text, frozenset(), False)` | N17 |
| M24 | `replace(...)` also passes `metadata=dict(result.metadata)` | N11 |
| M25 | `visited[0] > self._max_nodes` -> `False` | N15 |
| M26 | `depth >= self._max_depth` -> `False` | N15 |
| M27 | `kind is dict` -> `isinstance(value, dict)` | N13 (`OrderedDict`) |
| M28 | `_log_failure` adds `exc_info=True` | N17 (`boom`) |
| M29 | `_values` reads the environment first | N19 |
| M30 | `_values`: `stripped = value.strip()` -> `stripped = value` | N32 (the registry value) |
| M31 | drop `forms.add(json.dumps(whole)[1:-1])` | N33 json-ascii |
| M32 | drop `forms.add(json.dumps(whole, ensure_ascii=False)[1:-1])` | N33 json-utf8 |
| M33 | drop `forms.add(full.rstrip("="))` | N34 |
| M34 | `if isinstance(crew_scope, str) and crew_scope.strip():` -> `if crew_scope.strip():` | N35 |
| M35 | `_patterns`: `secret_forms(value, self._floor)` -> `secret_forms(value)` | N36 |

**Equivalent mutants (expected; not gaps):**
- The `if not present: return ...` line in `mask_result` is one half of a deliberate redundancy. The final guard (M13b) also returns the same object when nothing changed, so no one-line mutant of that early return can be killed. Do not remove either half: the early return skips the second walk, and the guard covers the NUL-join case.
- X19: `pairs.append(("crew_scope", crew_scope))` without `.strip()`. `_values()` strips every value, so the strip in `masked_credential_values` is redundant. It is kept, because the function's contract is stripped values for any future reader.

## 11. Verified Against Codebase (2026-11-21, `5d8a5eb4`)

```
rg -n "self\._specs: dict|self\._cache_ttl = cache_ttl|Invalidate cache so next get|# Cache if found|return results" src/probos/credential_store.py
  84, 86, 196, 338, 425 (each once)
rg -n "^def crew_scope_token|^def crew_scope_locked|self\.crew_scope = CrewScopeKeyring" src/probos/credential_store.py   428, 442, 99
rg -n "def token|def configured_crew_scope_token" src/probos/security/crew_scope.py   338, 99
rg -n "CREDENTIAL_NAME_WORDS|CREDENTIAL_NAME_SEGMENTS|def _is_credential_shaped|def env_name_refusal" src/probos/execution/command_env.py   51, 57, 85, 94
rg -n "^class ToolResult|@dataclass\(frozen=True\)" src/probos/tools/protocol.py   81, 80
rg -n "SRP_MAX_DIRECT_METHODS|GATING_CATEGORIES" scripts/check_architecture_principles.py   188, 160
rg -n "CredentialStore\(" src   runtime.py:740 (only)
rg -n "credential_store\._store_path|set_tier_enforcement\(True\)" src/probos/startup/finalize.py   4693, 4715
rg -n "def _key_forms|def redact\(|def redact_keys|def configured_api_keys" src/probos/provider_setup.py   281, 302, 324, 331
rg -n "llm_api_key_(fast|verifier)" src/probos/config.py   346, 537
rg -n "^# ProbOS Progress\r?$" PROGRESS.md   1 (count 1)
rg -n "^### AD-1360 -- a direct episode's" DECISIONS.md   1661 (count 1; no byte above 127 on the line)
git ls-files --eol src/probos/credential_store.py PROGRESS.md DECISIONS.md   all i/lf w/crlf
rg -n "asyncio_mode|^addopts" pyproject.toml   181, 196
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   CEILING AD-1361 (prompts); git AD-1359; issues AD-1360
```

## Absence Verified (2026-11-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No name S1 adds exists | `rg -n "secret_mask\|SecretMask\|SecretRegistry\|EnvSecretSource\|MaskOutcome\|_last_resolved\|masked_values" src tests` | none | yes |
| No tool-output path masks known values | `rg -n "def (redact\|mask\|scrub)\w*\(" src/probos` | `provider_setup.py:302,324` (operator setup and doctor text; callers `doctor/runner.py:109`, `doctor/checks/*`, `__main__.py`); `pii_redaction.py:31-66` (patterns) | yes for tool output; "nothing else masks" was wrong for operator text |
| No AD-1337 prompt or tracker entry exists | Glob `prompts/ad-1337*`; `rg -l AD-1337 --glob "*.{md,json,yaml}"` | none; only `docs/research/openhands-absorption.md` | yes |
| No test reads `credential_store.py`'s source | `rg -n "credential_store\.py\|getsource\(.*CredentialStore" tests` | census fixtures only (`ad1346_*`, `bf892`, `ad1195`), counting the subprocess, file write and event pair that S1 leaves unchanged | yes |
| `CredentialStore` has 15 direct methods | read `credential_store.py:66-425` | `__init__` .. `list_credentials`: 15 | yes |
| `security` is not a mapped layer | read `tests/test_layer_boundaries.py:16-27` | not in `LAYER_MAP` | yes |
| `ToolResult` subclasses have no `init=False` field | `rg -n "init=False\|__post_init__"` over the subclass files | two `__post_init__` that type-check their own fields; no `init=False` | yes |
| The module judges no value as a path | `rg -n "os\.path" src/probos/security/secret_masking.py` (on the M1 candidate; section 12) | none expected | checked by O8 |

## 12. Deterministic checks

- **Focused gate, `-n 0`:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on these files:
  - `tests/test_ad1337_secret_masking.py`
  - `tests/test_credential_store.py`, `tests/test_ad456_security_infrastructure.py`, `tests/test_ad456c_per_tier_credentials.py`, `tests/test_quality_hardening.py`
  - `tests/test_bf908_crew_scope_token.py`, `tests/test_bf908_floor_and_children.py`, `tests/test_bf890_command_env.py`, `tests/test_bf892_spawn_env_guard.py`
  - `tests/test_ad1195_durable_producers.py`, `tests/test_ad1195_eventlog_pair_freeze.py`
  - `tests/test_ad1346_admission_effect_census.py`, `tests/test_ad1346_admission_file_write_census.py`, `tests/test_ad1346_admission_egress_census.py`
  - `tests/test_layer_boundaries.py`, `tests/test_ad1270b_architecture_fitness.py`, `tests/test_ad1184_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` exits 0.
- `rg -n "masked_credential_values" src` finds only `credential_store.py` and `security/secret_masking.py`.
- `rg -n "logger\." src/probos/security/secret_masking.py` finds one call, in `_log_failure`.
- `rg -n "os\.path" src/probos/security/secret_masking.py` finds nothing.
- `git diff 5d8a5eb4 -- src/probos/execution/command_env.py src/probos/security/pii_redaction.py src/probos/provider_setup.py` is empty.
- The two new files are ASCII only.
- Broad gate, once for batch 1 after S3: `scripts/run_test_gate.py --label ad-1337-1560 --receipt logs/gates/ad-1337-1560.receipt.json`.

## 13. Prior art and blind spots

**Internal.**
- BF-890 (`command_env.py`) judges names, not values. Narrowed here, not changed.
- `PIIRedactor.redact_tokens` matches patterns. It stays as a second layer.
- `provider_setup.redact` (`:281-334`) applies the same idea to one provider key in operator text. Its `"Bearer " + key` base64 form is covered by the alignment forms, which it lacks. Merging the two was considered and deferred: its `<redacted>` contract and its docstring proof belong to the doctor's output.
- `docs/research/openhands-absorption.md:20,33`.
- Reference projects, checked 2026-11-21: OpenHands was last reviewed 2026-10-15 with a 90-day interval, so it is not overdue. No other row is relevant, and no row needs an update.

**External.**
- actions/runner `ValueEncoders` (Shift1/Shift2): **adopted** for the alignment forms.
- OpenHands' `SecretSource` registry: **adapted** as `SecretRegistry`.
- CodeQL's unmasked-secret query (a derived secret is masked only if it is registered) supports the explicit registry.
- GitHub's hardening guide (redaction is not guaranteed under transformation) and hackerdna's double-base64 leak: recorded as R3.
- The name-rule redactors in the env-name search match KEY, TOKEN, SECRET and PASSWORD as substrings or suffixes, special-case `KEYBOARD_LAYOUT`, and some treat `DATABASE_URL` as sensitive. **Adapted:** the suffix rule for `KEY`. **Deferred** as R2: their over-matching with allowlists, because E2 measured the cost here (git config names rewritten).

**Blind spots named.**
- A stored value that is a common word of at least 8 characters rewrites that word. Accepted, and recorded as a risk.
- A path held under a secret-shaped name whose last segment is not a path word is masked. Cosmetic over-masking; accepted (F1).
- Dict keys are not masked by the producer seam; the render seam covers the rendered text.
- A `bytes`, dataclass or custom-repr output is left to S3.
- `<secret:NAME>` copied into a file by `write_file`: a consult risk, for a follow-up.
- A pathological value (one repeated character) makes span finding grow with its occurrences.

## 14. Diff Reviewer: properties to verify

1. When nothing matches, with no values or with values, `mask_text` returns the same `str` object and `mask_result` the same `ToolResult` object.
2. No value, form or position reaches a log line, an exception message, `names`, or any return other than the masked text. The one log line carries the exception type only, with no traceback.
3. Every occurrence of every form of a value at or above the floor is replaced, for ASCII and non-ASCII values alike (UTF-8 bytes for the URL and base64 forms, both JSON escapings, padded and unpadded base64). Overlapping occurrences become one placeholder. No form shorter than the floor is masked.
4. `masked_credential_values` runs no subprocess, writes no access row, does not call `get`, applies no gate, returns only `str` values, and has exactly one caller in `src`.
5. `get` records `_last_resolved` only on success; `rotate` pops it wherever it writes `_store`; no other observable behaviour of `get`, `rotate`, `available` or `list_credentials` changes.
6. Every name `env_name_is_mask_shaped` accepts, BF-890 also refuses. The rule decides by name alone, never by value, so a secret starting with `/` is masked. `command_env.py` is unchanged.
7. Any exception inside a pass gives `MASKING_FAILED_TEXT` and `failed=True`; only a wrong input type raises.
8. `mask_result` never changes its input. `metadata` keeps its identity, and a subclass keeps its type and extra fields. Only exact `dict` values, `list` and `tuple` are walked, within both bounds.
9. The registry is locked, the store's dicts are copied before they are read, and the pattern table is replaced whole; a changed value set rebuilds it on the same pass.
10. `CredentialStore` still has 15 direct methods. `secret_masking.py` imports only the standard library, `probos.credential_store` and `probos.tools.protocol`, and uses `os` only for `os.environ`.

## 15. Acceptance

- [ ] Section 5's prediction holds: a collection error on the base, then 84 passed after M1; the focused gate is green.
- [ ] Mutation rows M1 to M35 (with M3b, M5b, M12b, M13a, M13b and M16b to M16d) are killed by the named cases. The two equivalent mutants in section 10 are expected.
- [ ] Section 12's `rg` and diff checks hold, and `check_architecture_principles.py --check` passes.
- [ ] TR1 and TR2 are applied; the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-21, scratch trees detached at `5d8a5eb4`, with this contract's pairs applied; the draft was proved first, then rev1, then this rev2)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed). Each test run went through `run_pytest_homeguard.ps1` and each probe through `run_probe_homeguard.ps1` (a redirected, empty home). Results:

| O | Result |
|---|---|
| O1 | All eight operations (the two new files, C1 to C4, TR1, TR2) are found by `contract_tools.py list`; every SEARCH occurs exactly once on `5d8a5eb4`, and both new paths are absent. Blobs after the pairs: tests `99666c78`, module `5b6de47a`, `credential_store.py` `6d800a8e`, PROGRESS `16d4d2a1`, DECISIONS `e06ed434`. |
| O2 | The new test file alone on the base: **a collection error**, `ImportError: cannot import name 'masked_credential_values' from 'probos.credential_store'`. |
| O3 | After M1's pairs: **84 passed** in 2.13 s (the draft gave 67, rev1 74; each prediction held). |
| O4 | A real store with a config value, an env value, a JSON entry, a CLI-filled `_last_resolved` entry and a crew token; an event-log stub inside a running loop; `subprocess.run` patched to raise (positive control: a CLI step reaches the patch): five pairs, no command, zero rows. The control `get("discord")` wrote one row. |
| O5 | `get`, `rotate`, two passes: the new value is masked, the old value comes back as the same text, a no-hit text is the same object. |
| O6 | Cost on the final candidate with the host quiet (min of 7 runs, ms). `mask_text` over 1 MiB, no hit: 0 values 0.00, 3 values 1.00, 10 values 3.30, 50 values 21.94; 50 values and 100 hits in 1 MiB: 22.29; the per-pass overhead on a short text is 0.025 at 50 values. `mask_result` over a list of 10,000 short strings: 2.05, 3.27 and 12.52 with no hit at 3, 10 and 50 values; 9.41 with 10 hits at 50 values. Recorded for S2's decision on `asyncio.to_thread`. |
| O7 | Names only: the orchestrator's shell holds 91 names; BF-890's rule matches 4 (`COPILOT_AGENT_SESSION_ID`, `GIT_CONFIG_KEY_0..2`) and the new rule none of them (`PROBOS_DISCORD_TOKEN` is not set in this shell; `env_name_is_mask_shaped("PROBOS_DISCORD_TOKEN")` is True). The subset property over every name of one to three segments from a 52-word vocabulary: 160,434 names, 103,241 accepted by the new rule, and every one refused by BF-890 (`credential_shaped` for a plain name, `unknown_shape` for one that is not a plain variable name, such as `0_TOKEN`). A table of 135 well-known names (79 hold a secret): the rule masks 70 of the 79; the 9 it does not mask are `AZURE_STORAGE_CONNECTION_STRING`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `SERVICEBUS_CONNECTION_STRING`, `DATABASE_URL`, `REDIS_URL`, `MONGODB_URI`, `SLACK_WEBHOOK_URL`, `OTEL_EXPORTER_OTLP_HEADERS` and `GIT_CONFIG_VALUE_0`, and BF-890 refuses none of them either (R2). Of the 56 names that hold no secret it masks 3: `AWS_ACCESS_KEY_ID`, `TOKENIZERS_PARALLELISM`, `HF_HUB_DISABLE_IMPLICIT_TOKEN` (the last two hold values under the floor). |
| O7b | F1. `EnvSecretSource` over `AWS_SECRET_ACCESS_KEY="/wJalr..."` (a base64-alphabet value that starts with `/`), `DB_PWD` and `WIN_TOKEN="C:\\Users\\x\\token"` keeps all three; the first draft's absolute-path rule had dropped the first and the last. `PWD`, `SSH_AUTH_SOCK`, `GOOGLE_APPLICATION_CREDENTIALS` and `DB_PASSWORD_FILE` are dropped by name (N23, N24). |
| O8 | **The focused gate** (section 12's 17 files, on the candidate with the trackers and the regenerated ledger): **574 passed, 2 skipped** (the two POSIX-only variants) under the default embeddings (203.78 s) and **574 passed, 2 skipped** under `PROBOS_EMBEDDINGS=local` (203.31 s), four workers each, the two runs side by side. `check_architecture_principles.py --check` passed (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`). `gen_ad_ledger.py` then `--check` reported "AD/BF ledger is current"; the generator changes `open-ads-report.md` and `ad-ledger-snapshot.json`. The redirected home kept two empty directories (`AppData`, `AppData\Roaming`): the same two appear when the same files run on the base tree without S1. |
| O9 | **The mutation campaign** (`mutants_gen.py` over `rows_ad1337s1r2.py`, each row one changed line of the candidate, over the unmutated baseline of 84 passing cases): **killed 54, survived 0, invalid 0**, and one row that named a wrong killer (X7, the same mutant as M31, which N33 `json-ascii` kills: my row file named N1, which holds an ASCII value). Every section 10 row M1 to M35 (with M3b, M5b, M12b, M13a, M13b and M16b to M16d) was killed by its named cases, and 20 extra rows of mine (X1, X2, X4 to X6, X9, X11 to X16, X20, X22 to X24, X27 to X29, X31) were killed. The two equivalent mutants of section 10 (the `if not present` return and X19) were run as rows E1 and E2 and survived, as expected. The first draft's campaign (67 cases, 48 rows) killed 41 and left 7 alive: six of those rows were real gaps (X3, X7, X8, X10, X25, X35) and became N32 to N36, and the seventh is X19. N37 pins the final guard that the draft's row M13 could not kill. |
| O10 | **A merge fuzz** over `mask_text` (30,000 random cases with overlapping values and several labels; 27,079 with an occurrence, 223 merged into fewer placeholders, 11,482 with more than one label): (P1) no form remains, (P2) the text left after deleting the placeholders equals the original with every covered character deleted, (P3) the number of placeholders lies between the number of covered runs and the number of occurrences, (P4) `names` equals the occurrences' labels, (P5) masking again changes nothing. All hold. Positive controls: the same fuzz fails on two mutants of `_substitute` (no merge; a merge that does not extend the end). |
| O11 | **The six new behaviours on the real code and on one-line mutants** (`probe_b11s1_rev2.py`): a `MagicMock` config gives `()` and the mutant gives a `MagicMock` pair; the NUL-join case returns the same object and the guard-less mutant returns an equal copy; padded store and registry values are masked by their core; a non-ASCII value holding a quote gives five distinct forms, all masked, and each JSON mutant leaks exactly its own form; an unpadded urlsafe base64 is masked whole and the mutant leaves `OQ` visible; `floor=5` masks 5 characters, `floor=13` leaves 12, and the mutant ignores the floor. |
| O12 | **Re-checked on the build branch before the Builder started** (2026-11-21, `feat/ad1337-secret-masking-20261121` at `5d8a5eb4`): `contract_tools.py checkpoints` on the build branch tree at `5d8a5eb4` (clean, before this contract was committed) found all eight operations, each SEARCH exactly once, exit 0 and nothing on stderr; its table is byte-identical to the oracle's (the same SHA-256), so the blobs after operation 6 are the oracle's (tests `99666c78`, module `5b6de47a`, `credential_store.py` `6d800a8e`). The Builder's output is checked against that table (`check_blobs_table.py`) after each milestone. |

**What the orchestrator changed in the Architect's draft:** nothing in the pairs, the tests or the module. This section replaces the placeholder section, and the `Sources` lines of the draft's answer are not kept.

**What these checks do not show.**
- Any seam, the event, or the vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`, and until S2 and S3 land, nothing calls the masker.
- The cost of a pass over a container of more than 10,000 nodes, or the walk bounds (32, 10,000) and the floor (8): none of the three was measured.
- A live boot: S1 reads neither the vessel's `.env`, its traces nor its store.
