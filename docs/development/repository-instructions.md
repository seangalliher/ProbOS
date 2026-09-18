# Repository instructions (AD-1200 / #1137)

Implementation candidate; independent review and release validation are pending.

## Authority and consumers

Repository files provide **untrusted, subordinate guidance**, not new permissions,
tools, executable authority, or replacements for Standing Orders. The loader and
renderer are stateless functions in `probos.repository_instructions`.

- `NativeBuilderHarness.run_build` seeds the shared loop from its existing explicit
  work directory and the build's target, reference, and test paths.
- Successful, authorized `ReadFileTool` and `CodebaseReadSourceTool` reads return
  frozen result subtypes with separate typed observations. Source text, slicing,
  metadata, and base result field order are preserved. Both readers use the
  existing file-access policy; neither receives the global-file exception.
- The tool-call adapter preserves the observation in a frozen call-result subtype.
  The loop merges it locally and derives one effective system prompt from the
  unchanged base before context estimation and compaction. Both actual request
  branches use that same prompt. Compaction cannot discard the separate snapshot.
- `WorkItemAgenticExecutor` receives observations through its registered tools,
  adapter, and loop. Its API and extra-context allowlist are unchanged. No cwd is
  inferred from task prose, shell commands, or arbitrary Python. There is no
  promise of repository guidance before an arbitrary first-action shell command.
- `CopilotBuilderAdapter.execute` uses the same discovery and renderer for the SDK
  session system message. SDK permission callbacks and lifecycle are unchanged.

No new flag, dependency, persisted schema, database, or startup wiring is added.
With no applicable context/files, request bytes remain unchanged. The installed
ProbOS source repository retains its existing behavior by filesystem identity,
not by matching the directory name `ProbOS`.

Build seeding uses `discover_build_repository_instructions`: absent, empty,
relative or lexically invalid working directories provide no repository authority,
so the adapter logs a contextual warning and preserves the existing request.
It never substitutes the process cwd or recognizes special placeholder strings.
Valid absolute directories delegate to generic discovery unchanged, including
denied/unreadable directory or instruction results and malformed target notices.
Registered file readers continue using generic discovery directly.
The SDK retains its established operational-directory default separately from
the caller-supplied instruction authority; choosing an SDK default does not
manufacture an instruction seed.

## Discovery and precedence

Global instructions exist only in the explicitly supplied
`<runtime.data_dir>\repository-instructions` directory. Discovery never creates
it, scans its siblings, guesses a user/vendor home, or substitutes a location for
a synthetic runtime without `data_dir`. Only `AGENTS.override.md` and `AGENTS.md`
are eligible there.

A usable explicit working directory establishes discovery authority. Targets
resolve against it and must remain within its repository. A regular `.git` file
or directory marks the nearest repository; a `.git` file's contents are never
followed. Discovery uses no Git subprocess. A nested repository stops inheritance
from its containing repository.

Each affected source frame carries complete `excluded_repositories` metadata,
derived from observed target boundaries even when a nested repository has no
instruction file. These dependencies remain attached to the instruction scope
after target eviction, including refresh, override switches, deletion and
recreation. That metadata is atomic with the source: an oversized exclusion
omits the source and body rather than silently widening its scope. Boundary facts
alone do not create an otherwise instruction-free addendum.

Inspect the current directory and relevant target-directory chains, deduplicating
shared ancestors. A source applies only to its stated subtree and repository,
excluding nested repositories, never to sibling scopes. Root Copilot fallback
has repository-root scope, not `.github` scope. There is no nested Copilot search.

Render in global, repository-root, ancestor, then nearest-directory order:

| Presence at one directory | Selection |
|---|---|
| Override absent | Try `AGENTS.md` |
| Override valid | Override only |
| Override empty/whitespace | Suppress normal; inherited guidance remains |
| Override unreadable, invalid, or observed disappearing | Partial/unavailable; never resurrect normal |
| Both root files absent | Try root `.github\copilot-instructions.md` |
| Root normal/override present but empty or invalid | No Copilot fallback |
| Nested normal/override present | Apply only there; root fallback remains inherited |

Missing files are ordinary absence. Invalid paths, unavailable reads, unsafe
boundaries, and exhausted discovery limits are not evidence that rules are absent.

