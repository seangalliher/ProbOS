# AD-271: Vibe Agent Creation — Human-Guided Agent Design

## Problem

Self-mod agent creation is fully automated — the human only gets approve/reject. No input into WHAT gets built or HOW. This leads to poorly designed agents (e.g., an agent that hits LinkedIn directly instead of searching via DuckDuckGo) because the LLM guesses the implementation approach.

## Design

Add a "Vibe Agent Creation" mode alongside the existing auto mode. When a capability gap is detected, the HXI shows two options:

- **"✨ Build Agent"** — auto mode (current behavior, LLM designs everything)
- **"🎨 Design Agent"** — vibe mode (human describes what they want, ProbOS enriches, human reviews, then builds)

### Vibe flow:

1. **User clicks "🎨 Design Agent"** → HXI shows a text input: "Describe how this agent should work"
2. **User types description** → e.g., "Search DuckDuckGo for the person's name, parse the results, find LinkedIn and Twitter profiles"
3. **POST `/api/selfmod/enrich`** → LLM takes the rough description + intent metadata and produces an enriched, detailed spec
4. **HXI shows enriched spec** → user reads the enhanced description with implementation details
5. **User approves** (or edits and resubmits) → **POST `/api/selfmod/approve`** with the enriched description as `intent_description`
6. **Same pipeline as auto** — design → validate → sandbox → deploy → auto-retry

### Key insight
The enriched description becomes the `intent_description` parameter passed to `AgentDesigner.design_agent()`. A detailed description like "use DuckDuckGo HTML search, parse results for LinkedIn profile URLs, extract name/title/company from snippets" produces dramatically better agents than a vague "look up a person."

## Implementation

### Backend: `src/probos/api.py`

Add one new endpoint:

```python
class EnrichRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    user_guidance: str  # The human's rough description

@app.post("/api/selfmod/enrich")
async def enrich_selfmod(req: EnrichRequest) -> dict[str, Any]:
    """Enrich a rough agent description into a detailed implementation spec."""
    if not getattr(runtime, 'llm_client', None):
        return {"enriched": req.user_guidance, "status": "no_llm"}

    from probos.types import LLMRequest

    enrich_prompt = (
        f"A user wants to create a new ProbOS agent. They provided this guidance:\n\n"
        f"Intent name: {req.intent_name}\n"
        f"Basic description: {req.intent_description}\n"
        f"Parameters: {req.parameters}\n"
        f"User's guidance: {req.user_guidance}\n\n"
        f"Expand this into a detailed, specific implementation plan for the agent. Include:\n"
        f"1. Exactly which URLs/APIs to use (prefer free, no-auth sources like DuckDuckGo)\n"
        f"2. How to parse the response data\n"
        f"3. What output format to return\n"
        f"4. Error handling approach\n"
        f"5. Any important constraints or limitations\n\n"
        f"Write this as a clear, concise specification (3-5 bullet points). "
        f"This will be given to an AI code generator to build the agent."
    )

    try:
        response = await runtime.llm_client.complete(LLMRequest(
            prompt=enrich_prompt,
            system_prompt=(
                "You are a technical architect helping design an AI agent. "
                "Produce a clear, actionable implementation spec from the user's rough description. "
                "Be specific about data sources, parsing strategies, and output format. "
                "Keep it concise — 3-5 bullet points. No code, just the spec."
            ),
            tier="fast",
            max_tokens=400,
        ))
        enriched = response.content.strip() if response and response.content else req.user_guidance
    except Exception:
        enriched = req.user_guidance

    return {
        "enriched": enriched,
        "intent_name": req.intent_name,
        "intent_description": req.intent_description,
        "parameters": req.parameters,
        "status": "ok",
    }
```

Also update the `SelfModRequest` model and the `/api/selfmod/approve` handler — when an enriched description is provided, use it as the `intent_description` instead of the original. The existing `SelfModRequest` already has `intent_description: str`, so the enriched text just goes there. No backend change needed for approve — the frontend sends the enriched text as `intent_description`.

### Frontend: `ui/src/components/IntentSurface.tsx`

Modify the self-mod proposal display to show two buttons instead of one:

**Where the current "Build Agent" button is rendered** (inside the `msg.selfModProposal` block), add a second button and a vibe design flow:

1. Add state:
```typescript
const [vibeMode, setVibeMode] = useState(false);
const [vibeInput, setVibeInput] = useState('');
const [enrichedSpec, setEnrichedSpec] = useState<string | null>(null);
const [enriching, setEnriching] = useState(false);
```

2. Replace the single "Build Agent" button with two:
```tsx
{/* Auto mode */}
<button onClick={() => approveSelfMod(msg.selfModProposal!)} style={...}>
  ✨ Build Agent
</button>

{/* Vibe mode */}
<button onClick={() => setVibeMode(true)} style={...}>
  🎨 Design Agent
</button>
```

