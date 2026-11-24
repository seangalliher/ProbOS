# AD-1337 S4 (#1560): per-run values. A vault credential ProbOS hands a browser session or an MCP server is masked while that session or client lives, and not after

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-22

**Status:** draft. Batch 2 is S4 + S5: one PR (`Refs #1560`), one broad gate. S4 is built, tested and useful alone, but S5 (the decomposed DAG's reflect route) is the last slice, and #1560 closes with it. Decision: consult `4bb6d748` (Q1, Q2 source 3, Q7 row "per-run", Q8 M21; on #1560, comment 7064966284), corrected here in D1, D3 and D5. No Captain condition.

**Base:** `02ce03ec794d` (the merge commit of batch 1, PR #1846: its tree equals the tree of `a86a2895`, the tip of batch 1, that the canonical gate ran on; `src` there is the same as at `108a7fff`, whose line numbers this contract cites. Since `33826d30`, where the premises of section 0 were first measured, only `finalize.py` differs in `src`, and every `finalize.py` line cited below was read again on that tree). Line numbers are those of `108a7fff`, before S4's pairs, except where a line is marked as one of M1's result. The draft cited `693c685c`: between it and `108a7fff` (`git diff --name-only 693c685c 108a7fff -- src tests`) only `finalize.py` (six lines added at 735-748), `tests/test_ad1337_executor_seam.py` (nine lines added before line 498), `render_masking.py` and `tests/test_ad1337_render_seam.py` differ, so a line cited below is the same at both except in the first two files. From batch 1, S4 uses only:
- S1: `SecretRegistry`, `SecretHandle`, `SecretMasker`, `secret_label`, `secret_forms`;
- S2: `runtime.secret_masker`, `ToolExecutor(secret_masker=)`, `finalize._wire_secret_masker`;
- S3: `secret_masker_of`, `mask_route_result`.
- Pair C1 edits the three lines of `_wire_secret_masker` that create the registry (`finalize.py:724-726`). If batch 1's repairs change them, C1's SEARCH fails loudly, so no edit can land silently.

**Line endings:** every edited file is `i/lf w/crlf` (`git ls-files --eol`). The SEARCH blocks are LF; match and write each file with its own endings. The new test file is LF and ASCII only.

**Milestones** (one Builder delegation each; the Builder applies the pairs and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then A1, B1, C1, D1, E1 to E3, G1, H1 to H3, J1 to J3 (7.2 to 7.9) | HIGH, security control (vault values) | One full review by the GPT Diff Reviewer with section 14's properties. The mutation campaign of record (section 10) stands in for a second reviewer. If round 1 finds a Critical or High defect, the repair gets a full re-review. |
| M2 | TR1 to TR3, then the ledger (7.10 to 7.13) | LOW | Delta |

- Commit subjects:
  - M1: `Mask the vault values handed to a browser session or an MCP server while they are in use`
  - M2: `Record the per-run values in the status, decisions and research entries`
- About 30 Builder tool calls for M1 and 10 for M2.

## 0. Premises (on `33826d30`, re-read on `a86a2895`)

| P | Premise | Evidence |
|---|---|---|
| P1 | `action_fill_credential` reads the vault at `:356` and fills at `:373`. It holds the runtime: the `runtime` keyword (`:287`), which `BrowserTool` passes as `self._runtime` (`tool.py:934-939`), and finalize builds the tool with the runtime (`finalize.py:438-446`). Its result carries no value (`:391`). | `tools/browser/credentials.py:283-391` |
| P2 | A filled value can come back to a model. `state` returns a non-password input's value (`actions.py:280-289`, `:316-317`). `extract_text` returns page text (`:792-804`). `eval_js` returns script results (`:1088-1110`). | `tools/browser/actions.py` |
| P3 | Every session end runs `_finish_ending`, which waits for `record.idle` (`tool.py:524`) and then calls `close_resources` (`:528`). `stop()` ends every session (`:686-711`). A failed start calls `close_resources` (`session.py:201-209`). `_active_session` refuses any state other than ACTIVE (`tool.py:309-315`). | `tools/browser/tool.py`, `session.py` |
| P4 | A whole tool call is one session operation (`tool.py:816-820`). `_run_operation` sets `idle` in its `finally` (`:561-567`), before the task completes. So the end's waiter is scheduled before the caller resumes: a `close_resources` that releases first runs before the executor's producer seam. | `tools/browser/tool.py:552-572` |
| P5 | `resolve_secret_value` returns the static token or the bundle's `access_token` (`registration.py:49-96`). `register_record` hands it to `register_server` (a header) or to `register_stdio_server` (an environment variable), on the strict path (`:187-247`) and the legacy path (`:248-262`). | `integrations/mcp_bridge/registration.py` |
| P6 | Every way a client leaves the bridge closes it: `unregister_server` (`bridge.py:243-257`), `close_all` (`:276-285`), the dead stdio client's replacement (`:157-163`) and candidate cleanup (`:225-235`). `register_server` never replaces a client (`:69-76`). | `integrations/mcp_bridge/bridge.py` |
| P7 | An update or a refresh unregisters and then registers again (`_reregister`, `routers/mcp_servers.py:328-339`). `oauth_refresh` stores the new bundle first (`:756-783`). The refresh token goes to the provider's token endpoint (`:773`), never to the server. | `routers/mcp_servers.py` |
| P8 | **Order:** the boot loop calls `register_record` at `finalize.py:5149`. `_wire_secret_masker`, which assigns a new `SecretRegistry` (`:726`), runs at `:5898`. `ProbOSRuntime.__init__` builds no registry. | `startup/finalize.py`; `runtime.py:739-742` |
| P9 | `MCPClient.close` reads `_transport` with `getattr`, for clients built with `__new__` (`client.py:196-202`). The class has 13 methods; S4 adds `hold_secret` (14), and D9's `_masked_reply` is a module function. The architecture check flags more than 15 (`check_architecture_principles.py:188`; `:560-569` counts the class body's `def`s). `BrowserSession` and `BrowserTool` are recorded SRP debt (`architecture-baseline.yaml:957-974`). | |
| P10 | A non-strict `MCP_BRIDGE_FAILED` carries the server's rpc error message in `detail` (`client.py:251-261`, `:347-352`), and the event is durable (`test_ad1195_durable_producers.py:58-62`). | residual R14 |
| P16 | **No production path runs `action_fill_credential`** (numbered past the test cases P1 to P15; measured on `e12d0a4d`). Its one call is in `_invoke_session` (`tool.py:934`), whose one caller is `BrowserTool.invoke` (`:818`), after the gate that refuses every verb outside `_AGENT_ACTIONS` (`:791-803`). BF-701 keeps `fill_credential` off that tuple (`:98-106`, `:123-128`), and AD-1154 refuses it again in dispatch (`agentic_dispatch.py:253`, used at `:1267`, `:1448`). So S4's browser half is armed, not live: like the `upload_file` hook (R17), it guards the day the verb is opened (R22). The tests assert the refusal and run the handler on the tool's own session; every read goes through the real executor and tool. | `tools/browser/tool.py`, `cognitive/agentic_dispatch.py` |

## 1. Problem

S1 to S3 mask what the credential store and the environment know. A vault value that ProbOS hands to a tool is in neither:
- the password or API key `fill_credential` types into a page, which `state` reads back for a text field (P2). No agent can call that verb today (P16), so this half is armed for the day it is opened, not a live leak;
- the token in an MCP server's `Authorization` header or environment variable (P5), which a server can echo in a result.

`runtime.secret_registry` (S1) is the place for these values, but nothing registers in it. If registration were added as Q7 wrote it, servers registered at boot would still go unmasked (P8).

## 2. Overview

| Part | Change |
|---|---|
| `security/secret_masking.py` | `secret_registry_of(holder)` and `register_run_secret(holder, kind, key, value)` (name `kind:key` when that is a plain label, else `kind`) |
| `runtime.py` | `ProbOSRuntime.__init__` builds `self.secret_registry` |
| `startup/finalize.py` | `_wire_secret_masker` keeps a real registry it finds |
| `tools/browser/credentials.py` | `fill_credential` refuses a bridge (CDP) session before reading the vault (D10); otherwise it registers `vault:<ref>` before `page.fill` and hands the handle to the session |
| `tools/browser/session.py` | `hold_secret`, `holds_secrets`, `release_secrets`; `close_resources` releases |
| `tools/browser/tool.py` | While its session holds a value, the tool masks its own result inside the operation |
| `integrations/mcp_bridge/client.py` | `MCPClient.hold_secret` (with the runtime's masker getter); a client holding a value masks each reply in `_call` (`_masked_reply`) and drops one that returns after `close` began (D9); `close` releases in a `finally` |
| `integrations/mcp_bridge/registration.py` | `register_record` registers `mcp:<server>` and settles the handle, with a getter for the runtime's masker, on the client it published, or releases it |

**Heavier designs rejected:**
- A `secret=` keyword on `MCPBridge.register_server` and `register_stdio_server`: it changes the bridge's signature, and every bridge double in the tests (`_RecordingBridge`, `_FakeBridge`) would reject it.
- Registering inside `resolve_secret_value`: no owner exists there, so every call would leak.
- Releasing from the executor after its mask: the browser tool cannot see the executor.
- Deferring the MCP client's release until its reply has passed the producer seam: the client cannot see the seam, and every MCP route suspends after the reply (D9).
- Masking in `call_tool` and its siblings instead of `_call`: it misses the rpc message (D9) and needs one guard per method.
- A per-session registry or a deduplicating registry: S1's API is final, and each fill is a Captain-approved tier-3 action, so there are few handles.
- Masking every browser result inside the tool: S2's producer seam would then record no `SECRET_MASKED` for any browser hit (D5 limits that loss to sessions that hold a value).

## 3. Consumers checked

| Changed | Consumer | Result |
|---|---|---|
| `register_run_secret` returns None without a real registry or a value | AD-706f tests (`_Runtime` without a registry, `test_ad706f_credential_vault.py:242-258`); BF-745, AD-1215, AD-1017 and AD-1211 runtime doubles | Unchanged: nothing is registered, and `get_client` is never called |
| The legacy registration reads the value directly (J3) | BF-745 (`bridge.http` and `bridge.stdio` contents, one vault read), `test_ad1017_mcp_auth.py` (router helpers, unchanged) | The same headers, environment and number of vault reads (D4) |
| `_settle_secret` holds only a real `MCPClient` | Bridge doubles whose `get_client` returns `object()` (`test_bf745:84`, `test_ad1215:104`) | The handle is released and nothing raises |
| `MCPClient.close` gains a `finally` and sets `_closing`; `_call` masks a holding client's reply (D9) | AD-449 and AD-1014 close tests; AD-1241's and BF-875's `_call` use; AD-1236's strict registrations; clients built with `__new__` (P9) | Same behaviour for a client holding nothing: class defaults (`_held_secrets = ()`, `_masker_of = None`, `_closing = False`) keep the old path for a client built without `__init__` and for every client no registration handed a value |
| `_settle_secret(runtime, ...)` | Its two calls in `register_record` (`registration.py:272`, `:311` after M1) | Both pass `runtime` (J2, J3) |
| `fill_credential` refuses a connected session (D10) | AD-706f's sessions (a real `BrowserSession`, never connected, `test_ad706f_credential_vault.py:52-57`); no test fills a bridge session | Unchanged; only a bridge session is refused |
| The nested `operation` in `BrowserTool.invoke` | The AD-1343 census (`RECORDED` includes `invoke`), S3's N15 (every `invoke` call) | No new `invoke` call: the nested function calls `_invoke_session`, `secret_masker_of` and `mask_route_result` |
| `holds_secrets` is read only when a masker exists | Every `BrowserTool` test without a runtime (`test_ad706_browser_tool.py:142`) and MagicMock sessions | No attribute is read: `secret_masker_of(None)` is None |
| `ProbOSRuntime` gains `secret_registry` | BF-925 guard names (`getattr(holder, "secret_registry", None)`) | The name is defined in production (B1, and finalize `:726`) |
| `_wire_secret_masker` keeps a registry | S2's N16 to N19 (`SimpleNamespace` runtimes without one, `test_ad1337_executor_seam.py:507-550`) | Unchanged: they get a new one |
| Masked browser output | HXI (the Captain's ACK `routers/agent_actions.py:81`, session open), the DM tier-1 route (`reply_pipeline.py:1178`) | They see placeholders for a filled value while it is registered (consult risk "HXI") |
| `adoption.py:245` and config servers (`finalize.py:5094`, `:5100`) | Not vault values | Out of S4's scope: R18 |

**Not checked:** a real Chromium page, a real MCP server, the vessel.

## 4. Decisions

- **D1 (sites, names and lifetimes, (a)).** The census (P15) pins every vault read in `src`:

  | Read | Disposition |
  |---|---|
  | `credentials.py:356` `action_fill_credential` | **Registered** as `vault:<ref>` from before `page.fill` until the session closes. No production path runs it today (P16, R22) |
  | `registration.py:63` `resolve_secret_value`, through `register_record` | **Registered** as `mcp:<server>` from before the bridge call until the published client closes |
  | `resolve_auth_headers` / `resolve_auth_env` | They keep no client. Their only callers in `src` are the router's `_resolve_auth_headers` and `_resolve_auth_env`, which nothing in `src` calls (asserted); they are the AD-1017 tests' entry point |
  | `routers/mcp_servers.py:611` `_build_oauth_provider` | The OAuth client secret, which ProbOS sends to the token endpoint; never handed to a tool or a server |
  | `routers/mcp_servers.py:767` `oauth_refresh` | The bundle is read for its refresh token (token endpoint only); the new access token is registered by the re-registration (D4) |
  | `routers/cloud_pickers.py:135` `_read_bundle` | The Captain's picker token, used by the HXI router only (Do Not Build: the Captain's view) |
  | `keyring_backend.py:196`, `credentials.py:240` (`materialize_to_temp`) | Inside a vault: the value goes to the caller's tempfile |
  | `actions.py:1028` `_action_upload_file` | Unreachable. Nothing in `src` puts `_runtime` in params, and the positional call matches neither vault's keyword-only signature (both asserted). A fix that wires it must register (R17) |

  My grep adds the `materialize_to_temp` calls (`actions.py:1028` and the two vault internals) to the request's list.

  **Names:** the label is `kind:key` when it matches `[A-Za-z0-9_.:-]{1,64}` and the bare `kind` otherwise, so a long ref, or one holding spaces or user text, becomes `vault`. S1's D9 still turns a label whose placeholder holds a form of a known value into `unnamed`. The ref and the server name already appear in `CREDENTIAL_READ` and in the MCP events. No name holds a value.
- **D2 (owners and release points, (b)).**
  - *Browser.* The `BrowserSession` owns the handle. `fill_credential` registers, then calls `session.hold_secret(handle)` with no await in between, so no cancellation point leaves the handle unowned. `close_resources` releases it as its first step after `_terminated = True`, on every ending path: operator end, expiry, shutdown, a failed start, and a cleanup failure (the session is fenced and can no longer be read, P3). A fill that fails or is cancelled keeps the value registered until close, because the page may hold part of it. `hold_secret` on a closed session releases at once. `release_secrets` can be called again safely.
  - *MCP.* The `MCPClient` that the registration published owns the handle: the client under the key afterwards, identity-checked against the one there before, and only a real `MCPClient`. `close` releases after the transport closes, in a `finally`. While it holds the value the client masks its own replies, and it drops a reply that returns after `close` began (D9). A duplicate or reused key keeps its old client, which holds its own handle, and the new handle is released. A failed or cancelled registration publishes nothing, and `_settle_secret` (in a `finally`) releases. Unregister, update, refresh and a dead stdio client's replacement all close the old client.
- **D3 (reaching the registry, (c)).** Each site reads the registry from the runtime it already holds: `fill_credential`'s `runtime` keyword and `register_record`'s `runtime` argument. There is no new constructor argument or setter. `secret_registry_of` returns None for a runtime without a real registry (a bare test runtime, a `MagicMock`), and then nothing is registered and behaviour is unchanged. **Premise correction (P8):** `ProbOSRuntime.__init__` builds the registry and `_wire_secret_masker` keeps it, because the boot loop registers before finalize builds the masker.
- **D4 (refresh and the refresh token, (d)).** A refresh is "store the bundle, then `_reregister`" (P7): the old client closes, releasing the old access token, and the new client holds the new token. The refresh token and the client secret are never handed to a tool or a server (only ProbOS sends them to the token endpoint), so they are not registered. P9 pins this. The legacy path keeps its vault reads: none for `auth_kind == "none"` or a stdio server without `auth_env_var`, otherwise one.
- **D5 (the browser race, in addition to Q7's design).** Releasing at close alone leaks a read that the end overtakes (P4). So `BrowserTool.invoke` masks its own result inside the session's operation, but only when a masker exists and the session holds a value. The mask runs before `idle` is set, so it runs before the release. Such a hit logs a WARNING with labels (`route=browser_session`). The producer seam then finds nothing, so those hits record no `SECRET_MASKED` (R13). A session that holds nothing leaves its results to the producer seam (P6), so the event loss is limited to sessions that filled a value. D9 is its MCP twin.
- **D6 (failure, fact 6).** `register` raises only `TypeError` for a value that is not a `str`. Neither site can produce one: the vault decodes UTF-8, the access token is a pydantic `str`, and the strict path checks `isinstance(secret, str)`. If it were reached:
  - the fill fails closed: the exception leaves before `page.fill`, and `BrowserTool` turns it into an error result whose fixed text holds no value;
  - the strict MCP path returns False;
  - the legacy path raises, as a vault exception would.

  No value, form or position goes into any message.
- **D7 (bounds, fact 7).** Browser handles are bounded by Captain-approved fills on live sessions; MCP handles by live clients (one each, more only under concurrent registration of one key). Nothing registers per call without an owner. The release tests are P2 (normal end), P3 (end during a read), P4 (exception and cancellation), P7 (closed session), P8 (unregister), P9 (refresh), P10 (duplicate), P11 (stdio failure and cancellation), P14 (close failure) and P17 (a close that overtakes a reply).
- **D8 (census, (f)).** P15 is a new census of every vault read and every caller of the MCP credential resolvers, each with a reason (D1). It is AST-only, imports nothing, and cannot flake. S3's N15 and S2's construction census gain no row: S4 adds no route past the executor and no executor construction.
- **D9 (a close that overtakes an MCP reply; the Architect's class check on S4).** Every MCP route suspends between `bridge.invoke` and the producer seam: OPEN and CONFIRM await `_record_episode` (`agentic_dispatch.py:1851`, `:1877`); CONSENSUS awaits `event_log.log` and `_store_mcp_invoke_episode` (`runtime.py:5125`, `:5133`). A `close` during that await (an operator disable, update or refresh, a dead stdio client's replacement, shutdown) released the value before the seam masked the reply. A close whose `finally` runs before the calling task resumes with a line it has already read is the same defect. This is batch 1's class: the guard ended at a lifecycle event (`close`), not at the end of what it protects (the client's last reply reaching a model). Repair, by construction:
  - `_settle_secret` hands the client a getter for the runtime's masker, read at each reply, because the boot loop registers before finalize builds it (P8).
  - `_call` masks the reply itself, with no await since the transport returned. `_masked_reply` masks each top-level value of the envelope as the producer seam masks a tool's output, so `result` keeps the same depth and node bounds. It logs route `mcp_client` at WARNING with labels; a failed pass raises `MCPProtocolError(MASKING_FAILED_TEXT, reason="bad_result")`.
  - `close` sets `_closing` before its first await. A holding client's reply that returns after that raises `MCPProtocolError("client closed", reason="client_closed", delivery_state="sent_unconfirmed")`, so the broker keeps the outcome uncertain.
  - The rpc message is masked before `_emit_failed` puts it in `detail` (R14 narrows). The producer seam then records no `SECRET_MASKED` for these hits (R13). A client handed no value, or seeing no masker, takes the old path.
  - `MCPClient` keeps 14 methods. P17 pins both halves and the failed pass. R15 is not filed.
- **D10 (a bridge session's page outlives its release).** `_close_playwright` never closes a bridge session's page (the user's own tab, AD-1052b), and `_connect_impl` reuses the first page of the first context, so a later bridge session could read a filled field after the release. No release point inside ProbOS outlives that tab. `fill_credential` therefore refuses a connected session (`skipped_reason` `bridge_session`) before it reads the vault. `is_connected` is read with `getattr(..., False) is True`, as `page` is read there. No agent can call the verb today (P16), so no live path changes; this keeps the armed half true (R22). P18 pins it.

## 5. Tests: new file `tests/test_ad1337_per_run.py` (17 cases, 24 items)

| P | Case |
|---|---|
| P1 | `register_run_secret` and `secret_registry_of`: a real registry only; no value; label rule (`vault:login`, `vault` for a ref with a space and for a 70-character ref); `TypeError` for bytes; release |
| P2 | Browser: the executor refuses `fill_credential` (P16), so the handler fills on the tool's own session; the value is masked when `page.fill` runs; every read, through the real `ToolExecutor` and in the tool's own result, is masked; after `tool.stop()` it is not masked; no form of it in caplog (DEBUG), events or audit rows |
| P3 | An end that overtakes an in-flight read still leaves that read masked, and the end releases |
| P4 | A fill that raises or is cancelled keeps the value until `close_resources` (x2) |
| P5 | A runtime with no registry or a `MagicMock` registry fills and reads as before (x2) |
| P6 | A session holding nothing leaves its result to the producer seam (no `browser_session` WARNING) |
| P7 | A closed session releases a late registration at once; release can be repeated |
| P8 | MCP http: masked through the executor while the client lives; the wire still carries the token; unregister releases; no form in logs or events |
| P9 | A refresh masks the new access token and not the old, and never the refresh token |
| P10 | A duplicate key keeps the old client and releases the new value, legacy and strict (x2) |
| P11 | stdio: published (held, unregister releases), raises (legacy), raises (strict), cancelled; registered before the hand-over (x4) |
| P12 | A server handed no credential (stdio without `auth_env_var`, http `none`): no vault read, nothing registered (x2) |
| P13 | `ProbOSRuntime` has a registry; `_wire_secret_masker` keeps a registry holding a boot registration |
| P14 | A client whose close fails still releases; a client built with `__new__` closes |
| P15 | Census: every vault read registers its value or has a recorded reason |
| P17 | MCP (D9): a reply read before its client closes stays masked when the route suspends past the close (route `mcp_client`); a reply still on the wire when close begins is dropped (`client_closed`); a failed pass withholds (`bad_result`) |
| P18 | A bridge (CDP) session is refused before the vault is read: nothing filled, nothing registered (D10) |

- **On `02ce03ec794d`:** collection error `ImportError: cannot import name 'register_run_secret' from 'probos.security.secret_masking'`.
- **After M1:** 24 passed. P16 is section 0's premise, so the new cases are P17 and P18, one item each; on the S4 tree without D9 and D10, P17 fails at its first `result.output` assertion and P18 at `outcome`. The draft's helper sent `fill_credential` through the executor, which refuses it (P16): 4 failed and 18 passed on the orchestrator's oracle tree. The helper now asserts that refusal and runs the handler on the tool's own session; the four tests keep their names.

## 6. What S4 leaves for S5

- Nothing in the code: S5 masks the DAG reflect and arbitration prompts with the runtime's masker (finalize assigns it to `IntentDecomposer.secret_masker`, and the arbitration reads `runtime.secret_masker`), and per-run values are already in the registry the masker reads.
- S5 pins its two prompts in a census of its own, rewrites one reason in S3's N15 table (its K14), carries the landing comment's closing paragraph for #1560 (section 8.1 is S4's paragraph of it) and is the last slice of batch 2.

## 7. The contract

### 7.1 New file `tests/test_ad1337_per_run.py` (M1, written first)

```python
"""AD-1337 S4 (#1560): per-run secret values.

A vault credential ProbOS hands a browser session (``fill_credential``) or an MCP server (its auth header or its
environment variable) is registered in ``runtime.secret_registry`` from just before it is handed over until that
session closes or that client is closed: a tool that echoes it back is masked, and afterwards it is not.

Proves, with the real BrowserTool (test_ad706's fake Playwright page), a real BrowserSession, a real
EncryptedFileCredentialVault, the real MCPBridge, MCPClient and HttpTransport (only the httpx client inside it is
replaced, as AD-449's tests replace it), the real ToolExecutor and S1's real masker:
- P1: register_run_secret and secret_registry_of;
- P2-P7: the browser: masked from before the fill, through the executor and in the tool's own result, until the
  session ends; a read the end overtakes; a failed or cancelled fill; no registry; a session holding nothing; a
  closed session;
- P8-P12: MCP: masked while its client lives; a refresh; a duplicate key; a stdio registration that publishes,
  fails or is cancelled; a server handed no credential;
- P13: the registry exists before the boot loop registers MCP servers, and finalize keeps it;
- P14: a client whose close fails still releases;
- P15: every vault read registers its value or has a recorded reason;
- P17: an MCP reply read before its client closes stays masked when the route suspends past the close, and a reply
  still on the wire when close begins is dropped;
- P18: a bridge (CDP) session is never filled with a vault value.
P2, P4, P8 and P17 assert that no form of a value reaches a log record (DEBUG), an event payload or an audit row.
Does not prove: a real Chromium page, a real MCP server, a live vessel, or an agent's fill: no agent can call
fill_credential today (contract premise P16), so the helper asserts the refusal and runs the handler on the tool's
own session.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import BrowserToolConfig, SystemConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError, _masked_reply
from probos.integrations.mcp_bridge.registration import register_record
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.store import McpServerRecord
from probos.routers.mcp_servers import _reregister
from probos.runtime import ProbOSRuntime
from probos.security.audit import AuditLog
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    MaskedResult,
    SecretMasker,
    SecretRegistry,
    register_run_secret,
    secret_forms,
    secret_registry_of,
)
from probos.startup import finalize
from probos.tools.browser.credentials import CredentialScope, action_fill_credential
from probos.tools.browser.lifecycle import BrowserLifecycleState
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolResult
from tests.fixtures import ad1343_seam_census as seam_census
from tests.test_ad1337_executor_seam import _EchoTool, _registry
from tests.test_ad1337_secret_masking import _masker, _no_builtin_env, _store  # noqa: F401 -- _no_builtin_env is autouse
from tests.test_ad706_browser_tool import _FakePage, _make_session_factory
from tests.test_bf745_mcp_credentials_survive_restart import _vault

FILLED = "fill-S4k7Rq2Wx9Lm3"
MCP_TOKEN = "mcp-S4t8Jv1Nc6Pz4"
OLD_ACCESS = "acc-S4o2Fd5Gh8Jk1"
NEW_ACCESS = "acc-S4n3Ty6Ui9Op2"
REFRESH = "ref-S4r4Qw7Er1Ty5"
STORED = "sto-S4g5Bn8Mk2Xc7"
VALUES = (FILLED, MCP_TOKEN, OLD_ACCESS, NEW_ACCESS, REFRESH, STORED)
PAGE = "https://s4.example/login"
URL = "https://s4.example/mcp"
VAULT_LABEL = "<secret:vault:login>"
MCP_LABEL = "<secret:mcp:learn>"


def _clean(*texts: str) -> None:
    """No form of any test value (raw, escaped, URL- or base64-encoded) appears in ``texts``."""
    joined = "\n".join(texts)
    for value in VALUES:
        assert not [form for form in secret_forms(value) if form in joined], value[:4]


def _runtime(vault: Any, *, registry: SecretRegistry | None, masker: SecretMasker | None, **extra: Any) -> Any:
    runtime = SimpleNamespace(config=SystemConfig(), credential_vault=vault, secret_masker=masker, **extra)
    if registry is not None:
        runtime.secret_registry = registry
    return runtime


def _real(tmp_path: Path, entries: dict[str, str] | None = None) -> tuple[SecretRegistry, SecretMasker]:
    registry = SecretRegistry()
    return registry, _masker(_store(tmp_path / "store", entries or {}), registry=registry)


# -- P1: the helpers ------------------------------------------------------------------------------------------------


def test_register_run_secret_registers_under_a_plain_label_and_only_in_a_real_registry() -> None:
    registry = SecretRegistry()
    holder = SimpleNamespace(secret_registry=registry)
    assert secret_registry_of(holder) is registry
    assert secret_registry_of(SimpleNamespace()) is None
    assert secret_registry_of(SimpleNamespace(secret_registry=MagicMock())) is None
    assert register_run_secret(SimpleNamespace(), "vault", "login", FILLED) is None
    assert register_run_secret(SimpleNamespace(secret_registry=MagicMock()), "vault", "login", FILLED) is None
    assert register_run_secret(holder, "vault", "login", None) is None and registry.values() == ()
    handles = [register_run_secret(holder, "vault", key, FILLED) for key in ("login", "my login", "x" * 70)]
    assert [name for name, _ in registry.values()] == ["vault:login", "vault", "vault"]
    with pytest.raises(TypeError):
        register_run_secret(holder, "vault", "login", b"not text")  # type: ignore[arg-type]
    for handle in handles:
        assert handle is not None
        handle.release()
    assert registry.values() == ()


# -- P2 to P7: the browser --------------------------------------------------------------------------------------------


class _EchoPage(_FakePage):
    """test_ad706's fake page (it records each call and closes). Its text shows the value it was last filled with, as a
    page that reflects a submitted form value does, then ``shown``; ``fill_gate`` and ``read_gate`` hold a fill or a
    read open, ``fill_error`` makes the fill raise, and ``masked_at_fill`` is what the masker made of the value when
    ``fill`` ran."""

    def __init__(self, masker: SecretMasker | None) -> None:
        super().__init__(title="S4")
        self.masker = masker
        self.filled = ""
        self.shown = ""
        self.masked_at_fill = ""
        self.fill_error: BaseException | None = None
        self.fill_gate: asyncio.Event | None = None
        self.read_gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def fill(self, selector: str, text: str) -> None:
        if self.masker is not None:
            self.masked_at_fill = self.masker.mask_text(text).text
        self.entered.set()
        if self.fill_gate is not None:
            await self.fill_gate.wait()
        if self.fill_error is not None:
            raise self.fill_error
        self.filled = text
        await super().fill(selector, text)

    async def inner_text(self, selector: str) -> str:
        self.entered.set()
        if self.read_gate is not None:
            await self.read_gate.wait()
        return f"signed in with {self.filled}{self.shown}"


async def _vault_with_login(tmp_path: Path) -> Any:
    vault = _vault(tmp_path)
    await vault.store(ref="login", value=FILLED, scope=CredentialScope(
        allowed_agent_ids=frozenset({"a1"}), allowed_domains=frozenset({"s4.example"}),
    ))
    return vault


def _browser(runtime: Any, page: _EchoPage, events: list[tuple[Any, Any]], audit: AuditLog) -> BrowserTool:
    tool = BrowserTool(
        config=BrowserToolConfig(enabled=True, default_min_interval_seconds=0.0), audit_log=audit,
        emit_event=lambda event_type, data: events.append((event_type, data)), runtime=runtime,
    )
    tool._session_factory = _make_session_factory(page=page)  # test_ad706's seam: a BrowserSession with a fake start
    return tool


async def _open_and_fill(tool: BrowserTool, executor: ToolExecutor) -> str:
    nav = await tool.invoke({"action": "goto", "url": PAGE}, {"agent_id": "a1"})
    session_id = nav.metadata["session_id"]
    # Contract premise P16: no agent can call fill_credential (BF-701 keeps it off _AGENT_ACTIONS; AD-1154 refuses
    # it), so S4's fill is armed, not live. Pin that, then run the handler on the tool's own session as _invoke_session
    # would; every read that follows still goes through the real executor and tool. Opening the verb fails here (R22).
    refused = await executor.invoke("a1", "browser", {
        "action": "fill_credential", "session_id": session_id, "selector": "#key", "credential_ref": "login",
    })
    assert refused.error == "unknown browser action: 'fill_credential'", refused
    session = tool._sessions[session_id]  # noqa: SLF001 -- the tool's own session, as _invoke_session receives it
    params = {"selector": "#key", "credential_ref": "login", "agent_id": "a1"}
    filled = await action_fill_credential(session, params, runtime=tool._runtime, emit_event=None)  # noqa: SLF001
    assert filled == {"ok": True, "selector": "#key", "ref": "login"}, filled
    return session_id


async def test_a_filled_credential_is_masked_from_before_the_fill_until_its_session_ends(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    page, events, audit = _EchoPage(masker), [], AuditLog()
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, events, audit)
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    session_id = await _open_and_fill(tool, executor)

    assert page.filled == FILLED and page.masked_at_fill == VAULT_LABEL  # registered before page.fill ran
    assert registry.values() == (("vault:login", FILLED),)
    read = {"action": "extract_text", "session_id": session_id}
    expected = {"session_id": session_id, "text": f"signed in with {VAULT_LABEL}"}
    assert (await executor.invoke("a1", "browser", read)).output == expected
    assert (await tool.invoke(read, {"agent_id": "a1"})).output == expected  # the tool masks its own result
    assert "AD-1337: route=browser_session masked names=['vault:login']" in caplog.text

    await tool.stop()
    assert registry.values() == () and masker.mask_text(FILLED).text == FILLED
    _clean(caplog.text, json.dumps(events, default=str), json.dumps([entry.detail for entry in audit.entries]))


async def test_a_read_that_ending_the_session_overtakes_is_still_masked(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, [], AuditLog())
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    session_id = await _open_and_fill(tool, executor)
    page.entered.clear()
    page.read_gate = asyncio.Event()
    read = asyncio.create_task(executor.invoke("a1", "browser", {"action": "extract_text", "session_id": session_id}))
    await asyncio.wait_for(page.entered.wait(), 5.0)
    stop = asyncio.create_task(tool.stop())
    for _ in range(50):  # bounded: the end marks the session ENDING within a few loop passes
        await asyncio.sleep(0)
        if tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDING:
            break
    assert tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDING
    for _ in range(3):
        await asyncio.sleep(0)  # the end reaches its wait for the session's operations
    assert not read.done() and not stop.done() and registry.values()  # the end waits for the read
    page.read_gate.set()
    result, _ = await asyncio.gather(read, stop)
    assert result.output == {"session_id": session_id, "text": f"signed in with {VAULT_LABEL}"}
    assert registry.values() == ()


@pytest.mark.parametrize("ending", ["raises", "cancelled"])
async def test_a_failed_or_cancelled_fill_keeps_its_value_until_the_session_closes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, ending: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    session = BrowserSession(session_id="s4-p4", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session._page = page  # noqa: SLF001 -- test_ad706f's started session (test_ad706f_credential_vault.py:52-57)
    session.set_last_url(PAGE)
    runtime = _runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker)
    params = {"selector": "#key", "credential_ref": "login", "agent_id": "a1"}
    if ending == "raises":
        page.fill_error = RuntimeError("fill refused")
        outcome = await action_fill_credential(session, params, runtime=runtime, emit_event=None)
        assert outcome == {"ok": False, "skipped_reason": "fill_error"}
    else:
        page.fill_gate = asyncio.Event()
        fill = asyncio.create_task(action_fill_credential(session, params, runtime=runtime, emit_event=None))
        await asyncio.wait_for(page.entered.wait(), 5.0)
        fill.cancel()
        with pytest.raises(asyncio.CancelledError):
            await fill
    assert session.holds_secrets and masker.mask_text(FILLED).text == VAULT_LABEL  # the page may hold the value
    assert await session.close_resources() is True
    assert not session.holds_secrets and registry.values() == ()
    _clean(caplog.text)


@pytest.mark.parametrize("registry_attribute", ["absent", "mock"])
async def test_without_a_registry_a_fill_and_a_read_are_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, registry_attribute: str,
) -> None:
    extra = {"secret_registry": MagicMock()} if registry_attribute == "mock" else {}
    page = _EchoPage(None)
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=None, masker=None, **extra), page, [], AuditLog())
    session_id = await _open_and_fill(tool, ToolExecutor(registry=_registry(tool)))
    read = await tool.invoke({"action": "extract_text", "session_id": session_id}, {"agent_id": "a1"})
    assert page.filled == FILLED and read.output == {"session_id": session_id, "text": f"signed in with {FILLED}"}
    assert "route=browser_session" not in caplog.text
    await tool.stop()


async def test_a_session_holding_nothing_leaves_its_results_to_the_producer_seam(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    registry, masker = _real(tmp_path, {"github": STORED})
    page = _EchoPage(masker)
    page.shown = STORED
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, [], AuditLog())
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    nav = await tool.invoke({"action": "goto", "url": PAGE}, {"agent_id": "a1"})
    session_id = nav.metadata["session_id"]
    read = await executor.invoke("a1", "browser", {"action": "extract_text", "session_id": session_id})
    assert read.output == {"session_id": session_id, "text": "signed in with <secret:github>"}
    assert "route=browser_session" not in caplog.text and registry.values() == ()
    await tool.stop()


async def test_a_closed_session_releases_a_late_registration_at_once() -> None:
    registry = SecretRegistry()
    session = BrowserSession(session_id="s4-p7", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session.hold_secret(registry.register("vault:login", FILLED))
    assert session.holds_secrets
    session.release_secrets()
    session.release_secrets()  # repeatable
    assert not session.holds_secrets and registry.values() == ()
    assert await session.close_resources() is True
    session.hold_secret(registry.register("vault:login", FILLED))
    assert not session.holds_secrets and registry.values() == ()


async def test_a_bridge_session_is_never_filled_with_a_vault_value(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    session = BrowserSession(session_id="s4-p18", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session._page, session._connected = page, True  # noqa: SLF001 -- a bridge (connect_over_cdp) session, AD-1052b
    session.set_last_url(PAGE)
    outcome = await action_fill_credential(
        session, {"selector": "#key", "credential_ref": "login", "agent_id": "a1"},
        runtime=_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), emit_event=None,
    )
    assert outcome == {"ok": False, "skipped_reason": "bridge_session"}
    assert page.filled == "" and not page.entered.is_set()
    assert not session.holds_secrets and registry.values() == ()


# -- P8 to P12: MCP -------------------------------------------------------------------------------------------------


class _EchoHttp:
    """Stands for the httpx client inside the real HttpTransport (AD-449's tests replace the same attribute). It
    answers each request with a tool result quoting the Authorization header the transport sent, as a server that
    echoes its own credential does."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.closed = False

    async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
        self.seen.append(headers.get("Authorization", ""))
        body = {"jsonrpc": "2.0", "id": json.loads(content)["id"], "result": {
            "content": [{"type": "text", "text": f"server saw {headers.get('Authorization', '')}"}],
        }}
        return SimpleNamespace(
            status_code=200, headers={"content-type": "application/json"}, json=lambda: body, text=json.dumps(body),
        )

    async def aclose(self) -> None:
        self.closed = True


async def _echo(client: MCPClient) -> _EchoHttp:
    real, echo = client._http, _EchoHttp()  # noqa: SLF001 -- AD-1014's test shim (client.py:131-144)
    client._http = echo  # noqa: SLF001
    await real.aclose()
    return echo


class _BridgeTool(_EchoTool):
    """A registered tool whose body is the call ``_McpTool.invoke`` makes on its OPEN branch
    (agentic_dispatch.py:1695-1706): ``bridge.invoke(url, name, arguments)``, the answer returned as the output."""

    def __init__(self, bridge: MCPBridge, url: str) -> None:
        super().__init__("mcp_echo")
        self.bridge, self.url = bridge, url

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output=await self.bridge.invoke(self.url, "echo", {}))


class _NullTransport:
    """A stdio transport that never spawned: ``close`` counts, or fails as asked."""

    last_metadata: dict[str, str] = {}

    def __init__(self, close_error: BaseException | None = None) -> None:
        self.close_error = close_error
        self.closes = 0

    async def start(self) -> None:
        return None

    async def request(self, payload: dict[str, Any]) -> dict:
        raise AssertionError("no request is made in these cases")

    async def close(self) -> None:
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


class _StdioBridge(MCPBridge):
    """The real bridge (its client table, get_client, unregister_server, register_server) with the stdio spawn
    replaced: it records the environment it was handed, may wait on ``gate`` or raise ``error``, and publishes a real
    MCPClient over a transport that never spawned."""

    def __init__(self) -> None:
        super().__init__(stdio_enabled=True)
        self.envs: list[dict[str, str]] = []
        self.transports: list[_NullTransport] = []
        self.entered = asyncio.Event()
        self.gate: asyncio.Event | None = None
        self.error: BaseException | None = None

    async def register_stdio_server(
        self, name: str, command: str, args: list[str], env: dict[str, str], cwd: str,
        *, timeout: float | None = None, reuse_if_matching: bool = False,
    ) -> bool:
        self.envs.append(dict(env))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if name in self._clients:
            return False
        transport = _NullTransport()
        self.transports.append(transport)
        self._clients[name] = MCPClient(session=MCPSession(server_url=f"stdio:{name}"), transport=transport)
        return True


class _CountingVault:
    def __init__(self) -> None:
        self.reads = 0

    async def read(self, *, ref: str, requesting_agent_id: str) -> str:
        self.reads += 1
        return MCP_TOKEN


def _http_record(**changes: Any) -> McpServerRecord:
    fields: dict[str, Any] = dict(
        name="learn", type="http", url=URL, id="srv1", auth_kind="static", credential_ref="mcp:srv1", enabled=True,
    )
    fields.update(changes)
    return McpServerRecord(**fields)


def _stdio_record(**changes: Any) -> McpServerRecord:
    fields: dict[str, Any] = dict(
        name="local", type="stdio", command="python", args=["-m", "srv"], id="srv2", auth_kind="static",
        credential_ref="mcp:srv2", auth_env_var="API_KEY", enabled=True,
    )
    fields.update(changes)
    return McpServerRecord(**fields)


async def test_an_mcp_credential_is_masked_while_its_client_lives(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    events: list[tuple[Any, Any]] = []
    bridge = MCPBridge(emit_event=lambda event_type, data: events.append((event_type, data)))
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    await register_record(_runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge), _http_record())
    client = bridge.get_client(URL)
    assert isinstance(client, MCPClient) and registry.values() == (("mcp:learn", MCP_TOKEN),)
    echo = await _echo(client)
    executor = ToolExecutor(registry=_registry(_BridgeTool(bridge, URL)), secret_masker=masker)
    result = await executor.invoke("agent-1", "mcp_echo", {})
    assert result.output == {"content": [{"type": "text", "text": f"server saw Bearer {MCP_LABEL}"}]}
    assert echo.seen == [f"Bearer {MCP_TOKEN}"]  # the output is masked; the server still gets its credential
    assert await bridge.unregister_server(URL) is True
    assert echo.closed and registry.values() == () and masker.mask_text(MCP_TOKEN).text == MCP_TOKEN
    _clean(caplog.text, json.dumps(events, default=str))


async def test_a_refresh_masks_the_new_access_token_and_never_the_refresh_token(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    bridge = MCPBridge()
    vault = _vault(tmp_path)
    record = _http_record(auth_kind="oauth", credential_ref="mcp:oauth:srv1")

    async def _bundle(access: str) -> None:
        await vault.store(ref=record.credential_ref, value=json.dumps(
            {"access_token": access, "refresh_token": REFRESH, "token_type": "Bearer"},
        ), scope=CredentialScope())

    await _bundle(OLD_ACCESS)
    runtime = _runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge)
    await register_record(runtime, record)
    first = bridge.get_client(URL)
    assert masker.mask_text(OLD_ACCESS).text == MCP_LABEL
    await _bundle(NEW_ACCESS)  # what oauth_refresh stores before it re-registers (routers/mcp_servers.py:776-782)
    await _reregister(runtime, record)
    assert bridge.get_client(URL) is not first and registry.values() == (("mcp:learn", NEW_ACCESS),)
    assert masker.mask_text(OLD_ACCESS).text == OLD_ACCESS
    assert masker.mask_text(REFRESH).text == REFRESH  # never handed to the server
    assert await bridge.unregister_server(URL) is True and registry.values() == ()


@pytest.mark.parametrize("require_ready", [False, True])
async def test_a_duplicate_key_keeps_the_old_client_and_releases_the_new_value(
    tmp_path: Path, require_ready: bool,
) -> None:
    registry = SecretRegistry()
    bridge = MCPBridge()
    assert bridge.register_server(URL, headers={}) is True  # a config server registers first (finalize.py:5094)
    config_client = bridge.get_client(URL)
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    outcome = await register_record(
        _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge), _http_record(), require_ready=require_ready,
    )
    assert outcome is (False if require_ready else None)
    assert bridge.get_client(URL) is config_client and registry.values() == ()
    await bridge.unregister_server(URL)


@pytest.mark.parametrize("case", ["published", "raises", "raises_strict", "cancelled"])
async def test_a_stdio_registration_owns_its_value_only_once_it_publishes_a_client(tmp_path: Path, case: str) -> None:
    registry = SecretRegistry()
    bridge = _StdioBridge()
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv2", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge)
    if case == "published":
        await register_record(runtime, _stdio_record())
        assert bridge.envs == [{"API_KEY": MCP_TOKEN}] and registry.values() == (("mcp:local", MCP_TOKEN),)
        assert await bridge.unregister_server("local") is True
        assert [transport.closes for transport in bridge.transports] == [1]
    elif case == "cancelled":
        bridge.gate = asyncio.Event()
        task = asyncio.create_task(register_record(runtime, _stdio_record()))
        await asyncio.wait_for(bridge.entered.wait(), 5.0)
        assert registry.values() == (("mcp:local", MCP_TOKEN),)  # registered before it is handed over
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        bridge.error = RuntimeError("spawn refused")
        if case == "raises":
            with pytest.raises(RuntimeError):
                await register_record(runtime, _stdio_record())
        else:
            assert await register_record(runtime, _stdio_record(), require_ready=True) is False
        assert bridge.envs == [{"API_KEY": MCP_TOKEN}]
    assert registry.values() == () and bridge.get_client("local") is None


@pytest.mark.parametrize("kind", ["stdio_without_env_var", "http_none"])
async def test_a_server_handed_no_credential_reads_and_registers_nothing(kind: str) -> None:
    registry = SecretRegistry()
    bridge = _StdioBridge()
    vault = _CountingVault()
    record = _stdio_record(auth_env_var="") if kind == "stdio_without_env_var" else _http_record(
        auth_kind="none", credential_ref="",
    )
    await register_record(_runtime(vault, registry=registry, masker=None, mcp_bridge=bridge), record)
    assert vault.reads == 0 and registry.values() == ()
    if kind == "stdio_without_env_var":
        assert bridge.envs == [{}]
    key = record.url if record.type == "http" else record.name
    assert await bridge.unregister_server(key) is True


# -- P13 and P14: the registry at boot, and a failing close ----------------------------------------------------------


async def test_the_registry_exists_before_the_boot_loop_and_finalize_keeps_it(tmp_path: Path) -> None:
    assert isinstance(ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "vessel").secret_registry, SecretRegistry)
    registry = SecretRegistry()
    runtime = SimpleNamespace(credential_store=MagicMock(), secret_registry=registry)
    handle = register_run_secret(runtime, "mcp", "learn", MCP_TOKEN)  # as the boot loop registers (finalize.py:5149)
    assert finalize._wire_secret_masker(runtime=runtime) is None  # no real store: no masker, as S2 decided
    assert runtime.secret_registry is registry and registry.values() == (("mcp:learn", MCP_TOKEN),)
    assert _masker(_store(tmp_path / "store", {}), registry=runtime.secret_registry).mask_text(MCP_TOKEN).text == MCP_LABEL
    assert handle is not None
    handle.release()


async def test_a_client_releases_its_value_when_its_close_fails_and_a_bare_client_holds_none() -> None:
    registry = SecretRegistry()
    client = MCPClient(
        session=MCPSession(server_url="stdio:local"), transport=_NullTransport(close_error=RuntimeError("stuck")),
    )
    client.hold_secret(registry.register("mcp:local", MCP_TOKEN))
    with pytest.raises(RuntimeError):
        await client.close()
    assert registry.values() == ()
    await MCPClient.__new__(MCPClient).close()  # AD-1014's __new__ convention (client.py:199)


class _GatedEchoHttp(_EchoHttp):
    """``_EchoHttp`` holding each answer until ``gate`` is set: a reply still on the wire."""

    def __init__(self) -> None:
        super().__init__()
        self.entered, self.gate = asyncio.Event(), asyncio.Event()

    async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
        self.entered.set()
        await self.gate.wait()
        return await super().post(url, content=content, headers=headers)


class _SuspendingBridgeTool(_BridgeTool):
    """``_BridgeTool`` with the suspension the MCP tool's OPEN branch has between the reply and its return (its
    episode write, agentic_dispatch.py:1851): it waits on ``gate`` once the reply is in."""

    def __init__(self, bridge: MCPBridge, url: str) -> None:
        super().__init__(bridge, url)
        self.replied, self.gate = asyncio.Event(), asyncio.Event()

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        output = await self.bridge.invoke(self.url, "echo", {})
        self.replied.set()
        await self.gate.wait()
        return ToolResult(output=output)


async def test_a_reply_read_before_its_client_closes_stays_masked_and_one_after_is_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    events: list[tuple[Any, Any]] = []
    bridge = MCPBridge(emit_event=lambda event_type, data: events.append((event_type, data)))
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge)
    await register_record(runtime, _http_record())
    await _echo(bridge.get_client(URL))
    tool = _SuspendingBridgeTool(bridge, URL)
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    call = asyncio.create_task(executor.invoke("agent-1", "mcp_echo", {}))
    await asyncio.wait_for(tool.replied.wait(), 5.0)
    assert await bridge.unregister_server(URL) is True and registry.values() == ()
    tool.gate.set()
    result = await call
    assert result.output == {"content": [{"type": "text", "text": f"server saw Bearer {MCP_LABEL}"}]}
    assert "AD-1337: route=mcp_client masked names=['mcp:learn']" in caplog.text
    await register_record(runtime, _http_record())  # a reply still on the wire when close begins is dropped
    client = bridge.get_client(URL)
    real, gated = client._http, _GatedEchoHttp()  # noqa: SLF001 -- AD-1014's test shim (client.py:131-144)
    client._http = gated  # noqa: SLF001
    await real.aclose()
    pending = asyncio.create_task(bridge.invoke(URL, "echo", {}))
    await asyncio.wait_for(gated.entered.wait(), 5.0)
    assert await bridge.unregister_server(URL) is True and registry.values() == ()
    gated.gate.set()
    with pytest.raises(MCPProtocolError) as dropped:
        await pending
    assert dropped.value.reason == "client_closed" and gated.seen == [f"Bearer {MCP_TOKEN}"]
    failing = SimpleNamespace(
        mask_result=lambda result: MaskedResult(ToolResult(error=MASKING_FAILED_TEXT), frozenset(), True),
    )
    with pytest.raises(MCPProtocolError) as withheld:
        _masked_reply(failing, {"result": {"text": MCP_TOKEN}}, "r1")  # type: ignore[arg-type]
    assert (withheld.value.reason, str(withheld.value)) == ("bad_result", MASKING_FAILED_TEXT)
    _clean(caplog.text, json.dumps(events, default=str), str(dropped.value))


# -- P15: the census ------------------------------------------------------------------------------------------------

_RESOLVERS = frozenset({
    "resolve_secret_value", "resolve_auth_headers", "resolve_auth_env",
    "_shared_resolve_auth_headers", "_shared_resolve_auth_env", "_resolve_auth_headers", "_resolve_auth_env",
})

VAULT_READS: dict[tuple[str, str, str], str] = {
    ("src/probos/tools/browser/credentials.py", "action_fill_credential", "read"):
        "registered as vault:<ref> before page.fill, released at session close; no agent can call it (#1820 R22)",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_secret_value", "read"):
        "the MCP credential; register_record registers it and the client it publishes releases it (AD-1337 S4)",
    ("src/probos/integrations/mcp_bridge/registration.py", "register_record", "resolve_secret_value"):
        "registered as mcp:<server> on the strict and the legacy path",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_auth_headers", "resolve_secret_value"):
        "keeps no client; its only caller is the router's _resolve_auth_headers, which nothing in src calls",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_auth_env", "resolve_secret_value"):
        "keeps no client; its only caller is the router's _resolve_auth_env, which nothing in src calls",
    ("src/probos/routers/mcp_servers.py", "_resolve_auth_headers", "_shared_resolve_auth_headers"):
        "no caller in src (a call would appear in this census): the AD-1017 tests' entry",
    ("src/probos/routers/mcp_servers.py", "_resolve_auth_env", "_shared_resolve_auth_env"):
        "no caller in src (a call would appear in this census): the AD-1017 tests' entry",
    ("src/probos/routers/mcp_servers.py", "_build_oauth_provider", "read"):
        "the OAuth client secret, which ProbOS sends to the token endpoint; never handed to a tool or a server",
    ("src/probos/routers/mcp_servers.py", "oauth_refresh", "read"):
        "read for the refresh token (token endpoint only); the new access token is registered by the re-registration",
    ("src/probos/routers/cloud_pickers.py", "_read_bundle", "read"):
        "the Captain's cloud-picker token, used by the HXI router only (Do Not Build: the Captain's view)",
    ("src/probos/security/keyring_backend.py", "KeyringCredentialBackend.materialize_to_temp", "read"):
        "inside a vault: the value goes to the caller's tempfile",
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp", "read"):
        "inside a vault: the value goes to the caller's tempfile",
    ("src/probos/tools/browser/actions.py", "_action_upload_file", "materialize_to_temp"):
        "unreachable (asserted below); a change that wires it must register (#1820 ad-1337 R17)",
}


class _VaultReads(seam_census.Visitor):
    """AD-1343's scope-tracking census visitor, recording each vault read (a ``read`` passing ``requesting_agent_id``,
    which both vaults take keyword-only, or any ``materialize_to_temp``) and each call of an MCP credential resolver."""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name == "materialize_to_temp" or name in _RESOLVERS or (
            name == "read" and any(keyword.arg == "requesting_agent_id" for keyword in node.keywords)
        ):
            self.calls.append(seam_census.Call(self._rel, ".".join(self._scope) or "<module>", name, "", ""))
        self.generic_visit(node)


def test_every_vault_read_registers_its_value_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str]] = set()
    runtime_keys: list[str] = []
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        rel = path.relative_to(seam_census.ROOT).as_posix()
        tree = ast.parse(path.read_bytes())
        visitor = _VaultReads(rel)
        visitor.visit(tree)
        found |= {(call.file, call.function, call.callee) for call in visitor.calls}
        for node in ast.walk(tree):  # anything that could put a runtime under params["_runtime"]
            if isinstance(node, ast.Dict) and any(
                isinstance(key, ast.Constant) and key.value == "_runtime" for key in node.keys
            ):
                runtime_keys.append(rel)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and isinstance(
                node.slice, ast.Constant,
            ) and node.slice.value == "_runtime":
                runtime_keys.append(rel)
    assert found == set(VAULT_READS), sorted(found ^ set(VAULT_READS))
    assert runtime_keys == []
    upload = seam_census.function("src/probos/tools/browser/actions.py", "_action_upload_file")
    [hook] = [
        node for node in ast.walk(upload)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "materialize_to_temp"
    ]
    assert len(hook.args) == 1 and not hook.keywords  # positional, so it matches neither keyword-only signature
    for rel, qualname in (
        ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp"),
        ("src/probos/security/keyring_backend.py", "KeyringCredentialBackend.materialize_to_temp"),
    ):
        assert [arg.arg for arg in seam_census.function(rel, qualname).args.kwonlyargs] == ["ref", "requesting_agent_id"]
```

### 7.2 `src/probos/security/secret_masking.py` (M1)

**A1.** SEARCH:
```
class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```
REPLACE:
```
def secret_registry_of(holder: object) -> SecretRegistry | None:
    """AD-1337 S4: ``holder.secret_registry`` when it is a real ``SecretRegistry``, else None."""
    registry = getattr(holder, "secret_registry", None)
    return registry if isinstance(registry, SecretRegistry) else None


def register_run_secret(holder: object, kind: str, key: str, value: str | None) -> SecretHandle | None:
    """AD-1337 S4: register ``value``, which ProbOS is about to hand a tool for one session, in ``holder``'s registry.

    The caller hands the handle to the session's owner, which releases it when the session ends. Returns None, having
    registered nothing, when ``value`` is None or ``holder`` has no real registry (a bare runtime, a test double). The
    name is ``kind:key`` when that is a plain label, else ``kind``, so no placeholder or event carries other text.
    ``TypeError`` (from ``register``) for a ``value`` that is not a ``str``.
    """
    registry = secret_registry_of(holder)
    if value is None or registry is None:
        return None
    name = f"{kind}:{key}"
    return registry.register(name if secret_label(name) == name else kind, value)


class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```

### 7.3 `src/probos/runtime.py` (M1)

**B1.** SEARCH:
```
        # --- Credential Store (AD-395) ---
        self.credential_store = CredentialStore(
            config=self.config, event_log=self.event_log,
        )
```
REPLACE:
```
        # --- Credential Store (AD-395) ---
        self.credential_store = CredentialStore(
            config=self.config, event_log=self.event_log,
        )
        # AD-1337 S4: the per-run secret values (a vault credential handed to a browser session or an MCP server).
        # Built here, not in finalize: the boot loop registers stored MCP servers before finalize builds the masker,
        # and _wire_secret_masker keeps this registry.
        from probos.security.secret_masking import SecretRegistry

        self.secret_registry = SecretRegistry()
```

### 7.4 `src/probos/startup/finalize.py` (M1)

**C1.** SEARCH:
```
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry

    runtime.secret_registry = SecretRegistry()
```
REPLACE:
```
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry, secret_registry_of

    # AD-1337 S4: ProbOSRuntime builds the registry, because the boot loop registers stored MCP servers before this
    # runs; a runtime double without one gets one here.
    registry = secret_registry_of(runtime)
    runtime.secret_registry = registry if registry is not None else SecretRegistry()
```

### 7.5 `src/probos/tools/browser/credentials.py` (M1)

**D1.** SEARCH:
```
    value = await vault.read(ref=ref, requesting_agent_id=agent_id)
    if value is None:
        if emit_event is not None:
            try:
                emit_event(
                    EventType.CREDENTIAL_READ_DENIED,
                    {"ref": ref, "agent_id": agent_id, "reason": "scope_denied_or_expired"},
                )
            except Exception:
                logger.debug("AD-706f: emit_event(CREDENTIAL_READ_DENIED) failed", exc_info=True)
        return {"ok": False, "skipped_reason": "credential_denied"}

    page = getattr(session, "page", None)
    if page is None:
        return {"ok": False, "skipped_reason": "session_not_started"}

    try:
        await page.fill(selector, value)
```
REPLACE:
```
    # AD-1337 S4 (D10): a bridge session's page is the user's own tab. Closing the session leaves it open and a later
    # bridge session reuses it, so no release point outlives what the page can show: ProbOS fills no vault value
    # there and reads none for it. Read with getattr, as ``page`` is below.
    if getattr(session, "is_connected", False) is True:
        return {"ok": False, "skipped_reason": "bridge_session"}

    value = await vault.read(ref=ref, requesting_agent_id=agent_id)
    if value is None:
        if emit_event is not None:
            try:
                emit_event(
                    EventType.CREDENTIAL_READ_DENIED,
                    {"ref": ref, "agent_id": agent_id, "reason": "scope_denied_or_expired"},
                )
            except Exception:
                logger.debug("AD-706f: emit_event(CREDENTIAL_READ_DENIED) failed", exc_info=True)
        return {"ok": False, "skipped_reason": "credential_denied"}

    page = getattr(session, "page", None)
    if page is None:
        return {"ok": False, "skipped_reason": "session_not_started"}

    # AD-1337 S4 (#1560): the value is masked from now until the session closes, so a page that shows it (``state``
    # reads a text field's value) is masked wherever a tool result reaches a model. Registered before the fill and
    # handed to the session with no await between, so no exit path leaves it without an owner.
    from probos.security.secret_masking import register_run_secret

    handle = register_run_secret(runtime, "vault", ref, value)
    if handle is not None:
        session.hold_secret(handle)

    try:
        await page.fill(selector, value)
```

### 7.6 `src/probos/tools/browser/session.py` (M1)

**E1.** SEARCH:
```
if TYPE_CHECKING:
    from probos.config import BrowserToolConfig
```
REPLACE:
```
if TYPE_CHECKING:
    from probos.config import BrowserToolConfig
    from probos.security.secret_masking import SecretHandle
```

**E2.** SEARCH:
```
        self._terminated = False
        self._recording_failed = False
        self._recording_finished = False
```
REPLACE:
```
        self._terminated = False
        self._recording_failed = False
        self._recording_finished = False
        # AD-1337 S4: the registrations of the credentials filled into this session; released when it closes.
        self._secret_handles: list[SecretHandle] = []
```

**E3.** SEARCH:
```
    async def stop(self) -> None:
        """Attempt cleanup, retaining failed resources for a subsequent retry."""
        await self.close_resources()

    async def close_resources(self) -> bool:
        """Join protected cleanup; False means resources need a retry."""
        self._terminated = True
```
REPLACE:
```
    def hold_secret(self, handle: SecretHandle) -> None:
        """AD-1337 S4: keep ``handle`` registered until this session closes; a closed session releases it at once."""
        if self._terminated:
            handle.release()
            return
        self._secret_handles.append(handle)

    @property
    def holds_secrets(self) -> bool:
        """AD-1337 S4: whether a value filled into this session is registered for masking."""
        return bool(self._secret_handles)

    def release_secrets(self) -> None:
        """AD-1337 S4: release every value this session holds; repeatable."""
        held, self._secret_handles = self._secret_handles, []
        for handle in held:
            handle.release()

    async def stop(self) -> None:
        """Attempt cleanup, retaining failed resources for a subsequent retry."""
        await self.close_resources()

    async def close_resources(self) -> bool:
        """Join protected cleanup; False means resources need a retry."""
        self._terminated = True
        # AD-1337 S4: an ended session is never read again, so its filled values stop being masked. The tool ends a
        # session only after its operations finish, and each operation masks its own result (BrowserTool.invoke).
        self.release_secrets()
```

### 7.7 `src/probos/tools/browser/tool.py` (M1)

**G1.** SEARCH:
```
            self._register_use(session.session_id)
            return await self._run_operation(
                session.session_id,
                lambda: self._invoke_session(params, context, session, t0, action, agent_id),
                allow_expired=newly_created,
            )
```
REPLACE:
```
            self._register_use(session.session_id)

            async def operation() -> ToolResult:
                from probos.security.secret_masking import mask_route_result, secret_masker_of

                result = await self._invoke_session(params, context, session, t0, action, agent_id)
                masker = secret_masker_of(self._runtime)
                if masker is None or not session.holds_secrets:
                    return result
                # AD-1337 S4: a session holding a filled credential masks its own result while this operation still
                # counts. Ending the session waits only for its operations and then releases the value, so a result
                # masked later, at the executor, could miss it.
                return mask_route_result(masker, result, route="browser_session")

            return await self._run_operation(session.session_id, operation, allow_expired=newly_created)
```

### 7.8 `src/probos/integrations/mcp_bridge/client.py` (M1)

**H1.** SEARCH:
```
if TYPE_CHECKING:
    from probos.execution.effect_types import ExternalEffectContext
    from probos.integrations.mcp_bridge.transport import Transport

logger = logging.getLogger(__name__)
```
REPLACE:
```
if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.execution.effect_types import ExternalEffectContext
    from probos.integrations.mcp_bridge.transport import Transport
    from probos.security.secret_masking import SecretHandle, SecretMasker

logger = logging.getLogger(__name__)


def _masked_reply(masker: SecretMasker | None, envelope: Any, request_id: str) -> Any:
    """AD-1337 S4 (D9): ``envelope`` with each top-level value masked as the producer seam masks a tool's output, so
    a reply's ``result`` has the same depth and node bounds here and there; ``envelope`` itself without a masker or
    when it is not a dict. A failed pass withholds the reply: ``MCPProtocolError`` with fixed text, no value."""
    if masker is None or not isinstance(envelope, dict):
        return envelope
    from probos.security.secret_masking import MASKING_FAILED_TEXT
    from probos.tools.protocol import ToolResult

    names: set[str] = set()
    masked: dict[Any, Any] = {}
    for key, value in envelope.items():
        outcome = masker.mask_result(ToolResult(output=value))
        if outcome.failed:
            raise MCPProtocolError(
                MASKING_FAILED_TEXT, reason="bad_result", delivery_state="sent_unconfirmed", request_id=request_id,
            )
        names |= outcome.names
        masked[key] = outcome.result.output
    if names:
        logger.warning("AD-1337: route=mcp_client masked names=%s", sorted(names))
    return masked
```

**H2.** SEARCH:
```
    async def close(self) -> None:
        # AD-1014: delegate teardown to the transport (HTTP closes the httpx
        # client; stdio closes stdin, terminates the subprocess, cancels the
        # stderr drain). Defensive getattr for __new__-bypass tests (convention #11).
        transport = getattr(self, "_transport", None)
        if transport is not None:
            await transport.close()
```
REPLACE:
```
    #: AD-1337 S4: the registrations of the credential this client sends (``registration.register_record``), released
    #: by ``close``. A class default, so a client built without ``__init__`` (convention #11) holds none.
    _held_secrets: tuple[SecretHandle, ...] = ()

    #: AD-1337 S4 (D9): where a client handed a value finds the runtime's masker, read at each reply (the boot loop
    #: registers before finalize builds it). None for a client that holds nothing, which keeps the old path.
    _masker_of: Callable[[], SecretMasker | None] | None = None
    #: AD-1337 S4 (D9): set by ``close`` before it awaits or releases anything.
    _closing: bool = False

    def hold_secret(
        self, handle: SecretHandle, masker_of: Callable[[], SecretMasker | None] | None = None,
    ) -> None:
        """AD-1337 S4: keep ``handle`` registered until this client is closed. With ``masker_of`` the client masks
        each reply itself (D9)."""
        self._held_secrets = (*self._held_secrets, handle)
        if masker_of is not None:
            self._masker_of = masker_of

    async def close(self) -> None:
        # AD-1014: delegate teardown to the transport (HTTP closes the httpx
        # client; stdio closes stdin, terminates the subprocess, cancels the
        # stderr drain). Defensive getattr for __new__-bypass tests (convention #11).
        transport = getattr(self, "_transport", None)
        # AD-1337 S4 (D9): before any await, so a reply that returns from here on is dropped, not passed on unmasked.
        self._closing = True
        try:
            if transport is not None:
                await transport.close()
        finally:
            # AD-1337 S4: once the transport is closed, or fails or is cancelled while closing, the credential it
            # sent is no longer masked; a second close finds nothing to release.
            held, self._held_secrets = self._held_secrets, ()
            for handle in held:
                handle.release()
```

**H3.** SEARCH:
```
            if effect_context is not None and not exc.request_id:
                exc.request_id = request_id
            raise

        if not isinstance(envelope, dict):
```
REPLACE:
```
            if effect_context is not None and not exc.request_id:
                exc.request_id = request_id
            raise

        # AD-1337 S4 (D9): a client handed a value masks its reply here, with no await since the transport returned:
        # every MCP route suspends between a reply and the producer seam (an episode write), and ``close`` releases
        # the value. ``close`` sets ``_closing`` before it awaits anything, so a reply that returns after it began is
        # dropped instead.
        masker_of = self._masker_of
        if masker_of is not None:
            if self._closing:
                raise MCPProtocolError(
                    "client closed", reason="client_closed",
                    delivery_state="sent_unconfirmed", request_id=request_id,
                )
            envelope = _masked_reply(masker_of(), envelope, request_id)

        if not isinstance(envelope, dict):
```

### 7.9 `src/probos/integrations/mcp_bridge/registration.py` (M1)

**J1.** SEARCH:
```
async def resolve_auth_headers(
    record: "McpServerRecord", runtime: Any
) -> dict[str, str]:
```
REPLACE:
```
def _registered_secret(
    runtime: Any, bridge: Any, record: McpServerRecord, key: str, value: str | None
) -> tuple[Any, Any]:
    """AD-1337 S4: register the credential this registration hands the server, as ``mcp:<name>``, and note the
    client already under ``key``. ``(None, None)`` when nothing is registered (no value, or no real registry)."""
    from probos.security.secret_masking import register_run_secret

    handle = register_run_secret(runtime, "mcp", record.name, value)
    if handle is None:
        return None, None
    try:
        return handle, bridge.get_client(key)
    except BaseException:
        handle.release()
        raise


def _settle_secret(runtime: Any, bridge: Any, key: str, before: Any, handle: Any) -> None:
    """AD-1337 S4: the client this registration published keeps ``handle`` until it is closed; otherwise it is released.

    Only a real ``MCPClient`` that is new under ``key`` can own it. A duplicate or reused key keeps its old client
    (which holds its own registration), and a failed or cancelled registration published nothing. The owner masks its
    own replies with the runtime's masker, read at each reply because the boot loop registers before finalize builds
    it (D9).
    """
    if handle is None:
        return
    from probos.integrations.mcp_bridge.client import MCPClient
    from probos.security.secret_masking import secret_masker_of

    client = bridge.get_client(key)
    if isinstance(client, MCPClient) and client is not before:
        client.hold_secret(handle, lambda: secret_masker_of(runtime))
    else:
        handle.release()


async def resolve_auth_headers(
    record: "McpServerRecord", runtime: Any
) -> dict[str, str]:
```

**J2.** SEARCH:
```
            auth_headers = _auth_headers(record, secret)
            auth_env = _auth_env(record, secret)
            key = record.url if record.type == "http" else record.name
            if record.type == "http":
                registered = bridge.register_server(
                    record.url, headers={**record.headers, **auth_headers},
                    reuse_if_matching=True,
                )
            else:
                registered = await bridge.register_stdio_server(
                    name=record.name,
                    command=record.command,
                    args=list(record.args),
                    env={**record.env, **auth_env},
                    cwd=record.cwd,
                    timeout=record.timeout_seconds,
                    reuse_if_matching=True,
                )
```
REPLACE:
```
            auth_headers = _auth_headers(record, secret)
            auth_env = _auth_env(record, secret)
            key = record.url if record.type == "http" else record.name
            handle, before = _registered_secret(runtime, bridge, record, key, secret)
            try:
                if record.type == "http":
                    registered = bridge.register_server(
                        record.url, headers={**record.headers, **auth_headers},
                        reuse_if_matching=True,
                    )
                else:
                    registered = await bridge.register_stdio_server(
                        name=record.name,
                        command=record.command,
                        args=list(record.args),
                        env={**record.env, **auth_env},
                        cwd=record.cwd,
                        timeout=record.timeout_seconds,
                        reuse_if_matching=True,
                    )
            finally:
                _settle_secret(runtime, bridge, key, before, handle)
```

**J3.** SEARCH:
```
    if record.type == "http":
        auth_headers = await resolve_auth_headers(record, runtime)
        bridge.register_server(
            record.url, headers={**record.headers, **auth_headers}
        )
        return
    auth_env = await resolve_auth_env(record, runtime)
    await bridge.register_stdio_server(
        name=record.name,
        command=record.command,
        args=list(record.args),
        env={**record.env, **auth_env},
        cwd=record.cwd,
        timeout=record.timeout_seconds,
    )
```
REPLACE:
```
    # AD-1337 S4: the value is read here, not through resolve_auth_headers or resolve_auth_env, so it can be
    # registered; the same records read the vault exactly as before (none, or stdio without auth_env_var: no read).
    value = None
    if record.auth_kind != "none" and (record.type == "http" or record.auth_env_var):
        value = await resolve_secret_value(record, runtime)
    key = record.url if record.type == "http" else record.name
    handle, before = _registered_secret(runtime, bridge, record, key, value)
    try:
        if record.type == "http":
            bridge.register_server(
                record.url, headers={**record.headers, **_auth_headers(record, value)}
            )
            return
        await bridge.register_stdio_server(
            name=record.name,
            command=record.command,
            args=list(record.args),
            env={**record.env, **_auth_env(record, value)},
            cwd=record.cwd,
            timeout=record.timeout_seconds,
        )
    finally:
        _settle_secret(runtime, bridge, key, before, handle)
```

### 7.10 `PROGRESS.md` (M2)

**TR1.** SEARCH (the whole line `:1`; it occurs once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1337 S4 (2026-11-22), #1560 -- per-run values: a vault credential ProbOS hands a browser session or an MCP server is masked while that session or client lives, and not after.** The MCP half is live. The browser half is armed, not live: no agent can call `fill_credential` today (BF-701, AD-1154), so it guards the day the verb is opened (#1820 ad-1337 R22). `register_run_secret` (`security/secret_masking.py`) registers it in `runtime.secret_registry` as `vault:<ref>` or `mcp:<server>` (a plain label, else the bare kind). `fill_credential` registers before `page.fill` and hands the handle to its `BrowserSession`, which releases it when it closes, on every ending path. While a session holds one, `BrowserTool.invoke` masks its own result inside the session's operation, because ending a session waits only for its operations and then releases. `register_record` registers the credential it puts in a header or an environment variable and hands the handle to the `MCPClient` it publishes, which releases it in `close` (unregister, update, refresh, a dead stdio client's replacement); a duplicate, a failed or a cancelled registration releases it at once. Such a client masks its own replies (route `mcp_client`), because every MCP route suspends between a reply and the producer seam (an episode write), and it drops a reply that returns after `close` began. `fill_credential` never fills a bridge (CDP) session, whose page outlives the session. `ProbOSRuntime` builds the registry, because the boot loop registers stored MCP servers before finalize builds the masker, and finalize keeps it. A refresh masks the new access token, not the old, and never the refresh token, which only ProbOS sends to the token endpoint. Measured by `tests/test_ad1337_per_run.py` (17 cases, 24 items): the executor refuses `fill_credential`; a value the handler fills on the tool's own session is masked from when `page.fill` runs until the session ends, on every read through the real executor and in the tool's own result; a read that the end overtakes stays masked; a failed or cancelled fill keeps its value until close; an MCP server's echoed header comes back as `<secret:mcp:learn>` while the wire still carries the token; unregister, refresh, a duplicate, a failure and a cancellation each release; a runtime with no registry behaves as before; no form of a value reaches a log, an event or an audit row; a reply read before its client closes stays masked across the route's suspension, and one still on the wire when close begins is dropped; a bridge session is refused before the vault is read; a census pins every vault read with its reason. Not measured: a real Chromium page, a real MCP server, a live run. Next: S5 (a decomposed DAG's reflect prompt), the last slice of batch 2; #1560 closes with it. Contract `prompts/ad-1337-s4-per-run-values.md`.
```

### 7.11 `DECISIONS.md` (M2)

**TR2.** SEARCH (the whole line; it occurs once and is S1's text, which no batch-1 repair touches):
```
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
```
REPLACE:
```markdown
- *Per-run values (S4).* `register_run_secret(holder, kind, key, value)` registers a value ProbOS is about to hand a tool for one session in `holder.secret_registry` (a real `SecretRegistry` only; otherwise nothing, so a bare runtime or a test double behaves as before), named `kind:key` when that is a plain label and `kind` otherwise. Two vault reads hand a value on: `fill_credential` (`vault:<ref>`) and `register_record` (`mcp:<server>`, the header or the stdio environment variable). Only the second is live. No agent can call `fill_credential` (BF-701 keeps it off the browser tool's agent verbs; AD-1154 refuses it in dispatch), so its registration and the session's hold are armed for the day the verb is opened, and a change that opens it keeps both (#1820 ad-1337 R22). A census gives every other vault read its reason: the Captain's HXI routers (the picker token, the OAuth client secret and the refresh exchange go to a provider's token endpoint, never to a tool), the two vaults' own `materialize_to_temp`, and `upload_file`'s `credential_ref` hook, which nothing can reach.
- *Owners and release (S4).* The `BrowserSession` owns a filled value's handle. It is registered before `page.fill` and handed over with no await between, and released when the session closes, on every ending path. Ending a session waits only for its operations and then releases, so a session that holds a value masks its own result inside the operation (`BrowserTool.invoke`, route `browser_session`, a WARNING with labels); without that, a read the end overtook reached the producer seam after the release. The `MCPClient` the registration published owns an MCP credential's handle (identity checked against the client already under the key) and releases it in `close`, after the transport, in a `finally`. Every MCP route suspends between a reply and the producer seam (an episode write), so the client masks its own replies while it holds the value (route `mcp_client`), and drops a reply that returns after `close` began. `fill_credential` refuses a bridge session: the user's tab outlives the session, so no release could follow what it shows. A duplicate or reused key, a failure and a cancellation release it at once. An update, a refresh and a dead stdio client's replacement close the old client, so the old token stops being masked. The refresh token is never handed to a server and is not registered.
- *Registry (S4).* `ProbOSRuntime.__init__` builds `runtime.secret_registry`, because the boot loop registers stored MCP servers before `_wire_secret_masker` runs; that function now keeps a real registry it finds. Bounded by live sessions and clients: each browser handle is one Captain-approved tier-3 fill.
- *Residual (S4).* #1820 items ad-1337 R13, R14, R16 to R18 and R22 (R15 is fixed in S4 by the client masking its own replies).
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
```

Batch 1's #1820 items end at R12 (R10 is not filed: its leak is already recorded on #1324), so S4's residuals are R13 to R18, the draft's R9 to R14 shifted by four. R15 is not filed: D9 fixes it. They are numbered so in TR2, in 8.3, in the census reason of the new test file (R17) and in section 13. S5 adds R19 to R21. S4's review adds R22 (the unreachable fill, P16), numbered after S5's so that S5's contract is unchanged; it appears in TR1, TR2, 8.1, 8.3, the census reason and section 13.

### 7.12 `docs/research/openhands-absorption.md` (M2)

**TR3.** SEARCH (part of line `:33`; it occurs once in the file):
```
Per-run values (S4) and a decomposed DAG's reflect prompt (S5) follow. |
```
REPLACE:
```
S4 masks the vault values ProbOS hands an MCP server while its client lives, and arms the same for a browser fill, which no agent can call today. A decomposed DAG's reflect prompt (S5) follows. |
```

### 7.13 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit any regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. Add no `roadmap.md` row (this is an AD).

## 8. Issue texts (post after batch 2 merges)

**8.1 #1560, S4's paragraph of the landing comment** (S5's contract adds its own and closes the issue):
> **AD-1337 S4 (per-run values; PR #...).** A vault credential ProbOS hands a tool for one session is registered in `runtime.secret_registry` from just before the hand-over until that session ends:
> - `fill_credential`'s value is `vault:<ref>`, owned by the browser session and released when it closes. This half is armed, not live: no agent can call the verb today (BF-701, AD-1154), so it closes no leak and guards the day the verb is opened (#1820 ad-1337 R22);
> - an MCP server's header or environment credential is `mcp:<server>`, owned by the client the registration published and released when it is closed (unregister, update, refresh).
>
> A page or a server that echoes the value is masked by the producer and render seams. A browser session that holds a value also masks its own result, because ending a session waits for its operations and then releases. An MCP client that holds a value masks its own replies, because every MCP route suspends between a reply and the producer seam, and drops a reply that returns after it began closing. `fill_credential` never fills a bridge (CDP) session, whose page outlives the session. The registry is built with the runtime, because the boot loop registers stored MCP servers before finalize builds the masker. The refresh token and the OAuth client secret only go to a token endpoint and are not registered. A census pins every vault read with its reason.

**8.2 #1557 (AD-1335):** nothing from S4.

**8.3 #1820:** add:
- **ad-1337 R13** (Low).
  - *Reach:* a browser session holding a filled value masks its own results (route `browser_session`); an MCP client holding a value masks its own replies (route `mcp_client`, S4 D9).
  - *Evidence:* S4 D5, P2.
  - *Gap:* those hits are logged at WARNING but record no `SECRET_MASKED`, because the producer seam then finds nothing.
- **ad-1337 R14** (Low; Medium before S4 D9).
  - *Reach:* an MCP server whose rpc error quotes its own `Authorization` header. A non-strict `MCP_BRIDGE_FAILED` carries the message in `detail` (`client.py:251-261`, `:347-352`; the spawn detail at `bridge.py:207`), and the event is durable (AD-1195).
  - *Evidence:* S4 P10 premise.
  - *Gap:* event payloads are not masked (the same class as R4's logs). A later event-log read by a model is masked only while the client lives. S4 D9 masks a value-holding client's reply before `_emit_failed` puts its rpc message in `detail`, so this remains for a client handed no per-run value (config-declared headers, R18).
- **ad-1337 R16** (Low).
  - *Reach:* a screenshot, or `verify`'s vision call, of a page showing a filled non-password field.
  - *Gap:* text masking cannot reach pixels.
- **ad-1337 R17** (Low).
  - *Reach:* `upload_file`'s `credential_ref` hook (`actions.py:1011-1029`) is unreachable today (S4 P15).
  - *Gap:* a change that wires it must register the value and, if `materialize_to_temp` returns text, release it.
- **ad-1337 R18** (Low).
  - *Reach:* header and environment values declared in `system.yaml` for an MCP server (`finalize.py:5094`, `:5100-5107`).
  - *Gap:* they are not vault values and are masked only when also in the environment or the store; this is the same class as R1 and joins its follow-up.
- **ad-1337 R22** (Low).
  - *Reach:* none today. `action_fill_credential` has one call, in `BrowserTool._invoke_session`, behind `invoke`'s gate, which refuses every verb outside `_AGENT_ACTIONS`. BF-701 keeps `fill_credential` off that tuple, and AD-1154 refuses it again in dispatch (`_NEVER_PARK_ACTIONS`).
  - *Evidence:* S4 P16. S4's tests assert the refusal and run the handler on the tool's own session.
  - *Gap:* S4's browser half (the `vault:<ref>` registration before `page.fill`, `BrowserSession.hold_secret` and the `browser_session` mask in `BrowserTool.invoke`) is armed but has never run from an agent's call. A change that opens the verb must keep the registration and the session hold, and must replace the S4 helper's direct handler call with the agent path. It must also keep S4 D10's refusal of a bridge session, whose page outlives the session.

## 9. What this does NOT change

- `ToolExecutor`, the render seam (`render_masking.py`), the agentic loop, `reply_pipeline`, `decomposer.py` (S5), `EventType`, the AD-1195 counts, `event_persistence.py`.
- `MCPBridge`'s methods and signatures, the router's auth helpers, `oauth_refresh`, the vault classes, `upload_file`.
- `agentic_dispatch.py` and `runtime.py` (their MCP routes keep their awaits; D9 masks in the client), the MCP transports, `MCPClient`'s public methods, `BrowserSession` (D10 only reads `is_connected`), and P15's census reasons.
- `architecture-baseline.yaml`, config and profiles, HXI, S2's and S3's censuses.
- S1's code: A1 only inserts two functions above `class SecretHandle`.

## 10. Mutation rows (one campaign on the M1 candidate; restore between rows)

| Row | Mutant (lines changed) | Killed by |
|---|---|---|
| M21 | `SecretHandle.release` body becomes `pass` (1) | P1, P2, P8 |
| U1 | `register_run_secret`: `if value is None or registry is None:` becomes `if True:` (1) | P1, P2, P8 |
| U2 | `register_run_secret`: `name if secret_label(name) == name else kind` becomes `name` (1) | P1 |
| U3 | `secret_registry_of`: `isinstance(registry, SecretRegistry)` becomes `registry is not None` (1) | P1 |
| U4 | runtime: delete `self.secret_registry = SecretRegistry()` (1) | P13 |
| U5 | finalize: `registry if registry is not None else SecretRegistry()` becomes `SecretRegistry()` (1) | P13 |
| U6 | credentials: `session.hold_secret(handle)` becomes `pass` (1) | P2, P4 |
| U7 | credentials: the registration (D1's `handle = ...` and its `if`, 3 lines) moved below the `page.fill` `try` (3 moved) | P2 (`masked_at_fill`), P4 |
| U8 | session: delete `self.release_secrets()` in `close_resources` (1) | P2, P3, P4 |
| U9 | session `hold_secret`: `if self._terminated:` becomes `if False:` (1) | P7 |
| U10 | session `release_secrets`: `handle.release()` becomes `pass` (1) | P2, P4, P7 |
| U11 | tool: `if masker is None or not session.holds_secrets:` becomes `if True:` (1) | P2 (the direct read), P3 |
| U12 | tool: the same line becomes `if masker is None:` (1) | P6 |
| U13 | `_settle_secret`: `client.hold_secret(handle, lambda: secret_masker_of(runtime))` becomes `handle.release()` (1) | P8, P9, P11 (published), P17 |
| U14 | `_settle_secret`: delete `and client is not before` (1) | P10 |
| U15 | `_settle_secret`: the else branch's `handle.release()` becomes `pass` (1) | P10, P11 (raises, cancelled) |
| U16 | `_registered_secret`: `return handle, bridge.get_client(key)` becomes `return handle, None` (1) | P10 |
| U17 | `MCPClient.close`: `handle.release()` becomes `pass` (1) | P8, P9, P11, P14 |
| U18 | `MCPClient.close`: the release moved out of the `finally`, after `await transport.close()` (4 lines re-indented) | P14 |
| U19 | legacy: `(record.type == "http" or record.auth_env_var)` becomes `True` (1) | P12 |
| U20 | `_call`: `if self._closing:` becomes `if False:` (1) | P17 (dropped) |
| U21 | `_call`: `envelope = _masked_reply(masker_of(), envelope, request_id)` becomes `pass` (1) | P17 (suspended route) |
| U22 | `close`: delete `self._closing = True` (1) | P17 (dropped) |
| U23 | `_settle_secret`: `client.hold_secret(handle, lambda: secret_masker_of(runtime))` becomes `client.hold_secret(handle)` (1) | P17 (both halves) |
| U24 | `_masked_reply`: `if outcome.failed:` becomes `if False:` (1) | P17 (withheld) |
| U25 | credentials: `if getattr(session, "is_connected", False) is True:` becomes `if False:` (1) | P18 |

- **Predicted equivalent:** none.
- **U11 and the order claim of P4:** if U11 survives P3, the claim that the end runs before the caller resumes is wrong; report it rather than drop the row (P2's direct read still kills U11).
- **sha256 rule:** record each edited file's sha256 on the candidate. If any file the Builder produces differs, rerun every row that mutates that file and every row killed by a case in `tests/test_ad1337_per_run.py`.

## 11. Verified Against Codebase (2026-11-22, `ob11b2` at `693c685c`)

```
read security/secret_masking.py:40-120, 203-300, 412-424
  116-118 secret_label; 203-210 secret_masker_of; 213-228 mask_route_result; 231-248 SecretHandle (A1 anchor 231-232, once)
  251-276 SecretRegistry.register raises TypeError only for non-str; 412-424 the masker labels registry names with secret_label
read startup/finalize.py:715-742   724-726 C1 SEARCH (once); 5079-5143 the MCP boot loop; rg "_wire_secret_masker\(" -> 715 (def), 5892 (call)
read runtime.py:739-742 (B1 SEARCH, once); rg "secret_registry" src/probos/runtime.py -> none
read tools/browser/credentials.py:207-391   283-289 runtime keyword; 356 read; 356-373 D1 SEARCH (once); 391 result
read tools/browser/tool.py:744-822, 908-989, 1000-1024, 519-572, 686-711, 309-315, 330-372, 1596-1632
  812-820 G1 SEARCH (once); 157,166 runtime; 934-939 fill dispatch; 1617 seed_confirmation_token
read tools/browser/session.py:8-36, 94-151, 193-209, 298-393, 638-656   33-34 E1; 149-151 E2; 298-304 E3 (each once)
read tools/browser/actions.py:280-321, 357-375, 792-804, 998-1046
read integrations/mcp_bridge/registration.py (whole, 263 lines)   99-101 J1; 214-231 J2; 248-262 J3 (each once)
read integrations/mcp_bridge/bridge.py:43-304; client.py:1-40, 74-357   21-25 H1; 196-202 H2; 233-237 H3 (each once)
read routers/mcp_servers.py:287-339, 604-624, 756-783; routers/cloud_pickers.py:120-141
read tests/test_ad706f_credential_vault.py:1-64, 236-263; tests/test_ad706_browser_tool.py:1-200
read tests/test_bf745_mcp_credentials_survive_restart.py:36-180; tests/test_ad1215_install_rung_mcp.py:80-139
read tests/test_ad1211_approval_fulfils_every_kind.py:325-389; tests/test_ad449_mcp_bridge.py:55-94
read tests/test_ad1337_secret_masking.py:1-102; tests/test_ad1337_executor_seam.py:101-145, 480-554
read tests/test_ad1337_render_seam.py:20-150, 185-195, 596-715; tests/fixtures/ad1343_seam_census.py:24-113
rg "requesting_agent_id\s*=|materialize_to_temp\(" src/probos -> the 13 lines behind P15's rows (and social_verification.py:513, a constructor keyword)
rg "def get_client" tests -> 10 doubles; rg "_session_factory = |class _\w*Session" tests -> every factory a BrowserSession subclass
rg "^SRP_MAX" scripts/check_architecture_principles.py -> 187 (500 lines), 188 (15 methods); MCPClient 13 defs
git ls-files --eol (the 11 edited files) -> i/lf w/crlf
D9 and D10 (the Architect's class check; ob11b2c at 108a7fff with S4 and S5 applied; that tree's lines unless HEAD):
read cognitive/agentic_dispatch.py:1825-1939   1841-1854, 1866-1880 bridge.invoke then await _record_episode
read runtime.py:5070-5153   5079 bridge.invoke; 5125 await event_log.log; 5133 await _store_mcp_invoke_episode
read integrations/mcp_bridge/client.py:28-301   33-45 _STRICT_FAILURE_REASONS (client_closed, bad_result); 220-301 _call
git show HEAD:client.py | grep -n -> 21 TYPE_CHECKING, 25 logger, 196 close, 204 _call, 234-237 H3 (anchor count 1)
rg "[^\x00-\x7F]" client.py -> 6, 237 (HEAD 221): no SEARCH may span HEAD 221, so H3 is its own pair
read integrations/mcp_bridge/bridge.py:55-294; transport.py:140-417 (stdout is read only inside request)
read tools/browser/session.py:190-440, 537-540   287-294 connect reuses pages[0]; 389-404 bridge close keeps the page
git show HEAD:credentials.py | grep -n -> 356 vault.read (count 1), 370, 373; non-ASCII only at 8, 14, 75, 155, 243
read tests/test_ad706f_credential_vault.py:48-57 (a real BrowserSession, never connected)
read scripts/check_architecture_principles.py:187-188, 540-569   560-564 count the class body's def and async def
read security/secret_masking.py:39, 47, 55, 89-95   ToolResult import, DEFAULT_MAX_DEPTH 32, MASKING_FAILED_TEXT, MaskedResult
```

## Absence Verified (2026-11-22)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No S4 name exists yet | `rg "register_run_secret\|secret_registry_of\|hold_secret\|holds_secrets\|release_secrets\|_held_secrets\|_settle_secret\|_registered_secret\|_secret_handles" -g "*.py"` | none (re-run on `33826d30`: exit 1; the draft's `test_ad1337_render_seam.py:694` was `open_browser_session`, which the pattern does not match) | yes |
| No test file of S4 | glob `tests/test_ad1337_*.py` | three batch-1 files | yes |
| `ProbOSRuntime` builds no registry | `rg "secret_registry" src/probos/runtime.py` | none | yes |
| Nothing puts `_runtime` in params | `rg "\[\s*[\"']_runtime[\"']\s*\]\|[\"']_runtime[\"']\s*:" src/probos` | none | yes (P15 asserts it) |
| The router auth wrappers have no caller in src | `rg "_resolve_auth_headers\(\|_resolve_auth_env\(" src` | their definitions (`mcp_servers.py:299`, `:306`) and the two `_shared_resolve_auth_*(` calls in their own bodies (`:303`, `:308`), which the pattern matches as a substring; no other line | yes (P15) |
| `close_all` has no production caller | `rg "close_all\(" src` | `bridge.py:30` (docstring), `:276` (def) | yes: MCP handles live until process exit at shutdown |
| Nothing in production runs `action_fill_credential` | `rg -n "action_fill_credential\(\|_invoke_session\(\|_NEVER_PARK_ACTIONS" src` (2026-11-22, `e12d0a4d`) | seven lines: `credentials.py:283` (def); `tool.py:934` (the call, in `_invoke_session`, whose def is `:824`), `:818` (its one caller, in `invoke`, after the gate at `:791`); `agentic_dispatch.py:253`, `:1267`, `:1448` (the refusal). Other `fill_credential` hits in `src`: the `actions.py` handler table, `action_approvals.py:13` (docstring), two config models (text) | yes (P16) |
| `MCP_BRIDGE_INVOKE` carries no header | read `client.py:287-322` | url, method, session id | yes |
| An unpublished stdio candidate's output reaches no model | `rg -n "stdout" src/probos/integrations/mcp_bridge` | `transport.py:280` (the pipe), `:318`, `:349-353` (read only inside `request`, by a caller holding the client); stderr goes to `logger.debug` (`:293-306`) | yes: releasing on a failed or cancelled registration is correct |
| No other holder or settler | `rg -n "_settle_secret\(\|\.hold_secret\(\|self\._closing\b" src` (after M1, on the oracle tree) | `registration.py:116` (def), `:131`, `:272`, `:311`; `credentials.py:385` (the session's); `client.py:248`, `:298` (S4's `_closing`, D9); `self._closing` elsewhere only in `federation/envelope.py`, `cognitive/elastic_team_store.py`, `cognitive/llm_client.py` (their own) | yes |
| No test fills a bridge session | `rg -n "action_fill_credential\(" tests` | `test_ad1337_per_run.py`; `test_ad706f_credential_vault.py:179`, `:203`, `:225`, `:248` (a real, unconnected session) | yes |
| No `bridge_session` reason exists yet | `rg -n "bridge_session" src` (2026-11-24, `a86a2895`, before S4's pairs) | only `connect_bridge_session` names (`tool.py:1178`, `:1184`, `:1186`, `:1333`; `browser_stream.py:203`) | yes |

## 12. Deterministic checks

- **Focused gate, `-n 0`:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on:
  - `tests/test_ad1337_per_run.py`, `tests/test_ad1337_executor_seam.py`, `tests/test_ad1337_render_seam.py`, `tests/test_ad1337_secret_masking.py`
  - `tests/test_ad706f_credential_vault.py`, `tests/test_ad706_browser_tool.py`, `tests/test_ad706a_browser_streaming.py`, `tests/test_ad706b_session_recording.py`, `tests/test_ad706c_1_browser_verify.py`, `tests/test_ad706c2_compute_use.py`, `tests/test_ad706e_action_vocab_v2.py`
  - `tests/test_ad1052a_browser_sessions.py`, `tests/test_ad1052b_browser_bridge.py`, `tests/test_ad1052c_browser_input_forward.py`, `tests/test_ad1153_browser_agentic_loop.py`, `tests/test_ad1154_approval_inbox.py`, `tests/test_ad1158_workstation_session_binding.py`, `tests/test_ad1161_captain_session.py`, `tests/test_browser_session_lifecycle.py`, `tests/test_bf695_playwright_host.py`, `tests/test_bf749_one_agent_one_browser.py`, `tests/test_bf822_browser_navigation_floor.py`, `tests/test_bf867_mouse_button_dispatch.py`, `tests/test_ad745_episode_anchor.py`, `tests/test_ad1346_admission_browser_egress.py`, `tests/test_ad1346_admission_egress_sinks.py`
  - `tests/test_ad449_mcp_bridge.py`, `tests/test_ad1014_stdio_mcp_transport.py`, `tests/test_ad1015_mcp_servers_api.py`, `tests/test_ad1017_mcp_auth.py`, `tests/test_ad1017a_mcp_device_code.py`, `tests/test_bf745_mcp_credentials_survive_restart.py`, `tests/test_ad1211_approval_fulfils_every_kind.py`, `tests/test_ad1215_install_rung_mcp.py`, `tests/test_ad1019b_router_access.py`, `tests/test_ad1019e_mcp_authoring.py`, `tests/test_bf754_mcp_callable_definitions.py`, `tests/test_bf759_mcp_content_delivery.py`, `tests/test_ad1241_mcp_offer_budget.py`, `tests/test_bf875_mcp_inbound_auth.py`
  - `tests/test_ad1343_seam_registry.py`, `tests/test_bf925_guard_names.py`, `tests/test_ad1195_durable_producers.py`, `tests/test_layer_boundaries.py`, `tests/test_ad1324_srp_layout.py`, `tests/test_ad1270b_architecture_fitness.py`, `tests/test_ad1184_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` exits 0.
- `rg -l "register_run_secret\(" src` finds only `security/secret_masking.py`, `tools/browser/credentials.py` and `integrations/mcp_bridge/registration.py`.
- `rg -n "_masked_reply\(|self\._closing" src/probos/integrations/mcp_bridge/client.py` finds the def, its one call in `_call`, `_closing` set in `close` and read in `_call`; `rg -n "\"bridge_session\"" src` finds only `tools/browser/credentials.py`.
- `git diff 02ce03ec794d -- src/probos/tools/executor.py src/probos/cognitive/ src/probos/events.py src/probos/event_persistence.py src/probos/integrations/mcp_bridge/bridge.py src/probos/routers/ docs/development/architecture-baseline.yaml tests/fixtures/` is empty.
- `git diff 02ce03ec794d -- src/probos/security/secret_masking.py` shows insertions only, all above `class SecretHandle:`.
- The new file is ASCII only.
- Broad gate, once for batch 2 (after S5): `scripts/run_test_gate.py --label ad-1337-1560-b2 --receipt logs/gates/ad-1337-1560-b2.receipt.json`.

## 13. Prior art and blind spots

- **Internal:** consult `4bb6d748` Q2 (source 3), Q7 and Q8; S1's `SecretRegistry`; S3's `mask_route_result` and route census (the shape of P15); AD-1343's census visitor (reused, not copied); AD-1014's `__new__` convention (the class defaults for `_held_secrets`, `_masker_of` and `_closing`); batch 1's S2 repair (consult `2188318e`: a guard ended by a lifecycle event rather than by what it protects), whose class the Architect then looked for in S4 (D9, D10).
- **External (one search):** GitHub's workflow-command docs say to register a value with `add-mask` before it is printed or used, and masking applies only to output after registration. Adopted: register before `page.fill` and before the bridge call. Adapted: Actions never unregisters within a job; S4 releases at session end, per #1560's acceptance. OpenHands' per-conversation secret registry (consult Q2) is the same shape. Reference projects checked on 2026-11-22: OpenHands was last reviewed 2026-10-15 and is not overdue; no overdue project in the table is relevant to this design.
- **Blind spots named:** the end-overtakes-read race (D5, fixed); the boot order (P8, fixed); event payloads (R14); a close that overtakes an MCP reply (D9, fixed; R15 is not filed); a bridge page that outlives its session (D10, fixed); pixels (R16); the dead upload hook (R17); the unreachable fill (P16, R22); config-declared MCP secrets (R18); HXI shows placeholders for a filled value while it is registered.

## 14. Diff Reviewer: properties to verify

1. Exactly two sites register: `fill_credential` (before `page.fill`) and `register_record` (before the bridge call, on both paths). Every other vault read has a true reason in P15. No S4 change opens `fill_credential` to an agent: `_AGENT_ACTIONS` and `_NEVER_PARK_ACTIONS` are unchanged, and the test helper asserts the executor's refusal (P16).
2. Every handle has exactly one owner on every exit path. The browser handle is handed to the session with no await in between, and the session releases it in `close_resources` on every ending path. The MCP handle is either held by the client this registration newly published (a real `MCPClient`, not the one there before) or released in a `finally`. `MCPClient.close` releases in a `finally`.
3. A browser result is never masked after its session's release: the tool masks inside the operation whenever a masker exists and the session holds a value. A session that holds nothing leaves its results to the producer seam.
4. With no real registry (`None`, absent, a `MagicMock`), nothing is registered, `get_client` and `holds_secrets` are not read, and behaviour, vault reads and the headers and environment handed over are unchanged.
5. No value, form or position reaches a log, an event payload, an exception message or an audit row. Names are `kind:key` only when that is a plain label.
6. `ProbOSRuntime` builds the registry, and `_wire_secret_masker` keeps a real one, so a boot registration is masked.
7. A refresh releases the old access token and registers the new one. The refresh token and the client secret are never registered.
8. `secret_masking.py` changes by insertion only, above `class SecretHandle`.
9. An MCP client handed a value masks each reply in `_call`, with no await between the transport's return and `_masked_reply`, while that value is registered. `close` sets `_closing` before its first await, and a reply that returns after that is dropped with fixed text (`client_closed`), never returned. A failed pass withholds the reply (`bad_result`). A client handed no value, or seeing no masker, takes the old path byte for byte.
10. `fill_credential` refuses a connected (bridge) session before it reads the vault, and nothing else in the fill changes.
11. A handle's release never comes before the end of the operation it protects: not on a cancel or an exception (the registration's `finally`; the session's hold before `page.fill`), not when a close overtakes a reply (the reply is masked before it leaves the client, or dropped), and not when what shows the value outlives its owner (a bridge page is never filled).

## 15. Acceptance

- [ ] Section 5's prediction holds: a collection error on `02ce03ec794d`, then 24 passed after M1. The focused gate is green.
- [ ] Mutation rows M21 and U1 to U25 are killed by the named cases.
- [ ] Section 12's `rg` and diff checks hold, and `check_architecture_principles.py --check` passes.
- [ ] TR1 to TR3 are applied, and the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-24, scratch worktrees detached at `a86a2895`, the tip of batch 1, whose tree is main's after the merge, with this contract's operations applied)

The 18 operations of section 7 (the new test file, the 14 source pairs and TR1 to TR3) were applied by `audit\contract_tools.py apply` (ASCII only) to scratch copies of that tree, so no run touched another's files: `ob11s4a` (the tests alone, then the source pairs; the focused runs), `ob11s4b` (the campaign, then the tracker pairs, the ledger and the tracker consumers) and `ob11s4base` (the pure tree, for red runs and the base comparisons). Results:

| R | Result |
|---|---|
| R1 | **The pairs.** `contract_tools.py list` finds the 18 operations, and every SEARCH occurs exactly once at its turn on `a86a2895` (A1 116 to 1,283 characters; B1 160 to 562; C1 140 to 413; D1 715 to 1,665; E1 65 to 125, E2 112 to 276, E3 304 to 1,287; G1 285 to 935; H1 190 to 1,485, H2 398 to 1,992, H3 171 to 919; J1 96 to 1,716, J2 816 to 1,069, J3 515 to 1,088; TR1 17 to 2,873, TR2 194 to 3,034, TR3 72 to 195). The eight source files change by **+233 -38** lines, the new test file has 746 lines, and the three trackers by +7 -1. The blob after each operation is in the `contract_tools.py checkpoints` table that the Builder briefs carry; the oracle's twelve files equal its final blobs (12 of 12), and the two copies are identical blob by blob. |
| R2 | **Red.** The new test file alone on the unchanged tree: `ImportError: cannot import name '_masked_reply' from 'probos.integrations.mcp_bridge.client'`, `Interrupted: 1 error during collection`, `1 error in 1.16s`. Section 5 predicts a collection error; the first of S4's names that the file imports is `_masked_reply` (`register_run_secret` comes later in the import list), so that is the message. |
| R3 | **Green.** With the source pairs: **24 passed** in 22.1 s (17 cases, 24 items, as section 5 predicts); under `-W error`: 24 passed in 15.7 s; the four AD-1337 files together (the new file, S1's 97, S2's 26, S3's 24): **171 passed** in 46.0 s. |
| R4 | **The campaign** (`audit\mutants_gen.py`, `audit\rows_ad1337s4b.py`; the new test file alone; each row changes one line, or the lines of a pair for U7 and U18, and restores the file before the next): the unmutated candidate ran 24 cases, all passed. **26 rows (M21, U1 to U25): killed 26, differs 0, survived 0, invalid 0**, and every named killer failed in every row. The extra failures beyond the named killers were: M21 13, U1 8, U6 1, U10 1, U15 1 and U17 1. The edited files' LF sha256 on the candidate: `secret_masking.py` `1e1a65ca...56e` (full value in `evidence-b11s4-campaign.txt`), `runtime.py` `3b3a606e...`, `finalize.py` `8c86c5ff...`, `credentials.py` `85de5b77...`, `session.py` `775c9d42...`, `tool.py` `d68376c5...`, `client.py` `880f80d8...`, `registration.py` `8cd78f50...` and the new test file `2f9bb6f9...`. If a file the Builder produces differs in blob from R1's, rerun the rows of that file. The copy was restored after the campaign (its nine files equal the oracle's). |
| R5 | **The focused gate of section 12** (52 files, `-n 0`, through the home-guard wrapper with an empty redirected home): **2122 passed, 3 skipped** with the default embedding mode (747 s) and **2122 passed, 3 skipped** with `PROBOS_EMBEDDINGS=local`, CI's mode (608 s). The three skips are the unchanged tree's: its 51 files that exist there give **2098 passed, 3 skipped** (689 s, `-rs`), the skipped being `tests/test_ad706_browser_tool.py:370` and `tests/test_browser_session_lifecycle.py:243` and `:302`, each "Requires real Playwright + Chromium (set PROBOS_PLAYWRIGHT_REAL=1)"; 2,098 and the 24 new cases make the 2,122. |
| R6 | **The static checks of section 12** on the oracle: `rg -l "register_run_secret\("` finds exactly `security/secret_masking.py`, `tools/browser/credentials.py` and `integrations/mcp_bridge/registration.py`; `_masked_reply` is defined at `client.py:31` and called once, in `_call` (`:303`), `_closing` is set in `close` (`:248`) and read in `_call` (`:298`); `"bridge_session"` appears only in `credentials.py:360`; `git diff a86a2895` over `executor.py`, `cognitive/`, `events.py`, `event_persistence.py`, `bridge.py`, `routers/`, the baseline and `tests/fixtures/` is **empty**; `secret_masking.py` has **21 insertions and 0 deletions**, one hunk at line 231, above `class SecretHandle` (now line 252); the new test file has no byte above 127. `check_architecture_principles.py --check` passes with `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, the same counts as the tree before S4 (`MCPClient` has 14 methods). |
| R7 | **M2.** TR1, TR2 and TR3 apply (one occurrence each). `gen_ad_ledger.py` wrote the ledger pair, `--check` reports "AD/BF ledger is current", and each file of the pair differs by three replaced lines: in the snapshot `captured_at`, `head` and `subject_count`, in the report the git-log row and two `PROGRESS.md` line numbers (the head-shaped lines that moved down by TR1's two added lines). The tests that read the trackers, the ledger or the research doc (`test_ad1184_ad_ledger.py`, `test_ad1250_detail_first_render_policy.py`, `test_ad1270f_codebase_index_memo.py`, `test_ad1346_identity_service_boot.py`, `test_ad689_edge_backfill.py`, `test_architect_agent.py`, `test_codebase_index.py`, `test_standing_orders_layout.py`) with `test_ad758_program_gate.py` and the new file: **256 passed** in 93 s. |
| R8 | **The premises and absences, read again on this tree.** Between `33826d30`, where section 0 was measured, and `a86a2895` only `src/probos/startup/finalize.py` differs in `src` (11 lines added, 5 removed, all inside `_wire_secret_masker`, at lines 736 to 748); the five `finalize.py` lines this contract cites hold there (`:438-446` the `BrowserTool(` build, `:715` the `def`, `:724-726` the registry lines that C1 replaces, `:5094` the config servers, `:5149` `register_record`). The absence rows of the section after section 11 were re-run: no S4 name in any `*.py` (exit 1); three AD-1337 test files; no `secret_registry` in `runtime.py`; no `_runtime` key in params; the router auth wrappers only at `mcp_servers.py:299, 303, 306, 308`; `close_all(` only at `bridge.py:30, 276`; the seven lines of P16 (`credentials.py:283`; `tool.py:818, 824, 934`; `agentic_dispatch.py:253, 1267, 1448`). One citation was wrong and is corrected in the section: the `bridge_session` row gave the line numbers of a tree with S4 applied (`tool.py:1187, 1193, 1195, 1342`); on the unchanged tree they are `tool.py:1178, 1184, 1186, 1333`. The `MCP_BRIDGE_INVOKE` row (`client.py:287-322`) and the transport rows (`transport.py:280, 318, 349-353`) hold. |
| R9 | **D9 and D10 are pinned and the pins discriminate.** D9 (a close that overtakes an MCP reply) is the case `test_a_reply_read_before_its_client_closes_stays_masked_and_one_after_is_dropped` (P17) and D10 (a bridge session is refused before the vault is read) is `test_a_bridge_session_is_never_filled_with_a_vault_value` (P18); rows U20 to U24 and U25 are killed by those cases and by no other named killer. P16 holds as measured in R8: the one call of `action_fill_credential` is behind the gate that refuses the verb, so the browser half is armed, not live (R22). |
| R10 | **Linux.** The Windows gate cannot see platform differences (batch 1's first CI run failed on one), so the test code of this contract was searched for the constructs that differ: a process spawn, `os.environ`, `HOME`, file modes, path separators, `read_text` without an encoding, signals, `sys.platform`, case-sensitive names, `subprocess`. Inside the contract's fenced blocks (the test file and the source pairs) the pattern finds only two `asyncio.sleep(0)` yields, the `materialize_to_temp` names of the AST census and two comments that mention a subprocess; the test file builds its vault and its credential store as real objects over `tmp_path`, uses doubles for the page, the transport and the runtime, and never starts a process or a real runtime. That is a reading, not a Linux run: the pull request's CI is the only one. |

**What the orchestrator changed in the Architect's section 7, 10 and 14:** nothing in the pairs, the test file, the rows or the properties. Three remarks on the surrounding text. (1) The header's base sentence and the heading of section 0 name the merge commit and the tip that merged (`a86a2895`), and say what was re-read on it (R8); batch 1's tip was `108a7fff` when this contract was drafted. (2) The `bridge_session` line numbers (R8). (3) Section 5 says "a collection error" and R2 names the first missing import.

**What these checks do not show.**
- A real Chromium page, a real MCP server and any live run: the file uses doubles for the page, the transport and the vault.
- Linux (R10), the broad gate of batch 2 (S5 is not built yet) and the HXI.