## Filesystem boundary

The existing security owner exposes `read_bounded_utf8`. It reuses existing
authorization, requires a regular file, pins the path chain and file, and validates
the opened object before reading any bytes. Existing resolver signatures remain
unchanged. The loader's global exception is limited to the two exact filenames;
ordinary tools, protected roots, and operator policy are not widened.

- POSIX: descriptor-relative, no-follow traversal with retained ancestor handles.
- Windows: stdlib handle APIs, reparse rejection, final-handle-path checks, and
  no delete sharing while handles are pinned.
- Root/file identity and named/opened revisions are rechecked. Windows named and
  CRT-handle `ctime` can differ, so timestamps are compared within the same API,
  including a pre/post-read handle snapshot.
- Malformed/NUL, drive-relative, alternate-stream, and device discovery paths
  are rejected. Escaping links, junctions/reparse points, and observed ancestor or
  file replacement yield unavailable observations, not outside content.
- Bytes are bounded before strict UTF-8 decoding; an optional BOM is accepted.
  Binary controls are rejected. Only a bounded prefix's terminal incomplete UTF-8
  code point is withheld; invalid interior bytes are never replaced.

Observed changes withhold the snapshot. This is **not** an atomic-snapshot promise
against arbitrary in-place writers. Contextual warnings contain typed reasons,
not instruction bodies or decoder payloads.

## Fixed bounds and request-local retention

| Bound | Value |
|---|---:|
| Repository ancestor search | 64 steps |
| Admitted current/target directories | 16 |
| Candidate instruction directories, including global | 64 |
| Read per selected file | 8,192 bytes + one detection byte |
| Aggregate bytes per discovery, including detection | 524,352 |
| Entire rendered addendum | 32,768 UTF-8 bytes |
| Retained target-directory snapshots per loop | 16 |
| Retained detailed omission identities | 64, plus one sticky overflow notice |
| Excluded repository dependencies per local scope | 16, plus sticky incompleteness |

Discover before allocating content. Admit nearest scopes before spending the
directory budget on ancestors. Rendering reserves framing and omission reporting,
then up to 256 rendered content bytes for each admitted target's nearest available
source. Remaining content is allocated nearest-first; global/ancestor content loses
space before specific rules, while presentation stays global-to-nearest.

Every separator, JSON escape, provenance field, and notice counts toward the
rendered limit. Full source/scope provenance is never abbreviated alongside a
body: if it does not fit, omit the source and report the omission. Prefixes,
unavailable sources, unvisited scopes, limit hits, and evictions are visible.
Partial means **unknown rules**, not absent rules.

All source, body, exclusion, notice and summary values use one HTML-safe JSON
serializer, including Unicode line separators and invalid-path surrogate text.
Only the actual envelope delimiters remain literal. Metadata admission is
nearest-first regardless of readability and precedes all body allocation;
ancestor text cannot crowd out a nearer unavailable or empty override's status.

Repeated observations deduplicate; rediscovered scopes replace stale snapshots,
including changed selection and deletion. Target rediscovery refreshes retention
order; older targets are visibly evicted after 16. State is local to one invocation,
including nested/concurrent runs, and is discarded on cancellation. Guidance is
never cumulatively appended to a previous effective prompt.

Omission history is conservative for the entire invocation. Repeated `(reason,
scope)` identities keep their maximum observed count, not a repeated-read sum.
Rediscovery does not erase an unvisited target's history. Beyond 64 detailed
identities, a sticky notice reports that additional history is withheld and its
exact distinct count is unknown; a fresh invocation starts with no history.

An instruction scope retains at most 16 distinct excluded repository roots.
Overflow, or a newly introduced scope after history was discarded, makes its
coverage incomplete until a fresh invocation. The source frame and body are then
withheld with an explicit reason, never rendered with missing boundaries. This is
the deliberate cost of bounded state: the system does not infer permission to
apply outer rules where a forgotten nested boundary may exist. File-reading
capabilities and permissions are unchanged. Private retention metadata alone does
not add text to a request that has no instruction sources or discovery notices.

