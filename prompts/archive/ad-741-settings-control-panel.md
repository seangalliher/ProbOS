# AD-741 — Settings / Control Panel HXI shell

**Status:** Draft (Wave 170)
**Dependencies:** none (additive)
**Estimated tests:** +17 pytest, +9 vitest
**License posture:** 0-line diff. Vite/React/Zustand only; no new pip or npm deps.

## Problem

The HXI today has WARD ROOM, CREW MANIFEST, NOTEBOOKS, RECORDS, EXPLORER, METRICS panels (see `ui/src/App.tsx:90-178`). There is no operator-facing surface to read or modify `system.yaml` at runtime — every config change requires editing the YAML file and restarting. The Captain mockup (extracted via Claude Artifact, transcribed in `prompts/WAVE-170-DISPATCH.md` §"Captain Mockup") inspired a multi-domain control panel with a drafted-change buffer, search, and explicit APPLY ↵ flow.

There is also no `/api/config` endpoint pair today (verified: `grep -r "api/config" src/probos/routers/` → 0 hits). This AD ships both the API and the UI shell in one wave.

**Scope refinement vs the original mockup** (Captain ruling 2026-05-17): the mockup's 28-entry, 6-domain sidebar was an aspirational sketch. SystemConfig has 180+ Pydantic classes but only ~10-12 expose operator-actionable knobs that make sense in a control panel. Most internal subsystems (Mesh, Consensus, Self-Mod, Dreaming, Circuit Breaker, NATS Bus, …) have no Captain-tunable surface — surfacing them as stub sidebar entries reads as "unfinished UI." v1 ships **11 wired sections (10 from AD-741 + Perception from AD-733) across 4 domains**, all real, and a single bottom-of-sidebar **Advanced configuration** affordance that opens the full `system.yaml` in the VIEW YAML modal for direct editing (read-only in v1; raw edit = forward marker AD-741-6).

## Solution overview

1. **New API surface** under `/api/config`:
   - `GET /api/config` — returns the live `SystemConfig.model_dump(mode='json')` + a section-descriptor registry + uptime + sync state. Secret-named fields (see §"Secret-field rule") are redacted to a `present | absent` boolean.
   - `POST /api/config` — accepts a draft patch dict, validates it by constructing a new `SystemConfig(**merged)`, returns 422 with field-level errors on failure, returns 200 with `restart_required: bool` + list of changed fields on success. Patches that include secret-flagged field paths are rejected 400 `secret_field_readonly`. **v1 does NOT mutate `runtime.config`** — it writes the validated YAML to disk and reports restart-required. Hot-reload of individual fields is AD-741-1 (forward marker).
   - `GET /api/config/yaml` — returns the current `system.yaml` text (for the `VIEW YAML` button). Secret values are scrubbed to `"<redacted>"` before render.
2. **Section descriptor registry** (`src/probos/settings/section_registry.py`, new file): single source of truth for the 11 sidebar entries — `(id, label, glyph, domain, description, fields: list[FieldDescriptor])`. 10 added by AD-741 + 1 `perception` added by AD-733 in the same wave. No stubs. Header reads `${section_count} sections · ${domain_count} domains` (dynamic).
3. **New HXI overlay panel** `ui/src/components/settings/SettingsPanel.tsx` (and friends), opened from the TopNav, drafted-change buffer in Zustand store. Matches the existing overlay-panel pattern (`WardRoomPanel`, `CrewRosterPanel`).

## Architecture decisions

- **Auth.** Both endpoints behind `require_crew_scope` (`src/probos/routers/auth.py:40`). When `AuthConfig.crew_scope_token` is empty (default single-Captain mode), it's a pass-through — same posture as every other Captain-only endpoint.
- **CSRF.** No app-wide CSRF middleware exists today (verified: 0 hits on `csrf` outside `cloud_pickers.py:state_store`). Reuse the same pattern AD-720c shipped — explicit `X-Probos-CSRF` header for POST `/api/config`, single-consume token issued by `GET /api/config` in the response body (NOT a cookie — HXI is same-origin, fetch sets the header). Forward marker AD-741-5 if a broader CSRF middleware lands later.
- **Hot-reload posture.** v1 treats EVERY field as `restart_required: true`. The response payload to APPLY surfaces this so the UI shows a clear "ProbOS restart required to take effect" banner with a `↻ Restart` button (POSTs to existing `/api/system/shutdown` — Captain re-launches manually; full restart-in-place is AD-741-4). Specific fields that CAN hot-reload (e.g. `system.log_level` via `logging.getLogger().setLevel`, `federation.enabled` toggle) are forward marker AD-741-1; treating them all uniformly in v1 avoids partial-apply confusion.
- **YAML round-trip.** Pydantic `model_dump` does NOT preserve YAML comments or key ordering. v1 accepts this loss and stamps a `# Edited via HXI YYYY-MM-DD HH:MM:SS UTC` comment header. Operators editing YAML by hand keep their comments only until the first HXI-driven APPLY. Document this in the UI's `VIEW YAML` modal footer.
- **YAML write target.** `runtime.config_path` if set, else the path passed at `_load_config()` time. If the path is None (in-memory-only test config), 503 `config_path_unavailable`. Verified `runtime.config_path` attribute exists by reading `__main__.py:_load_config` flow.
- **Validation errors.** Pydantic v2 `ValidationError.errors()` returns `[{loc: tuple, msg: str, type: str, input: any}]`. Map `loc` to the section/field descriptor, surface inline next to the field in the UI plus a toast in the status bar.
- **Sidebar grouping & order.** Domains are ordered by frequency-of-use, not architectural layer: (1) Core touched on first-run setup, (2) Perception & Voice touched whenever Captain changes sensory hardware, (3) Identity & Presentation touched when crew composition changes, (4) Connectivity touched when integrating with external systems. Captain's per-agent settings live in the existing `AgentProfilePanel` (`ui/src/components/profile/AgentProfilePanel.tsx`) launched from CrewRosterPanel — Settings panel does NOT duplicate that surface. Deep-link from Settings → Crew Roster → Agent Profile = forward marker AD-741-7.

