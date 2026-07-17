# AD-722b-5a - Federation avatar telemetry relay

**Status:** BUILD-READY / ARCHITECT THREE-PASS APPROVED
**Issue:** #659 (open; issue body rewrite is included below; do not mutate GitHub during architecture or build)
**Exact base:** clean `D:\ProbOS` `main` at `44a697558eae15f88df5ff64dfe53ce70a23eb9e`
**Numbering:** highest landed top-level is **AD-1123**; highest landed bug fix is **BF-672**. **AD-722b-5a is a pre-existing reserved sub-AD and changes neither ceiling.**
**Dependencies:** AD-722b/722b-3/722b-4/722b-5, BF-287, BF-672, AD-1123
**Estimated tests:** minimum 66 newly collected pytest cases in one new AD-722b-5a module, plus migration of the existing eight AD-722b-5 tests; no UI/Vitest change
**Commit subject:** `AD-722b-5a: wire federation avatar telemetry relay (closes #659)`

Wire the existing local telemetry subscription/rate surface to AD-1123's bounded one-way relay, add a closed avatar semantic contract, produce frames without requiring a browser, and terminate inbound frames in a bounded volatile runtime cache. Do not project remote frames into local WebSockets, the HXI, `AgentRegistry`, `IntentBus`, events, trust, or learning; those remain AD-722b-5b or later work.

---

## Proposed issue #659 body rewrite

Use this exact replacement body only after the Captain explicitly authorizes GitHub mutation. The Builder must not edit the issue.

