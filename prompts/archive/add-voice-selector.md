# Voice Selector Dropdown in HXI

## What to build

Add a voice picker dropdown that appears next to the voice toggle button in the DecisionSurface. The user can choose from available browser voices. Selection persists in localStorage.

## Implementation

### File: `ui/src/audio/voice.ts`

1. Export a function to get available voices:
```typescript
export function getAvailableVoices(): SpeechSynthesisVoice[] {
  if (!('speechSynthesis' in window)) return [];
  return speechSynthesis.getVoices().filter(v => v.lang.startsWith('en'));
}
```

2. Export a function to set a specific voice by name:
```typescript
export function setPreferredVoiceName(name: string | null): void {
  cachedVoice = null; // Clear cache so next speak uses new preference
  if (name) {
    localStorage.setItem('hxi_voice_name', name);
  } else {
    localStorage.removeItem('hxi_voice_name');
  }
}
```

3. Modify `findPreferredVoice()` to check localStorage first:
```typescript
function findPreferredVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  voicesLoaded = true;

  // Check user preference first
  const savedName = localStorage.getItem('hxi_voice_name');
  if (savedName) {
    const saved = voices.find(v => v.name === savedName);
    if (saved) {
      cachedVoice = saved;
      return saved;
    }
  }

  // Auto-detect best available (existing logic)
  const preferred = voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online (Natural)')
  ) || voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online')
  ) || voices.find(v =>
    v.lang.startsWith('en') && (
      v.name.includes('Google US English') ||
      v.name.includes('Google UK English') ||
      v.name.includes('Natural') ||
      v.name.includes('Samantha')
    )
  ) || voices.find(v => v.lang.startsWith('en')) || null;

  cachedVoice = preferred;
  return preferred;
}
```

4. Export a function to get the current voice name:
```typescript
export function getCurrentVoiceName(): string {
  const voice = findPreferredVoice();
  return voice?.name || 'Default';
}
```

### File: `ui/src/components/DecisionSurface.tsx`

Add a voice selector dropdown that shows when the user right-clicks the voice button (same pattern as the volume slider on the sound button).

1. Import from voice.ts:
```typescript
import { getAvailableVoices, setPreferredVoiceName, getCurrentVoiceName } from '../audio/voice';
```

2. Add state:
```typescript
const [showVoicePicker, setShowVoicePicker] = useState(false);
const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
```

3. Load voices when picker opens:
```typescript
useEffect(() => {
  if (showVoicePicker) {
    setAvailableVoices(getAvailableVoices());
  }
}, [showVoicePicker]);
```

4. Add right-click handler to voice button:
```tsx
<button
  onClick={() => setVoiceEnabled(!voiceEnabled)}
  onContextMenu={(e) => { e.preventDefault(); setShowVoicePicker(!showVoicePicker); }}
  style={btnStyle(voiceEnabled)}
  title={voiceEnabled ? 'Disable voice (right-click: choose voice)' : 'Enable voice output'}
>
  {'\uD83D\uDDE3\uFE0F'}
</button>
```

5. Add the dropdown after the voice button (only when showVoicePicker is true):
```tsx
{showVoicePicker && (
  <div style={{
    position: 'absolute',
    bottom: 40,
    right: 60,
    background: 'rgba(10, 10, 18, 0.92)',
    backdropFilter: 'blur(12px)',
    border: '1px solid rgba(240, 176, 96, 0.2)',
    borderRadius: 8,
    padding: '8px 0',
    maxHeight: 200,
    overflowY: 'auto',
    zIndex: 30,
    minWidth: 250,
  }}>
    <div style={{
      padding: '4px 12px 8px',
      fontSize: 11,
      color: '#888',
      borderBottom: '1px solid rgba(240, 176, 96, 0.1)',
    }}>
      Choose voice
    </div>
    {availableVoices.map((voice) => (
      <div
        key={voice.name}
        onClick={() => {
          setPreferredVoiceName(voice.name);
          setShowVoicePicker(false);
          // Speak a sample so user hears the voice immediately
          if (voiceEnabled) {
            import('../audio/voice').then(m => m.speakResponse('Voice selected'));
          }
        }}
        style={{
          padding: '6px 12px',
          fontSize: 12,
          cursor: 'pointer',
          color: voice.name === getCurrentVoiceName() ? '#f0b060' : '#c8d0e0',
          background: voice.name === getCurrentVoiceName() ? 'rgba(240, 176, 96, 0.08)' : 'transparent',
          fontFamily: "'Inter', sans-serif",
        }}
        onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(240, 176, 96, 0.15)'; }}
        onMouseLeave={(e) => { (e.target as HTMLElement).style.background = voice.name === getCurrentVoiceName() ? 'rgba(240, 176, 96, 0.08)' : 'transparent'; }}
      >
        {voice.name.replace(/ - English.*$/, '')}
        {voice.name.includes('Online (Natural)') && ' ✨'}
        {voice.name.includes('Online') && !voice.name.includes('Natural') && ' 🔵'}
      </div>
    ))}
  </div>
)}
```

The display name is stripped of "- English (United States)" for brevity. Neural voices get a ✨ indicator, other online voices get 🔵.

6. Close the picker when clicking elsewhere — add to the existing click-outside handler or add a simple `onBlur` approach.

## Constraints

- Only touch `ui/src/audio/voice.ts` and `ui/src/components/DecisionSurface.tsx`
- Do NOT touch any Python files
- Do NOT modify IntentSurface or canvas code
- Rebuild after: `cd ui && npm run build`
- Run Python tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
