# AD-513: Ship's Crew Manifest — Queryable Roster + Cognitive Grounding

**Type:** Feature (cognitive grounding + API + HXI)
**Priority:** High
**Prerequisites:** AD-429 (Ontology), AD-567g (Orientation)

## Problem

ProbOS has all the pieces of a crew manifest scattered across six subsystems — ontology (department, post, watches), trust network (trust scores), callsign registry (names), watch manager (watch assignments), earned agency (rank/tier), ACM (lifecycle state) — but no unified query surface. Consequences:

1. **Agents confabulate crew members.** Scout agent observed referencing "Rahda" and "Brahms" — seed personality names from Star Trek, not real crew. The LLM's parametric knowledge bleeds into agent cognition because agents have no authoritative "who is actually aboard" reference.

2. **Crew roster only exists in DM system prompts.** `_compose_dm_instructions()` (cognitive_agent.py line 1015) builds a department-grouped roster from `callsign_registry.all_callsigns()`, but this is injected ONLY during DM conversations. Proactive think cycles and Ward Room responses have **no crew roster context** — agents operating in those modes have zero grounding about who exists.

3. **No HXI crew directory.** The human Captain has no crew roster UI. The 3D canvas shows agent nodes but there's no list view, no searchable directory. `/api/ontology/organization` exists on the backend but has zero frontend consumers.

4. **No programmatic query surface.** Shepard (Security) requested a crew manifest with trust levels for security posture assessment — impossible today. No agent can ask "who is on this ship?" and get a structured answer.

## Solution

Three-layer delivery:

1. **Backend:** `VesselOntologyService.get_crew_manifest()` — assembles live roster from existing subsystems at query time. REST API endpoint. No new data store.

2. **Cognitive grounding:** Inject a compact "Ship's Complement" block into `_build_temporal_context()` — flows into ALL three prompt paths (DM, proactive, Ward Room). Prevents confabulation by grounding agents in the actual crew roster.

3. **HXI:** Crew Roster panel — left sidebar tab or floating panel showing department-grouped crew with status, rank, trust, click-to-profile.

## What This AD Delivers

1. `VesselOntologyService.get_crew_manifest()` method
2. `GET /api/ontology/crew-manifest` REST endpoint (with department/watch filters)
3. Crew manifest rendered as cognitive grounding block in `_build_temporal_context()`
4. `crew manifest` shell command
5. HXI `CrewRosterPanel` component
6. Anti-confabulation guardrail — agents know exactly who exists

## Files Modified

| File | Change |
|------|--------|
| `src/probos/ontology/service.py` | Add `get_crew_manifest()` method |
| `src/probos/routers/ontology.py` | Add `GET /api/ontology/crew-manifest` endpoint |
| `src/probos/cognitive/cognitive_agent.py` | Add `_build_crew_complement()` and inject into `_build_temporal_context()` |
| `src/probos/cognitive/orientation.py` | Add `crew_complement` field to `OrientationContext` |
| `src/probos/startup/finalize.py` | Wire crew complement rendering at boot + on onboarding |
| `ui/src/components/CrewRosterPanel.tsx` | New: crew roster panel component |
| `ui/src/store/useStore.ts` | Add `crewRosterOpen` state + `crewManifest` data |
| `ui/src/store/types.ts` | Add `CrewManifestEntry` interface |
| `ui/src/App.tsx` | Mount `CrewRosterPanel` |
| `tests/test_ontology.py` | Add `TestCrewManifest` tests |
| `tests/test_cognitive_crew_grounding.py` | New: test crew complement injection |

## Files NOT Modified / Created

- No new backend packages or dependencies
- No changes to `_compose_dm_instructions()` — the manifest grounding is a separate, universal block. The DM instruction block is about HOW to DM; the manifest is about WHO exists.
- No changes to Ward Room, trust network, proactive.py

## Design Details

### 1. `get_crew_manifest()` — `ontology/service.py`

Add this method to `VesselOntologyService` after `get_crew_context()` (line 389):