```markdown
## AD-722b-5a - Federation avatar telemetry relay

**Status:** BUILD-READY
**Base:** exact clean `main` commit `44a697558eae15f88df5ff64dfe53ce70a23eb9e`
**Prerequisite:** AD-1123 shipped/green and #1040 closed
**Numbering:** pre-existing AD-722b-5a subdecision; top-level ceiling remains AD-1123 and BF ceiling remains BF-672

### Problem

AD-722b-5 shipped `FederationTelemetryRelay` subscription filtering, a 10 fps/peer cap, and a pluggable callback, but nothing in production constructs or calls it. AD-1123 now supplies `FederationBridge.relay_one_way()` and an immutable exact-topic validator/sink registry, while production still passes `relay_topics=()`.

The local avatar telemetry frames are currently built only inside the per-agent and fleet WebSocket handlers. `AvatarEventBus` merely wakes subscribers; it does not build or retain frames. Therefore callback wiring alone would remain dead whenever no browser is connected. There is also no inbound remote telemetry sink, cache, runtime read API, `origin_mesh_id` field, or UI/store surface.

### Build

1. Register one closed topic, `avatar.telemetry.v1`, through AD-1123's immutable topic registry. Its exact payload is `{agent_id, frame_type, stream_id, sequence, data}`. Validate every key, nested field, exact built-in type, enum, string grammar, finite numeric range, and list bound. Full snapshot data is the exact safe projection of `AvatarTelemetrySnapshot.to_dict()` without the duplicate `agent_id`; diff data is a non-empty allowlisted top-level subset. Before semantic validation, a federation-only detached projection maps an unsupported `dsl_summary.color_palette_hint` to `""`; it never mutates the snapshot/local WebSocket frame or broadens the wire grammar. No arbitrary nested pass-through, source/origin field, asset, profile object, URL, binary, credential, or secret is allowed.
2. Add `PeerConfig.avatar_telemetry_agent_ids`, defaulting to an empty list. It names exact local agent IDs exported to that configured peer. There is no auto-push, wildcard, crew expansion, runtime registration API, or dynamic wire subscription. Empty config creates no producer tasks and emits no frames.
3. Extract one pure snapshot/diff frame selector shared by the existing per-agent WS loop, fleet WS loop, and federation producer. Preserve the local WS JSON contract exactly.
4. When federation, avatars, and avatar telemetry are enabled and at least one explicit subscription exists, start one referenced producer task per unique subscribed local agent, capped at 64. Each task subscribes to the existing `AvatarEventBus`, emits one initial full snapshot, then races event wakeups with the existing adaptive sampling interval. It never enters the popout sampling trigger. It works with zero local WebSocket clients, coalesces wakes, enforces a 100 ms defensive cadence floor, and owns cancellation/unsubscription/restart cleanup.
5. Type `set_emit_callback` as an async `(peer_id, exact_payload) -> bool` callback and wire it to `bridge.relay_one_way(peer_id, "avatar.telemetry.v1", payload)`. Reserve the local 10 fps/peer slot before awaiting the callback. A `False` bridge admission or ordinary failure consumes that attempt slot but does not count as dispatched; only literal `True` increments the returned dispatch count. Cancellation propagates.
6. Terminate validated inbound frames in a runtime-owned volatile LRU cache capped at 256 `(source_node, agent_id)` entries. `source_node` comes only from AD-1123's sink argument. A sender-generated 32-lowerhex `stream_id` and exact sequence number provide per-stream ordering: a snapshot may establish/resynchronize a stream, a diff requires the current stream and exactly `last_sequence + 1`, and stale/duplicate/gapped diffs drop. A new stream is admitted only by a snapshot. Expose backend-only runtime read methods for future AD-722b-5b; do not register remote agents locally or add an API/UI surface.
7. Start in the order cache/sink/topic -> bridge -> typed callback -> producer after `finalize_startup()` returns. The startup helper is strict: any ordinary validation/start failure self-cleans partial tasks/subscriptions and raises. Because finalization has already set `_started=True`, logged/announced startup, and CLI `_boot_runtime` has no failed-start cleanup wrapper, `ProbOSRuntime.start()` must contain that optional telemetry failure: catch `Exception` only, log what failed plus the impact/action (telemetry disabled; boot continues), set the relay attribute to `None`, and continue to `_startup_complete=True`. Unknown configured IDs, duplicate-peer/global-cap errors, and other helper-owned configuration failures therefore remain explicit with zero surviving producer tasks/event subscriptions but do not abort the already-announced runtime. `CancelledError` and every other `BaseException` propagate after helper cleanup. Stop producer, then close bridge relay admission, then clear the volatile cache, then stop transport. Restart creates a new stream ID and no leaked tasks, event subscriptions, rate windows, or frame state.

### Privacy and governance

- Configured peers only; configured-peer admission is not cryptographic authentication.
- Export only explicitly configured exact local agent IDs.
- Derive source from the validated bridge sink argument; payload cannot author `source_node` or `origin_mesh_id`.
- Never relay inbound telemetry onward.
- No `IntentBus`, `EventType`, trust, Hebbian, consensus, episodic, registry, profile-secret, inline avatar asset, VRM URL, image, attachment, or arbitrary metadata path.
- AD-722b-5b remains the HXI/API projection of cached remote frames and the future `origin_mesh_id` badge.

### Acceptance

- A real two-mesh `organize_fleet()`/`MockNATSBus` test proves an explicitly configured agent's initial full snapshot reaches the remote cache with zero WebSocket clients.
- Exact schema, federation-only palette projection, semantic ranges, secret/privacy rejection, source ownership, ordering/resync, LRU bound, config caps, 10 fps accounting, callback outcomes, contained optional startup failure, cancellation propagation, shutdown/restart, task cleanup, and local WS parity are adversarially tested; the new module collects at least 66 cases.
- AD-1123 relay/transport behavior and hashes remain unchanged.
- Focused and blast gates pass with no new warnings; the existing avatar baseline remains 77 passed with five known BF-326 warnings, relay baseline 224 passed, and lifecycle baseline 376 passed with two known dependency deprecations.
- Track `AD-722b-5a` in PROGRESS, DECISIONS, and the roadmap without changing the AD/BF ceilings; archive both prompt files byte-preservingly.
- Commit exactly `AD-722b-5a: wire federation avatar telemetry relay (closes #659)`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### Do not build

No remote HXI/API/WS projection, `origin_mesh_id` UI field, remote-agent registry insertion, persistence/backfill, dynamic subscription protocol, acknowledgement/retry/queue, transport or bridge change, authentication/signing claim, avatar asset transfer, trust/learning, or arbitrary topic/event/intent forwarding.
```

---

## Verified root cause

1. `FederationTelemetryRelay` exists only as local plumbing. No production caller constructs it, registers subscriptions, sets its callback, starts a producer, or invokes `on_local_telemetry_frame()`.
2. Its callback is untyped and assumed successful whenever it returns without raising; the current callback returns `None`, while `FederationBridge.relay_one_way()` returns `bool` where `True` means local handoff/admission only, not remote receipt.
3. AD-1123's bridge path is now sufficient and must remain unchanged: exact immutable topics, one target, exact bounded detached payloads, a server-owned source argument to one sink, a 64/s source/topic receiver ceiling, and no response/queue/rebroadcast/learning.
4. Runtime still passes `relay_topics=()` to the sole `organize_fleet()` call, so no semantic topic is live.
5. `AvatarTelemetrySnapshot.to_dict()` has a fixed flat-of-flats shape, but the two WebSocket handlers independently duplicate initial/full/diff selection. They are the only periodic snapshot builders in production.
6. `AvatarEventBus` stores `asyncio.Event` subscribers only. `notify()` cannot create a frame and is a no-op with no subscriber. An event callback without an owned waiter task cannot satisfy zero-browser production.
7. No remote telemetry cache, runtime read method, backend API, UI store key, or `origin_mesh_id` surface exists. Inbound delivery to a no-op sink would be dead wiring.
8. Existing source and tests already establish the safe boundaries to preserve: adaptive sampling, local WS frame shapes, snapshot diff semantics, bridge topic lifecycle, configured-peer admission, and shutdown order.

The local hypothesis was falsifiable: if a non-WebSocket producer or remote sink existed, callback-only wiring could be sufficient. Searches for every snapshot builder call, event-bus subscriber, remote telemetry/cache name, and `origin_mesh_id` returned only the HTTP/WS/local-HXI surfaces listed in the verification footer. The hypothesis stands.

---

## Pinned design decisions

### DD-1 - Topic payload is a closed five-key semantic envelope

The registered topic name is exactly `avatar.telemetry.v1`. Its nested AD-1123 relay payload is an exact built-in dict with exactly:

```json
{
  "agent_id": "counselor_bridge_0_ab12cd34",
  "frame_type": "snapshot",
  "stream_id": "0123456789abcdef0123456789abcdef",
  "sequence": 0,
  "data": {}
}
```

Do not flatten snapshot fields into the topic root. The wrapper keeps frame control metadata separate from data, permits exact snapshot/diff discrimination before nested validation, and avoids adding any source/provenance key. Do not duplicate `agent_id` inside snapshot data; the current local `AvatarTelemetrySnapshot.to_dict()` includes it, so the shared frame helper removes it for the wire and restores it only in local WS/cache projections.

Top-level rules:

| Field | Exact rule |
|---|---|
| `agent_id` | exact built-in `str`, `^[A-Za-z0-9_.-]{1,128}$` |
| `frame_type` | exact built-in `str`, literal `snapshot` or `diff` |
| `stream_id` | exact built-in `str`, `^[0-9a-f]{32}$`; random per relay `start()`; ordering only, never identity/authentication |
| `sequence` | exact built-in non-bool `int`, `0 <= value <= 9_007_199_254_740_991`; increment once per produced non-empty semantic frame |
| `data` | exact built-in `dict`; snapshot or diff schema below; no subclasses |

The semantic validator must use exact built-in checks, direct fixed-key lookup after exact-key admission, finite-number checks, and fixed list/string bounds. It must return literal `True` only for the complete contract and must never mutate input. AD-1123 independently detaches/caps the complete wire before and after this validator.

#### Snapshot data

A snapshot `data` object has exactly these nine keys, matching `AvatarTelemetrySnapshot.to_dict()` minus `agent_id`:

| Field | Exact rule |
|---|---|
| `expression_resting` | `None` or one exact string in `neutral`, `gentle_smile`, `focused`, `alert` |
| `current_signals` | exact four-key object described below |
| `mouth_active` | exact `bool` |
| `applied_modulation` | `None` or exact four-key object described below |
| `dsl_summary` | `None` or exact five-key object described below |
| `last_observed_at` | exact finite built-in `float`, `0.0 <= value <= 9_007_199_254_740_991.0`; informational sender clock only, never ordering/freshness authority |
| `degraded_reasons` | exact list, at most 12 unique exact strings, each from the fixed allowlist below |
| `sampling_rate_ms` | exact non-bool built-in `int`, `250 <= value <= 2_147_483_647` |
| `sampling_tier` | exact string in `high`, `normal`, `low` |

`current_signals` has exactly:

- `trust_delta`: exact finite built-in `float` in `[-1.0, 1.0]`;
- `load`: exact finite built-in `float` in `[0.0, 1.0]`;
- `working_state`: exact `idle`, `responding`, or `blocked`;
- `tier3_alert`: exact `bool`.

`applied_modulation`, when non-null, has exactly:

- `pitch_factor`: exact finite built-in `float` in `[0.0, 2.0]`;
- `rate_factor`: exact finite built-in `float` in `[0.1, 10.0]`;
- `volume_factor`: exact finite built-in `float` in `[0.0, 1.0]`;
- `fired_rules`: exact list of at most 16 unique exact strings. Admit only the operational literals `responding_rate`, `blocked_rate_pitch`, `high_trust_pitch`, `low_trust_pitch`, `tier3_rate_volume`; fixed intent literals `intent_warm`, `intent_concerned`, `intent_excited`, `intent_apologetic`, `intent_formal`, `intent_playful`, `intent_reassuring`, `intent_neutral`; and custom literals matching `^custom_[a-z][a-z_]{0,29}$`.

`dsl_summary`, when non-null, has exactly:

- `body_type`: `slim`, `average`, or `stocky`;
- `hair_style`: `short`, `medium`, `long`, `ponytail`, `bun`, or `shaved`;
- `primary_color`: exact `^#[0-9A-Fa-f]{6}$`;
- `outfit_style`: `uniform`, `casual`, `formal`, `robe`, or `tactical`;
- `color_palette_hint`: exact empty string, CSS keyword/identifier matching `^[A-Za-z][A-Za-z0-9_-]{0,31}$`, or hex color with exactly 3, 4, 6, or 8 hex digits. CSS functions, URLs, free text, control characters, and longer values reject on the wire.

This deliberately chooses **palette policy B**. `AppearanceProfile.color_palette_hint` locally permits any CSS color and has no validator, so the federation payload builder must make a detached federation-only projection before semantic validation: when `dsl_summary` is non-null and its exact built-in string `color_palette_hint` does not match the closed wire grammar above, clone `data` and `dsl_summary` and replace only that field with `""`. This is total over every exact built-in string: a value matching the closed wire grammar is preserved exactly and every other string maps to `""`. Missing/malformed/non-string `dsl_summary` or palette fields are not repaired and still reject. The projection must be total for exact built-in snapshot/diff containers, must never accept arbitrary CSS, and must not mutate or alias the source snapshot, shared frame, previous-frame cursor, or local per-agent/fleet WebSocket output. Exact tests cover supported keyword/hex pass-through plus `rgb()`, `rgba()`, `hsl()`, `hsla()`, `color()`, `lab()`, `lch()`, `oklab()`, `oklch()`, `var()`, `url()`, controls, overlength, and free-form inputs mapping to `""` only in the outbound federation copy.

`degraded_reasons` admits only:

```text
agent_not_found
avatar_sampling_state_unavailable
crew_profile_seeded
crew_profile_default
appearance_profile_missing
dsl_not_persisted
dsl_invalid
insufficient_trust_history
trust_history_malformed
bridge_alerts_unavailable
voice_profile_missing
voice_modulation_failed
```

#### Diff data

A diff `data` object is non-empty and contains any subset of these eight snapshot keys (including all eight when all changed):

```text
expression_resting
current_signals
mouth_active
applied_modulation
dsl_summary
degraded_reasons
sampling_rate_ms
sampling_tier
```

Each present value passes the same field-specific validator as a full snapshot. `agent_id`, `last_observed_at`, unknown fields, empty diffs, nested partial objects, and arbitrary metadata reject. Existing `compute_diff()` emits whole changed top-level values, so shallow cache/WS merge remains correct.

### DD-2 - One shared frame selector, local WS parity

Add `src/probos/avatars/telemetry_frames.py`. It must not import federation, runtime, router, config, events, trust, or storage. Keep `AvatarTelemetrySnapshot` behind `TYPE_CHECKING` or a narrow structural protocol so importing the helper does not load the telemetry builder. It owns:

```python
@dataclass(frozen=True)
class AvatarTelemetryFrame:
    agent_id: str
    frame_type: Literal["snapshot", "diff"]
    data: dict[str, Any]

def select_avatar_telemetry_frame(
    snapshot: AvatarTelemetrySnapshot,
    *,
    previous_snapshot: dict[str, Any] | None,
    tick_count: int,
    diff_enabled: bool,
    diff_threshold: float,
    full_every_n: int,
    force_full: bool = False,
) -> tuple[AvatarTelemetryFrame | None, dict[str, Any] | None]: ...

def avatar_telemetry_frame_to_ws(
    frame: AvatarTelemetryFrame,
) -> dict[str, Any]: ...

def project_avatar_telemetry_data_for_federation(
  data: dict[str, Any],
) -> dict[str, Any]: ...
```

It also owns `is_safe_avatar_agent_id()`, the fixed semantic constants, the policy-B palette projector, and the snapshot/diff field validators used by the federation topic validator. One validator implementation serves both outbound and inbound topic validation; do not clone the full snapshot schema in the cache, startup, or router. The relay calls the projector only after shared raw frame selection and before semantic parsing/payload assembly. The WS adapters never call it. For an exact built-in `data` dict, it returns a fresh top-level dict; for an exact built-in `dsl_summary` dict it returns a fresh nested dict and maps only an unsupported exact-string palette hint to `""`. It does not repair malformed/missing/non-string fields or inspect container subclasses; those remain unchanged for the parser to reject. The semantic parser then returns the detached validated built-ins used by the callback/cache.

`select_avatar_telemetry_frame()` must preserve current behavior:

- first/forced frame is full;
- `ws_diff_enabled=False` is always full;
- every `full_every_n` wake is full;
- otherwise use existing `compute_diff(previous, current, threshold)`;
- empty diff returns no frame and leaves prior state unchanged;
- non-empty diff carries complete changed top-level values and advances prior state via shallow merge;
- full frame advances prior state to the complete current snapshot;
- `last_observed_at` never triggers or appears in a diff;
- a `compute_diff` ordinary exception logs context and returns a full frame, matching both current WS fallbacks;
- local WS output remains byte-shape compatible: full `{"type":"snapshot","agent_id":...,<nine fields>}` and diff `{"type":"diff","agent_id":...,"changed":{...}}`.

Refactor both existing WS loops to call this helper. Preserve every existing agent cache update, adaptive timer/event wait, ping/receive behavior, history append, Records observation, connection/popout lifecycle, exception tier, and cleanup statement. Do not route local frames through federation and do not make the helper own side effects.

### DD-3 - Explicit default-empty per-peer export config

Extend the existing `PeerConfig` with:

```python
avatar_telemetry_agent_ids: list[str] = Field(
    default_factory=list,
    max_length=32,
)
```

The list names local agent IDs this node exports to that exact `peer.node_id`. It is not a request for remote IDs. Validate every entry with the same `is_safe_avatar_agent_id()` predicate and reject duplicates. Import that helper locally inside the `PeerConfig` validator rather than adding a top-level config-to-telemetry import. Do not add a global wildcard, callsign, pool, department, crew expansion, `all`, regex, dynamic runtime mutation, or wire subscription message.

Startup additionally requires:

- at most 16 peers have a non-empty telemetry list;
- at most 64 unique local agent IDs across all lists;
- duplicate configured `peer.node_id` entries participating in telemetry reject rather than last-write-win;
- every configured ID resolves through the real public `AgentRegistry.get()` at the post-`finalize_startup()` warm-boot seam; an unknown ID is an explicit helper configuration error before producer task creation and is then contained by the optional runtime binding;
- empty lists on every peer mean no producer object/task and zero outbound telemetry;
- no tracked YAML file changes. Operators may add the field to their local config after shipment.

This is production-live and default-inert. Do not choose a runtime/public registration API. Keep `FederationTelemetryRelay.register_peer()` as construction-time configuration only; after `start()`, registration, unregistration, and callback replacement reject until `stop()`.

### DD-4 - A bounded event/timer producer is necessary and owned

A post-WebSocket-send hook alone is dead with zero browser subscribers. `AvatarEventBus.notify()` cannot await a snapshot build and schedules nothing. Therefore the existing relay gains an explicit async lifecycle and one referenced producer task per unique configured agent, never per peer.

Use narrow constructor/start injection, not a runtime back-reference:

- an async `TelemetrySnapshotBuilder = Callable[[str], Awaitable[AvatarTelemetrySnapshot]]`;
- the existing `AvatarEventBus.subscribe/unsubscribe` surface;
- the existing `AvatarSamplingStateMachine.current_rate_ms()` surface;
- primitive diff policy values from `AvatarTelemetryConfig`;
- no config object or runtime object stored in the relay.

For each unique agent:

1. subscribe its event before the initial build;
2. build and dispatch an immediate full frame;
3. clear/race the event with `asyncio.sleep(max(0.1, current_rate_ms / 1000))`;
4. coalesce repeated wakeups and never build more often than once per 100 ms per agent;
5. build through `build_telemetry_snapshot` and select through the shared helper;
6. dispatch one semantic frame to the existing relay, which iterates explicit peer subscriptions sequentially;
7. await/cancel/reap both temporary waiter tasks on every iteration;
8. on task cancellation, clean up and re-raise; on ordinary build failure, log-and-degrade and retry on the next wake/interval;
9. always unsubscribe in `finally`.

Do not call `enter_popout()` or `exit_popout()`: federation subscription must not pin an agent in HIGH sampling. DM/chain notifications still wake immediately; idle cadence remains LOW. Do not append history, write Records, mutate `_last_self_avatar_snap`, or duplicate any local WS side effect.

The relay must retain every producer task reference in a bounded dict/set, clean up partial `create_task()` failure, make `start()`/`stop()` idempotent, clear tasks/events/frame cursor/sequence/rate state on stop, and generate a new stream ID on successful restart. With no registered agents, `start()` creates zero tasks.

### DD-5 - Callback result and 10 fps accounting are exact

Replace the untyped callback contract with:

```python
TelemetryEmitCallback = Callable[
    [str, dict[str, Any]],
    Awaitable[bool],
]
```

`max_per_sec_per_peer` must be an exact non-bool built-in `int` in `[1, 10]`, default 10. Lower test/operator caps remain valid; no caller can raise this telemetry-specific ceiling above 10.

`set_emit_callback()` is a fail-fast public boundary: while stopped, accept only a callable with exactly two effective positional parameters, no variadic/keyword-only extras, and `inspect.iscoroutinefunction(callback) is True`. Do not probe-invoke it. Contain the complete callable/coroutine/signature inspection sequence: every ordinary metadata exception becomes a fresh exact `ValueError("telemetry_emit_callback_invalid")`, while lifecycle `BaseException` propagates. Reject sync functions that merely return a coroutine. While running, callback replacement rejects before inspection or mutation.

The second argument is the complete exact avatar topic payload. Production installs an async adapter that does exactly:

```python
return await bridge.relay_one_way(
    peer_id,
    AVATAR_TELEMETRY_TOPIC,
    payload,
)
```

`True` means the bridge accepted and handed the datagram to its existing transport await; it is not a receipt acknowledgement. Before sequence or rate mutation, build and validate the complete semantic frame; invalid local frame input returns zero and consumes neither. Only literal `True` increments `on_local_telemetry_frame()`'s dispatched-peer count. `False`, `None`, or another result is not success.

Replace the check-then-note rate pair with one non-awaiting monotonic claim operation. It prunes the peer's one-second deque, rejects when ten slots are present, and appends the attempted slot before the callback await. Thus concurrent agent producer tasks cannot overshoot the peer cap. A bridge `False` or ordinary callback exception consumes the attempted slot, preventing disconnected/invalid peers from creating a tight uncapped retry path. A locally filtered/unsubscribed frame consumes no slot. Clear rate state on unregister/start/stop. Keep rate keys bounded by registered peer count.

Ordinary callback exceptions log what failed, why telemetry degrades, and that the frame is dropped, without payload/keys/values. Real `asyncio.CancelledError` propagates. The test default callback returns literal `True` and preserves a test-observable dispatch log capped at 256 entries.

### DD-6 - Inbound termination is a volatile, ordered, 256-entry cache

Keep `RemoteAvatarTelemetryCache` adjacent to the federation telemetry semantic contract, not in `AgentRegistry`, UI state, or a database. Production constructs exactly one runtime-owned instance with fixed `max_entries=256`.

The AD-1123 topic sink is `cache.ingest(source_node, payload)`. It is an exact two-argument `async def`, satisfying `FederationRelayTopic`. It reparses with the same single semantic parser used by the topic validator (defense in depth, no duplicate schema), obtains source only from the sink argument, and commits no await between validation and state mutation.

Key and merge semantics:

- key is exact `(source_node, agent_id)`; same `agent_id` from two sources is two entries;
- first frame for a key must be `snapshot`;
- same-stream `sequence <= last_sequence` drops as stale/duplicate;
- same-stream `diff` requires exactly `last_sequence + 1`; a gap drops and waits for a later full snapshot;
- same-stream `snapshot` with any greater sequence replaces the full state and resynchronizes after loss;
- a changed `stream_id` is admitted only by a snapshot, which replaces the prior stream state; a diff cannot open a stream;
- diff merge is shallow over the stored full snapshot body because nested changed fields are complete values;
- `last_observed_at` is retained from the most recent accepted snapshot and is never a cache ordering/freshness input;
- local `received_at=time.time()` records receiver freshness and is not supplied by the peer;
- accepted access moves the key to the LRU tail; inserting entry 257 evicts exactly the least recently accepted key;
- invalid/stale/gapped frames do not refresh LRU position;
- cache is volatile and clears on runtime shutdown/restart; no backfill, persistence, replay window, trust, or episode.

`stream_id` and `sequence` are loss/order diagnostics for one configured sender stream, not authentication or cross-process replay protection. The next-arriving valid new-stream snapshot is authoritative for that configured source/key. A locally rate-dropped or transport-lost frame may create a sequence gap; subsequent diffs then drop until the shared every-N full snapshot resynchronizes the receiver. Do not hide gaps by accepting a non-contiguous diff.

Public cache reads return fresh detached copies so callers cannot mutate authority. Expose runtime methods with full annotations:

```python
def get_remote_avatar_telemetry(
    self,
    source_node: str,
    agent_id: str,
) -> dict[str, Any] | None: ...

def list_remote_avatar_telemetry(self) -> list[dict[str, Any]]: ...
```

Each returned record has exactly `source_node`, `agent_id`, `stream_id`, `sequence`, `last_frame_type`, `received_at`, and `snapshot`; `snapshot` restores `agent_id` plus the nine full fields. List output is deterministic by `(source_node, agent_id)`. Do not call the field `origin_mesh_id` in this backend contract; AD-722b-5b may project validated `source_node` to that UI label.

### DD-7 - Composition and lifecycle order are fixed

Add `src/probos/startup/federation_telemetry.py` with two narrow, testable composition functions:

1. `build_federation_avatar_relay_topics(*, enabled, cache) -> tuple[FederationRelayTopic, ...]` returns empty when disabled and otherwise exactly one immutable topic contract for `avatar.telemetry.v1`.
2. `start_federation_avatar_telemetry(...) -> FederationTelemetryRelay | None` validates explicit subscriptions against the real registry, constructs/configures the relay, installs the typed bridge adapter, and starts producer tasks. It returns `None` for no bridge or no non-empty subscriptions and creates no task/state in those cases.

Runtime order:

1. eagerly construct the empty volatile remote cache in `ProbOSRuntime.__init__`;
2. before the sole `organize_fleet()` call, compute topic tuple enabled only when `federation.enabled`, `avatars.enabled`, and `avatar_telemetry.enabled` are all true;
3. pass that tuple instead of the current explicit `relay_topics=()`; `organize_fleet()` and the bridge constructor/start remain unchanged;
4. after `finalize_startup()` returns and warm boot has restored designed agents, call the startup helper so configured stable IDs are resolved against the complete registry;
5. the helper must self-clean every partial producer task/event subscription/rate/stream state and raise its typed/ordinary validation or startup failure to its caller; its cleanup scope catches `BaseException` only to stop/reap and then bare-raises the original exception, so it must not swallow or normalize cancellation, unknown IDs, duplicate peers/IDs, cap violations, or task-creation failures;
6. wrap only this optional post-finalize helper call in `try/except Exception` inside `ProbOSRuntime.start()`: on success assign the returned relay; on ordinary failure log what failed, that federation avatar telemetry is disabled, and that core startup continues, then set the declared relay attribute to `None` and proceed to the existing `_startup_complete=True` assignment; do not log payload/profile values;
7. do not catch `BaseException`: task cancellation and other lifecycle exceptions propagate after helper self-cleanup;
8. shutdown closes/stops the relay first, calls `federation_bridge.stop()` to close inbound relay admission second, clears the remote cache third, then stops transport and preserves the existing later NATS order. This order prevents a late inbound frame from repopulating the cache after clear.

This containment boundary is required because `finalize_startup()` sets `_started=True`, logs `ProbOS started`, and announces startup before returning, while CLI `_boot_runtime()` directly awaits `runtime.start()` without a cleanup wrapper and `_startup_complete=True` is assigned later in `runtime.py`. Therefore an optional telemetry `Exception` must not escape after the startup announcement. Unknown configured IDs and duplicate/cap/configuration errors remain explicit in the contextual runtime log and helper exception, produce zero surviving tasks/events, set the relay attribute to `None`, and leave the boot complete. A failed/absent federation transport still logs/degrades through the existing fleet path and yields no telemetry producer. Restart uses bridge-open-before-producer and producer-stop-before-bridge. Do not edit `startup/finalize.py` or move this helper into finalization.

### DD-8 - Privacy and governance boundaries do not move

- AD-1123 configured-peer membership remains a deployment/transport ACL, not cryptographic source authentication.
- The payload has no `source_node`, `origin_mesh_id`, peer address, callback name, intent, event, target runtime method, TTL, token, auth field, profile object, `vrm_url`, image, attachment ref, asset bytes, URL, free-form notes, or metadata.
- Exact local agent IDs are selected from static config and verified through public `registry.get()` only.
- Inbound sink never calls relay/bridge again and cannot loop or forward.
- Remote identities remain cache keys only and are never registered as local agents, pools, subscribers, callsigns, crew, trust subjects, or Hebbian nodes.
- No `IntentBus`, `EventType`, event log emission, consensus, trust, Hebbian, episode, Records, history, gossip, self-model, or learning update.
- No new authentication/signature/JWT/CURVE claim. Do not revive the phantom signed-envelope design from the 2026-05-15 AD-722b-5 draft.
- No UI, TypeScript, WebSocket contract addition, backend API endpoint, or `origin_mesh_id` store field. AD-722b-5b is still separate.

### DD-9 - Tracking requires a DECISIONS entry but no new ceiling

AD-722b-5a is reserved already, so do not mint AD-1124. It now makes durable architectural choices (closed semantic schema, explicit export authority, producer lifecycle, stream ordering, remote cache), so append a dedicated `### AD-722b-5a` entry under Era V in `DECISIONS.md`. State explicitly that it is a pre-existing subdecision and AD-1123/BF-672 remain the ceilings.

---

## Ordered build

### Section 0 - Event types

None. Do not edit `src/probos/events.py` or emit runtime events.

### Section 1 - Write all AD-722b-5a tests and record red

Create `tests/test_ad722b_5a_federation_telemetry_relay.py` first. Use real `SystemConfig`, `PeerConfig`, `AgentRegistry`, `AvatarEventBus`, `AvatarSamplingStateMachine`, `FederationRelayTopic`, `MockNATSBus`, `NATSFederationTransport`, and `organize_fleet()` at their boundaries. Narrow typed fakes may supply a snapshot builder or record a callback. Do not use `MagicMock`, `Mock`, or `AsyncMock` for config, registry, bridge, relay topic, bus, or transport.

Before production edits run the headline:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_red_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py::test_no_browser_two_mesh_composition_delivers_initial_snapshot_to_remote_cache -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected red: import/collection failure for the new frame/startup/cache surface or an assertion that production still passes an empty topic tuple/never starts the relay. Record the exact command and failure. Do not weaken the test.

Also run a focused red set for schema rejection, callback `False` accounting, diff-before-snapshot cache rejection, zero-subscription zero-task behavior, and producer stop/unsubscribe. At least one test per new production boundary must fail for the intended missing behavior before implementation; report any already-green invariant honestly.

### Section 2 - Add the shared local frame contract

Create `src/probos/avatars/telemetry_frames.py` to DD-1/DD-2. Refactor only the frame selection/send construction in the two `routers/agents.py` loops. Preserve all surrounding side effects and output shape. Run:

- the new pure frame/schema tests;
- `tests/test_ad722b_3_snapshot_diff.py`;
- the existing per-agent/fleet WS tests.

### Section 3 - Close and type the federation telemetry relay

Modify `src/probos/federation/telemetry_relay.py` to:

- retain `PeerTelemetrySubscription` and the existing public subscription/filter purpose;
- add the exact topic constant/parser/builder, typed callback, monotonic attempt-claim rate cap, stream/sequence state, producer lifecycle, and remote cache;
- keep subscription configuration immutable while running;
- add no runtime/IntentBus/EventType/transport implementation import;
- call no bridge method directly; the startup adapter owns that dependency.

Migrate `tests/test_ad722b_5_federation_telemetry.py` from the old `None` callback/log contract to the typed bool/exact payload contract without reducing its eight tests. Keep the existing filter/multicast/rate/recovery/unregister coverage and add old-surface regression assertions where they fit; the new module owns the broader cases.

### Section 4 - Add static config and production composition

Modify `PeerConfig` only as DD-3. Add `src/probos/startup/federation_telemetry.py` to DD-7. Modify runtime to:

- declare/eagerly construct cache and relay attributes;
- pass the computed topic tuple at the existing Phase-3 composition seam;
- start the relay only after `finalize_startup()` and contain only ordinary `Exception` from that optional helper call;
- log the exact helper reason plus impact/action, set the relay attribute to `None`, and continue to the existing `_startup_complete=True` assignment;
- allow `CancelledError` and every other `BaseException` to propagate after helper cleanup;
- expose the two read methods.

Do not modify `organize_fleet()` itself; AD-1123 already threaded `relay_topics` correctly. Do not move federation startup phases. Do not edit `startup/finalize.py`; the post-finalize containment belongs in `ProbOSRuntime.start()`.

### Section 5 - Close lifecycle before bridge shutdown

Modify `startup/shutdown.py` only around the existing federation stop block. Stop/reap the telemetry producer first, stop the bridge second so inbound relay admission is closed, clear the remote cache third, then stop transport exactly as before. Clear the producer runtime reference after its stop. Do not alter BF-598 idempotency, integrity markers, pool order, or NATS teardown.

### Section 6 - Run focused, blast, full, and source audits

Run every gate below, editor diagnostics on changed Python files, `compileall` or equivalent targeted compile, source scans, diff checks, and hash checks. No tracker/archive/commit step is allowed before all gates pass and Architect re-review approves the implementation.

### Section 7 - Conditional closeout

Only after green implementation review:

1. prepend one concise shipped block to `PROGRESS.md`, naming #659, the exact subscription/schema/producer/cache boundaries, no-browser proof, final gate counts/warnings, unchanged AD-1123/BF-672 ceilings, no UI/learning, and configured-peer-not-crypto-auth posture;
2. append `### AD-722b-5a (2026-07-17) - federation avatar telemetry relay (#659)` under Era V in `DECISIONS.md` with Context / Decision / Tests and the unchanged ceilings;
3. update the roadmap AD-722b-5a row to SHIPPED/CLOSED and leave AD-722b-5b explicitly separate for HXI/API projection and `origin_mesh_id` badge;
4. move both active prompts byte-preservingly to `prompts/archive/`, verify pre/post SHA-256, and do not reconstruct them;
5. stage only the exact final allowlist;
6. commit exactly `AD-722b-5a: wire federation avatar telemetry relay (closes #659)`;
7. do not push or mutate GitHub unless the Captain separately instructs it.

---

## Required tests

The new module must collect at least 66 cases and cover every branch below. Parameterization is encouraged where it keeps one behavior per case.

### A. Headline production composition

1. `test_no_browser_two_mesh_composition_delivers_initial_snapshot_to_remote_cache`: two real organized bridges over one shared started `MockNATSBus`; explicit node-A config exports one real registry agent to node B; both bridges register the real avatar topic; start through the real startup helper; no TestClient/WebSocket; node B receives exactly one cache snapshot with server-owned `source_node=node-a`; decoy source/agent/cache keys stay absent.
2. Event notify produces a diff or periodic full through the same path; receiver merges it.
3. Receiver-only node with empty outbound subscription still has the topic/cache and can receive; it starts no producer task.
4. Default `SystemConfig()`/empty peer lists leave topic/producer/network work inert.

### B. Exact semantic schema and privacy

5. Exact valid snapshot and valid diff accept on sender and receiver.
6. Missing/extra/non-string keys and dict/list/string/numeric subclasses reject without override invocation.
7. Agent ID exact 1/128 boundaries accept; empty, 129, slash, backslash, colon, whitespace, control, and subclass reject.
8. Frame type exact literals only.
9. Stream ID exact 32 lowerhex only; uppercase/wrong length/subclass reject.
10. Sequence 0/max boundaries accept; bool/negative/over-max/subclass reject.
11. Snapshot requires all nine exact fields; diff is non-empty, only eight allowed fields, and excludes `agent_id`/`last_observed_at`.
12. Every nullable, enum, finite float, and integer boundary pair is tested; NaN/Inf and wrong exact numeric type reject.
13. `current_signals`, modulation, DSL summary, fired rules, degraded reasons, the narrow direct wire palette validator, and nested exact-key matrices pass/fail as pinned; direct wire payloads containing CSS functions still reject.
14. `test_federation_palette_projection_supported_values_preserved`: empty, identifier/keyword, and 3/4/6/8-digit hex palette hints survive federation projection exactly.
15. Parameterized `test_federation_palette_projection_unsupported_maps_empty_only_on_wire`: valid local `rgb()`, `rgba()`, `hsl()`, `hsla()`, `color()`, `lab()`, `lch()`, `oklab()`, and `oklch()` plus `var()`, `url()`, controls, overlength, and free-form strings project to `""`; the source snapshot/frame, prior cursor, and per-agent/fleet WS outputs retain the original value.
16. `test_federation_palette_projection_malformed_shape_still_rejects_without_aliasing`: missing/non-string palette, malformed/non-dict DSL, and dict/string subclasses are not repaired or invoked; parser rejects, callback/cache are untouched, and every accepted projection is detached.
17. Unknown nested dict/list content, free-form metadata, source/origin fields, profile/VRM/URL/notes/assets/images/attachments/binary/data URLs and every AD-1123 forbidden secret key/prefix reject before callback/cache.
18. Semantic maximum payload passes the complete AD-1123 finalizer and stays below 32,768 final bytes; no arbitrary padding field can be added.
19. Parser returns detached exact built-ins and does not mutate/alias caller data.

### C. Shared frame selector and local parity

20. First/forced/disabled/every-N full behavior.
21. Significant diff, insignificant empty suppression, timestamp-only suppression, and shallow prior merge.
22. Diff exception falls back to full with one contextual warning.
23. Full/diff WebSocket adapters exactly match current per-agent and fleet JSON shapes, including unprojected local CSS palette values.
24. Existing per-agent/fleet endpoint tests remain unchanged and green; history, Records, agent cache, ping, popout, connection, and cleanup behavior remain observable.

### D. Subscription and callback/rate semantics

25. Default-empty config, valid list, duplicate IDs, invalid IDs, 33rd ID.
26. Duplicate telemetry peer node, 17th non-empty peer, and 65th unique agent reject before task creation; no truncation.
27. Unknown configured local ID rejects only at the post-finalize registry seam and before task creation.
28. Exact agent filter and same-agent multicast; unsubscribed peers consume no rate slot.
29. Constructor accepts exact caps 1 and 10; rejects bool/0/11/non-int. First ten attempts per peer admit and eleventh drops; another peer is independent; one-second recovery; map bounded/cleared.
30. Callback literal `True` counts dispatched; `False`/`None` do not; ordinary exception degrades; cancellation propagates.
31. Callback registration accepts an exact async function/decorated async wrapper and rejects wrong arity, variadic, keyword-only extra, sync, sync-coroutine-wrapper, and hostile ordinary metadata with exact `telemetry_emit_callback_invalid`; lifecycle `BaseException` propagates; no callable is invoked.
32. `False` and ordinary failure still consume the reserved attempt slot; concurrency cannot exceed ten callback entries for one peer.
33. Callback and subscription mutation while running reject before inspection/mutation; after stop reconfiguration is allowed.
34. Invalid semantic frames consume no sequence/rate/callback work; valid payload sequences advance only for produced non-empty semantic frames and are common across peer copies of one frame.

### E. Producer lifecycle and zero-browser operation

35. One producer task per unique agent, not per peer; exact finite task cap.
36. Subscribe-before-initial, immediate full, event wake, adaptive timer wake, 100 ms floor/coalescing.
37. Producer never enters popout and never changes sampling refcounts.
38. No subscriptions creates no task/event subscriber/callback traffic.
39. Stop cancels/reaps every task and waiter, unsubscribes events, clears rates/cursors/sequences, and is idempotent.
40. Start-stop-start creates a new stream ID, initial full, and no leaked old event/task/state.
41. Partial `create_task()` failure cancels/reaps prior tasks, unsubscribes, leaves stopped/empty, and permits restart.
42. Ordinary snapshot build failure logs/degrades and retries; real cancellation propagates.
43. Source scan proves no history/Records/agent-cache/popout/IntentBus/EventType/trust/Hebbian/episode/queue/retry task is added.

### F. Remote cache

44. Snapshot opens; diff-before-snapshot drops.
45. Contiguous diff merges; duplicate/stale/gapped diff drops without LRU refresh.
46. Greater same-stream snapshot resynchronizes after gap.
47. New-stream diff drops; new-stream snapshot replaces; old snapshot body cannot alias public read output.
48. Composite source+agent identity prevents collisions.
49. Entry 257 evicts exact LRU; invalid frames do not evict/refresh; cardinality remains 256.
50. Public `get`/`list` shape is exact/deterministic and returns detached copies.
51. Source comes from sink argument only; payload cannot spoof it; registry remains unchanged.
52. Shutdown clear and restart empty-cache behavior.

### G. Composition, shutdown, and invariants

53. Real topic factory disabled/enabled shape; exact validator and async sink signatures satisfy AD-1123 constructor checks.
54. Runtime source/behavior proves computed topic tuple replaces only the old explicit empty tuple and helper starts after `finalize_startup()`; `startup/finalize.py` remains byte-identical.
55. Startup helper with absent bridge or empty subscriptions returns `None` with zero tasks; ordinary transport unavailability preserves existing federation degrade behavior.
56. `test_runtime_contains_federation_telemetry_start_exception_and_completes_boot`: execute the real `ProbOSRuntime.start()` post-finalize binding (not a source-inspection predicate); fault a narrow dependency inside the real startup helper so it raises an ordinary typed error, then prove runtime returns normally, logs the exact reason plus `telemetry disabled`/`startup continues`, sets the relay attribute to `None`, and reaches `_started is True` plus `_startup_complete is True`.
57. Parameterized `test_runtime_contains_telemetry_configuration_error_without_resources`: unknown configured ID, duplicate telemetry peer node, 17th non-empty peer, and 65th unique-agent helper errors remain explicit in the warning, create zero surviving producer tasks/temporary waiter tasks/`AvatarEventBus` subscriptions/rate/stream state, leave the relay attribute `None`, and complete startup. Per-list duplicate/invalid/33rd-entry rejection remains the separate parse-time `PeerConfig` coverage in test 25.
58. `test_runtime_contains_partial_telemetry_start_failure_without_leak`: through real `ProbOSRuntime.start()` and the real helper, force a narrow collaborator failure after at least one producer task/event subscription exists; helper cleanup completes before the error reaches runtime, runtime contains the ordinary error, all relay/task/event/rate/stream state is empty, and `_startup_complete is True`.
59. `test_runtime_telemetry_start_cancellation_propagates`: through real `ProbOSRuntime.start()` and the real helper, make a narrow awaited collaborator raise real `asyncio.CancelledError` after at least one telemetry task/event subscription exists; helper cleanup leaves no task/event/rate/stream state, runtime propagates cancellation, emits no optional-failure warning, and does not set `_startup_complete=True`. Replacing the whole helper with a raising fake is insufficient because it does not prove cleanup.
60. `test_runtime_telemetry_start_baseexception_propagates`: the same real-helper shape with a sentinel `BaseException` also cleans, escapes the runtime binding unchanged, and is not normalized into optional telemetry degradation.
61. Shutdown ordering records producer stop -> bridge stop -> cache clear -> transport stop; a late inbound frame after bridge stop cannot repopulate cache; BF-598 re-entry remains unchanged.
62. Bridge, `federation/relay.py`, NATS/ZeroMQ/mock transport files, `startup/finalize.py`, and AD-1123 test remain byte-identical to pinned SHA-256/AST guards.
63. No remote cache write changes local registry count, subscribers, trust, Hebbian, episodes, events, or local WS store.
64. Logs contain no payload, field values, secrets, serialized body, profile data, or full agent snapshot.

---

## Exact file allowlist

### Production

- `src/probos/avatars/telemetry_frames.py` - NEW pure frame selector, policy-B federation palette projection, and one semantic field-validation authority
- `src/probos/federation/telemetry_relay.py` - typed relay callback/rate, closed projected topic payload, bounded producer lifecycle, remote cache
- `src/probos/startup/federation_telemetry.py` - NEW narrow topic/start composition helpers
- `src/probos/config.py` - one default-empty field on `PeerConfig`
- `src/probos/runtime.py` - cache/topic/start/read wiring
- `src/probos/routers/agents.py` - replace duplicated frame selection with shared helper only
- `src/probos/startup/shutdown.py` - stop producer, stop bridge, clear cache, then stop transport

### Tests

- `tests/test_ad722b_5a_federation_telemetry_relay.py` - NEW complete red/green/adversarial suite
- `tests/test_ad722b_5_federation_telemetry.py` - migrate existing eight callback/rate tests to the pinned bool/exact-payload contract

### Conditional closeout

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- move, without rewriting, these two prompts to `prompts/archive/`

No other source, test, config, YAML, UI, desktop, dependency, workflow, data, log, or tracker file is authorized.

### Frozen/forbidden files

These must remain byte-identical to exact base:

- `src/probos/federation/relay.py` - SHA-256 `6809979d39f65dcbe0c7c510dff5994c725e6b3620ed0e72aa1aa590d460c70e`
- `src/probos/federation/bridge.py` - SHA-256 `690a6d00a32b7e51cd25777d9b49db40433ea3269d104ca8d93393bc47b0b30f`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`
- `src/probos/startup/fleet_organization.py` - SHA-256 `7b9e17dd24bf020ef5c2797d3601c97fac62996c5c5fa53a21a1c2a6494abbc8`
- `src/probos/startup/finalize.py` - SHA-256 `211f7428270b82660cbd35fd8efee026e9a9f070511315967392ae998ee1992b`
- `src/probos/avatars/telemetry.py` - SHA-256 `59986fad1161664d5f6d2d2e13258fbe06767fdcac0f4cd4cf56f61feb3a23e7`
- `src/probos/avatars/events.py` - SHA-256 `d83e655966abf91747d47bba08c1fbbb5ab0d655f9d6a38087ea9f504a8ee233`
- `src/probos/avatars/sampling_state.py` - SHA-256 `decd156546628a9c289fe0f46371a719bc73c3e17364e430933cc687eb905a00`
- `src/probos/avatars/snapshot_diff.py` - SHA-256 `7124edaf5dfed5f15268810e8b73638d680cf83053d3f37ad8143e6f365886ab`
- `tests/test_ad1123_bounded_federation_relay.py` - SHA-256 `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5`
- `src/probos/types.py`, `src/probos/events.py`, `src/probos/protocols.py`, `src/probos/mesh/intent.py`, `src/probos/mesh/nats_bus.py`
- all `ui/**`, `desktop/**`, `config/*.yaml`, `pyproject.toml`, dependency/lock files

---

## Gates

All commands run from `D:\ProbOS`, use a unique isolated `PROBOS_DATA_DIR`, local/offline embeddings, no pytest cache, serial `-n 0` except the final parallel gate, `--timeout=90`, short traceback, and `RuntimeWarning` as error. Do not use `-n auto`.

### Focused red/green module

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_focused_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py tests/test_ad722b_5_federation_telemetry.py tests/test_ad722b_3_snapshot_diff.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected: all collected pass; new module has at least 66 cases; existing AD-722b-5 remains eight tests; no warning.

### Gate 1 - Relay/federation blast

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_gate1_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py tests/test_ad1123_bounded_federation_relay.py tests/test_ad722b_5_federation_telemetry.py tests/test_federation.py tests/test_federation_nats.py tests/test_ad637a_nats_foundation.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Pinned existing baseline: **224 passed, no warnings**. Expected: `224 + new AD-722b-5a collected count`, no warning.

### Gate 2 - Directed/transport parity blast

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_gate2_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py tests/test_ad1123_bounded_federation_relay.py tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_federation.py tests/test_federation_nats.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Pinned existing baseline from the green AD-1123 closeout: **466 passed, no warnings**. Expected: `466 + new AD-722b-5a collected count`, no warning.

### Gate 3 - Local avatar/WS parity

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_gate3_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722_avatar_telemetry.py tests/test_ad722b_websocket_push.py tests/test_ad722b4_fleet_telemetry.py tests/test_ad722b_3_snapshot_diff.py tests/test_ad722b_5_federation_telemetry.py tests/test_bf626_ws_safe_close.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Pinned baseline independently rerun on 2026-07-17: **77 passed, exactly five known BF-326 warnings**. Expected unchanged: 77 and only those five warnings.

### Gate 4 - Runtime/config/shutdown blast

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_gate4_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py tests/test_ad1123_bounded_federation_relay.py tests/test_ad479_federation_hardening.py tests/test_ad480_federation_mcp_a2a.py tests/test_ad443_mobility.py tests/test_runtime.py tests/test_ad447_phase_gates_pool_group.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Pinned baseline independently rerun on 2026-07-17: **376 passed, exactly two third-party dependency deprecations**. Expected: `376 + new AD-722b-5a collected count`, only those two warnings.

### Final full parallel gate

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_full_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/ -p no:cacheprovider -n 4 --dist=loadfile -q --tb=short } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

If a parallel failure occurs, rerun that exact file at `-n 0`. Pass in serial means environmental xdist noise and must be reported; fail in serial is a real blocker. Do not quarantine or edit unrelated tests under this AD.

---

## Source, privacy, diff, and hash audits

Before closeout:

```powershell
git diff --check
git diff --stat
git status --short
git diff --name-only
git diff --diff-filter=D --name-only
```

No deletion is allowed before prompt archival. At closeout the only allowed path removals are the two active prompt paths, paired with byte-identical additions under `prompts/archive/`.

`git diff -- src/probos/startup/finalize.py` must be empty. The optional post-finalize failure boundary is implemented only in `ProbOSRuntime.start()`; no finalization edit is authorized.

Verify frozen hashes from the allowlist. Run source scans over changed production for these forbidden executable shapes:

```text
IntentMessage
IntentBus
EventType
emit_event
record_outcome
hebbian
episodic
register(
registry.register
origin_mesh_id
vrm_url
attachment
image
bytes
send_to_peer
relay_one_way
create_task
Queue(
```

Expected carve-outs:

- `relay_one_way` occurs only in the typed startup adapter;
- `create_task` occurs only in the bounded producer lifecycle and every task reference is retained/reaped;
- textual comments/tests may name forbidden boundaries to assert absence;
- no other executable occurrence is allowed without Architect review.

Recompute SHA-256 for every changed/new implementation/test file and both prompts. Verify AD-1123 bridge/relay/fleet/test hashes remain exact. Inspect logs from adversarial tests to prove no payload/profile/secret value appears.

---

## Hard-stop conditions

1. HEAD, branch, origin, or initial worktree differs from the exact execution contract.
2. Any frozen AD-1123 bridge/relay/transport/fleet/test hash differs before or after build.
3. Correct implementation requires editing `startup/finalize.py`, `FederationBridge`, AD-1123 `relay.py`, a transport, `FederationMessage`, `IntentBus`, `EventType`, `AgentRegistry`, UI, API routes, or a config YAML.
4. A remote source/origin field must be accepted from payload content.
5. The full or diff data needs arbitrary nested pass-through, raw profile data, a URL, avatar/attachment bytes, or an unknown field; the wire accepts arbitrary CSS; or unsupported local palette syntax cannot be projected to `""` on a detached federation-only copy while local WS data remains unchanged.
6. Dynamic wire subscription, wildcard expansion, remote registration, acknowledgement, response, retry, queue, durable stream, replay persistence, or relay-onward becomes necessary.
7. The producer cannot work with zero WebSocket clients, or it starts before final warm boot makes configured stable IDs resolvable.
8. A task/event subscription/rate window survives stop, helper failure, contained runtime failure, or restart; the helper swallows an ordinary validation/start failure instead of cleaning and raising; runtime lets that ordinary optional failure escape after startup announcement; runtime fails to reach `_startup_complete=True`; or runtime catches cancellation/another `BaseException`.
9. `False` bridge admission is counted as dispatched, or failed attempts bypass the 10 fps capacity.
10. Remote frames mutate local registry, subscribers, trust, Hebbian, episodes, events, history, Records, or HXI state.
11. Existing local WS shape, sampling trigger, history/Records behavior, or the 77-test avatar baseline changes.
12. Any new warning appears in focused/blast gates, or an unchanged test fails serially.
13. More than the exact allowlist is needed; return the missing seam to Architect instead of improvising.
14. Original red-before evidence is missing/fabricated, or tests were weakened after red.
15. Trackers would mint AD-1124/change the AD or BF ceiling, omit the DECISIONS subentry, or claim cryptographic authentication.
16. Prompt archival cannot preserve exact pre-move hashes.
17. Builder is asked to push, close/edit #659, or perform any GitHub mutation without separate Captain instruction.

---

## What this does not change

- AD-1123 generic relay protocol, validator registry, envelope, rates, bridge lifecycle, transport serialization, and cancellation.
- Legacy federation intent RPC, directed DMs, attachments, gossip, peer trust, or cluster monitoring.
- Local telemetry snapshot values, HTTP endpoint, per-agent/fleet WS JSON, auth, adaptive sampling, history, Records, or HXI state.
- Remote agent discovery, registry, callsigns, pools, trust, Hebbian, consensus, episodic memory, learning, or self-model.
- Authentication/signatures/JWT/CURVE/NATS account policy.
- Remote telemetry API/SSE/WS/UI/store, `origin_mesh_id` badge, canvas nodes, or AD-722b-5b.
- Persistence, history, backfill, replay protection, ack/retry, delivery guarantee, durable queue, or stream protocol.
- Avatar/VRM/image/attachment asset distribution.
- Dependencies, packaging, YAML examples, desktop, or commercial overlay.

---

## Acceptance criteria

1. `avatar.telemetry.v1` is one immutable AD-1123 topic with the exact five-key semantic payload and every nested field/type/range pinned above.
2. One shared helper owns full/diff frame selection and both local WS loops preserve their exact behavior and JSON shape.
3. `PeerConfig.avatar_telemetry_agent_ids` is default-empty, exact, finite, duplicate-free, local-ID-only, and static; no automatic or dynamic subscription exists.
4. Production with all-empty subscription lists creates no producer task and emits no frame; configured production works with no browser WebSocket.
5. Producer tasks are bounded, referenced, event/timer driven, cadence-capped, cancellation-safe, restartable, and never alter popout/history/Records/agent cache.
6. Typed callback calls only `bridge.relay_one_way(peer_id, "avatar.telemetry.v1", payload)`; literal `True` is dispatched, failed attempts consume rate capacity, and cancellation propagates.
7. Receiver source is exclusively AD-1123's validated sink argument; payload cannot spoof source/origin, and inbound data is never relayed onward.
8. Volatile cache uses composite identity, strict snapshot/diff order/resync, local receive time, detached reads, deterministic list output, and exact 256-entry LRU eviction.
9. Runtime exposes backend-only read methods; no API/UI/WS/registry projection is added.
10. Startup order is cache/sink/topic -> bridge -> callback -> post-finalize producer. The strict helper cleans and raises; `ProbOSRuntime.start()` contains only ordinary optional telemetry `Exception`, logs reason/impact/action, sets relay `None`, and still reaches `_startup_complete=True`; cancellation/other `BaseException` propagates. Shutdown is producer -> bridge (closes inbound admission) -> cache clear -> transport -> existing NATS order; failures/restarts leak nothing.
11. No intent/event/trust/Hebbian/consensus/episode/learning/profile-secret/inline-asset path exists.
12. Headline uses real organized bridges and shared `MockNATSBus` to prove zero-browser end-to-end delivery into the remote cache.
13. Every required adversarial, bounds, privacy, palette-projection, ordering, rate, lifecycle, runtime-containment, cancellation, and parity test passes; new module collects at least 66 cases.
14. Focused gate, Gates 1-4, and full parallel gate pass with only the pinned warning baselines.
15. Frozen AD-1123, transport, and `startup/finalize.py` hashes remain exact; final diff contains only the allowlist and no unauthorized deletion.
16. PROGRESS, DECISIONS, and roadmap accurately close the reserved sub-AD/#659 while AD-1123 and BF-672 remain the ceilings.
17. Both prompts move byte-preservingly to archive; final commit subject is exact; Builder performs no push/GitHub mutation.
18. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-07-17)

Exact clean HEAD: `44a697558eae15f88df5ff64dfe53ce70a23eb9e` (`AD-1123: add bounded federation one-way relay`). Git status was empty before drafting. Issue #659 was read in full through GitHub and is OPEN; its body is the old two-paragraph forward marker.

```text
PROGRESS.md:3
  AD-1123 shipped; production relay registry empty; #659 unblocked/open;
  AD-1123 and BF-672 are the ceilings.
DECISIONS.md:13-19
  AD-1123 exact one-way relay decision and explicit child scope.
DECISIONS.md:5897-5917
  AD-722b-5 local callback/rate surface and reserved 5a/5b markers.
docs/development/roadmap.md:669-672
  AD-722b-5 local-only, AD-1123 shipped, AD-722b-5a open, 5b future UI.

src/probos/federation/telemetry_relay.py:30-130
  FederationTelemetryRelay, register/unregister, untyped set_emit_callback,
  on_local_telemetry_frame, post-success rate note, default None callback.
tests/test_ad722b_5_federation_telemetry.py:1-137
  Eight old local-only tests and four-argument None callback contract.

src/probos/federation/relay.py:25-30,66-145,174-383
  Fixed generic bounds, FederationRelayTopic, exact callable registry,
  bounded detacher/finalizer, safe node/topic predicates.
src/probos/federation/bridge.py:874-1035,1330-1444
  Constructor relay_topics tuple, bridge start/stop, relay_one_way -> bool,
  terminal inbound branch, source/topic rate and exact sink invocation.
src/probos/startup/fleet_organization.py:29-46,159-233
  organize_fleet already accepts relay_topics and passes it before bridge.start.
src/probos/runtime.py:1946-1964
  Sole production organize_fleet call explicitly passes relay_topics=().
src/probos/runtime.py:2521-2579
  Runtime directly awaits finalize_startup(), performs additional post-finalize
  wiring, and sets _startup_complete=True only at the tail.
src/probos/startup/finalize.py:4754-4802,5271
  Finalization sets runtime._started=True, logs the system started event and
  ProbOS started message, attempts the Ward Room startup announcement, and
  logs finalize complete before returning.
src/probos/__main__.py:496-587
  CLI _boot_runtime constructs the runtime and directly awaits runtime.start()
  without a failed-start cleanup wrapper.
src/probos/startup/shutdown.py:912-918
  Bridge currently stops before transport; producer must precede both.

src/probos/avatars/telemetry.py:286-393,586-822
  Exact nested snapshot dataclasses, to_dict projection, and sole builder.
src/probos/avatars/dsl.py:26-132
  Body/hair/outfit/expression enums and primary-color grammar.
src/probos/crew_profile.py:187,251-280,442-474
  Custom-emotion grammar/max and palette hint source; AppearanceProfile says
  any CSS color and from_dict performs no palette validation, so policy B
  projects unsupported exact strings to empty only on the federation copy.
src/probos/avatars/snapshot_diff.py:15-72
  Timestamp skip, top-level complete changed values, shallow-merge semantics.
src/probos/avatars/events.py:32-80
  Event-only subscriber registry; notify is no-op without subscribers.
src/probos/avatars/sampling_state.py:50-145
  Existing DM/chain/popout counts and current_rate_ms; relay must not popout.
src/probos/runtime.py:531-570
  Runtime eagerly owns sampling state, event bus, connection manager/history.
src/probos/routers/agents.py:1880-2139,2158-2360
  Per-agent and fleet handlers are the only periodic snapshot/full/diff loops.
src/probos/cognitive/cognitive_agent.py:2816-2826,4371-4393
  Chain/reply event notifications.
src/probos/cognitive/dm/reply_pipeline.py:1706-1721
  DM exit and event wake.

src/probos/config.py:1388-1392,2173-2391,3045-3074
  PeerConfig has only node_id/address; avatar rates/diff fields and federation
  peer list exist; no telemetry subscription config exists.
src/probos/substrate/identity.py:14-39
  Deterministic local IDs use safe underscore/hex shape.
src/probos/substrate/registry.py:18-77
  Public get/all APIs; no remote-agent surface.
src/probos/avatars/telemetry_history.py:24-36
  Existing local safe agent path grammar precedent.

ui/src/store/useStore.ts:322-330
  Only local avatarTelemetry Map exists.
ui/src/avatars/useFleetAvatarTelemetry.ts:1-66
  Only local fleet WS frame consumer exists.
Workspace grep for remote telemetry cache/UI/store/origin_mesh_id:
  zero production hits.

tests/test_ad1123_bounded_federation_relay.py
  133 collected AD-1123 cases at shipped closeout; bridge/transport AST and
  immutable empty-production registry precedents.
tests/test_ad722_avatar_telemetry.py,
tests/test_ad722b_websocket_push.py,
tests/test_ad722b4_fleet_telemetry.py,
tests/test_ad722b_3_snapshot_diff.py,
tests/test_bf626_ws_safe_close.py
  Existing snapshot, WS, event, diff, cleanup, and BF-287 surfaces read.

Empirical baseline reruns on exact HEAD:
  relay/federation Gate 1: 224 passed, no warnings;
  local avatar Gate 3: 77 passed, exactly 5 BF-326 warnings;
  runtime/lifecycle Gate 4: 376 passed, exactly 2 dependency deprecations.

Archived AD-1123 prompt SHA-256:
  727fda6b31eb290fd629bde9d0ec57eaca1e7e53122f787589bd72ef059c68c4
Archived AD-1123 execution SHA-256:
  b8a58577e97e762f9d7da89d7035f76cfd80dacbe48db690ae18ee7085fcec21
Frozen startup/finalize.py SHA-256:
  211f7428270b82660cbd35fd8efee026e9a9f070511315967392ae998ee1992b
```

Every concrete pre-existing API/path/signature used by this prompt maps to the live evidence above. New entities are introduced explicitly by this prompt and are not treated as missing pre-build APIs.

---

## Architect three-pass self-review

The original three passes below record the first draft review. They are superseded by the correction re-review appended after them.

### Pass 1 - Required correctness

**Verdict:** APPROVED. The issue is build-ready. The schema is closed field-by-field; outbound authority is explicit/default-empty; zero-browser production is real; inbound termination is bounded/non-no-op; source ownership, rate accounting, sequence/resync, startup/shutdown, and no-loop/no-learning are pinned. No unresolved design fork remains.

### Pass 2 - Recommended engineering quality

**Verdict:** APPROVED. One shared frame helper removes the existing WS duplication without coupling federation to routers. Startup uses narrow injected callbacks and public registry APIs. Tasks are finite/referenced/cancellation-safe. Cache is volatile and bounded. No database, dependency, transport, bridge, UI, or broad runtime handle is introduced.

### Pass 3 - Verification and dispatch readiness

**Verdict:** APPROVED pending only Builder red/green execution. Exact base, ceilings, issue state, source seams, old tests, archived AD-1123 contracts/hashes, empirical gate baselines, file allowlist, frozen paths, closeout, commit subject, and hard stops are all specified. The separate execution contract is binding for tree/Git/GitHub discipline.

## Correction re-review (2026-07-17)

### Re-review pass 1 - Required correctness

**Verdict:** APPROVED. C1 is corrected at the real lifecycle boundary: the helper remains strict/self-cleaning, while only its post-finalize call is contained by `ProbOSRuntime.start()` with `except Exception`; explicit configuration reasons remain logged, `_startup_complete=True` remains reachable, and cancellation/other `BaseException` propagate. `startup/finalize.py` is frozen and outside the allowlist. C2 selects policy B with a total exact-string projection, direct wire validation remains closed, and local WS data remains unchanged.

### Re-review pass 2 - Recommended engineering quality

**Verdict:** APPROVED. The projection is one detached pure helper shared by outbound semantic assembly, not an open CSS parser. Runtime containment owns only optional-service policy; helper cleanup still owns tasks/subscriptions/rates/stream state. The minimum new-module floor is 66, with explicit ordinary-error containment, unknown/duplicate/cap, partial-start leak, cancellation, sentinel-`BaseException`, supported-palette, unsupported-palette, malformed-shape, and local-parity coverage.

### Re-review pass 3 - Verification and dispatch readiness

**Verdict:** APPROVED pending Builder red/green execution. Exact HEAD `44a69755`, issue-body rewrite, allowlist, frozen finalize/AD-1123 surfaces, gates/count formulas, no AD-1124, no bridge/transport/UI/API change, and two-document binding are internally consistent. The execution document must bind the final SHA-256 of this corrected main prompt.

---

# HIGHEST-PRECEDENCE CONTINUATION/CORRECTION PACKET (2026-07-17)

**Authority:** This packet supersedes every conflicting status, frozen-test hash, test allowlist, unchanged-test hard stop, count formula, and execution-order clause above. Its authority is limited to the exact live continuation and corrections below. Every production/federation primitive freeze, privacy/security assertion, architectural boundary, closeout restriction, and Git/GitHub prohibition remains binding.

**Verdict:** CONDITIONAL CONTINUE. Builder Sections 1-5 are accepted as the live review point. The two Gate 1 failures are descendant-invalid AD-1123 test assertions, not production regressions. One independent producer-start exception-observation defect must also be corrected in the already-authorized AD-722b-5a implementation and new test module before the frozen-test correction.

## C0 - Exact live Builder handoff

- Exact base and current HEAD remain `44a697558eae15f88df5ff64dfe53ce70a23eb9e`; branch is `main...origin/main`; nothing is staged.
- The worktree contains only the original nine implementation/test paths plus these two active prompts. No tracker, archive, Git, or GitHub mutation has occurred.
- Builder completed Sections 1-5.
- `tests/test_ad722b_5a_federation_telemetry_relay.py` currently collects **198** cases.
- The exact focused gate reported **212 passed**.
- The completed local WS-focused subset reported **44 passed**, with exactly **two known BF-326 warnings**.
- Gate 1 collected **422** tests: **420 passed** and exactly the two failures named in C1/C2 below. All non-failing Gate 1 tests passed.
- Pre-correction SHA-256 of `tests/test_ad1123_bounded_federation_relay.py` is exactly `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5`.
- Live generic-surface review found no diff from base in `federation/bridge.py`, `federation/relay.py`, NATS/ZeroMQ/mock transports, types/events/protocols, mesh intent/NATS bus, fleet organization, or `startup/finalize.py`. The pinned bridge, relay, fleet, and finalizer hashes still match this prompt.

Preserve the existing red evidence verbatim. Do not rerun or manufacture pre-implementation red for C1/C2: Gate 1 already provides the required red. Do not weaken any behavioral or generic security assertion beyond the exact edits below.

## C1 - Remove only the obsolete production-empty source freeze

In `test_real_fleet_composition_with_explicit_empty_registry_is_inert`, retain the function name and the complete real-fleet explicit-empty behavioral proof. Delete only this trailing source-text block:

```python
  runtime_source = inspect.getsource(
    __import__("probos.runtime", fromlist=["ProbOSRuntime"]).ProbOSRuntime.start
  )
  assert "relay_topics=()," in runtime_source
```

Do not replace it with a child source assertion. The AD-722b-5a module already proves default configuration is inert, configured topics are live, and runtime passes the computed closed tuple. Duplicating that broad child coverage in the parent module is not authorized.

Rationale: the test's explicit `relay_topics=()` call still meaningfully proves an empty registry is organized and inert. Only its final inspection of `ProbOSRuntime.start` freezes AD-1123's temporary production-zero-topic state, which this child AD is specifically replacing with a default-empty computed tuple.

## C2 - Narrow and rename only the parent ownership guard

Rename:

```python
test_authorized_scope_has_no_transport_telemetry_event_config_or_shutdown_diff
```

to:

```python
test_authorized_scope_has_no_generic_relay_protocol_transport_or_fleet_diff
```

Replace only its `forbidden` tuple with this exact generic ownership set:

```python
  forbidden = (
    "src/probos/federation/bridge.py",
    "src/probos/federation/relay.py",
    "src/probos/federation/nats_transport.py",
    "src/probos/federation/transport.py",
    "src/probos/federation/mock_transport.py",
    "src/probos/types.py",
    "src/probos/events.py",
    "src/probos/protocols.py",
    "src/probos/mesh/intent.py",
    "src/probos/mesh/nats_bus.py",
    "src/probos/startup/fleet_organization.py",
  )
```

Keep its `git diff --name-only` invocation and `changed.isdisjoint(forbidden)` assertion unchanged. This removes only the four child-owned semantic/composition paths `federation/telemetry_relay.py`, `routers/agents.py`, `startup/shutdown.py`, and `config.py`, while strengthening the guard around AD-1123's generic bridge/relay, ZeroMQ/NATS/mock transports, shared protocol/type/event/mesh surfaces, and fleet composition. Do not hide, stage, stash, restore, or otherwise alter the live diff to satisfy this guard.

## C3 - Observe producer task failure at the readiness boundary

Live review found one independent implementation defect in an already-authorized path. `FederationTelemetryRelay._producer_loop()` sets `ready` in `finally`, including when `AvatarEventBus.subscribe()` raises. `FederationTelemetryRelay.start()` currently awaits `ready.wait()` and then proceeds without observing a task that has already failed, so a partial producer-start failure can be reported as success and remain latent until `stop()`.

Make this exact narrow correction in `src/probos/federation/telemetry_relay.py`: immediately after each `await ready.wait()`, observe a producer that is already complete:

```python
        await ready.wait()
        if task.done():
          task.result()
```

Do not catch or normalize `task.result()`. The existing enclosing `except BaseException` must clean all producer tasks/subscriptions/volatile state and re-raise the original ordinary exception, `CancelledError`, or other `BaseException`.

Add exactly one regression case to the already-authorized `tests/test_ad722b_5a_federation_telemetry_relay.py`, named `test_producer_subscription_failure_is_observed_cleans_and_permits_restart`. Use two exported agent IDs and an `AvatarEventBus` test subclass/fake whose second `subscribe()` raises `RuntimeError("subscribe-fault")`. Prove `start()` raises that error, the first producer is reaped/unsubscribed, `_producer_tasks`, event subscribers, rate/cursors/ticks, stream ID, and sequence are reset, and the same relay can start and stop successfully after disabling the fault. Add the regression first and record its focused red before applying the three-line production observation. No other production or test change is authorized by C3.

## One-path test authorization and hashes

Before implementation review, authorize exactly one additional test path:

```text
tests/test_ad1123_bounded_federation_relay.py
```

That path may change only by C1 and C2. Its pre-correction hash is the pinned `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5`. Applying the exact CRLF/no-BOM edits above deterministically yields final SHA-256:

```text
c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45
```

Builder must report and verify that final hash. A mismatch is a hard stop and requires Architect review; do not make a compensating edit. This packet supersedes the old unchanged-test/hash hard stop only for this one path and only from the pinned pre-hash to the pinned final hash. Every production/federation primitive hash and every other frozen path remains unchanged and binding.

C3 uses only the already-authorized `src/probos/federation/telemetry_relay.py` and `tests/test_ad722b_5a_federation_telemetry_relay.py`; it does not authorize another path.

## Continuation order and revised counts

1. Preserve all existing Builder red/green and Gate 1 evidence.
2. Add the single C3 regression, record its narrow red, apply the exact task-observation correction, and rerun that one regression green.
3. Apply only C1/C2 to the AD-1123 test and verify its hash is `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45`.
4. Immediately rerun the exact Gate 1 command. No additional production/test read, refactor, or edit may intervene. With the one C3 case, the new module must collect **199**, and Gate 1 must report **423 passed, no warnings**.
5. Continue directly through exact Gate 2 (**665 passed, no warnings**), Gate 3 (**77 passed, only the five pinned BF-326 warnings**), Gate 4 (**575 passed, only the two pinned dependency deprecations**), the full parallel gate, editor/compile checks, source/privacy scans, diff checks, and all frozen/changed-file hash audits.
6. Return the uncommitted implementation for Architect review. Include the preserved original red evidence, C3 red/green evidence, exact final counts/warnings, the parent test pre/final hashes, and final hashes for every changed/new file and both active prompts.

Do not update trackers, archive prompts, stage, commit, push, or mutate GitHub before that implementation review. No #659 body update is required for this correction packet: the feature scope, privacy posture, issue close semantics, and proposed replacement body are unchanged.

## Continuation three-pass self-review

### Pass 1 - Required correctness

**Verdict:** CONDITIONAL APPROVAL. C1 removes only a descendant-invalid source literal while retaining the explicit-empty behavioral test. C2 permits exactly the child-owned semantic/composition files while preserving and strengthening generic relay/protocol/transport/fleet ownership. C3 closes a real exception-observation hole at the producer readiness boundary without changing lifecycle policy.

### Pass 2 - Scope and engineering quality

**Verdict:** APPROVED. Exactly one additional frozen test path is authorized; its before/after hashes and exact edits are pinned. C3 stays inside two original allowlist paths and adds one boundary regression. No bridge, relay primitive, transport, fleet organization, finalizer, tracker, archive, Git, or GitHub change is permitted.

### Pass 3 - Dispatch readiness

**Verdict:** APPROVED TO CONTINUE through C3, C1/C2, exact Gate 1, Gates 2-4, full gate, and audits only. Tracker/archive/Git closeout remains blocked pending Architect implementation review. The execution prompt must bind the SHA-256 of this main prompt after this packet is appended.

---

# HIGHEST-PRECEDENCE IMPLEMENTATION REVIEW CORRECTION PACKET (2026-07-17)

**Authority:** This packet supersedes every conflicting scalar-sequence rule, sampling-rate bound assumption, lifecycle-transition rule, mutation-window rule, temporary-waiter construction rule, test count, gate count, and implementation-review verdict above. The prior C1-C3 corrections and parent-test final hash remain accepted. Every privacy boundary, generic relay/transport/fleet/finalizer freeze, closeout restriction, and Git/GitHub prohibition remains binding.

**Verdict:** BLOCKED. Do not close out AD-722b-5a. The implementation has one multi-agent ordering failure, one current-config/schema-totality failure, and three task-lifecycle failures. Apply only C4-C9 below, rerun the exact red/green and gates, then return the still-uncommitted tree for another Architect implementation review.

## Accepted live evidence

- HEAD and origin remain `44a697558eae15f88df5ff64dfe53ce70a23eb9e`; branch remains `main...origin/main`; nothing is staged.
- Active prompt pre-review hashes were main `8b1254b708a57fb62a4e0be6bd9d4095a2ae430aec3f705d83be412f0923c7f3` and execution `2ba775904520d45c9351e2777fcdf77f9943913ba3e824fc8bed983bbbdd872f`.
- The authorized parent-test transition is exact: `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5` -> `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45`.
- Builder red/green evidence through C3 is accepted: new module 199 cases; focused 212 passed; Gate 1 423/no warnings; Gate 2 665/no warnings; Gate 3 77 with only five BF-326 warnings; Gate 4 575 with only two pinned dependency deprecations; full gate 19,575 passed, 33 skipped, 454 repository-wide warnings.
- Editor diagnostics and targeted compile were green. The generic bridge/relay/transports/fleet/finalizer and avatar primitive hashes remain exact. No commercial, UI, YAML, tracker, archive, staged, deletion, or GitHub change exists.

Those results prove the implemented and tested cases only. They do not override the reachable failures below.

## C4 - Sequence authority is per agent, shared only across peer copies

The live relay stores one scalar `self._sequence`, but the receiver enforces `last_sequence + 1` independently for each `(source_node, agent_id)` cache key. Two valid agents therefore produce `agent-a:0`, `agent-b:1`, `agent-a:2`; the second agent-a frame is incorrectly dropped as gapped. Different peer filters create the same defect even without concurrent producers.

Replace the scalar with a bounded per-agent map:

```python
self._sequences: dict[str, int] = {}
```

For one semantically valid local frame:

1. Read `sequence = self._sequences.get(agent_id, 0)` before payload assembly.
2. Parse/validate the complete candidate using that sequence.
3. If invalid, return zero without changing the map, rate state, or callback state.
4. If valid, set `self._sequences[agent_id] = sequence + 1` before the first await and before peer iteration.
5. Reuse that one detached exact payload for every peer copy of the same semantic frame.

The map is bounded by the registered unique-agent cap. Clear it on start, stop, failed start, and restart. Keep one relay-wide random `stream_id` per successful start. Rate drops, bridge `False`, and callback failures still consume the produced frame's sequence for that agent, intentionally creating a receiver gap until a later full snapshot. Frames for another agent must never create that gap.

Update only the new AD-722b-5a module's existing private-state assertions from scalar `_sequence` to exact `_sequences` map assertions. Add exactly one case:

```text
test_multi_agent_sequences_are_per_agent_and_shared_across_peer_copies
```

Use two agents and overlapping/different peer filters. Prove each agent starts at sequence 0, each agent's next frame is sequence 1, copies of one frame share the same sequence, and a real `RemoteAvatarTelemetryCache` accepts both agents' contiguous diffs without waiting for a full resync.

## C5 - Make every valid sampling configuration wire-representable

`SamplingRatesConfig` currently enforces only `>= 250`, while the semantic schema rejects `sampling_rate_ms > 2_147_483_647`. A currently valid local configuration can therefore build a real local snapshot that the federation producer silently drops. Very large valid integers can also raise during `float(rate_ms)` in the producer after startup.

Define one shared constant in `avatars/telemetry_frames.py`:

```python
MAX_AVATAR_SAMPLING_RATE_MS = 2_147_483_647
```

Use it in the semantic field validator. In `SamplingRatesConfig._bound_rate`, retain the existing below-floor branch and error text, then locally import the constant and reject values above it at parse time with a contextual `ValueError`. Do not add a top-level config-to-avatar import. Do not clamp or project a valid configured rate, and do not widen the wire integer bound.

Add exactly one case:

```text
test_sampling_rate_config_upper_bound_matches_wire_contract
```

In that case, prove all-three-at-max configuration is valid, the real `AvatarSamplingStateMachine` returns the max, a snapshot carrying the max parses on the wire, and `max + 1` is rejected for each of `high_ms`, `normal_ms`, and `low_ms`.

## C6 - Serialize lifecycle transitions and observe later producer death

The current `stop()` sets `_running=False` before awaiting a snapshot of `_producer_tasks`. A concurrent restart can clear/repopulate the shared task dict while the old stop is awaiting; the old cleanup then clears the new task references and resets the new stream, leaving an orphan producer. Synchronous registration/callback mutation is also admitted during that stop window. Separately, a producer that fails after `start()` returns is retained but never observed: `stop()` gathers with `return_exceptions=True` and discards the result.

Add one relay-owned `asyncio.Lock` and serialize the complete public `start()` and `stop()` transitions. Concurrent starts remain idempotent; concurrent stops remain idempotent; a restart waits for stop cleanup to finish. `_require_stopped()` must reject while the relay is running **or while the lifecycle lock is held**, so subscription/callback mutation is allowed only after stop has fully completed.

After each readiness wait and the existing early `task.done() -> task.result()` check succeeds, register a done callback for that producer. The observer must always retrieve `task.result()`; expected cancellation is silent. If the task completes or raises while the relay is still running, log agent ID, exception type when present, impact (that agent's federation telemetry producer stopped), and action (relay restart required), without payload/profile values or exception text. Contain the callback so no event-loop `Task exception was never retrieved`/callback exception is emitted. Keep the completed task reference bounded until stop reaps/clears it; do not auto-spawn an unbounded restart loop.

Add exactly two cases:

```text
test_late_producer_failure_is_observed_without_unretrieved_exception
test_stop_and_concurrent_restart_are_serialized_without_orphaning_new_producer
```

The first faults `current_rate_ms()` only after readiness/initial production and proves the producer failure is retrieved and contextually logged. The second holds old-task cancellation cleanup open, starts stop and restart concurrently, proves restart cannot complete during stop, proves mutation rejects during the transition, then proves the new producer remains referenced/running with a new stream until a clean final stop.

## C7 - Reap a partially created event/timer waiter pair

The current producer creates `wait_event` and `wait_timer` before entering the `try/finally`. If the second `asyncio.create_task()` raises, the first waiter survives unreferenced.

Initialize both waiter variables to `None`, enter the `try`, create each waiter inside it, and in `finally` cancel and gather exactly the waiter tasks that were successfully created. Preserve real cancellation. Let an unexpected creation failure terminate the producer so C6's done observer reports it; do not spin or create a replacement task.

Add exactly one case:

```text
test_temporary_waiter_second_create_failure_reaps_first_waiter
```

Fault only the second unnamed waiter creation after the producer is healthy. Prove the first waiter is done, the producer failure is observed, no event/timer task survives, and stop clears the relay normally.

## C8 - Enforce the PeerConfig list cap before inspecting entries

The `mode="before"` validator currently iterates the entire list before Pydantic applies `Field(max_length=32)`. Reject an exact-list length above 32 with `list.__len__` before importing/calling the agent-ID predicate or iterating entries. Keep `Field(max_length=32)` as defense in depth, exact-list admission, safe-ID validation, and duplicate rejection.

Add exactly one case:

```text
test_peer_config_oversized_list_rejects_before_entry_validation
```

Instrument the locally imported predicate and prove a 33-entry exact list is rejected without one predicate call.

## C9 - Restore contextual, privacy-safe diff fallback logging

The shared selector removed the fleet fallback warning's agent context and currently emits `exc_info=True`, which can expose exception text derived from malformed values. Change only that warning to include `agent_id` and `exception_type`, plus the existing full-snapshot fallback action, without traceback, exception text, frame keys, or values.

Strengthen the existing `test_select_frame_diff_exception_falls_back_full` case; do not add another collected case. It must assert agent ID and `RuntimeError` appear, fallback remains full, and the marker text `diff-fault` does not appear.

## Exact correction allowlist

Production edits are limited to:

```text
src/probos/avatars/telemetry_frames.py
src/probos/federation/telemetry_relay.py
src/probos/config.py
```

Test edits are limited to:

```text
tests/test_ad722b_5a_federation_telemetry_relay.py
```

Do not further edit the migrated eight-test module or the now-correct AD-1123 parent test. Do not edit startup composition, runtime, routers, shutdown, cache semantics, generic federation files, avatar primitives, trackers, archives, Git, or GitHub. All existing live implementation changes remain in place; do not stash, restore, reset, or reconstruct them.

## Required red and green

Add all six new cases and strengthen the existing fallback case before production edits. With the same isolated environment used by the binding gates, run exactly:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad722b5a_review_red_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad722b_5a_federation_telemetry_relay.py::test_multi_agent_sequences_are_per_agent_and_shared_across_peer_copies tests/test_ad722b_5a_federation_telemetry_relay.py::test_sampling_rate_config_upper_bound_matches_wire_contract tests/test_ad722b_5a_federation_telemetry_relay.py::test_late_producer_failure_is_observed_without_unretrieved_exception tests/test_ad722b_5a_federation_telemetry_relay.py::test_stop_and_concurrent_restart_are_serialized_without_orphaning_new_producer tests/test_ad722b_5a_federation_telemetry_relay.py::test_temporary_waiter_second_create_failure_reaps_first_waiter tests/test_ad722b_5a_federation_telemetry_relay.py::test_peer_config_oversized_list_rejects_before_entry_validation tests/test_ad722b_5a_federation_telemetry_relay.py::test_select_frame_diff_exception_falls_back_full -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected red: all seven selected cases fail for the specific pre-correction behavior above. Record exact failures. After C4-C9, rerun the identical command: **7 passed, no warnings**.

Then run the original C3 subscription-failure regression together with all seven review cases: **8 passed, no warnings**. The subscription-readiness behavior must remain intact under the lifecycle lock.

## Revised exact counts and gates

Six new collected cases raise the new module from **199** to exactly **205**. Required outcomes now supersede every earlier count:

| Gate | Required result |
|---|---:|
| Focused binding gate | **218 passed**, no warnings |
| Gate 1 relay/federation | **429 passed**, no warnings |
| Gate 2 directed/transport | **671 passed**, no warnings |
| Gate 3 local avatar/WS | **77 passed**, only five pinned BF-326 warnings |
| Gate 4 runtime/config/shutdown | **581 passed**, only two pinned dependency deprecations |
| Full `tests/ -n 4 --dist=loadfile` | **19,581 passed, 33 skipped**, no warning beyond the accepted **454** repository-wide baseline |

Run editor diagnostics, targeted compile, source/privacy scans, `git diff --check`, exact changed-path/deletion/staged audits, and every frozen hash audit again. The parent test must remain exactly `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45`.

## Return boundary

Return the uncommitted tree for Architect review with:

- the seven-case red and green outputs;
- the eight-case C3-plus-review result;
- exact 205 collection evidence and all revised gate counts/warnings;
- proof that two-agent cache diffs remain contiguous and per-frame peer copies share sequence;
- proof that every valid sampling config value is wire-representable;
- late-failure observation, serialized stop/restart, mutation lockout, and temporary-waiter reap evidence;
- final hashes for every changed/new file and both active prompts;
- unchanged frozen hashes, parent-test hash, no deletions/staging, and no GitHub mutation.

Do not update trackers, archive prompts, stage, commit, push, or mutate #659 before the next Architect implementation review.

## Implementation-review three-pass verdict

### Pass 1 - Required correctness

**Verdict:** BLOCKED. Scalar sequence authority is incompatible with per-agent cache contiguity, and valid sampling configuration is not total over the wire schema.

### Pass 2 - Lifecycle and engineering quality

**Verdict:** BLOCKED. A later producer exception is silently consumed, concurrent stop/restart can orphan the replacement producer, temporary waiter partial creation leaks, and config admission scans beyond its declared cap.

### Pass 3 - Scope and continuation readiness

**Verdict:** APPROVED TO CORRECT C4-C9 ONLY. The existing no-browser composition, schema/privacy, callback/rate, cache, runtime containment, shutdown order, local WS parity, generic freezes, and prior gate evidence are otherwise accepted. Closeout remains blocked.

---

# HIGHEST-PRECEDENCE LIVE COUNT ARITHMETIC CORRECTION (2026-07-17)

**Authority:** This packet supersedes every conflicting focused-count expectation, C4-C9 implementation status, and continuation-order instruction above. It changes no architecture, behavior, file allowlist, privacy/security requirement, frozen-path rule, warning budget, closeout restriction, or Git/GitHub prohibition. No production, test, tracker, archive, Git, or GitHub edit is authorized by this packet.

**Verdict:** APPROVED TO RESUME DIRECTLY AT GATE 1. C4-C9 are implemented and their completed focused evidence is accepted. Do not rerun the focused gate and do not edit production or tests.

## Accepted live evidence

- The authoritative seven-node command first reported **7 failed** for the exact C4-C9 defects, then **7 passed, no warnings** after correction.
- C3 plus the seven review nodes reported **8 passed, no warnings**.
- `tests/test_ad722b_5a_federation_telemetry_relay.py` collects exactly **205** cases.
- The exact focused command already completed with **219 passed, no warnings**.
- The C4-C9 behavioral proofs are green, including per-agent sequence continuity, sampling-bound totality, late producer-failure observation, serialized stop/restart, transition mutation lockout, partial-waiter cleanup, bounded `PeerConfig` admission, and privacy-safe diff fallback logging.
- Editor diagnostics are clear; no path is staged or deleted; every required frozen hash remains intact.
- `tests/test_ad722b_3_snapshot_diff.py` collects exactly **6** cases and remains byte-identical to HEAD blob `c62f51360098d90e4f24799cc3cbcfeec8f39642`.

## Corrected arithmetic

| Gate | Authoritative formula | Required result |
|---|---:|---:|
| Focused binding gate | `205 + 8 + 6` | **219 passed, no warnings** |
| Gate 1 relay/federation | `224 + 205` | **429 passed, no warnings** |
| Gate 2 directed/transport | `466 + 205` | **671 passed, no warnings** |
| Gate 3 local avatar/WS | fixed baseline | **77 passed**, only five pinned BF-326 warnings |
| Gate 4 runtime/config/shutdown | `376 + 205` | **581 passed**, only two pinned dependency deprecations |
| Full `tests/ -n 4 --dist=loadfile` | `19,575 + 6` | **19,581 passed, 33 skipped**, no warning beyond the accepted **454** repository-wide baseline |

The prior C3 full-gate result of **19,575** already included the **199-case** new-module count. Only the six C4-C9 cases are added for the revised full total. The focused total is the sole revised arithmetic error. Any one-test-short focused total would require deleting a required collected case or editing a fifth frozen test path; both are prohibited.

## Exact continuation order

1. Accept the completed focused **219 passed, no warnings** run; do not rerun it.
2. Resume at Gate 1 and require **429 passed, no warnings**.
3. Continue through Gate 2 **671**, Gate 3 fixed **77**, Gate 4 **581**, and full **19,581 passed, 33 skipped**, with only the warning budgets above.
4. Complete the already-required editor, compile, source/privacy, diff, staged/deleted-path, changed-file hash, and frozen-hash audits.
5. Return the still-uncommitted tree for Architect review. Do not update trackers, archive prompts, stage, commit, push, mutate GitHub, or update #659.

## Arithmetic-correction three-pass verdict

### Pass 1 - Evidence and collection

**Verdict:** APPROVED. The completed red/green, eight-node regression, exact 205-case collection, and focused 219-case run are accepted.

### Pass 2 - Formula consistency

**Verdict:** APPROVED WITH ONE CORRECTION. Focused is **219**. Gate 1 **429**, Gate 2 **671**, Gate 3 **77**, Gate 4 **581**, and full **19,581** are correct.

### Pass 3 - Dispatch

**Verdict:** RESUME DIRECTLY AT GATE 1. No focused rerun and no production/test edit is permitted.

---

# HIGHEST-PRECEDENCE FULL-GATE WARNING-EVIDENCE CORRECTION (2026-07-17)

**Authority:** This packet supersedes every conflicting exact aggregate-warning requirement for the final full parallel gate, including the accepted-`454` ceiling and any hard stop based only on aggregate warning-count variance. It does not supersede any focused or Gate 1-4 warning contract, behavioral count, architecture/privacy requirement, file freeze, audit requirement, closeout restriction, or Git/GitHub prohibition. No production, test, tracker, archive, Git, or GitHub edit is authorized by this packet.

**Pre-correction prompt hashes:** main `a7dda6e7d6138b8541b02aad1c808d3c1dbfe1c76fe2203c42d62a305e4053ea`; execution `1533be80f92f5ab62b06fa3409e933b4df4d1f25125d8aabed45ab68d5e57685`.

**Verdict:** ACCEPT the completed full fresh result of **19,581 passed, 33 skipped, 458 warnings**. Do not rerun the focused gate, Gates 1-4, or the full gate. Resume with the remaining static/hash audits, then return the still-uncommitted implementation for Architect review.

## Warning adjudication

The prior **454** was one historical observation from an xdist suite with pre-existing warning races; it was not a valid deterministic gate. The corrected contract does not raise a numeric budget. It requires warning provenance to prove that AD-722b-5a introduced no warning.

Accepted live evidence:

- C4-C9 ran **7 red then 7 green**; C3 plus review nodes ran **8 green**; the new module collects **205**; focused is **219 passed, no warnings**.
- Gate 1 is **429 passed, no warnings**; Gate 2 is **671 passed, no warnings**; Gate 3 is **77 passed** with exactly five pinned BF-326 warnings; the fresh Gate 4 rerun is **581 passed** with exactly two pinned dependency deprecations. The interrupted 86% Gate 4 attempt is not evidence and requires no further rerun.
- The complete new module and all six C4-C9 additions are warning-clean under the serial focused gates with `-W error::RuntimeWarning`.
- The full warning summary contains zero mentions of `test_ad722b_5a`, `test_ad722b_5`, `telemetry_frames.py`, `federation/telemetry_relay.py`, `startup/federation_telemetry.py`, changed `config.py`, `runtime.py`, `routers/agents.py`, `startup/shutdown.py`, or `test_ad1123_bounded_federation_relay.py`.
- Current warning-summary blocks are confined to: 98 BF-326 `UserWarning` blocks at third-party `_pytest/fixtures.py`; one `PytestUnhandledThreadExceptionWarning` at third-party `_pytest/threadexception.py`; one `RuntimeWarning` block at frozen `cognitive/gap_predictor.py`; four at frozen `startup/finalize.py`; two at frozen `substrate/event_log.py`; and one at unchanged `tests/test_proactive_quality.py`. Repeated warnings folded into those blocks account for the aggregate total.
- The thread warning is attached to unchanged `tests/test_ad889_commission_chain.py::test_recommission_preserves_manual_restriction`, where an aiosqlite worker attempted `call_soon_threadsafe` after the pytest event loop closed. That standalone test does not construct `ProbOSRuntime`, and its pre-existing duplicate `await store.stop()` sequence is byte-identical to HEAD. The warning was absent from the retained earlier tail and is scheduling-dependent under xdist.
- Every repository warning-source file above is byte-identical to HEAD. The remaining source locations are third-party pytest internals. Other current non-BF warnings are unchanged unawaited-AsyncMock families in proactive quality, database abstraction/event logging, dream step/gap prediction, and new-crew/finalize paths; the retained pre-C4 tail independently proves the pre-existing new-crew/finalize family.
- The new producer path is not a plausible source for those frozen warnings: federation is default-off; each peer's export list is default-empty; no producer starts without an explicit non-empty export; and every producer plus temporary event/timer waiter is referenced, cancelled, and gathered under serialized startup/stop cleanup before federation bridge shutdown.

## Binding warning forcing function

For this completed full gate and any adjudicated rerun, aggregate warning count alone is neither a pass nor a fail. The full-gate warning criterion passes only when all of the following hold:

1. No warning source, warning node, traceback, or summary text names a changed/new AD-722b-5a implementation or test path.
2. Every aggregate variance is traceable to third-party code or a repository test/source file proven byte-identical to HEAD and to a pre-existing warning family or scheduling race.
3. Focused and blast gates retain their exact warning contracts; provenance adjudication cannot excuse a warning in those gates.
4. Any unresolved-task, unawaited-coroutine, thread-exception, resource, or other warning sourced from or causally tied to a changed/new path remains a hard stop, regardless of aggregate count.
5. A new warning source/family, an untraceable aggregate variance, or drift in a frozen warning-source blob is a hard stop and returns to Architect for the smallest source-focused serial reproducer. Do not automatically spend another full-suite run.

The completed **458** is accepted evidence for this run, not a new ceiling, floor, or reusable repository-wide allowance.

## Exact continuation order

1. Accept all completed behavioral gates and the fresh full result above; run no test gate again.
2. Complete only the already-required editor/targeted-compile, source/privacy, diff, staged/deleted-path, changed-file hash, and frozen-hash audits that remain outstanding.
3. Return the still-uncommitted tree and audit ledger for Architect implementation review.
4. Do not edit production/tests/trackers, archive prompts, stage, commit, push, mutate GitHub, or update #659.

## Warning-correction three-pass verdict

### Pass 1 - Provenance

**Verdict:** APPROVED. The 458-warning summary is wholly confined to third-party or HEAD-identical pre-existing sources; no changed/new path appears.

### Pass 2 - Causality

**Verdict:** APPROVED. Exact focused/blast warning gates and owned relay cleanup disprove an AD-722b-5a warning regression; the newly visible AD-889 thread block is an unchanged xdist scheduling race.

### Pass 3 - Dispatch

**Verdict:** RESUME AT STATIC/HASH AUDITS, THEN IMPLEMENTATION REVIEW. No further test run or code/test edit is permitted.
