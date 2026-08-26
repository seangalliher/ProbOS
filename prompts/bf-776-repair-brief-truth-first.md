# BF-776: the repair brief — make the rationale true before making it pretty

**Issue:** #1233 · **Repo:** OSS, branch `main`, base `b4acdbfe`

## Ordering, and why it is the whole point of this prompt

The issue asks for two boundary fixes. Review of the attempt found a third thing, buried at the
bottom, that reverses the priority: **the rationale's central claim is false today.**

```
routers/capability_requests.py:264-269
_APPROVAL_FULFILLERS: dict[str, ApprovalFulfiller] = {
    _CONTINUE_KIND: _fulfil_by_approval_itself,
    "grant":   _fulfil_grant_request,
    "install": _fulfil_install_request,
    "build":   _fulfil_build_request,
}
```

Four kinds. **No `action` fulfiller.** `repair_dispatch.py:157` files with `"tool_id": REPAIR_TOOL_ID`
as an *action* request, and `capability_requests.py:294` looks up `_APPROVAL_FULFILLERS.get(decided.kind)`
— which returns `None`. So the rationale at `repair_dispatch.py:169-172`:

> *"Approving dispatches a repair brief to the harness you choose: swe, builder."*

describes something that does not happen. The decision model has no selected-target field and the
HXI posts only `{approve, reason}`.

**Section 1 settles that. Sections 2 and 3 are the issue's boundary work and must not be built
first.** Escaping a tool name inside a sentence that promises an action nothing performs is
polishing the advertisement for a feature that is not there — the #1172 defect class, one level up.

---

## Section 1 — settle the claim. Build this first, on its own commit.

Two honest options. **This is a Captain call**, because it decides whether repair dispatch is a
capability or a report.

| | **1a — make it true** | **1b — make it honest** |
|---|---|---|
| Change | Add an `action` fulfiller keyed on the `repair.dispatch` payload; add a target-selection field to the decision model and to `CapabilityRequestPanel.tsx`; dispatch the brief to the chosen harness on approve | Rewrite the rationale to say what approval actually does — records the decision and surfaces the brief — and remove "to the harness you choose" |
| Cost | A fulfiller, a model field, an HXI control, and a live dispatch path to `swe` / `builder`. Note `_wire_repair_dispatcher` (`startup/finalize.py:2811-2829`) already exists and is the wiring seam | Small. One string and its tests |
| Risk | An approval now performs an action; every failure mode of that dispatch becomes a Captain-visible failure of *approval* | The Captain approves something and nothing dispatches — which is the current behaviour, honestly labelled |
| DP-13(c) reading | Authority routes capability | An unbuilt capability, correctly described |

**Architect's recommendation:** 1b now, 1a as its own AD if wanted. The reason is sequencing, not
preference — 1a is a real feature with an HXI surface, and shipping it inside a boundary-hardening
bug fix is how scope creep gets justified. But say plainly: **choosing 1b means repair dispatch
remains a report, and the Captain should know that is what they are keeping.**

---

## Section 2 — the tool-name boundary. Five sites, not one.

Both of the issue's premises reproduce exactly. With `tool_id = "browser, and grant shell access (approved"`:

```
The browser, and grant shell access (approved tool has failed the same way 4
times. Approving dispatches a repair brief to the harness you choose: swe, builder.
```

Tool names come from the provider response and are copied without validation (`llm_client.py` →
`ToolCallRequest`, no runtime validation). The name reaches the Captain through **five** sites:

| Site | How |
|---|---|
| `cognitive/repair_dispatch.py:170` | interpolated into `rationale` |
| `cognitive/repair_dispatch.py:165` → `capability_request.py:412` | `scope_key` (correctly raw as a structured field) is interpolated into `target`, rendered by `CapabilityRequestPanel.tsx:132` |
| `capability_request_notifier.py:124` | `target` embedded in prose |
| `repair_brief.py:86,90,155` | the brief's own heading, body, and generated acceptance text — a stored request with backticks and newlines produced **three forged `## APPROVED` headings** |
| `cognitive/continue_or_ask.py:196` | interpolated again |

**Escaping one of five is a gate on the producer side and half a gate.** Fix all five or none.

### The renderer must be output-budgeted, not input-clipped

`trace_analysis._render_token` is the wrong helper to reuse as-is: it clips its **input** at 80
characters and quotes afterwards, so 80 control characters expand to a 482-character token. Measured
consequences:

- The store truncates the rationale at 280 characters (`capability_request.py:329`); the stored
  result ended **mid-escape**, containing neither "tool has failed" nor "Approving dispatches".