```python
def get_crew_manifest(
    self,
    *,
    department: str | None = None,
    trust_network: Any | None = None,
    callsign_registry: Any | None = None,
) -> list[dict[str, Any]]:
    """Assemble live crew roster from ship subsystems.

    Returns one entry per crew agent with fields:
      agent_type, callsign, department, post, rank, trust_score,
      agent_id, is_alive, lifecycle_state.

    Enrichment sources are optional — omit for a minimal roster.
    """
    from probos.crew_profile import Rank

    crew_types = self.get_crew_agent_types()
    manifest: list[dict[str, Any]] = []

    for agent_type in sorted(crew_types):
        assignment = self.get_assignment_for_agent(agent_type)
        if not assignment:
            continue

        post = self.get_post(assignment.post_id)
        dept_id = self.get_agent_department(agent_type) or ""

        # Base entry from ontology
        entry: dict[str, Any] = {
            "agent_type": agent_type,
            "callsign": assignment.callsign,
            "department": dept_id,
            "post": post.title if post else "",
            "agent_id": assignment.agent_id or "",
        }

        # Enrich with callsign registry (live callsign may differ from ontology)
        if callsign_registry:
            live_cs = callsign_registry.get_callsign(agent_type)
            if live_cs:
                entry["callsign"] = live_cs

        # Enrich with trust score + rank
        if trust_network and assignment.agent_id:
            try:
                trust_score = trust_network.get_trust(assignment.agent_id)
                entry["trust_score"] = round(trust_score, 3)
                entry["rank"] = Rank.from_trust(trust_score).value
            except Exception:
                entry["trust_score"] = 0.5
                entry["rank"] = Rank.ENSIGN.value
        else:
            entry["trust_score"] = 0.5
            entry["rank"] = Rank.ENSIGN.value

        manifest.append(entry)

    # Filter by department if requested
    if department:
        manifest = [e for e in manifest if e["department"] == department]

    return manifest
```

**Pattern notes:**
- Follows the existing facade pattern — `VesselOntologyService` delegates to internal services.
- `trust_network` and `callsign_registry` are passed in (dependency inversion), not reached through runtime.
- `Rank.from_trust()` is a `@classmethod` on `Rank` enum in `probos.crew_profile` (uses `TRUST_SENIOR=0.85`, `TRUST_COMMANDER=0.7`, `TRUST_LIEUTENANT=0.5` from `probos.config`).
- No async needed — all data sources are synchronous (ontology is in-memory, trust `get_trust()` is sync).
- `get_crew_agent_types()` returns `set[str]` — sorted for deterministic output.
- `get_assignment_for_agent()` returns `Assignment | None` from `probos.ontology.models`.

### 2. REST API — `routers/ontology.py`

Add after the existing `/crew/{agent_type}` route (~line 60):

```python
@router.get("/crew-manifest")
async def get_crew_manifest(
    runtime: Any = Depends(get_runtime),
    department: str | None = None,
) -> dict:
    """AD-513: Ship's Crew Manifest — unified crew roster."""
    ont = runtime.ontology
    if not ont:
        raise HTTPException(503, "Ontology not initialized")

    manifest = ont.get_crew_manifest(
        department=department,
        trust_network=getattr(runtime, 'trust_network', None),
        callsign_registry=getattr(runtime, 'callsign_registry', None),
    )

    # Group by department for structured response
    departments: dict[str, list] = {}
    for entry in manifest:
        dept = entry.get("department", "unassigned")
        departments.setdefault(dept, []).append(entry)

    vessel = ont.get_vessel_identity()
    return {
        "vessel": {"name": vessel.name, "instance_id": vessel.instance_id},
        "crew_count": len(manifest),
        "departments": departments,
        "manifest": manifest,
    }
```

**Notes:**
- Follows the existing `Depends(get_runtime)` pattern in `routers/ontology.py`.
- No trust-gating for the REST endpoint in this AD — the endpoint serves the Captain's HXI. Agent-side trust-gated access is deferred (AD-513b).
- `getattr(runtime, ..., None)` for optional enrichment — graceful degrades to ontology-only data.

### 3. Cognitive Grounding — `cognitive_agent.py`

Add a new method `_build_crew_complement()` after `_build_temporal_context()` (line 1834):

