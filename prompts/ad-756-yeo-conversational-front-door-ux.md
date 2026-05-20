# AD-756 - Conversational Front Door UX (Welcome, Suggested Actions, Daily Briefing, Delegation UI)

Status: drafted (planning slate only)
Issue: #702
Parent: #486
Depends on: AD-750 (#696), AD-753 (#699), AD-755 (#701)

## Objective
Define the interaction layer where Yeo serves as front door while transparently delegating to specialist agents.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Welcome panel, suggested actions, daily briefing cards.
- Delegation UI showing Yeo-to-specialist handoff state.
- Message streaming/merge strategy for coherent responses.
- Explicit controls to inspect and override delegation decisions.

## Out of Scope
- Rebuilding voice/perception stacks shipped in Waves 175-180.
- New avatar renderer tracks.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Welcome panel and onboarding for personal assistant first launch.
- Suggested actions derived from personal calendar/inbox/threads.
- Daily briefing with yesterday's context + today's top 5 items.
- Delegation UI showing Yeo-to-specialist handoff reasoning.
- Message streaming/merge for coherent personal responses.

**Commercial Extension Point:**
- Org-wide suggested-action policy (team priorities, project milestones).
- Executive briefing variant with org context.
- Team delegation metrics and handoff audit log.
- Whitelabel branding and multi-language org support.

## File Targets
- `ui/src/components/wardroom/`
- `ui/src/store/`
- `src/probos/ward_room_pipeline.py`
- `src/probos/routers/agents.py`
- `src/probos/routers/wardroom.py`

## Pre-Flight Anchors
- Verify DM and ward-room pipeline stages in `src/probos/ward_room_pipeline.py`.
- Verify chat/delegation routes in `src/probos/routers/agents.py` and wardroom router.
- Verify current thread detail surfaces in `ui/src/components/wardroom/WardRoomThreadDetail.tsx`.

## Acceptance Criteria
- Delegation source/target and rationale are visible to the Captain.
- Stream merge behavior prevents duplicate or fragmented final responses.
- Suggested actions are bounded by policy and capability availability.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
