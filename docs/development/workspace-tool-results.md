# Workspace tool-result delivery (AD-1240)

AD-1240 (GitHub issue #1239) keeps a large tool result recoverable. Before it, a result above the configured
per-message cap was cut to a head and a tail with an elision marker, and the elided middle was lost from the
conversation. Now a result above 12,288 UTF-8 bytes is written to the calling agent's workspace, the model receives a
short pointer with an outline and a worked `read_file` call, and that call returns the exact text. The
interception point is after the real executor returns and every observer has seen the original result, and
before the tool-call converter's destructive rendering.

Storage and retention live in
[`workspace_result_store.py`](../../src/probos/execution/workspace_result_store.py): `WorkspaceResultStore`
(lifecycle, latch and the public protocol), `ArtifactIO` (the worker-thread disk protocol for one artifact) and
`GenerationReaper` (the retention sweep). `WorkspaceManager`
([`workspace.py`](../../src/probos/execution/workspace.py)) keeps path ownership only, and it reserves the result
directory from ordinary workspace operations. The executor, the attachment store and the tool registry do not
become payload stores or presentation services.

## The guarantee

> `.tool-results` is a runtime-reserved directory whose contents may be removed once their retention has expired. Large results are published into hourly generation directories, each named by the UTC hour of the injected clock (`YYYYMMDDTHHZ`). Every artifact's directory and files are created exclusively and never rewritten, and every committed artifact's `committed_at` falls inside its generation's hour. Reads return the exact committed text until `committed_at + 24 h` and refuse it with `result_expired` from then on. The reaper removes only whole generations whose hour ended at least 24 h ago, and decides this from the name and the clock alone, so ProbOS's own writers cannot race it and no ProbOS-produced artifact is removed before its retention expires; physical removal follows within about one hour plus one sweep. Each sweep samples the clock once, inside the store lock, and decides every removal in it from that sample; a clock that steps backwards while a sweep is already removing does not stop that sweep. ProbOS does not preserve anything that a process outside ProbOS writes or substitutes inside the directory, and Tier-1 code execution, which is not sandboxed (AD-993), counts as outside ProbOS. Inside an expired generation such content is removed with the generation. While a generation is unexpired and the running ProbOS process still holds its commitment record, a read refuses a payload, outline or manifest that differs from what the process committed in its digest, sizes, outline hash, `committed_at`, representation or owner digest (manifest keys it did not write are not compared); without that record (after a restart, or once the generation has been removed whole), a read can check only that the payload, outline and manifest agree with one another, so a consistent rewrite by a writer with ProbOS's own OS identity is not detected then, and no artifact is ever readable past the end of its generation's hour plus 24 hours, which is decided from the directory name alone. The reaper never follows links. Brief Windows sharing violations and their POSIX equivalents are retried within a bounded budget and deferred to the next sweep without switching offload off. Publication is latched until a completed `stop()` and a successful `start()` only by an integrity failure, by a generation that still cannot be removed because of a transient failure one further retention period after it expired, by a root or owner-namespace directory that has stayed unopenable for one retention period, by a sweep that raises or is cancelled, by the reaper task ending or being cancelled, or by a `start()` that fails or is cancelled. Private-path, foreign-owner and expiry refusals on every legacy workspace route remain.

The sections below say how each sentence is met. "Reaper residuals" lists the residuals that qualify it, and
"What is not promised" says in plain terms what the guarantee does not cover.

## Activation and compatibility

`AgenticLoop` holds its workspace-results owner in a data descriptor, `WorkspaceResultsSlot`, defined in
[`result_offload.py`](../../src/probos/cognitive/swe_harness/result_offload.py) and declared on the loop class as
`workspace_results`. It adds no method to the loop. The constructor keyword `workspace_results=` is assigned
through the slot when it is not `None`. Both production loop constructors keep their existing keyword arguments:
`WorkItemAgenticExecutor` ([`agentic_dispatch.py`](../../src/probos/cognitive/agentic_dispatch.py)) and
`NativeBuilderHarness` ([`native_builder.py`](../../src/probos/cognitive/swe_harness/native_builder.py)) assign
`loop.workspace_results = resolve_workspace_results(runtime)` immediately after constructing the loop, and merge
the delivery context (the same authorized registry view the run's executor uses) into the run context. An
absent, invalid or unavailable public runtime owner resolves to `UnavailableWorkspaceResults`, not to an unarmed
loop and not to an ambient workspace.

A direct caller of `AgenticLoop` that injects no owner, or `None`, keeps legacy behaviour, including truncation of
large results by the message cap. An injected owner arms delivery even when the message cap is zero. The slot
refuses an invalid owner (`workspace_owner_invalid`, `None` included) and refuses every assignment once the first
`run()` has begun (`workspace_binding_closed`), whether that run completes, fails or is cancelled. Later runs are
allowed; each run has its own settings snapshot and its own source-recovery scope.

At or below the offload threshold the existing first serialization and renderer stay in use. No artifact, outline
or additional reader offer is added. The base `ToolResult` and `ToolCallResult` fields are unchanged; frozen
subtypes carry the delivery metadata and keep the delegation and repository-instruction types.

## Canonical representation and explicit limits

| Boundary | Limit |
|---|---:|
| Armed offload trigger | Strictly greater than 12,288 canonical UTF-8 bytes |
| Canonical capture | 1 MiB (1,048,576), in characters and in UTF-8 bytes |
| Encoded JSONL payload | 8 MiB (8,388,608 bytes) |
| One physical JSONL line | At most 512 bytes including LF (42 characters per fragment) |
| ASCII-encoded outline | 1,024 bytes |
| Manifest | 4,096 bytes |
| Eligibility inspection | 4,096 visited slots; depth 32 |
| Serialized generated read arguments | 4,096 bytes |
| Window asked for by the generated worked call | At most 4,096 characters |
| Artifact read retention | 86,400 seconds from manifest commitment |
| Generation | 3,600 seconds (one UTC hour) |

The trigger is about two ordinary 6,000-character allowances (see the comment above
`TOOL_RESULT_THRESHOLD_BYTES` in
[`workspace_results.py`](../../src/probos/execution/workspace_results.py)): it catches the measured 14,373-byte
lost-middle example without requiring a recovery turn for every small result. The size is measured in UTF-8
bytes, so a value of fewer than 12,288 characters can still be offloaded. These are per-result limits, not a
tree budget, and not a guarantee that a result at or below the threshold cannot be truncated by an ordinary
message cap. Recovery needs one more model iteration to read the result back and a further one to consume it.

The converter captures its existing first serialization once. Root strings are unchanged; `None` becomes the
existing empty string; other built-ins use the existing ordered Python textual representation, labelled
`python-repr`, not JSON. Character count, strict UTF-8 byte count and SHA-256 qualify that same text. Producer
error text is qualified separately from delivery failure.

Exact eligible types are `str`, `None`, `bool`, `int`, `float`, `list`, `tuple` and `dict`. Revisited containers
terminate inspection and retain Python's existing recursion markers. Above the threshold, opaque or subclass
values, excessive inspection, serialization or encoding failures and size-limit violations fail delivery
explicitly. Successfully rendered small opaque values keep the existing behaviour without a second stateful
representation call. Arbitrary legacy `str(Any)` is not claimed to be hard-bounded.

## Workspace ownership, publication and reading

The neutral `WorkspaceResults` protocol and the frozen records live in `workspace_results.py`.
`WorkspaceResultStore` implements it:

- `bind_agent(agent_id, registered_agent) -> AgentWorkspace`
- `store_tool_result(binding, payload) -> WorkspaceResultRef`
- `read_tool_result_slice(binding, path, offset, limit) -> WorkspaceSlice`
- `reap_tool_results() -> WorkspaceReapResult`, which takes no argument
- `start()`, `stop()` and the retained `background_tasks` tuple

The store is constructed with a `WorkspaceManager` and uses only its `root`, `sanitize` and `key_for_agent`;
`WorkspaceManager` has no result lifecycle of its own.

A binding requires the exact registered identity: the agent id is a string of at most 256 characters and equals
the registered object's `id`. The owner folder is selected as before (callsign, then agent type, then id,
sanitized), and an agent that resolves to the `shared` fallback is refused. A SHA-256 digest of the exact agent
id separates identities that sanitize to the same owner folder. Artifact ids come from `secrets.token_hex(16)`;
they are never derived from model request ids or tool names.

### Layout and generation names

```text
<root>/<owner-key>/.tool-results/<GEN>/<agent-digest>/<artifact-id>/
    payload.jsonl
    outline.json
    manifest.json
```

`<GEN>` is the UTC hour of the injected clock, `YYYYMMDDTHHZ`: 12 characters, fixed width. In
`workspace_results.py`, `generation_name` builds a name and `generation_start` parses one strictly: a name is
accepted only if `generation_name` would itself produce it. `generation_expiry(GEN)` is the start of the hour plus
3,600 plus 86,400 seconds. `<agent-digest>` is 64 lowercase hex characters and `<artifact-id>` is 32.

Each physical line of `payload.jsonl` is one ASCII-escaped JSON string fragment of at most 42 characters, so the
line stays under 512 bytes including LF; concatenating the decoded fragments reconstructs the canonical text
exactly, with no separator. `outline.json` is a deterministic ASCII summary: representation, root type,
character, byte and line counts, bounded shape counts, and the fact that keys and values are omitted.
`manifest.json` records the kind and version, owner key and digest, artifact id, `committed_at`, representation,
the text's SHA-256 and sizes, and the outline's SHA-256.

### Publication

Publication runs in a worker thread under the one store lock that reads and sweeps also take.

1. **Admission.** The generation is `generation_name(max(clock(), high_water))`. The high-water mark is
   process-local, starts at negative infinity, is raised by every commit and is never restored from disk. A clock
   that moves backward therefore never puts a publication into an earlier generation and never shortens
   retention.
2. **Creation.** The agent directory is pinned (missing directories on the way are created), the artifact
   directory is created, and `payload.jsonl`, `outline.json` and `manifest.staged` are each created exclusively
   (`O_CREAT | O_EXCL`), written, flushed with `fsync` and never rewritten.
3. **Commit.** `committed_at = max(clock(), generation_start(GEN), high_water)`. If that is not before the end of
   the generation's hour, this artifact is left unadvertised (no `manifest.json`; the reaper removes it with its
   generation) and publication is retried once, in the generation of `committed_at`. A second rollover is
   `workspace_write_failed`. Otherwise `manifest.staged` becomes `manifest.json` by a hard link, which fails if
   the target exists, so a manifest is never replaced. The staged name is then removed, the high-water mark is
   raised and the artifact is recorded in the in-process registry described under Reading.