3. When `vibeMode` is true, show a design form below the buttons:
```tsx
{vibeMode && !enrichedSpec && (
  <div style={{ marginTop: 12, width: '100%' }}>
    <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>
      Describe how this agent should work:
    </div>
    <textarea
      value={vibeInput}
      onChange={(e) => setVibeInput(e.target.value)}
      placeholder="e.g., Search DuckDuckGo for the person's name, parse the top results, find LinkedIn profile links..."
      style={{
        width: '100%', minHeight: 60, padding: 8,
        background: 'rgba(10, 10, 18, 0.6)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 8, color: '#c8d0e0', fontSize: 13,
        fontFamily: "'Inter', sans-serif", resize: 'vertical',
      }}
    />
    <button
      onClick={async () => {
        setEnriching(true);
        try {
          const res = await fetch('/api/selfmod/enrich', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              intent_name: msg.selfModProposal!.intent_name,
              intent_description: msg.selfModProposal!.intent_description,
              parameters: msg.selfModProposal!.parameters,
              user_guidance: vibeInput,
            }),
          });
          const data = await res.json();
          setEnrichedSpec(data.enriched);
        } catch {
          setEnrichedSpec(vibeInput); // Fallback to raw input
        } finally {
          setEnriching(false);
        }
      }}
      disabled={!vibeInput.trim() || enriching}
      style={{ marginTop: 8, ...greenButtonStyle }}
    >
      {enriching ? '🔄 Enriching...' : '✨ Enrich Spec'}
    </button>
  </div>
)}
```

4. When `enrichedSpec` is set, show the enriched spec with approve button:
```tsx
{enrichedSpec && (
  <div style={{ marginTop: 12, width: '100%' }}>
    <div style={{ fontSize: 12, color: '#f0b060', marginBottom: 6 }}>
      📋 Enriched Agent Spec:
    </div>
    <div style={{
      padding: 12, borderRadius: 8,
      background: 'rgba(240, 176, 96, 0.06)',
      border: '1px solid rgba(240, 176, 96, 0.15)',
      fontSize: 13, lineHeight: 1.6, color: '#c8d0e0',
      whiteSpace: 'pre-wrap',
    }}>
      {enrichedSpec}
    </div>
    <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
      <button
        onClick={() => {
          // Build with enriched description
          approveSelfMod({
            ...msg.selfModProposal!,
            intent_description: enrichedSpec,
          });
          setVibeMode(false);
          setEnrichedSpec(null);
          setVibeInput('');
        }}
        style={greenButtonStyle}
      >
        🚀 Build This Agent
      </button>
      <button
        onClick={() => { setEnrichedSpec(null); }}
        style={grayButtonStyle}
      >
        ✏️ Edit
      </button>
      <button
        onClick={() => {
          setVibeMode(false);
          setEnrichedSpec(null);
          setVibeInput('');
        }}
        style={grayButtonStyle}
      >
        Cancel
      </button>
    </div>
  </div>
)}
```

5. When user clicks "Edit", clear `enrichedSpec` so they go back to the textarea with their original input still there.

### Frontend: `ui/src/store/types.ts`

No changes needed — `SelfModProposal` already has `intent_description: string` which gets sent to the approve endpoint.

## Tests

### File: `tests/test_distribution.py` (or `tests/test_hxi_events.py`)

Add 1-2 tests:

1. `test_enrich_endpoint_returns_enriched` — mock LLM, call `/api/selfmod/enrich`, verify response has `enriched` field with non-empty text
2. `test_enrich_endpoint_fallback_without_llm` — verify fallback returns user_guidance when LLM unavailable

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-271 section before `## Active Roadmap`:

```
### AD-271: Vibe Agent Creation — Human-Guided Agent Design

**Problem:** Self-mod agent creation was fully automated — the human only got approve/reject. No input into what gets built or how. This led to poorly designed agents when the LLM guessed the wrong implementation approach.

| AD | Decision |
|----|----------|
| AD-271 | Added "🎨 Design Agent" option alongside "✨ Build Agent" in the HXI self-mod proposal. User describes desired behavior in a text field → LLM enriches into detailed spec → user reviews → approves → same design pipeline with the enriched description. New `/api/selfmod/enrich` endpoint. No changes to the self-mod pipeline itself — the enriched text flows through as `intent_description` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added `EnrichRequest` model and `POST /api/selfmod/enrich` endpoint |
| `ui/src/components/IntentSurface.tsx` | Added "🎨 Design Agent" button, vibe input textarea, enrichment display, approve/edit/cancel flow |

NNNN/NNNN tests passing (+ 11 skipped). N new tests.
```

## Constraints

- Only touch `src/probos/api.py`, `ui/src/components/IntentSurface.tsx`, test files, and `PROGRESS.md`
- Do NOT modify `self_mod.py`, `agent_designer.py`, `runtime.py`
- Do NOT change the self-mod pipeline — the enriched description is just a better `intent_description`
- The `/api/selfmod/enrich` endpoint is a simple LLM call — no new infrastructure
- The frontend state (vibeMode, vibeInput, enrichedSpec) should be per-message, not global — use local state in the message rendering or key by message ID
- Rebuild UI after: `cd ui && npm run build`
- Run Python tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
