# AD-902 — Per-agent developmental (T3) skill management surface

**One-line:** Add a Captain-facing surface to acquire, re-level, and suspend an agent's developmental (T3) skill records — the write path the Service Record's read-only "Skills & Proficiency" section has been missing.

**Status:** Ready for build
**Dependencies:** AD-428 (`AgentSkillService`), AD-892 (`routers/crew.py`), AD-897 (`ServiceRecord.tsx`), AD-901 (`StandingOrders.tsx` precedent), BF-610 (skill-count fix — do not re-touch)
**Estimated tests:** ~14 new (≈8 backend real-fixture + ≈6 Vitest UI)
**Current highest AD:** AD-901 → this is **AD-902**.

---

## Problem

The Crew Personnel Console (AD-896) gave every governed personnel facet a write surface **except developmental skills**:

| Facet | Read | Write verb | AD |
|---|---|---|---|
| Standing orders / directives | ✅ | ✅ issue / approve / revoke | AD-900/901 |
| Tool certifications | ✅ | ✅ grant / revoke | AD-894/899 |
| Skill **catalog** (definitions) | ✅ | ✅ create / retire | AD-895/898 |
| Developmental (T3) **per-agent** skills | ✅ count only | ❌ **none** | — |

The Service Record's `sr-section-skills` block ([ServiceRecord.tsx](ui/src/components/personnel/ServiceRecord.tsx#L246-L273)) renders a developmental-skill **count** plus the read-only cognitive (T2) list. There is no way for the Captain to give an agent a skill, correct a proficiency level after an assessment, or pull a skill an agent's model can no longer support.

