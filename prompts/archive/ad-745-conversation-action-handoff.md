# AD-745 — Conversation → action handoff (browser scope v1; Playwright dispatch)

**Status:** Drafted 2026-05-19, GATE 1 pending.
**Closes:** (new top-level AD; no existing GH issue — filed at wave close per AD-722c-3).
**Depends on:** AD-744 (DM-frame contract), AD-706 (BrowserTool / Playwright session), AD-706c-2 (`compute_use_click` coordinate-grounded action), AD-706e (action vocabulary v2), AD-706f (credential vault — referenced for forward marker only), AD-423a (ToolType.COMPUTER_USE), AD-731 (refs not blobs), AD-541b (anchored episodes).
**Estimated tests:** +18 pytest, +6 vitest.

## Problem

After AD-744 ships, the Captain can share a screen to {agent} alongside a DM turn. The natural next sentence is "can you click that button for me?" or "make this change in the doc." Today the agent honest-degrades: it can describe what it sees, but it has no path to **act** on what the Captain just shared.

AD-706 already ships the BrowserTool substrate: Playwright session per Captain, `_HANDLERS` action vocabulary (click/type/scroll/state/screenshot/drag/key_combo/mouse_move/mouse_button/upload_file/download/eval_js/verify/compute_use_click/fill_credential), three-tier classifier with Captain-ACK gates, AD-541b episode anchors per action. AD-745 is the **dispatch layer** that connects a CognitiveAgent's DM reply to the BrowserTool surface.

## Solution overview

