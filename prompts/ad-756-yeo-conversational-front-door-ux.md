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

## Implementation Spec

### Section 1: Suggested Actions Panel

**File:** `ui/src/components/wardroom/SuggestedActionsPanel.tsx` (new)

Create component that displays 3–5 actions ranked by Hebbian routing + attention scoring:
```typescript
interface SuggestedAction {
  id: string;
  label: string;  // "Review meeting notes", "Approve PR"
  emoji: string;  // use SVG icon, not emoji
  agent: string;  // "ArchitectAgent", "OutlookAgent"
  score: number;  // Hebbian rank [0-1]
  metadata: { intent: string; context: string };
}

async function fetchSuggestedActions(): Promise<SuggestedAction[]> {
  // GET /work/suggested-actions → ranked list
}
```

**Endpoint:** `GET /work/suggested-actions` returns top-3 actions.

**Tests:** `tests/test_suggested_actions_panel.tsx` (1 test)
- Actions panel renders without errors

### Section 2: Welcome Panel & Onboarding

**File:** `ui/src/components/wardroom/WelcomePanel.tsx` (new)

First-run UX showing:
- "Welcome to Yeo, Captain's personal assistant"
- Example prompts: "What's on my calendar?", "Summarize my inbox", "Review the latest PR"
- Captain Card editor (set name, preferred contact, working hours)

**Tests:** `tests/test_welcome_panel.tsx` (1 test)
- Welcome panel displays on first login

### Section 3: Daily Briefing Panel

**File:** `ui/src/components/wardroom/DailyBriefingPanel.tsx` (new)

Displays synthesized briefing at start-of-day:
- "Overnight inbox: 12 new emails (3 flagged)"
- "Calendar: 5 meetings today, 2 free slots"
- "Suggested actions" → top-3 ranked by urgency + relevance

**Endpoint:** `GET /work/daily-briefing` returns structured briefing.

**Tests:** `tests/test_daily_briefing_panel.tsx` (1 test)
- Briefing renders without errors

### Section 4: Delegation Visibility & Handoff Reasoning

**File:** `ui/src/components/wardroom/DelegationReasoningPanel.tsx` (new)

When Yeo delegates to a specialist, show:
```
Yeo → ArchitectAgent
Reason: "You asked for architecture review; ArchitectAgent is best equipped"
Status: "Reading codebase..."
```

**Wire:** Each `TaskDAGNode` carries `delegated_to` + `delegation_reason` metadata.

**Endpoint:** `GET /dag/{dag_id}/delegation-trace` returns full routing.

**Tests:** `tests/test_delegation_reasoning_panel.tsx` (1 test)
- Delegation reason visible for each agent handoff

### Section 5: Stream Merge & Message Coherence

**File:** `src/probos/ward_room_pipeline.py` (extend)

Modify response streaming to prevent duplicates:
```python
async def merge_agent_responses(responses: list[AgentResponse]) -> str:
    """Merge multi-agent responses into coherent final message.
    
    Strategy: LLM reads all agent outputs + metadata, writes single unified response.
    Prevent: "Here's X. Here's X again from another agent."
    """
    all_content = [r.content for r in responses]
    metadata = [{"agent": r.agent, "intent": r.intent} for r in responses]
    
    merged = await llm.call(
        system="Synthesize these agent responses into a single coherent message. "
               "Avoid duplication; cite which agent provided each insight.",
        user=f"Agent outputs:\n{json.dumps(all_content)}\nMetadata:\n{json.dumps(metadata)}"
    )
    return merged
```

**Tests:** `tests/test_stream_merge.py` (2 tests)
- Multiple agent responses merged without duplication
- Final message cites source agents

### Section 6: At-Mention Delegation in Chat

**File:** `ui/src/components/wardroom/ChatInput.tsx` (extend)

Add @-mention autocomplete:
- Type `@` → list all registered agents + their intents
- `@OutlookAgent draft email` → delegates email drafting
- Full message: "Draft a thank-you email" → Yeo reasons it needs OutlookAgent

**Tests:** `tests/test_chat_mention.tsx` (1 test)
- @-mention autocomplete functional

### Section 7: Acceptance Criteria & Gate

**Test Expectations:**
- Vitest: 8 tests (1 per UI component + stream merge + mention)
- Python: 2 tests (stream merge + endpoint validation)
- **Total: 10 new tests**

**Dependencies:** Requires AD-750 (semantic layer for suggested actions), AD-753 (permissions for delegation), AD-755 (office skills for delegation targets).

**Type Annotations:** All TypeScript components fully typed (no `any`).

**Completion Signal:**
- All 10 tests passing
- Suggested actions visible on home screen
- Delegation reasoning appears when Yeo delegates
- Stream merge prevents duplicate responses in multi-agent flows

## Acceptance Criteria
- Delegation source/target and rationale are visible to the Captain.
- Stream merge behavior prevents duplicate or fragmented final responses.
- Suggested actions are bounded by policy and capability availability.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
