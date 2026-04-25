# AD-308/309: Architect API + HXI — Design Proposals from the Bridge

*"The First Officer presents the schematics; the Captain decides whether to build."*

This prompt adds the API surface and HXI approval flow for the Architect Agent (AD-306/307). The Captain can request a feature design via `/design` slash command or POST endpoint, watch progress via WebSocket, review the ArchitectProposal (summary, rationale, risks, embedded BuildSpec) in the IntentSurface, and either approve it (which forwards the BuildSpec to `/api/build/submit`) or reject it.

This mirrors the Builder API + HXI pattern (AD-304/305) exactly — fire-and-forget async, progress events via WebSocket, inline approval in IntentSurface. The key difference: approving an architect proposal **doesn't write code** — it submits the embedded BuildSpec to the Builder pipeline.

**Current AD count:** AD-307. This prompt uses AD-308+.
**Current test count:** 1815 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/api.py` lines 108-127 — BuildRequest/BuildApproveRequest models (mirror pattern for DesignRequest)
2. `src/probos/api.py` lines 185-209 — `/build` slash command handler (mirror for `/design`)
3. `src/probos/api.py` lines 577-779 — Builder API endpoints, `_run_build()`, `_execute_build()` (mirror `_run_design()` pattern)
4. `src/probos/cognitive/architect.py` — ArchitectAgent, ArchitectProposal, `_parse_proposal()` (the agent is already built — you're adding the API surface)
5. `ui/src/store/types.ts` — BuildProposal interface, ChatMessage (mirror for ArchitectProposalView)
6. `ui/src/store/useStore.ts` lines 219 — `addChatMessage` meta parameter (extend to include architect proposal)
7. `ui/src/store/useStore.ts` lines 598-652 — build_* event handlers (mirror for design_* events)
8. `ui/src/components/IntentSurface.tsx` lines 260-282 — `approveBuild`/`rejectBuild` callbacks (mirror for architect)
9. `ui/src/components/IntentSurface.tsx` lines 584-664 — BuildProposal approval UI (mirror for architect proposal)
10. `tests/test_builder_api.py` — test patterns for API endpoints

---

## What To Build

### Step 1: API Models and Endpoints (AD-308)

**File:** `src/probos/api.py` (existing file)

**1a. Add Pydantic models** near the BuildRequest/BuildApproveRequest models (around line 127):

```python
class DesignRequest(BaseModel):
    """Request to trigger the ArchitectAgent."""
    feature: str
    phase: str = ""

class DesignApproveRequest(BaseModel):
    """Request to approve an architect proposal — forwards BuildSpec to builder."""
    design_id: str
```

**1b. Add `/design` slash command** in the chat endpoint, right after the `/build` handler (after line 208). Follow the exact same pattern:

```python
            elif parts[0].lower() == "/design":
                args = parts[1] if len(parts) > 1 else ""
                # Parse "feature description" or "phase N: feature description"
                design_parts = args.split(":", 1) if args else ["", ""]
                feature = design_parts[0].strip()
                phase = ""
                if len(design_parts) > 1:
                    # Check if the first part is a phase number
                    feature = design_parts[1].strip()
                    phase = design_parts[0].strip()
                    # If it doesn't look like a phase, treat the whole thing as the feature
                    if not phase.lower().startswith("phase") and not phase.isdigit():
                        feature = args.strip()
                        phase = ""
                elif feature:
                    pass
                if not feature:
                    return {"response": "Usage: /design <feature description> or /design phase 31: <feature>", "dag": None, "results": None}
                import uuid
                design_id = uuid.uuid4().hex[:12]
                asyncio.create_task(_run_design(
                    DesignRequest(feature=feature, phase=phase),
                    design_id,
                    runtime,
                ))
                return {
                    "response": f"Design request submitted (id: {design_id}). The Architect is analyzing...",
                    "design_id": design_id,
                    "dag": None,
                    "results": None,
                }