1. **Action bracket marker** in DM replies: `[ACTION: {"verb":"click","selector":"#submit","intent":"the Submit button"}]`. Mirrors AD-728d / AD-730-3 / AD-743 bracket-marker family. Parser is a new `step_5_action_dispatch` pipeline stage on `DmReplyPipeline`.
2. **Dispatch path** (one action per DM reply in v1): the parser extracts the JSON envelope, looks up the agent's `ToolPermission` for BrowserTool (AD-423a/b/c — already shipped), classifies via existing `classify_action`, and dispatches to BrowserTool. Tier-1 actions run inline; tier-2 actions surface a per-action ACK to the Captain; tier-3 actions surface a destructive-confirmation modal.
3. **Action surface** in the HXI: a new `AgentActionLog` component (collapsed per HXI #5) renders the agent's action history per DM thread. Each entry: action JSON + result frame ref + per-action stop button (HXI #4 motion: pulse during action-in-flight).
4. **Mirror session**: when the agent acts on a Captain-shared URL, BrowserTool launches its own Chromium context targeting the same URL (`BrowserSession.user_data_dir` keeps profile-clone isolation). The shared frame is the PERCEPTION channel; the action surface is the MIRROR session. Captain explicitly confirmed this safety posture (Phase 3 decision #5).
5. **Honest-degrade for non-browser surfaces**: when the agent receives a `captain_explicit_share` frame whose source is NOT a navigable URL (e.g., Photoshop window), AD-745 v1 returns describe-only. Forward marker AD-745-1 ships OS-pointer control.

## Scope

- IN: `step_5_action_dispatch` pipeline stage; `[ACTION: <json>]` bracket marker; dispatch to BrowserTool via existing `_HANDLERS`; tier-1/2/3 ACK ladder via existing `classify_action`; destructive-pattern URL allow-list (financial/auth/admin patterns); per-DM-turn action limit (default 1 — forward marker AD-745-6 for multi-step plans); `AgentActionLog` HXI component; per-action stop button (sets `BrowserSession.aborted=True`).
- IN (consensus posture): **Destructive action verbs require Captain ACK (existing AD-706e tier-3 ladder).** `requires_consensus=True` reserved for destructive-pattern URL matches (forward marker AD-745-2 for multi-agent quorum on these — v1 uses Captain-ACK-only).
- IN (Minimal Authority): agent acts in BrowserTool's isolated Chromium context, NOT the Captain's logged-in browser. Profile-clone deferred to AD-745-5 forward marker.
- IN (Reversibility): every action writes an `AnchorFrame(channel="action", trigger_type="agent_action_executed")` episode per AD-541b with `{verb, args_hash, before_frame_ref, after_frame_ref, result}`. The "after_frame_ref" is a screenshot via existing `screenshot` action — provides the audit trail and the next-step LLM input.
- IN (Safety Budget): three-tier ladder mapped to existing classifier:

  | Tier | Verbs | Gate | requires_consensus |
  |---|---|---|---|
  | 1 (auto) | `screenshot`, `state`, `scroll`, `mouse_move` | None (inline run) | False |
  | 2 (ACK) | `click`, `type`, `drag`, `key_combo` (non-destructive), `mouse_button` | Captain in-thread ACK (existing AD-706e UX) | False |
  | 3 (Captain ACK every call) | `compute_use_click`, `eval_js`, `upload_file`, `download`, destructive `key_combo` (Ctrl+W etc.), tier-2 verbs on URLs matching destructive allow-list | Modal confirmation in DM thread | False (v1); True (AD-745-2 forward marker) |

- IN (per-session trust budget): reuses AD-706c-2 Guard #10 — `BrowserSession._compute_use_consecutive_autonomous` is extended to all tier-2+ verbs, not just `compute_use_click`. New `BrowserToolConfig.action_dispatch_max_consecutive_autonomous` (default 5).
- OUT: OS-scope action (AD-745-1 forward marker).
- OUT: multi-agent quorum on destructive actions (AD-745-2 forward marker).
- OUT: OmniParser SOM grounding (AD-745-3 forward marker).
- OUT: pluggable grounding strategy (AD-745-4 forward marker).
- OUT: consensual profile-clone (AD-745-5 forward marker).
- OUT: multi-step action plans in a single DM turn (AD-745-6 forward marker).
- OUT: dedicated action-history audit surface beyond the new `AgentActionLog` (AD-745-7 forward marker for cross-thread action audit).

## Verification: existing code referenced by this AD

```
Select-String -Path src/probos/tools/browser/actions.py -Pattern "_HANDLERS\[|def classify_action"
  778: _HANDLERS["compute_use_click"] = action_compute_use_click
  783-789: _HANDLERS[drag/key_combo/mouse_move/mouse_button/upload_file/download/eval_js]
  795: _HANDLERS["fill_credential"] = action_fill_credential
  798: def classify_action(

Select-String -Path src/probos/tools/browser/compute_use.py -Pattern "action_compute_use_click|_PROMPT_TEMPLATE"
  43: _PROMPT_TEMPLATE = (
  86: async def action_compute_use_click(
  (Guard #9 verification handshake at compute_use.py:~170 — verify exact line in pre-flight.)

Select-String -Path src/probos/tools/browser/session.py -Pattern "_compute_use_consecutive_autonomous|aborted"
  (Wave 162 AD-706c-2 Guard #10 fields — verify during pre-flight.)

Select-String -Path src/probos/tools/protocol.py -Pattern "ToolType|ToolPermission"
  22:    COMPUTER_USE = "computer_use"
  (Permission enum used by AD-720b chat tool-grant pipeline.)

Select-String -Path src/probos/cognitive/dm/ -Pattern "step_4d_follow_up_parse|DmReplyPipeline" -SimpleMatch
  (Wave 176 AD-743 follow-up pipeline; new step_5_action_dispatch inserts after step_4d.)

Select-String -Path src/probos/tools/browser/__init__.py -Pattern "BrowserTool|BrowserSession"
  3: from probos.tools.browser.tool import BrowserTool
  6: __all__ = ["BrowserTool", "BrowserSession"]

Select-String -Path src/probos/api_models.py -Pattern "ToolPermissionStore|tool_grant"
  321: Captain grants an agent scoped access to a registered tool (BrowserTool
  (AD-720b chat-tool-grant precedent for Captain-issued permission flow.)
```

## Implementation

### Section 0: Config

`src/probos/config.py` — extend `BrowserToolConfig`:

```python
# AD-745: action dispatch from DM replies.
action_dispatch_enabled: bool = Field(default=False,
    description="AD-745: master switch. Default OFF (Wave 10 convention #14).")
action_dispatch_max_consecutive_autonomous: int = Field(default=5, ge=0, le=20,
    description=("AD-745: consecutive tier-1/2 actions before forcing Captain "
                 "ACK. Reuses AD-706c-2 Guard #10 trust-budget pattern."))
action_dispatch_max_per_dm_turn: int = Field(default=1, ge=1, le=10,
    description=("AD-745 v1: single action per DM reply. >1 reserved for "
                 "AD-745-6 multi-step plans (forward marker)."))
destructive_url_patterns: list[str] = Field(
    default_factory=lambda: [
        "*/checkout*", "*/payment*", "*/billing*",
        "*/auth/*", "*/login*", "*/oauth*",
        "*/admin/*", "*/settings/account*",
        "*/delete*", "*/destroy*",
    ],
    description=("AD-745: fnmatch patterns. URLs matching any pattern force "
                 "all action verbs to tier-3 (Captain ACK every call)."),
)
```

### Section 1: Bracket parser

New file `src/probos/cognitive/dm/action_parser.py`:

```python
_ACTION_RE = re.compile(r"\[ACTION:\s*(\{.*?\})\s*\]", re.DOTALL)

@dataclass(frozen=True)
class ActionEnvelope:
    verb: str
    args: dict[str, Any]
    raw_intent: str  # the human-readable "intent" field for confirm modal

def parse_action_envelopes(reply_text: str) -> list[ActionEnvelope]:
    """Returns 0+ envelopes. Tier-2 honest-degrade — malformed JSON skipped."""
```

Hard cap: respect `action_dispatch_max_per_dm_turn`. Extra envelopes dropped with WARNING log.

### Section 2: Pipeline stage

New `step_5_action_dispatch` in `src/probos/cognitive/dm/pipeline.py` (or wherever `DmReplyPipeline` lives — verify location during pre-flight). Inserts AFTER `step_4d_follow_up_parse` (AD-743) and BEFORE `step_4b_dm_outbound_parse`. Idempotent and tier-2 — every failure mode degrades to "drop the action, keep the reply."

Flow per envelope:
1. Look up Captain's ToolPermission for BrowserTool. If absent → drop + log `action_dispatched_no_permission`.
2. `classify_action(verb, args, page_url=session.url, page_title=session.title)` → tier 1/2/3.
3. Match `page_url` against `destructive_url_patterns`. If match → force tier 3.
4. Compute `BrowserSession._compute_use_consecutive_autonomous` (already shipped). If above cap → force tier 3.
5. Emit `EventType.ACTION_DISPATCH_PROPOSED` with the envelope + classification.
6. Tier 1: dispatch inline, emit `ACTION_DISPATCH_EXECUTED`.
7. Tier 2: emit `ACTION_DISPATCH_ACK_PENDING`. The HXI surfaces an in-thread ACK button; Captain ACK calls `POST /api/browser/actions/{action_id}/ack`. Timeout (default 60s, configurable) honest-degrades to `ACTION_DISPATCH_TIMED_OUT`.
8. Tier 3: emit `ACTION_DISPATCH_CONFIRM_PENDING`. HXI surfaces a destructive-confirmation modal; Captain ACK is an explicit click, NOT silent timeout. NO timeout — modal stays open until Captain decides.

### Section 3: Action endpoint

New file `src/probos/routers/agent_actions.py`:

```
POST /api/browser/actions/{action_id}/ack   — Captain in-thread approve
POST /api/browser/actions/{action_id}/abort — Captain abort
GET  /api/browser/actions/{thread_id}       — list pending + recent actions for a DM thread
```

All under `require_crew_scope`. `action_id` is the SHA-256 of `(captain_id, agent_id, dm_turn_id, action_seq)`. Pending actions in-memory dict (forward marker AD-745-7 for SQLite persistence across restart).

### Section 4: Episode anchor

Every executed action (tier 1, tier 2 post-ACK, tier 3 post-confirm) writes an Episode per AD-541b:

```python
Episode(
    timestamp=...,
    user_input=captain_dm_text_or_empty,
    outcomes=[{
        "intent": "agent_action_executed",
        "verb": envelope.verb,
        "args_hash": hashlib.sha256(json.dumps(envelope.args, sort_keys=True).encode()).hexdigest(),
        "before_frame_ref": pre_screenshot_sha,
        "after_frame_ref": post_screenshot_sha,
        "result": dispatch_result,
        "tier_classified": tier,
    }],
    reflection=f"{agent_id} executed {envelope.verb} ({envelope.raw_intent})",
    source="action_dispatch",
    importance=7,
    anchors=AnchorFrame(
        channel="action",
        trigger_type="agent_action_executed",
        trigger_agent=agent_id,
    ),
)
```

Note: `before_frame_ref` is a screenshot taken JUST BEFORE the action. `after_frame_ref` is taken after via the existing `screenshot` action handler. AD-731 invariant preserved — frames flow through `AttachmentStore.write`.

### Section 5: HXI — AgentActionLog

New file `ui/src/components/chat/AgentActionLog.tsx`. Renders inside each DM thread when actions exist. Collapsed by default (HXI #5). Per-entry:

- Verb name in mono.
- `intent` description.
- Stroke-SVG tier glyph (1/2/3 = different stroke densities, no color reliance per a11y).
- Status: `proposed` (dim grey) / `ack_pending` (amber, pulsing per HXI #4) / `confirm_pending` (amber, faster pulse) / `executed` (green stroke check) / `aborted` (red stroke X) / `failed` (orange stroke alert).
- Before/after frame thumbnails (stroke-bordered, click to expand).
- Per-action ABORT button (stroke-SVG X).

New `useActionLogStore.ts` Zustand slice — polls `GET /api/browser/actions/{thread_id}` every 2s while the thread is focused.

### Section 6: HXI — Tier-2 ACK + Tier-3 confirm

Tier-2 ACK: appears as a stroke-bordered card directly above the DM composer in the active thread. Buttons: APPROVE / SKIP. Card shows action verb + intent + page URL + favicon (stroke-SVG fallback).

Tier-3 confirm modal: full-screen overlay (matches AD-741 SettingsPanel overlay shape). Title in red stroke "Destructive action proposed." Body: action JSON pretty-printed (NOT in inline-code; HXI #3 — uppercase mono per HXI design). URL pattern match reason shown verbatim ("URL matches `*/checkout*`"). Buttons: APPROVE (amber outline, confirms in-place) / ABORT (red stroke, also aborts session if Captain wishes). NO emoji.

### Section 7: Tests

`tests/test_ad745_action_parser.py`:
1. `parse_action_envelopes` extracts one envelope.
2. Handles multiple envelopes (count-capped per config).
3. Malformed JSON → skipped with WARNING log.
4. No envelopes → returns empty list.

`tests/test_ad745_pipeline_dispatch.py`:
5. Tier-1 verb (`screenshot`) dispatches inline, emits EXECUTED event.
6. Tier-2 verb (`click`) emits ACK_PENDING, blocks on ACK.
7. Tier-3 verb (`compute_use_click`) emits CONFIRM_PENDING, blocks on confirm.
8. Destructive URL pattern forces tier-3 even for tier-2 verb.
9. Consecutive-autonomous cap forces tier-3 after N tier-1/2 actions.
10. Per-DM-turn cap enforced; extra envelopes dropped + logged.
11. Missing ToolPermission honest-degrades to dropped + log.
12. AD-745 master switch off honest-degrades to dropped.

`tests/test_ad745_episode_anchor.py`:
13. Executed action writes Episode with `anchor.channel="action"` + `trigger_type="agent_action_executed"`.
14. Before/after frame refs present in outcomes.
15. AD-731 invariant: action outcomes carry SHA refs, not bytes.

`tests/test_ad745_action_endpoints.py`:
16. POST /ack approves pending tier-2 action.
17. POST /abort aborts pending action AND sets `BrowserSession.aborted=True`.
18. GET /actions returns per-thread action list with status.

`ui/src/components/chat/__tests__/AgentActionLog.test.tsx`:
1. Renders collapsed by default.
2. Expand toggle reveals entries.
3. Tier glyph stroke-density matches classification.
4. ABORT button calls POST /abort.
5. Pulse animation on `ack_pending` / `confirm_pending` status.
6. Frame thumbnails are stroke-bordered (HXI #3 sanity).

Total: +18 pytest, +6 vitest.

## Acceptance criteria

- All tests pass with the standard gate.
- `cd ui && npm run build` exits 0.
- AD-731 invariant source-scan passes on `cognitive/dm/action_parser.py` + `routers/agent_actions.py`.
- AD-541b episode anchor written for every executed action.
- Zero new pip deps (Playwright already resident from AD-706).
- Zero new npm deps.
- 0-line diff on all 5 license files.
- Default-OFF: `action_dispatch_enabled=False` preserves baseline behavior for operators who don't want the surface.
- Forward markers filed with TECHNICAL triggers per AD-722c-3:
  - AD-745-1 — `DesktopActionTool` OS-pointer scope. Trigger: Captain shares a non-browser surface AND requests action ≥3 times.
  - AD-745-2 — Multi-agent quorum on destructive actions (`requires_consensus=True` on destructive-pattern URL matches). Trigger: tier-3 confirm-pending events sustained ≥10/wave OR Captain reports near-miss destructive action.
  - AD-745-3 — OmniParser SOM grounding for VLM-coordinate accuracy. Trigger: `compute_use_click` failure rate observed ≥20% OR Captain demand for canvas/embed grounding.
  - AD-745-4 — Pluggable grounding strategy (mirrors AD-742d). Trigger: AD-745-3 lands AND operator demand for choice.
  - AD-745-5 — Consensual profile-clone (agent acts in a clone of the Captain's logged-in profile for the duration of the task). Trigger: Captain explicitly requests "use my login."
  - AD-745-6 — Multi-step action plans per DM turn. Trigger: AD-745 v1 exercised ≥1 wave AND Captain demand for batched actions.
  - AD-745-7 — Cross-thread action audit surface + SQLite persistence of pending actions across restart. Trigger: action volume sustained ≥50/wave OR Captain demand for action history beyond live thread.
- PROGRESS.md Wave 178 block updated post-ship.

## Out-of-scope (explicit)

- Any OS pointer control (AD-745-1).
- Multi-agent quorum on destructive verbs (AD-745-2).
- OmniParser / SeeAct grounding (AD-745-3 / -4).
- Consensual profile-clone (AD-745-5).
- Multi-step plans (AD-745-6).
- Cross-thread action audit (AD-745-7).
- New BrowserTool action verbs beyond what AD-706e ships (verbs are dispatch consumers; new verbs land in AD-706e siblings).

## Overlap with AD-721j (Blender Connector)

AD-721j (#538, OPEN) proposes Blender computer-use control via the same `ToolType.COMPUTER_USE` slot. AD-745 ships the **generic dispatch substrate** that AD-721j would otherwise duplicate. Recommendation: re-scope AD-721j post-AD-745 to "Blender as a target application of DesktopActionTool (AD-745-1)." Captain ruling required at wave close — see RESEARCH-wave-178.md §11 question 1.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`, especially the consensus + minimal-authority + reversibility requirements for destructive screen-action intents.**