```python
def _build_crew_complement(self) -> str:
    """AD-513: Build compact crew complement for cognitive grounding.

    Prevents confabulation by anchoring agents to the actual crew roster.
    Injected into all prompt paths via _build_temporal_context().
    """
    rt = getattr(self, '_runtime', None)
    if not rt or not getattr(rt, 'ontology', None):
        return ""

    try:
        manifest = rt.ontology.get_crew_manifest(
            callsign_registry=getattr(rt, 'callsign_registry', None),
        )
    except Exception:
        return ""

    if not manifest:
        return ""

    self_atype = getattr(self, 'agent_type', '')
    dept_groups: dict[str, list[str]] = {}
    for entry in manifest:
        if entry["agent_type"] == self_atype:
            continue
        dept = (entry.get("department") or "bridge").capitalize()
        dept_groups.setdefault(dept, []).append(entry["callsign"])

    if not dept_groups:
        return ""

    lines = ["=== SHIP'S COMPLEMENT (these are the ONLY crew aboard) ==="]
    for dept_name in sorted(dept_groups):
        members = ", ".join(sorted(dept_groups[dept_name]))
        lines.append(f"  {dept_name}: {members}")
    lines.append(
        "Do NOT reference crew members who are not listed above. "
        "If you are uncertain whether someone is aboard, verify against this roster."
    )
    return "\n".join(lines)
```

**Inject into `_build_temporal_context()`** — after the orientation block (line 1832), before the return:

```python
        # AD-567g: Cognitive re-localization orientation
        orientation = getattr(self, '_orientation_rendered', None)
        if orientation:
            parts.append(orientation)

        # AD-513: Crew complement grounding (anti-confabulation)
        crew_complement = self._build_crew_complement()
        if crew_complement:
            parts.append(crew_complement)

        return "\n".join(parts)
```

**Why this injection point:**
- `_build_temporal_context()` is called from ALL three `_build_user_message()` branches (DM at line 1880, Ward Room at line 1930, proactive at line 1986).
- Injecting here means every cognitive invocation sees the crew roster — no path can confabulate.
- Placement after orientation is correct — first the agent knows WHO IT IS (orientation), then WHO ELSE IS ABOARD (complement).
- This is a lightweight method call — `get_crew_manifest()` is in-memory data assembly, no DB queries, no async.

**Relationship to `_compose_dm_instructions()`:**
- `_compose_dm_instructions()` tells agents HOW to DM (`[DM @callsign]` format) — it stays.
- `_build_crew_complement()` tells agents WHO EXISTS — purely cognitive grounding.
- They overlap in listing crew, but serve different purposes. The DM instruction block includes formatting instructions; the complement block is a bare assertion of who is aboard.
- Acceptable overlap — not DRY-violating because they serve different cognitive functions.

### 4. `OrientationContext` — `cognitive/orientation.py`

Add `crew_complement` field after `social_verification_available` (line 51):

```python
    # AD-513: Crew roster for cognitive grounding
    crew_names: list[str] = field(default_factory=list)   # all crew callsigns aboard
```

This allows orientation rendering to include crew names for boot-time identity grounding. The `build_orientation()` method can include: "Your shipmates aboard are: {', '.join(ctx.crew_names)}" in the rendered orientation text.

### 5. Startup Wiring — `startup/finalize.py`

In the warm boot orientation block (around line 370-386), populate `crew_names` on the `OrientationContext`:

```python
# Where OrientationContext is constructed for warm boot (~line 354-382):
# Add crew_names from callsign_registry
_crew_names = []
if hasattr(runtime, 'callsign_registry'):
    for _at, _cs in runtime.callsign_registry.all_callsigns().items():
        if _cs and _at != agent.agent_type:
            _crew_names.append(_cs)

# Include in OrientationContext construction
_ctx = OrientationContext(
    callsign=_callsign,
    post=_post,
    department=_dept,
    # ... existing fields ...
    crew_names=sorted(_crew_names),
)
```

**Also** update cold-start orientation in `_handle_onboarding_orientation()` (search for where `OrientationContext(` is constructed with `lifecycle_state="first_boot"`) to include `crew_names`.

### 6. HXI: `CrewRosterPanel.tsx`

**New file:** `ui/src/components/CrewRosterPanel.tsx`

Follow the `WardRoomPanel.tsx` left-sidebar pattern but as a **floating panel** (like `AgentProfilePanel.tsx`) so it doesn't conflict with the Ward Room's left-side position.