```

**1c. Add API endpoints** after the builder endpoints (after the `_execute_build` function):

```python
    # ------------------------------------------------------------------
    # Architect Agent API (AD-308)
    # ------------------------------------------------------------------

    @app.post("/api/design/submit")
    async def submit_design(req: DesignRequest) -> dict[str, Any]:
        """Start async architectural design. Progress via WebSocket events."""
        import uuid
        design_id = uuid.uuid4().hex[:12]
        asyncio.create_task(_run_design(req, design_id, runtime))
        return {
            "status": "started",
            "design_id": design_id,
            "message": f"Design request for '{req.feature}' started...",
        }

    @app.post("/api/design/approve")
    async def approve_design(req: DesignApproveRequest) -> dict[str, Any]:
        """Approve architect proposal — forwards embedded BuildSpec to builder."""
        # The build spec was stored in the pending_designs dict during _run_design
        if req.design_id not in _pending_designs:
            return {"status": "error", "message": f"Design {req.design_id} not found or already processed"}

        proposal_data = _pending_designs.pop(req.design_id)
        build_spec = proposal_data["build_spec"]

        # Forward to builder pipeline
        import uuid
        build_id = uuid.uuid4().hex[:12]
        build_req = BuildRequest(
            title=build_spec.get("title", ""),
            description=build_spec.get("description", ""),
            target_files=build_spec.get("target_files", []),
            reference_files=build_spec.get("reference_files", []),
            test_files=build_spec.get("test_files", []),
            ad_number=build_spec.get("ad_number", 0),
            constraints=build_spec.get("constraints", []),
        )
        asyncio.create_task(_run_build(build_req, build_id, runtime))

        return {
            "status": "forwarded",
            "design_id": req.design_id,
            "build_id": build_id,
            "message": f"Proposal approved — forwarded to Builder (build_id: {build_id})",
        }
```

**1d. Add `_pending_designs` store and `_run_design` pipeline** — add `_pending_designs: dict[str, dict] = {}` near the `_ws_clients` list (around line 145). Then add the pipeline function after the builder pipeline functions:

```python
    async def _run_design(
        req: DesignRequest,
        design_id: str,
        rt: Any,
    ) -> None:
        """Background design pipeline with WebSocket progress events."""
        try:
            rt._emit_event("design_started", {
                "design_id": design_id,
                "feature": req.feature,
                "message": f"Architect analyzing: {req.feature}...",
            })

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "surveying",
                "step_label": "\u2609 Surveying codebase...",
                "current": 1,
                "total": 3,
                "message": "\u2609 Surveying codebase and roadmap...",
            })

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "designing",
                "step_label": "\u2b21 Designing specification...",
                "current": 2,
                "total": 3,
                "message": "\u2b21 Generating architectural proposal via deep LLM...",
            })

            from probos.types import IntentMessage
            intent = IntentMessage(
                intent="design_feature",
                params={
                    "feature": req.feature,
                    "phase": req.phase,
                },
            )

            results = await rt.intent_bus.broadcast(intent)

            design_result = None
            for r in results:
                if r and r.success and r.result:
                    design_result = r
                    break

            if not design_result or not design_result.result:
                error_msg = "ArchitectAgent returned no results"
                if results:
                    errors = [r.error for r in results if r and r.error]
                    if errors:
                        error_msg = "; ".join(errors)
                rt._emit_event("design_failure", {
                    "design_id": design_id,
                    "message": f"Design failed: {error_msg}",
                    "error": error_msg,
                })
                return

            rt._emit_event("design_progress", {
                "design_id": design_id,
                "step": "review",
                "step_label": "\u25ce Ready for review",
                "current": 3,
                "total": 3,
                "message": "\u25ce Proposal ready \u2014 awaiting Captain review",
            })

            result_data = design_result.result
            if isinstance(result_data, str):
                import json as _json
                try:
                    result_data = _json.loads(result_data)
                except Exception:
                    result_data = {"proposal": {}, "llm_output": result_data}

            proposal = result_data.get("proposal", {})
            llm_output = result_data.get("llm_output", "")

            # Store proposal for later approval
            _pending_designs[design_id] = {
                "proposal": proposal,
                "build_spec": proposal.get("build_spec", {}),
            }

            rt._emit_event("design_generated", {
                "design_id": design_id,
                "title": proposal.get("title", req.feature),
                "summary": proposal.get("summary", ""),
                "rationale": proposal.get("rationale", ""),
                "roadmap_ref": proposal.get("roadmap_ref", ""),
                "priority": proposal.get("priority", "medium"),
                "dependencies": proposal.get("dependencies", []),
                "risks": proposal.get("risks", []),
                "build_spec": proposal.get("build_spec", {}),
                "llm_output": llm_output,
                "message": f"Architect proposes: {proposal.get('title', req.feature)} \u2014 review and approve to forward to Builder.",
            })

        except Exception as e:
            logger.warning("Design pipeline failed: %s", e, exc_info=True)
            rt._emit_event("design_failure", {
                "design_id": design_id,
                "message": f"Design failed: {e}",
                "error": str(e),
            })
