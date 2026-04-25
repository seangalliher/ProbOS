# HXI Conversation Flow — "The Process Is Everything"

## Philosophy

The human-to-agent flow is a continuous conversation, not a series of isolated transactions. The user types a thought. The mesh responds. The user refines. The mesh adapts. Everything else — the canvas, the bloom, the animations — exists to give this conversation a living context. But the conversation itself is primary.

The current implementation treats each message as a discrete event: open pill → type → submit → pill closes → response panel appears → dismiss → click pill again → repeat. This breaks flow. It should feel like texting — continuous, effortless, always ready for the next message.

## Changes

### 1. Pill stays open after sending

After the user presses Enter and the message sends:
- The input field clears but STAYS focused and open
- The pill does NOT collapse back to resting state
- The user can immediately type their next message
- The pill only collapses when the user explicitly clicks away or presses Escape

### 2. Conversation appears inline, not as a separate panel

Instead of the response appearing in a floating "response panel" that auto-fades after 8 seconds:
- The conversation appears ABOVE the pill in a compact, scrollable thread
- User messages on the right (warm tint), system responses on the left (cool tint)
- The thread is semi-transparent so the canvas shows through
- Maximum height: 40% of viewport, scrollable
- The thread is always visible while the pill is focused
- When the pill collapses (Escape / click away), the thread fades with it
- The most recent exchange is always visible

### 3. Remove the separate response panel and feedback strip

The "Decision Surface" concept from the spec was designed for a command-response model. The conversation flow replaces it:
- Responses appear inline in the conversation thread
- Feedback buttons (👍 👎 ✏️) appear as small icons at the end of each system response — NOT as a separate strip
- No auto-fade. No "pin" button. The conversation persists while the pill is open

### 3b. Feedback buttons must give visible confirmation

When the user clicks a feedback icon, they need to SEE that something happened:

- **👍 Approve:** Icon briefly flashes green, then shows a small "✓ Learned" text that fades after 2 seconds. The icon stays but becomes dimmed/disabled (can't approve twice)
- **👎 Reject:** Icon briefly flashes red, then shows a small "✓ Noted" text that fades after 2 seconds. Icon becomes dimmed/disabled
- **✏️ Correct:** Opens the input field pre-filled with "correct: " and the original response context. The user types their correction and sends it as a message. This flows naturally in the conversation thread: the correction appears as a user message, and the system responds with confirmation

**Visual feedback on the canvas too:** When feedback is given:
- 👍: A brief golden pulse radiates from the center of the canvas — the mesh absorbed positive feedback
- 👎: A brief cool-blue pulse — the mesh noted negative feedback  
- These pulses are subtle (opacity 0.1, 500ms duration) but noticeable — the mesh visibly responds to your judgment

**Disable after use:** Each response's feedback icons can only be used once. After clicking any of the three, all three become disabled (dimmed) for that response. This matches the runtime's `_last_feedback_applied` flag that prevents double-rating.

### 4. The pill becomes a conversation anchor

When resting (pill collapsed):
- Shows "✦ Ask ProbOS..." as before
- Small badge showing recent message count
- Click → opens to conversation mode (input focused, recent thread visible)

When active (conversation mode):
- Input at bottom
- Conversation thread above, scrolling up
- Semi-transparent background so canvas is visible
- Width: 50-60% of viewport, centered
- Thread + input feel like a single integrated element

When you press Escape or click outside:
- Thread and input fade out smoothly
- Pill returns to resting state
- The mesh canvas becomes primary again

### 5. The mesh reacts to the conversation

While chatting:
- The canvas continues to animate — agents light up, routing pulses fire, consensus flashes happen
- The conversation thread is translucent so you SEE the mesh working behind it
- This is the "everything else fades" — the UI chrome is minimal and transparent, the process (mesh + conversation) is what you experience

### 6. Typing starts immediately

No click required to start typing. If the pill is visible and the user starts pressing keys, it should auto-focus and capture the keystrokes. Like Spotlight on macOS — just start typing.

Implementation: add a global `keydown` listener that, if no other input is focused and the key is a printable character, focuses the pill input and inserts the character.

## Implementation

**File:** `ui/src/components/IntentSurface.tsx` — significant rewrite

The component becomes a conversation anchor:

```
Resting state:
  ┌──────────────────┐
  │ ✦ Ask ProbOS...  │  (small pill, bottom center)
  └──────────────────┘

Active state (click pill or just start typing):
  ┌──────────────────────────────────┐
  │                                  │  ← conversation thread
  │  System: Hello! I'm ProbOS...   │     (scrollable, translucent)
  │                        You: hi  │
  │                                  │
  │  System: I can help with files, │
  │  web search, translation...     │
  │                                  │
  │ ┌──────────────────────────────┐ │
  │ │ Type your message...        │ │  ← input (always ready)
  │ └──────────────────────────────┘ │
  └──────────────────────────────────┘
```

- Enter sends message, clears input, keeps focus
- Escape collapses to resting pill
- Click outside collapses to resting pill
- Feedback icons (👍 👎) inline at end of each system message
- Thread max-height 40vh, overflow-y scroll
- Background: `rgba(10, 10, 18, 0.75)` with `backdrop-filter: blur(16px)`
- Smooth expand/collapse transition (300ms spring)

**File:** `ui/src/components/DecisionSurface.tsx` — simplify

Remove the response panel and feedback strip. The status bar at the very bottom (connection, agents, health, mode, TC_N) stays — it's useful ambient info. But the response display moves into the conversation thread above.

**File:** `ui/src/App.tsx` — add global keydown listener

```typescript
useEffect(() => {
  function handleGlobalKey(e: KeyboardEvent) {
    // Don't capture if another input is focused
    if (document.activeElement?.tagName === 'INPUT' || 
        document.activeElement?.tagName === 'TEXTAREA') return;
    // Only printable characters
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Trigger pill open + focus with this character
      // (communicate via store or event)
      useStore.getState().triggerInput(e.key);
    }
  }
  window.addEventListener('keydown', handleGlobalKey);
  return () => window.removeEventListener('keydown', handleGlobalKey);
}, []);
```

Store needs: `triggerInput: (char: string) => void` action that sets a flag for IntentSurface to consume.

## Do NOT Change
- No Python code changes
- No WebSocket protocol changes
- No canvas/Three.js changes
- No agent behavior changes
- Status bar at bottom stays (connection info is useful)
- The canvas remains the visual backdrop — the conversation is a translucent overlay

## The Vibe Check

After implementing: the pill is resting. You just start typing — the pill opens, captures your keys, and you're in conversation mode. You type "hello", Enter. Response appears above. You immediately type "what's the weather in Tokyo", Enter. Response appears. The mesh behind is pulsing, routing, reacting. You keep going. The flow is continuous. When you're done, Escape. The conversation fades. The mesh breathes alone.

If at any point you have to click a button to keep the conversation going, start over.
