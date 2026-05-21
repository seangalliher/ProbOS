# AD-766 — YeomanAgent (bridge crew: Captain's personal assistant)

Status: drafted
Issue: #712
Depends on: AD-710 (Yeo design), AD-739 (Captain Card), AD-749 (M365 connectors), AD-752 (proactive scheduler), AD-758 (Yeo feature-complete gate)

## Captain bug report (2026-05-20)

> "I don't see the yeoman crew agent active. The Yeoman was supposed to be a crew agent, should be part of the bridge. This is the captain's personal assistant. If you research the role of a Yeoman on a ship this agent's role should align, except of course they are an AI agent."

The "Yeo program" (AD-749..AD-757 + AD-758 gate) shipped the **substrate Yeo would consume** — M365 connectors, proactive scheduler, captain card persona, session manager, desktop lifecycle — but **the agent itself was never instantiated.** AD-710 filed the design intent; no implementation followed. Grep confirms zero matches for `class Yeoman`, `callsign = "Yeo"`, or `agent_type = "yeo"` in `src/probos/`. The Captain Card identity string ([captain_card/card.py#L91](src/probos/captain_card/card.py#L91)) describes Yeo as a persona, but no agent declares it.

## The Yeoman role (anchored in source material)

A naval / Starfleet Yeoman is the Captain's **personal administrative aide and gatekeeper** — distinct from the First Officer (Number One, who commands when the Captain is absent) and from a generic "assistant" or "concierge." Concretely:

- **Schedule management** — owns the Captain's calendar; brokers meeting requests; flags conflicts; protects focus time.
- **Correspondence triage** — reads incoming messages, summarizes, prioritizes, and surfaces only what the Captain must personally see.
- **Reports for signature** — assembles status reports, briefings, and standing orders into Captain-ready form; presents the clipboard / PADD with "Sign here, Captain."
- **Ship's log maintenance** — captures and files the Captain's log entries and personnel records.
- **Visitor management** — controls bridge access; announces visitors; escorts to ready room.
- **Standing orders dispatch** — relays the Captain's standing orders to the appropriate department heads.
- **Always on the bridge** — Yeoman is always near the Captain; presence matters as much as task throughput.

What the Yeoman is **NOT**:
- Not a tactical operator (that's Helm / Tactical / Security).
- Not an analyst (that's Science).
- Not a decision-maker (that's the Captain, then XO).
- Not a general-purpose chatbot (that's the decomposer + crew at large).

The defining trait is **proximity to the Captain plus administrative authority** — Yeoman acts in the Captain's name for the small things so the Captain's attention is reserved for the big ones.

## Why this matters

- **The proactive scheduler currently has no consumer.** `proactive_scan_inbox`, `proactive_scan_calendar`, `proactive_scan_teams` jobs emit findings into the bus with no Yeo subscriber to triage them into Captain DMs. The whole AD-752 pipeline runs and the Captain hears nothing unless they `/proactive status` it.
- **Captain Card persona has nowhere to attach.** AD-739 defined Yeo's voice and instructions but no agent class adopts them — they're literally orphaned strings.
- **Bridge exists but Yeoman isn't on it.** [config.py#L524](src/probos/config.py#L524) defines `bridge_pools: list[str] = ["counselor"]` (currently one entry). [runtime.py#L966](src/probos/runtime.py#L966) registers Counselor via `self.spawner.register_template("counselor", CounselorAgent)` under the `# Bridge crew (AD-398)` comment. [ontology/spatial.py#L81](src/probos/ontology/spatial.py#L81) reserved a Yeoman slot at `(0, 0, 1.5)` — the ontology already anticipated Yeoman as Bridge crew. Only the agent class itself is missing. (Note: the string `"first_officer"` appears in `runtime.py:1241` inside `CONN_ELIGIBLE_POSTS` and in `ontology/spatial.py:79`, but no `FirstOfficer` agent class is registered — it's a reserved post id, not an active crew member.)
- **AD-758 gate measured program rubric, not agent existence.** The integration gate confirmed AD-749..AD-757 wiring; it did not assert "and the agent the Captain talks to actually exists." This is exactly the kind of miss the AD-765 audit will catch — but the Captain shouldn't wait.

## Scope (v1)

### 1. Join the existing Bridge
- The Bridge tier already exists (`bridge_pools = ["counselor"]` at `config.py:524`; CounselorAgent registered at `runtime.py:966` under the `# Bridge crew (AD-398)` comment). **Do NOT re-create it.** Yeoman becomes the second registered Bridge crew member.
- Place `yeoman.py` at `src/probos/cognitive/yeoman.py` to mirror `CounselorAgent`'s placement at `src/probos/cognitive/counselor.py` (NOT under a new `bridge/` subfolder — keep loose under `cognitive/`).
- Add `"yeoman"` to `bridge_pools` in `config.py:524` (currently `["counselor"]`) so the tiered-trust + Bridge palette logic picks it up.
- Add the registration call `self.spawner.register_template("yeoman", YeomanAgent)` immediately after the Counselor registration at `runtime.py:966` (inside the `# Bridge crew (AD-398)` comment block).
- Spatial slot `(0, 0, 1.5)` from `ontology/spatial.py:81` is already reserved — wire it through via the standard post-lookup pattern Counselor uses (grep Counselor's slot consumption first; if it's automatic via ontology post id, nothing more to do).
- Existing Bridge HXI surface (verify location — grep for `bridge` under `ui/src/components/`; if no dedicated Bridge folder exists today, the Yeoman card lives in whatever crew-roster panel Counselor renders in). Reuse the existing Bridge department color (verify a `bridge` token exists in the palette; if not, the Builder adds one and notes it explicitly).

### 2. YeomanAgent class
- File `src/probos/cognitive/yeoman.py` (mirrors `cognitive/counselor.py`).
- `class YeomanAgent(CognitiveAgent)`.
- `agent_type = "yeoman"`, `callsign = "Yeo"`, `department = "Bridge"`, `tier = "domain"`.
- **Singleton** — exactly one instance per runtime (not pool-scaled). Spawned at startup whether or not M365 is configured (M365 absence means Yeo works with empty inbox/calendar, not that Yeo is absent).
- `instructions` string — **adopts the Captain Card identity** ("You are Yeo, {captain_name}'s personal assistant…"). Extends with role rules:
  - "Act in the Captain's name for administrative matters; never make tactical, financial, or destructive decisions without explicit Captain approval."
  - "Triage proactive scan results into a single Captain DM digest; do not flood the bridge."
  - "Delegate specialist work to the right crew member (@-mention) rather than answering outside your lane."
  - "Maintain the Captain's standing orders and surface conflicts before they become problems."

### 3. Capabilities & intent descriptors
- `daily_briefing` — assemble overnight inbox + calendar + Teams highlights into a Captain DM.
- `schedule_lookup` — answer "what's on my calendar today / this week?"
- `triage_inbox` — summarize unread mail, flag the 1–3 items needing Captain attention.
- `delegate_to_crew` — given a request, identify the right specialist (Surgeon for medical, Engineer for systems, etc.) and @-mention them in a thread.
- `relay_standing_order` — broadcast a Captain order to the named department head.
- All read-only intents tagged for AD-765 §4 spot-check (`autoApproveReadOnly`) so proactive runs don't trigger quorum.

### 4. Proactive scheduler wiring
- YeomanAgent subscribes to result intents from `proactive_scan_inbox`, `proactive_scan_calendar`, `proactive_scan_teams`.
- Aggregates findings within a 60s rolling window (configurable via `CognitiveConfig.yeoman_digest_window_seconds`, default 60).
- Emits a single `direct_message` intent to the Captain with the consolidated digest, formatted as a structured brief (not raw scan dumps).
- Respects work-hours and quiet-hours from the existing proactive config — Yeo doesn't ping at 03:00.

### 5. Captain Card binding
- `card.py` Yeo identity string (`captain_card/card.py:91`) is the canonical source; YeomanAgent reads it via the captain_card module rather than duplicating.
- v1: persona changes require runtime restart — there is no hot-reload mechanism for `CaptainCard` today (`load_card` is called once at startup in `runtime.py:1600`, no file-watcher or on-change hook). Forward marker `AD-766a — live CaptainCard hot-reload into running YeomanAgent` filed for follow-up.

### 6. HXI surfacing
- Bridge department gets a section in the crew roster panel (wherever Engineering/Medical/Science are listed).
- YeomanAgent shows there with amber/gold department color and the Yeo avatar (if AD-721 avatar work has shipped for Yeo specifically; otherwise generic crew glyph).
- Default-pinned to the top of the 1:1 DM list — Yeo is the Captain's primary conversational partner.
- HXI Design Principle #3 (no emoji; inline SVG glyphs only) and #11 (agentic-first — Yeo's presence nudges the Captain toward delegation over manual work).

### 7. Runtime registration
- `runtime.py` pool creation registers YeomanAgent at startup, singleton not pooled.
- Heartbeat/health check: YeomanAgent appears in `/system_health` and crew roster.
- Survives warm boot (existing agent restoration path) — no special-casing needed if it follows the standard CognitiveAgent registration pattern.

### 8. Tests
- `tests/test_yeoman_agent.py`:
  - Registration: YeomanAgent is in the registered agents after runtime boot.
  - Singleton: exactly one instance; spawning a second is rejected or returns the same instance.
  - Persona binding: instructions string includes the Captain Card identity.
  - Proactive subscription: when a `proactive_scan_inbox` result is published, YeomanAgent receives it.
  - Digest aggregation: multiple scan results within the window produce a single DM, not N DMs.
  - Quiet hours: scan results received during quiet hours are queued, not DM'd.
  - Delegation: a request requiring specialist work routes to the right crew callsign.
  - read-only auto-approve: read intents bypass quorum (depends on AD-765 §4 finding).
- `ui/src/__tests__/CrewRoster.bridge.test.tsx`: Bridge section renders; Yeoman appears with department color; default-pinned in DM list.

## Out of scope

- **Modifying the existing Bridge crew** — First Officer (Number One) and Counselor are out of scope. Yeoman is purely additive.
- **Yeo-specific voice/avatar work** — if AD-721 already shipped a generic crew avatar, use it; bespoke Yeo avatar is a follow-up.
- **M365 write actions through Yeo** — read-only digest in v1. Write actions (draft reply, book meeting on Captain's behalf) come after the AD-765 audit confirms the permission model for unattended runs.
- **Cross-device continuity** — commercial overlay scope per AD-697/AD-698.
- **Multi-Captain support** — single Captain in v1.
- **Refactoring the Captain Card persona shape** — Yeo consumes it as-is.

## Acceptance signals

- `/system_health` lists YeomanAgent in the Bridge department.
- Opening the HXI shows a Bridge section in the crew roster with Yeoman present.
- Sending a DM to Yeo gets a response using the Captain Card persona.
- A proactive inbox scan that returns 3 findings produces 1 consolidated DM from Yeo, not 3.
- `/explain` on a Yeo DM reply shows the persona source (Captain Card), the scan inputs aggregated, and any delegation decisions made.
- All scheduled proactive scans now have a visible Captain-facing consumer.
- `npm run build` clean. `pytest tests/ -x -q` green.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

- CognitiveAgent subclass: behavior in `instructions`, not procedural code in `decide()`.
- Singleton enforced explicitly (Layer architecture: domain agent registered by runtime).
- Tier classification correct: Yeoman is `domain` (Captain-facing), not `utility` or `core`.
- New department respects the Substrate → Mesh → Consensus → Cognitive → Experience layering.
- Public methods fully type-annotated.
- Structured logging at info on startup, digest emission; warning on scan-subscription failures.
- No emoji in HXI surface — amber/gold department color via tokens, inline SVG glyph.
- Test coverage: registration + persona + subscription + digest + delegation + quiet-hours (≥6 boundary tests).

## Open questions for Architect review

1. **Bridge agent file layout.** RESOLVED 2026-05-20 by architect review: `CounselorAgent` lives at `src/probos/cognitive/counselor.py`. Yeoman mirrors at `src/probos/cognitive/yeoman.py`. Do not introduce a `bridge/` subfolder.
2. **Singleton enforcement mechanism.** Constructor guard? Runtime registration guard? Both? Recommend runtime-side guard (single source of truth) with constructor warning if instantiated outside the runtime path. Verify the spawner's `register_template` signature for `pool_size=1, scalable=False` style kwargs before adopting that path; if absent, fall back to manual `__init__` check.
3. **read-only tagging blocker.** §3 above assumes the AD-765 audit will produce a verdict on `autoApproveReadOnly`. If the audit reveals the policy doesn't exist, this AD ships without the tag and a follow-up AD adds it once the policy lands. Don't block on AD-765.
4. **Spawning order at startup.** YeomanAgent must be alive before the first `proactive_scan_*` cron fires. If startup ordering doesn't already guarantee this, add a "wait for Yeoman ready" gate in the scheduler boot path.
5. **Proactive subscription mechanism (architect-added).** §4 assumes per-scan-type intent names `proactive_scan_inbox`, `proactive_scan_calendar`, `proactive_scan_teams`. Verify against `proactive.py` and `agents/operations/scheduler.py:39` (`hook = f"proactive_scan_{scan_type}"`) — the scheduler uses `webhook_name`, but the intent emitted on the bus may be the generic `"proactive_scan"` with a `scan_type` param (see `proactive.py:201, 219`). Builder must trace the actual emission shape before writing subscription code; if it's the generic shape, subscribe to `proactive_scan` and dispatch by `scan_type` inside YeomanAgent.