This bounds guidance only, not the whole prompt, HTTP escaping, source output, or
the separate execution budget. Guidance bodies are not appended to file-tool
outputs, metadata, delegated evidence, or existing durable trace schemas.

## Downstream transport and degraded-cache behavior

Nonempty system prompts participate in the existing ephemeral response-cache
identity at both degraded-read branches and the successful-write branch. The
versioned SHA-256 input is the unambiguous pair of user and system prompts; there
is no fallback to a prompt-only entry. Empty/absent system prompts retain the exact
old key. Existing LRU, original-tier keying and structured-message cache bypass
remain unchanged. This is system-prompt isolation, not a complete semantic cache
key for every provider setting.

OpenAI and native Ollama request/response logging, including the connected HTTP
error path, records safe metadata rather than bodies. Provider echoes are still
returned to callers but do not copy instruction contents into those logs.
Retry headers, malformed provider tool names, upstream error values, exception
details and invalid token-count values are not logging arguments. Returned errors,
tool names and the retry schedule retain their existing behavior.
Transport payloads, response parsing, SDK permissions and retry policy are unchanged.

## Compatibility and validation

Before production edits at base
`3df0f351520605effdbc2be9a49a72ad1a201127`, deterministic fake providers captured
the no-instructions oracle in
`tests/fixtures/ad1200_no_instructions_golden.json`. Only fixture/source-repository
paths are normalized. Two independently located captures matched, and the oracle
passed on the unchanged base. It pins actual requests in both transcript modes,
native missing/unscoped/installed-repository behavior, base result field order,
and actual work-item durable trace bytes. It is not regenerated to accept changes.

The approved 18-file focused selection measured **493 passed, 4 skipped** in
22.44 seconds, including all **120 new cases**. Its session assertion verified all
247 loaded ProbOS modules came from the candidate worktree. Existing assertions,
configuration, prior baselines, and the ledger snapshot are unchanged.

The parent independently reran the same final selection: **493 passed, 4 skipped**
in 20.30 seconds, with the same 247-module source-provenance assertion. Durable
log/JUnit evidence is retained under
`logs/gates/ordinary-1137-parent-focused-20260918T114540565.*`. A separate parent
probe captured actual native-builder requests in both modes: global, root and
nearest-override rules arrived in order, and the overridden normal file did not.

The existing skips are one symlink-privilege test and three absent-SDK tests;
permissions/dependencies were not changed. New Windows junction/root/ancestor/file
retarget tests prove the retarget occurred and no outside bytes were read. Fake
SDK execution tests do not require a provider. POSIX runtime execution was not
performed on this Windows host.

Crossings include native first/next requests, both registered readers through the
real work-item executor to the next parent request in both modes, fake SDK session
configuration, compaction/token accounting, changed/deleted observations, visible
eviction, and nested/concurrent/cancelled invocation isolation. Removing pre-read
validation made its race control fail after reading 13 outside-fixture bytes;
reverting the Windows timestamp correction failed the stable-file control.
Disconnecting both actual request branches failed four native/work-item controls.
All mutations were restored before the passing combined selection.

These are implementation-stage results, not independent-review, full-gate,
external-model-quality, release, or closure evidence. Rollback is an ordinary Git
revert with no migration or production-data rewrite. The parent owns review,
canonical validation, and release.

### Review-repair evidence

Independent R1 review found six defects in the initial candidate; the parent
reproduced all six before repairing them under the bounded Architect amendment.
The final amended 25-selector focused invocation passed **608 tests, 4 existing
skips**, including all **165 AD-1200 cases**, with all 247 loaded ProbOS modules
asserted inside the candidate. Log and JUnit:
`logs/gates/ordinary-1137-r1-final-focused-20260918T125603194.*`.
JUnit SHA-256: `18896537d2c23c100135c479124e403727bd1660f245749200d343b87f8f6f7d`.

New tests reach both real transport formats and both degraded-cache branches.
Native and work-item crossings compare identical transcripts while replacing or
deleting guidance, with successful same-guidance cache controls. A fixture first
misidentified legacy tool-result framing; it was corrected to the actual
`[tool_result:...]` form without changing production behavior or old tests.
The unchanged-base golden remains byte-identical. These are focused repair
results; fresh independent review and canonical release gates are still required.

