# HXI Glass Bridge — Design Prompt
## Next-Generation Human Experience for ProbOS Agentic OS

---

## One-Line Vision

**A sheet of frosted glass over a living neural mesh — the Captain's bridge for a starship that runs on agents, not engines.**

---

## Design Origin

### What Exists Today
The current HXI renders the cognitive mesh as a field of luminous orbs in 3D space. Each orb is an agent. Clusters represent departments (Core Systems, Engineering, Science, Medical, Self-Modification). Cyan arcs show Hebbian routing connections. Amber glow indicates high activity. A status bar reads system vitals: agent count, health, idle/active state, trust mean, entropy. A minimal text input floats at bottom center: "Ask ProbOS..." A unified Bridge panel slides in from the right with prioritized sections: Attention, Active, Notifications, Kanban, Recent. The main viewer can switch between the 3D canvas and a full kanban board.

This is the **substrate layer** — the raw neural visualization plus functional command panel. It works. It's beautiful. **Keep all of it.** The orbs, the breathing, the Hebbian arcs, the chat overlay, the Bridge panel — this is the foundation. The mesh is the ship's soul. The chat is the Captain's voice. The Bridge is the crew's report.

### What Comes Next
Layer a **frosted glass working surface** over the orbs. The mesh doesn't disappear — it breathes underneath, visible through the glass like bioluminescence under ice. But the glass is where the human *works*. The glass is where tasks live, where decisions surface, where the collaboration happens.

**Critical constraint:** The existing orb canvas remains the ever-present backdrop, exactly as it is today. The chat overlay (IntentSurface) stays as the Command Surface at the bottom. The Bridge panel on the right stays as the crew status console. The glass layer adds a *middle layer* — the collaboration and task surface that sits between the mesh and the command inputs. Think of it as three depth layers:

1. **Backdrop (z=0):** The 3D orb mesh — always there, always breathing, always beautiful
2. **Glass (z=1):** The task/collaboration surface — contextual cards, DAG nodes, decisions, artifacts
3. **Controls (z=2):** The Bridge panel (right), Command Surface (bottom), Context Ribbon (top) — always accessible

---

## Core Design Principles

### 1. The Glass Metaphor
The interface layers a translucent, subtly frosted glass over the existing living mesh. Not opaque — translucent. The orbs pulse and drift beneath, exactly as they do today. When the system is idle, the glass is nearly clear and the mesh is prominent (the current experience). When the human begins working, the glass frosts slightly and task content sharpens into focus on top. The depth relationship is literal: **your work is in the foreground, the mesh is the substrate beneath, and you can always see through**.

- OLED-native: true blacks beyond the glass edge. The glass itself has no border — it fades to transparency at the periphery. Content emerges from darkness.
- The frost level is dynamic. High-focus tasks increase frost (less mesh distraction). Overview/monitoring mode clears the frost (maximum mesh visibility — the current idle experience). The system reads engagement and adjusts automatically.
- Gaussian blur + subtle noise texture on the glass. Not Apple's frosted glass — grittier. Think cyberpunk holographic display viewed through cold condensation.

### 2. NeXTStep Precision, Cyberpunk Soul
Steve Jobs' NeXT interface was revolutionary because it was geometrically precise, information-dense, and unapologetically digital. It didn't pretend to be paper or wood. It was a *computer* and it looked like one. Carry that DNA forward:

