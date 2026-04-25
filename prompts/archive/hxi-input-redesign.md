# HXI Input Redesign — "Think Into The Mesh"

## Problem

The current chat input is a full-width text bar bolted on top of the canvas. It feels like a web form, not a cognitive interface. It covers the canvas, doesn't adapt to content, and creates a jarring contrast between the atmospheric WebGL scene and the flat HTML input. The chat history scrolls over the canvas as a standard message list.

The HXI spec says: "The HXI is not a dashboard. It is a cognitive membrane." The input should feel like you're thinking into the mesh, not typing into Google.

## Design: The Pulse Input

### Resting State
- A small, breathing pill shape at bottom-center of the viewport
- Size: ~120px wide, 40px tall. Centered horizontally
- Semi-transparent dark background with subtle warm border glow (`rgba(240, 176, 96, 0.15)`)
- Contains a faint cursor icon or "✦" symbol and the hint text "Ask..." (not "Ask ProbOS anything..." — too long for a pill)
- Gently pulses opacity in sync with the heartbeat rhythm (±5% opacity, 1.2s cycle)
- Does NOT cover any significant canvas area

### Focus / Active State  
- On click: pill smoothly expands to ~50% viewport width (spring animation with overshoot, ~300ms)
- The expansion is centered — grows equally left and right from center
- Background slightly more opaque. Border glow brightens
- Canvas behind dims by ~15% (subtle vignette effect, NOT a modal overlay)
- Cursor appears. User types freely
- Input grows horizontally with content: minimum 40% width, maximum 70% width
- Never full-screen width. Never touches the edges. The canvas breathes around it
- Height stays single-line unless text wraps (then grows to max 3 lines)

### Submission
- Enter submits. The text inside the input fades out (200ms)
- The pill smoothly contracts back to resting state (spring, 300ms)
- The canvas brightens back to normal
- A small indicator appears near the pill: a loading dot-pulse showing "processing"
- DAG execution events animate in the canvas as before

### Response Display
- Responses do NOT appear inline in a chat log above the input
- Instead: response materializes as a **floating panel** rising from the bottom-center
- The panel is translucent dark with backdrop blur, warm border, rounded corners
- Response text appears with a typewriter fade-in effect (characters materialize left-to-right, ~20ms per character, or all-at-once for long responses)
- The panel auto-sizes to content: short responses = compact panel, long = taller (max 40% viewport height, scrollable)
- The panel persists for 8 seconds after the last character appears, then fades out (3 second fade) unless the user hovers it
- If the user hovers: panel stays visible until mouse leaves (then starts the 8s timer)
- If a new response arrives while the previous is showing: previous fades out quickly (500ms), new one rises in
- The panel has a small "pin 📌" button that keeps it visible permanently until dismissed

### Chat History
- Not visible by default. The canvas stays clean
- The resting-state pill has a tiny history indicator: a small dot above it showing count of recent messages (like an unread badge, but subtle — `"3"` in dim text)
- Click the pill when it's resting (not focused): instead of expanding to input mode, shows a **history panel** — translucent scrollable list of recent exchanges (last 20)
- History panel: rises from bottom-center, same style as response panel but taller
- Each entry: user text (warm tint, right-aligned) and system response (cool tint, left-aligned)
- Click anywhere outside the history panel to dismiss
- Click the input area within the history panel to switch to input mode (history panel morphs into input)
- Press Escape to dismiss history and return to resting pill

### Feedback Strip
- The Approve/Correct/Reject buttons should appear briefly WITHIN the response panel (not as a separate strip)
- Three small icon buttons at the bottom-right of the response panel: 👍 👎 ✏️
- They appear when a response arrives and fade with the response panel
- If the panel is pinned, feedback buttons persist

### DAG Progress
- When a DAG is executing, show progress NOT as a horizontal bar of nodes in the Intent Surface
- Instead: show a small compact indicator near the pulse input — "⚡ 2/3 tasks" — minimal, unobtrusive
- The real DAG progress is visible in the CANVAS — agents lighting up, routing pulses, consensus flashes
- This removes the need for, a separate DAG visualization component overlaying the canvas

## Implementation

### Files to modify:
- `ui/src/components/IntentSurface.tsx` — complete rewrite to the Pulse Input design
- `ui/src/components/DecisionSurface.tsx` — response panel + feedback integration
- `ui/src/App.tsx` — adjust layout if the Intent/Decision surfaces change structure

### CSS/Style guidelines:
- Use CSS `transition` for all size/opacity changes (spring feel via `cubic-bezier(0.34, 1.56, 0.64, 1)`)
- `backdrop-filter: blur(12px)` on all translucent panels
- Border: `1px solid rgba(240, 176, 96, 0.15)` (warm, subtle)
- Border-radius: `24px` for the pill, `16px` for panels
- Font: same as existing (`Inter`, warm off-white `#e0dcd4`)
- All animations: organic easing, never linear, never snapping

### Key interaction states:
```
Resting   →  (click)   →  Focused/Input  →  (Enter)  →  Processing  →  Response Panel  →  (8s/fade)  →  Resting
Resting   →  (click)   →  History Panel   →  (click outside)  →  Resting
Response  →  (hover)   →  Persists        →  (mouse leave)    →  8s timer → Fade → Resting
Response  →  (pin 📌)  →  Persists        →  (dismiss)        →  Resting
```

### Reset / Clear

Since there's no persistent chat log on screen, "reset" is about clearing stored history:

- **History panel** has a small "Clear" link at the bottom — clears all stored chat messages from the Zustand store. The canvas/agents/trust are unaffected
- The resting pill could have a subtle right-click context menu with "Clear history" and "New session" options
- **"New session"** sends a POST to `/api/chat` with the message `/reset` (or a dedicated endpoint if one exists) — this clears the runtime's working memory and attention focus for a fresh conversational context, without restarting ProbOS or losing learned trust/routing

These are secondary interactions — most users won't need them because responses auto-fade and the canvas stays clean by default.

## Do NOT Change
- No Python code changes (unless a `/api/reset` endpoint is needed — in that case, add a minimal one that clears working memory)
- No WebSocket protocol changes  
- No Zustand store schema changes (can add `showHistory`, `pinnedResponse` boolean state)
- No Three.js canvas changes
- No agent behavior changes
- The canvas remains the visual hero — the input/output UI is secondary, atmospheric, and non-intrusive

## The Vibe Check
After implementing: look at the screen with the input in resting state. The canvas should be 95% of what you see. A small, breathing pill at the bottom. The mesh is alive. You click the pill, type a thought, press Enter, and your words dissolve into the system. A response rises from the depth, glowing softly. You read it. It fades. The mesh continues breathing. You are inside it.

If the UI feels like a chat app with a fancy background, start over.