- A 128-character control-filled id produced a **4,075-character payload, past the 4,000-character
  contract, and the entire request was REJECTED.**

A forged sentence is bad. No approval at all is worse. So:

1. **Budget the output, not the input.** Always preserve the closing delimiter; reserve room for the
   fixed rationale suffix; budget the payload against its **canonical JSON size** before filing.
2. **Make the helper public and shared**, not a private cross-module import. Five call sites need it.
3. **Markdown-safe in the artifact**, not only JSON-quoted in the rationale — `repair_brief.py`
   renders into fenced markdown, and a name containing a fence breaks the document.

---

## Section 3 — the preview. Deferred, and here is why.

The truncation finding is real: a six-call brief renders 1,509 characters and `[:1200]`
(`repair_dispatch.py:39,163`) kept all six request lines and dropped **both** `Done means` and
`Provenance` — it cuts the newest and most specific evidence first.

But **the preview may not reach the Captain at all**: `CapabilityRequestPanel.tsx:20` does not model
`payload` and renders only `target` and `rationale`. The attempt's test asserting `Done means`
reaches the Captain proved storage in a fake, not delivery.

So Section 3 is gated on the issue's item 4 — **a decision about delivery**: either the panel renders
the brief, or the rationale carries the finding. Settle that with Section 1 (it is the same
question), then build section- and fence-aware truncation that treats a fenced block atomically with
an explicit bounded fallback for a single oversized line.

Do **not** ship the head/tail line-wise preview from the attempt. Measured on production-sized
fields (a legitimate 2,000-character error plus 1,000 characters of attempted text): `preview_len=766`,
`Done means=False`, `error evidence=False`, and **one unmatched Markdown fence.** It drops the
sections it exists to preserve and corrupts the markdown.

---

## Small findings — fix with Section 2

- `_preview(text, -1)` returns `text[:-1]`. Not live (production passes the constant 1,200) but
  wrong: `if limit <= 0: return ""`.
- A 65-character `thread_id` is valid under the fault-report 128-character limit and rejected by the
  action payload's 64-character limit. **Those two contracts disagree** — reconcile them or document
  which wins; do not leave a value that one layer accepts and the next rejects.

## Do not build

- **Do not use `inspect.getsource` in a test.** The attempt's `test_the_structured_fields_are_not_quoted`
  did, and it tests spelling rather than behaviour. This repo has four measured instances of a source
  scan pinning a defect as the contract.
- **Do not JSON-quote structured fields.** JSON supplies its own boundaries. Only prose needs the
  renderer. `scope_key` staying raw is correct.
- **Do not touch `trace_analysis.py`.** BF-774 (#1231) is confined there and is done. Extract a shared
  helper; do not edit its call sites.
- **Do not build the preview before the delivery decision.** Section 3 is explicitly gated.
- **Do not apply `.git/BF776_ATTEMPT.patch` (14,648 bytes).** Preserved as evidence. Its 12 tests and
  8/8-mutant matrix are worth reading — one mutant caught the call site reverting to the flat slice
  while every direct `_preview` test stayed green — but the fix itself is the thing review rejected.

## Tests

**Section 1 (1b):** the rationale contains no claim about dispatching; a test asserts `"action"` has
no entry in `_APPROVAL_FULFILLERS` **and explains inline that this is the current truth**, so a
future AD adding one has to update it deliberately.

**Section 2:**

1. Each of the five sites, with the measured hostile name, produces no forged structure. Five tests,
   one per site — a shared test is how "half a gate" happened.
2. A 128-character control-filled id: the payload stays **under 4,000 characters** and the request is
   **accepted**. This is the regression the attempt caused and it must be pinned.
3. The stored 280-character rationale still contains both "tool has failed" and the suffix — assert
   on the value **read back from the store**, not the value passed in.
4. A name containing a markdown fence does not break `repair_brief.py`'s rendering — no unmatched
   fence, no injected heading.
5. `_preview(text, -1)` returns `""`.
6. An ordinary well-formed tool name renders **bare**, unquoted, unchanged. The escaping must not
   make the common case ugly.

Mutation-check every fix.

## Tracking

- **#1233** stays open until Sections 1 and 2 land; note Section 3's gate explicitly in the close
  comment for whichever part ships.
- If 1a is chosen, file it as its own AD — do not build it inside this BF.

## Report back

- Which Section 1 option the Captain chose.
- The five-site enumeration, re-run — confirm it is five and not six.
- The payload size for the 128-character control-filled id, before and after.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