## Secret-field rule (hard standard)

Any Pydantic field whose **field name** (not its containing class) matches the regex `(?i)(secret|token|password|api_key|private_key)` is treated as a redacted surface:

1. `GET /api/config` replaces the value with `null` and marks the field descriptor with `kind: "secret_present_only"`. The UI renders this as a read-only `Configured` / `Not configured` chip (boolean derived from `bool(original_value)`).
2. `GET /api/config/yaml` replaces matching values with the literal string `"<redacted>"` before serializing.
3. `POST /api/config` rejects any patch whose flattened key list contains a secret-flagged path → 400 `secret_field_readonly` with the offending paths.
4. Secret values are mutated only by direct `system.yaml` edits (or AD-706f vault for OAuth credentials per AD-720c) — never through the HXI.

Implementation: a single `_is_secret_field_id(field_id: str) -> bool` helper in `section_registry.py`, used by both the registry's field descriptor builder AND the API layer (read redaction, yaml scrub, write rejection). A new `FieldKind` value `secret_present_only` carries the chip metadata. Tested in `test_ad741_secret_redaction.py` (+3 tests in §"Tests").

Verified secret-field paths in HEAD (audit performed for the 11 wired sections):
- `cloud_pickers.<provider>.client_secret` (3 providers × 1 field = 3 paths)
- `auth.crew_scope_token` (outside v1 wired surfaces but covered by the rule)
- Any future field named `*_token` / `*_secret` / etc. is automatically caught — no per-field whitelist maintenance.

## Section registry (v1 wired surfaces — 10 + 1)

Every section below maps to fields verified to exist in HEAD (`src/probos/config.py`). Field paths quote the exact attribute name; the registry's `field_id` strings are this dotted form rooted at SystemConfig.

| # | Section id | Sidebar label / glyph | Domain | Fields exposed v1 |
|---|---|---|---|---|
| 1 | `system` | `◇ System` | Core | `system.name` (text), `system.version` (readonly), `system.log_level` (enum: TRACE/DEBUG/INFO/WARN/ERROR/FATAL) |
| 2 | `llm_tiers` | `✺ LLM Tiers` | Core | Per-tier (fast / standard / deep / vision / image_gen): `system.llm_base_url_<tier>`, `system.llm_model_<tier>`, `system.llm_timeout_<tier>`. Per-tier honest-degrade banner when unconfigured. (Vision = AD-732, image_gen = AD-730-3 — Wave 169.) |
| 3 | `memory` | `◈ Memory` | Core | `memory.max_episodes` (int), `memory.relevance_threshold` (float), `memory.agent_recall_threshold` (float), `memory.embedding_model` (text) |
| 4 | `perception` | `▣ Perception` | Perception & Voice | (Filled by AD-733 §"Settings wiring": camera enable, fps, kill switch, indicator preferences) |
| 5 | `voice` | `≈ Voice` | Perception & Voice | `tts.enabled` (bool), `tts.backend` (enum: browser/piper), `tts.voice_model` (text), `tts.length_scale` (float), `tts.noise_scale` (float), `lipsync.backend` (enum), `lipsync.binary_path` (text) |
| 6 | `avatars` | `✿ Avatars` | Identity & Presentation | `avatars.enabled` (bool), `avatars.avatars_dir` (text), `avatars.max_vrm_size_bytes` (int), `avatars.renderer_enabled` (bool), `avatars.fallback_to_parametric_on_error` (bool). Per-agent appearance edits stay in `CrewAvatarEditor` — not duplicated here. |
| 7 | `ward_room` | `◊ Ward Room` | Identity & Presentation | `ward_room.enabled` (bool), `ward_room.max_thread_posts` (int), `ward_room.dm_exchange_limit` (int), `ward_room.retention_days` (int). Hebbian router toggle exposed as `ward_room_hebbian.enabled` (bool) since the substructure lives outside `WardRoomConfig`. |
| 8 | `federation` | `⊞ Federation` | Connectivity | `federation.enabled` (bool), `federation.node_id` (readonly), `federation.bind_address` (text) |
| 9 | `channels` | `≣ Channels` | Connectivity | `channels.discord.enabled` (bool), `channels.discord.webhook_url` (text), `channels.slack.enabled` (bool), `channels.slack.webhook_url` (text), `channels.webhook.enabled` (bool), `channels.webhook.url` (text). Bot tokens / signing secrets are secret-flagged and shown as `Configured / Not configured` chips per §"Secret-field rule". (Builder verifies exact field names on each `*Config` at implementation time — pre-flight grep against `class DiscordConfig` / `SlackConfig` / `WebhookConfig`.) |
| 10 | `cloud_pickers` | `↑ Cloud Pickers` | Connectivity | `cloud_pickers.enabled` (bool), per-provider (`google_drive`, `onedrive`, `dropbox`): `enabled` (bool), `client_id` (text). `client_secret` is secret-flagged. |
| 11 | `tools` | `⚒ Tools` | Connectivity | `browser_tool.enabled` (bool), `browser_tool.headless` (bool), `browser_tool.session_max_duration_seconds` (int), `mcp.enabled` (bool), `mcp.servers` (readonly list view — add/remove = AD-741-2 forward marker) |