**Dimensions:** 360×520px, fixed position, draggable title bar.

**Layout:**
- **Title bar:** "Ship's Complement" + crew count badge + close button. Draggable.
- **Filter bar:** Department filter chips (Engineering, Science, Medical, Security, Bridge) — toggle on/off.
- **Crew list:** Scrollable, department-grouped. Each entry row:
  - Department color dot (left)
  - Callsign (primary text, `#e0dcd4`)
  - Post title (secondary text, `#8888a0`, font-size 10)
  - Rank badge (ENSIGN/LT/CMDR/SR, colored)
  - Trust score bar (tiny, colored per trust bands: `>0.7 #f0b060`, `>0.35 #88a4c8`, `<0.35 #7060a8`)
  - State indicator dot (active=`#80c878`, degraded=`#f0b060`)
  - Click → `openAgentProfile(agent.id)`

**Data source:** Fetch `GET /api/ontology/crew-manifest` on panel open. Re-fetch on `state_snapshot` agent changes.

**Styling (match HXI design language):**
```typescript
{
  background: 'rgba(10, 10, 18, 0.92)',
  backdropFilter: 'blur(16px)',
  border: '1px solid rgba(240, 176, 96, 0.2)',
  borderRadius: 12,
  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
  fontFamily: "'JetBrains Mono', monospace",
  color: '#e0dcd4',
}
```

**Department colors (established convention):**
```typescript
const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};
```

**Rank labels and colors:**
```typescript
const RANK_LABELS: Record<string, string> = {
  ensign: 'ENS',
  lieutenant: 'LT',
  commander: 'CMDR',
  senior_officer: 'SR',
};
```

### 7. Store Changes — `useStore.ts` + `types.ts`

**`types.ts` — add:**

```typescript
export interface CrewManifestEntry {
  agentType: string;
  callsign: string;
  department: string;
  post: string;
  rank: string;
  trustScore: number;
  agentId: string;
}
```

**`useStore.ts` — add state:**

```typescript
crewRosterOpen: boolean;
crewManifest: CrewManifestEntry[] | null;
```

**Actions:**

```typescript
toggleCrewRoster: () => void;
fetchCrewManifest: () => Promise<void>;
```

`fetchCrewManifest` calls `GET /api/ontology/crew-manifest`, maps snake_case response to camelCase `CrewManifestEntry[]`, sets `crewManifest`.

### 8. `App.tsx` — Mount

Import and render `<CrewRosterPanel />` alongside other floating panels:

```tsx
<CrewRosterPanel />
```

**Toggle button:** Add a "CREW" button in the glass toolbar area (near `WardRoomToggle`). Style: amber ghost button, uppercase, `fontSize: 10`, `letterSpacing: 1.5`.

### 9. Shell Command — Deferred to AD-513b

The shell command `crew manifest` requires changes to `shell.py` or the experience command framework. This is orthogonal to the cognitive grounding fix and the HXI panel. Defer to keep this AD focused.

### 10. Agent Tool Access — Deferred to AD-513b

Trust-gated agent access (Security Chief sees trust scores, regular crew see callsigns only) requires the Earned Agency trust-tier check in the API. Defer to keep this AD focused.

## Engineering Principles Compliance

- **DRY:** `get_crew_manifest()` is the SINGLE source of truth. `_build_crew_complement()` calls it. HXI calls the REST endpoint that calls it. No duplicate assembly logic.
- **SOLID (S — Single Responsibility):** `VesselOntologyService` already owns crew queries. The manifest is a composition of existing queries — not a new responsibility. The REST route is a thin wrapper. The cognitive grounding is a separate concern in `cognitive_agent.py`.
- **SOLID (D — Dependency Inversion):** `get_crew_manifest()` receives `trust_network` and `callsign_registry` as parameters, not by reaching into runtime. Constructor injection for optional enrichment.
- **SOLID (O — Open/Closed):** Adding `get_crew_manifest()` extends `VesselOntologyService` without modifying existing methods. Adding content to `_build_temporal_context()` extends temporal context without modifying existing blocks.
- **Law of Demeter:** No reaching through private attributes. Uses `ont.get_crew_agent_types()`, `ont.get_assignment_for_agent()`, `callsign_registry.get_callsign()` — all public APIs. NOTE: Fix the existing LoD violation in `routers/ontology.py` line 39 (`ont._assignments.values()`) while we're editing the file — replace with proper API calls.
- **Fail Fast:** `_build_crew_complement()` catches exceptions and returns empty string — appropriate for a non-critical cognitive supplement. Agent functions fine without it, just with less grounding.
- **Defense in Depth:** Two anti-confabulation layers: (1) crew complement in temporal context (universal), (2) DM instructions still enforce "ONLY DM crew listed above" (DM-specific). Belt and suspenders.
- **Cloud-Ready Storage:** No new storage. `get_crew_manifest()` assembles from in-memory subsystem data at query time.

