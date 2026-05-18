"""AD-741: ``/api/config`` — operator config read/write API.

Three endpoints:

- ``GET /api/config`` returns the live :class:`SystemConfig` snapshot
  (secrets redacted), the section-descriptor registry, uptime, and a
  single-consume CSRF token for the subsequent POST.
- ``GET /api/config/yaml`` returns the current YAML text with secret
  values replaced by ``"<redacted>"``.
- ``POST /api/config`` accepts a sparse patch dict, validates it by
  constructing a fresh :class:`SystemConfig`, persists it to disk, and
  returns ``restart_required=True``. Secret-flagged paths are rejected
  with 400 ``secret_field_readonly`` — defense-in-depth alongside the
  UI's chip-only render.

CSRF token store is in-process; suitable for the single-Captain default
posture. AD-741-5 forward marker covers multi-Captain audit logging.
"""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from probos.config import SystemConfig
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.settings.section_registry import (
    SECTIONS,
    domain_counts,
    domain_render_order,
    is_secret_field_id,
)

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger(__name__)

# Single-consume CSRF token store, 5-min TTL.
_csrf_tokens: dict[str, float] = {}
_CSRF_TTL_SECONDS = 300


def _gc_csrf() -> None:
    now = time.monotonic()
    stale = [k for k, t in _csrf_tokens.items() if now - t > _CSRF_TTL_SECONDS]
    for k in stale:
        _csrf_tokens.pop(k, None)


def _issue_csrf() -> str:
    _gc_csrf()
    tok = secrets.token_urlsafe(32)
    _csrf_tokens[tok] = time.monotonic()
    return tok


def _consume_csrf(tok: str) -> bool:
    _gc_csrf()
    return _csrf_tokens.pop(tok, None) is not None


def _redact_secrets(node: Any, out_presence: dict[str, bool], prefix: str = "") -> Any:
    """Walk a dict tree; replace secret-named leaf values with None.

    Records ``out_presence[dot_path] = bool(original_value)`` so the UI
    can render a ``Configured`` / ``Not configured`` chip without seeing
    the secret value itself.
    """
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
    """Merge ``patch`` into a copy of ``base``. Lists overwrite entirely."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _diff_paths(before: dict, after: dict, prefix: str = "") -> list[str]:
    """Return the dot-paths whose values differ between two snapshots."""
    out: list[str] = []
    keys = set(before) | set(after)
    for k in sorted(keys):
        path = f"{prefix}.{k}" if prefix else k
        bv = before.get(k)
        av = after.get(k)
        if isinstance(bv, dict) and isinstance(av, dict):
            out.extend(_diff_paths(bv, av, path))
        elif bv != av:
            out.append(path)
    return out


def _write_yaml_atomic(path: str, data: dict) -> None:
    p = Path(path)
    header = f"# Edited via HXI {time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    body = yaml.safe_dump(data, sort_keys=False)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(body)
        os.replace(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _section_payload() -> list[dict[str, Any]]:
    return [
        {
            "section_id": s.section_id,
            "label": s.label,
            "glyph": s.glyph,
            "domain": s.domain,
            "description": s.description,
            "fields": [
                {
                    "field_id": f.field_id,
                    "label": f.label,
                    "kind": f.kind,
                    "enum_values": list(f.enum_values),
                    "description": f.description,
                    "hot_reload": f.hot_reload,
                }
                for f in s.fields
            ],
        }
        for s in SECTIONS
    ]


@router.get("", dependencies=[Depends(require_crew_scope)])
async def get_config(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return a read-only snapshot of the live config + section registry."""
    raw = runtime.config.model_dump(mode="json")
    secret_present: dict[str, bool] = {}
    redacted = _redact_secrets(raw, secret_present)
    start = getattr(runtime, "_start_time", time.monotonic())
    return {
        "config": redacted,
        "secret_present": secret_present,
        "sections": _section_payload(),
        "domain_counts": domain_counts(),
        "domain_order": list(domain_render_order()),
        "section_count": len(SECTIONS),
        "config_path": str(getattr(runtime, "config_path", "") or ""),
        "uptime_seconds": round(time.monotonic() - start, 1),
        "csrf_token": _issue_csrf(),
    }


@router.get("/yaml", dependencies=[Depends(require_crew_scope)])
async def get_config_yaml(runtime: Any = Depends(get_runtime)) -> PlainTextResponse:
    """Return the current ``system.yaml`` text with secrets scrubbed."""
    raw = runtime.config.model_dump(mode="json")
    scrubbed = _scrub_secrets_for_yaml(raw)
    text = yaml.safe_dump(scrubbed, sort_keys=False)
    return PlainTextResponse(text, media_type="text/yaml")


@router.post("", dependencies=[Depends(require_crew_scope)])
async def post_config(req: Request, runtime: Any = Depends(get_runtime)) -> Any:
    """Validate a draft patch, persist it to disk, and report restart-required."""
    csrf = req.headers.get("X-Probos-CSRF", "")
    if not _consume_csrf(csrf):
        return JSONResponse(status_code=403, content={"error": "invalid_csrf"})

    try:
        body = await req.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid_json"})
    patch = body.get("patch") if isinstance(body, dict) else None
    if not isinstance(patch, dict):
        return JSONResponse(status_code=400, content={"error": "patch_required"})

    # Defense in depth: reject any patch that targets a secret-flagged path.
    patch_paths = _flatten_dot_paths(patch)
    blocked = [p for p in patch_paths if is_secret_field_id(p)]
    if blocked:
        logger.warning(
            "AD-741 rejected secret-field patch (blocked=%s); secrets are "
            "edited via system.yaml or the OAuth vault, not the HXI.",
            sorted(blocked),
        )
        return JSONResponse(
            status_code=400,
            content={"error": "secret_field_readonly", "blocked": sorted(blocked)},
        )

    current = runtime.config.model_dump(mode="python")
    merged = _deep_merge(current, patch)
    try:
        new_cfg = SystemConfig(**merged)
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_failed",
                "errors": [
                    {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                    for err in e.errors()
                ],
            },
        )

    cfg_path = getattr(runtime, "config_path", None)
    if not cfg_path:
        return JSONResponse(status_code=503, content={"error": "config_path_unavailable"})

    try:
        _write_yaml_atomic(cfg_path, new_cfg.model_dump(mode="json"))
    except OSError as ex:
        logger.error(
            "AD-741 config write failed (cfg_path=%s): %s; "
            "in-memory runtime config unchanged.",
            cfg_path,
            ex,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "write_failed", "detail": str(ex)},
        )

    changed_fields = _diff_paths(current, merged)
    logger.info(
        "AD-741 config write: path=%s changed=%s; restart required to take effect.",
        cfg_path,
        changed_fields,
    )
    return {"ok": True, "restart_required": True, "changed_fields": changed_fields}
