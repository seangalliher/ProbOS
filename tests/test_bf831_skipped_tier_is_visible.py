"""BF-831 (#1296): the Captain was not told which tier was skipped.

BF-830 (#1295) stops a consensus rejection entering the Tier 1 retry, because
that retry RE-EXECUTES the act the crew declined. It records the skip in
`EscalationResult.tiers_skipped` and passes it into the Tier 3 context.

Neither surface read it. Measured by review, the Captain saw::

    tiers_attempted = ['user']
    tiers_skipped   = None      (not read)

So the prompt gave no reason the retry was skipped — and worse, the tier being
consulted RIGHT NOW is appended to `tiers_attempted` before the callback runs,
so it was listed under "Already tried". The Captain was told the prompt they
were standing in had already been tried.
"""

from __future__ import annotations

import pytest

from probos.experience.panels import _format_escalation


class _Console:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text: str = "") -> None:
        self.lines.append(str(text))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def _prompt(context: dict) -> _Console:
    """Run the real approval callback with input stubbed to 'skip'."""
    import builtins

    import probos.experience.commands.approval_callbacks as mod

    console = _Console()
    real_input = builtins.input
    try:
        builtins.input = lambda *_a, **_kw: ""
        await mod.user_escalation_callback(console, "question?", context)
    finally:
        builtins.input = real_input
    return console


def _context(**kw) -> dict:
    base = {
        "intent": "run_command",
        "params": {"command": "rm -rf /important"},
        "error": "consensus rejected",
        "tiers_attempted": ["user"],
    }
    base.update(kw)
    return base


# ── the prompt ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_captain_is_told_why_the_retry_was_skipped() -> None:
    console = await _prompt(
        _context(
            tiers_skipped={
                "retry": "consensus rejected the act; retrying would perform it again"
            }
        )
    )
    assert "retry" in console.text
    assert "would perform it again" in console.text


@pytest.mark.asyncio
async def test_the_tier_being_consulted_is_not_listed_as_already_tried() -> None:
    """`user` is appended before the callback runs, so listing it verbatim
    tells the Captain the prompt they are answering was already attempted."""
    console = await _prompt(_context(tiers_attempted=["user"]))
    assert "Already tried" not in console.text, console.text


@pytest.mark.asyncio
async def test_tiers_that_really_were_tried_are_still_listed() -> None:
    """The regression the fix above could cause."""
    console = await _prompt(_context(tiers_attempted=["retry", "arbitration", "user"]))
    assert "Already tried" in console.text
    assert "retry" in console.text
    assert "arbitration" in console.text


@pytest.mark.asyncio
async def test_an_EARLIER_user_consultation_is_not_hidden() -> None:
    """Only the tier being consulted now is dropped — the LAST entry — not
    every `user` by value.

    Filtering by value hid a legitimate earlier consultation: measured with
    `["user", "retry", "user"]`, which rendered only `retry`. The cascade
    appends USER once today so this is not yet reachable, but the value rule
    would simply be the wrong identity test if it ever were.
    """
    console = await _prompt(_context(tiers_attempted=["user", "retry", "user"]))
    assert "Already tried" in console.text
    assert console.text.count("user") >= 1, console.text
    assert "retry" in console.text


@pytest.mark.asyncio
async def test_enum_members_are_handled_as_well_as_strings() -> None:
    """`tiers_attempted` can hold either."""
    from probos.types import EscalationTier

    console = await _prompt(
        _context(tiers_attempted=[EscalationTier.RETRY, EscalationTier.USER])
    )
    assert "retry" in console.text
    assert "Already tried" in console.text


@pytest.mark.asyncio
async def test_a_context_without_the_key_still_prompts() -> None:
    """Every caller that predates BF-830 passes no `tiers_skipped`."""
    console = await _prompt(_context())
    assert "your decision needed" in console.text


@pytest.mark.asyncio
async def test_a_hostile_skip_value_does_not_break_the_prompt() -> None:
    """The Captain must still be asked even if the field is malformed — the
    decision matters more than the annotation."""
    for value in (None, [], "retry", 42):
        console = await _prompt(_context(tiers_skipped=value))
        assert "your decision needed" in console.text, value


