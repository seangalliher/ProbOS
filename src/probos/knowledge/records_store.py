"""Ship's Records — Git-backed instance knowledge store (AD-434)."""

import asyncio
import fnmatch
import logging
import math
import os
import re
import subprocess
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from probos.cognitive.provenance import record_write_time
from probos.execution.command_env import trusted_command_env
from probos.utils.frontmatter import split_frontmatter

logger = logging.getLogger(__name__)

# BF-957: how many distinct git errors one store remembers so that each is logged once; past this the oldest is dropped.
_GIT_WARNED_MAX = 32
# BF-957: the git verbs that take the index lock. A zero exit of one forgets every remembered error.
_GIT_INDEX_VERBS = frozenset({"add", "commit"})
# BF-957: a commit with nothing staged exits non-zero and says so on stdout; it is not an error.
_GIT_NOTHING_STAGED = ("nothing to commit", "nothing added to commit")


def _git_error_line(stderr: str, stdout: str) -> str:
    """BF-957: the first non-empty line a failed git command printed. Two failures with the same line are one error."""
    for text in (stderr, stdout):
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:300]
    return "(no output)"


# Directory structure per AD-434 design
_SUBDIRS = (
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "bills",          # AD-618a: Standard Operating Procedures (raw YAML, not markdown)
    "consultations",  # AD-594a: Session-scoped consultation workspaces (raw files; per-workspace subdirs)
    "_archived",
)

# AD-1140: frontmatter keys ``write_entry`` owns. A caller supplying one of
# these through ``extra_frontmatter`` is rejected rather than silently dropped —
# dropping would let the caller believe it stamped provenance that is not there.
_RESERVED_FRONTMATTER_KEYS = frozenset({
    "author",
    "classification",
    "status",
    "created",
    "updated",
    "revision",
    "department",
    "topic",
    "tags",
    "metrics",
})

# Classification hierarchy (higher index = broader access)
_CLASSIFICATION_LEVELS = {
    "private": 0,
    "department": 1,
    "ship": 2,
    "fleet": 3,
}

# AD-1157: the default classification for an agent notebook entry.
#
# The authority for this value is the records ontology — ``config/ontology/
# records.yaml``, document class ``notebook``, ``classification_default:
# private``, with the stated rule "Private by default — agent can explicitly
# publish entries". The code shipped ``department`` instead and the divergence
# went unnoticed for the life of the corpus: 2,453 of 2,453 notebook entries on
# the reference vessel were written at ``department``, none at ``private`` and
# none at ``ship``, because the ``[NOTEBOOK]`` action tag had no syntax for the
# choice and neither proactive write site passed one. The default was therefore
# the only classification any notebook could ever receive.
#
# Named rather than inlined so the ontology and the code have a single
# comparison point, and guarded by a test that parses ``records.yaml`` and
# asserts the two still agree — a silent redefinition here is the exact defect
# this constant exists to close, so a comment alone would be the same
# unenforced promise that produced it.
NOTEBOOK_DEFAULT_CLASSIFICATION = "private"

# BF-679: classifications whose visibility depends on *who is reading* rather
# than on the scope level alone. Mirrors the gate in :meth:`RecordsStore.read_entry`.
# Owned here (the store defines the rule); ``knowledge.semantic`` imports it so
# the ChromaDB filter and this predicate cannot drift apart.
_IDENTITY_GATED_CLASSIFICATIONS = frozenset({"private", "department"})

# BF-679: the one reader id with unrestricted read access (``read_entry``'s rule).
_UNRESTRICTED_READER = "captain"


def record_is_readable(
    frontmatter: dict[str, Any],
    *,
    scope: str = "ship",
    reader_id: str | None = None,
    reader_department: str = "",
) -> bool:
    """BF-679: may this record be read at ``scope`` by this reader?

    The single source of truth for records admissibility on the *keyword*
    retrieval path. :func:`probos.knowledge.semantic.build_records_scope_filter`
    is its declarative twin — the same rule expressed as a ChromaDB ``where``
    clause so the semantic path enforces it at query time rather than by
    post-filtering. Both are exercised against each other by the BF-679 parity
    tests; change one and you must change the other.

    Two layers compose:

    * **Scope level** (always applied) — a record is admissible when
      ``level(classification) <= level(scope)``. An unrecognised record
      classification defaults to level ``0`` and an unrecognised ``scope`` to
      level ``2``.
    * **Reader identity** — mirrors :meth:`RecordsStore.read_entry`:
      ``private`` needs authorship, ``department`` needs a matching department
      or authorship. Strictly stricter than the scope level, never looser.

    ``reader_id`` is deliberately tri-state, because "no reader was supplied"
    and "an anonymous reader asked" are different questions:

    * ``None`` — **identity not specified**. Scope level only; the pre-BF-679
      behaviour.
    * ``""`` — **anonymous reader**. The identity layer runs with an empty
      author, so identity-gated classifications are withheld. This is the
      fail-closed state the Oracle uses for a caller it cannot identify.
    * ``"captain"`` — unrestricted, per ``read_entry``.
    * anything else — an author/department identity, matched against the
      record's ``author`` / ``department`` frontmatter.

    One deliberate departure from ``read_entry``: a ``department`` record that
    carries **no** ``department`` frontmatter is readable only by its author,
    not by every reader who also has no department. ``read_entry`` compares
    ``reader_department != doc_dept`` and so admits the empty-matches-empty
    case; ``build_records_scope_filter`` omits the department clause entirely
    when the reader has no department. Parity between the two Oracle retrieval
    paths is the BF-679 requirement, and of the two behaviours the closed one
    is the safe one to converge on.
    """
    doc_class = frontmatter.get("classification", "ship")
    # A non-str classification takes the same level-0 default ``search`` has
    # always applied; the explicit type check additionally survives an
    # unhashable value rather than raising out of the scan, and keeps such a
    # record out of the identity-gated set (it is not one of the four labels).
    is_labelled = type(doc_class) is str
    doc_level = _CLASSIFICATION_LEVELS.get(doc_class, 0) if is_labelled else 0
    if doc_level > _CLASSIFICATION_LEVELS.get(scope, 2):
        return False

    if reader_id is None or reader_id == _UNRESTRICTED_READER:
        return True
    if not is_labelled or doc_class not in _IDENTITY_GATED_CLASSIFICATIONS:
        return True

    doc_author = frontmatter.get("author", "")
    if reader_id == doc_author:
        return True
    if doc_class == "department":
        return bool(reader_department) and reader_department == frontmatter.get(
            "department", "",
        )
    return False


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# BF-952: the keyword axis of Ship's Records search (``RecordsStore.search``).
#
# The base scored a record by the fraction of query words found as substrings of the raw file,
# YAML keys included, and broke ties by path: ``i`` matched "ship", ``status`` matched every
# record, and a conversational question matched the whole repository at one score, so the paths
# that sort first won. A record is now matched on whole words of its body and of the frontmatter
# values in ``_SEARCH_FIELD_WEIGHTS``, and ranked by term rarity: BM25 with field weights, the
# shape BF-625 uses in ``cognitive/transcript_grounding.py``.
_SEARCH_TOKEN_RE = re.compile(r"\w+(?:[-.]\w+)*")
_SEARCH_PART_RE = re.compile(r"\w+")
_SEARCH_STOPWORDS: frozenset[str] = frozenset(
    (
        "a about above after again against all also am an and any are as at be because been before being "
        "below between both but by can could did do does doing down during each few for from further had has "
        "have having he her here hers herself him himself his how i if in into is it its itself just me may "
        "might more most must my myself no nor not now of off on once only or other our ours ourselves out "
        "over own same shall she should so some such than that the their theirs them themselves then there "
        "these they this those through to too under until up us very was we were what when where which while "
        "who whom why will with would you your yours yourself yourselves "
        # what the tokeniser leaves of a contraction: I'd, we'll, I'm, they're, it's, don't, I've
        "d ll m re s t ve"
    ).split()
)
#: Frontmatter fields whose *values* are scored, each weighted against one body occurrence (1.0).
#: Keys, ``classification``, ``status``, the timestamps and ``revision`` are never scored.
#: ``department`` is here because the self-monitoring pull searches by department name.
_SEARCH_FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "topic": 3.0,
    "tags": 3.0,
    "department": 2.0,
    "author": 2.0,
}
_SEARCH_BM25_K1 = 1.5
_SEARCH_BM25_B = 0.75
_SEARCH_LIMIT = 20
#: BF-952: the search loads frontmatter with libyaml when it is installed (it parses every record on
#: each call, and PyYAML's pure-Python scanner was about a third of that cost). Every other reader
#: loads as the base did, with ``yaml.safe_load`` (A5, round 5). ``_search_load_frontmatter`` reads as
#: the base did a frontmatter libyaml cannot load, for any reason (A4), and one nesting
#: ``_SEARCH_LIBYAML_DEPTH_LIMIT`` collections deep or more (A5).
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
#: BF-952 A5: the search hands libyaml only a block nesting fewer than this many collections deep. Below
#: it PyYAML's pure-Python composer builds the block too; from about 330 levels it raises
#: ``RecursionError`` (the base's reading), and a block that deep is read with the base's call.
_SEARCH_LIBYAML_DEPTH_LIMIT = 100