**Bottom-of-sidebar affordance** (rendered after the last domain group, not part of the registry):

> **Advanced configuration** — Edit `system.yaml` directly. The Settings panel surfaces the most common operator knobs; the full schema has 180+ classes. [`Open YAML editor →`]

The `Open YAML editor →` button opens the existing VIEW YAML modal in expanded mode (read-only in v1). Raw YAML editing with Pydantic validation on save = forward marker AD-741-6.

**Per-agent settings affordance** (rendered as a one-line note at the top of the sidebar OR as a single `Crew` group with one entry — architect's call at UI-implementation time; default is the one-line note):

> Per-agent settings live in the Crew Roster. [`Open Crew →`]

Clicking opens `CrewRosterPanel`. No new panel. Deep-link to a specific agent's profile = AD-741-7.

## Implementation

### Section 1 — Section descriptor registry

Create `src/probos/settings/__init__.py` and `src/probos/settings/section_registry.py`:

```python
"""AD-741: Single source of truth for HXI Settings panel sections."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

FieldKind = Literal[
    "text", "readonly", "enum", "bool", "int", "float",
    "secret_present_only",  # §"Secret-field rule" — renders as Configured/Not configured chip
]

@dataclass(frozen=True)
class FieldDescriptor:
    field_id: str        # dot-path into SystemConfig, e.g. "system.log_level"
    label: str           # human label
    kind: FieldKind
    enum_values: tuple[str, ...] = ()   # only used when kind == "enum"
    description: str = ""
    hot_reload: bool = False             # v1: always False (forward marker AD-741-1)

@dataclass(frozen=True)
class SectionDescriptor:
    section_id: str
    label: str
    glyph: str
    domain: Literal["Core", "Perception & Voice", "Identity & Presentation", "Connectivity"]
    description: str
    fields: tuple[FieldDescriptor, ...] = ()

# Registry — order matters for sidebar rendering. v1 = 10 sections from AD-741
# + 1 (perception) inserted by AD-733 in the same wave. All wired; no stubs.
SECTIONS: tuple[SectionDescriptor, ...] = (
    SectionDescriptor(
        section_id="system",
        label="System",
        glyph="◇",
        domain="Core",
        description="Process identity and global log level.",
        fields=(
            FieldDescriptor("system.name", "Process name", "text"),
            FieldDescriptor("system.version", "Version", "readonly"),
            FieldDescriptor(
                "system.log_level", "Log level", "enum",
                enum_values=("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"),
            ),
        ),
    ),
    # ... 9 more entries from AD-741; perception inserted by AD-733 in same wave.
    # See §"Section registry (v1 wired surfaces — 10 + 1)" for the full table.
)

_SECRET_RE = __import__("re").compile(r"(?i)(secret|token|password|api_key|private_key)")

def is_secret_field_id(field_id: str) -> bool:
    """Per §'Secret-field rule': field whose terminal segment matches the regex."""
    terminal = field_id.rsplit(".", 1)[-1]
    return bool(_SECRET_RE.search(terminal))

def get_section(section_id: str) -> SectionDescriptor | None:
    for s in SECTIONS:
        if s.section_id == section_id:
            return s
    return None

def domain_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for s in SECTIONS:
        out[s.domain] = out.get(s.domain, 0) + 1
    return out
```

**Verify before drafting the full SECTIONS tuple:** for each section in the §"Section registry" table, the Builder MUST `grep -n "<field_name>:" src/probos/config.py` to confirm each field path exists. The verify-first audit in this prompt covers the 8 `*Config` classes referenced by the new sections (see footer §"Verified Against Codebase"). No `wired=False` stubs in v1.

### Section 2 — `/api/config` router

Create `src/probos/routers/config.py`. Register in `__init__.py` alongside existing routers (same pattern as `cloud_pickers.py`).

```python
"""AD-741: Operator config read/write API for HXI Settings panel."""
from __future__ import annotations
import logging, secrets, time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from probos.config import SystemConfig
from probos.routers.auth import require_crew_scope
from probos.runtime import ProbOSRuntime  # type-only at TYPE_CHECKING; runtime via Depends
from probos.routers._common import get_runtime
from probos.settings.section_registry import (
    SECTIONS, domain_counts, is_secret_field_id,
)

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger(__name__)

# Single-consume CSRF token store, 5-min TTL.
_csrf_tokens: dict[str, float] = {}
_CSRF_TTL_SECONDS = 300

def _issue_csrf() -> str:
    _gc_csrf()
    tok = secrets.token_urlsafe(32)
    _csrf_tokens[tok] = time.monotonic()
    return tok

def _consume_csrf(tok: str) -> bool:
    _gc_csrf()
    return _csrf_tokens.pop(tok, None) is not None

def _gc_csrf() -> None:
    now = time.monotonic()
    stale = [k for k, t in _csrf_tokens.items() if now - t > _CSRF_TTL_SECONDS]
    for k in stale: _csrf_tokens.pop(k, None)

@router.get("", dependencies=[Depends(require_crew_scope)])
async def get_config(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Read-only snapshot of current SystemConfig + section registry + status.

    Secret-named fields are redacted to None per §'Secret-field rule'. The UI
    derives a Configured/Not configured chip from the descriptor + a separate
    `secret_present` map.
    """
    raw = runtime.config.model_dump(mode="json")
    secret_present: dict[str, bool] = {}
    redacted = _redact_secrets(raw, secret_present)
    return {
        "config": redacted,
        "secret_present": secret_present,  # dot-path → bool(original value)
        "sections": [
            {
                "section_id": s.section_id, "label": s.label, "glyph": s.glyph,
                "domain": s.domain, "description": s.description,
                "fields": [
                    {"field_id": f.field_id, "label": f.label, "kind": f.kind,
                     "enum_values": list(f.enum_values), "description": f.description,
                     "hot_reload": f.hot_reload}
                    for f in s.fields
                ],
            }
            for s in SECTIONS
        ],
        "domain_counts": domain_counts(),
        "section_count": len(SECTIONS),
        "config_path": str(getattr(runtime, "config_path", "") or ""),
        "uptime_seconds": round(time.monotonic() - runtime._start_time, 1),
        "csrf_token": _issue_csrf(),
    }

@router.get("/yaml", dependencies=[Depends(require_crew_scope)])
async def get_config_yaml(runtime: Any = Depends(get_runtime)) -> PlainTextResponse:
    """Return the current system.yaml text (for the VIEW YAML button). Secret
    values are replaced with the literal string '<redacted>' before serialize."""
    import yaml
    raw = runtime.config.model_dump(mode="json")
    scrubbed = _scrub_secrets_for_yaml(raw)
    text = yaml.safe_dump(scrubbed, sort_keys=False)
    return PlainTextResponse(text, media_type="text/yaml")

@router.post("", dependencies=[Depends(require_crew_scope)])
async def post_config(req: Request, runtime: Any = Depends(get_runtime)) -> Any:
    csrf = req.headers.get("X-Probos-CSRF", "")
    if not _consume_csrf(csrf):
        return JSONResponse(status_code=403, content={"error": "invalid_csrf"})

    body = await req.json()
    patch = body.get("patch")
    if not isinstance(patch, dict):
        return JSONResponse(status_code=400, content={"error": "patch_required"})

    # Reject any patch that targets a secret-flagged path. The UI MUST surface
    # secrets as read-only chips and never POST them; this is the server-side
    # defense-in-depth check.
    patch_paths = _flatten_dot_paths(patch)
    blocked = [p for p in patch_paths if is_secret_field_id(p)]
    if blocked:
        return JSONResponse(status_code=400, content={
            "error": "secret_field_readonly", "blocked": sorted(blocked),
        })

    # Deep-merge patch onto current dump, then validate via SystemConfig.
    current = runtime.config.model_dump(mode="python")
    merged = _deep_merge(current, patch)
    try:
        new_cfg = SystemConfig(**merged)
    except ValidationError as e:
        return JSONResponse(status_code=422, content={
            "error": "validation_failed",
            "errors": [{"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                       for err in e.errors()],
        })

    # Persist to disk; mark restart required.
    cfg_path = getattr(runtime, "config_path", None)
    if not cfg_path:
        return JSONResponse(status_code=503, content={"error": "config_path_unavailable"})
    try:
        _write_yaml_atomic(cfg_path, new_cfg.model_dump(mode="json"))
    except OSError as ex:
        logger.error("AD-741 config write failed (cfg_path=%s): %s", cfg_path, ex)
        return JSONResponse(status_code=500, content={"error": "write_failed", "detail": str(ex)})

    changed_fields = _diff_paths(current, merged)
    logger.info("AD-741 config write: path=%s changed=%s", cfg_path, changed_fields)
    return {"ok": True, "restart_required": True, "changed_fields": changed_fields}

def _redact_secrets(node: Any, out_presence: dict[str, bool], prefix: str = "") -> Any:
    """Walk dict tree; replace secret-named leaf values with None, record bool in out_presence."""
    if isinstance(node, dict):
        new: dict[str, Any] = {}
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                new[k] = _redact_secrets(v, out_presence, path)
            elif is_secret_field_id(path):
                out_presence[path] = bool(v)
                new[k] = None
            else:
                new[k] = v
        return new
    return node

def _scrub_secrets_for_yaml(node: Any, prefix: str = "") -> Any:
    if isinstance(node, dict):
        new: dict[str, Any] = {}
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                new[k] = _scrub_secrets_for_yaml(v, path)
            elif is_secret_field_id(path) and v:
                new[k] = "<redacted>"
            else:
                new[k] = v
        return new
    return node

def _flatten_dot_paths(node: Any, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.extend(_flatten_dot_paths(v, path))
            else:
                out.append(path)
    return out

def _deep_merge(base: dict, patch: dict) -> dict:
    """Merge patch into copy of base. Patch leaves overwrite. Lists overwrite entirely."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def _diff_paths(before: dict, after: dict, prefix: str = "") -> list[str]:
    """Return dot-paths whose values differ."""
    out: list[str] = []
    keys = set(before) | set(after)
    for k in sorted(keys):
        path = f"{prefix}.{k}" if prefix else k
        bv, av = before.get(k), after.get(k)
        if isinstance(bv, dict) and isinstance(av, dict):
            out.extend(_diff_paths(bv, av, path))
        elif bv != av:
            out.append(path)
    return out

def _write_yaml_atomic(path: str, data: dict) -> None:
    import os, tempfile, yaml
    from pathlib import Path
    p = Path(path)
    header = f"# Edited via HXI {time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    body = yaml.safe_dump(data, sort_keys=False)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(header); fh.write(body)
        os.replace(tmp, p)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
```

**Verify before commit:**
- `from probos.routers._common import get_runtime` — grep this exact symbol. If named differently in this codebase (some routers use `from probos.routers.deps import get_runtime`), use the canonical one. Pre-flight grep: `grep -n "def get_runtime" src/probos/routers/`.
- `runtime.config_path`: confirm the attribute name on `ProbOSRuntime`. Read `__main__.py:_load_config` and the runtime ctor to find the canonical name. If it's not stored on runtime today, the AD adds `self.config_path: str | None = None` set during `_load_config`.

### Section 3 — Register the router

In `src/probos/routers/__init__.py` (or wherever routers are mounted; pattern verified by reading cloud_pickers + system registration):

```python
from probos.routers import config as _config_router
# in the include_router list / app.include_router(_config_router.router) section:
app.include_router(_config_router.router)
```

### Section 4 — HXI Settings panel

Create:
- `ui/src/components/settings/SettingsPanel.tsx` — root overlay (matches `WardRoomPanel` shape)
- `ui/src/components/settings/SettingsSidebar.tsx` — grouped sidebar
- `ui/src/components/settings/SettingsMain.tsx` — main panel rendering per section
- `ui/src/components/settings/SettingsTopBar.tsx` — view tabs + search + VIEW YAML/DISCARD/APPLY/BRIDGE buttons
- `ui/src/components/settings/SettingsStatusBar.tsx` — bottom bar (uptime, in-sync / unsynced)
- `ui/src/components/settings/YamlModal.tsx` — VIEW YAML overlay
- `ui/src/components/settings/icons.tsx` — stroke-SVG glyph mapping (HXI Design Principle #3 — no emoji)

Zustand store extension (`ui/src/store/useStore.ts`):
```ts
// AD-741 Settings panel state
settingsOpen: boolean
openSettings: () => void
closeSettings: () => void
settingsDraft: Record<string, any>   // sparse patch keyed by section.field dot-path
settingsDraftCount: number
setSettingsDraftField: (fieldId: string, value: any) => void
discardSettingsDraft: () => void
settingsSelectedSectionId: string
selectSettingsSection: (id: string) => void
settingsSearch: string
setSettingsSearch: (q: string) => void
```

TopNav (`App.tsx`) gets a new entry between metrics and Bridge:
```tsx
<NavButton label="SETTINGS" active={settingsOpen} onOpen={openSettings} testId="topnav-settings" />
```

In `App.tsx` overlay-render block:
```tsx
{settingsOpen && <SettingsPanel />}
```

**Behavior:**
- On open: fetch `GET /api/config`. Cache `config`, `secret_present`, `sections`, `csrf_token`, `uptime_seconds`, `config_path`.
- Sidebar groups by `domain` in the order: **Core** → **Perception & Voice** → **Identity & Presentation** → **Connectivity** (per §"Architecture decisions" sidebar grouping rule). Header reads `⌘ CONTROL PANEL` and subtitle `${section_count} sections · ${Object.keys(domain_counts).length} domains` (dynamic; never hardcoded).
- A bottom-of-sidebar **Advanced configuration** affordance opens the VIEW YAML modal (read-only in v1).
- A top-of-sidebar one-line note links to Crew Roster for per-agent settings.
- Selecting a section sets `settingsSelectedSectionId`; main panel renders fields. Secret-flagged fields render as a read-only `Configured / Not configured` chip from the `secret_present[field_id]` boolean — never as an editable text input.
- Editing a field calls `setSettingsDraftField`; `settingsDraftCount > 0` enables DISCARD + APPLY buttons and flips status bar to `unsynced (${draftCount} drafts)`.
- APPLY ↵: POST `/api/config` with `{patch: draft}` + header `X-Probos-CSRF: <token>`. On 200: clear draft, show "Restart required" banner with link to `/api/system/shutdown`. On 422: surface inline field errors via `loc`. On 400 `secret_field_readonly`: surface "Secret fields can only be edited in system.yaml directly" toast. On 403 (CSRF expired): re-fetch config to refresh token, prompt operator to re-apply. On 500/503: toast in status bar.
- VIEW YAML: GET `/api/config/yaml`, render in modal (read-only `<pre>`).
- BRIDGE button: `useStore.setState({ settingsOpen: false, bridgeOpen: true })`.
- Search box: substring (case-insensitive) match against section labels AND field labels of all sections (since v1 has no stubs); filters sidebar.
- Status bar: `T+HH:MM:SS` computed in-browser from `uptime_seconds + (Date.now() - openedAt) / 1000`, tick every 1s.

### Section 5 — Tests

**pytest** (`tests/test_ad741_config_api.py`, +9):
1. `GET /api/config` returns sections + config + uptime + csrf_token (real `SystemConfig()` per BF-287).
2. `GET /api/config/yaml` returns valid YAML that round-trips through `yaml.safe_load`.
3. `POST /api/config` missing CSRF → 403.
4. `POST /api/config` valid patch on `system.log_level` → 200 + `restart_required=True` + `changed_fields == ["system.log_level"]`; file on disk contains the new value.
5. `POST /api/config` invalid value (e.g. `system.log_level: "BOGUS"`) → 422 + `errors[0].loc == ["system", "log_level"]`.
6. `POST /api/config` rejected when `config_path` is None → 503 `config_path_unavailable`.
7. CSRF single-consume: second POST with same token → 403.
8. Section registry: `domain_counts()` returns exactly the 4 domain keys from §"Architecture decisions"; `len(SECTIONS) == 11` (10 from AD-741 + 1 perception inserted by AD-733 — assertion gated on AD-733 having committed first or the perception entry being mocked); `get_section("system").fields[0].field_id == "system.name"`.
9. AD-741 source-scan: assert `tests/test_ad741_config_api.py` has zero `MagicMock` imports (BF-287 sentinel).

**pytest** (`tests/test_ad741_section_registry.py`, +3):
1. Every section's `domain` ∈ `{"Core", "Perception & Voice", "Identity & Presentation", "Connectivity"}`.
2. Every section has at least one field with `kind != "readonly"` (every wired section is operator-actionable).
3. Every `field.field_id` resolves to a real attribute path under `SystemConfig()` (use `_resolve_dot_path(SystemConfig(), field_id)` helper; raise on missing). This is the standing-rule guard against phantom field references slipping into the registry between waves.

**pytest** (`tests/test_ad741_secret_redaction.py`, +3 — new file per §"Secret-field rule"):
1. `is_secret_field_id("cloud_pickers.google_drive.client_secret") is True`; `is_secret_field_id("system.log_level") is False`; `is_secret_field_id("auth.crew_scope_token") is True`.
2. `GET /api/config` with a SystemConfig holding `cloud_pickers.google_drive.client_secret = "xyz"` returns `config["cloud_pickers"]["google_drive"]["client_secret"] is None` AND `secret_present["cloud_pickers.google_drive.client_secret"] is True`.
3. `POST /api/config` with patch `{"cloud_pickers": {"google_drive": {"client_secret": "newval"}}}` → 400 `secret_field_readonly` with `blocked == ["cloud_pickers.google_drive.client_secret"]`; file on disk unchanged.

**pytest** (`tests/test_ad741_integration.py`, +2):
1. End-to-end: GET → patch on `system.log_level` → POST → re-GET reflects the change (write to real `tmp_path` yaml; runtime points at it via `config_path`).
2. YAML round-trip via `GET /api/config/yaml` with a secret value set → response text contains `<redacted>`, never the secret literal.

**vitest** (`ui/src/components/settings/__tests__/SettingsPanel.test.tsx`, +6):
1. Sidebar groups render in the order Core → Perception & Voice → Identity & Presentation → Connectivity, with correct domain counts.
2. Selecting a section renders its fields with correct controls (text / readonly / enum buttons / `Configured / Not configured` chip for secret fields).
3. Bottom-of-sidebar "Advanced configuration" affordance is present and opens the VIEW YAML modal on click.
4. Editing a field flips DISCARD + APPLY from disabled to enabled.
5. DISCARD clears the draft + restores disabled state.
6. APPLY POSTs the patch with the CSRF header; 200 response surfaces "Restart required" banner.

**vitest** (`ui/src/components/settings/__tests__/SettingsSidebar.test.tsx`, +3):
1. Search filter matches by section label.
2. Search filter matches by field label across all wired sections (e.g. "log level" surfaces System; "voice model" surfaces Voice).
3. Search filter shows "no results" placeholder when nothing matches.

## Tracking

- PROGRESS.md — add the wave 170 AD-741 entry under Wave 170 in flight.
- DECISIONS.md — append AD-741 entry (config read/write API + Settings panel).
- `docs/development/roadmap.md` — add AD-741 to shipped list with forward markers AD-741-1 / -2 / -3 / -4 / -5 listed.

## Forward markers (file as GitHub issues per wave-closing rule)

- **AD-741-1** — Per-field hot-reload paths (no restart required) for safe fields: `system.log_level` via `logging.getLogger().setLevel`, `federation.enabled` toggle, etc. **Technical trigger:** Captain requests "I changed log level but it didn't take effect without restart."
- **AD-741-2** — Per-section live status pulse + structured editors for collection-shaped fields (e.g. add/remove MCP servers, `peers` list, `cloud_pickers.<provider>` add new provider). **Technical trigger:** Captain asks "how do I add an MCP server from the panel?" v1 shows the list read-only.
- **AD-741-3** — YAML diff preview before APPLY (current VIEW YAML dumps full config; this shows the draft diff). **Technical trigger:** Captain rejects an APPLY because they couldn't see exactly what would change.
- **AD-741-4** — Restart-in-place modal: a guided "saved + restarting now" flow that POSTs `/api/system/shutdown` and reconnects when the runtime comes back up. **Technical trigger:** Captain hits APPLY 3+ times and forgets to restart manually.
- **AD-741-5** — Multi-Captain auth + audit log of who-changed-what. **Technical trigger:** more than one operator with crew_scope_token in production.
- **AD-741-6** — Raw YAML editor mode: turn the read-only VIEW YAML modal into an editable textarea with Pydantic validation on save (POSTs the full document through a new `POST /api/config/yaml` endpoint that runs the same validate→write path as `POST /api/config`). **Technical trigger:** Captain needs to edit a field the registry doesn't surface (one of the 170+ unwired Config classes).
- **AD-741-7** — Per-agent settings deep-link from Settings → Crew Roster → Agent Profile via `location.hash` glue (e.g. `#crew/<agent_id>/profile`). No new panel; just a one-line jump from the Settings sidebar note. **Technical trigger:** Captain says "how do I get to Counselor's settings from here?"

## Acceptance criteria

- All tests pass under `pytest tests/test_ad741_*.py -v -n 0` and `cd ui; npx vitest run`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` passes with delta ≈ +17 over baseline.
- `cd ui; npm run build` succeeds (BF-279 / AD-738b — vitest is NOT enough).
- `/api/config` GET + POST + /yaml all return correct status codes per the test matrix.
- HXI: opening Settings, editing `system.log_level` from INFO to DEBUG, clicking APPLY → 200 response + "Restart required" banner visible; clicking ↻ Restart POSTs `/api/system/shutdown`.
- Sidebar shows `11 sections · 4 domains` (or whatever the registry computes — never hardcoded). Domains render in the order Core → Perception & Voice → Identity & Presentation → Connectivity.
- Secret fields render as `Configured / Not configured` chips, NEVER as editable inputs; POST that tries to set one returns 400 `secret_field_readonly`.
- "Advanced configuration — Edit system.yaml directly" affordance is present at the bottom of the sidebar and opens the VIEW YAML modal.
- VIEW YAML modal returns valid round-trippable YAML with secret values replaced by `"<redacted>"`.
- 0 emoji in the new UI files (`grep -rE "[\x{1F300}-\x{1FAFF}]" ui/src/components/settings/` returns nothing). All glyphs are inline stroke SVG per HXI Design Principle #3.
- 0 new pip deps (`yaml` already resident via `pyyaml` in `pyproject.toml`); 0 new npm deps.
- License posture clean: no third-party code absorbed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## What this does NOT change

- Does NOT mutate `runtime.config` in-process (every field is restart_required v1).
- Does NOT add CSRF middleware globally — token is endpoint-scoped.
- Does NOT add multi-Captain auth.
- Does NOT replace any existing config field.
- Does NOT add new top-level config sections (the Perception section is added by AD-733 in the same wave).
- Does NOT add tab routing — Settings is an overlay panel like every other HXI panel.
- Does NOT touch `system.yaml`'s structure — only its persistence path.

## Verified Against Codebase (2026-05-17, revision pass)

```
grep -n "api/config" src/probos/routers/    # 0 hits — endpoint does not exist yet
grep -n "class SystemConfig" src/probos/config.py
  4185: class SystemConfig(BaseModel):
grep -n "require_crew_scope" src/probos/routers/auth.py
  40: async def require_crew_scope(
grep -n "_start_time" src/probos/runtime.py
  757: self._start_time: float = time.monotonic()
  870: self._start_time_wall: float = time.time()
grep -n "WardRoomPanel" ui/src/App.tsx
  17: import { WardRoomPanel } from './components/wardroom';
  176: <WardRoomPanel />
grep -n "openWardRoom" ui/src/App.tsx
  95: const openWardRoom = useStore(s => s.openWardRoom);
grep -n "AgentProfilePanel" ui/src/components/profile/
  AgentProfilePanel.tsx exists (per workspace tree) — confirms per-agent settings surface is real.
```

### Audit for the 8 new field surfaces (revision pass)

| # | Section | Backing class | config.py line | Field paths verified |
|---|---|---|---|---|
| 1 | `system` | `SystemConfig` | 4185 | `system.name`, `system.version`, `system.log_level` — pre-verified prior pass. |
| 2 | `llm_tiers` | `SystemConfig` (top-level `llm_*` fields per AD-732) | 4185 | Per-tier field names follow the `llm_<kind>_<tier>` convention (AD-732 + AD-730-3). Builder MUST grep `llm_base_url_vision`, `llm_model_image_gen`, etc. in `config.py` before locking the registry; if any tier is missing a field, that tier renders only the fields that exist (honest-degrade). |
| 3 | `memory` | `MemoryConfig` | 721 | `max_episodes`, `relevance_threshold`, `agent_recall_threshold`, `embedding_model` — ALL verified present (read lines 721-760). Note: prior draft used `episodic_max_episodes` / `episodic_retention_days` / `recall_top_k` which are **phantom** — corrected in revision. |
| 4 | `perception` | `PerceptionConfig` (added by AD-733) | (added by AD-733) | Wiring inserted by AD-733 in the same wave; this AD only reserves the `perception` section id. |
| 5 | `voice` | `TTSConfig`, `LipSyncConfig` | 1940, 1900 | `tts.enabled`, `tts.backend`, `tts.voice_model`, `tts.length_scale`, `tts.noise_scale` — verified present in TTSConfig body. `lipsync.backend`, `lipsync.binary_path` — Builder pre-flight grep against LipSyncConfig body to confirm exact field names. |
| 6 | `avatars` | `AvatarsConfig` | 1207 | `avatars.enabled`, `avatars.avatars_dir`, `avatars.max_vrm_size_bytes`, `avatars.renderer_enabled`, `avatars.fallback_to_parametric_on_error` — verified present (read lines 1207-1240). |
| 7 | `ward_room` | `WardRoomConfig`, `WardRoomHebbianConfig` | 3147, 2833 | `ward_room.enabled`, `ward_room.max_thread_posts`, `ward_room.dm_exchange_limit`, `ward_room.retention_days` — verified present (read lines 3147-3170). `ward_room_hebbian.enabled` — verified at line 2833. |
| 8 | `federation` | `FederationConfig` | 2084 | `federation.enabled`, `federation.node_id`, `federation.bind_address` — verified present (read lines 2084-2110). |
| 9 | `channels` | `DiscordConfig`, `SlackConfig`, `WebhookConfig` | 3355, 3367, 3378 | Classes verified present. Exact field names per provider (`webhook_url`, `bot_token`, `signing_secret`, etc.) — Builder pre-flight grep against each class body to confirm. Token / secret fields auto-redacted by §"Secret-field rule" regex. |
| 10 | `cloud_pickers` | `CloudPickersConfig`, `CloudPickerProviderConfig` | 1879, 1862 | `cloud_pickers.enabled`, per-provider `enabled` + `client_id` verified present (read lines 1862-1900). `client_secret` is secret-flagged. |
| 11 | `tools` | `BrowserToolConfig`, `MCPConfig` | 1018, 2802 | `browser_tool.enabled`, `browser_tool.headless`, `browser_tool.session_max_duration_seconds` — verified present. `mcp.enabled`, `mcp.servers` (list) — verified present. |

**Sections dropped from Captain's spec during verify-first:**

- `◉ Wake Word` (`WakeWordConfig`): **does NOT exist** in HEAD. `grep -n 'class WakeWord\|hotword\|porcupine\|wake_word' src/probos/config.py` returns nothing. Wake-word capability is not currently a config surface. Captain's spec asked to expose `WakeWordConfig.enabled / model / sensitivity`; none of these fields exist. Dropped from v1; if wake-word lands in a future AD it adds its own section via the registry.

**Phantom field corrections applied:**

- `memory.episodic_max_episodes` → `memory.max_episodes` (real field at line 723).
- `memory.episodic_retention_days` → not present in HEAD; replaced with `memory.relevance_threshold` (real, line 728).
- `memory.recall_top_k` → not present in HEAD; replaced with `memory.agent_recall_threshold` (real, line 734).
- `avatars.expression_weights / telemetry_rate` (per Captain spec): not direct AvatarsConfig fields. Telemetry rate lives in `AvatarTelemetryConfig` (line 1569) — out of v1 scope; expression weights are per-VRM, not global config. Replaced with `enabled / avatars_dir / max_vrm_size_bytes / renderer_enabled / fallback_to_parametric_on_error`.
- `ward_room.post_budget / default_channel` (per Captain spec): not present in HEAD. Replaced with real fields `enabled / max_thread_posts / dm_exchange_limit / retention_days`.
- `ward_room.hebbian_weights toggle` (per Captain spec): lives in `WardRoomHebbianConfig.enabled` (separate top-level config block, not nested under WardRoomConfig). Surfaced as `ward_room_hebbian.enabled` in the registry.