4. **A failure after the link.** If publishing raises, the artifact counts as committed only when `manifest.json`
   holds exactly the staged bytes. Anything else is `workspace_write_failed`, and a manifest that differs from the
   staged one is never advertised. A volume that cannot hard-link fails here too: the run stops with
   `workspace_write_failed`, nothing is advertised, and the unadvertised files go with their generation.

`workspace_result_store.py` never uses `replace`, `rename`, `rmtree` or `move`; a test parses the module and
fails on any attribute, name or import with one of those names.

Every committed artifact in a generation satisfies `generation_start(GEN) <= committed_at <
generation_start(GEN) + 3600`.

### Reading

`read_tool_result_slice` accepts only a path of the exact shape
`<root>/<owner-key>/.tool-results/<GEN>/<own-digest>/<artifact-id>/payload.jsonl` (canonical generation name,
32-hex artifact id, the caller's own digest), and then runs, in order:

1. **Before any I/O**, if the clock is at or past `generation_expiry(GEN)`, the read is refused with
   `result_expired`.
2. The manifest (at most 4,096 bytes) and the outline (at most 1,024 bytes) are read and the reference is built.
3. **Registry check.** The reference is compared with what this process committed (below); a mismatch is
   `payload_changed`.
4. `committed_at` must lie inside the generation's hour, or the manifest is `manifest_invalid`.
5. If the clock is at or past `committed_at + 86,400`, the read is refused with `result_expired`.
6. The payload is read (opening it retries Windows sharing violations 32 and 33 only), decoded, and checked for
   length, byte count and SHA-256; a difference is `payload_changed`. Expiry is checked again after the read.
7. The slice is `text[o:e]` over decoded Unicode code points, where `o = offset or 0` and `e = o + limit`, or
   `len(text)` when no limit is given. Python's slice semantics apply, negative positions included. Offsets are
   not bytes and not JSONL lines.

The registry is `CommittedArtifacts`, an in-process record of what this store committed. It holds one bucket per
owner namespace and generation, and per artifact seven fields: SHA-256, `committed_at`, source characters, UTF-8
bytes, the outline's SHA-256, the owner digest and the representation. Every read compares the files with it
immediately after the reference is built, so while the process holds an artifact's record (from its commit until its
generation is removed whole or found already gone, or until the process ends) a rewrite of the payload, outline or
manifest is refused, including a consistent rewrite, a changed `committed_at` and a changed representation. A
bucket is dropped only when its generation has been removed whole, or found already gone: dropping it earlier,
including when a removal is deferred, would let a changed `committed_at` or a consistent rewrite be served
again. The registry is never restored from disk, and unregistered artifacts are
not refused after a restart, because that would make ProbOS-produced data unreadable before its retention
expires.

Every artifact read goes through `WorkspaceResultStore.read_tool_result_slice`. The native `read_file` tool
reaches an artifact only through it and opens nothing under a workspace root's `.tool-results` itself;
`codebase_read_source` refuses such a path with `workspace_reader_required`. A private, malformed, partial,
cross-owner or expired artifact never falls through to an ordinary raw-file read. Recovery results are typed
(`WorkspaceSliceToolResult`) and are never offloaded again. A slice that does not fit the actual message
allowance fails explicitly. Both ordinary source reads and artifact verification may read the whole file: one
tool invocation is not a promise of one filesystem seek.

### The reserved namespace

