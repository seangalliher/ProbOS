"""AD-812: natural-language → ScheduleSpec parser.

Pure function. Translates operator English into a dataclass the
slash-command handler can hand to PersistentTaskStore.create_task(...).

Design notes
------------
- Fast-tier LLM is the primary parse engine. Tight JSON-output prompt.
- Regex safety net handles the cheap "in N minutes/hours" case without
  paying for an LLM call.
- Honest-degrade: if the LLM is unavailable and regex doesn't match,
  return ScheduleSpec(kind="error", ...). The slash-command surfaces
  the error to the operator verbatim — no silent fallback.
- No new dependencies. croniter (MIT, already in deps) is the only
  third-party touched, and only to validate generated cron exprs.

Wave: 812. Issue: #736.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_VALID_KINDS = ("once", "interval", "cron", "error")


@dataclass(frozen=True)
class ScheduleSpec:
    """Parsed schedule. Maps directly onto PersistentTaskStore.create_task."""

    kind: Literal["once", "interval", "cron", "error"]
    intent_text: str = ""
    execute_at: float | None = None
    interval_seconds: float | None = None
    cron_expr: str | None = None
    channel_id: str | None = None
    max_runs: int | None = None
    reason: str = ""


_SYSTEM_PROMPT = """You translate natural-language scheduling requests into JSON.

OUTPUT FORMAT (strict JSON, no prose, no markdown fences):
{
  "kind": "once" | "interval" | "cron",
  "intent_text": "<the action to perform, without the time/channel words>",
  "execute_at_iso": "<ISO-8601 datetime>" or null,
  "interval_seconds": <number> or null,
  "cron_expr": "<5-field cron>" or null,
  "channel": "<lowercase channel name or null>",
  "max_runs": <number> or null
}

RULES:
- "kind=once" → execute_at_iso set, others null.
- "kind=interval" → interval_seconds set, others null.
- "kind=cron" → cron_expr set, others null. Use standard 5-field cron (m h dom mon dow).
- Channel words ("to telegram", "via slack", "on discord") populate "channel".
  Otherwise channel is null. Do NOT invent channels.
- "intent_text" is the verb-phrase the operator wants executed, with the
  scheduling and channel words stripped. e.g. "every weekday at 7am send my
  LinkedIn metrics to Telegram" → intent_text="send my LinkedIn metrics".
- "every weekday" → cron_expr="0 H * * 1-5" with H from the parsed hour.
- "every Monday" → cron_expr with dow=1.
- Treat "now" as the current time.
- If the request is ambiguous, pick the most natural interpretation.
- Never output prose. Never wrap in ```json fences. Output the JSON object only.
"""


def _regex_relative(text: str, now: float) -> ScheduleSpec | None:
    """Cheap safety net for 'in N minutes/hours/days' phrasings."""
    m = re.search(
        r"\bin\s+(\d+)\s+(second|minute|hour|day)s?\b",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]
    intent = re.sub(
        r"\bin\s+\d+\s+(second|minute|hour|day)s?\b",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    if not intent:
        return None
    return ScheduleSpec(
        kind="once",
        intent_text=intent,
        execute_at=now + n * seconds,
    )


def _channel_to_id(name: str | None) -> str | None:
    """Map a free-form channel name to a `<adapter>:default` id."""
    if not name:
        return None
    n = name.strip().lower()
    known = {"telegram", "slack", "discord", "matrix", "teams", "gmail"}
    if n in known:
        return f"{n}:default"
    return None


def _validate_cron(expr: str) -> bool:
    try:
        from croniter import croniter

        return croniter.is_valid(expr)
    except Exception:
        return False


async def parse_nl_schedule(
    text: str,
    llm_client: "BaseLLMClient | None" = None,
    *,
    now: float | None = None,
) -> ScheduleSpec:
    """Translate natural language into a ScheduleSpec.

    Order of operations:
      1. Regex safety net for "in N minutes/hours/days" — no LLM call.
      2. Fast-tier LLM with a strict JSON-output prompt.
      3. Honest-degrade to ScheduleSpec(kind="error", reason=...)
         when both fail. The caller surfaces the reason verbatim.
    """
    if not text or not text.strip():
        return ScheduleSpec(kind="error", reason="empty input")

    clock = time.time() if now is None else now

    fast = _regex_relative(text, clock)
    if fast is not None:
        logger.debug("AD-812: regex fast-path matched: %r -> %s", text, fast)
        return fast

    if llm_client is None:
        return ScheduleSpec(
            kind="error",
            reason="LLM unavailable and request did not match the regex fast-path",
        )

    from probos.types import LLMRequest

    try:
        resp = await llm_client.complete(
            LLMRequest(
                prompt=text,
                system_prompt=_SYSTEM_PROMPT,
                tier="fast",
                max_tokens=256,
                temperature=0.0,
            )
        )
    except Exception as exc:
        logger.warning("AD-812: LLM parse failed (%s); returning error spec", exc)
        return ScheduleSpec(kind="error", reason=f"LLM parse failed: {exc}")

    raw = getattr(resp, "content", None) or getattr(resp, "text", "") or ""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
    except Exception as exc:
        logger.warning("AD-812: LLM output not JSON (%s): %r", exc, raw[:200])
        return ScheduleSpec(kind="error", reason="LLM returned non-JSON output")

    kind = obj.get("kind")
    if kind not in ("once", "interval", "cron"):
        return ScheduleSpec(kind="error", reason=f"invalid kind {kind!r}")

    intent_text = (obj.get("intent_text") or "").strip()
    if not intent_text:
        return ScheduleSpec(kind="error", reason="intent_text missing")

    channel_id = _channel_to_id(obj.get("channel"))
    max_runs = obj.get("max_runs")
    if max_runs is not None and not isinstance(max_runs, int):
        max_runs = None

    if kind == "once":
        iso = obj.get("execute_at_iso")
        if not iso:
            return ScheduleSpec(kind="error", reason="execute_at_iso missing for kind=once")
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            execute_at = dt.timestamp()
        except Exception as exc:
            return ScheduleSpec(kind="error", reason=f"invalid execute_at_iso: {exc}")
        if execute_at <= clock:
            return ScheduleSpec(kind="error", reason="execute_at is in the past")
        return ScheduleSpec(
            kind="once",
            intent_text=intent_text,
            execute_at=execute_at,
            channel_id=channel_id,
            max_runs=max_runs,
        )

    if kind == "interval":
        secs = obj.get("interval_seconds")
        if not isinstance(secs, (int, float)) or secs <= 0:
            return ScheduleSpec(kind="error", reason="interval_seconds missing or non-positive")
        return ScheduleSpec(
            kind="interval",
            intent_text=intent_text,
            interval_seconds=float(secs),
            channel_id=channel_id,
            max_runs=max_runs,
        )

    # kind == "cron"
    expr = obj.get("cron_expr")
    if not expr or not _validate_cron(expr):
        return ScheduleSpec(kind="error", reason=f"invalid cron_expr: {expr!r}")
    return ScheduleSpec(
        kind="cron",
        intent_text=intent_text,
        cron_expr=expr,
        channel_id=channel_id,
        max_runs=max_runs,
    )