def _search_query_terms(query: str) -> list[str]:
    """BF-952: the distinct compound tokens of ``query``, in order, without stopwords.

    A query made only of stopwords keeps them all rather than finding nothing.
    """
    terms = list(dict.fromkeys(match.group() for match in _SEARCH_TOKEN_RE.finditer(query.lower())))
    kept = [term for term in terms if term not in _SEARCH_STOPWORDS]
    return kept or terms


def _search_field_text(value: Any) -> str:
    """BF-952: a frontmatter value as the text to score: a string, a number, or the strings and numbers of a list.

    A boolean is not text, alone or in a list (A1, finding 2).
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and type(value) is not bool:
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(
            str(item) for item in value
            if isinstance(item, (str, int, float)) and type(item) is not bool
        )
    return ""


def _load_frontmatter(block: str) -> Any:
    """BF-952 A5: a frontmatter block loaded exactly as the base loaded it, with ``yaml.safe_load``.

    A falsy value or a ``YAMLError`` is ``{}``. Any other error propagates, as on the base: a constructor's
    (``updated: 2026-13-05`` raises ``ValueError``) and PyYAML's ``RecursionError`` for a block nesting about 330
    collections deep.
    """
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:  # A5: the base's own catch; a constructor error or a RecursionError propagates
        return {}


def _nests_below(block: str, limit: int) -> bool:
    """BF-952 A5: whether libyaml parses ``block`` and its collections nest fewer than ``limit`` deep.

    It reads the loader's event stream, which the parser produces without recursing, and stops at ``limit``, so it
    is safe however deep the block. Siblings add no depth. A block that does not parse is not below the limit.
    """
    depth = 0
    try:
        for event in yaml.parse(block, Loader=_RECORDS_YAML_LOADER):
            if isinstance(event, yaml.CollectionStartEvent):
                depth += 1
                if depth >= limit:
                    return False
            elif isinstance(event, yaml.CollectionEndEvent):
                depth -= 1
    except Exception:  # A5: not a swallow; the base's call then reads it: its value, {} or its error (A6)
        return False
    return True


def _search_load_frontmatter(block: str) -> Any:
    """BF-952 A1, A4, A5: a frontmatter block as the search loads it: libyaml where it is safe, else as the base did.

    With libyaml installed and the block nesting fewer than ``_SEARCH_LIBYAML_DEPTH_LIMIT`` collections deep, the
    block is libyaml's value, ``{}`` for a falsy one. That differs from the base where PyYAML's scanner refuses the
    block (RK8: a tab after a key). A block libyaml cannot load, for any reason (A4), and one nesting deeper (A5),
    is read by :func:`_load_frontmatter`, the base's call: its value, ``{}`` for a ``YAMLError``, or its error (A6).
    """
    if _RECORDS_YAML_LOADER is yaml.SafeLoader or not _nests_below(block, _SEARCH_LIBYAML_DEPTH_LIMIT):
        return _load_frontmatter(block)
    try:
        frontmatter = yaml.load(block, Loader=_RECORDS_YAML_LOADER)
    except Exception:  # A4 (round 4): libyaml cannot load the block, so it is read as the base read it
        return _load_frontmatter(block)
    return frontmatter or {}


def _search_read_document(raw: str) -> tuple[Any, str, str | None]:
    """BF-952 A5: a document's frontmatter and body as the search reads them, and its frontmatter block.

    The framing every reader shares (BF-940: :func:`probos.utils.frontmatter.split_frontmatter`) and the search's load
    (:func:`_search_load_frontmatter`). The block (``None`` for a document with no frontmatter) lets the search check
    a record it would return against the base's reading (:func:`_base_reading_admits`).
    """
    block, rest = split_frontmatter(raw)
    if block is None:
        return {}, raw, None
    return _search_load_frontmatter(block), rest.strip(), block


def _base_reading_admits(
    block: str, *, scope: str, reader_id: str | None, reader_department: str,
) -> bool:
    """BF-952 A5: whether the base's reading of a frontmatter block admits this reader at ``scope``.

    That reading is ``read_entry``'s and the semantic index's (:func:`_load_frontmatter`). The search returns a
    record only where it admits the reader too, so no difference between libyaml's reading and the base's, known
    (RK8) or not, can show a reader a record the base's reading withholds (RK15; BF-679).
    """
    try:
        frontmatter = _load_frontmatter(block)
    except Exception:  # A5: read_entry raises on this block (a constructor error, a RecursionError)
        logger.debug("BF-952: withholding a record the base's reading cannot build", exc_info=True)
        return False  # A5: the search withholds what read_entry raises on
    return type(frontmatter) is dict and record_is_readable(
        frontmatter, scope=scope, reader_id=reader_id, reader_department=reader_department,
    )


def _search_record_counts(
    frontmatter: dict[str, Any], body: str, terms: list[str],
) -> tuple[dict[str, float], int]:
    """BF-952: each query term's weighted count in a record, and the record's length in words.

    A body occurrence counts 1 and a field of ``_SEARCH_FIELD_WEIGHTS`` its weight. A plain
    term counts each word (``\\w+``) equal to it, so ``952`` is found inside ``bf-952``; a term
    holding ``-`` or ``.`` counts each whole compound equal to it. The length counts words,
    whatever their weight. A record whose scored text holds no term even as a substring is
    only measured: a term counted as a word is always such a substring, so nothing is lost.
    """
    scored = [(body.lower(), 1.0)]
    scored.extend(
        (_search_field_text(frontmatter.get(name)).lower(), weight)
        for name, weight in _SEARCH_FIELD_WEIGHTS.items()
    )
    words = [_SEARCH_PART_RE.findall(text) for text, _ in scored]
    length = sum(len(found) for found in words)
    weights: dict[str, float] = {}
    if not any(term in text for text, _ in scored for term in terms):
        return weights, length
    compound_terms = [term for term in terms if "-" in term or "." in term]
    for (text, weight), found in zip(scored, words):
        if not found:
            continue
        word_counts = Counter(found)
        compound_counts = Counter(_SEARCH_TOKEN_RE.findall(text)) if compound_terms else word_counts
        for term in terms:
            count = compound_counts[term] if term in compound_terms else word_counts[term]
            if count:
                weights[term] = weights.get(term, 0.0) + weight * count
    return weights, length


def _search_records(
    search_path: Path,
    root: Path,
    terms: list[str],
    *,
    scope: str,
    reader_id: str | None,
    reader_department: str,
) -> list[dict]:
    """BF-952: the walk, parse and ranking of :meth:`RecordsStore.search`, run in a worker thread.

    It reads files under ``search_path`` and touches no store state, so it is safe off the
    event loop. Every record is parsed, not only those that match, because a term's rarity
    is counted over what this reader may read and over nothing else (A4). BF-958: the walk is
    the default listing's (:func:`_markdown_files`), and a file that resolves outside the
    repository is skipped before it is read, as :meth:`RecordsStore.list_entries` skips it.
    """
    repo = root.resolve()  # BF-958: root is the repository, resolved or as configured
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None]] = []
    for md_file in sorted(_markdown_files(search_path, strict=False)):
        rel_path = str(md_file.relative_to(root)).replace("\\", "/")
        if rel_path.startswith("_archived/"):
            continue
        try:
            if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the search reads
                logger.warning(
                    "BF-958: Ship's Records search skipped %s: it resolves outside the records repository (a link), "
                    "so it is not read; read_entry refuses it too",
                    rel_path,
                )
                continue
            raw = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
        try:
            frontmatter, content_text, block = _search_read_document(raw)
        except Exception:
            # A1, A5: YAML accepted the frontmatter and its constructor raised (``updated: 2026-13-05``
            # is a ``ValueError``, not a ``YAMLError``), or it nests too deep for PyYAML's composer
            # (``RecursionError``). ``read_entry`` raises for such a record; the search withholds it
            # rather than end every search or read it as ``{}``.
            logger.debug("BF-952: skipping %s, whose frontmatter cannot be constructed", rel_path, exc_info=True)
            continue
        if type(frontmatter) is not dict:
            # A non-empty YAML list or a truthy scalar names no classification; the record is
            # withheld rather than read at a default level (it raised on the base). A falsy one
            # (``[]``, ``false``, ``0``, ``''``) is ``{}``, as every reader has read it.
            logger.debug("BF-952: skipping %s, whose frontmatter is not a mapping", rel_path)
            continue
        # Classification scope + reader-identity check (BF-679)
        if not record_is_readable(
            frontmatter,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        ):
            continue
        weights, length = _search_record_counts(frontmatter, content_text, terms)
        readable.append((rel_path, frontmatter, content_text, weights, length, block))
    if not readable:
        return []

    count = len(readable)
    average_length = sum(entry[4] for entry in readable) / count
    rarity: dict[str, float] = {}
    for term in terms:
        holders = sum(1 for entry in readable if term in entry[3])
        rarity[term] = math.log(1.0 + (count - holders + 0.5) / (holders + 0.5))
    total_rarity = sum(rarity[term] for term in terms)

    ranked: list[tuple[tuple[Any, ...], dict[str, Any], str | None]] = []
    for rel_path, frontmatter, content_text, weights, length, block in readable:
        matched = [term for term in terms if term in weights]
        if not matched:
            continue
        coverage = min(1.0, sum(rarity[term] for term in matched) / total_rarity)
        norm = 1.0 - _SEARCH_BM25_B + _SEARCH_BM25_B * (length / average_length if average_length else 0.0)
        relevance = sum(
            rarity[term] * weights[term] * (_SEARCH_BM25_K1 + 1.0)
            / (weights[term] + _SEARCH_BM25_K1 * norm)
            for term in matched
        )
        written = record_write_time(frontmatter)
        key = (-coverage, -relevance, written is None, -(written or 0.0), rel_path)
        ranked.append((key, {
            "path": rel_path,
            "frontmatter": frontmatter,
            "score": coverage,
            "snippet": content_text[:200],
        }, block))
    ranked.sort(key=lambda pair: pair[0])
    results: list[dict] = []
    for _, result, block in ranked:
        # A5 (round 5): a record is returned only where the base's reading of it, read_entry's and the
        # semantic index's, admits this reader too. A record with no frontmatter reads as {} for both.
        if block is not None and not _base_reading_admits(
            block, scope=scope, reader_id=reader_id, reader_department=reader_department,
        ):
            continue
        results.append(result)
        if len(results) == _SEARCH_LIMIT:
            break
    return results


def _resolves_inside(path: Path, repo: Path) -> bool:
    """BF-958: whether ``path`` resolves inside ``repo`` (the resolved repository), :meth:`RecordsStore._safe_path`'s
    rule, which the listing and the search apply to each file their walk returns before reading it. A link loop
    resolves nowhere (``Path.resolve`` raises ``RuntimeError``), so it is not inside; an ``OSError`` propagates."""
    try:
        return path.resolve().is_relative_to(repo)
    except RuntimeError:
        return False  # Path.resolve raised RuntimeError: a link loop resolves nowhere, so it is outside


def _contained(path: Path, repo: Path, rel_path: str, reader: str) -> bool:
    """BF-959: whether a reader that lists or reads ``path`` itself may use it: it resolves inside ``repo`` (the
    resolved repository), :func:`_resolves_inside`'s rule. Never raises. A path outside, or in a link loop, is logged
    at WARNING by ``rel_path`` and not used; one whose resolution raises ``OSError`` is logged at DEBUG and not used
    either, as ``list_entries`` skips an unreadable file in its default mode."""
    try:
        inside = _resolves_inside(path, repo)
    except OSError:  # BF-959: a path whose resolution fails is not used, and is no error of the reader
        logger.debug(
            "BF-959: Ship's Records %s skipped %s: its path could not be resolved", reader, rel_path, exc_info=True,
        )
        return False  # BF-959: fail closed
    if not inside:
        logger.warning(
            "BF-959: Ship's Records %s skipped %s: it resolves outside the records repository (a link); "
            "read_entry refuses it too",
            reader, rel_path,
        )
    return inside


def _markdown_files(search_path: Path, *, strict: bool, pattern: str = "*.md") -> list[Path]:
    """AD-1341 S4 (A4, A5), BF-958, BF-959: every file named ``pattern`` (default ``*.md``) under ``search_path`` by a
    walk that descends no directory link; with ``strict``, or the ``OSError`` that hid one.

    A5 (round 3 R3-M1-1): ``os.walk`` filed an entry whose type it could not read as a file and never descended into
    it, as ``Path.rglob`` passed over a directory it could not list (A4): each standard walker absorbs some error. So
    this walk is explicit, and each filesystem operation it makes has one disposition (the AD-1341 S4 contract's 7.3a
    table, with BF-958's OJ row and default column):

    - O1 ``os.scandir(search_path)``: ``FileNotFoundError`` or ``NotADirectoryError`` lists nothing, since nothing
      was written under a directory that is not there. Any other ``OSError``: ``strict`` raises; the default lists
      nothing.
    - O2 ``os.scandir`` of a directory a listing reported: ``strict`` raises any ``OSError``, ``FileNotFoundError``
      included (gone since, or unaddressable, it is not proved empty; a strict caller refuses and is retried). The
      default passes over that directory, as ``rglob`` did.
    - O3 each step of a listing: any ``OSError`` raises, in both modes, as ``rglob``'s descent (``Path.walk``)
      raised one. ``rglob`` also matched each directory in a separate scan that swallowed one, so the base outlived
      a one-shot fault that hit that scan, losing that directory's own documents (BF-958 contract L10).
    - OJ ``entry.is_junction()`` (BF-958): a directory junction is not descended, and a WARNING names it, in both
      modes. ``is_dir(follow_symlinks=False)`` is true for a junction, so before BF-958 this walk descended one.
    - O4 ``entry.is_dir(follow_symlinks=False)``: the type comes from the listing record, so a symbolic link is not
      descended, as ``rglob`` descends none.

    An ``OSError`` from OJ or O4 raises with ``strict``, and the entry is never taken for a file; the default takes
    the entry for no directory, as ``rglob``'s walk did. Only a successful listing proves a document absent. A
    directory named ``*.md`` is no document and is not returned; the suffix matches with the platform's case rule
    (``fnmatch``), as ``rglob``'s does. Whether a returned file resolves inside the repository is the caller's
    check (:func:`_resolves_inside`).
    """
    found: list[Path] = []
    pending: list[Path] = [search_path]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)  # O1 for search_path, O2 below it
        except (FileNotFoundError, NotADirectoryError):
            if strict and directory is not search_path:
                raise  # O2 (A5): a directory a listing reported is never "no documents"
            continue  # O1: search_path does not exist, so nothing was written under it; O2 in the default mode
        except OSError:
            if strict:  # O1, O2: the strict walk raises what it cannot list
                raise
            logger.debug("Skipping a records directory that cannot be listed: %s", directory, exc_info=True)
            continue  # O1, O2 in the default mode, as rglob passed over it
        with listing:
            for entry in listing:  # O3: an OSError while listing propagates, in both modes
                path = Path(directory, entry.name)
                try:
                    if entry.is_junction():  # OJ (BF-958): never descended; it may lead out of the repository
                        logger.warning(
                            "BF-958: Ship's Records did not descend %s: it is a directory junction, which may lead "
                            "out of the records repository; the records behind it are not listed or searched there",
                            path,
                        )
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)  # O4
                except OSError:
                    if strict:  # OJ, O4: the strict walk never reads an unknown entry as a file
                        raise
                    is_dir = False  # BF-958: the default walk reads it as rglob's walk did, as no directory
                if is_dir:
                    pending.append(path)
                elif fnmatch.fnmatch(entry.name, pattern):  # BF-959
                    found.append(path)
    return found


class RecordsStore:
    """Git-backed institutional knowledge store for a ProbOS instance.

    Every document has YAML frontmatter with author, classification, status,
    department, topic, tags. Every write is a git commit. Git log = audit trail.
    """

    def __init__(self, config: Any, ontology: Any = None):
        self._config = config
        self._repo_path = Path(config.repo_path)
        self._ontology = ontology
        self._commit_lock = asyncio.Lock()
        # BF-957: one git child of this store at a time, held from launch until the child has exited.
        self._git_lock = threading.Lock()
        # BF-957: the git errors already logged, oldest first; read and written only under _git_warned_lock.
        self._git_warned: dict[tuple[str, str], None] = {}
        self._git_warned_lock = threading.Lock()
        self._pending_commits: list[str] = []
        self._commit_task: asyncio.Task | None = None
        self._confidence_tracker: Any = None
        self._semantic_indexer: Any = None  # AD-1138

    @property
    def repo_path(self) -> Path:
        return self._repo_path

    async def initialize(self) -> None:
        """Initialize the records repository. Creates dir + git init if needed."""
        self._repo_path.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in _SUBDIRS:
            (self._repo_path / subdir).mkdir(exist_ok=True)

        # Git init if not already a repo
        git_dir = self._repo_path / ".git"
        if not git_dir.exists():
            await self._git("init")
            # Configure local git identity for this repo
            await self._git("config", "user.email", "records@probos.local")
            await self._git("config", "user.name", "Ship Records")
            # Create .shiprecords.yaml config
            await self._write_config()
            await self._git("add", ".shiprecords.yaml")
            await self._git("commit", "-m", "Ship's Records initialized")
            logger.info("Ship's Records initialized: %s", self._repo_path)
        else:
            logger.info("Ship's Records loaded: %s", self._repo_path)

    async def write_entry(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
        *,
        classification: str = "ship",
        status: str = "draft",
        department: str = "",
        topic: str = "",
        tags: list[str] | None = None,
        metrics: dict[str, Any] | None = None,  # AD-553
        extra_frontmatter: dict[str, Any] | None = None,  # AD-1140
        preserve_classification_on_update: bool = False,  # AD-1157a
    ) -> str:
        """Write a document to Ship's Records.

        Generates YAML frontmatter, writes file, git add + commit.
        Returns the relative path of the created file.

        AD-1140: ``extra_frontmatter`` merges caller-owned envelope fields into
        the frontmatter **before** ``yaml.dump``. They round-trip through
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them), a
        value holding ``---`` included: the frontmatter ends at a line of its
        own (BF-940, #1686). ``yaml.dump`` writes a tuple or another Python
        object with a
        ``!!python/`` tag, which no reader loads (BF-952 L24). The AD-1138
        ``frontmatter_json`` sidecar holds them whole only within
        ``semantic.py``'s 4,000-character cap (``_RECORD_FRONTMATTER_CHARS``);
        past it the index stores ``{}``. Any key in
        :data:`_RESERVED_FRONTMATTER_KEYS` raises
        ``ValueError`` — this is the fail-fast tier, because silently dropping a
        reserved key would let a caller believe it stamped provenance that is
        not there. ``None`` (the default) leaves the written bytes identical.

        AD-1157a: ``preserve_classification_on_update`` keeps an existing
        document's classification when rewriting it, for callers that supplied
        no preference of their own. Update-in-place otherwise re-stamps every
        rewrite with the caller's default, so a routine AD-550 revision
        silently reclassifies a document nobody asked to reclassify — and
        because the write path is the same for a first draft and a revision,
        that default is applied to documents authored long before it existed.
        Ignored on create, where there is nothing to preserve.
        """
        # Validate classification
        if classification not in _CLASSIFICATION_LEVELS:
            raise ValueError(f"Invalid classification: {classification}")

        if extra_frontmatter is not None:
            if type(extra_frontmatter) is not dict:
                raise ValueError("extra_frontmatter must be a dict")
            collisions = sorted(
                key for key in extra_frontmatter
                if key in _RESERVED_FRONTMATTER_KEYS
            )
            if collisions:
                raise ValueError(
                    "extra_frontmatter may not set store-owned keys: "
                    + ", ".join(collisions)
                )

        # Build frontmatter
        now = datetime.now(timezone.utc).isoformat()
        frontmatter: dict[str, Any] = {
            "author": author,
            "classification": classification,
            "status": status,
            "created": now,
            "updated": now,
        }

        # AD-550: Update-in-place — preserve created timestamp + track revision
        file_path = self._safe_path(path)
        if file_path.exists():
            try:
                existing_raw = file_path.read_text(encoding="utf-8")
                existing_fm, _ = self._parse_document(existing_raw)
                if "created" in existing_fm:
                    frontmatter["created"] = existing_fm["created"]
                existing_rev = existing_fm.get("revision", 1)
                frontmatter["revision"] = existing_rev + 1
                # AD-1157a: the caller expressed no preference, so the author's
                # standing choice on this document outranks the caller default.
                # An unrecognised stored value is left to the default rather
                # than carried forward — it would fail the write validation
                # that already ran, turning a revision into a hard error.
                if preserve_classification_on_update:
                    existing_class = existing_fm.get("classification")
                    if existing_class in _CLASSIFICATION_LEVELS:
                        frontmatter["classification"] = existing_class
            except Exception:
                logger.debug("AD-550: Could not read existing frontmatter for update-in-place", exc_info=True)

        if department:
            frontmatter["department"] = department
        if topic:
            frontmatter["topic"] = topic
        if tags:
            frontmatter["tags"] = tags

        # AD-553: Attach metrics snapshot
        if metrics:
            frontmatter["metrics"] = metrics

        # AD-1140: caller-owned envelope fields. Reserved-key collisions were
        # already rejected above, so this can only add keys the store does not
        # own.
        if extra_frontmatter:
            frontmatter.update(extra_frontmatter)

        # Compose full document
        fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        full_content = f"---\n{fm_yaml}---\n\n{content}"

        # Write file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(full_content, encoding="utf-8")

        # Git add + commit
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")

        if self._confidence_tracker is not None:
            self._confidence_tracker.initialize_entry(path)

        # AD-1138: keep the semantic index current so a newly written record is
        # discoverable immediately rather than at the next backfill. Never let
        # indexing fail a write — the record is on disk and committed, and
        # keyword search already covers it.
        if self._semantic_indexer is not None:
            try:
                await self._semantic_indexer.index_record(
                    path=path,
                    content=content,
                    classification=frontmatter["classification"],
                    author=author,
                    department=department,
                    topic=topic,
                    tags=tags,
                    frontmatter=frontmatter,
                )
            except Exception:
                logger.warning(
                    "AD-1138: semantic indexing failed for %s; the record is written "
                    "and stays keyword-searchable until its next write or backfill",
                    path, exc_info=True,
                )

        logger.info("Record written: %s by %s (%s)", path, author, frontmatter["classification"])
        return path

    def set_semantic_indexer(self, indexer: Any) -> None:
        """AD-1138: Late-bind the semantic record indexer.

        Mirrors :meth:`set_confidence_tracker` (AD-444). Needed because the
        ``SemanticKnowledgeLayer`` is built in the structural-services startup
        phase, after the cognitive phase that constructs this store. The
        indexer is duck-typed on a single awaitable ``index_record(...)``
        method. ``None`` (the default) leaves ``write_entry`` byte-identical.
        """
        self._semantic_indexer = indexer

    def set_confidence_tracker(self, tracker: Any) -> None:
        """AD-444: Late-bind confidence tracker."""
        self._confidence_tracker = tracker

    async def confirm_entry(self, entry_path: str) -> float | None:
        """AD-444: Confirm an entry, increasing its confidence score."""
        if self._confidence_tracker is not None:
            return self._confidence_tracker.confirm(entry_path)
        return None

    async def contradict_entry(self, entry_path: str) -> float | None:
        """AD-444: Contradict an entry, decreasing its confidence score."""
        if self._confidence_tracker is not None:
            return self._confidence_tracker.contradict(entry_path)
        return None

    async def seed_manuals(self, source_dir: Path) -> int:
        """Seed manuals from source directory into ship-records/manuals/.

        BF-084: Copies markdown files from config/manuals/ to manuals/ with
        ship-classified frontmatter. Overwrites existing (shipyard-managed).
        Returns count of seeded manuals.
        """
        if not source_dir.is_dir():
            logger.info("BF-084: Manual source dir %s not found, skipping", source_dir)
            return 0

        count = 0
        for md_file in sorted(source_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            path = f"manuals/{md_file.name}"
            await self.write_entry(
                author="shipyard",
                path=path,
                content=content,
                message=f"Seed manual: {md_file.stem}",
                classification="ship",
                status="published",
                topic=md_file.stem,
                tags=["manual"],
            )
            count += 1

        if count:
            logger.info("BF-084: Seeded %d manual(s) into Ship's Records", count)
        return count

    async def append_captains_log(self, content: str, message: str = "") -> str:
        """Append an entry to the Captain's Log.

        Append-only, daily files, always ship-classified.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"captains-log/{today}.md"
        file_path = self._repo_path / path

        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        entry = f"\n### {timestamp}\n\n{content}\n"

        if file_path.exists():
            # Append to existing daily file
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing + entry, encoding="utf-8")
        else:
            # New daily file with frontmatter
            frontmatter = {
                "author": "captain",
                "classification": "ship",
                "status": "published",
                "created": datetime.now(timezone.utc).isoformat(),
            }
            fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f"---\n{fm_yaml}---\n\n# Captain's Log — {today}\n{entry}", encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(message or f"[captains-log] Entry for {today}")

        logger.info("Captain's Log entry appended: %s", path)
        return path

    async def write_notebook(
        self,
        callsign: str,
        topic_slug: str,
        content: str,
        *,
        department: str = "",
        tags: list[str] | None = None,
        classification: str | None = None,
        metrics: dict[str, Any] | None = None,  # AD-553
        extra_frontmatter: dict[str, Any] | None = None,  # AD-1140
    ) -> str:
        """Write to an agent's notebook.

        Creates or updates notebooks/{callsign}/{topic_slug}.md

        AD-1140: ``extra_frontmatter`` is passed straight through to
        :meth:`write_entry`; see its docstring for the reserved-key contract.

        AD-1157: ``classification`` of ``None`` means *the author expressed no
        preference*, and is not the same as passing the default explicitly. A
        new entry takes :data:`NOTEBOOK_DEFAULT_CLASSIFICATION` (``private``),
        matching the records ontology; an existing entry keeps whatever it
        already has. A concrete value is the author's own choice and is applied
        either way — an agent that tags ``[NOTEBOOK slug ship]`` on a note it
        wrote last week means to widen that note, and an agent that tags it
        ``private`` means to pull it back.

        A notebook is an agent's own working surface; the governed route into
        the shared commons is ``publish_finding`` (AD-1140), which writes at
        ``ship`` and always passes its classification explicitly.

        Note that ``private`` binds on the *query* path only (BF-679). The
        AD-550 dedup gate and the AD-554 cross-agent convergence scan both read
        notebook files directly off disk and are unaffected, so curation and
        convergence continue to see the full corpus.
        """
        if not callsign or not callsign.strip():  # BF-218: guard against empty callsign
            raise ValueError("callsign must not be empty for notebook writes")
        path = f"notebooks/{callsign}/{topic_slug}.md"
        self._safe_path(path)  # Validate before delegating to write_entry
        return await self.write_entry(
            author=callsign,
            path=path,
            content=content,
            message=f"{callsign} notebook: {topic_slug}",
            classification=(
                NOTEBOOK_DEFAULT_CLASSIFICATION
                if classification is None
                else classification
            ),
            preserve_classification_on_update=(classification is None),
            status="draft",
            department=department,
            topic=topic_slug,
            tags=tags,
            metrics=metrics,
            extra_frontmatter=extra_frontmatter,
        )

    async def write_bill(
        self,
        bill_id: str,
        content: str,
        author: str = "captain",
        *,
        version: int = 1,
    ) -> str:
        """Write a Bill YAML file to Ship's Records (AD-618a).

        Bypasses write_entry() — bills are raw YAML, not markdown with
        frontmatter. write_entry() wraps content in ``---\\nfrontmatter\\n---``
        which would corrupt the bill YAML and make it unparseable by
        parse_bill_file(). Uses _safe_path() for traversal prevention,
        writes directly, then git add + commit.

        Args:
            bill_id: Unique bill identifier (slug, e.g. "research-consultation").
            content: Full YAML content of the bill. Not validated against the
                bill schema — callers should use parse_bill() first if they
                want pre-write validation. Raw write supports drafts and
                authoring workflows.
            author: Who authored this bill.
            version: Bill version number.

        Returns:
            Relative path of the created file.
        """
        filename = f"{bill_id}.bill.yaml"
        rel_path = f"bills/{filename}"

        file_path = self._safe_path(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", rel_path)
            await self._commit(
                f"[records] [bill] {bill_id} v{version} — authored by {author}"
            )

        logger.info("Bill written: %s by %s", rel_path, author)
        return rel_path

    async def list_bills(self) -> list[dict]:
        """List all Bill files in Ship's Records (AD-618a).

        Bypasses list_entries() — bills are .bill.yaml files, not .md.
        list_entries() lists only *.md files, so it would never find them.

        Returns:
            List of dicts with 'path' and 'bill_id' keys for each bill.
        """
        bills_dir = self._safe_path("bills")
        if not bills_dir.exists():
            return []

        results = []
        # BF-949 R1: bills_dir comes from _safe_path, which resolves, so its paths are taken against the resolved root
        root = self._repo_path.resolve()
        for yaml_file in sorted(_markdown_files(bills_dir, strict=False, pattern="*.bill.yaml")):  # BF-959
            rel_path = str(yaml_file.relative_to(root)).replace("\\", "/")
            if not _contained(yaml_file, root, rel_path, "bill listing"):  # BF-959
                continue
            # Extract bill_id from filename (e.g. "research-consultation.bill.yaml" → "research-consultation")
            bill_id = yaml_file.name.removesuffix(".bill.yaml")
            results.append({"path": rel_path, "bill_id": bill_id})

        return results

    async def check_notebook_similarity(
        self,
        callsign: str,
        topic_slug: str,
        new_content: str,
        *,
        similarity_threshold: float = 0.8,
        staleness_hours: float = 72.0,
        max_scan_entries: int = 20,
    ) -> dict:
        """AD-550: Check if a notebook write is redundant.

        Returns:
            {
                "action": "write" | "update" | "suppress",
                "reason": str,
                "existing_path": str | None,
                "existing_content": str | None,
                "similarity": float,
            }
        """
        no_match: dict[str, Any] = {
            "action": "write",
            "reason": "no_existing_entry",
            "existing_path": None,
            "existing_content": None,
            "similarity": 0.0,
            # AD-552: Frequency metadata
            "revision": 0,
            "created_iso": None,
            "updated_iso": None,
            # AD-553: Previous metrics for baseline delta
            "existing_metrics": {},
        }

        now = datetime.now(timezone.utc)
        staleness_cutoff = now.timestamp() - (staleness_hours * 3600)

        # --- Layer 2: Exact topic match ---
        exact_path = f"notebooks/{callsign}/{topic_slug}.md"
        exact_file = self._safe_path(exact_path)
        if exact_file.exists():
            try:
                raw = exact_file.read_text(encoding="utf-8")
                fm, existing_content = self._parse_document(raw)
                updated_str = fm.get("updated", "")
                entry_ts = 0.0
                if updated_str:
                    try:
                        entry_ts = datetime.fromisoformat(updated_str).timestamp()
                    except (ValueError, TypeError):
                        pass

                similarity = _jaccard_similarity(new_content, existing_content)

                # AD-552: Extract frequency metadata from frontmatter
                _revision = fm.get("revision", 1)
                _created_iso = fm.get("created", None)
                _updated_iso = fm.get("updated", None)
                # AD-553: Extract existing metrics for baseline delta
                _existing_metrics = fm.get("metrics", {})

                if entry_ts > staleness_cutoff and similarity >= similarity_threshold:
                    return {
                        "action": "suppress",
                        "reason": "content unchanged from recent entry",
                        "existing_path": exact_path,
                        "existing_content": existing_content,
                        "similarity": similarity,
                        "revision": _revision,
                        "created_iso": _created_iso,
                        "updated_iso": _updated_iso,
                        "existing_metrics": _existing_metrics,
                    }

                if entry_ts <= staleness_cutoff:
                    return {
                        "action": "update",
                        "reason": "stale entry, refreshing",
                        "existing_path": exact_path,
                        "existing_content": existing_content,
                        "similarity": similarity,
                        "revision": _revision,
                        "created_iso": _created_iso,
                        "updated_iso": _updated_iso,
                        "existing_metrics": _existing_metrics,
                    }

                # Fresh but different content → update
                return {
                    "action": "update",
                    "reason": "different content for same topic",
                    "existing_path": exact_path,
                    "existing_content": existing_content,
                    "similarity": similarity,
                    "revision": _revision,
                    "created_iso": _created_iso,
                    "updated_iso": _updated_iso,
                    "existing_metrics": _existing_metrics,
                }
            except Exception:
                logger.debug("AD-550: Error reading existing notebook entry", exc_info=True)

        # --- Layer 3: Cross-topic scan ---
        notebook_dir = self._repo_path / "notebooks" / callsign
        if notebook_dir.is_dir():
            try:
                entries: list[tuple[float, Path]] = []
                repo = self._repo_path.resolve()  # BF-959: layer 3 compares resolved paths
                for md_file in notebook_dir.glob("*.md"):
                    if md_file.name == f"{topic_slug}.md":
                        continue  # Already checked above
                    try:
                        rel_path = f"notebooks/{callsign}/{md_file.name}"
                        if not _contained(md_file, repo, rel_path, "notebook similarity check"):  # BF-959
                            continue
                        raw = md_file.read_text(encoding="utf-8")
                        fm, _ = self._parse_document(raw)
                        updated_str = fm.get("updated", "")
                        entry_ts = 0.0
                        if updated_str:
                            try:
                                entry_ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        if entry_ts > staleness_cutoff:
                            entries.append((entry_ts, md_file))
                    except Exception:
                        continue

                # Sort by recency, cap scan
                entries.sort(key=lambda x: x[0], reverse=True)
                for _, md_file in entries[:max_scan_entries]:
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        _, existing_content = self._parse_document(raw)
                        similarity = _jaccard_similarity(new_content, existing_content)
                        if similarity >= similarity_threshold:
                            matched_path = f"notebooks/{callsign}/{md_file.name}"
                            return {
                                "action": "suppress",
                                "reason": f"similar content exists at {matched_path}",
                                "existing_path": matched_path,
                                "existing_content": existing_content,
                                "similarity": similarity,
                            }
                    except Exception:
                        continue
            except Exception:
                logger.debug("AD-550: Cross-topic scan failed", exc_info=True)

        return no_match

    async def check_cross_agent_convergence(
        self,
        anchor_callsign: str,
        anchor_department: str,
        anchor_topic_slug: str,
        anchor_content: str,
        *,
        convergence_threshold: float = 0.5,
        divergence_threshold: float = 0.3,
        staleness_hours: float = 72.0,
        max_scan_per_agent: int = 5,
        min_convergence_agents: int = 2,
        min_convergence_departments: int = 2,
    ) -> dict[str, Any]:
        """AD-554: Incremental cross-agent convergence/divergence scan.

        Anchored on a just-written entry, scans recent notebooks from OTHER
        agents in OTHER departments for convergent or divergent conclusions.
        """
        result: dict[str, Any] = {
            "convergence_detected": False,
            "convergence_agents": [],
            "convergence_departments": [],
            "convergence_coherence": 0.0,
            "convergence_topic": "",
            "convergence_matches": [],
            "convergence_independence_score": 0.0,  # AD-583
            "convergence_is_independent": True,      # AD-583
            "divergence_detected": False,
            "divergence_agents": [],
            "divergence_departments": [],
            "divergence_topic": "",
            "divergence_similarity": 1.0,
            "divergence_matches": [],
        }

        notebooks_dir = self._repo_path / "notebooks"
        if not notebooks_dir.is_dir():
            return result

        now = datetime.now(timezone.utc)
        staleness_cutoff = now.timestamp() - (staleness_hours * 3600)

        convergence_matches: list[dict[str, Any]] = []
        divergence_matches: list[dict[str, Any]] = []

        # Scan other agents' notebook directories
        try:
            repo = self._repo_path.resolve()  # BF-959: the scan compares resolved paths
            for agent_dir in sorted(notebooks_dir.iterdir()):
                if not agent_dir.is_dir():
                    continue
                other_callsign = agent_dir.name
                if other_callsign == anchor_callsign:
                    continue  # Skip self
                if agent_dir.is_junction() or agent_dir.is_symlink():  # BF-959: a directory link is never scanned
                    logger.warning(
                        "BF-959: Ship's Records convergence scan did not scan notebooks/%s: it is a directory link "
                        "(a junction or a symbolic link), which may lead out of the records repository; the "
                        "notebooks behind it are not read",
                        other_callsign,
                    )
                    continue

                # Collect recent entries for this agent
                entries: list[tuple[float, Path, str, str]] = []  # (ts, path, topic, dept)
                for md_file in agent_dir.glob("*.md"):
                    try:
                        rel_path = f"notebooks/{other_callsign}/{md_file.name}"
                        if not _contained(md_file, repo, rel_path, "convergence scan"):  # BF-959
                            continue
                        raw = md_file.read_text(encoding="utf-8")
                        fm, content = self._parse_document(raw)
                        updated_str = fm.get("updated", "")
                        entry_ts = 0.0
                        if updated_str:
                            try:
                                entry_ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        if entry_ts <= staleness_cutoff:
                            continue
                        dept = fm.get("department", "")
                        topic = fm.get("topic", md_file.stem)
                        entries.append((entry_ts, md_file, topic, dept))
                    except Exception:
                        continue

                # Sort by recency, cap scan
                entries.sort(key=lambda x: x[0], reverse=True)
                for _, md_file, topic, dept in entries[:max_scan_per_agent]:
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        fm, content = self._parse_document(raw)
                        similarity = _jaccard_similarity(anchor_content, content)
                        rel_path = f"notebooks/{other_callsign}/{md_file.name}"
                        match_info = {
                            "callsign": other_callsign,
                            "department": dept,
                            "topic_slug": topic,
                            "similarity": similarity,
                            "path": rel_path,
                            "content": content,
                            "frontmatter": fm,  # AD-583: preserved for anchor independence
                        }

                        # Convergence: high similarity from different department
                        if similarity >= convergence_threshold and dept and dept != anchor_department:
                            convergence_matches.append(match_info)

                        # Divergence: same topic, low similarity, different department
                        if (
                            topic == anchor_topic_slug
                            and similarity < divergence_threshold
                            and dept
                            and dept != anchor_department
                        ):
                            divergence_matches.append(match_info)
                    except Exception:
                        continue
        except Exception:
            logger.debug("AD-554: Cross-agent scan error", exc_info=True)
            return result

        # Evaluate convergence
        if convergence_matches:
            conv_agents = {anchor_callsign}
            conv_depts = {anchor_department}
            for m in convergence_matches:
                conv_agents.add(m["callsign"])
                conv_depts.add(m["department"])

            if len(conv_agents) >= min_convergence_agents and len(conv_depts) >= min_convergence_departments:
                # Compute coherence (average pairwise similarity among converging entries)
                similarities = [m["similarity"] for m in convergence_matches]
                coherence = sum(similarities) / len(similarities) if similarities else 0.0

                # Infer topic from common words
                from collections import Counter as _Counter
                all_words: list[str] = []
                all_words.extend(anchor_content.lower().split()[:50])
                for m in convergence_matches:
                    all_words.extend(m.get("content", "").lower().split()[:50])
                common = _Counter(all_words).most_common(3)
                topic = "-".join(w for w, _ in common) if common else anchor_topic_slug

                result["convergence_detected"] = True
                result["convergence_agents"] = sorted(conv_agents)
                result["convergence_departments"] = sorted(conv_depts)
                result["convergence_coherence"] = coherence
                result["convergence_topic"] = topic
                result["convergence_matches"] = [
                    {k: v for k, v in m.items() if k not in ("content", "frontmatter")}
                    for m in convergence_matches
                ]

                # AD-583: Compute anchor independence for converging entries
                try:
                    from types import SimpleNamespace
                    from probos.cognitive.social_verification import compute_anchor_independence

                    independence_threshold = convergence_threshold  # reuse param as fallback
                    try:
                        # Try to get config threshold
                        from probos.config import RecordsConfig as _RC583
                        _rc = _RC583()
                        independence_threshold = _rc.convergence_independence_threshold
                    except Exception:
                        independence_threshold = 0.3

                    episodes = []
                    for m in convergence_matches:
                        fm = m.get("frontmatter", {})
                        anchors = SimpleNamespace(
                            duty_cycle_id=fm.get("duty_cycle_id", ""),
                            channel_id=fm.get("channel_id", ""),
                            thread_id=fm.get("thread_id", ""),
                        )
                        ts = 0.0
                        updated_str = fm.get("updated", "")
                        if updated_str:
                            try:
                                ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        episodes.append(SimpleNamespace(anchors=anchors, timestamp=ts))

                    independence_score = compute_anchor_independence(episodes)
                    result["convergence_independence_score"] = independence_score
                    result["convergence_is_independent"] = independence_score >= independence_threshold
                except Exception:
                    # Non-critical — default to conservative (potentially pathological)
                    result["convergence_independence_score"] = 0.0
                    result["convergence_is_independent"] = False

        # Evaluate divergence
        if divergence_matches:
            div_agents = {anchor_callsign}
            div_depts = {anchor_department}
            lowest_sim = 1.0
            for m in divergence_matches:
                div_agents.add(m["callsign"])
                div_depts.add(m["department"])
                if m["similarity"] < lowest_sim:
                    lowest_sim = m["similarity"]

            result["divergence_detected"] = True
            result["divergence_agents"] = sorted(div_agents)
            result["divergence_departments"] = sorted(div_depts)
            result["divergence_topic"] = anchor_topic_slug
            result["divergence_similarity"] = lowest_sim
            result["divergence_matches"] = [
                {k: v for k, v in m.items() if k != "content"} for m in divergence_matches
            ]

        return result

    async def read_entry(
        self,
        path: str,
        reader_id: str,
        reader_department: str = "",
    ) -> dict | None:
        """Read a document, enforcing classification access control.

        Returns {"frontmatter": {...}, "content": "..."} or None if denied.
        """
        file_path = self._safe_path(path)
        if not file_path.exists():
            return None

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content = self._parse_document(raw)

        # Classification check — Captain has unrestricted read access
        if reader_id != "captain":
            doc_class = frontmatter.get("classification", "ship")
            doc_author = frontmatter.get("author", "")
            doc_dept = frontmatter.get("department", "")

            if doc_class == "private" and reader_id != doc_author:
                return None
            if doc_class == "department" and reader_department != doc_dept and reader_id != doc_author:
                return None
            # ship and fleet are readable by all crew

        return {"frontmatter": frontmatter, "content": content, "path": path}

    async def list_entries(
        self,
        directory: str = "",
        *,
        author: str = "",
        status: str = "",
        tags: list[str] | None = None,
        classification: str = "",
        strict: bool = False,
    ) -> list[dict]:
        """List documents with optional filters.

        Returns list of {"path": ..., "frontmatter": {...}} dicts.

        A file that cannot be read is skipped and logged at debug. AD-1341 S4 (A2): ``strict=True`` re-raises an
        ``OSError`` reading a listed regular file instead (a sharing violation, a permission, an I/O error: the file
        exists but cannot be read now), for a caller that must not take an unreadable document for an absent one (the
        AD-754 erasure's read of pending exit notes, and the stand-down). Bytes that are not UTF-8 are still skipped:
        that is a property of the file, not of the moment. ``False`` (the default) keeps every other caller unchanged.
        A4, A5: ``strict=True`` walks with ``_markdown_files(strict=True)``, which raises every ``OSError`` that could
        leave a document unseen (a directory it cannot open, a listing step that fails, an entry whose type it cannot
        read) and reads only a missing ``directory`` as empty. A listed file whose read fails raises for any
        ``OSError``, with no second look at whether it is still a file (A5).

        BF-958: in both modes the walk does not descend a directory junction, and a listed file that resolves outside
        the repository (a link; :meth:`read_entry` refuses it) is skipped. Each is logged at WARNING; neither raises.
        """
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        repo = self._repo_path.resolve()  # BF-958: the containment rule compares resolved paths
        results = []
        # AD-1341 S4 (A4), BF-958: one walk for both modes; only the strict mode raises what hid a document
        found = _markdown_files(search_path, strict=strict)

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
            # Skip archived
            if rel_path.startswith("_archived/"):
                continue
            try:
                if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the listing reads
                    logger.warning(
                        "BF-958: Ship's Records listing skipped %s: it resolves outside the records repository "
                        "(a link), so it is not listed; read_entry refuses it too",
                        rel_path,
                    )
                    continue
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
            except OSError:
                if strict:  # A5 (O5): a file the walk listed is never "no document", whatever the read's error
                    raise  # AD-1341 S4 (A2): a file that exists but cannot be read now is never "no document"
                logger.debug("Skipping unreadable file", exc_info=True)
                continue
            except Exception:
                logger.debug("Skipping unreadable file", exc_info=True)
                continue

            # Apply filters
            if author and fm.get("author") != author:
                continue
            if status and fm.get("status") != status:
                continue
            if classification and fm.get("classification") != classification:
                continue
            if tags and not set(tags).issubset(set(fm.get("tags", []))):
                continue

            results.append({"path": rel_path, "frontmatter": fm})

        return results

    async def get_history(self, path: str, limit: int = 20) -> list[dict]:
        """Get git log for a specific file.

        BF-957 A5, A7: one ``git log`` with ``--encoding=UTF-8``, which overrides an operator's
        ``i18n.logOutputEncoding``. Git outputs an unlabelled commit's subject as stored and converts a labelled
        commit's subject from its encoding label to UTF-8. The store's own commits carry no label: ``_git_sync``
        runs every ``git commit`` with ``i18n.commitEncoding=UTF-8`` (A7), because an operator's setting would
        label the store's UTF-8 messages without converting them. A commit an older store labelled that way is
        read as git converts it (contract L15). Fields are separated by NUL (A6).
        """
        self._safe_path(path)  # Validate — raises ValueError if traversal
        try:
            result = await self._git(
                "log", f"--max-count={limit}",
                "--encoding=UTF-8", "--format=%H%x00%aI%x00%s",  # BF-957 A5, A7: one read, UTF-8 output
                "--follow", "--", path
            )
            entries = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\x00", 2)
                if len(parts) == 3:
                    entries.append({"commit": parts[0], "timestamp": parts[1], "message": parts[2]})
            return entries
        except Exception:
            logger.debug("Git query failed", exc_info=True)
            return []

    async def publish(self, path: str, author: str) -> None:
        """Promote a document from draft to published status."""
        file_path = self._safe_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Record not found: {path}")

        raw = file_path.read_text(encoding="utf-8")
        fm, content = self._parse_document(raw)

        if fm.get("author") != author and author != "captain":
            raise PermissionError("Only the author or Captain can publish")

        fm["status"] = "published"
        fm["updated"] = datetime.now(timezone.utc).isoformat()

        fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        file_path.write_text(f"---\n{fm_yaml}---\n\n{content}", encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] Published: {path} — by {author}")

    async def search(
        self,
        query: str,
        scope: str = "ship",
        *,
        reader_id: str | None = None,
        reader_department: str = "",
        directory: str = "",
    ) -> list[dict]:
        """Keyword search across records.

        BF-952: a record matches on whole words of its body and of the values of
        its ``title``, ``topic``, ``tags``, ``department`` and ``author``
        frontmatter, never on a YAML key or on part of a word. The query's
        stopwords are dropped; a query made only of stopwords keeps them all, and
        a query with no words finds nothing. Records rank by how much of the
        query's rarity they hold, then by BM25 relevance with title, topic and tag
        hits weighted above body hits, then by the newer ``updated`` (else
        ``created``), then by path. ``score`` is the first of these: the summed
        rarity (IDF) of the query terms the record holds over that of all of them,
        between 0 and 1, and it never rises down the list. Rarity is counted only
        over the records this reader may read, so a record withheld from the
        reader cannot move the scores it is shown. A record whose frontmatter is
        a non-empty YAML list or a truthy scalar, or one YAML's constructor cannot
        build (``updated: 2026-13-05``), is skipped; one whose frontmatter does not
        parse reads as ``{}``, as every reader reads it (A3; BF-940, #1686). A
        number in ``title``, ``topic``, ``tags``, ``department`` or ``author`` is
        scored as text; a boolean is not. At most 20 results. The walk, parse and
        ranking (:func:`_search_records`) run in a worker thread, so a search does
        not block the event loop; ``scope`` and ``directory`` are checked first, here.

        BF-679: ``reader_id`` / ``reader_department`` add the identity layer
        :meth:`read_entry` applies, so a caller that knows who is asking no
        longer receives another crew member's ``private`` or out-of-department
        records. The default ``reader_id=None`` means *identity not specified*
        and applies the scope level only; see :func:`record_is_readable` for the
        full tri-state contract.

        BF-949: ``scope`` is one of the four classification labels; any other
        value raises ``ValueError``. ``directory`` confines the walk to that
        directory of the repository, validated as :meth:`list_entries` validates
        it (a path that leaves the repository raises ``ValueError``); ``""`` walks
        the whole repository.
        """
        if type(scope) is not str or scope not in _CLASSIFICATION_LEVELS:
            raise ValueError(
                "Unknown records scope; expected one of: "
                + ", ".join(_CLASSIFICATION_LEVELS)
            )
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        terms = _search_query_terms(query)
        if not terms:
            return []
        # BF-952: the walk parses every readable record (A4), most of a second on a ship's
        # corpus, so it runs in a worker thread and the event loop stays free meanwhile.
        return await asyncio.to_thread(
            _search_records,
            search_path,
            root,
            terms,
            scope=scope,
            reader_id=reader_id,
            reader_department=reader_department,
        )

    async def get_stats(self) -> dict:
        """Get repository statistics.

        BF-959: one walk of the repository (:func:`_markdown_files`, which descends no directory junction) counts the
        ``*.md`` files that resolve inside it, ``_archived`` included; a file that resolves outside (a link) is logged
        at WARNING and not counted. Each directory's count is taken from that list by the file's first path component.
        """
        repo = self._repo_path.resolve()  # BF-959: the statistics compare resolved paths
        counted: list[Path] = []  # BF-959: the repository-relative path of each file counted
        for md_file in _markdown_files(self._repo_path, strict=False):
            rel = md_file.relative_to(self._repo_path)
            if _contained(md_file, repo, rel.as_posix(), "statistics"):  # BF-959
                counted.append(rel)
        doc_count = len(counted)
        try:
            commit_count_str = await self._git("rev-list", "--count", "HEAD")
            commit_count = int(commit_count_str.strip())
        except Exception:
            logger.debug("Git query failed", exc_info=True)
            commit_count = 0

        # Count by directory
        dir_counts: dict[str, int] = {}
        for subdir in _SUBDIRS:
            if subdir.startswith("_"):
                continue
            if (self._repo_path / subdir).exists():
                dir_counts[subdir] = sum(1 for p in counted if p.parts[0] == subdir)  # BF-959

        return {
            "total_documents": doc_count,
            "total_commits": commit_count,
            "repo_path": str(self._repo_path),
            "directories": dir_counts,
        }

    # --- Internal helpers ---

    # ------------------------------------------------------------------
    # AD-594a: Raw-file surfaces (no frontmatter coercion)
    # Used by ConsultationWorkspace for manifest.yaml / journal.md / plan files /
    # work-item YAML / per-advisory artifacts. Reuses _safe_path for traversal
    # protection and _commit for the git plumbing. Never raises path-traversal
    # errors silently — _safe_path raises ValueError; callers (WorkspaceRegistry)
    # treat that as a programmer error.
    # ------------------------------------------------------------------
    async def write_workspace_file(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
    ) -> str:
        """AD-594a: Write a raw text file (no YAML frontmatter wrapper).

        Args:
            author: Author identity for the git commit.
            path: Repo-relative path (e.g. ``consultations/<id>/manifest.yaml``).
            content: Raw text to write (UTF-8). For binary use, encode upstream.
            message: Commit message body.

        Returns the relative path of the written file.
        """
        file_path = self._safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")
        logger.debug("AD-594a: workspace file written: %s by %s", path, author)
        return path

    async def read_workspace_file(self, path: str) -> str | None:
        """AD-594a: Read a raw text file. Returns None if missing."""
        file_path = self._safe_path(path)
        if not file_path.exists():
            return None
        return file_path.read_text(encoding="utf-8")

    async def append_workspace_file(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
    ) -> str:
        """AD-594a: Append text to a raw file (e.g. journal.md). Creates if absent."""
        file_path = self._safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as fh:
            fh.write(content)
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")
        logger.debug("AD-594a: workspace file appended: %s by %s", path, author)
        return path

    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document.

        BF-940 (#1686): the frontmatter ends at the first later line of only hyphens, so a value holding ``---``
        stays whole (:func:`probos.utils.frontmatter.split_frontmatter`). The YAML is loaded here, in this frame,
        so PyYAML's recursion frontier is the one the base had (BF-952 A6, L30).
        """
        block, rest = split_frontmatter(raw)
        if block is None:
            return {}, raw
        try:
            fm = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            fm = {}
        return fm, rest.strip()

    def _safe_path(self, user_path: str) -> Path:
        """Validate and resolve a user-supplied path, preventing traversal.

        Raises ValueError if the resolved path escapes the records repo.
        """
        resolved = (self._repo_path / user_path).resolve()
        repo_resolved = self._repo_path.resolve()

        if not resolved.is_relative_to(repo_resolved):
            raise ValueError(f"Path traversal denied: {user_path!r}")

        return resolved

    async def _write_config(self) -> None:
        """Write the .shiprecords.yaml configuration file."""
        config = {
            "version": "1.0",
            "retention_policies": {
                "captains_log": "permanent",
                "published_reports": "permanent",
                "active_notebooks": "archive_90_days_inactive",
                "draft_notebooks": "archive_365_days",
                "operations": "until_superseded",
            },
            "classification_default": "department",
        }
        config_path = self._repo_path / ".shiprecords.yaml"
        config_path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    async def _git(self, *args: str) -> str:
        """Run a git command in the records repo."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._git_sync, args)

    def _git_sync(self, args: tuple[str, ...]) -> str:
        """Synchronous git execution.

        BF-957: at most one git child of this store runs at a time (``_git_lock``, held until the child has
        exited and its result is classified), so the store's own commands never meet at the index lock, and the
        once-per-error memory changes in the order the children ran. A non-zero exit is logged at WARNING once
        per distinct error, with git's first output line only, and its stdout is returned as before; a commit
        with nothing staged is not an error. A command that outlives the timeout is stopped by
        ``subprocess.run``; this logs a WARNING, because what it changed is not known and a lock it held may
        remain, and re-raises the same exception. A4: the WARNING is emitted after this call releases
        ``_git_lock``, so a log handler that reads git through this store does not wait on this call; it can
        still wait for a command another thread is running (contract L14). Git's output is decoded as UTF-8
        with replacement, so a locale codec (cp1252) that cannot decode it no longer turns it into ``None``.
        Git re-encodes a commit subject for a configured encoding, so ``get_history`` asks for UTF-8 output. A7:
        ``git commit`` alone runs with ``-c i18n.commitEncoding=UTF-8`` (``pin``), so an operator's setting cannot
        label the store's UTF-8 messages without converting them; no other command's argv changes.
        """
        verb = args[0] if args else ""
        # BF-957 A7: the store writes UTF-8; an operator's i18n.commitEncoding would label it without converting
        pin = ("-c", "i18n.commitEncoding=UTF-8") if verb == "commit" else ()
        due: tuple[object, ...] = ()  # BF-957 A4: the WARNING, emitted once _git_lock is released
        try:
            with self._git_lock:
                try:
                    result = subprocess.run(
                        ["git", *pin, *args],
                        env=trusted_command_env(),
                        cwd=str(self._repo_path),
                        capture_output=True,
                        encoding="utf-8",  # BF-957 A4: the locale's codec (cp1252) lost output; A5: see get_history
                        errors="replace",
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    if self._remember_git_warning((verb, "timeout")):
                        due = (
                            "Ship's Records: git %s did not finish in 30 s and was stopped. What it changed is "
                            "not known, and a lock file it held may remain in %s. `probos doctor` reports the "
                            "repository's state.",
                            verb,
                            self._repo_path / ".git",
                        )
                    raise
                # BF-957 A3: classified under the lock, so a later child's warning is never cleared by an earlier success.
                if result.returncode == 0:
                    if verb in _GIT_INDEX_VERBS:
                        self._forget_git_warnings()
                    return result.stdout
                if any(phrase in result.stdout for phrase in _GIT_NOTHING_STAGED):
                    return result.stdout
                error = _git_error_line(result.stderr, result.stdout)
                if self._remember_git_warning((verb, error)):
                    due = (
                        "Ship's Records: git %s failed (exit %d): %s. Records are still written to disk, but a "
                        "failed add or commit leaves them out of the records history. This error is logged once "
                        "until a git add or commit succeeds; `probos doctor` reports the repository's state.",
                        verb,
                        result.returncode,
                        error,  # BF-957 A3: git's first line only; the rest may advise removing a lock without the precondition
                    )
                return result.stdout
        finally:
            if due:  # BF-957 A4: after _git_lock is released; a log handler may read git through this store
                logger.warning(*due)

    def _remember_git_warning(self, key: tuple[str, str]) -> bool:
        """BF-957 A4: remember ``key``; True when it was not logged since the last successful git add or commit.

        At most ``_GIT_WARNED_MAX`` keys are remembered; past that the oldest is dropped and may be logged again.
        The caller logs when this returns True; ``_git_sync`` does so after releasing ``_git_lock``.
        """
        with self._git_warned_lock:
            if key in self._git_warned:
                return False
            if len(self._git_warned) >= _GIT_WARNED_MAX:
                self._git_warned.pop(next(iter(self._git_warned)))
            self._git_warned[key] = None
            return True

    def _warn_git_once(self, key: tuple[str, str], msg: str, *args: object) -> None:
        """BF-957: log ``msg`` at WARNING unless ``key`` was logged since the last successful git add or commit."""
        if self._remember_git_warning(key):
            logger.warning(msg, *args)

    def _forget_git_warnings(self) -> None:
        """BF-957: a git add or commit succeeded, so any earlier error that recurs is logged again."""
        with self._git_warned_lock:
            self._git_warned.clear()

    async def _commit(self, message: str) -> None:
        """Debounced git commit.

        BF-957: an ``Exception`` other than a timeout (for example, git is missing) is logged at WARNING once per
        exception type until a git add or commit succeeds, without a claim about whether git ran: it may come from
        before the launch or after it. A timeout is not logged again: ``_git_sync`` has logged it, and what the
        stopped commit changed is not known. Neither is raised, as before; cancellation (``CancelledError``, not an
        ``Exception``) still propagates, as before. Here the warning memory is updated without ``_git_lock``.
        """
        if not self._config.auto_commit:
            return
        async with self._commit_lock:
            try:
                await self._git("commit", "-m", message, "--allow-empty-message")
            except Exception as e:
                if isinstance(e, subprocess.TimeoutExpired):
                    return  # BF-957 A3: _git_sync logged it once per verb; "did not run" would be false
                self._warn_git_once(
                    ("commit", type(e).__name__),
                    "Ship's Records: git commit raised %s: %s. The record is written to disk; whether it reached "
                    "the records history is not known. Logged once until a git add or commit succeeds.",
                    type(e).__name__,
                    e,
                )