`.tool-results` is reserved from ordinary workspace operations whoever owns an artifact and whatever its expiry.
`WorkspaceManager.resolve_file` refuses a lexical entry into it, any lexical prefix or the owner folder that
resolves into it (including an alias that enters it and a later `..` that leaves it), and the final resolution,
all before any parent is created. The folder and the target are each resolved once, and the value that was
checked is the value returned. `list_files` and `total_bytes` never list, enter or size the namespace: the walk
drops an entry named `.tool-results` in any letter case, and drops a link that leads outside the owner folder or
into it. A plain file is never resolved, a directory or link is resolved once, and a directory is entered only
while it is still the object that was checked: the walk observes it with `lstat`, without following a link, before
and after its scan, and uses the listing only if both show a real directory that is not a reparse point and has the
identity taken from its scan entry. Each scan entry is classified (directory, link, file) from the observation it
carries, and a real directory that is observed a second time for its identity is classified again from that
observation, so a directory that became a link in between is a link and one that became a file is a plain file. A
link is never entered. A link to a directory is listed once with size 0 and
is never sized (its target is walked once, as itself); a link to a file inside the owner folder is sized from its
checked target.

> The ordinary workspace walk observes only a directory's own final component before entering it; an ancestor swapped for an alias to the same object between a scan and a child's descent could still expose that child's plain-file names and sizes.

The workspace HTTP routes (`routers/agents.py`, unchanged by AD-1240) read a file, write a file, list suggestions
and create a suggestion only after `resolve_file` returns a path; when it returns `None` they answer 400, before
governance or the suggestion store is touched. Dismiss by id carries no path and still works. Tier-1 code is not
confined by this: the per-owner folder is confinement by convention, not a kernel-enforced boundary
(see the module note in `workspace.py`).

## Original sources: no copy, invocation-only recovery

A successful, authorized native `read_file` or `codebase_read_source` observation can carry a frozen `SourceRef`:
agent and run identity, canonical path, opened identity and revision, raw-byte digest, range, and
whole-versus-slice. `read_file` keeps zero-based Python line slicing; `codebase_read_source` keeps its one-based
`start_line` translation. Existing decoding and newline behaviour are unchanged.

An admitted source promise reserves its path until this `run()` exits. The loop, not the model's arguments,
selects `FreshRead` or the trusted `RecoverRead`, and it does so from the call's own lexical path before any
registry lookup, permission check, bind or resolver call. Once a promise is selected, a later failure or
replacement (an owner whose callsign changed, a replaced reader registration, a redirected resolver) is a
content-free refusal (`InvocationRefusal`) before the call starts: no executor call, no events, no hooks, and the
run stops with `stopped_reason="error"` and `reference_unavailable` rather than turning the promise into a fresh
read. Conflicting observations refuse (`source_conflict`) rather than overwrite an expectation. Recovery
reauthorizes the file and verifies identity,
revision and digest; a disappearance, replacement or in-place change is `source_changed`.

An artifact path this run published is a workspace promise of the same kind, held by the run's
`SourceRecoveryScope` (`reserve_workspace`, recorded only after the pointer frame was admitted, and
`workspace_promised`). A call that names it, by its exact path or by an alias spelling the reader resolves to it,
is checked before invocation: only `read_file` may serve it, the reader must still be the one whose identity was
fixed at first admission, and that reader must still resolve the published path, compared in its lexically
normalized spelling, so an equivalent spelling such as one containing `..` recovers through the unchanged reader.
Otherwise the call is
refused with `reference_unavailable` before it starts. The alias decision is made outside the step that turns an
unresolvable fresh read into an ordinary one, so a refusal there is never swallowed into a fresh read. Promises
are run-local: a new top-level run has a new scope, and an artifact path that was never promised takes the typed
fresh route with its owner, digest and expiry checks.

An unpromised fresh read keeps each native reader's ordinary producer-error and next-correction behaviour for a
directory, a disappearance, a permission failure or a read failure; it does not become a delivery failure and
does not retry through an unchecked read. A recovery or private-artifact failure never downgrades to that path.

Original-source pointers create no payload, outline, manifest or reaper entry. Their inline outline and worked
call describe the verified source range. A line larger than the actual allowance cannot be recovered intact
through ordinary line slicing: that is a refusal (`source_line_too_large`), not a pointer-to-pointer loop or a
new column-slicing feature. Recovery is supported by the next model iteration in the same invocation. The next
top-level turn or a restart loses source expectations: a bare path then asks for a fresh read, and an explicit
recovery without its live reference returns `reference_unavailable`. There is no durable source registry and no
restart-validated source-recovery claim.

## Admission, consumers and failures

Preparation requires the current authorized native reader from the same registry view the run uses, including
permissions, restrictions, department and lock-out (LOTO). The reader definition is offered lazily with the normal alias
and deduplication rules, retained across refreshes, and rechecked before every later request; no broader runtime
registry is used to recover authority. When delivery is armed with a real owner and the strict profile is off,
`agentic_dispatch.py` keeps the `read_file` definition full in the AD-1189 deferred-schema manifest
(`_recovery_reader_full`), so the deferred-schema guard never refuses the reader a worked call advertises; it
holds after every refresh, including with the AD-1241 MCP offer. Plan mode whose AD-1156 allowlist excludes
`read_file` has no recovery reader, so `_delivery_armed` is false there: the loop is left unarmed and keeps legacy
delivery, with one INFO log. A failed recovery read through a reader that is not in the dispatch offer is labelled
unknown in AD-1248 failure summaries. A whole pointer, outline and worked call must fit the actual final
allowance: the frame is sized against the exact path width before anything is published (the generation name is
fixed width), and both message modes use the common final formatter, so an affected presentation is complete or
refused, never character-truncated. A result group that carries a pointer or a slice is kept whole for the rest of
the run: a compaction that would change one is not applied, and the complete uncompacted history is sent.

Iterations. A new pointer needs at least two further model requests (read back, then answer) and a recovery read
needs one. The loop passes `delivery_remaining` to the delivery step: the total ceiling net of AD-1324 floor
re-issues and, when AD-1208's counted ceiling is armed, the smaller of that and the counted remainder. If fewer
remain, the run stops with `recovery_iterations_unavailable` rather than send a pointer the model cannot follow.

- **AD-1191:** only the canonical native output is offloaded. Typed evidence identity and original hashes stay
  separate, and the existing bounded evidence frame, with its privacy counters and honest omissions, is reserved
  inline first.
- **AD-1192:** an offloaded, source or recovered presentation is never presented for acknowledgement.
- **AD-1200:** original-source instruction observations and scope and exclusion merging remain intact; workspace
  paths do not replace original guidance.
- **AD-1146 and AD-1148:** correlation, ordered outcomes and the existing parallel allowlist are unchanged.
- **AD-1151 and BF-760:** original and rendered qualification stay distinct from the bounded, versioned `delivery`
  trace metadata (ASCII JSON of at most 4,096 bytes, or `metadata_omitted`). Output-disabled trace bytes are
  unchanged. A 24-hour reference is not lossless durable archival.

Missing ownership or reader authority, stale sources, capture or write failures and unfit frames are **delivery
failures**, not fabricated producer faults and not successful truncation. Post-hooks keep the original result.
Completion events, error signatures, duration and source qualification keep their producer meaning. Calls that
were already issued finish once, in request order, and all outcomes are retained before the loop stops with the
existing `stopped_reason="error"`. Neither production caller retries or falls back to another execution path.

Error codes are fixed, content-free and at most 96 characters. The final explanatory text is nonempty, at most 128
characters and within the positive result cap; `!` is used when it cannot fit. Payload bodies are not added to
logs, events, Intent parameters or a second payload store.

## Inline results and the armed-unavailable policy

