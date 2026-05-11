"""AD-724: Lightweight sanity gate for DM one-shot replies.

Migrates three existing regex cleanups (BF-120 markdown strip, BF-119
challenge parse, AD-572 move parse) into a named, individually-testable
module, and adds three log-only quality checks (length floor, repetition,
orphaned tags).

Tier-2 log-and-degrade. The gate NEVER blocks a reply. Rejections log a
warning and the original text is shipped unchanged. Strict mode is a
forward marker (AD-724-1+).

State (per-agent last-reply cache for repetition detection) is in-memory
and lost on restart. Persistence is out of scope.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# --- Compiled regexes ---
# BF-120: markdown wrapper around structured tags.
_MARKDOWN_OPEN_RE = re.compile(r"[`*]{1,3}\[")
_MARKDOWN_CLOSE_RE = re.compile(r"\][`*]{1,3}")

# BF-119: well-formed challenge tag.
_CHALLENGE_RE = re.compile(r"\[CHALLENGE\s+@(\w+)\s+(\w+)\]")
_CHALLENGE_STRIP_RE = re.compile(r"\[CHALLENGE\s+@\w+\s+\w+\]")

# AD-572: well-formed move tag.
_MOVE_RE = re.compile(r"\[MOVE\s+(\S+)\]")
_MOVE_STRIP_RE = re.compile(r"\[MOVE\s+\S+\]")

# AD-724: malformed tags (open bracket + keyword, but missing close bracket
# OR missing value). These do NOT match the well-formed regexes above.
_ORPHANED_CHALLENGE_RE = re.compile(r"\[CHALLENGE\b(?![^\[\]]*\])")
_ORPHANED_MOVE_RE = re.compile(r"\[MOVE\b(?![^\[\]]*\S+\s*\])")
# A pair of square brackets containing nothing but whitespace, or an
# unmatched single open/close bracket on a line.
_EMPTY_BRACKETS_RE = re.compile(r"\[\s*\]")


class DmSanityGateConfig(BaseModel):
    """AD-724: configuration for the DM sanity gate.

    Default-ON because the three migrated behaviors (BF-120, BF-119, AD-572)
    are already running unconditionally in HEAD. Disabling this config
    DISABLES those migrations too — see warning in `process()`.
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100


@dataclass
class DmSanityResult:
    """Outcome of one `DmSanityGate.process()` call.

    `cleaned_text` is what the caller should use for downstream parsing
    and Captain-visible output. `warnings` is a list of `(check_name, detail)`
    tuples that the caller MAY surface (currently logged only).
    """

    cleaned_text: str
    warnings: list[tuple[str, str]] = field(default_factory=list)