```

**Key design decisions:**
- The `_pending_designs` dict holds proposals in memory between generation and approval. This is the same transient pattern as builds — not persisted, lost on restart. Fine for now.
- Approving a design forwards the embedded BuildSpec to `_run_build()` — reusing the entire existing builder pipeline. No duplication.
- WebSocket events use `design_*` prefix (not `build_*`) so the HXI can distinguish architect events from builder events.
- The `/design` slash command supports two formats: `/design <feature>` and `/design phase 31: <feature>`.

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

### Step 2: HXI TypeScript Types (AD-309)

**File:** `ui/src/store/types.ts` (existing file)

Add `ArchitectProposalView` interface after the `BuildProposal` interface (around line 71):

```typescript
export interface ArchitectProposalView {
  design_id: string;
  title: string;
  summary: string;
  rationale: string;
  roadmap_ref: string;
  priority: 'high' | 'medium' | 'low';
  dependencies: string[];
  risks: string[];
  build_spec: {
    title: string;
    description: string;
    target_files: string[];
    reference_files: string[];
    test_files: string[];
    ad_number: number;
    constraints: string[];
  };
  llm_output: string;
  status: 'analyzing' | 'review' | 'approved' | 'rejected';
}
```

Update the `ChatMessage` interface to include `architectProposal`:

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'system';
  text: string;
  timestamp: number;
  selfModProposal?: SelfModProposal;
  buildProposal?: BuildProposal;
  architectProposal?: ArchitectProposalView;
}
```

### Step 3: Zustand Event Handlers (AD-309)

**File:** `ui/src/store/useStore.ts` (existing file)

**3a. Import `ArchitectProposalView`** in the type imports at the top (line 6):

Add `ArchitectProposalView` to the import from `./types`.

**3b. Add `designProgress` state** alongside `buildProgress` (around line 190):

```typescript
designProgress: { step: string; current: number; total: number; label: string } | null;
```

Initialize to `null` in the initial state (alongside `buildProgress: null`).

**3c. Extend `addChatMessage` meta** to include `architectProposal`. Update the type signature (line 219):

```typescript
addChatMessage: (role: 'user' | 'system', text: string, meta?: {
  selfModProposal?: SelfModProposal;
  buildProposal?: BuildProposal;
  architectProposal?: ArchitectProposalView;
}) => void;
```

Update the spread in the addChatMessage implementation (around line 313) to include:

```typescript
...(meta?.architectProposal ? { architectProposal: meta.architectProposal } : {}),
```

**3d. Add `design_*` event handlers** in the `handleEvent` switch statement, right after the `build_failure` case (before `default`):

```typescript
      case 'design_started': {
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'design_progress': {
        const step = data.step as string;
        const current = data.current as number;
        const total = data.total as number;
        const label = (data.step_label || data.message || '') as string;
        set({ designProgress: { step, current, total, label } });
        if (label) {
          get().addChatMessage('system', label);
        }
        break;
      }

      case 'design_generated': {
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        const proposal: ArchitectProposalView = {
          design_id: data.design_id as string,
          title: data.title as string,
          summary: data.summary as string,
          rationale: data.rationale as string,
          roadmap_ref: data.roadmap_ref as string,
          priority: (data.priority as string || 'medium') as 'high' | 'medium' | 'low',
          dependencies: data.dependencies as string[],
          risks: data.risks as string[],
          build_spec: data.build_spec as ArchitectProposalView['build_spec'],
          llm_output: data.llm_output as string,
          status: 'review',
        };
        get().addChatMessage('system', msg, { architectProposal: proposal });
        break;
      }

      case 'design_success': {
        soundEngine.playSelfModSpawn();
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'design_failure': {
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }
```

### Step 4: IntentSurface Architect Approval UI (AD-309)

**File:** `ui/src/components/IntentSurface.tsx` (existing file)

**4a. Import `ArchitectProposalView`** from `../store/types` (add to existing import on line 6).

