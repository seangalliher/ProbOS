"""BF-794 (#1258): a disclosure that fits in one message is never split.

``split_for_wire`` is exactly lossless, so the AD-1248 disclosure was never
destroyed -- it was *fragmented at the worst possible place*. The ``\\n\\n``
that precedes the disclosure is the last newline in the text and is exactly
the right boundary, but the ``cut < limit // 2`` guards rejected it whenever
the body was short and the tail long. Control fell through to the space
search, and because the disclosure is a comma-separated list the cut landed
*inside* it: message 1 ended mid-sentence and message 2 carried a
six-character orphan.

The sweep below asserts its own premise before trusting any negative result.
An earlier 36,240-case sweep of this exact question returned zero cuts and was
wrong, because it capped the tool-name count at five -- the defect needs 15-31
names, where the disclosure exceeds half the wire limit.
"""

import random

import pytest

from probos.channels import discord_adapter
from probos.dm_reply import (
    _DISCLOSURE_PREFIX,
    DmReply,
    ToolFailures,
    _compose_disclosure,
    split_for_wire,
)

DISCORD_LIMIT = 2000
TELEGRAM_LIMIT = 4096

_BODY_FILL = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do "


def _pre_bf794_split(text: str, limit: int) -> list[str]:
    """The boundary rule as it stood at ``11a8910d``, verbatim.

    Inlined rather than imported so the premise assertion below is measuring
    the defect and not a later edit to it.
    """
    if limit <= 0:
        raise ValueError(f"split_for_wire(limit={limit}) needs a positive limit")
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    while text:
        if len(text) <= limit:
            pieces.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        cut = cut + 1 if cut != -1 else -1
        if cut <= 0 or cut < limit // 2:
            space = text.rfind(" ", 0, limit)
            cut = space + 1 if space != -1 else -1
        if cut <= 0 or cut < limit // 2:
            cut = limit
        pieces.append(text[:cut])
        text = text[cut:]
    return pieces


