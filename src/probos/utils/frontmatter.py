"""BF-940 (#1686): where the frontmatter of a Markdown document ends.

Ship's Records documents and SKILL.md files open with ``---``, hold YAML, and close with a line of their own. The base cut
each at the first two ``---`` it found, inside a YAML value too, so a value holding ``---`` was cut short and the keys after
it left the frontmatter. This module frames a document (``split_frontmatter`` and ``base_split_frontmatter`` load nothing).
BF-970 (#1801) adds ``load_frontmatter``, the one reading of a Ship's Records frontmatter block: it checks the nesting with a
parse that does not recurse (``frontmatter_nests_too_deep``) and loads only below ``FRONTMATTER_DEPTH_LIMIT``, so no reader's
answer depends on the frames above it (this replaces BF-952 A6's frame arrangement). It imports nothing of ProbOS (``utils``
holds pure helpers any layer may import). BF-940 slice 2 adds ``dump_frontmatter``, the writers' half: the one place a
frontmatter mapping becomes YAML text, so that a document the store writes is a document the store reads (L24); it refuses
what ``load_frontmatter`` would not load (BF-970).
"""

from __future__ import annotations

import re
from typing import Any

import yaml

#: A line of three or more hyphens and nothing else but trailing blanks. Group 1 is the hyphens: whatever follows them (the
#: blanks, the line break) belongs to the text after the marker, as what followed the second ``---`` did on the base.
_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Frame ``text`` as ``(block, rest)``: its frontmatter block and the text after it. ``block`` is None with none.

    A text has frontmatter when it begins with ``---``. The block runs from those three hyphens to the first later line
    made only of hyphens (three or more, trailing blanks allowed), line break included; ``rest`` is everything after that
    line's hyphens, not stripped, so a caller that rewrites the document keeps its whitespace. A ``---`` inside a line ends
    nothing. Where no such line follows, the text is framed as the base framed every document: the block ends at the first
    later ``---`` wherever it stands (L18), and ``(None, text)`` returns when there is none.
    """
    if not text.startswith("---"):
        return None, text
    first_break = text.find("\n")
    if first_break != -1:
        closing = _CLOSING_LINE.search(text, first_break + 1)
        if closing is not None:
            return text[3:closing.start()], text[closing.end(1):]
    return base_split_frontmatter(text)  # a text with no closing line is framed as the base framed it (L18)


def base_split_frontmatter(text: str) -> tuple[str | None, str]:
    """Frame ``text`` as the base framed every document: cut at the first two ``---`` it holds, wherever they stand.

    ``block`` is what stands between the opener and the next ``---``, inside a value too, and ``rest`` is what follows it, not
    stripped; ``(None, text)`` for a text that does not begin with ``---`` or holds no later one. It is the rule's answer for a
    text with no closing line (L18). BF-940 A1 read this cut where the rule's block did not load; BF-970 (#1801) removed that.
    Wherever ``split_frontmatter`` returns a block this returns one too, and it is that block up to its first ``---`` (U4).
    """
    parts = text.split("---", 2) if text.startswith("---") else []
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, text


#: BF-970 (#1801): a frontmatter whose YAML holds this many collections open at once, or more, is not loaded by any reader and is
#: not written by ``dump_frontmatter``. The top-level mapping counts as one; a mapping or a sequence, flow or block, opens one more;
#: an alias opens none (the value it names was built where its anchor stands). PyYAML's composer recurses about two Python frames a
#: level, so a load below this depth needs a fixed number of frames whatever the caller's stack.
FRONTMATTER_DEPTH_LIMIT = 64


def frontmatter_nests_too_deep(text: str, loader: Any = yaml.SafeLoader) -> bool:
    """BF-970 (#1801): whether ``text``, parsed with ``loader``, holds ``FRONTMATTER_DEPTH_LIMIT`` collections open at once.

    It reads the parser's event stream, which neither PyYAML's parser nor libyaml's builds by recursion, and stops at the event
    that reaches the limit, so its answer does not depend on the caller's stack and its work is bounded by the length of ``text``:
    no node is built and no alias is followed. Siblings add no depth. A parse error before the limit, a ``YAMLError``, is
    ``False``: the load that follows, with the same ``loader``, meets the same error below the limit and reads it as YAML's
    refusal. BF-970 A2 (round 1 F4): any other exception of the parser propagates, as it does from the load: PyYAML's scanner
    raises ``ValueError`` for an escape past U+10FFFF (``"\\U00110000"``), and each reader handles it as a constructor's error
    (contract D4, L12).
    """
    depth = 0
    try:
        for event in yaml.parse(text, Loader=loader):
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
                if depth >= FRONTMATTER_DEPTH_LIMIT:
                    return True
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
    except yaml.YAMLError:
        return False  # a parse error before the limit: the load reads YAML's refusal
    return False


def load_frontmatter(block: str, loader: Any = yaml.SafeLoader) -> tuple[Any, bool]:
    """BF-970 (#1801): a frontmatter block as every Ship's Records reader reads it: ``(frontmatter, unparsed)``.

    ``unparsed`` is True, and ``frontmatter`` ``{}``, for a block YAML refuses (a ``YAMLError``) or one that holds
    ``FRONTMATTER_DEPTH_LIMIT`` collections open at once or more (:func:`frontmatter_nests_too_deep`, checked first with the
    same ``loader``). Otherwise ``frontmatter`` is the load's value, ``{}`` for a falsy one, and ``unparsed`` is False; with the
    default loader that value is ``yaml.safe_load``'s. Any other error of the check or the load propagates, as from ``yaml.safe_load``: a
    constructor's ``ValueError`` (``updated: 2026-13-05``) included. No ``RecursionError`` comes from the nesting: the load
    runs only below the limit.
    """
    if frontmatter_nests_too_deep(block, loader):
        return {}, True
    try:
        return yaml.load(block, Loader=loader) or {}, False
    except yaml.YAMLError:
        return {}, True


class _NestsTooDeep(yaml.YAMLError):
    """BF-970: the text ``safe_dump`` wrote holds ``FRONTMATTER_DEPTH_LIMIT`` collections open at once, which no reader loads."""


_UNWRITABLE = (yaml.YAMLError, RecursionError)


def _dump(mapping: dict[Any, Any]) -> str:
    text = yaml.safe_dump(mapping, default_flow_style=False, sort_keys=False)
    if frontmatter_nests_too_deep(text):  # BF-970: checked before the read-back load, which recurses
        raise _NestsTooDeep("frontmatter nests too deep")
    if type(yaml.safe_load(text)) is not dict:
        raise yaml.YAMLError("frontmatter did not read back as a mapping")
    return text


def dump_frontmatter(mapping: dict[Any, Any]) -> str:
    """Write ``mapping`` as the YAML a document's frontmatter holds, or raise ``ValueError`` (BF-940 slice 2, L24).

    A document the store writes is a document the store reads. ``yaml.dump`` wrote a tuple, an ``OrderedDict``, a ``frozenset``
    or any other object with a ``!!python/`` tag, which no reader loads: the document read as ``{}``, at the default ``ship``
    classification, whoever its author. The text here is ``yaml.safe_dump``'s with the arguments the writers used. For every
    value ``yaml.dump`` wrote without a ``!!python/`` tag (every value ``safe_load`` builds that holds no tuple) it is
    byte-identical to ``yaml.dump``'s. Where ``yaml.dump`` wrote a tag, a tuple is written as a list and an object ``safe_dump``
    refuses is a ``ValueError``. ``safe_load`` builds a tuple for exactly two tags, ``!!omap`` and ``!!pairs`` (a list of
    tuples), so a mapping holding one is written as a list of lists: the readers load it, as lists, not as the ordered mapping
    or the pairs it was (BF-940 A1, F2). The text is then loaded once more, because ``safe_dump`` writes what ``safe_load``
    refuses (a tuple as a mapping key). BF-970 (#1801): a mapping whose text holds ``FRONTMATTER_DEPTH_LIMIT`` (64)
    collections open at once or more is a ``ValueError`` (no reader loads it: :func:`load_frontmatter`), checked before the
    read-back load, and so is one nested beyond the recursion limit. The message names the top-level keys at fault and the
    error's type, or the limit, never a value (AD-1140's fail-fast tier); the caller has touched no file yet.
    """
    try:
        return _dump(mapping)
    except _UNWRITABLE as exc:
        keys = []
        for key, value in mapping.items():
            try:
                _dump({key: value})
            except _UNWRITABLE:
                keys.append(str(key))
        if isinstance(exc, (_NestsTooDeep, RecursionError)):  # BF-970: what no reader loads is not written
            raise ValueError(
                "frontmatter key(s) %s nest %d or more collections deep, which no reader loads; flatten them"
                % (", ".join(keys) or "(none singly)", FRONTMATTER_DEPTH_LIMIT)
            ) from exc
        raise ValueError(
            "frontmatter key(s) %s hold a value that cannot be written so that it reads back (%s); use strings, numbers, "
            "booleans, None, dates, and lists or mappings of them" % (", ".join(keys) or "(none singly)", type(exc).__name__)
        ) from exc