class DmSanityGate:
    """AD-724: synchronous, in-process sanity gate for DM one-shot replies.

    Stateful (per-agent last-reply cache). Construct once per runtime.
    Thread-safety: caller responsibility. The chat router calls this
    inside the FastAPI request handler, which is already serialized per
    request by Starlette.
    """

    def __init__(self, config: DmSanityGateConfig | None = None) -> None:
        self.config = config or DmSanityGateConfig()
        # agent_id -> last cleaned reply text. Bounded by agent population.
        self._last_reply_by_agent: dict[str, str] = {}

    # --- Migrated regex helpers (behavior-preserving) ---

    def strip_markdown(self, text: str) -> str:
        """BF-120: strip markdown wrappers from structured tags.

        Identical behavior to the inline `re.sub` pair at
        `routers/agents.py:944-945` (HEAD).
        """
        if not text:
            return text
        text = _MARKDOWN_OPEN_RE.sub("[", text)
        text = _MARKDOWN_CLOSE_RE.sub("]", text)
        return text

    def extract_challenge(self, text: str) -> tuple[str, str] | None:
        """BF-119: extract `(target_callsign, game_type)` from a challenge tag.

        Returns ``None`` if no well-formed `[CHALLENGE @x y]` tag is present.
        """
        if not text:
            return None
        m = _CHALLENGE_RE.search(text)
        if not m:
            return None
        return m.group(1), m.group(2)

    def strip_challenge(self, text: str) -> str:
        """BF-119: remove `[CHALLENGE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1003` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _CHALLENGE_STRIP_RE.sub("", text).strip()

    def extract_move(self, text: str) -> str | None:
        """AD-572: extract the move position from a `[MOVE pos]` tag.

        Returns ``None`` if no well-formed move tag is present.
        """
        if not text:
            return None
        m = _MOVE_RE.search(text)
        if not m:
            return None
        return m.group(1)

    def strip_move(self, text: str) -> str:
        """AD-572: remove `[MOVE ...]` tags from Captain-visible text.

        Mirrors the inline `re.sub` at `routers/agents.py:1041` (HEAD),
        including the trailing `.strip()`.
        """
        if not text:
            return text
        return _MOVE_STRIP_RE.sub("", text).strip()

    # --- New checks (Tier-2 log-and-degrade) ---

    def check_length_floor(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """Return a `(check_name, detail)` warning if `text.strip()` is shorter
        than `config.length_floor`, else ``None``. Logs at WARNING level.
        """
        stripped_len = len(text.strip())
        if stripped_len < self.config.length_floor:
            detail = (
                f"reply length {stripped_len} < floor {self.config.length_floor}"
            )
            logger.warning(
                "AD-724: DM length floor breached for agent %s: %s",
                agent_id, detail,
            )
            return ("length_floor", detail)
        return None

    def check_repetition(self, agent_id: str, text: str) -> tuple[str, str] | None:
        """Return a warning if the first `repetition_prefix_chars` of `text`
        exactly match the previous reply for this agent. Logs at WARNING.

        Does NOT update the cache — the caller does that via `process()`
        after all checks have run.
        """
        prev = self._last_reply_by_agent.get(agent_id, "")
        n = self.config.repetition_prefix_chars
        if not prev or not text:
            return None
        if text[:n] == prev[:n]:
            detail = (
                f"first {n} chars match previous reply (possible decoder loop)"
            )
            logger.warning(
                "AD-724: DM repetition detected for agent %s: %s",
                agent_id, detail,
            )
            return ("repetition", detail)
        return None

    def check_orphaned_tags(self, text: str) -> tuple[str, str] | None:
        """Return a warning if the text contains a malformed structured tag:
        a `[CHALLENGE` or `[MOVE` without a closing bracket, or `[]`.
        Logs at WARNING.
        """
        if not text:
            return None
        if _ORPHANED_CHALLENGE_RE.search(text):
            detail = "orphaned [CHALLENGE — missing closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _ORPHANED_MOVE_RE.search(text):
            detail = "orphaned [MOVE — missing value or closing bracket"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        if _EMPTY_BRACKETS_RE.search(text):
            detail = "empty []"
            logger.warning("AD-724: DM orphaned tag: %s", detail)
            return ("orphaned_tag", detail)
        return None

    # --- Orchestration entry point ---

    def process(self, agent_id: str, text: str) -> DmSanityResult:
        """Run the full gate. Returns a `DmSanityResult` carrying the cleaned
        text and any non-fatal warnings.

        If the config is disabled, the markdown strip still runs (it is a
        pure-string normalization with no behavioral risk) but the three
        new checks are skipped. This preserves the BF-120 migration
        invariant when an operator disables the gate.

        Order:
            1. strip_markdown (BF-120 migration; always runs)
            2. check_orphaned_tags (on stripped text, before extraction)
            3. check_length_floor
            4. check_repetition
            5. update last-reply cache
        """
        cleaned = self.strip_markdown(text)

        warnings: list[tuple[str, str]] = []
        if self.config.enabled:
            for check in (
                self.check_orphaned_tags(cleaned),
                self.check_length_floor(agent_id, cleaned),
                self.check_repetition(agent_id, cleaned),
            ):
                if check is not None:
                    warnings.append(check)

        # Update cache AFTER repetition check; bound to live agents only.
        # Empty replies do not poison the cache.
        if cleaned.strip():
            self._last_reply_by_agent[agent_id] = cleaned

        return DmSanityResult(cleaned_text=cleaned, warnings=warnings)
