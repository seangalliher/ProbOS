# AD-752 - Proactive Scheduling + Work-Hours/Quiet-Hours Policy

Status: drafted (planning slate only)
Issue: #698
Parent: #486
Depends on: AD-750 (#696)
Related: #483

## Objective
Provide proactive assistant behavior with policy-safe heartbeat scans and schedule nudges.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Work-hours and quiet-hours policy model.
- Heartbeat/cron scan policy and suppression windows.
- Daily briefing trigger windows and reminder throttles.
- UX conventions for cron automation status and editability.

## Out of Scope
- Commercial enterprise policy orchestration products.
- Replacing existing task scheduler primitives.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Work-hours and quiet-hours configured locally by Captain.
- Cron-driven proactive scans during work hours.
- Daily briefing trigger windows and reminder throttles.

**Commercial Extension Point:**
- Org-wide work-hours policy distribution and enforcement.
- Incident routing during org quiet-hours (ROTA-based escalation).
- Cross-device proactive policy and time-zone handling for remote teams.

## File Targets
- `src/probos/proactive.py`
- `src/probos/duty_schedule.py`
- `src/probos/agents/operations/scheduler.py`
- `src/probos/config.py`
- `ui/src/components/wardroom/`

## Pre-Flight Anchors
- Verify scheduler behavior in `src/probos/agents/operations/scheduler.py`.
- Verify persistent scheduled-task APIs in `src/probos/routers/scheduled_tasks.py`.
- Verify proactive routing hooks in `src/probos/proactive.py`.

## Acceptance Criteria
- Work-hours/quiet-hours policies are explicit, testable, and overridable.
- Proactive scans are auditable with clear reason codes.
- No duplicate scheduler subsystem is introduced.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