**4b. Add collapsible state** — add a `designSpecExpanded` state alongside the existing `buildCodeExpanded` (wherever that's declared):

```typescript
const [designSpecExpanded, setDesignSpecExpanded] = useState<Record<string, boolean>>({});
```

**4c. Add `approveDesign` and `rejectDesign` callbacks** after the `rejectBuild` callback (around line 282):

```typescript
  /* ── approve architect proposal → forward to builder ── */
  const approveDesign = useCallback(async (proposal: ArchitectProposalView) => {
    addChatMessage('system', `Forwarding "${proposal.title}" to Builder...`);
    try {
      await fetch('/api/design/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          design_id: proposal.design_id,
        }),
      });
    } catch {
      addChatMessage('system', '(Design approval request failed)');
    }
  }, [addChatMessage]);

  /* ── reject architect proposal ── */
  const rejectDesign = useCallback(() => {
    addChatMessage('system', 'Design proposal rejected by Captain.');
  }, [addChatMessage]);
```

**4d. Add Architect Proposal inline UI** in the message rendering section, right after the build proposal UI block (after the closing `)}` of the `msg.buildProposal` block, around line 665). This is the most important UI piece:

```tsx
                    {/* Architect proposal review */}
                    {msg.architectProposal && msg.architectProposal.status === 'review' && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        {/* Proposal overview card */}
                        <div style={{
                          padding: '10px 14px',
                          borderRadius: 8,
                          background: 'rgba(80, 160, 176, 0.08)',
                          border: '1px solid rgba(80, 160, 176, 0.2)',
                          fontSize: 12,
                          color: '#c8d0e0',
                          marginBottom: 8,
                        }}>
                          <div style={{ color: '#50a0b0', marginBottom: 6, fontWeight: 600, fontSize: 13 }}>
                            {'\u2609'} {msg.architectProposal.title}
                          </div>
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Summary:</strong> {msg.architectProposal.summary}
                          </div>
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Rationale:</strong> {msg.architectProposal.rationale}
                          </div>
                          {msg.architectProposal.roadmap_ref && (
                            <div style={{ marginBottom: 4 }}>
                              <strong style={{ color: '#a0a8b8' }}>Roadmap:</strong> {msg.architectProposal.roadmap_ref}
                            </div>
                          )}
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Priority:</strong>{' '}
                            <span style={{ color: msg.architectProposal.priority === 'high' ? '#ff8866' : msg.architectProposal.priority === 'low' ? '#88aa88' : '#b0a050' }}>
                              {msg.architectProposal.priority}
                            </span>
                          </div>

                          {/* Build spec file targets */}
                          {msg.architectProposal.build_spec.target_files.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#a0a8b8' }}>Target files:</strong>
                              {msg.architectProposal.build_spec.target_files.map((f, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#80c8a0' }}>
                                  {'\u2022'} {f}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Risks */}
                          {msg.architectProposal.risks.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#cc8866' }}>Risks:</strong>
                              {msg.architectProposal.risks.map((r, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#cc9977' }}>
                                  {'\u26A0'} {r}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Dependencies */}
                          {msg.architectProposal.dependencies.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#a0a8b8' }}>Dependencies:</strong>
                              {msg.architectProposal.dependencies.map((d, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#8888a0' }}>
                                  {'\u2192'} {d}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Collapsible full spec */}
                        <button
                          onClick={() => setDesignSpecExpanded(prev => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                          style={{
                            background: 'rgba(80, 160, 176, 0.08)',
                            border: '1px solid rgba(80, 160, 176, 0.15)',
                            borderRadius: 6, padding: '4px 12px',
                            color: '#50a0b0', cursor: 'pointer', fontSize: 12,
                            fontFamily: "'Inter', sans-serif",
                            marginBottom: 8,
                          }}
                        >
                          {designSpecExpanded[msg.id] ? '\u25BC Hide Full Spec' : '\u25B6 View Full Spec'}
                        </button>
                        {designSpecExpanded[msg.id] && (
                          <pre style={{
                            padding: 12, borderRadius: 8,
                            background: 'rgba(10, 10, 18, 0.8)',
                            border: '1px solid rgba(80, 160, 176, 0.15)',
                            fontSize: 11, lineHeight: 1.4, color: '#a0a8b8',
                            maxHeight: 300, overflowY: 'auto',
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            marginBottom: 8,
                          }}>
                            {msg.architectProposal.build_spec.description || msg.architectProposal.llm_output}
                          </pre>
                        )}

                        {/* Action buttons */}
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => approveDesign(msg.architectProposal!)}
                            style={{
                              background: 'rgba(80, 160, 176, 0.1)',
                              border: '1px solid rgba(80, 160, 176, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#50d0e0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                              textShadow: '0 0 8px rgba(80, 160, 176, 0.5)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(80, 160, 176, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(80, 160, 176, 0.1)'; }}
                          >
                            {'\u2609'} Approve & Build
                          </button>
                          <button
                            onClick={rejectDesign}
                            style={{
                              background: 'rgba(128, 128, 160, 0.1)',
                              border: '1px solid rgba(128, 128, 160, 0.2)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#8888a0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.1)'; }}
                          >
                            Reject
                          </button>
                        </div>
                      </div>
                    )}
```

**Key UI decisions:**
- Teal color scheme (`#50a0b0`) matches the Science pool group tint — the Build UI uses amber, this uses teal
- The "Approve & Build" button makes the flow clear: approval forwards to Builder, not just archives the proposal
- Shows summary, rationale, roadmap ref, priority, target files, risks, and dependencies in the overview card
- "View Full Spec" collapses/expands the full description (which is the detailed spec the Builder will consume)
- Risks shown in warm orange/coral to draw attention

### Step 5: Tests (AD-308)

**File:** `tests/test_architect_api.py` (new file)

Write tests covering at least these categories:

1. **DesignRequest model** — required fields, defaults, full population
2. **DesignApproveRequest model** — required fields
3. **POST /api/design/submit** — returns design_id, status started
4. **/design slash command — valid** — `/design Add network egress policy` → response with design_id
5. **/design slash command — with phase** — `/design phase 31: Add network egress policy` → phase parsed
6. **/design slash command — empty** — `/design` with no args → usage message
7. **POST /api/design/approve — missing design_id** — returns error when design not found
8. **_run_design pipeline — success** — mock ArchitectAgent response via intent_bus.broadcast, verify design_generated event is emitted with correct fields
9. **_run_design pipeline — failure** — mock broadcast returning no results, verify design_failure event
10. **Approval flow — forwarding** — mock a pending design, call approve endpoint, verify it creates a build task

Follow the patterns from `tests/test_builder_api.py`:
- Use `httpx.AsyncClient` with `ASGITransport` for endpoint tests
- Use `unittest.mock.AsyncMock` for mocking runtime
- Use `pytest.mark.asyncio` for async tests
- Mock `asyncio.create_task` to prevent background tasks from actually running in endpoint tests

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
**Run vitest too:** `cd d:/ProbOS/ui && npx vitest run`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-308 | Architect API — POST /api/design/submit, POST /api/design/approve, /design slash command, _run_design background pipeline, design_* WebSocket events (design_started, design_progress, design_generated, design_failure). Approval forwards embedded BuildSpec to existing builder pipeline |
| AD-309 | Architect HXI — ArchitectProposalView TypeScript type, Zustand design_* event handlers, IntentSurface inline proposal review UI (teal theme) with summary/rationale/risks/dependencies card, collapsible full spec, Approve & Build / Reject buttons |

---

## Do NOT Build

- **Automated Architect → Builder triggering** — the Captain must explicitly click "Approve & Build" in the HXI. No automatic forwarding, even for high-priority proposals.
- **Proposal persistence** — `_pending_designs` is in-memory dict, lost on restart. Durable storage comes later with the full self-improvement pipeline (Phase 30).
- **Proposal revision/iteration** — if the Captain rejects, there's no "revise and resubmit" flow yet. The Captain can just `/design` again with refined guidance.
- **Multiple proposals per request** — the Architect returns one proposal per design request. Multi-proposal comparison is future work.
- **designProgress HXI indicator** — the progress state is tracked in Zustand but does NOT need a visual progress bar in the UI for this prompt. The chat messages already show step-by-step progress. A visual indicator is future polish.

---

## Constraints

- Do NOT add new dependencies to `pyproject.toml` — use only existing imports
- Do NOT modify `src/probos/cognitive/architect.py` — it's already built, you're just connecting it via the API
- Do NOT modify `src/probos/cognitive/builder.py` — reuse the existing BuildRequest model and _run_build pipeline
- Do NOT modify `src/probos/runtime.py` — the ArchitectAgent is already registered
- Follow existing code style: match the BuildRequest/BuildApproveRequest patterns exactly
- Keep the IntentSurface architect UI structurally parallel to the build UI — same patterns, teal instead of amber
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Run vitest: `cd d:/ProbOS/ui && npx vitest run`

---

## Update PROGRESS.md When Done

Add to the current era progress file:

```
## Phase 32d: Architect API + HXI (AD-308--309)

| AD | Decision |
|----|----------|
| AD-308 | Architect API — POST /api/design/submit, POST /api/design/approve, /design slash command, _run_design pipeline, design_* WebSocket events. Approval forwards BuildSpec to builder pipeline |
| AD-309 | Architect HXI — ArchitectProposalView type, Zustand design_* handlers, IntentSurface proposal review UI (teal) with summary/rationale/risks/dependencies card, Approve & Build / Reject buttons |

**Status:** Complete — N new tests (NNNN Python total)
```

Update the status line test count in `PROGRESS.md` line 3.
