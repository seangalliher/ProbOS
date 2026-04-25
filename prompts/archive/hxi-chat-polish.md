# HXI Polish: Markdown Chat Rendering + TTS Cleanup + Chat Persistence

Three self-contained UI improvements. All frontend-only — no Python changes.

---

## 1. Markdown Rendering in Chat Messages

### Problem
Chat messages render as raw text with `whiteSpace: 'pre-wrap'`. LLM responses contain markdown (`**bold**`, `• bullets`, `## headers`, `---` dividers, backticks) that should render as formatted HTML.

### Implementation

Install `react-markdown`:
```bash
cd ui && npm install react-markdown
```

In `ui/src/components/IntentSurface.tsx`, replace the raw text rendering:

```tsx
{msg.text}
```

with:

```tsx
import ReactMarkdown from 'react-markdown';

// ... inside the message div:
<ReactMarkdown
  components={{
    // Style overrides to match HXI aesthetic
    p: ({children}) => <p style={{ margin: '4px 0' }}>{children}</p>,
    strong: ({children}) => <strong style={{ color: '#f0d0a0' }}>{children}</strong>,
    h2: ({children}) => <h2 style={{ fontSize: 14, margin: '8px 0 4px', color: '#f0d0a0' }}>{children}</h2>,
    h3: ({children}) => <h3 style={{ fontSize: 13, margin: '6px 0 3px', color: '#f0d0a0' }}>{children}</h3>,
    ul: ({children}) => <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul>,
    ol: ({children}) => <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol>,
    li: ({children}) => <li style={{ margin: '2px 0' }}>{children}</li>,
    code: ({children}) => <code style={{ background: 'rgba(240, 176, 96, 0.1)', padding: '1px 4px', borderRadius: 3, fontSize: 12 }}>{children}</code>,
    hr: () => <hr style={{ border: 'none', borderTop: '1px solid rgba(136, 164, 200, 0.15)', margin: '8px 0' }} />,
    a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#88a4c8' }}>{children}</a>,
  }}
>
  {msg.text}
</ReactMarkdown>
```

Remove the `whiteSpace: 'pre-wrap'` from the message container style (ReactMarkdown handles line breaks via block elements).

Keep `wordBreak: 'break-word'` for long URLs.

### Important
- Only apply ReactMarkdown to `system` role messages. User messages should stay as plain text (they typed it, don't reformat it).
- For user messages, keep the existing `{msg.text}` with `whiteSpace: 'pre-wrap'`.

---

## 2. TTS Cleanup

### Problem
The TTS `speakResponse()` receives the full markdown text including `**`, `•`, `---`, etc. The speech synthesizer reads these as literal characters ("asterisk asterisk bold asterisk asterisk").

### Implementation

In `ui/src/components/IntentSurface.tsx`, where `speakResponse(response)` is called, strip markdown before passing to TTS:

```tsx
if (voiceEnabled && response && !response.startsWith('(')) {
  // Strip markdown formatting for cleaner TTS
  const cleanText = response
    .replace(/\*\*(.+?)\*\*/g, '$1')     // **bold** → bold
    .replace(/\*(.+?)\*/g, '$1')          // *italic* → italic
    .replace(/#{1,6}\s/g, '')             // ## headers → plain
    .replace(/[-•]\s/g, '')               // bullet points
    .replace(/---+/g, '')                 // horizontal rules
    .replace(/`(.+?)`/g, '$1')            // `code` → code
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')   // [link](url) → link text
    .replace(/\n{2,}/g, '. ')             // double newlines → pause
    .trim();
  speakResponse(cleanText);
}
```

Also update the voice preference list in `ui/src/audio/voice.ts` — add Edge neural voices which are higher quality than the defaults:

```typescript
const preferred = voices.find(v =>
  v.lang.startsWith('en') && (
    v.name.includes('Microsoft Mark Online') ||  // Edge neural (natural)
    v.name.includes('Microsoft Aria Online') ||  // Edge neural (natural)
    v.name.includes('Google US English') ||
    v.name.includes('Google UK English') ||
    v.name.includes('Natural') ||
    v.name.includes('Samantha') ||
    v.name.includes('Microsoft Zira') ||
    v.name.includes('Microsoft David')
  )
) || voices.find(v => v.lang.startsWith('en')) || null;
```

---

## 3. Chat History Persistence (localStorage)

### Problem
Chat messages disappear on page refresh. Users lose context.

### Implementation

In `ui/src/store/useStore.ts`:

1. On `addChatMessage`, save to localStorage:
```typescript
addChatMessage: (role, text, meta) => {
    const msg: ChatMessage = { ... };
    set((s) => {
      const updated = [...s.chatHistory.slice(-49), msg];
      // Persist to localStorage (drop selfModProposal — not restorable)
      try {
        const serializable = updated.map(m => ({
          id: m.id, role: m.role, text: m.text, timestamp: m.timestamp,
        }));
        localStorage.setItem('hxi_chat_history', JSON.stringify(serializable));
      } catch {}
      return { chatHistory: updated };
    });
  },
```

2. On store initialization, restore from localStorage:
```typescript
chatHistory: (() => {
    try {
      const stored = localStorage.getItem('hxi_chat_history');
      if (stored) return JSON.parse(stored) as ChatMessage[];
    } catch {}
    return [];
  })(),
```

3. On the existing clear button (already wired to `useStore.setState({ chatHistory: [] })`), also clear localStorage:
```typescript
useStore.setState({ chatHistory: [] });
localStorage.removeItem('hxi_chat_history');
```

---

## Build and Test

After all changes:
```bash
cd ui && npm run build
```

Then restart `probos serve` and verify:
1. Send "Hello" — response renders with formatted text (bold, bullets if any)
2. Send a weather query — reflection renders with markdown formatting
3. Toggle voice on — TTS reads clean text without "asterisk asterisk"
4. Refresh the browser page — chat history persists
5. Click clear button — history cleared including localStorage

## Constraints

- Only touch UI files: `ui/src/components/IntentSurface.tsx`, `ui/src/audio/voice.ts`, `ui/src/store/useStore.ts`, `ui/package.json`
- Do NOT touch any Python files
- Do NOT modify the canvas, animations, or agent rendering
- Do NOT add any new React components — modify existing ones
- Run Python tests after to verify no regressions: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Rebuild UI: `cd ui && npm run build`
