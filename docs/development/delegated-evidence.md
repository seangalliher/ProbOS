# Delegated evidence (AD-1191 / #1128)

## Scope and compatibility

This is invocation-local provenance returned by `delegate_task`, not a claim
verification receipt. It adds no store lookup, network request, model call,
configuration flag, or durable trace/checkpoint schema. The existing delegation
enablement, depth, iteration, identity, permission, and consensus policies are
unchanged.

`DelegatedToolResult` is a frozen subtype of `ToolResult`.
`DelegatedToolCallResult` is a frozen subtype defined beside `ToolCallResult`.
Both carry a typed `DelegationEvidence`; neither base dataclass changes its
fields or positional order. `WorkItemAgenticOutcome` appends a default-`None`
`delegation_evidence` field. Other outcome consumers keep their existing
projections.

The native `output`, `error`, `duration_ms`, and `metadata` remain unchanged.
The adapter retains its existing error-text selection, structured-output
rendering, and `source_chars` measurement, including on errors. It transfers
the typed extension separately. Arbitrary dictionary or metadata keys do not
acquire evidence authority.

Only the transcript formatter adds evidence:

```text
{"evidence":{...canonical single-line JSON...}}
<legacy ToolCallResult.output, subject to its existing message policy>
```

Both actual loop transcript paths use this formatter for delegated results.
Ordinary results retain their previous rendering and truncation path. Stored
`ToolCallResult.output`, trace bytes, error signatures, publication confirmation,
metadata, body/frontmatter, and claim identity remain on their old contracts.

## Producers and interpretation

The executor installs a run-local collector on its existing raw-result
post-hook. A successful real `publish_finding` write returns a frozen
`FindingToolResult` containing a typed `FindingPublication`. Duplicate
suppression, rate refusal, and failed writes remain ordinary results and do not
count as new publications.

The shared frozen `FindingClaim` owns the existing title/claim/basis
normalization, confidence default and accepted inputs. Claim identity still
hashes the sorted, compact, `ensure_ascii=False` JSON triple in UTF-8.
`compute_claim_id` remains importable from `publish_finding_tool`.

Only this invocation's ship-visible publications are exported. A fleet request
actually written at ship scope says `classification: ship` and
`requested_scope: fleet`. Private and department publications contribute only
restricted-scope omission counts: no claim body, claim ID, or record path is
exported. No requestor-policy lookup is added.

A nonblank final result is one **opaque, unverified delegate assertion** with
the original result's SHA-256 and exact UTF-8 byte length. Whitespace is not
removed before hashing. Prose is not split into claims or citations, and no
title, basis, confidence, or independent verification is invented. Empty
completion remains completed. An invalid UTF-8 assertion is visibly omitted
without changing the native result.

Source coverage means only the actual current-run trace hash and eligible
publication references, not all factual sources used by the model. Trace-store
unavailability is visible as partial source coverage. Artifacts use the public
extraction of the existing seven-field `run_python` validator. The original
32-reference outcome limit, ignored-entry count, and stricter persisted
finalizer contract are unchanged; the evidence view preserves upstream
omissions and applies its own smaller bound.

The additional collector retains at most eight bounded publication entries;
restricted, oversized-core, and over-count claim objects are not retained.
Artifact projection examines at most the existing 32 outcome references and
retains at most eight. Separate invocations never share a collector. A nested
delegate's findings and artifacts are not flattened into its caller's
authorship.

## Envelope

All envelope models are frozen, strict and extra-forbidding, with tuple
collections internally. The schema has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exact integer `1`, not a boolean or numeric/string lookalike. |
| `status` | `completed`, `exhausted`, `failed`, `not_started`, or `unknown`. |
| `producer` | Actual nullable `agent_id`, `thread_id`; fixed scope `this_delegate_invocation`. |
| `verification` | `state: not_performed` or `unknown`, fixed scope `claims`. Neither publication nor completion verifies truth. |
| `claims` | Discriminated `delegate_assertion` and `published_finding` entries, always `unverified`. |
| `source_refs` | Discriminated `tool_trace` hash and `published_finding` reference/classification entries. |
| `artifacts` | `artifact_id`, `content_hash`, `thread_id`, `name`, `mime`, `size_bytes`, `version`. |
| `coverage` | `observed`, `partial`, or `unknown`, separately for claims, source refs, and artifacts. |
| `omissions` | Aggregated `section`, `reason`, `count`, `saturated`; never omitted content. |