Exactly two producer results are never offloaded. Each is identified by its exact Python type, never by tool id,
metadata key or text:

- `WorkPullReceipt` (AD-1187, [`work_item_pull_tool.py`](../../src/probos/tools/work_item_pull_tool.py)): a
  complete, pre-admitted control receipt.
- `OwnedStepsViewResult` (AD-1192, [`work_item_steps_tool.py`](../../src/probos/tools/work_item_steps_tool.py)):
  a complete owned-steps page whose view JSON is at most 16 KiB (`MAX_OWNED_VIEW_BYTES`); the rendered text can
  reach about 16.8 KB. Its exact text authorizes the acknowledgement in `agentic_dispatch.py`, which an offloaded
  page could never receive.

In `result_offload.py` the check is `type(raw) is ... and raw.error is None`. A subclass of either type, either
type carrying an error, a plain result that carries the same metadata key, and a plain result from a tool that has
the same tool id are all offloaded like any other result. An exempt result stays inline and is admitted against the
message cap: if it does not fit, the run stops with `delivery_frame_too_large`; it is never truncated. Every other
result above the threshold takes the offload path, including a `review_requests` list and a delegated result
(whose evidence frame is reserved inline first).

**Armed-unavailable.** `resolve_workspace_results(runtime)` never returns `None`, so every production caller is
armed, except that a plan-mode run whose allowlist excludes `read_file` keeps legacy delivery (below). With no
started store (the runtime has no `workspace_results` attribute, or it is not a valid owner),
a result at or below 12,288 bytes is delivered as before, and a result above it stops the run with
`stopped_reason="error"` and the content-free code `workspace_unavailable`. It is not truncated and not silently
destroyed: the producer's outcome is kept (a successful result is still not an error), and the model is told only
`Result delivery failed (workspace_unavailable).`, or `!` when the message cap is too small for that sentence. A
direct `AgenticLoop` caller that injects no owner is unarmed and unaffected, and so is a plan-mode run whose
allowlist excludes `read_file` (legacy delivery, one INFO log). One production caller is armed-unavailable by
construction: the crew verifier's session-correction runtime projection (`_SessionCorrectionRuntime` in
`crew_verifier.py`) is a deliberately narrow, frozen set of attributes and carries no workspace store, so a result
above the threshold in a correction run stops the run with `workspace_unavailable` instead of being truncated.
Giving that projection an owner is a follow-up, not part of this change.

## Strict profile

When the executor reports `protected_effects_enabled` (the strict protected-execution profile), the loop keeps
legacy delivery: no capture, no offload and no source promise, whatever owner was assigned. It logs once per run
at INFO, without content. A strict run never calls the store, and its events, results, requests and trace bytes
equal those of the loop before AD-1240. Offload under the strict profile was considered and deferred; strict
results are therefore not covered by the recoverability guarantee.

## Lifecycle, retention and rollback

### Startup and ownership

Phase 1 of startup ([`infrastructure.py`](../../src/probos/startup/infrastructure.py)) builds
`WorkspaceResultStore(WorkspaceManager(config.execution.workspace_root))` and starts it after
`trust_network.start()` and before the identity registry, so a failure while it starts leaves nothing else
open; Phase 1's unwind stops it if a later step fails. The root resolves exactly as the legacy workspace
manager's does (a relative path goes under the platform data directory); it is not rebased on `runtime.data_dir`.
The started store, or the typed unavailable owner, is returned in the last field of `InfrastructureResult`
([`results.py`](../../src/probos/startup/results.py)) and published as `runtime.workspace_results`
([`runtime.py`](../../src/probos/runtime.py)), which holds `UnavailableWorkspaceResults` from construction until
Phase 1 replaces it.

The typed unavailable owner stays when the configured root is missing, is not a string or path, or is `""`, `"."`
or `Path()` (an empty value would resolve to the platform data directory, which is ambient storage), and when the
store cannot start: its first sweep reports a failure, or no `background_register` callable was supplied
(`reaper_unregistered`). A store that fails to start is stopped. Every use of the unavailable owner raises
`workspace_unavailable`; nothing is redirected to ambient storage.

`start()` validates the root (it must not be a filesystem anchor), runs one sweep, starts a reaper task that is
registered through `background_register`, and then sweeps every 60 seconds. Construction, binding and a sweep of
an absent root create no directories; only an admitted publication creates the owner paths it needs. An absent
child below a validated, accessible ancestor is an empty sweep with nothing created, unless this process pinned that
root or namespace before, in which case its absence is an integrity failure. If no ancestor can be
opened, not even the filesystem anchor, the sweep raises `workspace_reap_failed` after trying that anchor once,
and Phase 1 keeps the unavailable owner instead of waiting on an unbounded worker. Blocking filesystem work runs
off the event loop, and every retained task drains its worker thread before a cancellation propagates.

### Generations and the reaper

`GenerationReaper` removes whole generations and nothing smaller. It decides from a generation's name and the
clock alone and never reads a manifest, so a writer that commits inside a generation cannot race it. It visits
each owner directory whose name equals its own sanitized form, then the names in that owner's `.tool-results`:

- A name that is not a canonical generation name, a name that does not round-trip, and a generation whose hour
  has not started are left alone and counted `skipped`.
- A generation with `now < generation_expiry(GEN)` is left untouched and is not counted.
- At `now >= generation_expiry(GEN)` the whole generation is removed. By then every artifact committed in its hour
  is past its own 24-hour read expiry, so no ProbOS-produced artifact is removed before its retention expires. An
  artifact is physically removed between 0 and about 3,600 seconds after it stopped being readable, plus up to one
  sweep interval.

The sweep reads its time from the store clock inside the store lock (`reap_tool_results()` takes no argument), so
a queued sweep can never act on a time taken before a publication it waited for. It takes one sample per sweep and
decides every removal in that sweep from it.

Removal of one expired generation is a bounded, bottom-up walk built only from `pin_directory`, `list_names`,
`remove_file` and `remove_directory` in
[`file_access.py`](../../src/probos/security/file_access.py), to a depth of 3 below `<GEN>` (agent directory,
artifact directory, files) and at most 10,000 entries per sweep (`SWEEP_ENTRY_CAP`):

- It removes every regular file and every real directory the pinned primitives accept, whatever its name.
- It never descends into, follows or removes a symlink, junction, reparse point or special file (checked with
  `lstat` and `is_reparse_point`). Such an entry is left in place and counted `skipped`, and its generation
  directory is retained.
