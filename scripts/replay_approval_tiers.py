"""AD-1356 (#1722), acceptance 1: replay filed agent-work approvals against the tool-effect table, read-only.

Reads a copy of ``capability_requests.db`` (never the live file, which the Captain's vessel owns), opened read-only, and
says for each ``action`` request filed in the window what AD-1356 S1 to S4 now decide for it. Writes a JSON receipt.

    python -P scripts/replay_approval_tiers.py --db COPY --since EPOCH --until EPOCH [--reads-unconfined]
        [--routine auto|chief|captain] [--elevated auto|chief|captain] [--registered-ids ID,ID] [--receipt PATH]

Buckets: ``<tier>_<decider>`` for an agent-work call (``*_auto``: the run calls the tool directly; ``*_chief``: AD-1213's
route decides it; ``*_captain``: the Captain does); ``recovery_read`` (S1.3's gate admits it); ``unregistered`` (a
non-``mcp:`` id the table does not list and ``--registered-ids`` does not hold: S1.1 refuses it and nothing is filed);
``unlisted`` (such an id, with no ``--registered-ids``: refused or critical, which the script cannot tell);
``input_error`` (a repair whose brief carries a ``<tool>_invalid:`` mark, which S1.2 no longer files);
``repair_captain``; ``other_captain``.

``--registered-ids`` names the tool ids that exist on the vessel. It is read only for a non-``mcp:`` id the table does
not list: an id in it is critical, the Captain's. A listed id is taken as registered; an ``mcp:`` id is critical.

Offline limits: no tool registry, so a non-``mcp:`` id the table does not list is split only by ``--registered-ids``
and an ``mcp:`` tool is critical; no ontology, so a ``*_chief`` request filed by a chief, or by crew with no
same-department chief, goes live to the First Officer under a live delegation, else the Captain; the recovery-read test
does not check the workspace root. Exit 0 with a receipt; 2, with no receipt written, when the copy is missing, an
argument is invalid, an epoch is not finite, or ``--receipt`` names the copy or one of its SQLite sidecars. A copy that
changes while it is read raises.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from probos.capability_request import agent_work_call, repair_action, validate_action_payload
from probos.config_models.experience import ApprovalInboxConfig
from probos.execution.workspace_results import is_workspace_result_path
from probos.tools.effect_tiers import (
    DECIDER_AUTO,
    DECIDER_CAPTAIN,
    DECIDER_CHIEF,
    ELEVATED_TOOL_IDS,
    ROUTINE_TOOL_IDS,
    TIER_CRITICAL,
    tier_decider,
    tool_tier,
)
from probos.tools.protocol import is_caller_input_error

DEFAULT_RECEIPT = Path("logs/gates/ad-1356-replay.receipt.json")
_DECIDERS = (DECIDER_AUTO, DECIDER_CHIEF, DECIDER_CAPTAIN)
_INPUT_MARK = re.compile(r"\b([a-z0-9_]+)_invalid:[a-z0-9_]+")
_ROWS = (
    "SELECT id, agent_id, kind, work_item_id, created_at, payload FROM capability_requests "
    "WHERE kind = 'action' AND created_at >= ? AND created_at < ? ORDER BY created_at, id"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recovery_read(tool_id: str, params: dict[str, Any]) -> bool:
    """S1.3's test without the workspace root: a read_file of an absolute path with no ``..`` naming the result
    directory."""
    raw = params.get("path") if tool_id == "read_file" else None
    if type(raw) is not str:
        return False
    path = Path(raw)
    return path.is_absolute() and ".." not in path.parts and is_workspace_result_path(path)


def bucket(
    req: Any, *, reads_confined: bool, routine: str, elevated: str, registered: frozenset[str] | None = None,
) -> tuple[str, str]:
    """``(bucket, tool id)`` for one ``action`` request; ``registered`` is ``--registered-ids``, None when absent."""
    call = agent_work_call(req)
    if call is not None:
        tool_id = call["tool_id"]
        if _recovery_read(tool_id, call["params"]):
            return "recovery_read", tool_id
        if tool_id not in ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS and not tool_id.startswith("mcp:"):
            if registered is None:
                return "unlisted", tool_id
            if tool_id not in registered:
                return "unregistered", tool_id
        tier = TIER_CRITICAL if tool_id.startswith("mcp:") else tool_tier(tool_id, reads_confined=reads_confined)
        return f"{tier}_{tier_decider(tier, routine=routine, elevated=elevated)}", tool_id
    payload = req.payload if isinstance(req.payload, dict) else {}
    tool_id = str(payload.get("tool_id", ""))
    if repair_action(req) is not None:
        match = _INPUT_MARK.search(str(payload["params"].get("brief", "")))
        if match is not None and is_caller_input_error(match.group(1), match.group(0)):
            return "input_error", tool_id
        return "repair_captain", tool_id
    return "other_captain", tool_id


def replay(
    db: Path, *, since: float, until: float, reads_confined: bool, routine: str, elevated: str,
    registered: frozenset[str] | None = None,
) -> dict[str, Any]:
    """The receipt for the ``action`` requests in ``[since, until)``; the copy's bytes are hashed before and after."""
    before = _sha256(db)
    with contextlib.closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute(_ROWS, (since, until)).fetchall()
    if _sha256(db) != before:
        raise RuntimeError("replay_approval_tiers: the database copy changed while it was read")
    entries: list[dict[str, Any]] = []
    for request_id, agent_id, kind, work_item_id, created_at, raw in rows:
        try:
            payload = validate_action_payload(json.loads(raw)) if raw else None
        except ValueError:
            payload = None
        req = SimpleNamespace(kind=kind, payload=payload, work_item_id=work_item_id)
        name, tool_id = bucket(
            req, reads_confined=reads_confined, routine=routine, elevated=elevated, registered=registered,
        )
        entries.append({"id": request_id, "agent_id": agent_id, "created_at": created_at, "tool_id": tool_id, "bucket": name})
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["bucket"]] = counts.get(entry["bucket"], 0) + 1
    return {
        "v": 1, "ad": "AD-1356", "db": str(db), "db_sha256": before, "since": since, "until": until,
        "reads_confined": reads_confined,
        "registered_ids": None if registered is None else sorted(registered),
        "deciders": {"routine": routine, "elevated": elevated, "critical": DECIDER_CAPTAIN},
        "requests": len(entries), "counts": dict(sorted(counts.items())),
        "captain_routed": sum(n for name, n in counts.items() if name.endswith("_captain")),
        "chain_decided": sum(n for name, n in counts.items() if name.endswith("_chief")),
        "unlisted_tool_ids": sorted({entry["tool_id"] for entry in entries if entry["bucket"] == "unlisted"}),
        "unregistered_tool_ids": sorted({entry["tool_id"] for entry in entries if entry["bucket"] == "unregistered"}),
        "rows": entries,
    }