Backend gap (the central design decision in this spec): `AgentSkillService` exposes `acquire_skill` and `update_proficiency`, but **no removal/suspend verb exists** — confirmed by grep. However the data model already carries a soft-removal flag: `AgentSkillRecord.suspended: bool` ([skill_framework.py](src/probos/skill_framework.py#L592)) and the `agent_skills.suspended` column ([skill_framework.py](src/probos/skill_framework.py#L939)), already honored by `check_decay` (`WHERE ... suspended = 0`, [skill_framework.py](src/probos/skill_framework.py#L1409)) and `SkillProfile.proficiency_of` ([skill_framework.py](src/probos/skill_framework.py#L646-L648)). **The schema models suspension; no method writes it.** This AD wires that already-modeled capability rather than introducing a hard `DELETE`.

There is prior art for proficiency updates at `POST /api/skills/agents/{id}/assess` ([skills.py](src/probos/routers/skills.py#L61-L77)). AD-902 does **not** duplicate its logic — the new crew-prefixed PATCH calls the **same** `skill_service.update_proficiency`. The new surface is REST-co-located with the rest of the console's `/api/crew/{agent_id}/…` endpoints (roster, record, tools, directives) so the front end fetches one prefix.

---

## Solution

Three pieces, each independently buildable:

1. **Backend verb (additive):** add `suspend_skill(agent_id, skill_id, suspended=True)` to `AgentSkillService` — a soft, fully reversible toggle over the existing `suspended` column, using the existing `_get_record` / `_upsert_record` helpers. Returns `None` when no record exists (→ 404 at the HTTP layer). No new `EventType` (deliberate non-goal — see §"What this does NOT change").
2. **Backend endpoints (new):** four `/api/crew/{agent_id}/skills…` routes on the existing `crew` router — list / acquire / re-level-or-toggle / suspend — following the AD-894/900 dict-body + `503/404/400` shape exactly.
3. **Frontend (new component, composed):** `SkillManagement.tsx` rendered **inside** `ServiceRecord`'s `sr-section-skills` block, mirroring how AD-901's `StandingOrders` is composed inside `sr-section-orders` ([ServiceRecord.tsx](ui/src/components/personnel/ServiceRecord.tsx#L346-L349)). Acquire (skill picker from the registry), proficiency stepper, suspend/reinstate with two-step confirm. Stroke-only chrome, amber accents, no emoji, honest-degrade.

**Governance posture:** every operation is reversible — `acquire_skill` is an idempotent `INSERT OR REPLACE` upsert, `update_proficiency` can move levels in either direction, `suspend` is a soft boolean toggle that preserves `assessment_history`. Per **Minimal Authority** these are Captain-authorized audited edits → **no new consensus gate**. Per **Safety Budget**, the two destructive-feeling paths (down-leveling and suspend) get a UI two-step confirm. No hard delete, so **Reversibility Preference** holds.

---

## Section 1 — `AgentSkillService.suspend_skill` (backend verb)

Add the method to `AgentSkillService`, placed immediately after `count_agents_with_skill` ([skill_framework.py](src/probos/skill_framework.py#L1480-L1494), the `# AD-428b v1: Development goals` divider follows it).

```python
# --- in src/probos/skill_framework.py, inside class AgentSkillService ---
```

SEARCH (anchor on the end of `count_agents_with_skill` + the divider that follows):

```python
        async with self._db.execute(
            "SELECT COUNT(*) FROM agent_skills WHERE skill_id = ?", (skill_id,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # AD-428b v1: Development goals
    # ------------------------------------------------------------------
```

REPLACE:

```python
        async with self._db.execute(
            "SELECT COUNT(*) FROM agent_skills WHERE skill_id = ?", (skill_id,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def suspend_skill(
        self, agent_id: str, skill_id: str, suspended: bool = True,
    ) -> AgentSkillRecord | None:
        """AD-902: soft-suspend (or reinstate) an agent's skill record.

        A reversible toggle over the already-modeled ``suspended`` column. A
        suspended skill is excluded from decay sweeps and from
        ``SkillProfile.proficiency_of``/``breadth`` (see the ``not s.suspended``
        guards) but its proficiency and ``assessment_history`` are preserved, so
        reinstating with ``suspended=False`` restores the prior standing. There
        is no hard delete — Reversibility Preference holds.

        Returns the updated record, or ``None`` when the agent holds no record
        for ``skill_id`` (the caller maps this to 404).
        """
        record = await self._get_record(agent_id, skill_id)
        if not record:
            return None
        record.suspended = bool(suspended)
        await self._upsert_record(record)
        return record

    # ------------------------------------------------------------------
    # AD-428b v1: Development goals
    # ------------------------------------------------------------------
```

> No telemetry emission in v1 (no `SKILL_SUSPENDED` `EventType`). This keeps the AD a single additive method with zero `events.py` migration. If suspension telemetry is wanted later it is a separate AD.

---

## Section 2 — `/api/crew/{agent_id}/skills…` endpoints

Append to [routers/crew.py](src/probos/routers/crew.py) after the last route. Follow the existing dict-body convention (AD-894/900 use `body: dict[str, Any]`, **not** Pydantic request models — do not add `api_models`). Accessor is `getattr(runtime, "skill_service", None)` ([crew.py](src/probos/routers/crew.py#L80)); registry is `getattr(runtime, "skill_registry", None)`.

Add a serializer + four routes:

```python
# ----------------------------------------------------------------------
# Developmental (T3) skill management (AD-902) — a Captain-facing write
# surface over AgentSkillService (AD-428). Co-located on /api/crew so the
# console fetches one prefix. update_proficiency here is the SAME method the
# /api/skills/.../assess endpoint (AD-428) calls — no logic is duplicated.
# All mutations are reversible (idempotent upsert / two-way level moves /
# soft suspend), so no consensus gate (Minimal Authority).
# ----------------------------------------------------------------------


def _serialize_skill_record(record: Any, defn: Any) -> dict[str, Any]:
    """Project an AgentSkillRecord (+ its definition) to the console shape."""
    data = record.to_dict()
    data["name"] = defn.name if defn is not None else record.skill_id
    data["category"] = defn.category.value if defn is not None else "acquired"
    return data


@router.get("/{agent_id}/skills")
async def crew_developmental_skills(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """The agent's developmental (T3) skill records (AD-902).

    Every record — including ``suspended`` ones, so the console can offer
    reinstatement — joined with its registry definition for name + category.
    Honest-degrades to an empty list when the skill service is unavailable.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        return {"agent_id": agent_id, "skills": [], "count": 0}
    registry = getattr(runtime, "skill_registry", None)
    records = await skill_service.get_all_records(agent_id)
    skills = [
        _serialize_skill_record(
            r, registry.get_skill(r.skill_id) if registry is not None else None,
        )
        for r in records
    ]
    return {"agent_id": agent_id, "skills": skills, "count": len(skills)}


@router.post("/{agent_id}/skills")
async def crew_acquire_skill(
    agent_id: str, body: dict[str, Any], runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Give a crew agent a developmental skill (AD-902).

    Body: ``{skill_id, proficiency?, source?}``. ``proficiency`` is the 1-7
    level integer (defaults to FOLLOW=1). Unmet prerequisites raise a 400 with
    the service's explanatory message.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    skill_id = body.get("skill_id")
    if not skill_id:
        raise HTTPException(400, "skill_id is required")
    registry = getattr(runtime, "skill_registry", None)
    if registry is not None and registry.get_skill(skill_id) is None:
        raise HTTPException(404, f"Skill not found: {skill_id}")
    from probos.skill_framework import ProficiencyLevel
    level = ProficiencyLevel.FOLLOW
    if "proficiency" in body and body["proficiency"] is not None:
        try:
            level = ProficiencyLevel(int(body["proficiency"]))
        except (ValueError, TypeError):
            raise HTTPException(400, f"Invalid proficiency: {body.get('proficiency')}") from None
    try:
        record = await skill_service.acquire_skill(
            agent_id, skill_id, source=body.get("source", "captain"), proficiency=level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    defn = registry.get_skill(skill_id) if registry is not None else None
    return _serialize_skill_record(record, defn)


@router.patch("/{agent_id}/skills/{skill_id}")
async def crew_update_skill(
    agent_id: str, skill_id: str, body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Re-level and/or suspend-toggle an agent's skill (AD-902).

    Body may carry ``proficiency`` (1-7 int → ``update_proficiency``) and/or
    ``suspended`` (bool → ``suspend_skill``). Reinstatement is ``{suspended:
    false}``. 404 when the agent holds no record for ``skill_id``.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    if "proficiency" not in body and "suspended" not in body:
        raise HTTPException(400, "proficiency or suspended is required")
    from probos.skill_framework import ProficiencyLevel
    record = None
    if "proficiency" in body and body["proficiency"] is not None:
        try:
            level = ProficiencyLevel(int(body["proficiency"]))
        except (ValueError, TypeError):
            raise HTTPException(400, f"Invalid proficiency: {body.get('proficiency')}") from None
        record = await skill_service.update_proficiency(
            agent_id, skill_id, level, source="captain",
            notes=body.get("notes", ""),
        )
        if record is None:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    if "suspended" in body and body["suspended"] is not None:
        record = await skill_service.suspend_skill(
            agent_id, skill_id, suspended=bool(body["suspended"]),
        )
        if record is None:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    registry = getattr(runtime, "skill_registry", None)
    defn = registry.get_skill(skill_id) if registry is not None else None
    return _serialize_skill_record(record, defn)


@router.delete("/{agent_id}/skills/{skill_id}")
async def crew_suspend_skill(
    agent_id: str, skill_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Suspend a skill (AD-902). Soft, reversible — reinstate via PATCH."""
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    record = await skill_service.suspend_skill(agent_id, skill_id, suspended=True)
    if record is None:
        raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    return {"suspended": True, "agent_id": agent_id, "skill_id": skill_id}
```

> **Verify the registry method name during build.** This spec uses `registry.get_skill(skill_id)` — the same call `acquire_skill` makes internally ([skill_framework.py](src/probos/skill_framework.py#L1279)). The `skills.py` registry-list route uses `runtime.skill_registry.list_skills(...)`. Builder: confirm `get_skill` exists on the `SkillRegistry` instance before wiring (grep `def get_skill` in `skill_framework.py`); it is exercised by `acquire_skill`, so it is real, but verify the exact name.

**No `api.py` change** — the `crew` router is already registered (`crew as crew_router  # AD-892`, [api.py](src/probos/api.py#L222)). New routes ride the existing registration.

---

## Section 3 — `SkillManagement.tsx` (frontend, composed in Service Record)

Create `ui/src/components/personnel/SkillManagement.tsx`, modeled on [StandingOrders.tsx](ui/src/components/personnel/StandingOrders.tsx) (the AD-901 precedent: per-agent, composed inside a Service Record section, write verbs with honest-degrade + two-step confirm + `chipStyle` stroke buttons + no emoji).

Required behavior:

- **Props:** `{ agentId: string }`.
- **Load:** on mount/`agentId` change, `fetch('/api/crew/${agentId}/skills')`; honest-degrade to `[]` on `!resp.ok` or throw (mirror `StandingOrders.refresh`). Also load the acquirable catalog from `fetch('/api/skills/registry')` for the acquire picker; honest-degrade to `[]`.
- **List:** each developmental record shows name, category, proficiency label (map 1-7 → FOLLOW…SHAPE — reuse `record.proficiency_label` from `to_dict()`), and a dim "(suspended)" marker when `suspended`. `data-testid={`skill-row-${skill_id}`}`.
- **Acquire:** a `<select>` of registry skills the agent doesn't already hold + an "Acquire" button → `POST /api/crew/${agentId}/skills` `{skill_id, proficiency:1}`. On `!ok`, parse `body.detail` into an inline error (mirror `StandingOrders.issueOrder`'s 400-detail parse) so an unmet-prerequisite 400 is shown verbatim.
- **Re-level:** up/down stepper per row → `PATCH /api/crew/${agentId}/skills/${skill_id}` `{proficiency}`. Down-leveling requires a two-step confirm (`confirmDownId` state, mirror `confirmRevokeId`).
- **Suspend / reinstate:** a `DELETE /api/crew/${agentId}/skills/${skill_id}` with two-step confirm for suspend; a `PATCH … {suspended:false}` to reinstate. After any mutation, re-`refresh()`.
- **HXI:** stroke-only `chipStyle` buttons, amber `#f0b060` active, no emoji, calm empty state ("No developmental skills.").

Compose it inside the existing skills section. SEARCH in [ServiceRecord.tsx](ui/src/components/personnel/ServiceRecord.tsx#L246-L273) (the `sr-section-skills` block — append after the cognitive-skills render, before the closing `</div>`):

SEARCH:

```tsx
        {cognitiveSkills.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680', padding: '4px 0' }}>No cognitive skills.</div>
        ) : (
          cognitiveSkills.map(s => (
            <div key={s.skill_id} style={{ fontSize: 11, padding: '3px 0' }}>
              <span style={{ color: '#c8c8d4' }}>{s.name}</span>
              <span style={{ color: '#666680' }}> — {s.description}</span>
            </div>
          ))
        )}
      </div>
```

REPLACE:

```tsx
        {cognitiveSkills.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680', padding: '4px 0' }}>No cognitive skills.</div>
        ) : (
          cognitiveSkills.map(s => (
            <div key={s.skill_id} style={{ fontSize: 11, padding: '3px 0' }}>
              <span style={{ color: '#c8c8d4' }}>{s.name}</span>
              <span style={{ color: '#666680' }}> — {s.description}</span>
            </div>
          ))
        )}
        <div style={{ marginTop: 12 }}>
          <SkillManagement agentId={agentId} />
        </div>
      </div>
```

Add the import next to the existing `StandingOrders` import ([ServiceRecord.tsx](ui/src/components/personnel/ServiceRecord.tsx#L24)):

SEARCH:

```tsx
import StandingOrders from './StandingOrders';
```

REPLACE:

```tsx
import StandingOrders from './StandingOrders';
import SkillManagement from './SkillManagement';
```

> BF-610 left the developmental-skill **count** + avg-proficiency labels in this section. Do **not** remove or re-derive them — `SkillManagement` is additive below them.

---

## Tests

### Backend — `tests/test_ad902_skill_management.py` (real fixtures, BF-287)

Use a **real** `AgentSkillService` on a temp SQLite db + a real `SkillRegistry` (no MagicMock at the substrate boundary — BF-287). Mirror the fixture style of the existing skill-framework tests. Drive HTTP via FastAPI `TestClient` with a runtime stub that exposes the real `skill_service` and `skill_registry` as attributes (real services, stub container).

1. `suspend_skill` toggles the column and is reversible; `assessment_history` + proficiency preserved across suspend→reinstate.
2. `suspend_skill` returns `None` for an unheld skill.
3. `GET /api/crew/{id}/skills` lists held records with `name` + `category`; includes suspended records.
4. `GET …/skills` honest-degrades to `{"skills": [], "count": 0}` when `skill_service` is `None` (stub it absent).
5. `POST …/skills` acquires (happy path) → record at requested level.
6. `POST …/skills` → 404 for unknown `skill_id`; 400 for missing `skill_id`; 400 (with the service message) on unmet prerequisite.
7. `PATCH …/skills/{sid}` re-levels (happy) and 404s for an unheld skill; `{suspended:true}` suspends; `{suspended:false}` reinstates; 400 when neither field present.
8. `DELETE …/skills/{sid}` suspends (returns `suspended:true`) and 404s for an unheld skill; a follow-up `GET` shows the record still present but `suspended:true`.

### Frontend — `ui/src/components/personnel/SkillManagement.test.tsx` (Vitest)

Mirror [StandingOrders.test.tsx](ui/src/components/personnel/StandingOrders.test.tsx) (per-URL `vi.fn` fetch stub recording `{url, method, body}`):

1. Renders held developmental skills with proficiency labels.
2. Acquire POSTs `{skill_id, proficiency:1}` to `/api/crew/{id}/skills` and refreshes.
3. A 400 with `detail` (unmet prerequisite) surfaces the message inline.
4. Suspend is two-step confirm and DELETEs; reinstate PATCHes `{suspended:false}`.
5. Honest-degrades to the empty state when every fetch fails.
6. Output contains no emoji (HXI Principle #3) — assert against the stroke-SVG/no-emoji regex used by the sibling tests.

**Run gates:** backend `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad902_skill_management.py -v -n 0`; full gate `pytest tests/ -q -n 4 --dist=loadfile`; UI `cd ui && npx vitest run`.

---

## What This Does NOT Change (out of scope — do not build)

- **Cognitive (T2) skills.** The `sr-cognitive-skills-header` list and `cognitive_skill_catalog` stay read-only. T2 skills are department+rank-derived identity, not per-agent assignable. No per-agent T2 override.
- **Rank / department gating.** No change to how T2 visibility or role-skill templates are gated.
- **The skill-definition catalog CRUD.** Creating/retiring `SkillDefinition`s is AD-895/898's job (`SkillLibrary.tsx`, `routers/skills.py`). AD-902 only assigns *existing* definitions to agents.
- **BF-610 skill-count display.** Already fixed (commit `fc93d2fa`). Do not re-address the "Skills 0" contradiction.
- **New `EventType`.** `suspend_skill` emits nothing in v1. No `events.py` migration. `SKILL_SUSPENDED` telemetry is a future, separate AD.
- **A new console view.** `SkillManagement` is composed inside the existing `sr-section-skills` (à la AD-901), **not** added to the `ConsoleView` `'roster' | 'skills' | 'tools'` switcher.
- **`api_models` Pydantic request models.** Crew routes use raw `dict` bodies (AD-894/900 convention).

---

## Tracking

- **PROGRESS.md** — add the AD-902 line under the Crew Personnel Management epic (after AD-901). Update the test count.
- **DECISIONS.md** — append AD-902 recording: the soft-`suspend_skill` choice over a hard delete (Reversibility Preference), crew-prefixed REST co-location reusing `update_proficiency` (DRY, no logic duplication), and no-consensus-gate posture (Minimal Authority).
- **docs/development/roadmap.md** — mark AD-902 if the epic is tracked there.

One AD = one commit titled `AD-902: Per-agent developmental skill management surface`. PROGRESS.md + DECISIONS.md updated in the **same** commit.

---

## Acceptance Criteria

- `AgentSkillService.suspend_skill` added; reversible; returns `None` on unheld skill; full type annotations.
- Four `/api/crew/{agent_id}/skills…` routes live with the `503/404/400` cases above; `update_proficiency` is reused (not reimplemented).
- `SkillManagement.tsx` composed inside `sr-section-skills`; acquire / re-level / suspend / reinstate all work; two-step confirm on down-level + suspend; honest-degrade; no emoji.
- Backend tests use real `AgentSkillService` + `SkillRegistry` (no MagicMock at the substrate boundary — BF-287).
- Existing AD-896/897/898/899/901 testids stay green; the BF-207 dream-timeout pair is the only tolerated red in the full gate.
- PROGRESS.md + DECISIONS.md updated in the same commit.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-03)

```
# No removal/suspend verb exists; suspended column + field do
grep -n "class AgentSkillService" src/probos/skill_framework.py
  1199: class AgentSkillService:
grep -n "suspended" src/probos/skill_framework.py
  592:     suspended: bool = False     # True if model lacks required capabilities (AgentSkillRecord)
  939:     suspended INTEGER DEFAULT 0,                       (_SCHEMA, PK (agent_id, skill_id))
  1409:    "SELECT * FROM agent_skills WHERE proficiency > 1 AND suspended = 0"   (check_decay honors it)
  646-648: SkillProfile.proficiency_of skips suspended records
# (no `def suspend_skill`, no `def remove_skill`, no `DELETE FROM agent_skills` anywhere)

# Methods reused / placement anchor
grep -n "async def acquire_skill\|async def update_proficiency\|async def get_all_records\|async def count_agents_with_skill\|async def _get_record\|async def _upsert_record" src/probos/skill_framework.py
  1265: async def acquire_skill(... source="commissioning", proficiency=ProficiencyLevel.FOLLOW) -> AgentSkillRecord  (raises ValueError on prereq)
  1340: async def update_proficiency(... new_level, source="assessment", notes="") -> AgentSkillRecord | None  (None if no record)
  1468: async def get_all_records(self, agent_id) -> list[AgentSkillRecord]
  1480: async def count_agents_with_skill(self, skill_id) -> int   (insertion point: divider at ~1494)
  1603: async def _get_record(...) -> AgentSkillRecord | None
  1615: async def _upsert_record(...)  -> INSERT OR REPLACE (idempotent upsert)
grep -n "registry.get_skill" src/probos/skill_framework.py
  1279: defn = self._registry.get_skill(skill_id)   (get_skill is real; verify name at build)

# Router conventions (dict body, 503/404/400, accessor)
grep -n 'router = APIRouter\|getattr(runtime, "skill_service"\|HTTPException' src/probos/routers/crew.py
  32:  router = APIRouter(prefix="/api/crew", tags=["crew"])
  80:  skill_service = getattr(runtime, "skill_service", None)
  168: raise HTTPException(503, "Agent capital service not available")
  173: raise HTTPException(404, f"Agent not found: {agent_id}")
  340: @router.post("/{agent_id}/directives")  -> body: dict[str, Any]; 400 "content is required"; 400 reason on failure
  301: @router.post("/{agent_id}/tools")       -> 503/400/404 grant pattern
grep -n "get_runtime\|skill_service\|update_proficiency" src/probos/routers/skills.py
  61:  @router.post("/agents/{agent_id}/assess")  -> calls runtime.skill_service.update_proficiency (prior art, reused not duplicated)
grep -n "crew as crew_router" src/probos/api.py
  222: crew as crew_router,  # AD-892  (router already registered — no api.py change)

# Frontend composition precedent (AD-901 inside Service Record)
grep -n "import StandingOrders\|<StandingOrders\|sr-section-skills\|sr-section-orders" ui/src/components/personnel/ServiceRecord.tsx
  24:  import StandingOrders from './StandingOrders';
  247: <div data-testid="sr-section-skills">         (compose <SkillManagement/> here)
  346: <div data-testid="sr-section-orders">
  348: <StandingOrders agentId={agentId} tiers={tiers} />   (the exact precedent)
grep -n "confirmRevokeId\|body?.detail\|chipStyle\|catch { *setDirectives(\[\])" ui/src/components/personnel/StandingOrders.tsx
  (two-step confirm via confirmRevokeId; 400 body.detail parse; chipStyle stroke buttons; honest-degrade refresh — template for SkillManagement)

# Console view switcher (do NOT add a 4th view)
grep -n "type ConsoleView" ui/src/components/personnel/CrewPersonnelConsole.tsx
  26:  type ConsoleView = 'roster' | 'skills' | 'tools';
```
