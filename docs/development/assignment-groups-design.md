# AD-408: Dynamic Assignment Groups

## Summary

Agents have a permanent **department** (where their desk is) and optional temporary **assignments** (where they're working right now). Assignments are transient overlays on the static pool group structure — they don't change pool membership, agent routing, or department affiliation. They change visual clustering on the canvas and auto-create Ward Room channels.

## Motivation

Current pool groups are static, registered at startup. Every agent orb sits in its department cluster forever. But real work is cross-departmental:

- A security audit needs Wesley (Science) + Worf (Security) + O'Brien (Operations)
- A build wave needs LaForge (Engineering) + Scotty (Engineering) + Number One (Science)
- Bridge duty pulls Troi and Number One into the command center temporarily

Without dynamic assignments, the canvas shows organizational structure but not operational activity. The Captain can't glance at the canvas and see "three agents are working together on something."

## Design

### Assignment Types

| Type | Duration | Example | Auto-dissolves |
|------|----------|---------|----------------|
| **Bridge** | Session-scoped | Captain opens a command session | When session ends |
| **Away Team** | Mission-scoped | Cross-department task force for a specific goal | When mission completes or Captain dissolves |
| **Working Group** | Open-ended | Ongoing cross-department initiative | Captain dissolves manually |

### Data Model

```python
@dataclass
class Assignment:
    id: str                          # uuid
    name: str                        # "Security Audit Alpha", "Bridge Watch"
    assignment_type: str             # "bridge" | "away_team" | "working_group"
    members: list[str]               # agent_ids
    created_by: str                  # Captain or agent_id
    created_at: float
    completed_at: float | None = None
    mission: str = ""                # Brief description of purpose
    ward_room_channel_id: str = ""   # Auto-created Ward Room channel
    status: str = "active"           # "active" | "completed" | "dissolved"
```

### Behavior

**Creating an assignment:**
- Captain creates via API/shell: `/assign away-team "Security Audit" @wesley @worf @obrien`
- Or programmatically via API: `POST /api/assignments`
- Ward Room auto-creates a channel for the assignment (type="custom", named after the assignment)
- Members get notified via the notification system

**Visual on canvas:**
- Assigned agents' orbs animate smoothly from their department cluster to a new transient cluster
- The transient cluster appears as a smaller sphere with a distinct tint (maybe white/silver for away teams)
- A dashed/dotted wireframe boundary (vs solid for departments) signals transience
- Label shows assignment name instead of department
- Agents retain a faint connection line back to their department sphere (ghost line)

**Sphere click → group chat:** Clicking any group sphere (department or assignment) opens the Ward Room channel for that group. The visual structure IS the navigation. Click the bridge sphere → bridge channel opens with all bridge officers in context. Click the Engineering sphere → #engineering channel. This connects AD-407 (Ward Room) to AD-408 (Assignments) through spatial interaction.

**When assignment completes/dissolves:**
- Agent orbs animate back to their department clusters
- Transient sphere shrinks and fades
- Ward Room channel is archived (not deleted — conversations persist)
- Assignment record preserved for history

**Agents are NOT removed from their department pool.** This is critical — assignments are a visual and communication overlay, not a pool membership change. Agent routing, intent handling, and pool scaling are unaffected. An agent on an away team still responds to department intents. They're just *also* collaborating on the assignment.

### Bridge as a Special Assignment

The Bridge is not a permanent pool group — it's a standing assignment. When the Captain opens a command session, Bridge officers (Number One, Troi) are automatically assigned. Other agents can be temporarily pulled to the bridge ("I need LaForge on the bridge").

This means the Bridge sphere only appears when there's an active command session. When the Captain is offline, Bridge officers return to their department clusters. This is visually accurate — the bridge is staffed when the Captain is present.

### Layout Integration

`computeLayout()` gets a new parameter: `assignments: Assignment[]`

Algorithm change:
1. First pass: compute department clusters (existing logic)
2. Second pass: for any agent in an active assignment, override their position to the assignment cluster
3. Assignment clusters are placed at a smaller radius (4.0 vs 6.0) — closer to center, signaling "active work"
4. Bridge assignment is always at origin (0, 0, 0) — the true center

### API Endpoints

```
POST   /api/assignments                 — Create assignment
GET    /api/assignments                 — List active assignments
GET    /api/assignments/{id}            — Get assignment detail
POST   /api/assignments/{id}/members    — Add/remove members
POST   /api/assignments/{id}/complete   — Mark assignment complete
DELETE /api/assignments/{id}            — Dissolve assignment
```

### WebSocket Events

```
assignment_created    — New assignment, UI creates transient cluster
assignment_updated    — Members changed, UI re-layouts
assignment_completed  — Assignment done, UI animates agents back to departments
```

### Ward Room Integration

Each assignment auto-creates a Ward Room channel:
- Channel type: `"custom"` (reuses existing Ward Room infrastructure)
- Channel name: Assignment name
- Auto-subscribes all assignment members
- Channel archived when assignment completes (not deleted)

### Shell Commands

```
/assign away-team "name" @agent1 @agent2 ...   — Create away team
/assign bridge @agent1 @agent2 ...              — Pull agents to bridge
/assign working-group "name" @agent1 ...        — Create working group
/assign list                                     — Show active assignments
/assign complete <id>                            — Complete an assignment
/assign dissolve <id>                            — Dissolve immediately
```

## What This Replaces

- **No Bridge PoolGroup** — Bridge is an assignment, not a static group
- The Counselor's pool stays `"bridge"` for routing purposes, but she visually sits in an assignment cluster only when the bridge is active

## Implementation Phases

**Phase 1 (AD-408a):** Backend — `AssignmentService` with SQLite, data model, API endpoints, Ward Room auto-channel, WebSocket events. No canvas changes yet.

**Phase 2 (AD-408b):** Frontend — `computeLayout()` assignment override, transient cluster rendering (dashed wireframe, different tint), smooth position animation, ghost department connection lines.

**Phase 3 (AD-408c):** Shell commands, bridge auto-activation on Captain login, agent notification integration.

## Prior Art

- **Kubernetes:** Pods have a permanent namespace (department) plus labels (assignments) that create ad-hoc groupings. Services select by label, not by namespace. Same principle: static org + dynamic overlay.
- **Slack Huddles:** Temporary audio channels that auto-dissolve. The assignment is the huddle; the Ward Room channel is the text trace.
- **Military:** Permanent unit assignment (1st Battalion) vs temporary task force attachment (Task Force X-Ray). The soldier belongs to their battalion but operates under the task force commander.

## Risks

- **Visual clutter** — Too many active assignments could make the canvas noisy. Mitigate: cap active assignments, auto-dissolve stale ones.
- **Routing confusion** — Agents in assignments still respond to department intents. This is a feature, not a bug, but could be confusing. Clear documentation needed.
- **Ward Room channel sprawl** — Every assignment creates a channel. Archived channels accumulate. Mitigate: archival + summarization (Ward Room Phase 2).
