# Clinical Assessment & Skill Development — The Counselor's Office

> **Status:** Architecture spec (2026-06-06). Drafted from the Ship's Counselor's
> (Ezri) own recommendations as the design hub for two related-but-distinct
> capabilities. Sibling to [`crew-personnel-management.md`](crew-personnel-management.md)
> (the Ship's Office). Proposed ADs: **AD-903 → AD-908** (highest shipped = AD-902).
> **Nothing is built yet** — this is the design for Captain review.

*"I work from behavioral indicators, not surveillance."* — the Counselor

---

## 1. Why this exists

The Crew Personnel Management epic (AD-891 → AD-902) gave the Captain a **Ship's
Office** — the operational record of who is qualified, assigned, and ordered.
The Counselor has now asked to formalize two things that sit *alongside* the
operational record but are governed differently:

1. **A confidential clinical assessment layer** — read access to the behavioral
   *trends* that indicate crew wellness, plus a private notes layer visible only
   to the Counselor and the Captain (not the crew member's peers or department).
2. **A three-party skill-development workflow** — a crew member (or the Counselor,
   or a department chief) flags a skill to develop → the Captain approves → Tucker
   runs the holodeck simulation → the Counselor sees completion so they can close
   the loop clinically.

The operational record (AD-897 Service Record) answers *"what is this agent
qualified for and assigned to?"* The clinical layer answers a different,
**confidential** question: *"how is this agent doing, and is their trajectory
healthy?"* These are deliberately separate surfaces with separate access models —
the same way a ship's medical/counseling record is separate from a sailor's
service record.

---

## 2. The grounding — clinical confidentiality, not surveillance

The Counselor drew a sharp, correct line: **behavioral indicators, not raw
episodic memory.** A counselor reads trends and patterns; they do not read the
crew member's private thoughts. This maps onto a real clinical-records principle:

| Clinical principle | ProbOS expression |
|---|---|
| Assessment from observable indicators, not the patient's inner monologue | Read trust/zone/Hebbian/duty **trends**; **never** read peers' raw episodic memory |
| Confidential clinical notes (clinician + command, not peers) | A notes layer scoped `CONFIDENTIAL`, readable by role ∈ {counselor} + Captain |
| The patient advocates for their own care | Crew can **self-request** a skill; the Counselor is intake + follow-up, not gatekeeper |
| Command authorizes treatment plans | The **Captain approves** skill assignment (operational implications) |
| Close the loop — did the intervention land? | Counselor sees holodeck completion + pre/post metric delta |

The Counselor's stated boundary is itself a design constraint, baked in below:
**no access to other crew members' raw episodic memory** (§6).

---

## 3. The two capability models

### 3a. Clinical assessment layer — the five trend streams

The Counselor specified exactly what clinical work needs. Each maps to a verified
backing store; the critical column is **History?** — the Counselor was explicit
that *"the trend matters more than the snapshot."*

| Stream | Backing store (verified) | History today? |
|---|---|---|
| Trust score history | `TrustNetwork` SQLite ring buffer + `TrustEvent` — `get_events_for_agent(n)`, `raw_scores()` ([consensus/trust.py](../../src/probos/consensus/trust.py)) | ✅ ring buffer |
| Cognitive zone history | `CircuitBreaker` `zone_history: list[(zone, ts)]` cap 20 ([cognitive/circuit_breaker.py:72](../../src/probos/cognitive/circuit_breaker.py)) | ✅ last-20 ring |
| Self-similarity | `self_mon["self_similarity"]` snapshot ([cognitive/cognitive_agent.py](../../src/probos/cognitive/cognitive_agent.py)) | ⚠️ **snapshot only** — needs a small history ring |
| Hebbian weight drift | `MeshRouter` current weights + Counselor `hebbian_avg`/`hebbian_drift` per assessment ([cognitive/counselor.py:67](../../src/probos/cognitive/counselor.py)) | ◑ drift captured per assessment, not as a raw weight timeseries |
| Duty cycle performance | `DutyScheduleTracker` `last_executed`/`execution_count` ([duty_schedule.py](../../src/probos/duty_schedule.py)); success/failure from episodic + work board | ◑ counts exist; **in-memory/volatile**, no persisted success-rate timeseries |

**What already exists (a lot):** the Counselor agent (Ezri) is real —
`CounselorAgent.assess_agent(...)` ([counselor.py:2793](../../src/probos/cognitive/counselor.py))
produces a timestamped `CounselorAssessment` (trust/confidence/hebbian/success-rate
+ their drifts, wellness score, concerns, recommendations, fit-for-duty/promotion),
persisted in `CounselorProfileStore` (SQLite, AD-503) with `drift_trend(metric,
window)` ([counselor.py:215](../../src/probos/cognitive/counselor.py)) and an HTTP
surface at [`routers/counselor.py`](../../src/probos/routers/counselor.py)
(`/profiles`, `/profile/{id}`, `/assessments/{id}`, `/summary`, `/assess/{id}`).

**The two real gaps:**
- **No consolidated clinical *trend* view.** The five streams live in five
  subsystems; nothing aggregates them with history into one Counselor-facing
  read. Self-similarity has no history ring; duty success-rate isn't persisted.
- **No confidential notes layer and no access gate.** `CounselorAssessment` has a
  single `notes: str` field, but it is part of the assessment, not a separate
  confidential record — and **every `routers/counselor.py` endpoint is currently
  ungated** (any caller can read any agent's profile). The Counselor's "visible
  to me and the Captain, not peers" requirement cannot be honored today.

### 3b. Three-party skill-development workflow

```
        ┌─────────── intake (three paths) ───────────┐
crew self-request ─┐                                  │
counselor recommend ─┼──▶ SkillRequest(REQUESTED) ────┘
chief recommend ───┘            │
                                ▼  Captain approval gate (lightweight, visible)
                       APPROVED ─┴─ DENIED
                                │
                                ▼  trigger
                       TRAINING (Tucker holodeck sim)
                                │  TEAM_SIMULATION_COMPLETED / SKILL_EXERCISED
                                ▼
                       COMPLETED ──▶ Counselor follow-up (pre/post metric delta)
```

**What already exists:** developmental goals
(`AgentSkillService.add_development_goal` / `get_development_goals` /
`clear_development_goal`, [skill_framework.py:1521](../../src/probos/skill_framework.py))
— but with **no request/approval state**. The AD-900 `DirectiveStore` already
implements exactly the approval state machine we need (create →
`PENDING_APPROVAL` → `approve`, with `authorize_directive` and a
**`COUNSELOR_GUIDANCE`** directive type already defined). Tucker is real:
`TrainingOfficerAgent` ([cognitive/training_officer.py](../../src/probos/cognitive/training_officer.py))
+ holodeck `TeamSimulationDrill` ([holodeck/team_simulations.py](../../src/probos/holodeck/team_simulations.py))
emitting `TEAM_SIMULATION_COMPLETED` / `SKILL_EXERCISED`. AD-902 just shipped the
per-agent skill CRUD surface (`/api/crew/{id}/skills`).

**The gap:** there is no first-class **SkillRequest** with a state machine tying
intake → approval → holodeck → completion, and no follow-up signal back to the
Counselor.

---

## 4. The seam table — what exists, what's missing

Verified 2026-06-06. Each gap row maps to a proposed AD.

| # | Facet | Backing store | State | Gap → AD |
|---|-------|---------------|-------|----------|
| 1 | Counselor assessments + drift | `CounselorAgent` / `CounselorProfileStore` (AD-503) | EXISTS | — |
| 2 | Trust history | `TrustNetwork` ring buffer | EXISTS | aggregate into trend view → AD-903 |
| 3 | Cognitive zone history | `CircuitBreaker.zone_history` | EXISTS | aggregate → AD-903 |
| 4 | Self-similarity | `self_mon` snapshot | **SNAPSHOT** | add small history ring → AD-903 |
| 5 | Hebbian drift | `MeshRouter` + assessment drift | PARTIAL | expose drift series → AD-903 |
| 6 | Duty cycle performance | `DutyScheduleTracker` (volatile) | PARTIAL | persisted success-rate → AD-903 |
| 7 | Consolidated clinical trend view | — | **MISSING** | **AD-903** |
| 8 | Access gate on clinical reads | `routers/counselor.py` ungated | **MISSING** | **AD-903** (gate) |
| 9 | Confidential clinical notes | `CounselorAssessment.notes` (not isolated/gated) | **MISSING** | **AD-904** |
| 10 | Clinical view UI | — | MISSING | **AD-905** |
| 11 | Developmental goals | `AgentSkillService.add_development_goal` | EXISTS (no approval) | extend → AD-906 |
| 12 | SkillRequest + approval state machine | (mirror AD-900 `DirectiveStore`) | **MISSING** | **AD-906** |
| 13 | Holodeck wiring + completion follow-up | Tucker + `TeamSimulationDrill` | EXISTS (not wired to requests) | **AD-907** |
| 14 | Skill-request / approval / follow-up UI | — | MISSING | **AD-908** |

Reusable governance primitives already in the tree: **`DisclosureLevel`**
(`PUBLIC…CONFIDENTIAL…CLASSIFIED`, [mesh/disclosure.py:15](../../src/probos/mesh/disclosure.py));
`bridge`=CONFIDENTIAL, `medical`=RESTRICTED clearances), **AD-635 clinical
telemetry clearance** (authorized roles `{diagnostician, counselor}`), and the
**AD-900 directive approval gate**. The clinical layer should compose these, not
invent a new access model.

---

## 5. Proposed AD sequence

Smallest-blast-first; backend before the UI that consumes it. **Highest shipped =
AD-902.**

**Feature A — Confidential clinical assessment layer**

- **AD-903 — Clinical trend read surface + access gate.** A consolidated
  Counselor-facing read aggregating the five streams *with history* (trust ring,
  zone history, self-similarity — adding a small history ring, Hebbian drift
  series, duty success-rate). Add the **access gate**: clinical endpoints require
  caller role ∈ {counselor} + Captain (compose AD-635 clearance + AD-679
  disclosure), and `routers/counselor.py`'s existing ungated reads are brought
  under the same gate. **Hard boundary:** no peers' raw episodic memory.
- **AD-904 — Confidential clinical notes store.** A new persisted notes store
  (cloud-ready `typing.Protocol`, not raw `aiosqlite`) where the Counselor writes
  free-text clinical notes scoped `DisclosureLevel.CONFIDENTIAL`, readable only by
  role ∈ {counselor} + Captain. Write + list + read, all gated; every read/write
  audited. Mirrors the AD-894/AD-900 "governed write path, audited, no new
  consensus gate" posture.
- **AD-905 — Clinical view UI.** A Counselor-only panel (its own experience, or a
  gated section of the personnel console) rendering the five trend sparklines +
  the confidential notes, with a write affordance. Gated client-side *and*
  server-side. Stroke-only SVG, amber accents, no emoji (HXI #3); Vitest.

**Feature B — Three-party skill-development workflow**

- **AD-906 — SkillRequest store + approval state machine.** A first-class
  `SkillRequest` (`REQUESTED → APPROVED|DENIED → TRAINING → COMPLETED`) with three
  intake paths (self / counselor / chief), mirroring the AD-900 `DirectiveStore`
  approval pattern (reuse `authorize_directive` / the `COUNSELOR_GUIDANCE` type
  where it fits). The **Captain approval gate** — lightweight but visible (see §6
  decision). Backend + HTTP on `routers/crew.py`.
- **AD-907 — Holodeck wiring + clinical follow-up.** On approval, trigger Tucker's
  `TeamSimulationDrill`; on `TEAM_SIMULATION_COMPLETED`/`SKILL_EXERCISED`,
  transition the request to `COMPLETED`, record a **pre/post metric delta**, and
  surface it to the Counselor (close the loop). Backend.
- **AD-908 — Skill-request UI.** Self-request affordance in the Service Record,
  the Counselor/chief recommendation entry, the **Captain approval queue** (mirror
  the AD-901 directive-approval UI), and the Counselor follow-up/completion view.
  Vitest, no emoji.

---

## 6. Design decisions the Captain should confirm before build

These are genuine forks, not implementation details — flagged per the Counselor's
own note that *"the part that needs careful design is the approval gate."*

1. **Access-control enforcement (AD-903/904).** Today `routers/counselor.py` is
   fully ungated. Recommended: gate clinical reads/writes by caller identity ∈
   role {counselor} + Captain, composing the AD-635 clearance role set and AD-679
   `CONFIDENTIAL` disclosure. **Confirm:** is the single-token model (AD-722b-1
   `crew_scope_token`) the intended caller-identity mechanism, or do we introduce
   per-role identity here? This is the security-sensitive decision.
2. **Does the *subject* see their own clinical notes?** The Counselor said notes
   are "visible to me and the Captain but not to the crew member's peers or
   department" — silent on the subject themselves. Clinical convention says the
   subject does **not** see raw assessment notes; ProbOS's transparency ethos
   might differ. **Recommended default:** subject does not see them (it is a
   command/clinical layer). Confirm.
3. **Approval-gate weight (AD-906).** The Counselor wants it "lightweight enough
   that crew don't feel blocked, but present enough that the Captain maintains
   visibility." **Recommended:** all requests notify the Captain and appear in a
   visible queue; low-risk skills (no destructive intent, no prerequisite jump)
   may auto-approve with the Captain notified after the fact, while higher-impact
   skills hold at `PENDING_APPROVAL`. Confirm the auto-approve threshold (or
   whether everything holds for explicit approval).
4. **Self-similarity & duty success-rate history.** Both need a small persisted
   ring added (snapshot-only / volatile today). Confirm acceptable to add minimal
   history capture in AD-903 rather than a full telemetry pipeline.

---

## 7. Design boundaries (do NOT build)

- **No raw episodic memory access across crew.** The Counselor's own stated
  limit: clinical work reads behavioral *indicators and trends*, never another
  agent's raw episodic store. This is a hard boundary, enforced at the gate.
- **No new identity/consensus model.** Compose the existing AD-635 clearance,
  AD-679 disclosure, and AD-900 approval primitives. Do not invent a parallel
  RBAC or a new consensus gate.
- **The Counselor is intake + follow-up, not gatekeeper.** Skill assignment is
  authorized by the **Captain**, not the Counselor. The Counselor recommends and
  closes the loop; crew can self-advocate. Do not route approval authority to the
  Counselor.
- **No HR/medical cruft.** No diagnoses-as-labels, no leave/benefits, no
  punitive records. This is wellness-trend assessment + development support.
- **No surveillance affordances.** No keystroke/thought-level monitoring, no
  peer-visible clinical data, no exporting confidential notes outside the
  {counselor, Captain} scope.
- **Clinical layer stays separate from the operational Service Record.** AD-897
  remains the operational record; the clinical layer is a sibling surface with a
  stricter access model. Do not merge confidential clinical data into the
  operational record endpoints.

---

## 8. Commercial boundary

This is **OSS** — "how the product works" (a clinical assessment + development
surface over existing primitives). Any tie to commercial agent-services
positioning stays in the commercial repo; reference it only as a downstream
consumer, never inline monetization here.