# ── through a REAL Rich console ───────────────────────────────────
#
# The double above records strings and cannot parse markup, so it stops short
# of the boundary that actually broke: `[dim]{why}[/dim]` is Rich MARKUP, and
# an unmatched closing tag raises `MarkupError`. Measured by review, a reason
# of "[/dim]BROKEN" raised in the callback BEFORE `input()` ran — the Captain
# was never asked at all — and raised again while rendering the results Panel,
# suppressing the whole panel. The non-dict cases above are discarded by the
# `isinstance` guard and never reach the interpolation.


def _real_console():
    import io

    from rich.console import Console

    buffer = io.StringIO()
    return Console(file=buffer, width=100, force_terminal=False), buffer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile",
    ["[/dim]BROKEN", "[bold red]INJECT[/bold red]", "[not a tag", "]["],
)
async def test_markup_in_a_reason_cannot_suppress_the_prompt(hostile: str) -> None:
    import builtins

    import probos.experience.commands.approval_callbacks as mod

    console, buffer = _real_console()
    real_input = builtins.input
    asked = []
    try:
        builtins.input = lambda *_a, **_kw: asked.append(True) or ""
        await mod.user_escalation_callback(
            console, "q?", _context(tiers_skipped={"retry": hostile})
        )
    finally:
        builtins.input = real_input

    assert asked, f"the Captain was never asked: {hostile!r}"
    assert "your decision needed" in buffer.getvalue()


@pytest.mark.asyncio
async def test_markup_in_a_TIER_NAME_is_escaped_too() -> None:
    import builtins

    import probos.experience.commands.approval_callbacks as mod

    console, buffer = _real_console()
    real_input = builtins.input
    asked = []
    try:
        builtins.input = lambda *_a, **_kw: asked.append(True) or ""
        await mod.user_escalation_callback(
            console, "q?", _context(tiers_skipped={"[/dim]evil": "why"})
        )
    finally:
        builtins.input = real_input

    assert asked
    assert "evil" in buffer.getvalue()


@pytest.mark.parametrize(
    "hostile",
    ["[/dim]BROKEN", "[bold red]INJECT[/bold red]", "[not a tag", "]["],
)
def test_markup_in_a_reason_cannot_suppress_the_panel(hostile: str) -> None:
    """`_format_escalation`'s lines are rendered inside a Rich Panel
    (`renderer.py:435`), so a raise there costs the whole panel, not one line.
    """
    from rich.panel import Panel

    console, buffer = _real_console()
    lines = _format_escalation(
        {
            "tier": "user",
            "resolved": False,
            "reason": "user declined",
            "tiers_skipped": {"retry": hostile},
        }
    )
    console.print(Panel("\n".join(lines), title="Results"))

    out = buffer.getvalue()
    assert "Results" in out, f"the panel was suppressed: {hostile!r}"
    assert "not tried" in out


# ── the final panel ───────────────────────────────────────────────


def test_the_panel_shows_the_skip_and_its_reason() -> None:
    lines = _format_escalation(
        {
            "tier": "user",
            "resolved": False,
            "reason": "user declined",
            "tiers_skipped": {"retry": "consensus rejected the act"},
        }
    )
    body = "\n".join(lines)
    assert "not tried (retry)" in body
    assert "consensus rejected the act" in body


def test_the_panel_is_unchanged_without_the_key() -> None:
    """An escalation result recorded before BF-830 carries no skips."""
    lines = _format_escalation(
        {"tier": "retry", "resolved": True, "reason": "Retry 1 succeeded"}
    )
    assert lines == [
        "    [yellow]\u2191 Escalated (Tier: retry)[/yellow] \u2014 [green]Resolved[/green]",
        "      Retry 1 succeeded",
    ]


def test_the_panel_tolerates_a_malformed_skip_field() -> None:
    for value in (None, [], "retry", 42):
        lines = _format_escalation(
            {"tier": "user", "resolved": False, "reason": "r", "tiers_skipped": value}
        )
        assert lines[0].startswith("    [yellow]")