`complete` maps to completed; `max_iterations` and `token_budget` to exhausted;
loop/caught error to failed; existing early refusal to not_started; missing or
unrecognized legacy state to unknown. The token-budget mapping is compatibility
handling, not new delegation budget policy. Cancellation propagates without
creating a terminal result.

Real observed-empty differs from unobserved. Legacy outcomes lacking the typed
collection have unknown coverage and verification, even if they carry final
text or report completion. A caught exception can likewise have unknown
coverage: it must not claim that no earlier work occurred.

## Bounds and packing

| Bound | Limit |
| --- | --- |
| Claims | One final assertion plus at most eight findings. |
| Source refs | One actual trace plus at most eight finding refs. |
| Artifacts | Eight; upstream omission counts remain visible. |
| Inline finding core | 1,024 canonical serialized bytes. Larger cores become reference-only, with original claim ID/ref and `content_omitted: field_limit`. |
| Identities / record paths | 512 UTF-8 bytes; existing artifact ID rules remain unchanged. |
| Evidence frame | 4,096 bytes, including wrapper and separator LF. |
| Added JSON transport contribution | 8,192 bytes after HTTPX-compatible string escaping. Tests measure actual local HTTPX request encoding in both transcript modes. |
| Omission counters | 2,147,483,647, with `saturated: true` if exceeded. At most 28 distinct section/reason combinations. |

Serialization uses sorted keys, compact separators, `ensure_ascii=True`, and
`allow_nan=False`. The producer contract is validated before packing. Whole
identity fields and whole entries are omitted, never clipped; a finding and
its reference are atomic. Oversized cores are never hashed after truncation.

Packing order is mandatory summary/final assertion, trace, then alternating
artifacts and finding/reference pairs in their observed order. Future omission
bookkeeping is reserved before an optional entry is admitted. Omission reasons
are `count_limit`, `field_limit`, `byte_limit`, `message_limit`, `invalid`,
`restricted_scope`, and `upstream_omission`. Any affected observed collection
becomes partial; a legacy unknown collection stays unknown.

For an existing positive message cap `C`, the frame receives at most
`floor(C/2)` characters and is repacked. The existing head/tail truncator gets
only the remainder for legacy text. The formatter never passes a zero
remainder to that truncator, whose zero means unbounded, or applies a late
generic truncation across JSON.

If a summary cannot fit, the exact 36-character marker is
`{"evidence_omitted":"message_limit"}`. Caps 36 through 73 return that marker
alone. Caps 1 through 35 return the documented `!` omission sentinel. At
larger caps the marker plus LF can precede bounded legacy text. These tiny
views necessarily disclose omission rather than the unavailable summary.

The finite new-evidence bound is not a retroactive bound on native final text.
With the existing message bound disabled, the native legacy suffix remains
complete. With it enabled, only the transcript view is limited.

## Validation and rollback

The two AD-1191 test modules cover strict schemas, exact byte/+1 and count
boundaries, UTF-8/escaping, saturation, tiny caps, unchanged base field order,
publication bytes/hash, durable output/error identity, and real next-parent
request crossings. The crossings use scripted LLMs, the real executor and
publication/artifact producers, and isolated local stores/fakes. They assert
that producers actually fired and cover errors, restricted scope, descendants,
concurrent invocations, and cancellation. They do not establish external-model
answer quality or independent factual verification.

Ordinary Git rollback is sufficient: no persistence migration or new stored
evidence contract is introduced. Focused implementation evidence is not an
independent review, canonical full gate, release, or issue closure. Those steps
remain with the parent workflow.