R2 review verified the cache, framing, omission-history and metadata-first repairs,
then found the two residual logging/eviction defects described above. Five new
transport, real-discovery and real-loop cases independently reproduced them before
repair. The amended 25-selector selection then passed **635 tests, 4 existing
skips**, including **192 AD-1200 cases**, with 247 source imports verified.
Evidence: `logs/gates/ordinary-1137-r2-focused-20260918T134348966.*`;
JUnit SHA-256 `225dec92b2958a9f56e24ee46a52ed353e69f12699c6d9e05f9761ca4a8eac9a`.
The defensive backend-error-result test maps a real transport result to the
declared error field; it does not claim the current OpenAI parser produces it.

A separate portability probe demonstrated that the original test normalizer
treated equivalent Windows/POSIX fixture paths differently. Only normalization
of explicitly owned fixture locations was corrected, including nested JSON
strings while preserving other bytes. Four targeted checks passed: the unchanged
original golden plus three cross-platform path/data-sensitivity controls.
Evidence: `logs/gates/ordinary-1137-golden-portability-20260918T135650817.*`.
The original golden was neither regenerated nor edited. These fixture checks are
not a claim of POSIX runtime execution; hosted platform validation remains pending.

Final pre-R3 combined validation, including those portability controls:
**638 passed, 4 existing skips**, with **195 AD-1200 cases** and 247 candidate
source imports verified. Log/JUnit:
`logs/gates/ordinary-1137-final-focused-20260918T140147189.*`;
JUnit SHA-256 `7305e0f4151fc2d651ea6cedaaf9f51547797a6ccfa1acc52f3c83ef7d3988d7`.
Earlier overlapping runs remain historical evidence, not additive totals.

R3 independently verified the R2 functional repairs, then exposed redundant
validation at the declared dimensions and a test-normalizer byte-fidelity gap.
Unchanged frozen scope/target values are now reused; changed shared metadata is
validated once per distinct value. Tests assert zero repeated validations for a
stable 16-target/1,024-scope state and exactly the required validations for changed
dependencies, rather than relying on machine-dependent timing. An owned typed-state
probe measured active render/merge medians of 2.062/3.083 ms; this is not a filesystem
benchmark. The test oracle now replaces only owned-path raw spans, preserving
unrelated escape bytes even in nested JSON strings.

Final R3-repair focus: **649 passed, 4 existing skips**, including **206 AD-1200
cases**. Log/JUnit: `logs/gates/ordinary-1137-r3-final-focused-20260918T151640368.*`;
JUnit SHA-256 `09ff668d1d178316c4fcf076ec19776e88a1d84c1cafb2158324deeac841f246`.
The original golden is unchanged. Independent replacement-candidate approval
and canonical/hosted release gates remain required.

The first canonical committed-tree gate exposed three existing AD-1152 golden
failures: the legacy build cwd `<work>` acquired an invalid-target addendum.
The shared build-only applicability adapter repairs that compatibility gap;
neither existing golden nor its tests changed. All 272 targeted AD-1200/AD-1152
cases passed afterward, including the three former failures and real native/fake
SDK request-boundary controls. Evidence:
`logs/gates/ordinary-1137-compatibility-20260918T161303364.*`.
The failed canonical gate is retained as failure evidence and cannot authorize
release; a new reviewed commit and fresh canonical receipt are required.

The complete 26-selector compatibility focus passed **715 tests, 4 existing
skips**, retaining all original tests and both goldens. Log/JUnit:
`logs/gates/ordinary-1137-compatibility-final-20260918T161520156.*`;
JUnit SHA-256 `cb5c48837cece960b36b4f40b4f2431aec5264a72714be39e6db3ee91d34bf0e`.

Independent delta review caught the SDK constructor's prior empty-cwd fallback
masking raw authority. After separating those values and adding direct discovery/
call-site spies, final focus passed **716 tests, 4 existing skips**.
`logs/gates/ordinary-1137-final-seeding-20260918T163045424.*`;
JUnit SHA-256 `0bb8fa34ab8a3fe948fa6419df9e242ded0f1ef23f75aa13e90e71446b4b12c3`.
Both prior goldens remain unchanged.