- **Monospaced typography for system data.** Agent names, trust scores, status codes — all in a crisp monospace face (JetBrains Mono, Berkeley Mono, or similar). Human-facing content (task descriptions, reflections, conversation) uses a clean geometric sans (Inter, Geist, or similar).
- **Hard geometric containers** with precise 1px borders. No rounded-everything softness. Rectangles. Chamfered corners only where they encode meaning (e.g., a chamfered card = proposal awaiting approval, a sharp card = executed result).
- **High information density.** Respect the user's intelligence. Don't hide data behind progressive disclosure by default — show it, but at varying visual weights. Primary information is high-contrast. Secondary is dimmed. Tertiary is near-invisible until hovered. Everything is always *there*, just at different luminance levels.
- **Color as data, not decoration.** The cyberpunk palette is functional:
  - **Amber (#f0b060 → #ffcc44):** Active task, human attention needed, agent currently executing
  - **Cyan (#00e5ff → #4dd0e1):** System nominal, healthy connections, trust > 0.7
  - **Magenta (#e040fb → #f50057):** Alert, consensus disagreement, trust < 0.3, destructive operation pending
  - **Violet (#7c4dff → #b388ff):** Cognitive activity — LLM reasoning, episodic recall, dreaming
  - **White (#e0e0e0):** Human-authored content, user text, manual overrides
  - **True black (#000000):** OLED background. Pixels off. The void beyond the glass.
  - **Dim gray (#1a1a2e → #16213e):** The glass surface itself. Near-black but with depth.

### 3. Center-Focus Task Architecture
The human's current task is always at the center of the glass. Not a sidebar. Not a chat thread pushed to one side. **Center. Stage.** Everything radiates outward from the task.

```
                    ┌─────────────────────────────────────────┐
                    │           CONTEXT RIBBON                │
                    │  ◇ 3 agents active  ◇ trust 0.87       │
                    │  ◇ 2 sub-tasks pending                  │
                    ├─────────────────────────────────────────┤
                    │                                         │
                    │                                         │
                    │          ╔═══════════════════╗          │
                    │          ║   ACTIVE TASK      ║          │
                    │          ║                     ║          │
                    │          ║  "Refactor the      ║          │
                    │          ║   payment service   ║          │
                    │          ║   to use async      ║          │
                    │          ║   operations"       ║          │
                    │          ║                     ║          │
                    │          ║  ▸ DAG: 4 nodes     ║          │
                    │          ║  ▸ Progress: 2/4    ║          │
                    │          ║  ▸ Confidence: 0.91 ║          │
                    │          ╚═══════════════════╝          │
                    │                                         │
                    │    ┌──────────┐    ┌──────────┐         │
                    │    │ SUB-TASK │    │ SUB-TASK │         │
                    │    │ Read svc │    │ Design   │         │
                    │    │ ● done   │    │ ◐ active │         │
                    │    └──────────┘    └──────────┘         │
                    │    ┌──────────┐    ┌──────────┐         │
                    │    │ SUB-TASK │    │ SUB-TASK │         │
                    │    │ Write    │    │ Test     │         │
                    │    │ ○ queued │    │ ○ queued │         │
                    │    └──────────┘    └──────────┘         │
                    │                                         │
                    ├─────────────────────────────────────────┤
                    │  ✦ Ask ProbOS...                        │
                    │           ◆ voice  ◆ attach  ◆ propose │
                    └─────────────────────────────────────────┘
```

- The **Active Task Card** is the gravitational center. It's slightly raised from the glass (subtle parallax shadow, 2-3px offset). It breathes slowly when agents are working on it. It pulses amber when it needs human input.
- **Sub-task cards** orbit the center card in a spatial DAG layout. Completed cards dim and drift downward. Active cards glow. Queued cards are ghosted outlines. Dependencies are shown as faint connecting lines.
- **The Context Ribbon** runs across the top — a single dense line of system state. Not a header. A HUD element. Agent count, aggregate trust, pending decisions, elapsed time. Always visible, never demanding.
- **The Command Surface** at the bottom is more than a text input. It's a multimodal entry point: text, voice (visualized as a waveform in the input field), file attachment, and "propose" mode (where the human drafts a plan rather than a command). The input field has no visible border — just a subtle glow line at its base.

### 4. Human-Led, Agent-Operated
The Captain doesn't fly the ship. The Captain *commands* the ship. The crew flies it.

- **The human never sees "loading..."** — they see agents working. When the human submits a task, the glass doesn't show a spinner. It shows the DAG forming in real-time: nodes appearing, agents self-selecting (their orbs brighten beneath the glass), connections routing.
- **Decisions rise, results sink.** Anything that needs human attention floats upward toward the top of the glass. Completed work sinks down and eventually fades through the glass back into the mesh (becoming part of the system's memory). The vertical axis encodes urgency: top = needs you, middle = active, bottom = done.
- **The Captain's Gaze.** The system tracks where on the glass the human is focused (mouse position, scroll position, expanded panels). Agents working on things the human is looking at get slightly more context and slightly higher priority. Not a gimmick — genuine attention-weighted resource allocation.
- **Three interaction depths:**
  - **Command:** "Do this." → System executes autonomously. Results appear when done.
  - **Collaborate:** "Let's do this." → System proposes a DAG. Human reviews, modifies, approves. Execution progresses visibly. Human can intervene at any node.
  - **Direct:** "I'll do this." → System provides tools (embedded editor, terminal, browser). Agents observe and assist but don't act unless asked.

### 4b. Agent-First, Not App-First
The Bridge is an ops console, not an app launcher. The agents are the primary workers — the human is the Captain, not the operator.

- **Headless by default.** If agents can handle it, no glass surface needed. The Captain doesn't open an app to run tests — they see a task card showing the agent running tests. Agents are the Captain's digital eyes and hands. The glass only surfaces what needs the Captain's attention or what the Captain chooses to engage with.
- **Trust-driven progressive reveal.** New or low-trust agents get more prominent cards — the Captain needs to verify their work. High-trust agents get condensed representations — the Captain trusts them. Over time, the glass gets *quieter* as the crew earns trust. The visual layer of Earned Autonomy. This is deeply satisfying: the system proves itself and gets out of your way.
- **Multi-task constellation.** Agentic flow often means 3-5 concurrent agent workflows, not one focal task. The center of the glass supports a **constellation** — a cluster of active task cards with the most urgent one slightly elevated. The Captain's gaze (mouse position) promotes whichever task they attend to. This is the real adaptive focus: multiple things happening, emphasis shifts fluidly.
- **The Command Surface breathes with engagement.** When agents are autonomously executing, the input surface (today's chat overlay) recedes to a thin glow line — the Captain doesn't need it. When the Captain moves toward it (mouse approaches, keyboard activity), it swells to full capability. The glass reads the Captain's posture and adapts. This reduces the "I should be typing" pressure.

### 4c. Ambient Confidence — Glanceable System State
The Captain should know the system's state in under 1 second without reading a single number.

- **Ambient color temperature.** The glass edge and the mesh beneath shift color temperature based on system state. Cool blue-cyan = all nominal, crew executing. Warm amber edge = attention building, something may need the Captain soon. Hot magenta pulse = urgent, action required now. No reading required. The Captain walks back to their desk and knows the state before they sit down.
- **"Crew has it handled" state.** The prompt defines Idle (no tasks), but the optimal agentic state is different: *agents working, nothing needs the Captain.* This should feel distinctly good. The glass is clear, the mesh is active but calm, a subtle golden warmth at the edges says "your crew is executing, everything is fine." The Captain should feel the satisfaction of delegation working. This is NOT idle — it's the ship running well under the crew's command.
- **Return-to-bridge summary.** When the Captain has been away (no input for N minutes), the glass condenses into a briefing card on return: "While you were away: 3 tasks completed, 1 new notification, trust stable at 0.87." One card, one glance, caught up. Then it dissolves. This is the agentic equivalent of checking your phone — but curated by your crew.
- **Completion celebrations.** When an agent successfully completes a complex task, the mesh briefly blooms in the department color — engineering orange, science teal. The sound chord resolves. Brief, not obtrusive, but *earned*. The Captain feels pride in their crew. This is the delight that makes the system emotionally resonant.

### 5. The Bridge Aesthetic
This is the bridge of a starship, not a desktop. The environmental cues reinforce this:

- **No window chrome.** No title bars, no minimize/maximize/close. The glass IS the entire display. If the OS needs to surface system controls, they bleed in from the edges as ghosted overlays.
- **Ambient mesh beneath.** The orbs are always there, always moving, always breathing. They are the ship's engine room visible through a transparent deck plate. When the system is working hard, the mesh is more active — more connections firing, more glow. When idle, it's a slow, meditative drift.
- **Department sectors.** The mesh organizes into spatial clusters visible through the glass. The human learns to associate quadrants with function: upper-left = engineering agents, lower-right = science/research, center = core systems. Spatial memory replaces menu navigation.
- **Alert-driven reconfiguration (LCARS pattern).** When the system needs human attention — approve a build, resolve a consensus split, confirm a destructive operation — the glass reconfigures. The current layout compresses to make room for the **Decision Surface**: a prominent card with full context, agent recommendations, risk assessment, and clear approve/reject/modify affordances. Department colors bleed through:
  - **Engineering (orange):** Build proposals, code changes, deployment approvals
  - **Science (teal):** Research results, data analysis, knowledge graph updates
  - **Medical (green):** System health alerts, agent lifecycle events, recovery actions
  - **Security (red):** Destructive operations, permission escalations, trust violations
- **Status bar as ship's telemetry.** The bottom bar isn't a taskbar — it's a sensor readout. Continuous, real-time, information-dense:
  ```
  ● LIVE — 55 agents  Health: 0.82  ● idle  Trust: 0.114  Entropy: 2.756
  ```
  Each value is interactive on hover. Trust shows the distribution curve. Health shows per-department breakdown. Entropy indicates system complexity/disorder. The green dot is the heartbeat — it pulses with the system's actual heartbeat interval.

### 6. Authentically Digital
This is not a physical metaphor forced onto a screen. This is what a computer *should* look like when it stops pretending to be a desk. But cyberpunk ≠ visual noise. Every effect must justify its presence over an 8-hour workday, not just a screenshot.

- **Scan lines and chromatic aberration.** Available at configurable intensity (default: very subtle or off). These create depth and reinforce the "projected display" feel, but they fight readability over long sessions. The cyberpunk soul comes from the color palette, typography, and spatial design — not from CRT simulation. Let the user dial them up if they want the full aesthetic.
- **Luminance ripple transitions.** When state changes (new task, task complete, alert), a brief 50-100ms directional luminance sweep or ripple. Not a glitch — a glitch signals hardware failure on a real bridge, triggering anxiety. The ripple signals "the system shifted" with authority. Intentional, not broken.
- **Processing texture.** When the system is processing heavily, the mesh beneath the glass becomes more active — more connection arcs firing, orbs pulsing faster, more glow. This is organic and already part of the current experience. The human *feels* the system working through the mesh activity, not through artificial overlays. Data rain is available as an opt-in aesthetic layer (Ctrl+Shift+D) for users who want the cinematic feel, off by default.
- **No shadows except depth.** Physical shadows imply physical light sources. The glass has no drop shadows. It has *depth blur* — elements at different z-depths have different sharpness. The task card is sharp. The mesh beneath is soft. The status bar is sharp. This is focus-based depth, not light-based depth.

### 7. The Collaboration Canvas
When the human and agents are actively collaborating, the center of the glass transforms into a **collaboration canvas** — a shared workspace where both can contribute:

- **The DAG as a living diagram.** Not a static flowchart. Nodes breathe. Active nodes pulse. The human can drag nodes to reorder, tap to expand, swipe to dismiss. Agent edits to the DAG appear in real-time (nodes shifting, new connections routing) with a faint cyan trace showing "the system did this."
- **Inline agent commentary.** Agents can annotate the canvas — short, contextual notes that appear as small monospaced labels near their work. "Confidence: 0.72 — found 3 similar approaches in episodic memory." These annotations fade unless hovered.
- **Split-pane escalation.** When a sub-task needs human input, the canvas doesn't navigate away. The relevant node expands in-place, pushing adjacent content outward. The human addresses the question, the node collapses, work continues. No context switching.
- **Artifact embedding.** Code, documents, images, data visualizations — all render inline on the glass. No "open in new tab." The artifact appears as a frosted sub-panel within the task card, scrollable and interactive. The glass contains everything.

---

## Spatial Layout — The Five Zones

The glass is organized into five implicit zones. No visible borders between them — just spatial convention that the human learns through use. **Zones 2 and 4 are phantom zones** — invisible by default, materializing when they have relevant content and fading after acknowledgment. The Captain's workspace is maximally clear until something needs their attention.

```
┌────────────────────────────────────────────────────────────┐
│  ZONE 1: CONTEXT RIBBON (top edge)                         │
│  Ambient confidence glow · system state · active dept      │
├────────────────────────────────────────────────────────────┤
│              │                          │                   │
│  ZONE 2:     │   ZONE 3: TASK CENTER    │  ZONE 4:         │
│  HISTORY     │                          │  BRIDGE PANEL     │
│  (phantom    │   Multi-task constella-  │  (existing AD-387 │
│   left)      │   tion or single task    │   panel, slides   │
│              │   DAG · Collaboration    │   in from right)  │
│  Appears     │   canvas · Embedded      │                   │
│  when        │   artifacts              │  Attention ·      │
│  relevant    │                          │  Active · Notifs  │
│              │                          │  Kanban · Recent   │
│              │                          │                   │
├────────────────────────────────────────────────────────────┤
│  ZONE 5: COMMAND SURFACE (bottom edge)                      │
│  Current chat overlay · voice · attach · propose            │
└────────────────────────────────────────────────────────────┘
```

- **Zone 1 (Context Ribbon):** 32-40px. Single line. Dense. Monospaced. Updates in real-time. Encodes ambient confidence: the ribbon's edge glows cool cyan when nominal, warm amber when attention building, magenta when urgent. Slides left to show history on hover-hold.
- **Zone 2 (History):** Phantom zone. Invisible when not needed. Materializes on the left when a task completes or when the Captain's mouse drifts leftward. Shows recent task cards as compressed summaries. Tapping a history card pulls it back to center. Fades out when the Captain's attention returns to center. No permanent screen real estate.
- **Zone 3 (Task Center):** Dominant. Expands to fill available space. Shows the multi-task constellation (multiple concurrent agent workflows) or a single focused task DAG. When no task is active, this zone clears completely — the mesh shows through at full beauty. This IS today's canvas view, with task cards overlaid on top.
- **Zone 4 (Bridge Panel):** The existing AD-387 Bridge panel. Slides in from the right on the BRIDGE button. Contains the prioritized sections: Attention, Active, Notifications, Kanban, Recent. This is the crew's report — always accessible, never forced. When open, Zone 3 narrows but adapts. When closed, Zone 3 fills the full viewport.
- **Zone 5 (Command Surface):** The current chat overlay (IntentSurface). Preserved as-is — the Captain's voice. When expanded, it pushes upward. When collapsed, it's a single glowing line with "Ask ProbOS..." The surface recedes further when agents are autonomously executing (thin glow line) and swells when the Captain engages (mouse proximity, keyboard activity).

### Zone Behavior
- Zones 2 and 4 (sides) fade to near-transparency when the human is focused on Zone 3 (center). They sharpen when the mouse drifts toward them or when they have updates.
- Zone 3 expands to fill the glass when in **Focus Mode** (double-tap the task card or keyboard shortcut). Zones 2 and 4 slide off-edge. Zone 1 stays.
- The zones have no hard borders. Content in Zone 3 can overflow into Zones 2/4 if the DAG is large. The layout is gravitational, not grid-locked.

---

## Interaction Patterns

### Task Lifecycle
1. **Inception.** Human types or speaks into the Command Surface. The text appears center-glass as a glowing amber line, then transforms into a task card as the system begins decomposing.
2. **Decomposition.** Sub-task nodes materialize around the card — appearing one at a time as the DAG is built, not all at once. Faint connecting lines draw between them. The human can intervene during decomposition: "That's too many steps — combine these two."
3. **Execution.** Sub-task nodes activate sequentially or in parallel. Active nodes glow. The corresponding orbs beneath the glass brighten and pulse. Cyan connection arcs fire between the active agents' orbs. The human sees the mesh *responding* to their task.
4. **Decision Points.** When a sub-task needs human input, the node swells and floats upward (decisions rise). An amber pulse radiates from it. The glass slightly frosts the surrounding area to draw focus. The human addresses it and the node returns to its position.
5. **Completion.** Nodes dim to a cool gray as they complete. The task card updates its progress bar. When all nodes complete, the task card glows briefly, then slowly sinks downward and leftward into the History zone. A brief reflection summary appears in its place, auto-fading after 5 seconds unless the human engages it.
6. **Memory.** The completed task passes through the glass and becomes part of the mesh — literally. The episodic memory entry causes a subtle brightening in the relevant agent orbs. The system just learned from this interaction.

### Gesture Language (Mouse + Keyboard, extensible to touch/VR)
- **Click task card:** Expand detail view
- **Click sub-task node:** Expand that node's execution context
- **Drag node:** Reorder execution priority
- **Right-click node:** Context menu (retry, skip, reassign to different agent, add constraint)
- **Scroll in Zone 3:** Navigate the DAG spatially
- **Hover agent card (Zone 4):** Highlight the agent's orb beneath the glass, show trust distribution sparkline
- **Double-click task card:** Focus Mode (zones collapse)
- **Esc:** Exit Focus Mode / dismiss overlays
- **Ctrl+Space:** Toggle glass transparency (full mesh view / full glass view)
- **Ctrl+Shift+D:** Toggle data rain
- **↑ in Command Surface:** Previous command recall

---

## OLED Optimization

Every design decision accounts for OLED's strengths (per-pixel lighting, true black, infinite contrast):

- **True black background (#000000).** Pixels are off. The glass floats in void. This isn't just aesthetic — it saves power and creates the depth illusion.
- **OLED bloom.** Bright elements (amber task card, cyan connections, magenta alerts) naturally bloom against the black ground. Don't fight this — lean into it. The glow IS the interface's personality. HDR content uses 600-800 nit peaks for task cards and alerts against a 0-2 nit background.
- **Burn-in avoidance.** Static elements (zones, status bar) are kept at low luminance (< 40% brightness). High-luminance elements are transient (pulses, transitions, alerts). The glass texture includes micro-movement (very slow drift, 0.1px/frame) to prevent OLED burn. The status bar randomly offsets ±1px vertically every 15 minutes.
- **High contrast ratio.** Text on glass surfaces uses at minimum 7:1 contrast ratio (WCAG AAA). Primary text: #e0e0e0 on #1a1a2e. Secondary: #808090 on #0d0d1a. Alert text: #ffcc44 on #0d0d1a.

---

## Typography

| Role | Family | Weight | Size | Color | Tracking |
|------|--------|--------|------|-------|----------|
| System data | Berkeley Mono / JetBrains Mono | 400 | 11-12px | #808090 | +0.5px |
| Agent names | Mono | 500 | 12px | #a0a0b0 | +1px (uppercase) |
| Task titles | Geist / Inter | 600 | 16-18px | #e0e0e0 | 0 |
| Human text (conversation) | Geist / Inter | 400 | 14-15px | #e0e0e0 | 0 |
| Reflection/summary | Geist / Inter | 300 | 13px | #a0a0b0 | 0 |
| Context ribbon | Mono | 400 | 10px | #666680 | +1px |
| Alert text | Mono | 700 | 12px | #ffcc44 | +0.5px |

---

## Animation Timing

| Event | Effect | Duration | Easing |
|-------|--------|----------|--------|
| Task card appears | Fade up + scale 0.95→1.0 | 300ms | ease-out-cubic |
| Sub-task node appears | Pop in from center + settle | 200ms | spring(0.8, 0.3) |
| Node completes | Glow pulse + dim | 400ms | ease-in-out |
| Task completes (all nodes) | Department-color mesh bloom + chord resolve | 600ms | ease-out |
| Decision rises | Float upward 20-40px | 600ms | ease-out-quad |
| Task sinks to history | Drift left+down + compress | 800ms | ease-in-quad |
| Glass frost change | Gaussian blur transition | 1200ms | linear |
| State transition | Luminance ripple sweep | 80ms | ease-out |
| Ambient state shift | Edge color temperature transition | 1200ms | linear |
| Agent tether appears | Draw from card to orb | 300ms | ease-out |
| Alert pulse | Radial glow expand | 200ms + 200ms fade | ease-out + linear |
| Command Surface swell | Height expand on proximity | 300ms | ease-out |
| Command Surface recede | Height compress on inactivity | 800ms | ease-in |
| Return briefing card | Fade in center + dissolve on dismiss | 300ms in, 500ms out | ease-out, ease-in |

---

## Bridge States

The glass has three distinct ambient states, each with its own feel:

### The Idle Bridge (no tasks)
When no task is active, the glass is at minimum frost. The mesh dominates. The bridge is at rest. But it's not empty:

- The Context Ribbon still reads system vitals, edge glow is cool cyan
- Agent orbs breathe slowly — the system is alive, waiting
- Faint Hebbian connections shimmer between orbs — the system is always learning
- The Command Surface glows softly: **"Ask ProbOS..."**
- If dreaming is active (episodic consolidation), the mesh shows dream activity: brief flickers of past task patterns replaying across the orbs, like a sleeping brain

This is the screensaver that isn't a screensaver. It's the ship at warp — engines running, crew at stations, Captain on the bridge. Nothing needs doing, but everything is ready.

### The Autonomous Bridge (crew working, Captain free)
This is the optimal agentic state — agents are executing, nothing needs the Captain. This should feel distinctly *good*:

- The glass is clear but not idle — task cards float at low prominence in the constellation, showing progress
- The mesh is actively working: orbs pulse, connections fire, but at a calm, confident pace
- A faint golden warmth at the glass edges says "your crew is executing, everything is fine"
- The Command Surface is at minimum — a thin glow line. The Captain doesn't need to type
- The Context Ribbon shows progress counts: "3 active · 0 attention" in cool tones
- Completions trigger brief department-colored mesh blooms and ascending chimes

The Captain feels the satisfaction of delegation working. This is the emotional payoff for building a trusted crew. The glass is quiet because the system has *earned* quiet.

### The Attention Bridge (Captain needed)
When tasks need the Captain's input, the glass shifts:

- Ambient color warms toward amber at the edges — the Captain sees the shift peripherally
- Attention items float upward (decisions rise) and pulse with amber glow
- The Bridge panel highlights the Attention section with a count badge
- The Command Surface swells slightly — inviting input
- If multiple items need attention, they arrange as a prioritized stack, most urgent highest

The transition between states is smooth (1200ms ambient color shift), never jarring. The Captain always knows the state without reading — they can feel it.

---

## Sound Design (Optional, Human-Configured)

Sound follows the same principle as motion: it encodes state, never decorates.

- **Task inception:** Low, warm tone. A hum beginning.
- **Sub-task completion:** Soft chime. Ascending pitch for each sequential completion (building a chord across the DAG).
- **All tasks complete:** The chord resolves. Musical completion = task completion. The moment of pride — your crew delivered.
- **Alert/decision needed:** A calm but distinct tone. Not a notification bell — a tonal shift in the ambient soundscape. The bridge sounds different when it needs you, even before you see it.
- **Ambient state — Autonomous Bridge:** A steady, warm low hum. Slightly richer than idle. The sound of a healthy crew working. Reassuring.
- **Ambient state — Idle Bridge:** Barely audible low drone. The engine room hum. If you mute it, the silence is noticeable.
- **Return to bridge:** A brief welcoming tone when the Captain returns after absence. "Welcome back. Here's what happened."

---

## Responsive Behavior

The glass adapts to viewport without changing its principles:

- **Ultrawide (>2560px):** Full five-zone layout. Maximum information density. Side zones at full width. The mesh has maximum visible area.
- **Standard (1920px):** Five-zone default. Side zones slightly narrower.
- **Laptop (1366-1440px):** Side zones collapse to icons. Expand on hover. Task center takes full width.
- **Tablet (768-1024px):** Vertical stack. Context ribbon → Task center → Command surface. History and agents accessible via edge swipes. Glass effect maintained.
- **Mobile (<768px):** Single column. Task card fills viewport. Glass frost is heavier (mesh shown as ambient color shift only, not individual orbs). Gesture-driven navigation between zones.

---

## Implementation Philosophy

This is not built all at once. The glass layers over the existing mesh progressively. **The current HXI (orbs + chat + Bridge panel) is preserved at every phase.**

1. **Phase 0 (Current — AD-387 complete):** Mesh orbs + status bar + chat overlay + unified Bridge panel + adaptive main viewer (canvas/kanban). What exists today. This is the foundation.
2. **Phase 1 — The Glass:** Frosted overlay on the canvas with center task card(s). Mesh visible beneath. The glass renders task cards from existing `agentTasks` data — no new backend. Dynamic frost based on task count (more tasks = more frost). Multi-task constellation for concurrent workflows.
3. **Phase 2 — The DAG:** Sub-task nodes render spatially around task cards. Real-time execution visualization. DAG steps from existing `TaskStepView` data.
4. **Phase 3 — Ambient Intelligence:** Ambient confidence (edge color temperature), "crew has it handled" state, return-to-bridge briefing card, completion celebrations. Bridge states (Idle/Autonomous/Attention) drive visual mood.
5. **Phase 4 — The Alive Glass:** Configurable scan lines, chromatic aberration, data rain (all opt-in). The cyberpunk atmosphere layer for users who want maximum immersion.
6. **Phase 5 — The Adaptive Bridge:** Trust-driven progressive reveal (trusted agents get quieter cards). Command Surface breathing. Captain's Gaze attention weighting. Cognitive model adapts layout to human patterns.

Each phase is independently valuable. Phase 1 alone transforms the experience from "watching the mesh and checking the sidebar" to "commanding a ship."

---

## What This Is NOT

- **Not a chat app with a fancy background.** The task card is not a chat bubble. The Command Surface is not a chat input. The structure is spatial and persistent, not conversational and ephemeral.
- **Not a dashboard.** There are no widgets, no charts for their own sake, no grid of cards. The layout is task-driven, not metric-driven.
- **Not skeuomorphic.** The glass metaphor is about depth perception and focus management, not about simulating a physical object. There is no frame, no handle, no reflection. It's computational glass.
- **Not maximalist.** Cyberpunk ≠ visual noise. The density is intentional and every element earns its pixels. If you removed something and the Captain lost information, it stays. If you removed it and they didn't notice, it goes. Effects like scan lines, chromatic aberration, and data rain are opt-in aesthetics — not defaults.
- **Not replacing what works.** The orb mesh, the chat overlay, the Bridge panel — these exist and they're good. The glass layers over them. It doesn't replace them. Every phase builds on the current HXI, never discards it.

---

## Reference Touchstones

| Source | What to Take | What to Leave |
|--------|-------------|---------------|
| NeXTStep | Geometric precision, information density, typographic hierarchy, digital authenticity | Platform-specific widgets, window management paradigm |
| Cyberpunk 2077 UI | Color palette, scan lines, glitch language, data rain texture, neon-on-black contrast | Decorative noise, illegible text, style over function |
| LCARS (Star Trek) | Alert-driven reconfiguration, department color coding, bridge-as-workspace metaphor | Rounded corners everywhere, beige/purple palette, static layouts |
| Bloomberg Terminal | Information density, monospaced data, respect for expert users, keystroke efficiency | Visual monotony, zero delight, learning cliff |
| Minority Report | Spatial gesture interaction, transparent displays, depth-based UI | Hand-waving UX theatre, no persistent state |
| Apple Vision Pro | Frosted glass depth, focus-based sharpness, passthrough integration | Rounded softness, consumer-friendly simplicity, widget thinking |
| Westworld tablet UI | Clean glass aesthetic, data overlaid on translucent surface, cyberpunk-meets-precision | Prop-level fidelity (looks good, doesn't need to function) |

---

*The mesh is the brain. The glass is the bridge. The Captain commands. The crew executes. The ship earns its quiet. Welcome aboard.*