## Verification

1. Run ontology tests: `pytest tests/test_ontology.py -v`
2. Run cognitive grounding tests: `pytest tests/test_cognitive_crew_grounding.py -v`
3. Run full test suite: `pytest --tb=short`
4. HXI build: `cd ui && npm run build` — TypeScript compiles clean
5. **Manual:** Start ProbOS → open HXI → verify "CREW" button → click → crew roster panel shows all agents grouped by department → click agent → profile opens
6. **Anti-confabulation:** Start ProbOS → wait for proactive cycle → verify crew complement appears in agent prompts (check logs for "SHIP'S COMPLEMENT")
7. **REST API:** `curl http://localhost:8000/api/ontology/crew-manifest` → returns structured manifest
8. **Filtered:** `curl http://localhost:8000/api/ontology/crew-manifest?department=engineering` → returns only engineering crew

## Deferred

- **AD-513b: Shell command + agent tool access** — `crew manifest` command, trust-gated agent queries
- **AD-513c: Federation ship manifest** — `get_ship_manifest()` for inter-ship gossip (AD-479)
- **AD-513d: Live refresh** — WebSocket push on crew change (onboarding, recycling) instead of poll
- **Fix `orientation_supplement` dead context** — `proactive.py._gather_context()` gathers `context["orientation_supplement"]` but `_build_user_message()` never consumes it. Separate BF.

## Test Plan

### `tests/test_ontology.py` — `TestCrewManifest`

```python
class TestCrewManifest:
    """AD-513: Crew manifest assembly from subsystems."""

    def test_manifest_returns_all_crew(self):
        """get_crew_manifest() returns one entry per crew-tier agent."""

    def test_manifest_entry_fields(self):
        """Each entry has agent_type, callsign, department, post, rank."""

    def test_manifest_enriched_with_trust(self):
        """trust_network enrichment adds trust_score and rank."""

    def test_manifest_enriched_with_live_callsign(self):
        """callsign_registry enrichment uses live callsign over ontology."""

    def test_manifest_department_filter(self):
        """department parameter filters results."""

    def test_manifest_without_enrichment(self):
        """Returns minimal roster when trust/callsign not provided."""

    def test_manifest_sorted_deterministic(self):
        """Manifest entries are sorted by agent_type for determinism."""
```

### `tests/test_cognitive_crew_grounding.py` — `TestCrewComplement`

```python
class TestCrewComplement:
    """AD-513: Crew complement cognitive grounding."""

    def test_complement_included_in_temporal_context(self):
        """_build_temporal_context() includes SHIP'S COMPLEMENT block."""

    def test_complement_excludes_self(self):
        """Agent's own callsign is excluded from the complement."""

    def test_complement_department_grouped(self):
        """Crew are grouped by department in the complement block."""

    def test_complement_includes_anti_confab_instruction(self):
        """Block ends with 'Do NOT reference crew members not listed above.'"""

    def test_complement_graceful_without_ontology(self):
        """Returns empty string if ontology not available."""

    def test_complement_in_proactive_prompt(self):
        """Proactive _build_user_message includes crew complement."""

    def test_complement_in_dm_prompt(self):
        """DM _build_user_message includes crew complement."""

    def test_complement_in_ward_room_prompt(self):
        """Ward Room _build_user_message includes crew complement."""
```

## Test Impact

- **Added:** ~15 tests (7 ontology + 8 cognitive grounding)
- **Removed:** 0
- **Net:** +15