def _render(nnames: int, nlen: int, body_len: int) -> tuple[str, str]:
    """Return ``(rendered_text, disclosure)`` for a reply with N failed tools."""
    assert nlen >= 4
    names = [f"t{i:03d}" + "x" * (nlen - 4) for i in range(nnames)]
    failures = ToolFailures.from_mapping({f"k{i}": n for i, n in enumerate(names)})
    body = (_BODY_FILL * (body_len // len(_BODY_FILL) + 2))[:body_len]
    text = str(DmReply(body=body, tool_failures=failures).render())
    disclosure = _compose_disclosure(failures.names(), failures.failed_call_count)
    return text, disclosure


def _boundaries(pieces: list[str]) -> list[int]:
    """Cumulative offsets at which the text was cut."""
    out: list[int] = []
    run = 0
    for piece in pieces[:-1]:
        run += len(piece)
        out.append(run)
    return out


def _cuts_inside_disclosure(text: str, disclosure: str, pieces: list[str]) -> list[int]:
    start = len(text) - len(disclosure)
    return [o for o in _boundaries(pieces) if start < o < len(text)]


# --------------------------------------------------------------------------
# The load-bearing sweep
# --------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [DISCORD_LIMIT, TELEGRAM_LIMIT])
def test_disclosure_that_fits_within_the_limit_is_never_split(limit: int) -> None:
    """No cut lands inside a disclosure that could have been kept whole.

    Sweeps the full name space, which is the axis that matters: the cut
    requires ``len(disclosure) > limit / 2``, which Discord reaches at roughly
    fifteen 64-character names. A sweep that caps names low finds nothing and
    proves nothing.

    FIXABLE means the whole tail fits in one message and was split anyway.
    UNFIXABLE means the disclosure alone exceeds the wire limit (32 x 64 =
    2,174 > 2,000), which no boundary placement can help; it stays lossless
    and is asserted separately below.
    """
    fixable_before = fixable_after = unfixable_after = 0

    for nnames in range(1, 33):
        for nlen in (8, 16, 32, 48, 64):
            for body_len in range(0, limit + 400, 4):
                text, disclosure = _render(nnames, nlen, body_len)
                if len(text) <= limit:
                    continue
                fits = len(disclosure) + len(_DISCLOSURE_PREFIX) <= limit

                if _cuts_inside_disclosure(
                    text, disclosure, _pre_bf794_split(text, limit)
                ) and fits:
                    fixable_before += 1

                pieces = split_for_wire(text, limit)
                assert "".join(pieces) == text, "the split must stay lossless"
                assert all(len(p) <= limit for p in pieces)
                if _cuts_inside_disclosure(text, disclosure, pieces):
                    if fits:
                        fixable_after += 1
                    else:
                        unfixable_after += 1

    # PREMISE. A sweep that cannot see the defect cannot certify its absence.
    assert fixable_before > 0, (
        "the pre-BF-794 rule produced no mid-disclosure cut anywhere in this "
        "sweep, so the sweep does not reach the regime where the defect lives "
        "and its zero below would be meaningless"
    )
    assert fixable_after == 0, (
        f"{fixable_after} disclosures that fit in one message were split anyway"
    )
    if limit == DISCORD_LIMIT:
        assert unfixable_after > 0, (
            "Discord's 2,000-char limit is smaller than the largest disclosure "
            "the system can emit, so some cases must remain unfixable; none "
            "here means the sweep stopped short of _MAX_NAMES"
        )


def test_the_reported_discord_and_telegram_cases_are_fixed() -> None:
    """The two published repros, pinned by their exact piece lengths.

    Both ended with a six-character orphan opening message 2 -- the symptom
    the issue was filed on.
    """
    for limit, nnames, body_len in ((DISCORD_LIMIT, 15, 948), (TELEGRAM_LIMIT, 31, 1988)):
        text, disclosure = _render(nnames, 64, body_len)
        before = _pre_bf794_split(text, limit)
        assert [len(p) for p in before][-1] == 6, (
            f"premise: the pre-fix rule should orphan six characters, got "
            f"{[len(p) for p in before]}"
        )
        assert _cuts_inside_disclosure(text, disclosure, before)

        after = split_for_wire(text, limit)
        assert _cuts_inside_disclosure(text, disclosure, after) == []
        assert after[-1] == disclosure, "the disclosure should arrive whole"
        assert "".join(after) == text


def test_a_disclosure_larger_than_the_limit_is_still_split_losslessly() -> None:
    """The UNFIXABLE case is accepted behaviour, not a latent bug.

    32 names of 64 characters render a 2,174-character disclosure, which no
    boundary placement fits inside Discord's 2,000. The split stays exact, so
    every name still reaches the Captain across two messages.
    """
    text, disclosure = _render(32, 64, 0)
    assert len(disclosure) > DISCORD_LIMIT
    pieces = split_for_wire(text, DISCORD_LIMIT)
    assert "".join(pieces) == text
    assert all(len(p) <= DISCORD_LIMIT for p in pieces)
    assert all(p for p in pieces)


# --------------------------------------------------------------------------
# The contract the fix must not break
# --------------------------------------------------------------------------


def test_split_is_lossless_and_terminates_for_random_text() -> None:
    """``"".join(split_for_wire(t, n)) == t`` for every input, exactly.

    An empty piece is the shape of the non-termination adversarial review
    found in the hoisted original, so it is asserted against for every
    non-empty input. Empty input is the one case that legitimately yields
    ``[""]``, from the early return that never enters the loop.
    """
    rng = random.Random(1258)
    alphabet = "ab \n\n\t.,-"
    for _ in range(4000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
        limit = rng.randint(1, 40)
        pieces = split_for_wire(text, limit)
        assert "".join(pieces) == text
        assert all(len(p) <= limit for p in pieces)
        if text:
            assert all(p for p in pieces), "an empty piece means the loop can hang"

    assert split_for_wire("", 10) == [""]


@pytest.mark.parametrize("limit", [0, -1, -2000])
def test_a_nonpositive_limit_still_raises(limit: int) -> None:
    with pytest.raises(ValueError):
        split_for_wire("anything at all", limit)


def test_ordinary_prose_never_costs_an_extra_message() -> None:
    """What the new boundary rule does to text that carries no disclosure.

    The rule fires on the *last* newline, so prose with no newline at all is
    byte-identical -- asserted here rather than assumed. Prose that does have
    paragraph breaks can split differently, and does: roughly 1.5% of
    over-limit pairs in this corpus. That perturbation is not free, so the
    property that matters is measured rather than waved at -- it never costs
    an extra wire message, which is rate-limit consumption, not cosmetics.
    """
    rng = random.Random(794)
    words = (
        "the ship computer reports a sensor anomaly near deck twelve and "
        "recommends immediate review of logs before the next watch"
    ).split()

    flat_compared = paragraph_changed = paragraph_compared = 0
    for newline_rate in (0.0, 0.004, 0.05):
        for _ in range(2000):
            limit = rng.choice((40, 120, 500, 2000, 4096))
            parts: list[str] = []
            for _ in range(rng.randint(5, 600)):
                parts.append(rng.choice(words))
                if rng.random() < newline_rate:
                    parts.append("\n")
            text = " ".join(parts)
            if len(text) <= limit:
                continue

            before = _pre_bf794_split(text, limit)
            after = split_for_wire(text, limit)
            assert "".join(after) == text
            assert all(len(p) <= limit for p in after)
            assert len(after) <= len(before), (
                f"the new rule used {len(after)} messages where the old used "
                f"{len(before)}; a boundary improvement must not cost a message"
            )
            if newline_rate == 0.0:
                flat_compared += 1
                assert after == before, (
                    "text with no newline has no last newline to prefer, so the "
                    "rule must be inert"
                )
            else:
                paragraph_compared += 1
                if after != before:
                    paragraph_changed += 1

    assert flat_compared > 500, "the newline-free arm did not exercise anything"
    assert paragraph_changed > 0, (
        "no paragraph-bearing case changed, so this test is not measuring the "
        "new rule at all"
    )


def test_the_rule_is_scoped_to_a_trailing_block() -> None:
    """The last-newline clause is what keeps this a tail fix.

    Dropping it gives the broader rule "any early newline whose remainder
    fits", which also eliminates every mid-disclosure cut -- so the sweep
    above cannot tell the two apart. It is pinned here instead: when the text
    continues past the candidate newline, there is no trailing block to keep
    whole and the pre-BF-794 boundary is retained. Measured over a mixed prose
    corpus the narrow rule perturbs 1.43% of over-limit pairs against the
    broad rule's 1.83%.
    """
    text, limit = "a\nbbbbbbbb\nc", 10
    assert text.rfind("\n", 0, limit) != text.rfind("\n"), (
        "premise: this case only discriminates when a newline follows the "
        "candidate, which is what the clause tests"
    )
    assert split_for_wire(text, limit) == _pre_bf794_split(text, limit) == [
        "a\nbbbbbbbb",
        "\nc",
    ]


def test_the_splitter_stays_ignorant_of_the_disclosure() -> None:
    """BF-794 is a boundary-quality fix, not a disclosure-aware one.

    ``split_for_wire`` is shared by every wire-limited sink and must not grow
    knowledge of ``DmReply``. If it ever does, the seam change this fix was
    built to avoid has arrived by the back door.
    """
    import inspect

    source = inspect.getsource(split_for_wire)
    for forbidden in ("DmReply", "_DISCLOSURE_PREFIX", "tool_failures", "disclosure"):
        assert forbidden not in source, (
            f"split_for_wire references {forbidden!r}; it must stay a generic "
            f"string splitter, docstring included"
        )


def test_telegram_and_discord_share_one_splitter() -> None:
    """One fix, both sinks -- the reason no seam change was needed.

    The issue is titled Telegram, but Discord's 2,000-char limit is the
    reachable channel: it needs only a 1,000-character disclosure, which
    fifteen MCP tool ids reach.
    """
    text, _ = _render(15, 64, 948)
    assert discord_adapter._chunk_message(text) == split_for_wire(text, DISCORD_LIMIT)
    assert discord_adapter._MAX_MESSAGE_LENGTH == DISCORD_LIMIT

    import probos.channels.telegram_adapter as telegram_adapter

    assert telegram_adapter._MAX_MESSAGE_LENGTH == TELEGRAM_LIMIT
    source = __import__("inspect").getsource(telegram_adapter.TelegramAdapter.send_response)
    assert "split_for_wire(" in source, (
        "Telegram must route through the shared splitter for this fix to reach it"
    )
