# Review: AD-766 — YeomanAgent (bridge crew)
**Verdict:** ⚠️ Conditional — three Required findings before build
**The Yeoman concept is right; several concrete claims about existing Bridge crew, runtime registration, and hot-reload are factually wrong against HEAD.**

## Required (must fix before building)
1. **`runtime.py:1241` is NOT a registration tuple.** Verified — line 1241 reads `"first_officer", "counselor",` inside a set called `CONN_ELIGIBLE_POSTS` in the `_check_night_order_escalation` method (Conn-eligibility role list), NOT in `_create_pools` or `register_template` wiring. The actual Counselor registration is at `runtime.py:966`: `self.spawner.register_template("counselor", CounselorAgent)`. **Required fix**: §1 must point Builder to line 966 (after `# Bridge crew (AD-398)` comment) as the insertion site for `self.spawner.register_template("yeoman", YeomanAgent)`, not line 1241.

2. **There is NO `FirstOfficer` agent class.** Verified — grep for `class FirstOfficer`, `class NumberOne`, `register_template("first_officer"` returns zero matches. `"first_officer"` exists only as: an ontology post id (`ontology/spatial.py:79`), a string in `CONN_ELIGIBLE_POSTS`, a backfill comment, and a `"science": "number_one"` dual-hat mapping in `cognitive_agent.py:1326`. Today's actual Bridge crew is **Counselor only** (one entry in `bridge_pools = ["counselor"]` at `config.py:524`). **Required fix**:
   - §1 must NOT claim "the Bridge department already exists (First Officer + Counselor registered)." Replace with "the Bridge tier currently has one registered agent (Counselor). Yeoman becomes the second."
   - Drop the "First Officer / Counselor" example phrasing in the auditor instruction; tell Builder to mirror `CounselorAgent`'s placement.
   - Bridge agent file layout: `CounselorAgent` lives at `src/probos/cognitive/counselor.py` (NOT a `bridge/` subfolder, NOT under `agents/bridge/`). **Required fix**: change `src/probos/agents/bridge/yeoman.py` in §2 to `src/probos/cognitive/yeoman.py` to mirror the Counselor pattern, OR explicitly call out in the prompt that introducing `cognitive/bridge/` (and moving Counselor) is in scope. Recommend the former: keep it loose under `cognitive/` like Counselor.

3. **Captain Card hot-reload is a phantom.** Verified — `CaptainCard` is a Pydantic model at `captain_card/card.py:42` with `load_card`/`save_card` functions; runtime.py:1600 calls `load_card` at startup. There is no file-watcher, no `on_card_change` hook, no agent-side `reload_card` mechanism. The `hot_reload` flag in `settings/section_registry.py` is for Settings fields, NOT for CaptainCard. **Required fix**: §5 must downgrade "Persona changes in the Captain Card hot-reload into the running YeomanAgent (no restart)" to "Persona changes require restart for v1; AD-766a forward marker for live hot-reload."

## Recommended
1. Singleton enforcement: §3 Open Question #2 already flags this. Recommend runtime-side enforcement: in `_create_pools`, register YeomanAgent with `pool_size=1, scalable=False` (verify these are real `register_template` kwargs by reading the spawner signature). If those kwargs don't exist, the singleton guard becomes a manual check in `__init__` that errors if a second instance is constructed.
2. Spatial slot wiring: `ontology/spatial.py:81` confirmed `"yeoman": (0.0, 0.0, 1.5)`. The slot is reserved but not actively consumed by any agent today — Builder should grep for how Counselor consumes its slot to confirm the wiring is automatic (it likely is, via post lookup).
3. Proactive subscription mechanism: §4 says YeomanAgent "subscribes to result intents from `proactive_scan_inbox`, etc." — verify the intent bus actually emits a separate `proactive_scan_inbox` event vs a single `proactive_scan` with a `scan_type` param. Builder should grep `proactive.py` and the scheduler before writing the subscription code; the current prompt assumes per-scan-type intent names that may not exist.
4. AD-765 §4 dependency: the prompt's §3 last bullet ("read-only auto-approve: read intents bypass quorum (depends on AD-765 §4 finding)") creates a soft dependency on AD-765 completing first. Open Question #3 says "Don't block on AD-765" — good. Keep the bullet as "best-effort if AD-765 has landed; otherwise ship without and file follow-up."
5. AD-739 reference (Captain Card persona, AD-749 M365 connectors, AD-752 proactive scheduler, AD-758 Yeo gate) — all confirmed real. Dependency graph valid.

## Nits
- "Bridge HXI surface (`ui/src/components/bridge/`)" — verify this directory exists before claiming "gains a Yeoman card." If it doesn't exist, downgrade to "the HXI surface for Bridge crew (location TBD by Builder grep)."
- "amber/gold department color" — confirm `bridge` has a token in the color palette; if not, the Builder will need to add one, which is a non-trivial design-token change.

## Verified
- `CaptainCard` Pydantic model at `captain_card/card.py:42`. ✓
- Yeo identity string at `captain_card/card.py:91`. ✓
- `bridge_pools: list[str] = ["counselor"]` at `config.py:524` (correct line, correct shape). ✓
- `ontology/spatial.py:81` has `"yeoman": (0.0, 0.0, 1.5)` reserved slot. ✓
- `CounselorAgent` at `src/probos/cognitive/counselor.py:475`. ✓
- Counselor registration at `runtime.py:966`. ✓
- Proactive scheduler exists with `_SCAN_TYPES = ("inbox", "calendar", "teams")` at `agents/operations/scheduler.py:22`. ✓
- No `class Yeoman*`, no `agent_type = "yeoman"`, no `callsign = "Yeo"` registrations in `src/probos/` (Captain's bug report verified). ✓
- AD-710 / AD-739 / AD-749 / AD-752 / AD-758 dependency ADs are real. ✓

## Re-review (2026-05-20)
All three Required findings addressed by prompt edits:
1. Registration site corrected from `runtime.py:1241` (CONN_ELIGIBLE_POSTS set) to `runtime.py:966` (under `# Bridge crew (AD-398)`). ✓
2. "First Officer + Counselor registered" replaced with the accurate "Counselor only; Yeoman becomes the second" framing. Bridge file layout pinned to `src/probos/cognitive/yeoman.py` mirroring `counselor.py`. ✓
3. CaptainCard hot-reload phantom downgraded to v1-restart-required with forward marker `AD-766a` for live hot-reload. ✓

Recommended #3 (proactive subscription mechanism verification) added as Open Question #5 so the Builder grep's the actual emission shape before writing subscription code. Required findings cleared. **Ready for GATE 1.**
