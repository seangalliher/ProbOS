"""BF-940 (#1686): the framing function's contract, row by row. Each reader's own cases are in test_bf940_frontmatter_framing.py."""

from __future__ import annotations

import random

import pytest

from probos.utils.frontmatter import split_frontmatter


@pytest.mark.parametrize(("text", "framed"), [
    pytest.param("---\na: 1\n---\n\nbody\n", ("\na: 1\n", "\n\nbody\n"), id="the-store-shape"),
    pytest.param("---\na: x---y\n---\nbody", ("\na: x---y\n", "\nbody"), id="hyphens-inside-a-line-end-nothing"),
    pytest.param("---\na: 1\n----\nbody", ("\na: 1\n", "\nbody"), id="a-closing-line-of-four-hyphens"),
    pytest.param("---\na: 1\n---  \nbody", ("\na: 1\n", "  \nbody"), id="trailing-blanks-stay-in-the-rest"),
    pytest.param("---\r\na: 1\r\n---\r\nbody", ("\r\na: 1\r\n", "\r\nbody"), id="crlf"),
    pytest.param("---\na: 1\n---", ("\na: 1\n", ""), id="the-closing-line-ends-the-text"),
    pytest.param("---\n---\nbody", ("\n", "\nbody"), id="an-empty-block"),
    pytest.param("---\na: 1 --- b\nbody", ("\na: 1 ", " b\nbody"), id="no-closing-line-the-base-framing-L18"),
    pytest.param("---\ra: 1\r---\rbody", ("\ra: 1\r", "\rbody"), id="no-line-feed-at-all-the-base-framing"),
    pytest.param("---\na: 1\nbody", (None, "---\na: 1\nbody"), id="no-later-hyphens-L18"),
    pytest.param("---", (None, "---"), id="an-opener-alone"),
    pytest.param("", (None, ""), id="empty"),
    pytest.param("\ufeff---\na: 1\n---\n", (None, "\ufeff---\na: 1\n---\n"), id="a-byte-order-mark"),
    pytest.param("a: 1\n---\nbody", (None, "a: 1\n---\nbody"), id="no-opener"),
])
def test_each_shape_is_framed_as_its_row_says(text, framed):
    assert split_frontmatter(text) == framed


def _loop(text: str) -> tuple[str | None, str]:
    """The same rule as a loop over the lines: the reference for random documents."""
    if text.startswith("---"):
        offset = text.find("\n") + 1
        for line in text[offset:].split("\n") if offset else ():
            bare = line.rstrip(" \t\r")
            if len(bare) >= 3 and set(bare) == {"-"}:
                return text[3:offset], text[offset + len(bare):]
            offset += len(line) + 1
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2]
    return None, text


def test_random_documents_are_framed_as_a_loop_over_the_lines_frames_them():
    rng, pieces = random.Random(940), ["---", "----", "--", "-", "\n", "\r\n", "\r", " ", "\t", "a", ": ", "x---y", "---\n", "\n---\n"]
    for _ in range(4000):
        text = "---" * rng.randint(0, 1) + "".join(rng.choice(pieces) for _ in range(rng.randint(0, 16)))
        assert split_frontmatter(text) == _loop(text), repr(text)
