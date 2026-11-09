# BF-945 (#1720): The red team's http_fetch verifier applies the fetch agent's URL floor: it requests nothing the floor refuses and sends its request to the address the floor approved

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was not logged in), 2026-11-08
**Status:** ready to build on `origin/main` `98d0d99b` (reading tree `D:\ProbOS-worktrees\bf959-base`). **Oracle:** none run (a read-only consult): a script applied the pairs in memory to the LF blobs at `98d0d99b`, each SEARCH once, and parsed the results (section 11). Counts are by reading; the mutants are unrun.
**Orchestrator oracle and amendments (2026-11-08):** the build tree is `origin/main` `6ee2bfa0` (BF-959's merge, on `98d0d99b`): `PROGRESS.md`, `DECISIONS.md` and the two ledger files differ from `98d0d99b` by BF-959's text, and the three base blobs above are unchanged (the header check (2) above therefore applies to `src/probos/agents` and the one test file only; M3's anchors occur once on `6ee2bfa0`). Every block (14 pairs and the new test file) was applied by tool on `98d0d99b`, each SEARCH matching exactly once, after two amendments to N1-1: the `credentials` row builds its URL with `_AT` (a tool's output redacts a URL with embedded credentials, so a Builder could not copy the original line), and the Architect's pair for the log assertion (the `file-scheme` rows log no host: `host = urlparse(url).hostname or "-"`). G1 at M1: 5 passed and 24 xfailed (`--runxfail`: 24 AssertionErrors, at the section 6 asserts); G2 on the M3 head: 604 passed; `check_architecture_principles.py --check` passes; one `httpx.AsyncClient(` in `red_team.py`; a census of section 9's ten rows (the new file alone) killed all ten. Blobs on `98d0d99b` at the M2 head: `http_fetch.py` `8af51711a12180b17616002ff73b13dcfdebed07`, `red_team.py` `a33bd3c270edb3102011e6ba66c471d1cbf98507`, `tests/test_ad1346_admission_egress_sinks.py` `04c273f93c66f47c2aa4c01f217462d901943dce`, the new test file `c75e41662fbc0a141a8391fe393d52f5afabaa01` (at M1: `63bb31c6a5e035ed96ceb32001b98a08b07f2a7e`).
**Amendment A1 (2026-11-08, after review round 1 by `gpt-6.1-sol`):** the review found four issues. A first approved address that only timed out ended the verification and cost the fetch agent a failure outcome (F1); the refusal log carried the account name of a schemeless `account:pw@host` URL as a scheme's value (F2); the test file's docstring understated what it replaces (F4); and a public host with userinfo is approved by the shared floor, as before the change, so only the log is claimed credential-free (F3). The repair is the commit `BF-945 A1` (the Architect's repair design, pairs A1-1 to A1-17, and this one): `request_pinned` also moves on after `httpx.ConnectTimeout` (`HttpFetchAgent._request_pinned` is unchanged), a new `_reason_for_log` drops a scheme's value from the refusal log, and the test file gains a `userinfo-no-scheme` row, T8 and a corrected docstring (7 functions, 36 cases). The blocks of section 7 stay as the record of M1 to M3; the lines the A1 pairs replace are superseded in the tree.
**Amendment A2 (2026-11-08, after review round 2 by `gpt-6.1-sol`):** the review found two statements that said more than the evidence: the test file's docstring still omitted what the chain test's runtime stub replaces (F4), and property 7 of section 13 said T8 pins each boundary although it has no case for a pool timeout (N1). Both are corrected in the commit `BF-945 A2`. Sections 4 and 6 count the file as M1 to M3 built it (29 cases, T1 18); the final file has 36 cases (T1 20, T8 5).
**Base blobs:** `agents/red_team.py` `09209d02e759d6e1780f20357f8f466a079233fb`; `agents/http_fetch.py` `9f3ee9eb97f7707ff7e6930db59390238e3e37bd`; `tests/test_ad1346_admission_egress_sinks.py` `548af76d092e1129b7c85f9c14b715511b6294e6`.
**Dependencies:** AD-1346 M3e3b (the shadow `check_at`, `red_team.py:530`, kept), BF-821, #1421. **Tier:** M1 STANDARD (tests); M2 HIGH (a floor in a security path; edits the fetch agent's module); M3 STANDARD.
**Estimated tests:** one new file, 6 functions, 29 cases (5 pass, 24 xfail at M1); one existing test value is edited (P2-11). **BF number:** BF-945, held by #1720; nothing new is allocated (section 11).

**Which text describes the head.** Before building: `git rev-parse HEAD:src/probos/agents/red_team.py HEAD:src/probos/agents/http_fetch.py HEAD:tests/test_ad1346_admission_egress_sinks.py` prints the blobs above, `git diff --stat 98d0d99b HEAD -- src/probos/agents tests/test_ad1346_admission_egress_sinks.py PROGRESS.md DECISIONS.md` is empty, and the new test file does not exist. If the first or second fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **No floor.** `RedTeamAgent._verify_http_fetch` (`red_team.py:507`) takes `url` (`:515`), refuses an unsafe method (`:516`), makes the shadow check (`:530`), then runs `httpx.AsyncClient(timeout=4.0)` and `client.request(method, url)` (`:532-533`). The file holds no URL guard, egress consult or resolver call (section 11). `HttpFetchAgent` makes all three: `_validate_url` (`http_fetch.py:297`, from `:397`) and per hop `_validate_and_pin` (`:335`, from `:558`), then the request pinned to the approved address (`_pin_kwargs` `:682`, `_request_pinned` `:722`; used at `:568`, `:571`, `:588`).
2. **What it learns reaches its verdict.** For a URL the fetch agent refuses, the verifier sends the GET or HEAD and answers `Agent claims failure but URL is reachable` (`:542`), `Status code mismatch: expected=<its status> actual=<claimed>` (`:558`), `Content length mismatch` (`:572`), or verifies a matching success; its resolution of a name is unpinned. The orchestrator's reproduction on `66de630b` (cited from #1720, not re-run): 12 PASS for `169.254.169.254`, `127.0.0.1:8080/admin` and `10.0.0.5`.
3. **Reach** (traced here). `submit_intent_with_consensus` calls `verify` for each successful result (`runtime.py:4763`, `:4805`) and records the combined verdict as the fetch agent's trust outcome (`:4853`, `:4883`). `TwoStageVerifier.verify` calls it (`validation_framework.py:100`) only for a claimed failure (a claimed success is `metadata_only`, `:86`, `:133-134`), and is reached only through `ReconciliationEscalator`, which `finalize.py:4482` builds and nothing calls.

## 2. Solution

`agents/http_fetch.py` gains `vet_url`, `pin_kwargs` and `request_pinned`: public functions over the fetch agent's own methods (`_check_egress` and `_validate_and_pin` become classmethods, `_request_pinned` a staticmethod; no body, call site or behaviour changes). `_verify_http_fetch` asks `vet_url(url)` after the method refusal and the shadow check, before the client is built. A refusal requests nothing: `verified=not claimed.success`, a discrepancy for a claimed success only. A floor that raises requests nothing: `verified=False`. Otherwise the approved addresses are requested through `request_pinned`, `follow_redirects=False` written; the other verdicts and `timeout=4.0` are as before. ES2 verifies a name that resolves nowhere through the real floor: its constant changes (P2-11).

## 3. Decisions

**D1. Where the floor lives** (Engineering Principles: DRY, Law of Demeter).

| # | Option | Judgement |
|---|---|---|
| 1 | Public functions in `http_fetch.py` over the fetch agent's own methods (chosen) | One implementation; no private name crosses a module; `vet_url` reads the module globals `test_ad1346_admission_egress_sinks.py:177-178` patches; the patch points of eight test files stay (section 11); the one `httpx.AsyncClient(` stays in the verifier (census row `ad1346_effect_census.py:202`) |
| 2 | Move the bodies to module functions | The same end state, a ~75-line move in a security file |
| 3 | The verifier calls `url_guard` with its own pin | A second copy of BF-821's `Host` and SNI technique; no policy reachable |
| 4 | The verifier calls the fetch agent's private methods | Private access across modules; `_request_pinned` needs an instance |

**D2. The verdict on a refusal** (Fail Fast: log-and-degrade; Logging Standards).

| # | Verdict | Judgement |
|---|---|---|
| 1 | `verified=not claimed.success`; the text for a claimed success only; no confidence update; a WARNING with host and reason (chosen) | The method refusal in this function (#1421; `test_issue1421_http_fetch_safe_methods.py:467-486`) and AD-1328 S2a's refusal (`red_team.py:444-455`): the fetch agent refuses the same URL, so a failure claim is not contradicted and a success claim is not confirmed |
| 2 | `verified=False` for both claims | A failure the fetch agent reported reads as "the claim is false" at `TwoStageVerifier` |
| 3 | `verified=True` at low confidence (`:112-120`) | Endorses a success it did not check |
| 4 | Raise | `runtime.py:4783` catches per verifier; `TwoStageVerifier.verify` does not |

| Caller | Meets a refusal with | Before | After |
|---|---|---|---|
| `submit_intent_with_consensus` | a claimed success only: `(False, REFUSAL)` per verifier, then `record_outcome(success=False)` for the fetch agent | a matching status verified `True` | a failure outcome: a success the floor refuses at verification means the name now resolves to a refused address, the lookup failed, or the claim is false |
| `TwoStageVerifier.verify` | a claimed failure only: `(True, "")` | `(False, "...reachable")`: "the failure claim is false" | the failure claim stands |

A floor that raises is `verified=False` with its own text and a WARNING (AD-1328 S2a's judge fault, `red_team.py:429-440`); it can raise (L4). The status and length checks (`:550-572`) are not reached on a refusal. A URL refused by shape (httpx raised `ValueError` for an empty URL, measured) and an unresolvable name (`Verifier cannot reach URL...`) now take this verdict.

**D3. The pin, redirects, timeout, method.**

| # | Request path | Judgement |
|---|---|---|
| 1 | Pin to the approved addresses in order, as `request_pinned`, which also moves on after a connect timeout; `_request_pinned` unchanged (chosen) | One lookup; the connection lands on an address the floor judged, and a first address that only times out does not end the verification (httpx's own connect tried every address). Cost: L2 |
| 2 | Validate, then `client.request(method, url)` | A second, unjudged resolution: DNS rebinding |
| 3 | A custom transport | A new class for what `Host` and `sni_hostname` already do |
| 4 | Widen `_request_pinned` to catch `ConnectTimeout` | Changes the fetch agent for no gain: its chain's `asyncio.timeout(8.0)` equals its connect timeout (`http_fetch.py:540`, `:565`), so no time is left for the next address |
| 5 | Keep the first-error behaviour and record it | A regression: a first address that only times out reads `Verifier cannot reach URL` and costs the fetch agent a failure outcome |

`httpx.AsyncClient` follows no redirect unless `follow_redirects=True`; the default is False (installed 0.28.1; `pyproject.toml:29` requires `>=0.27`), so the verifier answers about the first hop; the fetch agent follows by hand and judges every hop, hop 0 included (`:558-588`). The verifier follows none, so none needs the floor; the keyword is now written and T4 pins it. `timeout=4.0` stays the first `timeout=<number>` in the function (`test_ad152_regressions.py:88-91`, AD-1346 register R96) and below `verification_timeout_seconds` (5.0, `config_models/core.py:90`); the method refusal (`:516`) still precedes the shadow check, the floor and every lookup.

**D4. The egress consult.**

| # | How the verifier gets the policy | Judgement |
|---|---|---|
| 1 | `vet_url` reads it where the fetch agent does: `_validate_and_pin` then `cls._egress_policy` (chosen) | The identical rule at the identical moment; nothing to wire (`tests/conftest.py:231` resets it); none set: no consult, as the fetch agent |
| 2 | A setter on the red team, called at `finalize.py:4806` | A second copy of the same state, set separately |
| 3 | A constructor argument from `_spawn_red_team` | The policy is built later: `create_agent_fleet` runs at `runtime.py:2972`, `finalize_startup` at `:3709`, which builds it (`finalize.py:4709`): the argument would be None |
| 4 | `getattr(self._runtime, "egress_policy", None)` | The runtime holds one whenever `egress_enabled`, but the fetch agent consults it only when `egress_active_enforcement` (default False) wired it (`finalize.py:4802-4806`; BF-751's note, `config.py:2868-2879`): the verifier would enforce what the fetch agent does not |

AD-1346 M3e3b's check is built, not pending; its D205 puts this guard after it and before the request. ES1 (`test_ad1346_admission_egress_sinks.py:206`) needs one `check_at` statement in the body before the first egress point and the census counts one `httpx.AsyncClient(` in the scope: both hold with the floor after the check.

**D5. Tests** (Testing Standards). The real `RedTeamAgent`, guard and pin, only `socket.getaddrinfo` and `httpx.AsyncClient` replaced, each refusal asserting which reason fired (BF-832), and one seam test through `submit_intent_with_consensus` (chosen). Rejected: unit tests of the three facades alone (the defect was that the verifier did not call them); a source-text test.

**D6. Trackers.** PROGRESS.md, DECISIONS.md and the ledger (M3), as BF-959's. The roadmap is not edited (`Grep BF-945` finds 0; its Bug Tracker, `:1131`, holds BF-682 and BF-683); no security document changes (`docs/architecture/consensus.md:22` and `docs/agents/inventory.md:91` describe the fetch agent); `security/egress.py`'s header is not edited (L5).

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-11, then N2-1 (removing the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf945_red_team_url_floor.py -q -n 0 -p no:randomly`. **Expected: 5 passed** (the guard functions), **24 xfailed** (the class). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.**
  1. `PY -m pytest tests/test_bf945_red_team_url_floor.py tests/test_ad152_regressions.py tests/test_red_team.py tests/test_issue1421_http_fetch_safe_methods.py tests/test_ad1346_admission_egress_sinks.py tests/test_ad1346_admission_egress_census.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_sink_wiring.py tests/test_ad451_validation_framework.py tests/test_bf743_browser_ssrf_floor.py tests/test_bf819_redirect_ssrf.py tests/test_bf820_domain_slot_serialisation.py tests/test_bf821_pinned_address.py tests/test_bf770_fetch_coalescing.py tests/test_bf729_ad1222_chosen_limits.py tests/test_bf769_blocked_search_fails.py tests/test_bf772_fetch_failures_are_honest.py tests/test_bf807_truncation_reaches_readers.py tests/test_ad456b_runtime_sandboxing.py tests/test_ad456_security_infrastructure.py tests/test_bf751_egress_allowlist.py tests/test_conftest_egress_policy_isolation.py tests/test_sandbox_fetch_broker.py tests/test_expansion_agents.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
  2. `PY -P scripts/check_architecture_principles.py --check`
  3. `rg -n "httpx\.AsyncClient\(" src/probos/agents/red_team.py` prints one line.
  - **Expected:** the new file 29 passed; every other file 0 failed, collected counts equal M0; the check clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-945 M1: tests for the red team's http_fetch verifier applying the fetch agent's URL floor, xfail until built (#1720)`
- **M2:** `BF-945 M2: the red team's http_fetch verifier requests nothing the URL floor refuses and sends its request to the approved address (#1720)`
- **M3:** `BF-945 M3: trackers and ledger (#1720)`; its body ends with the line `Closes #1720.`

## 6. Tests (`tests/test_bf945_red_team_url_floor.py`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 18 | 8 URLs (loopback, metadata, private, reserved, a name that resolves to loopback, unresolvable, scheme, credentials) and a floor that raises, x both claims: no request, the verdict, `<host> (<reason>)` logged (`-` for a URL with no host), no credentials | M2 |
| T3 | 2 | The pin: address, `Host`, SNI, one lookup, also when the name changes its answer | M2 |
| T6 | 3 | The egress policy: denies (both claims), allows | M2 |
| T7 | 1 | **Seam:** real fetch agents, `submit_intent_with_consensus`, real verifiers, trust outcomes; a control round first | M2 |
| T2 | 4 | Guard: the old verdicts on an approved URL | none |
| T4 | 1 | Guard: one request, no hop | none |

**How each xfail case fails on the base.** At an `assert` of its own body: T1 at `assert seen == []`; T3 at the recorded host; T6 at `calls == [URL]`; T7 at the second round's `(False, REFUSAL)` line (its premise lines pass on the base). The assertions after the first (the verdict, the capability-gap and confidence line, the log pin) are not reached on the base; they first run at G2.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf945_red_team_url_floor.py`:

```python
"""BF-945 (#1720): the red team's http_fetch verifier applies the fetch agent's URL floor.

The real ``RedTeamAgent``, URL guard and pin; only ``socket.getaddrinfo`` (a resolver that knows its own names) and
``httpx.AsyncClient`` (on a recording ``httpx.MockTransport``) are replaced. The class holds the cases the unfixed tree
fails; the functions before it pass on both. No BF-945 name is imported.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import types
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.red_team import RedTeamAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.types import IntentMessage, IntentResult

NAME, PUBLIC = "api.example.test", "93.184.215.14"
URL = f"https://{NAME}/items/1"
REFUSAL = "Agent claims success for a URL that the fetch floor refuses, so it was not re-fetched"
FAULT = "The URL floor could not judge the URL, so it was not re-fetched"
_LOGGER = "probos.agents.red_team"
_AT = "@"  # joins the "credentials" URL below: a tool's output redacts a literal user:password@host, so a reader could not copy it

class _Resolver:
    """``socket.getaddrinfo``: a list answers every call, a list of lists one per call (the last repeated), an exception
    is raised; an address literal answers itself; any other name is refused."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers, self.calls = answers, []

    def __call__(self, host: Any, *_args: Any, **_kwargs: Any) -> list[Any]:
        name = host.decode("ascii") if isinstance(host, bytes) else str(host)
        self.calls.append(name)
        answer = self.answers.get(name)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            try:
                ipaddress.ip_address(name)
            except ValueError:
                raise socket.gaierror(f"not a test name: {name!r}") from None
            answer = [name]
        elif isinstance(answer[0], list):
            answer = answer[min(self.calls.count(name), len(answer)) - 1]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in answer]


def _rig(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any] | None = None, handler: Any = None):
    """The resolver and a transport recording each request (200 and ``ok``, ``handler``'s response, or the exception
    ``handler`` is). Once per test: it wraps ``httpx.AsyncClient``."""
    names = {NAME: [PUBLIC], "localtest.me": ["127.0.0.1"], "boom.example.test": UnicodeError("label too long")}
    resolver = _Resolver({**names, **(answers or {})})
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(handler, Exception):
            raise handler
        return handler(request) if handler else httpx.Response(200, content=b"ok", request=request)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    return resolver, seen


async def _verify(url: str, success: bool = True, *, status: int = 200, length: int = 2,
                  verifier: RedTeamAgent | None = None) -> Any:
    intent = IntentMessage(intent="http_fetch", params={"url": url})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="http-0", success=success, error=None if success else "refused",
        result={"status_code": status, "body_length": length} if success else None,
    )
    return await (verifier or RedTeamAgent(agent_id="rt-0", pool="red_team")).verify("http-0", intent, claimed)


AS_BEFORE = [  # id, claimed success, claimed status, claimed length, transport answer, verified, discrepancy
    ("verified", True, 200, 2, None, True, ""),
    ("claims-failure-but-reachable", False, 200, 2, None, False, "Agent claims failure but URL is reachable"),
    ("status-mismatch", True, 204, 2, None, False, "Status code mismatch: expected=200 actual=204"),
    ("unreachable", True, 200, 2, httpx.ConnectError("down"), False, "Verifier cannot reach URL but agent claims success"),
]
REFUSED = [  # id, url, what the log names (the floor's reason, or the exception class of a floor that raises)
    ("loopback", "http://127.0.0.1:8080/admin", "Blocked private/reserved IP: 127.0.0.1"),
    ("link-local-metadata", "http://169.254.169.254/latest/meta-data/", "Blocked private/reserved IP: 169.254.169.254"),
    ("private", "http://10.0.0.5/", "Blocked private/reserved IP: 10.0.0.5"),
    ("reserved", "http://240.0.0.1/", "Blocked private/reserved IP: 240.0.0.1"),
    ("name-to-loopback", "http://localtest.me/", "Blocked private/reserved IP: 127.0.0.1"),
    ("unresolvable", "http://nowhere.example.test/", "Cannot resolve hostname: nowhere.example.test"),
    ("file-scheme", "file:///etc/passwd", "Blocked scheme: file"),
    ("credentials", "http://user:s3cret" + _AT + "169.254.169.254/latest/", "Blocked private/reserved IP: 169.254.169.254"),
    ("floor-raises", "http://boom.example.test/", "UnicodeError"),
]


@pytest.mark.parametrize("case", AS_BEFORE, ids=[case[0] for case in AS_BEFORE])
async def test_a_url_that_passes_the_floor_is_verified_as_before(monkeypatch, case):
    _label, success, status, length, answer, verified, discrepancy = case
    _resolver, seen = _rig(monkeypatch, handler=answer)
    verdict = await _verify(URL, success, status=status, length=length)
    assert (verdict.verified, verdict.discrepancy) == (verified, discrepancy) and len(seen) == 1


async def test_a_redirect_is_not_followed(monkeypatch):
    answered: list[httpx.Request] = []

    def redirect_once(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        return httpx.Response(302 if len(answered) == 1 else 200, headers={"location": "http://127.0.0.1/admin"}, request=request)

    _resolver, seen = _rig(monkeypatch, handler=redirect_once)
    verdict = await _verify(URL)
    assert len(seen) == 1 and seen[0].url.host in (NAME, PUBLIC), [str(request.url) for request in seen]
    assert verdict.discrepancy == "Status code mismatch: expected=302 actual=200"


class TestTheVerifierJudgesTheUrlAsTheFetchAgentDoes:
    # BF-945 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-945 M2 builds it")

    @pytest.mark.parametrize("success", [True, False], ids=["claimed-success", "claimed-failure"])
    @pytest.mark.parametrize("label,url,logged", REFUSED, ids=[row[0] for row in REFUSED])
    async def test_a_url_the_floor_refuses_or_cannot_judge_is_not_requested(
        self, monkeypatch, caplog, label, url, logged, success,
    ):
        _resolver, seen = _rig(monkeypatch)
        assert (await _verify(URL)).verified is True and len(seen) == 1, "premise: an approved URL is requested once"
        seen.clear()
        verifier = RedTeamAgent(agent_id="rt-0", pool="red_team")
        before = verifier.confidence
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            verdict = await _verify(url, success, verifier=verifier)
        expected = (False, FAULT) if label == "floor-raises" else (not success, REFUSAL if success else "")
        assert seen == [], "a URL the floor refuses or cannot judge was requested"
        assert (verdict.verified, verdict.discrepancy) == expected
        assert not is_capability_gap(expected[1]) and verdict.confidence == verifier.confidence == before
        host = urlparse(url).hostname or "-"  # the log names the host, or - for a URL with none (file:///...)
        verb = "could not judge" if label == "floor-raises" else "refused"
        assert f"{verb} {host} ({logged})" in caplog.text
        assert "s3cret" not in caplog.text and "label too long" not in caplog.text

    @pytest.mark.parametrize("answers", [[PUBLIC], [[PUBLIC], ["127.0.0.1"]]], ids=["stable", "name-changes-its-answer"])
    async def test_the_request_goes_to_the_approved_address_and_speaks_the_name(self, monkeypatch, answers):
        resolver, seen = _rig(monkeypatch, {NAME: answers})
        verdict = await _verify(URL)
        (request,) = seen
        assert (request.url.host, request.headers.get("host"), request.extensions.get("sni_hostname")) == (PUBLIC, NAME, NAME)
        assert resolver.calls == [NAME] and verdict.verified is True

    @pytest.mark.parametrize(
        "answer,success,verified,discrepancy",
        [(False, True, False, REFUSAL), (False, False, True, ""), (True, True, True, "")],
        ids=["denies-claimed-success", "denies-claimed-failure", "allows"],
    )
    async def test_the_egress_policy_the_fetch_agent_holds_decides_for_the_verifier(
        self, monkeypatch, caplog, answer, success, verified, discrepancy,
    ):
        _resolver, seen = _rig(monkeypatch)
        calls: list[str] = []
        monkeypatch.setattr(
            HttpFetchAgent, "_egress_policy", types.SimpleNamespace(is_allowed=lambda url: calls.append(url) or answer),
        )
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            verdict = await _verify(URL, success)
        assert calls == [URL] and len(seen) == int(answer)
        assert (verdict.verified, verdict.discrepancy) == (verified, discrepancy)
        assert ("Egress policy: blocked by AD-456b runtime sandboxing" in caplog.text) is (not answer)

    async def test_a_fetch_the_verifier_cannot_reproduce_is_not_confirmed_and_costs_the_fetch_agent_trust(self, monkeypatch):
        from tests.test_issue1421_http_fetch_safe_methods import _bus_with_agents, _stub_runtime

        async def no_wait(self, _domain, state):
            state.last_request_time = 0
            return 0.0

        monkeypatch.setattr(HttpFetchAgent, "_wait_for_rate_limit", no_wait)
        resolver, seen = _rig(monkeypatch)
        outcomes: list[tuple[str, bool]] = []
        trust = types.SimpleNamespace(
            get_score=lambda _id: 0.5, record_outcome=lambda agent_id, *, success, **_kw: outcomes.append((agent_id, success)),
        )

        async def one_round():
            for table in (HttpFetchAgent._inflight, HttpFetchAgent._waiters, HttpFetchAgent._domain_state):
                table.clear()
            seen.clear()
            outcomes.clear()
            runtime = _stub_runtime(_bus_with_agents()[0])
            runtime.trust_network = trust
            out = await runtime.submit_intent_with_consensus("http_fetch", params={"url": URL}, timeout=30.0)
            rechecks = [r for r in seen if r.headers["user-agent"] != HttpFetchAgent.USER_AGENT]
            return [(v.verified, v.discrepancy) for v in out["verifications"]], list(outcomes), rechecks

        verdicts, trusted, rechecks = await one_round()
        assert verdicts == [(True, "")] * 6 and len(rechecks) == 6, "premise: 2 verifiers x 3 results, all verified"
        assert trusted == [(f"http-{i}", True) for i in range(3)], "premise: the round records trust"
        recheck = RedTeamAgent._verify_http_fetch

        async def name_changes_its_answer(self, *args, **kwargs):
            resolver.answers[NAME] = ["127.0.0.1"]
            return await recheck(self, *args, **kwargs)

        monkeypatch.setattr(RedTeamAgent, "_verify_http_fetch", name_changes_its_answer)
        verdicts, trusted, rechecks = await one_round()
        assert seen, "premise: the fetch agents fetched at the public address"
        assert verdicts == [(False, REFUSAL)] * 6 and rechecks == []
        assert trusted == [(f"http-{i}", False) for i in range(3)]
```

### 7.2 M2

**P2-1.** `src/probos/agents/http_fetch.py`
SEARCH:
```
    def _check_egress(self, url: str) -> str | None:
```
REPLACE:
```
    @classmethod
    def _check_egress(cls, url: str) -> str | None:  # BF-945: a classmethod, so ``vet_url`` needs no agent
```

**P2-2.** `src/probos/agents/http_fetch.py`
SEARCH:
```
        policy = type(self)._egress_policy
```
REPLACE:
```
        policy = cls._egress_policy
```

**P2-3.** `src/probos/agents/http_fetch.py`
SEARCH:
```
    def _validate_and_pin(self, url: str) -> PinnedTarget:
```
REPLACE:
```
    @classmethod
    def _validate_and_pin(cls, url: str) -> PinnedTarget:  # BF-945: a classmethod, so ``vet_url`` needs no agent
```

**P2-4.** `src/probos/agents/http_fetch.py`
SEARCH:
```
        egress = self._check_egress(url)
```
REPLACE:
```
        egress = cls._check_egress(url)
```

**P2-5.** `src/probos/agents/http_fetch.py`
SEARCH:
```
    async def _request_pinned(
        self,
        client: httpx.AsyncClient,
```
REPLACE:
```
    @staticmethod  # BF-945: it reads no instance state
    async def _request_pinned(
        client: httpx.AsyncClient,
```

**P2-6.** `src/probos/agents/http_fetch.py`
SEARCH:
```
class HttpFetchAgent(BaseAgent):
    """Concrete agent that fetches URLs via HTTP.
```
REPLACE:
```
def vet_url(url: str) -> PinnedTarget:
    """BF-945: the fetch agent's judgement of a URL (the floor, then the egress consult) for a caller that is not the
    fetch agent: the approved addresses or the refusal. It reads the policy the fetch agent reads."""
    return HttpFetchAgent._validate_and_pin(url)


def pin_kwargs(
    logical: httpx.URL, addresses: tuple[str, ...]
) -> list[tuple[httpx.URL, dict[str, str], dict[str, str]]]:
    """BF-945: the fetch agent's pinned attempts (BF-821): connect to each approved address, speak to the name."""
    return HttpFetchAgent._pin_kwargs(logical, addresses)


async def request_pinned(
    client: httpx.AsyncClient,
    method: str,
    attempts: list[tuple[httpx.URL, dict[str, str], dict[str, str]]],
) -> httpx.Response:
    """BF-945: the fetch agent's request over those attempts, each approved address in order (BF-821)."""
    return await HttpFetchAgent._request_pinned(client, method, attempts)


class HttpFetchAgent(BaseAgent):
    """Concrete agent that fetches URLs via HTTP.
```

**P2-7.** `src/probos/agents/red_team.py`
SEARCH:
```
from probos.agents.http_fetch import safe_fetch_method
```
REPLACE:
```
from probos.agents.http_fetch import pin_kwargs, request_pinned, safe_fetch_method, vet_url
```

**P2-8.** `src/probos/agents/red_team.py`
SEARCH:
```
from typing import Any

import httpx
```
REPLACE:
```
from typing import Any
from urllib.parse import urlparse

import httpx
```

**P2-9.** `src/probos/agents/red_team.py`
SEARCH:
```
_RERUN_TEARDOWN_GRACE_S = 5.0


class RedTeamAgent(BaseAgent):
```
REPLACE:
```
_RERUN_TEARDOWN_GRACE_S = 5.0


def _host_of(url: Any) -> str:
    """BF-945: the host of ``url`` for a log line (never credentials, path or query); ``-`` when there is none."""
    try:
        return urlparse(url).hostname or "-"
    except (AttributeError, TypeError, ValueError):
        return "-"


class RedTeamAgent(BaseAgent):
```

**P2-10.** `src/probos/agents/red_team.py`
SEARCH:
```
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.request(method, url)
```
REPLACE:
```
        # BF-945: the fetch agent's floor, after the shadow check and before any request.
        try:
            target = vet_url(url)
        except Exception as error:  # BF-945: not judged, so not requested
            logger.warning(
                "BF-945: the URL floor could not judge %s (%s); not re-fetched, the claim is left unverified",
                _host_of(url), type(error).__name__,
            )
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy="The URL floor could not judge the URL, so it was not re-fetched",
                confidence=self.confidence,
            )
        if target.reason is not None:  # BF-945: refused, so nothing is requested
            logger.warning(
                "BF-945: the URL floor refused %s (%s); not re-fetched, the verdict rests on the refusal",
                _host_of(url), target.reason,
            )
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=not claimed.success,  # BF-945: nothing was fetched
                discrepancy=(
                    "Agent claims success for a URL that the fetch floor refuses, so it was not re-fetched"
                    if claimed.success else ""
                ),
                confidence=self.confidence,
            )
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:  # BF-945: no hop, so no floor per hop
                response = await request_pinned(client, method, pin_kwargs(httpx.URL(url), target.addresses))  # BF-945: pinned
```

**P2-11.** `tests/test_ad1346_admission_egress_sinks.py`
SEARCH:
```
VERIFIED_URL = "https://ad1346-m3e3b.test/verified"
```
REPLACE:
```
VERIFIED_URL = "https://93.184.215.14/ad1346-m3e3b-verified"  # BF-945: a public address: ES2's real URL floor needs no lookup
```

**N2-1.** `tests/test_bf945_red_team_url_floor.py`
SEARCH:
```
    # BF-945 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-945 M2 builds it")

    @pytest.mark.parametrize("success", [True, False], ids=["claimed-success", "claimed-failure"])
```
REPLACE:
```
    @pytest.mark.parametrize("success", [True, False], ids=["claimed-success", "claimed-failure"])
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-945 (DATE), #1720 -- the red team's http_fetch verifier applies the fetch agent's URL floor.**
- **Base.** The verifier requested the intent's URL with no URL guard and no egress consult, so it sent a GET or HEAD to loopback, link-local, private and reserved addresses, and to names that resolve to one, that the fetch agent refuses; its resolution was unpinned.
- **Fix.** It asks `vet_url` (the fetch agent's floor and egress consult: new public functions in `agents/http_fetch.py` over its own methods) and requests nothing it refuses (`verified` is `not claimed.success`; a floor that raises leaves the claim unverified); an approved URL is requested at the approved address (as BF-821), no redirect followed. Contract `prompts/bf-945-red-team-url-floor.md`. Closes #1720.

```

**P3-2.** `DECISIONS.md`. Append after BF-960's entry. Its last bullet occurs once.
SEARCH:
```
- *Reversal.* Revert the BF-960 commits.
```
REPLACE:
```
- *Reversal.* Revert the BF-960 commits.

### BF-945 -- The red team's http_fetch verifier applies the fetch agent's URL floor (DATE, #1720)

- *Scope.* `agents/http_fetch.py` (`vet_url`, `pin_kwargs`, `request_pinned`; two classmethods and a staticmethod), `agents/red_team.py` (`_verify_http_fetch`, `_host_of`), one constant of `tests/test_ad1346_admission_egress_sinks.py`, tests. Contract `prompts/bf-945-red-team-url-floor.md`.
- *G1 (where).* Public functions in the fetch agent's module over its own methods. Rejected: the verifier's own pin (a second copy of BF-821); the bodies moved; `fetch_governed`.
- *G2 (verdict).* `verified=not claimed.success`, as the method refusal in the same function (#1421); a floor that raises is `verified=False` (AD-1328 S2a). Rejected: `False` for both claims; `True` at low confidence; raising.
- *G3 (pin, egress).* The request goes to the approved addresses; no redirect is followed; the egress consult is the fetch agent's own policy, read where it reads it. Rejected: a setter on the red team; a constructor argument (the policy is built after the fleet); a runtime lookup (a policy the fetch agent does not enforce).
- *Residual.* L1 to L8 of the contract. *Reversal.* Revert the BF-945 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

The fetch agent's behaviour (`_validate_url`, `_fetch_url`, `_follow_and_fetch`, the bodies of the four methods above, rate limiting, coalescing, refusal strings), `security/url_guard.py` and `egress.py`; the method refusal (#1421), the shadow check and its position, `timeout=4.0`, the verdict texts and `update_confidence` calls for an approved URL, the red team's other verifiers; `runtime.py`, `finalize.py`, `_spawn_red_team`, `validation_framework.py`, the configuration (no field), the browser tool; AD-1346's census rows and `ES1` to `ES4` (one constant of ES2). OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/agents/red_team.py | `if target.reason is not None:  # BF-945: refused, so nothing is requested` | `if False:` | T1, T6 |
| 2 | M2 | src/probos/agents/red_team.py | `verified=not claimed.success,  # BF-945: nothing was fetched` | `verified=False,` | T1[claimed-failure], T6 |
| 3 | M2 | src/probos/agents/red_team.py | `"Agent claims success for a URL that the fetch floor refuses, so it was not re-fetched"` | `""` | T1[claimed-success], T6, T7 |
| 4 | M2 | src/probos/agents/red_team.py | `_host_of(url), _reason_for_log(target.reason),` | `"-", _reason_for_log(target.reason),` | T1[credentials] |
| 5 | M2 | src/probos/agents/red_team.py | `except Exception as error:  # BF-945: not judged, so not requested` | `except ZeroDivisionError as error:` | T1[floor-raises] |
| 6 | M2 | src/probos/agents/red_team.py | `async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:  # BF-945: no hop, so no floor per hop` | `async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:` | T4 |
| 7 | M2 | src/probos/agents/red_team.py | `response = await request_pinned(client, method, pin_kwargs(httpx.URL(url), target.addresses))  # BF-945: pinned` | `response = await client.request(method, url)` | T3 |
| 8 | M2 | src/probos/agents/http_fetch.py | `return HttpFetchAgent._validate_and_pin(url)` | `return PinnedTarget(None, ())` | T1, T6, T7 |
| 9 | M2 | src/probos/agents/http_fetch.py | `egress = cls._check_egress(url)` | `egress = None` | T6[denies], `test_ad456b_runtime_sandboxing.py` |
| 10 | M2 | src/probos/agents/http_fetch.py | `return HttpFetchAgent._pin_kwargs(logical, addresses)` | `return [(logical, {}, {})]` | T3 |

No campaign of record (a read-only consult). The Builder runs the 10 mutants once, on M2's head, with the new file alone. Not tabulated, for the cap: the fault branch's `verified=False`, the fault line's host (pinned by `T1[floor-raises]`), and dropping the `follow_redirects` keyword (equivalent: httpx's default is False; row 6 is the killable form).

## 10. Recorded limits

- **L1.** `vet_url` resolves on the event loop with `socket.getaddrinfo`, as the fetch agent's floor does (BF-821): a slow resolver holds the loop and the consensus `wait_for` (`runtime.py:4762`) cannot interrupt it. Each of the two verifiers (`config_models/core.py:91`) resolves once per result; nothing caches.
- **L2.** The approved addresses are tried in order, as BF-821 does, where httpx's own connect overlapped attempts 0.25 s apart (anyio's `connect_tcp`). `request_pinned` moves on after a refused connection (`ConnectError`) and after a connect that timed out (`ConnectTimeout`, a TLS handshake included); a read, write or pool timeout ends the request. The fetch agent's `_request_pinned` moves on after a refusal only and is unchanged (D3). Each attempt has the client's 4.0 s against the consensus wrapper's 5.0 s (`config_models/core.py:90`), so after a blackholed first address the next has about 1.0 s: a second address that answers in that time verifies; an attempt still running at 5.0 s is cut (`runtime.py:4791`: a `Verification timeout` WARNING, no verdict and no trust change from that verifier), as two addresses that both time out are; an attempt that fails earlier gives the next address or, for the last, `Verifier cannot reach URL but agent claims success`, as for one address. The tests raise the exceptions; real connect timings were not measured.
- **L3.** The verifier follows no redirect, before and after: a claim about a redirect chain's final answer meets the first hop's status and reads as `Status code mismatch`. A separate defect, not filed by this contract.
- **L4.** `resolve_and_pin` catches `socket.gaierror` only; a label over 63 characters makes `socket.getaddrinfo` raise `UnicodeError` (measured), which the fetch agent's `_validate_url` lets out of `_fetch_url` (`http_fetch.py:397`, outside any `try`; what its callers do is not traced). The verifier answers it with the fault verdict (T1[floor-raises]); the fetch agent is not changed.
- **L5.** `security/egress.py`'s header says the red team's probes call `is_allowed`; through `vet_url` they do only when the fetch agent's policy is wired (`egress_active_enforcement`, default False). The header is not edited.
- **L6.** A fault of the floor reads as `verified=False` for a claimed failure too, as a judge fault does (`red_team.py:429-440`): both callers read it as "unverified". The egress policy's own failure allows the request, as for the fetch agent (`http_fetch.py:322-331`).
- **L7.** A name that answers a public address to the fetch agent and a refused one to the verifier is the rebinding case: the verifier refuses and the fetch agent takes a failure outcome (T7); a resolver failure at the verifier does the same, as before.
- **L8.** No test opens a socket or resolves a name. The 12-PASS reproduction is cited, not re-run; DNS rebinding against a live name server was not demonstrated; nothing here is a live-system claim.

## 11. Verified Against Codebase (2026-11-08, reading tree `D:\ProbOS-worktrees\bf959-base` at `98d0d99b`)

**Run by the Architect, read-only and in memory (no test; nothing written into a repository tree):**

```
url_guard.py from the base blob, CPython 3.12.13, getaddrinfo stubbed: the 8 URLs of T1 give exactly T1's reasons; an approved name and literal give their address; the real getaddrinfo on a 70-character label raises UnicodeError, not gaierror
httpx 0.28.1 on MockTransport: a pinned request arrives with url host = the address, headers["host"] = the name, extensions["sni_hostname"] = the name, user-agent python-httpx/0.28.1; follow_redirects=False gives the 302 and one request, True a second request to the Location; a handler's ConnectError propagates after the request is recorded; client.request("GET", "") raises ValueError
This contract's 15 blocks applied in label order to the LF blobs: every SEARCH occurs once; the results parse and compile; in _verify_http_fetch: one httpx.AsyncClient( call and no other egress primitive, one check_at call as a body statement before it, the first timeout= number is 4.0; RedTeamAgent keeps 13 methods (threshold 15); no type(self)._egress_policy remains; each section 9 line occurs once in its patched file
```

**Absence Verified (2026-11-08)**

```
CLAIM: red_team.py holds no URL guard, egress consult or resolver call
RUN:   Grep "validate_public_url|validate_and_pin|url_guard|EgressPolicy|is_allowed|[Ee]gress|getaddrinfo|socket" in agents/red_team.py
FOUND: one line, :530, the M3e3b shadow check (the issue's lowercase "egress" rg prints it too)
HOLDS: yes

CLAIM: the only src callers of RedTeamAgent.verify are runtime.py:4763 and validation_framework.py:100; nothing calls reconcile on the escalator
RUN:   Grep "rt_agent\.verify|_red_team\.verify|\.verify\(target_agent_id|red_team\.verify\(|reconciliation_escalator|ReconciliationEscalator|TwoStageVerifier" and "\.reconcile\(" over src
FOUND: runtime.py:4763, validation_framework.py:100 (TwoStageVerifier built only at :316); finalize.py:4481-4488 builds the escalator ("built, not invoked"); the .reconcile( hits are other classes
HOLDS: yes

CLAIM: no BF-945 other than #1720
RUN:   git log --all --grep=BF-945 (0); prompts bf-9* (941, 946 to 960); gh issue list --state all --search "BF-945 in:title"; Grep "BF-945|#1720" in PROGRESS.md, DECISIONS.md, roadmap.md
FOUND: one issue, #1720 (OPEN, bug); PROGRESS.md:102 and DECISIONS.md:1141 (AD-1346 M3e3b: "BF-945's URL guard is its own change"); roadmap: 0
HOLDS: yes

CLAIM: vet_url, pin_kwargs, request_pinned, _host_of are free names; the four converted methods are named by no other src file, and by eight test files that only patch or call them
RUN:   Grep "\bvet_url\b|\bpin_kwargs\b|[^_\w]request_pinned\b|\b_host_of\b" over src, tests, scripts; Grep "_validate_and_pin|_pin_kwargs|_request_pinned|_check_egress" over src, tests
FOUND: 0 for the new names. src: http_fetch.py only. tests: bf729, bf769, bf770, bf807, bf819, bf820, bf821, issue1421: setattr patches of _validate_and_pin (bf729:73 on an instance; the others on the class), a subclass override (bf820:392), a setattr of _pin_kwargs (bf821:439), calls of _pin_kwargs and _request_pinned (bf821); _check_egress: 0 test hits
HOLDS: yes (pytest's monkeypatch restores a class attribute from the class __dict__, classmethods and staticmethods included)

CLAIM: no test asserts a verdict text of _verify_http_fetch; the tests that run its real http path are ES2 to ES4 and two of #1421's
RUN:   Grep "URL is reachable|Status code mismatch|Content length mismatch|Verifier cannot reach URL|_verify_http_fetch" over src, tests, scripts, ui/src, config; Grep "RedTeamAgent" in tests (19 files); git grep -c "red_team" -- tests scripts (43 files, none in scripts)
FOUND: the texts only in red_team.py; the function named by the census fixture (:202), ES (:4, :89) and ad152 (:85-90); ES2 (:272, resolver=False, a .test name that resolves nowhere) breaks under the real floor (P2-11); ES3 and ES4 patch the floor names in probos.agents.http_fetch, which vet_url reads; #1421 :470 and :492 use a DNS fake that resolves their host and read the default user agent; test_red_team.py: 0 http_fetch; ad1346_file_write_census.py: 0 red_team
HOLDS: yes

CLAIM: no AD-1346 census row, ledger line or line anchor changes
RUN:   Read the fixture's _EgressScan and rows, ES1, EC4; the in-memory check above
FOUND: rows are keyed by (file, scope) and counted by AST, not line; the egress row counts httpx.AsyncClient( (kept: one); httpx.URL, client.request and request_pinned are no EGRESS_PRIMITIVES name or argument; ES1 needs the check_at statement before the first point (kept); the subprocess row and BF-892's scan are untouched; admission_service's "named" and "importers" sets read the text and the imports, unchanged; check_architecture_principles.py: SRP threshold 15 methods (RedTeamAgent 13; its baseline trigger is lines only), HttpFetchAgent's two triggers unchanged
HOLDS: yes
```

**Not measured by the Architect:** the 10 mutants (by reading, not run); the orchestrator's reproduction; L2's timing; what the fetch agent's callers do with L4's `UnicodeError`; that `_stub_runtime` reaches `record_outcome` for three agents (T7's control round asserts it). **Measured by the orchestrator's oracle** (the 15 blocks applied by tool on `98d0d99b`): G1 5 passed and 24 xfailed, `--runxfail` 24 failures at the section 6 asserts; G2 602 passed and 2 failed before the N1-1 correction (the two `file-scheme` cases, whose log line has no host: corrected by the Architect's pair, applied in N1-1).

## 12. Prior Art and Blind Spots

- **Internal: adopted.** This function's method refusal (#1421) and AD-1328 S2a's refusal and judge fault (the verdicts); BF-821's pin and BF-819's per-hop floor (the fetch agent's methods); BF-743's one floor and BF-832's "assert which refusal fired"; the #1421 file's strict DNS and `MockTransport` rig; AD-1346 M3e3b's D205 and R96. **Rejected:** a second pin in the red team; `fetch_governed` (a rate limit, retry, body cap, coalescing and a dict result, on an instance); a runtime lookup of the policy. **External:** none consulted.
- **Blind spots handled.** A name that changes its answer, a floor that raises, credentials in a refused URL (kept out of the log; a public host with userinfo is approved, as before), the policy on, a redirect, a first address that only times out, and the chain to the trust outcome (T1, T3, T6, T4, T7, T8).
- **What discards a correct result.** An approved URL refused: a resolver failure at the verifier (L7). An approved URL not verified: the sequential connect (L2), the first hop's status (L3). **Recorded:** L1 to L8.

## 13. Diff Reviewer: properties to verify

1. In `_verify_http_fetch`, `vet_url(url)` runs after the method refusal and the one `check_at` statement and before `httpx.AsyncClient(`; nothing is requested when it returns a reason or raises; the function holds one `check_at` call and one `httpx.AsyncClient(`.
2. The request goes through `request_pinned(client, method, pin_kwargs(httpx.URL(url), target.addresses))` with `follow_redirects=False`; `timeout=4.0` is the first `timeout=<number>` in the function's source, comments and docstring included.
3. The refusal verdict is `verified=not claimed.success`, the text for a claimed success only, no `update_confidence`; the fault verdict is `verified=False`. Trace both through `runtime.py:4763` to `combine_verdicts` and `record_outcome`, and through `validation_framework.py:100`.
4. `_check_egress` and `_validate_and_pin` read `cls._egress_policy`; every call site (`http_fetch.py:308`, `:345`, `:558`, `:568`, `:571`, `:588`) still resolves; `_request_pinned` is static; the facades call the fetch agent's own methods and read the module-global `validate_and_pin_public_url`.
5. Each BF-945 log message begins `BF-945:` and names the host (`-` when the URL has none), never credentials, path or body; the fault line names the exception class, not its text; the refusal line names the floor's reason with a scheme's value dropped (`_reason_for_log`: of the nine reasons `vet_url` can return, eight carry the host, an address or fixed text; `urlparse` reads the `account` of a schemeless `account:pw@host/path` as a scheme). T1 pins `<verb> <host> (<reason or ExceptionName>)` per row and that `acct-9f3b` is absent.
6. P2-11 changes the value of `VERIFIED_URL` only; ES1, ES3 and ES4 pass unedited. At M1 every xfail case fails at an `assert` of its own body and the file collects on the unfixed tree; the assertions after T1's first failing one first run at G2.
7. `request_pinned` moves to the next address after `httpx.ConnectError` and `httpx.ConnectTimeout` only, raises the last address's error, and leaves `HttpFetchAgent._request_pinned` unchanged; T8 pins a connect error and a connect timeout moving on to the next address, every address failing ending the verification, and a read timeout and a write timeout not moving on.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **A URL the fetch agent refuses** (loopback, link-local metadata, private, reserved, a name that resolves to one, unresolvable, a scheme other than http and https): the verifier requests nothing, answers `verified=not claimed.success` and never "reachable"; a floor that raises requests nothing and leaves the claim unverified (T1).
- **A URL the floor approves:** requested at the approved address with the name as `Host` and SNI (the next approved address only after a connect that was refused or timed out, T8), no redirect followed, every old verdict unchanged (T2, T3, T4); the fetch agent's egress policy decides for the verifier as for the fetch agent (T6).
- **The chain:** a fetch the verifier cannot reproduce is not confirmed and records a failure outcome for the fetch agent; the control round verifies (T7).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