def _names_the_copy(receipt: Path, db: Path) -> bool:
    """True when ``receipt`` is the copy or one of its SQLite sidecars: by resolved path (case folded where the host
    folds case) or, when both exist, by file identity (a hard link)."""
    target = os.path.normcase(os.path.realpath(receipt))
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = db.with_name(db.name + suffix)
        if target == os.path.normcase(os.path.realpath(candidate)):
            return True
        if receipt.exists() and candidate.exists() and os.path.samefile(receipt, candidate):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    defaults = ApprovalInboxConfig()
    parser = argparse.ArgumentParser(description="AD-1356: replay filed agent-work approvals, read-only")
    parser.add_argument("--db", required=True, type=Path, help="a COPY of capability_requests.db")
    parser.add_argument("--since", required=True, type=float, help="epoch seconds, inclusive")
    parser.add_argument("--until", required=True, type=float, help="epoch seconds, exclusive")
    parser.add_argument("--reads-unconfined", action="store_true", help="as if security_infra.read_roots were unset")
    parser.add_argument("--routine", choices=_DECIDERS, default=defaults.agent_work_routine_decider)
    parser.add_argument("--elevated", choices=_DECIDERS, default=defaults.agent_work_elevated_decider)
    parser.add_argument(
        "--registered-ids", default=None,
        help="comma-separated tool ids that exist on the vessel; read only for an id the table does not list",
    )
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"replay_approval_tiers: no database at {args.db}", file=sys.stderr)
        return 2
    if not (math.isfinite(args.since) and math.isfinite(args.until)):
        print("replay_approval_tiers: --since and --until must be finite epoch seconds", file=sys.stderr)
        return 2
    if _names_the_copy(args.receipt, args.db):
        print(f"replay_approval_tiers: --receipt {args.receipt} is the copy or one of its sidecars", file=sys.stderr)
        return 2
    reads_confined = not args.reads_unconfined
    registered = (
        None if args.registered_ids is None
        else frozenset(part.strip() for part in args.registered_ids.split(",") if part.strip())
    )
    receipt = replay(
        args.db, since=args.since, until=args.until, reads_confined=reads_confined,
        routine=args.routine, elevated=args.elevated, registered=registered,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"replay_approval_tiers: {receipt['requests']} requests; Captain-routed {receipt['captain_routed']}; "
        f"chain {receipt['chain_decided']}; receipt {args.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