- An entry whose name the primitives refuse (one containing `:` or `\`, ending in a dot or space, or naming a
  reserved device) is left in place and counted `skipped`.
- An entry below the depth bound is left in place and counted `skipped`.
- Entries beyond the cap are `deferred` to the next sweep; a cap deferral never escalates.
- `deleted` counts whole generations removed.
- When the removal of an expired generation starts, the directory identities cached under it are evicted; its
  registry bucket is evicted only once the generation is removed whole or found already gone. The identities of
  the root, the owner and the namespace, and of unexpired generations, are kept, so integrity detection still
  works.
- A sweep that reaches the cap records where its budget ran out, per directory (the root's owners, a namespace's
  generations), and the next sweep resumes after that owner or generation and wraps round. Only the visiting
  order changes, never which generations are selected. Owners are reaped with no root pin held; each namespace pin
  re-verifies the whole chain.
- No journal is kept. A partly removed expired generation is still expired, so the next sweep finishes it.

### Failure taxonomy and retry

`classify_os_error(exc, platform=...)` sorts a filesystem failure into `gone`, `transient` or `integrity`; it takes
the platform explicitly so both tables are tested on both CI platforms. The sweep settles every failure against
the **anchor chain**, the path from the workspace root through the owner directory to the owner's `.tool-results`,
and checks that chain first, whatever the failure's kind.

| Class | Windows | POSIX | Count and effect |
|---|---|---|---|
| Already gone | `FileNotFoundError` on the leaf | same | success |
| Transient | `PermissionError`, or `OSError` with `winerror` 32, 33, 5, 145 or 303 | `errno` `EBUSY`, `EAGAIN`, `ETXTBSY` or `ENOTEMPTY` | retried; if the budget runs out, `deferred`; no latch |
| Integrity | any failure while the anchor chain does not verify (identity changed, reparse point in the chain, a previously pinned directory disappeared, an opened directory moved); a missing filesystem anchor; `clock_invalid`; inside an expired generation with the anchor intact, any `OSError` that is neither gone nor transient and any exception type other than `FileAccessDenied` or `ValueError` | the same, including `EACCES`, `EPERM`, `EROFS`, `EIO`, `ELOOP` and `ENOTDIR` | `failed`; latches |
| Escalated deferral | a generation still not removed because of a transient failure when `now >= generation_expiry(GEN) + 86,400`; a root or owner-namespace pin or listing that has been continuously deferred for 86,400 seconds | same | `failed`; latches |
| Foreign | non-generation or future names; links, special files and refused names inside an expired generation; depth beyond 3; `FileAccessDenied` or `ValueError` at or below `<GEN>` while the anchor chain is intact | same | `skipped`; never escalates, never latches |
| Capped | entries beyond 10,000 in one sweep | same | `deferred`; never escalates |

The retry policy is `RetryPolicy(attempts=4, delays=(0.05, 0.2, 0.5), sweep_sleep_budget=2.0)`: at most four tries,
with sleeps of 0.05, 0.2 and 0.5 seconds between them. One runner spans one sweep (or one store operation) and
never sleeps past its 2.0-second budget; if the next delay would exceed it, the failure is raised instead.
Sleeping happens in the worker thread through an injected `sleep`, so tests assert the recorded delays and never
wait. The retried operations are file and directory removal in the sweep, the root and namespace pins and
listings, each with its closing check (an exhausted transient there is `deferred` and logged at WARNING), the removal of `manifest.staged`
after a commit (left in place if it still fails), and opening `payload.jsonl` for a read (sharing violations 32
and 33 only). A directory-not-empty failure is not retried by the runner: the walk lists the directory again and
removes it again within the same attempt bound.

### Latch and recovery

- **What latches.** Publication becomes unavailable (the next `store_tool_result` raises
  `workspace_unavailable`), before the sweep releases the store lock, when a sweep reports `failed > 0`, when a
  sweep raises or is cancelled (for example `clock_invalid`, or `workspace_reap_failed` for a missing anchor),
  when the reaper task ends with an exception or is cancelled, or when a start fails or is cancelled.
  `deferred` and `skipped` never latch.
- **Recovery.** A completed `stop()` followed by a successful `start()` whose startup sweep reports `failed == 0`.
  A clean public sweep does not clear the latch, and `start()` on a store that is latched but not stopped is
  refused with `workspace_unavailable`.
- **Reads.** Unexpired typed reads keep working while the latch is set, and after `stop()`.
- **Commit.** Admission and the final manifest commit both recheck availability.
- **Per process.** The latch, the store lock and the registry belong to one process. Two ProbOS processes on one
  root are not promised: an artifact's margin against the other process's clock is `end(G) − committed_at`, near
  zero for a late commit.
- **Escalations are deliberate and reversible.** Without them a retention that cannot make progress would be
  reported only by log lines while disk use grows. Each is one branch that can become a log-only warning; the cost
  is stated in the code: with a warning only, a lock held for more than a further 24 hours would grow disk use
  without bound, and with the latch it turns offload off until the store is stopped and started again.

### Reaper residuals

These qualify the reaper's behaviour and the guarantee. The ten quoted sentences below, with the one under "The
reserved namespace", are the agreed wording of the residuals.

> An entry inside an expired generation that the pinned filesystem primitives refuse to touch — a link, a junction, a special file, or a name they reject, such as one containing `:` or `\` or ending in a dot or space — is left in place, counted as skipped, and keeps its generation directory on disk; ProbOS never creates such entries, so they come only from a process outside ProbOS, the material retained is bounded by what that process wrote, and it never latches publication.

> An entry inside an expired generation whose identity changes while the reaper removes it is treated as content placed there by a process outside ProbOS when the pinned primitives report an identity change or a refused name and the chain from the workspace root to the owner's `.tool-results` directory still verifies: it is removed or left for the next sweep and never latches. With that chain intact, any other error from such an entry that is neither already-gone nor transient (for example `ENOTDIR`, `EACCES` or `EIO`) is an integrity failure and latches publication, and so is a change anywhere in that chain.

> On POSIX, removal acts on directory objects that were verified to be inside the expired generation when they were opened, not on their current pathnames; a process outside ProbOS that moves such a directory elsewhere during removal can have entries removed from it at its new location, and the reaper's next check then treats the change as foreign (inside the generation) or as an integrity failure (above it).

> A hard link created by a process outside ProbOS is indistinguishable from an ordinary file and is listed and served as one.

> A `review_requests` list above 12,288 bytes is offloaded (its content stays recoverable); only producer-typed results (`WorkPullReceipt`, `OwnedStepsViewResult`) stay inline.

> A sweep decides every removal from the one clock sample it takes inside the store lock; if the clock steps backwards while that sweep is removing, an artifact it removes may be one that a reading of the stepped-back clock would still call unexpired. Reads are serialized with sweeps, so no read observes the clock in the middle of a sweep.

> A generation's commitment record is dropped only when the generation has been removed whole or found already gone; a generation whose removal is deferred, capped or held keeps it until it is removed or the process restarts. Once a generation has been removed whole its record is gone, so if the clock steps back far enough for the generation's name to read as unexpired again, an artifact that a process outside ProbOS places there is read with the restart-grade consistency check only; and a generation directory that a process outside ProbOS removes before its expiry is never listed again, so its record stays in memory until the process ends.

> Inside one expired generation the walk runs in name order, so ProbOS artifacts listed after at least 10,000 retained foreign entries in that same generation stay on disk with it; and a sweep that walks that many entries holds the store lock, delaying publications and reads, for the length of the walk (measured at 10,000 entries from about 10 seconds to over 35 seconds, depending on the host's load; this is not a bound).

> A root or owner namespace that disappears while ProbOS is stopped is treated after the restart as never created.

> Two ProbOS processes on one workspace root are not promised: the store lock, the high-water mark, the registry and the identity cache are per process, and an artifact's margin against another process's clock is `end(G) − committed_at`, which is near zero for an artifact committed late in its hour.

Further residuals:

- **After a restart the registry is empty.** A read then checks only that the payload, outline and manifest agree
  with one another, so a consistent rewrite by a writer with ProbOS's own OS identity is served. It is never
  served past `generation_expiry(GEN)`, which is decided from the directory name, and an out-of-hour
  `committed_at` is still refused as `manifest_invalid`.
- **After a restart nothing about the anchors is remembered.** While the process runs, a root or owner namespace it
  has pinned before (`DirectoryIdentities.knows`) that is now missing is an integrity failure and latches; after a
  restart the memory is empty, which is the quoted residual above.
- **A permission-class error latches.** A persistent `EACCES`, `EPERM`, `EROFS` or `EIO` while removing an expired
  generation, with the anchor chain intact, is an integrity failure and latches publication. This is a decision the
  Captain can change.
- **A failed recovery read through a reader outside the dispatch offer** is labelled unknown in AD-1248 failure
  summaries.
- **Foreign entries can hold back physical removal.** A link, special file or refused name keeps its generation
  directory on disk and is reported as `skipped` on every sweep. Each sweep visits such an entry, and the
  directories above it, again and counts them against the 10,000-entry cap. Foreign entries in one expired
  generation can delay, but not prevent, the removal of other generations, because a capped sweep resumes after the
  generation and the owner where its entry budget ran out.
- **An outside deletion of an unexpired generation.** If a process outside ProbOS deletes a generation that has
  not expired, the directory identities this process cached for it (the generation directory and each agent
  directory beneath it) are never evicted, because the name is no longer listed. Publication into that owner's
  generation then fails with `workspace_write_failed` for the rest of its hour. It does not latch publication,
  and the next hour uses a new generation.
- **Crash durability is not claimed.** Each file is flushed with `fsync` as it is written. Publishing a manifest
  ends by removing the staged name and then, on POSIX, flushing the directory. If removing the staged name fails
  after the link, the artifact is treated as committed but that directory flush is skipped, and the staged file
  stays until its generation is removed. The pointer is delivered to the model during the run that produced the
  result, and the artifact is a 24-hour recovery copy, not an archive.

### Shutdown and rollback

Shutdown stops the store once the pools (its publishers) have stopped, in a `finally` inside the existing
"pools stop and intent bus drain" step in [`shutdown.py`](../../src/probos/startup/shutdown.py), so a store is
stopped even when the pool step raises, in normal shutdown and in rollback mode. The AD-824 background-task sweep
leaves the store's reaper task alone: the store drains its own reaper and worker threads when it stops, and a
cancellation that arrives during the stop is deferred until transport teardown completes, as it is for the pools.
`stop()` can be called more than once. It removes nothing: committed files stay for their retention.

AD-1240 adds no configuration field and no switch, so rolling it back is a code revert. A rollback plan must keep
the namespace reservation, a compatible reader and the reaper in place until the last committed artifact has
expired and its generation has been removed (about 25 hours after the last commit at most, plus a sweep
interval). It must not delete workspaces or original sources, and it must not reopen ordinary raw-file access to
`.tool-results`. No host daemon, provider, streaming transport, result catalog, AD-1190 budget system or new model
tool is introduced.

## What is not promised

- **Not an archive.** An artifact is readable for 24 hours from its commit and is then refused with
  `result_expired`. Nothing is promised across a crash, and a restart loses the source-promise expectations of the
  run that held them.
- **Nothing a process outside ProbOS writes.** Content that such a process writes or substitutes in
  `.tool-results` is not preserved. Inside an expired generation it is removed with the generation. Tier-1 code
  execution is not sandboxed (AD-993), and the code runner uses the owner's workspace folder as the working
  directory of Tier-1 code, so Tier-1 code counts as outside ProbOS.
- **After a restart, only consistency.** A consistent rewrite by a writer with ProbOS's own OS identity is served
  after a restart, until the generation's hour plus 24 hours has passed.
- **Not instantaneous removal.** Physical removal follows within about one hour plus one sweep after the last
  artifact in a generation expired, and later if ProbOS was not running. A foreign entry keeps its generation
  directory on disk.
- **No protection against a relocated directory on POSIX.** Removal is confined to directory objects, not
  pathnames.
- **Not for the strict profile or a plan mode without `read_file`.** Under the strict protected-execution profile,
  and in plan mode whose allowlist excludes `read_file`, results are delivered as before AD-1240.
- **Not for small results.** A result at or below 12,288 bytes can still be cut by the configured message cap.
- **Not without a started store.** With the typed unavailable owner an oversize result stops the run with
  `workspace_unavailable`.
- **Not across two ProbOS processes.** The store lock, the high-water mark, the registry and the identity cache
  are per process, and each process reads its own clock. A process whose clock runs ahead removes a generation by
  its own reading of the time. An artifact's margin against that is `end(G) − committed_at`, which is near zero
  for a commit late in its hour, so such an artifact can be removed earlier than 24 hours after its commit by
  almost the whole clock difference. Two processes on one root are therefore not promised. This is stated, not
  tested.
- **No hard-link hardening.** A hard link created outside ProbOS is served as an ordinary file, and a volume that
  cannot hard-link cannot offload.

## Code map

| Piece | File |
|---|---|
| Neutral protocol, records, limits, generation names; `SourceRecoveryScope` with the run-local workspace promises `reserve_workspace` and `workspace_promised` | `src/probos/execution/workspace_results.py` |
| Store, artifact I/O, reaper (15 methods), registry, failure taxonomy; `DirectoryIdentities.knows`; the module-level `_rotated` (sweep cursor order) and `_is_expired` (generation selection) | `src/probos/execution/workspace_result_store.py` |
| Path ownership, reservation, ordinary inspection (the module-level `_classify` classifies a scan entry from one observation of it) | `src/probos/execution/workspace.py` |
| Pinned file primitives, `is_reparse_point` | `src/probos/security/file_access.py` |
| Delivery admission, the slot, source scope and refusal, the workspace-promise reader check | `src/probos/cognitive/swe_harness/result_offload.py` |
| Capture of the first serialization | `src/probos/cognitive/swe_harness/tool_call.py` |
| Native readers and typed results | `src/probos/cognitive/swe_harness/tools.py` |
| Arming, iteration accounting, delivery stop | `src/probos/cognitive/swe_harness/agentic_loop.py` |
| Production callers; the full recovery reader in the AD-1189 offer and plan-mode legacy delivery (`_delivery_armed`, `_recovery_reader_full`) | `src/probos/cognitive/agentic_dispatch.py`, `src/probos/cognitive/swe_harness/native_builder.py` |
| The two exempt result types | `src/probos/tools/work_item_pull_tool.py`, `src/probos/tools/work_item_steps_tool.py` |
| Startup, shutdown, runtime owner | `src/probos/startup/infrastructure.py`, `results.py`, `shutdown.py`, `src/probos/runtime.py` |

## Contract tests

Three files own the contract; run each with `-n 0`.

| File | Carries |
|---|---|
| [`tests/test_ad1240_tool_result_delivery.py`](../../tests/test_ad1240_tool_result_delivery.py) | capture, the source scope, delivery admission, the loop, the production callers, the strict profile, the inline exemptions, iteration accounting and the end-to-end crossings |
| [`tests/test_ad1240_workspace_result_lifecycle.py`](../../tests/test_ad1240_workspace_result_lifecycle.py) | generations, the store and reaper, the failure taxonomy, retry, the latch, the registry, Phase 1 startup and shutdown |
| [`tests/test_ad1240_workspace_results.py`](../../tests/test_ad1240_workspace_results.py) | records, the file-access primitives, the reserved namespace on the legacy workspace routes, and the cost of ordinary inspection |

### Acceptance rows

| Row | What it fixes | Test (in the file named above unless stated) |
|---|---|---|
| R1-1 | an alias of a promised source is refused (`source_changed`), never downgraded to a fresh read | `test_promised_source_alias_refuses`, `test_promised_source_alias_by_changed_path_resolution_refuses`, `test_promised_source_physical_junction_alias_refuses`, `test_promised_source_physical_symlink_alias_refuses` (delivery) |
| R1-2 | the real read, write, suggestion-list and suggestion-create routes answer 400 for the reserved namespace at three clocks; list and sizes exclude it; dismiss by id still works | `test_legacy_routes_refuse_reserved_namespace`, `test_r1_private_publication_is_confined_through_real_workspace_http` (workspace results) |
| R1-3 | a missing filesystem anchor ends the sweep instead of repeating | `test_missing_anchor_terminates`, `test_missing_anchor_terminates_injected` (lifecycle) |
| R1-4 | a fresh read error keeps the producer's semantics, armed or not | `test_fresh_read_errors_keep_producer_semantics` (delivery) |
| R1-5 | integrity latches, transients defer | `test_integrity_failure_latches_publication`, `test_sharing_violation_defers_without_latch`, `test_sharing_violation_defers_without_latch_injected`, `test_persistent_deferral_escalates_at_two_retention_periods`, `test_cap_deferral_and_foreign_entries_never_escalate`, `test_root_transient_defers_without_latch`, `test_persistent_root_deferral_escalates_after_one_retention_period` (lifecycle) |
| F1 | a queued sweep never deletes a commit made after the clock moved back | `test_queued_sweep_after_clock_rollback_never_deletes_a_new_commit` (lifecycle) |
| F2 | the registry refuses a consistent rewrite, a changed `committed_at` and a changed representation while the process lives; the after-restart residual is pinned; buckets are evicted with their generation | `test_consistent_rewrite_is_refused_while_the_process_lives`, `test_committed_at_tamper_is_refused_while_the_process_lives`, `test_manifest_representation_flip_is_refused_while_the_process_lives`, `test_after_restart_a_consistent_rewrite_is_the_documented_residual`, `test_registry_bucket_evicted_with_its_generation` (lifecycle) |
| F3 | an identity change inside an expired generation is outside behaviour; a change above it latches; a missing leaf is success but a missing chain is an integrity failure | `test_identity_change_inside_expired_generation_is_documented_outside_behaviour`, `test_ancestor_change_above_generation_during_removal_latches`, `test_enoent_on_the_leaf_is_success_but_enoent_in_the_chain_is_an_integrity_failure` (lifecycle) |
| F4 | POSIX removal is confined to directory objects (documented behaviour) | `test_posix_relocation_during_removal_is_documented` (lifecycle) |
| R2-1 | a promise survives loss of authority; a refusal never shifts a later real outcome | `test_promise_survives_authority_loss`, `test_promise_survives_authority_loss_through_the_loop`, `test_refusal_before_later_real_error_reaches_correlation` (delivery) |
| R2-2 | `resolve_file` returns only the value it checked | `test_resolve_file_returns_only_the_checked_value`, `test_resolve_file_physical_swap_returns_the_checked_value` (workspace results) |
| R2-3 | documented behaviour: an outside write inside an expired generation is removed with it | `test_documented_outside_write_in_expired_generation_is_removed` (lifecycle) |
| R2-3a to R2-3c | an unexpired generation is never reaped; links are not followed; logical expiry at 24 hours, physical removal at the generation's end | `test_unexpired_generation_never_reaped`, `test_link_in_expired_generation_is_not_followed`, `test_link_in_expired_generation_is_not_followed_injected`, `test_logical_expiry_at_24h_physical_at_generation_end` (lifecycle) |
| R2-4 | the descriptor needs no binder method, so five existing loop-double tests stay unchanged | `test_the_tool_is_actually_offered_to_the_loop` (`tests/test_ad1209_work_item_status.py`); `test_the_tool_is_not_offered_when_the_flag_is_off` and `test_the_tool_is_actually_offered_when_the_flag_is_on` (`tests/test_ad1226_recall_artifact.py`); `test_executor_forwards_priority_into_the_loop` and `test_executor_without_priority_omits_the_kwarg` (`tests/test_bf731_captain_llm_lane.py`) |
| R2-5 | ordinary inspection cost is bounded and independent of the file count | `test_ordinary_inspection_resolve_budget`, `test_resolve_count_independent_of_file_count` (workspace results) |
| N1, N2 | the loop keeps its method count and the architecture baseline is unchanged | `tests/test_ad1324_srp_layout.py` (unchanged) and `scripts/check_architecture_principles.py --check` |
| N3, N4 | rollover never commits outside its generation; a backward clock uses the high-water generation | `test_rollover_mid_publication_commits_in_next_generation`, `test_backward_clock_uses_high_water_generation` (lifecycle) |
| N5 | identity-cache entries under a removed generation are evicted | `test_reaped_generation_identities_are_evicted` (lifecycle) |
| N6 | the strict profile keeps legacy delivery and trace bytes | `test_strict_profile_keeps_legacy_delivery_and_trace_bytes`, `test_strict_baseline_fixture_matches_the_unarmed_loop` (delivery) |
| N7 | below-threshold requests are byte-identical to the pre-edit loop | `test_legacy_requests_match_pre_edit_golden`, `test_armed_below_threshold_requests_and_results_are_byte_identical` (delivery) |
| N8 | entries the primitives refuse are left in place, skipped, never latch | `test_posix_only_entry_names_the_primitives_refuse_are_left_in_place`, `test_entry_refused_by_the_pinned_primitives_is_foreign_unless_the_chain_failed` (lifecycle) |
| Inline exemptions | the two exempt types stay inline and are acknowledged; look-alikes are offloaded | `test_owned_steps_page_above_threshold_stays_inline_and_is_acknowledged`, `test_ordinary_16k_result_with_the_owned_steps_metadata_key_still_offloads`, `test_plain_result_from_a_tool_named_read_owned_steps_is_not_exempt`, `test_work_pull_receipt_is_admitted_inline_and_never_offloaded`, `test_plain_receipt_lookalike_is_not_exempt` (delivery); `tests/test_ad1192_owned_steps_dm.py` (unchanged) |
| Iterations | `delivery_remaining` follows both AD-1208 ceilings on every tool execution path | `test_delivery_remaining_follows_both_ad1208_ceilings`, `test_delivery_remaining_reaches_every_tool_execution_path` (delivery) |
| Armed-unavailable | an oversize result with no started store stops the run with `workspace_unavailable` | `test_actual_production_callers_bind_available_or_unavailable_owner`, `test_unavailable_owner_is_armed_but_small_outputs_remain_legacy` (delivery); `test_real_large_delegation_unavailable_owner_stops_delivery` (`tests/test_ad1191_delegation_wire.py`) |
| Promised reader | the AD-1189 manifest never withholds the recovery reader when delivery is armed; strict and unavailable-owner runs keep AD-1189's withholding; plan mode without `read_file` keeps legacy delivery | `test_deferred_schemas_never_withhold_the_promised_reader`, `test_deferred_schemas_with_mcp_offer_never_withhold_the_promised_reader`, `test_strict_or_unavailable_owner_keeps_ad1189_withholding_unchanged`, `test_plan_mode_keeps_legacy_delivery` (delivery) |
| Workspace promises | a published artifact path is served only by the reader admitted with it, by exact path or alias spelling, and refused before invocation otherwise (16 cases: registration replaced, resolver redirected, callsign changed or resolver answers differently, × both transcript modes × parallel on and off); promises are exact, active and run-local | `test_workspace_promise_refuses_replaced_reader_before_invocation`, `test_real_dispatch_reader_identity_loss_is_refused_before_the_executor`, `test_workspace_promise_alias_spelling_is_validated_and_refused_when_the_reader_is_replaced`, `test_workspace_promise_refuses_the_other_native_reader_before_invocation`, `test_repeated_slices_of_a_promised_workspace_path_validate_each_time`, `test_unpromised_artifact_path_keeps_the_typed_fresh_route`, `test_source_recovery_scope_workspace_promises_are_exact_active_and_run_local` (delivery) |
| Reaper repairs | one clock sample per sweep; a deferred generation keeps its commitment record; a remembered anchor that is missing latches, a never-created one does not; capped sweeps rotate; root and namespace units retry whole, closing check included | `test_sweep_decides_every_removal_from_its_one_clock_sample`, `test_deferred_generation_keeps_its_commitment_record`, `test_remembered_anchor_missing_is_an_integrity_failure`, `test_anchor_removed_while_the_process_runs_latches_publication`, `test_never_created_anchor_is_a_healthy_empty_sweep`, `test_sweep_listing_remembers_the_namespace_so_its_removal_is_an_integrity_failure`, `test_capped_sweeps_rotate_to_later_generations`, `test_transient_failure_at_context_exit_is_retried`, `test_directory_identities_knows_only_the_paths_it_remembers`, `test_rotated_resumes_after_the_cursor_then_wraps_round` (lifecycle) |
| Ordinary walk | a directory is entered only while an `lstat` before and after its scan shows the checked real directory; each child is classified from the observation it carries, the second identity-bearing `lstat` of a real directory included; links are never entered; the reserved name is pruned in any case | `test_ordinary_walk_does_not_enter_a_directory_replaced_by_an_alias_to_the_same_object`, `test_overview_route_does_not_list_a_directory_replaced_by_an_alias_to_the_same_object`, `test_ordinary_walk_skips_a_directory_that_cannot_be_examined_when_entered`, `test_links_inside_the_owner_folder_are_listed_once_and_never_entered`, `test_links_are_never_entered_on_a_filesystem_without_identities`, `test_a_directory_seen_as_a_link_at_its_fresh_observation_is_listed_once_and_never_sized_or_entered`, `test_a_directory_still_a_directory_at_its_fresh_observation_is_sized_and_entered_as_before`, `test_a_directory_seen_as_a_file_at_its_fresh_observation_is_listed_as_a_plain_file`, `test_a_file_link_is_sized_from_its_checked_target_or_dropped`, `test_case_variants_of_the_namespace_name_are_pruned_by_name` (workspace results) |
| Startup and shutdown | the store starts before the identity registry and stops in a `finally` | `test_phase_one_starts_the_store_before_the_identity_registry`, `test_cancellation_during_store_start_never_starts_the_identity_registry`, `test_identity_registry_start_failure_stops_the_started_store`, `test_shutdown_stops_the_store_even_when_the_pool_step_raises` (lifecycle) |

### End-to-end crossings

- `test_raw_producer_to_workspace_to_next_request_verbatim_readback` crosses the whole chain with nothing mocked
  between the links, in both transcript modes. A real producer returns a raw value above 12,288 UTF-8 bytes
  (non-ASCII and CRLF content, a unique marker in the middle). The real `ToolExecutor` and its observers (a
  post-hook and the durable record hooks over a real `EventLog`) see the raw object. The armed `AgenticLoop`
  offloads it to a real store on disk, in the generation layout, with nothing else created under the root. The
  actual next request carries the pointer, with the exact path, and not the marker. The model's reply is the
  worked call parsed from that captured request, executed by the loop's own `read_file`, and then the same call
  with only its window moved to the middle; the following request carries the exact middle slice. A result below
  the threshold in the same run is delivered whole with no delivery metadata.
- `test_raw_recording_workspace_actual_request_verbatim_and_middle_readback` crosses the same chain with container
  values, hostile call ids and the durable trace.
- `test_original_source_no_copy_full_loop_recovers_through_real_reader` crosses the source-recovery path.
- `test_real_runtime_start_and_stop_run_the_store_lifecycle_end_to_end` crosses Phase 1, the runtime attribute and
  shutdown.

### Immutable references

`tests/fixtures/ad1240_below_threshold_golden.json` and `tests/fixtures/ad1240_strict_profile_baseline.json` were
captured on unmodified `main` before any source edit (each file's `base` is
`1c9abde5bcde5fef96f2035ff319f81b0c002ff9`). They store the size and SHA-256 of the serialized observations, are
compared exactly, and are never regenerated to make a change pass. The existing AD-1152 and AD-1200 goldens are
untouched.

### First CI run

CI runs on `ubuntu-latest` with Python 3.12 (`.github/workflows/ci.yml`); the canonical gate runs on Windows. A
test whose premise needs a Windows handle, a `winerror`, a junction or a drive letter is skipped elsewhere and is
paired with an injected variant that runs on both platforms; a test whose premise is POSIX is skipped on Windows
and, where a pairing exists, paired the same way. No test skips on both platforms. The POSIX-premise tests are
skipped on Windows, so their first execution is the first `ubuntu-latest` CI run of this change, which must show
them **passed, not skipped**:

- `test_posix_only_entry_names_the_primitives_refuse_are_left_in_place` (the `aux` and `nul.txt` cases rely on
  Python 3.12's `PureWindowsPath.is_reserved`)
- `test_posix_fifo_in_expired_generation_is_left_in_place`
- the symlink variants of `test_link_in_expired_generation_is_not_followed`,
  `test_integrity_failure_latches_publication`, `test_resolve_file_physical_swap_returns_the_checked_value` and
  `test_promised_source_physical_symlink_alias_refuses`
- the real variant of `test_ancestor_change_above_generation_during_removal_latches`
- `test_posix_relocation_during_removal_is_documented`
- added by the review-3 repairs: the symlink variants of
  `test_ordinary_walk_does_not_enter_a_directory_replaced_by_an_alias_to_the_same_object` and
  `test_overview_route_does_not_list_a_directory_replaced_by_an_alias_to_the_same_object`

When this document was written (M5a), the Windows runs skipped 15 cases in 8 test functions (6 in lifecycle, 1 in
workspace results, 1 in delivery). After the review-3 repairs the Windows run of the three AD-1240 test files
skips 20 cases in 10 test functions (12 cases in 6 functions in lifecycle, 6 in 3 in workspace results, 2 in 1 in
delivery) and passes 922; the first CI run is the count of record.

Focused execution evidence, remaining coverage gaps and release status belong to the execution report. This
document is not a canonical gate receipt or a release or closure claim.
