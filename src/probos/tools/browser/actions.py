"""AD-706: Action handlers for BrowserTool's 10-action vocabulary.

Each handler is an async free function that accepts a ``BrowserSession`` and
the action params dict, performs the work via Playwright (or a test fake),
and returns the action's output dict. ``BrowserTool.invoke()`` is a dispatch
table over the action verb that calls into ``dispatch_action``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from probos.tools.browser.session import _FORWARD_TEXT_MAX  # noqa: SLF001 — same package

if TYPE_CHECKING:
    from probos.tools.browser.session import BrowserSession

logger = logging.getLogger(__name__)


# -- Tier-3 keyword/path heuristics --------------------------------------

# AD-706e: destructive keyboard combinations that always require Captain ACK.
_KEY_COMBO_TIER_3_PATTERNS: frozenset[str] = frozenset({
    "control+w", "control+q", "alt+f4", "control+shift+w",
})

# AD-706e: download file suffixes that escalate the action to tier-3.
_DOWNLOAD_TIER_3_SUFFIXES: tuple[str, ...] = (".exe", ".dll", ".dmg", ".msi")

# AD-706e: eval_js script length cap (chars). Captain-supervised escape hatch.
_EVAL_JS_MAX_SCRIPT_LEN: int = 4096

# AD-1160: ceiling on ``key_type``'s inter-keystroke delay (ms). Playwright's
# ``keyboard.type(delay=...)`` sleeps between every character, so the wall time
# is delay x len(text); at the ``_FORWARD_TEXT_MAX`` bound 250 ms already means
# ~17 minutes of a held event loop. Anything above this is a malformed value,
# not a slow-typing preference.
_KEY_TYPE_MAX_DELAY_MS: int = 250

# AD-1179 / BF-867: the mouse and scroll vocabularies, declared ONCE.
#
# ``tool.py``'s schema enums and the handler gates below both read these, so the
# agent cannot be offered a value the handler then refuses -- the BF-701 shape,
# generalised from the top-level action verb to a handler's own parameters.
#
# Ordered tuples, never sets: Python string hashing is randomised per process,
# so ``list(some_set)`` would emit a different enum order on every boot and the
# wire bytes an LLM receives would vary run to run. Membership tests use the
# tuple directly -- these are three and four elements long.
_MOUSE_BUTTONS: tuple[str, ...] = ("left", "right", "middle")
_MOUSE_PRESSES: tuple[str, ...] = ("down", "up", "click")
_SCROLL_DIRECTIONS: tuple[str, ...] = ("up", "down", "left", "right")

# BF-692: bounds on ``state``'s element discovery.
#
# ``_STATE_MAX_ELEMENTS`` and ``_STATE_ELEMENTS_ELISION`` mirror
# ``agentic_dispatch._BROWSER_MAX_ELEMENTS`` / ``_BROWSER_ELEMENTS_ELISION``
# (AD-1153/DD-3), which bound the same list again on its way out to the agentic
# loop. They are duplicated rather than imported because ``tools`` must not
# import from ``cognitive``; tests/test_bf692_state_element_discovery.py imports
# both pairs and asserts they agree, so the duplication cannot silently drift.
_STATE_MAX_ELEMENTS: int = 100
_STATE_ELEMENTS_ELISION: str = (
    "[truncated: {omitted} further page elements elided. Narrow the page or "
    "re-run state after navigating.]"
)

# BF-692: ceiling on how many DOM nodes the walk INSPECTS, independent of how
# many it returns. The output cap alone does not bound the work: a page with a
# million matching nodes would still pay per-node layout + style reads before
# the 100th record is accepted, blocking the Playwright loop.
_STATE_MAX_SCAN_NODES: int = 2000

# BF-699: the accessibility-tree discovery path, tried BEFORE the DOM walk.
#
# BF-692 gave ``state`` a real DOM walk, and it works — on the TOP FRAME ONLY.
# ``page.evaluate`` runs in the main frame's context, so an application that
# hosts its editor in an iframe returns exactly one record: the ``<iframe>``
# element itself. Measured 2026-07-31 against the reference vessel's Word
# Online document: the walk returned a single node while the accessibility tree
# held 700+, every one of them behind one frame boundary.
#
# That is not a Word quirk. Word, Excel, PowerPoint, Google Docs and most
# embedded SaaS editors are iframe-hosted, so the entire category of
# application an operator most wants an agent to drive was unreachable, and the
# failure was SILENT — an empty list reads as "nothing here", not "I cannot see
# through this boundary". The agent on the reference vessel concluded the
# document was "rendered as a canvas/image" and spent its budget accordingly.
#
# ``Locator.aria_snapshot(mode="ai")`` crosses frames on its own and returns
# frame-qualified refs (``f1e4`` = frame 1, element 4). Crucially
# ``aria-ref=f1e4`` is itself a valid Playwright selector, so it drops into the
# existing record shape and ``_resolve_target_selector`` -> ``page.click(...)``
# reaches the in-frame element with NO change to click / type / key_type. All
# four facts were verified against real Chromium before this was written.
#
# Roles that are addressable regardless of whether they carry a name. Interactive
# controls are self-evidently worth an index; ``application``/``document``/``main``
# are included because an editing surface is a click target even though it is not
# a control, and Word's outer container is an unnamed ``application``.
_A11Y_INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "button", "checkbox", "combobox", "link", "listbox", "menuitem",
    "menuitemcheckbox", "menuitemradio", "option", "radio", "searchbox",
    "slider", "spinbutton", "switch", "tab", "textbox", "treeitem",
})
_A11Y_SURFACE_ROLES: frozenset[str] = frozenset({
    "application", "document", "main",
})

# BF-700: an accessible NAME is what makes a node worth addressing, not its role.
#
# BF-699 filtered on role alone and therefore still could not reach Word's
# document body. Measured against the reference vessel's live document: the
# editing surface is neither a control nor one of the surface roles above — it is
#
#     generic "Document Contents" [ref=f1e578]
#       generic "Page 1"          [ref=f1e586]
#
# a ``generic``, the single most common role in the tree (106 of them) and the
# one a role allowlist drops hardest. The ``table "Loading additional document
# content"`` sitting beside it is a decoy: Word emits that string on a table, a
# link and nine headings as screen-reader scaffolding, and none of them is the
# surface. An earlier plan to allowlist ``table`` would have added noise and
# still missed the target.
#
# A name is the signal. Something the page bothered to label is something a user
# — or an agent — can mean. Measured on that same document the rule moves the
# element list from 64 to 85 (cap 100) and admits exactly five named generics:
# Rename file, Ribbon Tabs, Styles, Document Contents, Page 1. All five are
# meaningful; the 106 unnamed generics and 48 unnamed images stay dropped.
#
# Verified end to end before this was written: clicking ``aria-ref=f1e586`` and
# then typing placed "Hello Sean" in the Captain's document, with the typing
# going to the FOCUSED element rather than a targeted one — which is what
# ``_action_key_type``'s ``keyboard.type`` already does.
_A11Y_NAME_MAX: int = 200


def _a11y_addressable(role: str, name: str) -> bool:
    """BF-700: is this accessibility node worth an index?"""
    if role in _A11Y_INTERACTIVE_ROLES or role in _A11Y_SURFACE_ROLES:
        return True
    return bool(name)


# Matches one ``aria_snapshot`` line, e.g.
#   - textbox "Document body" [ref=f1e4]
#   - button "Outer Button" [ref=e3]
# The name is optional; the ref is not (a node without one cannot be addressed).
_A11Y_NODE_RE = re.compile(
    r'^\s*-\s+(?P<role>[a-zA-Z]+)'
    r'(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?'
    r'.*?\[ref=(?P<ref>[A-Za-z0-9]+)\]'
)

# BF-692: the real element walk. Runs entirely in page context and returns
# ``{"elements": [...], "matched": int, "truncated": bool}``.
#
# ``selector`` is load-bearing — ``_resolve_target_selector`` turns ``index`` N
# straight into ``page.click(record["selector"])``, so a selector matching more
# than one node clicks the wrong thing. Uniqueness is therefore *proved* inside
# the page rather than assumed: every candidate selector is re-queried with
# ``querySelectorAll`` and kept only when it matches exactly one node and that
# node is the element it was built for. An element whose selector cannot be
# proved unique is dropped, because an unaddressable entry in the snapshot only
# costs the agent an iteration.
_STATE_DOM_WALK_JS: str = """
() => {
  const MAX_RECORDS = %(max_records)d;
  const MAX_SCAN = %(max_scan)d;
  const TEXT_MAX = 120;
  const DEPTH_MAX = 25;
  const SELECTOR = [
    'a[href]', 'button', 'input', 'textarea', 'select',
    '[role]', '[onclick]', '[contenteditable]:not([contenteditable="false"])'
  ].join(',');

  const esc = (s) => {
    if (window.CSS && typeof CSS.escape === 'function') { return CSS.escape(s); }
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
  };

  const isVisible = (el) => {
    if (el.hidden) { return false; }
    let r = null;
    try { r = el.getBoundingClientRect(); } catch (e) { return false; }
    if (!r || r.width <= 0 || r.height <= 0) { return false; }
    let st = null;
    try { st = window.getComputedStyle(el); } catch (e) { st = null; }
    if (!st) { return true; }
    if (st.display === 'none') { return false; }
    if (st.visibility === 'hidden' || st.visibility === 'collapse') { return false; }
    if (parseFloat(st.opacity || '1') === 0) { return false; }
    return true;
  };

  const uniqueSelector = (el) => {
    if (el.id) {
      const byId = '#' + esc(el.id);
      try {
        if (document.querySelectorAll(byId).length === 1) { return byId; }
      } catch (e) { /* malformed id, fall through to the path walk */ }
    }
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < DEPTH_MAX) {
      const tag = (node.localName || '').toLowerCase();
      if (!tag) { return null; }
      if (node !== el && node.id) {
        const anchor = '#' + esc(node.id);
        let unique = false;
        try { unique = document.querySelectorAll(anchor).length === 1; } catch (e) { unique = false; }
        if (unique) { parts.unshift(anchor); node = null; break; }
      }
      const parent = node.parentElement;
      if (!parent) { parts.unshift(tag); node = null; break; }
      let k = 0;
      for (let i = 0; i < parent.children.length; i++) {
        const sib = parent.children[i];
        if ((sib.localName || '').toLowerCase() === tag) {
          k++;
          if (sib === node) { break; }
        }
      }
      parts.unshift(tag + ':nth-of-type(' + k + ')');
      node = parent;
      depth++;
    }
    if (node) { return null; }
    const sel = parts.join(' > ');
    if (!sel) { return null; }
    try {
      const hits = document.querySelectorAll(sel);
      if (hits.length !== 1 || hits[0] !== el) { return null; }
    } catch (e) { return null; }
    return sel;
  };

  const roleOf = (el, tag) => {
    const explicit = el.getAttribute('role');
    if (explicit && explicit.trim()) { return explicit.trim().split(/\\s+/)[0]; }
    if (tag === 'a') { return 'link'; }
    if (tag === 'button') { return 'button'; }
    if (tag === 'select') { return 'combobox'; }
    if (tag === 'textarea') { return 'textbox'; }
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'checkbox') { return 'checkbox'; }
      if (t === 'radio') { return 'radio'; }
      if (t === 'submit' || t === 'button' || t === 'reset' || t === 'image') { return 'button'; }
      return 'textbox';
    }
    if (el.isContentEditable) { return 'textbox'; }
    return '';
  };

  const textOf = (el) => {
    let t = '';
    try { t = el.innerText || ''; } catch (e) { t = ''; }
    if (!t) { try { t = el.textContent || ''; } catch (e) { t = ''; } }
    return String(t).slice(0, TEXT_MAX * 8).replace(/\\s+/g, ' ').trim().slice(0, TEXT_MAX);
  };

  const nameOf = (el) => {
    const keys = ['aria-label', 'name', 'placeholder', 'title', 'alt'];
    for (let i = 0; i < keys.length; i++) {
      const v = el.getAttribute(keys[i]);
      if (v && String(v).trim()) { return String(v).trim().slice(0, TEXT_MAX); }
    }
    return '';
  };

  const valueOf = (el, tag) => {
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      // Never surface a password field's contents: this list is forwarded to
      // the model and persisted in the durable tool trace.
      if (t === 'password') { return ''; }
      if (t === 'checkbox' || t === 'radio') { return el.checked ? 'checked' : ''; }
    }
    if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') { return ''; }
    const v = el.value;
    return typeof v === 'string' ? v.slice(0, TEXT_MAX) : '';
  };

  let nodes = null;
  try { nodes = document.querySelectorAll(SELECTOR); } catch (e) { nodes = null; }
  if (!nodes) { return {elements: [], matched: 0, truncated: false}; }

  const out = [];
  let matched = 0;
  let truncated = nodes.length > MAX_SCAN;
  const limit = Math.min(nodes.length, MAX_SCAN);
  for (let i = 0; i < limit; i++) {
    const el = nodes[i];
    if (!el || el.nodeType !== 1) { continue; }
    if (!isVisible(el)) { continue; }
    matched++;
    if (out.length >= MAX_RECORDS) { truncated = true; continue; }
    const sel = uniqueSelector(el);
    if (!sel) { continue; }
    const tag = (el.localName || '').toLowerCase();
    const rec = {tag: tag, selector: sel};
    const role = roleOf(el, tag);
    if (role) { rec.role = role; }
    const text = textOf(el);
    if (text) { rec.text = text; }
    const name = nameOf(el);
    if (name) { rec.name = name; }
    const value = valueOf(el, tag);
    if (value) { rec.value = value; }
    if (tag === 'a') {
      const href = el.getAttribute('href');
      if (href) { rec.href = String(href).slice(0, TEXT_MAX * 4); }
    }
    out.push(rec);
  }
  return {elements: out, matched: matched, truncated: truncated};
}
""" % {"max_records": _STATE_MAX_ELEMENTS, "max_scan": _STATE_MAX_SCAN_NODES}

_TIER_3_PATH_TOKENS: tuple[str, ...] = (
    "checkout", "payment", "transfer", "subscribe", "signup", "register",
)

_TIER_3_TEXT_RE = re.compile(
    r"i\s+agree|accept\s+(all|cookies|terms)|continue|sign\s*up|"
    r"create\s+account|pay|confirm\s+order|place\s+order|transfer|subscribe",
    re.IGNORECASE,
)


# -- Action dispatch -----------------------------------------------------


async def dispatch_action(
    session: BrowserSession,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a single action to its handler. Raises on unknown action."""
    handler = _HANDLERS.get(action)
    if handler is None:
        raise ValueError(f"unknown browser action: {action}")
    return await handler(session, params)


# -- Individual handlers -------------------------------------------------


async def _action_goto(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    url = params.get("url") or ""
    if not url:
        raise ValueError("goto requires 'url'")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.goto(url)
    session.set_last_url(url)
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": url,
        "page_title": page_title or "",
    }


def _index_element_records(raw: Any) -> list[dict[str, Any]]:
    """Normalise raw element records into the indexed snapshot shape.

    Shared by both ``state`` discovery paths so the fake seam and the real DOM
    walk cannot drift apart in what they propagate. Non-dict entries are
    skipped; the ``index`` is the position in ``raw``, which is what
    ``BrowserSession.resolve_index`` looks up.
    """
    elements: list[dict[str, Any]] = []
    for i, rec in enumerate(raw or []):
        if not isinstance(rec, dict):
            continue
        entry: dict[str, Any] = {"index": i}
        for key in ("role", "text", "tag", "href", "name", "value", "selector", "frame"):
            if key in rec:
                entry[key] = rec[key]
        elements.append(entry)
    return elements


def _parse_a11y_snapshot(snapshot: str) -> tuple[list[dict[str, Any]], int]:
    """BF-699: turn an ``aria_snapshot(mode="ai")`` string into element records.

    Returns ``(records, omitted)`` in the same shape ``_discover_elements``
    produces, so the caller cannot tell which source it got and nothing
    downstream changes.

    ``selector`` is set to ``aria-ref=<ref>``, which Playwright resolves
    directly — including across a frame boundary, which is the entire point.
    Verified against real Chromium: ``page.locator("aria-ref=f1e4")`` matched
    the in-frame input and typing into it worked.
    """
    records: list[dict[str, Any]] = []
    matched = 0
    for line in snapshot.splitlines():
        m = _A11Y_NODE_RE.match(line)
        if m is None:
            continue
        role = m.group("role").lower()
        # BF-700: the name is read BEFORE the admission test, because for a
        # ``generic`` it IS the admission test.
        name = (m.group("name") or "").replace('\\"', '"').strip()[:_A11Y_NAME_MAX]
        if not _a11y_addressable(role, name):
            continue
        matched += 1
        if len(records) >= _STATE_MAX_ELEMENTS:
            continue
        records.append({
            "role": role,
            "name": name,
            "text": name,
            "selector": f"aria-ref={m.group('ref')}",
            # ``f<N>e<M>`` means frame N; a bare ``eM`` is the main frame. Kept
            # so an agent can tell that an element lives inside an embedded
            # application rather than the page chrome around it.
            "frame": m.group("ref").split("e")[0] if m.group("ref")[0] == "f" else "",
        })
    return records, max(matched - len(records), 0)


async def _a11y_discover_elements(page: Any) -> tuple[list[dict[str, Any]], int] | None:
    """BF-699: discover elements through the accessibility tree.

    Returns ``None`` when this path is unavailable or yields nothing, which
    means "fall through to the BF-692 DOM walk" — so a page with no ARIA
    semantics, an older Playwright without ``aria_snapshot``, or any failure at
    all behaves exactly as it did before this fix.
    """
    locator_factory = getattr(page, "locator", None)
    if not callable(locator_factory):
        return None
    try:
        root = locator_factory("body")
        snapshot_fn = getattr(root, "aria_snapshot", None)
        if not callable(snapshot_fn):
            return None
        snapshot = await snapshot_fn(mode="ai")
    except Exception:
        logger.warning(
            "BF-699: accessibility snapshot failed on the open page; falling "
            "back to the BF-692 DOM walk, which cannot see inside iframes. If "
            "this page hosts its editor in a frame the element list will be "
            "empty and the agent should use screenshot/coordinates instead.",
            exc_info=True,
        )
        return None
    if not isinstance(snapshot, str) or not snapshot.strip():
        return None
    records, omitted = _parse_a11y_snapshot(snapshot)
    if not records:
        return None
    return records, omitted


async def _discover_elements(page: Any) -> tuple[list[dict[str, Any]], int]:
    """BF-699: choose a discovery strategy for ``state``.

    The accessibility tree is tried FIRST because it crosses frame boundaries
    and the DOM walk does not. The walk remains the fallback: it sees elements
    carrying no ARIA semantics at all, and keeping it preserves the BF-692
    contract (proved-unique CSS selectors, path selectors, never surfacing a
    password value) on every page where the tree is empty or unavailable.

    The two strategies are separate named functions rather than one branchy
    body so each one's contract can be tested against real Chromium on its own
    terms — the DOM walk's guarantees are about CSS selectors, and the tree's
    are about frames and roles.
    """
    a11y = await _a11y_discover_elements(page)
    if a11y is not None:
        return a11y
    return await _dom_discover_elements(page)


async def _dom_discover_elements(page: Any) -> tuple[list[dict[str, Any]], int]:
    """BF-692: walk the live DOM for interactable elements.

    Returns ``(records, omitted)``. ``omitted`` is the number of visible
    candidates the caps dropped, and is 0 when nothing was truncated.

    Log-and-degrade throughout: ``state`` is the action an agent runs FIRST to
    orient itself, and ``_action_state`` has always absorbed discovery failures
    rather than raising. A page whose scripts break ``evaluate`` must still
    yield an empty snapshot, not a failed tool call.

    TOP FRAME ONLY — ``page.evaluate`` runs in the main frame's context. That
    limit is why BF-699 put the accessibility tree in front of this.
    """
    try:
        raw = await page.evaluate(_STATE_DOM_WALK_JS)
    except Exception:
        logger.warning(
            "BF-692: DOM element walk failed on the open page; 'state' returns "
            "an empty element list this call, so the agent has nothing to "
            "address by index and should fall back to screenshot/coordinates.",
            exc_info=True,
        )
        return [], 0
    if not isinstance(raw, dict):
        logger.warning(
            "BF-692: DOM element walk returned %s, expected dict; treating the "
            "page as having no addressable elements this call.",
            type(raw).__name__,
        )
        return [], 0
    found = raw.get("elements")
    if not isinstance(found, list):
        logger.warning(
            "BF-692: DOM element walk returned no 'elements' list (got %s); "
            "treating the page as having no addressable elements this call.",
            type(found).__name__,
        )
        return [], 0
    records = [rec for rec in found if isinstance(rec, dict)]
    # Defence in depth: the JS already caps, but the cap is the contract and is
    # re-imposed here so a fake/proxy that returns more cannot widen it.
    if len(records) > _STATE_MAX_ELEMENTS:
        records = records[:_STATE_MAX_ELEMENTS]
    matched = raw.get("matched")
    omitted = 0
    if raw.get("truncated") is True:
        omitted = matched - len(records) if isinstance(matched, int) else 0
        omitted = max(omitted, 1)
    return records, omitted


async def _action_state(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Return an indexed list of clickable/interactable elements.

    Mirrors the browser-use indexed-element pattern: each entry has a stable
    ``index`` so the LLM can say ``click 5`` instead of synthesizing CSS.
    The session keeps the most recent snapshot so subsequent click/type calls
    can resolve the index back to a selector.

    BF-692: a real Playwright ``Page`` has no ``list_elements``, so before this
    fix every live session fell through that branch to ``[]`` and the snapshot
    was always empty — an agent that ran ``state`` first, as the tool
    description tells it to, learned nothing and spent its remaining iterations
    clicking blind. The ``list_elements`` branch is kept FIRST as the test seam
    the existing suites inject; the real DOM walk sits beneath it.
    """
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    omitted = 0
    if hasattr(page, "list_elements"):
        # Test fake or deterministic DOM-walk helper.
        try:
            raw: Any = await page.list_elements()
        except Exception:
            logger.debug("AD-706: page.list_elements failed", exc_info=True)
            raw = []
        records: list[Any] = list(raw or [])
    else:
        records, omitted = await _discover_elements(page)
    elements = _index_element_records(records)
    session.record_state_snapshot(elements)
    out: list[Any] = list(elements)
    if omitted > 0:
        # Same in-list marker shape agentic_dispatch._bound_browser_output uses.
        # Deliberately NOT in the snapshot: resolve_index must only ever hand
        # _resolve_target_selector a dict.
        out.append(_STATE_ELEMENTS_ELISION.format(omitted=omitted))
    return {"session_id": session.session_id, "elements": out}


def _resolve_target_selector(
    session: BrowserSession,
    params: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Resolve params['index'] or params['selector'] to a CSS selector."""
    selector = params.get("selector")
    record: dict[str, Any] | None = None
    if not selector:
        idx = params.get("index")
        if idx is None:
            raise ValueError("click/type requires 'index' or 'selector'")
        if not isinstance(idx, int):
            raise ValueError("'index' must be int")
        record = session.resolve_index(idx)
        if record is None:
            raise ValueError(f"no element at index {idx} in last state snapshot")
        selector = record.get("selector")
        if not selector:
            raise ValueError(f"element at index {idx} has no selector")
    return selector, record


async def _action_click(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector, _record = _resolve_target_selector(session, params)
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.click(selector)
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    url = session.last_url
    if hasattr(page, "url"):
        try:
            page_url = page.url
            if isinstance(page_url, str) and page_url:
                url = page_url
                session.set_last_url(url)
        except Exception:
            logger.debug("AD-706: page.url access failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": url,
        "page_title": page_title or "",
    }


async def _action_type(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector, _record = _resolve_target_selector(session, params)
    text = params.get("text")
    if text is None:
        raise ValueError("type requires 'text'")
    if not isinstance(text, str):
        raise ValueError("'text' must be string")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    if hasattr(page, "fill"):
        await page.fill(selector, text)
    else:
        await page.type(selector, text)
    return {"session_id": session.session_id, "url": session.last_url}


async def _action_scroll(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    direction = (params.get("direction") or "down").lower()
    if direction not in _SCROLL_DIRECTIONS:
        raise ValueError(f"invalid scroll direction: {direction}")
    raw_amount = params.get("amount", 500)
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        raise ValueError("'amount' must be int")
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    dx = 0
    dy = 0
    if direction == "down":
        dy = amount
    elif direction == "up":
        dy = -amount
    elif direction == "right":
        dx = amount
    elif direction == "left":
        dx = -amount
    expr = f"window.scrollBy({dx}, {dy})"
    await page.evaluate(expr)
    return {"session_id": session.session_id, "url": session.last_url}


async def _action_screenshot(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Capture a screenshot, scaled to XGA bounds.

    Anthropic computer-use-demo discipline (MIT): render at
    ``screenshot_max_width × screenshot_max_height`` (default 1024×768) so the
    model gets a token-efficient frame and coordinates remain stable.
    """
    import base64

    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    cfg = session._config  # noqa: SLF001 — same module/package boundary
    max_w = cfg.screenshot_max_width
    max_h = cfg.screenshot_max_height

    # Determine current viewport so we can compute the scale-down factor.
    viewport_w = max_w
    viewport_h = max_h
    try:
        if hasattr(page, "viewport_size"):
            vs = page.viewport_size
            if callable(vs):
                vs = vs()
            if isinstance(vs, dict):
                viewport_w = int(vs.get("width", max_w) or max_w)
                viewport_h = int(vs.get("height", max_h) or max_h)
    except Exception:
        logger.debug("AD-706: viewport_size lookup failed", exc_info=True)

    # Compute target dims preserving aspect ratio, never exceeding XGA bounds.
    if viewport_w > 0 and viewport_h > 0:
        scale = min(max_w / viewport_w, max_h / viewport_h, 1.0)
        out_w = max(1, int(viewport_w * scale))
        out_h = max(1, int(viewport_h * scale))
    else:
        out_w, out_h = max_w, max_h

    raw = await page.screenshot()
    if isinstance(raw, bytes):
        b64 = base64.b64encode(raw).decode("ascii")
    elif isinstance(raw, str):
        b64 = raw
    else:
        b64 = ""
    return {
        "session_id": session.session_id,
        "screenshot_b64": b64,
        "width": out_w,
        "height": out_h,
    }


async def _action_wait(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector = params.get("selector")
    if selector:
        page = session.page
        if page is None:
            raise RuntimeError("browser session is not started")
        await page.wait_for_selector(selector)
        return {"session_id": session.session_id, "waited_for": selector}

    raw_ms = params.get("milliseconds")
    if raw_ms is None:
        raw_seconds = params.get("seconds")
        if raw_seconds is None:
            raise ValueError("wait requires 'milliseconds', 'seconds', or 'selector'")
        ms = int(float(raw_seconds) * 1000)
    else:
        try:
            ms = int(raw_ms)
        except (TypeError, ValueError):
            raise ValueError("'milliseconds' must be int")
    if ms < 0:
        raise ValueError("'milliseconds' must be non-negative")
    t0 = time.monotonic()
    await asyncio.sleep(ms / 1000.0)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return {"session_id": session.session_id, "waited_ms": elapsed_ms}


async def _action_back(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.go_back()
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": session.last_url,
        "page_title": page_title or "",
    }


async def _action_forward(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    await page.go_forward()
    page_title = ""
    try:
        page_title = await page.title()
    except Exception:
        logger.debug("AD-706: page.title() failed", exc_info=True)
    return {
        "session_id": session.session_id,
        "url": session.last_url,
        "page_title": page_title or "",
    }


async def _action_extract_text(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    selector = params.get("selector") or "body"
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    text = ""
    if hasattr(page, "inner_text"):
        try:
            text = await page.inner_text(selector)
        except Exception:
            logger.debug("AD-706: inner_text failed", exc_info=True)
            text = ""
    return {"session_id": session.session_id, "text": text or ""}


# -- AD-706e: vocabulary v2 ---------------------------------------------


async def _action_drag(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Drag from one element to another via Playwright's locator.drag_to()."""
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    from_selector = params.get("from_selector")
    to_selector = params.get("to_selector")
    if not from_selector or not to_selector:
        # Allow index-based resolution as a fallback (mirrors click/type).
        from_idx = params.get("from_index")
        to_idx = params.get("to_index")
        if isinstance(from_idx, int):
            rec = session.resolve_index(from_idx)
            if rec is not None:
                from_selector = rec.get("selector")
        if isinstance(to_idx, int):
            rec = session.resolve_index(to_idx)
            if rec is not None:
                to_selector = rec.get("selector")
    if not from_selector or not to_selector:
        raise ValueError("drag requires 'from_selector'/'to_selector' or 'from_index'/'to_index'")
    if hasattr(page, "drag_and_drop"):
        await page.drag_and_drop(from_selector, to_selector)
    else:
        # Stub-friendly fallback: locator.drag_to.
        src = page.locator(from_selector)
        dst = page.locator(to_selector)
        await src.drag_to(dst)
    return {
        "session_id": session.session_id,
        "from_selector": from_selector,
        "to_selector": to_selector,
    }


async def _action_key_combo(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Press a keyboard combination via page.keyboard.press('Control+S')."""
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    keys = params.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("key_combo requires 'keys' as a non-empty list of key names")
    combo = "+".join(str(k) for k in keys)
    keyboard = getattr(page, "keyboard", None)
    if keyboard is None:
        raise RuntimeError("page has no keyboard handle")
    await keyboard.press(combo)
    return {"session_id": session.session_id, "combo": combo}


def _resolve_key_type_delay(raw: Any) -> int | None:
    """AD-1160: validate ``key_type``'s ``delay_ms``. ``None`` means no delay.

    Log-and-degrade rather than raise: the delay only tunes typing cadence, so
    a malformed value should still land the keystrokes — refusing the whole
    action over it would be the less honest outcome. ``bool`` is rejected
    explicitly because ``isinstance(True, int)`` is ``True`` in Python, and
    ``delay=True`` would reach Playwright as a silent 1 ms delay.
    """
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        logger.warning(
            "AD-1160: key_type 'delay_ms' must be an int, got %r (%s); typing "
            "with no inter-key delay. A canvas app may drop keystrokes typed "
            "at full speed — re-issue with an int delay_ms if text is lost.",
            raw, type(raw).__name__,
        )
        return None
    if raw < 0 or raw > _KEY_TYPE_MAX_DELAY_MS:
        logger.warning(
            "AD-1160: key_type 'delay_ms'=%d is outside 0..%d; typing with no "
            "inter-key delay. A delay above the ceiling would hold the event "
            "loop for delay x len(text) — minutes on a long string.",
            raw, _KEY_TYPE_MAX_DELAY_MS,
        )
        return None
    if raw == 0:
        return None
    return raw


async def _action_key_type(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """AD-1160: type free text at the current keyboard focus. No selector.

    This is the only typing path that reaches a canvas-rendered app. Word
    Online draws its document into ``<div id="WACViewPanel">``: there is no
    ``contenteditable`` and no input element, so ``_action_type``'s
    ``page.fill(selector, text)`` has nothing to target. Mirrors the
    ``kind == "type"`` branch of :meth:`BrowserSession.forward_input`, which is
    the AD-1052c *human* path through the same Playwright primitive.

    ``delay_ms`` is load-bearing for such apps — they drop keystrokes typed
    with no inter-key delay — but is validated and bounded by
    :func:`_resolve_key_type_delay`.
    """
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    text = params.get("text")
    if text is None:
        raise ValueError("key_type requires 'text'")
    if not isinstance(text, str):
        raise ValueError("'text' must be string")
    keyboard = getattr(page, "keyboard", None)
    if keyboard is None:
        raise RuntimeError("page has no keyboard handle")
    truncated = len(text) > _FORWARD_TEXT_MAX
    if truncated:
        logger.warning(
            "AD-1160: key_type text is %d chars, over the %d-char bound; "
            "typing the leading %d only. The result reports truncated=True — "
            "re-issue key_type with the remainder to finish the string.",
            len(text), _FORWARD_TEXT_MAX, _FORWARD_TEXT_MAX,
        )
        text = text[:_FORWARD_TEXT_MAX]
    delay_ms = _resolve_key_type_delay(params.get("delay_ms"))
    if delay_ms is None:
        await keyboard.type(text)
    else:
        await keyboard.type(text, delay=delay_ms)
    result: dict[str, Any] = {
        "session_id": session.session_id,
        "url": session.last_url,
        "typed": len(text),
    }
    if truncated:
        result["truncated"] = True
    return result


async def _action_mouse_move(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Move the mouse cursor to (x, y) without clicking. Silent observation."""
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    x = params.get("x")
    y = params.get("y")
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("mouse_move requires int 'x' and 'y' coordinates")
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        raise RuntimeError("page has no mouse handle")
    await mouse.move(x, y)
    return {"session_id": session.session_id, "x": x, "y": y}


async def _action_mouse_button(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Press, release, or click a specific mouse button at the current position."""
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    button = params.get("button", "left")
    if button not in _MOUSE_BUTTONS:
        raise ValueError(
            "mouse_button 'button' must be one of: " + ", ".join(_MOUSE_BUTTONS)
        )
    # BF-867: read 'press', not 'action'. 'action' is the DISPATCH key --
    # ``tool.py`` reads it out of ``params`` without removing it and forwards the
    # same dict, so it is always "mouse_button" here. This branch therefore
    # raised on every call and the "click" default was unreachable: the verb was
    # offered and refused for its whole life. There is deliberately no ``action``
    # fallback -- a lenient alias would re-create the collision.
    press = params.get("press", "click")
    if press not in _MOUSE_PRESSES:
        raise ValueError(
            "mouse_button 'press' must be one of: " + ", ".join(_MOUSE_PRESSES)
        )
    mouse = getattr(page, "mouse", None)
    if mouse is None:
        raise RuntimeError("page has no mouse handle")
    if press == "down":
        await mouse.down(button=button)
    elif press == "up":
        await mouse.up(button=button)
    else:
        # BF-693: this used to be ``mouse.click(0, 0, ...)`` behind a
        # ``hasattr(mouse, "click_button")`` guard. Playwright's ``Mouse`` has
        # no such method, so the guard never fired and every click landed at
        # viewport (0, 0) instead of the current cursor position the docstring
        # promises — a mouse_move followed by a click hit the top-left corner.
        # down+up is the correct coordinate-free idiom and needs no state.
        await mouse.down(button=button)
        await mouse.up(button=button)
    return {"session_id": session.session_id, "button": button, "press": press}


async def _action_upload_file(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Upload a file via page.set_input_files(). Tier 3 always.

    Optional ``credential_ref`` param hooks into AD-706f credential vault:
    when set, the file path is materialised from the vault to a tempfile.
    When the vault is unavailable, honest-degrade rather than crash.
    """
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    selector = params.get("selector")
    if not selector or not isinstance(selector, str):
        raise ValueError("upload_file requires 'selector' (CSS selector for <input type=file>)")
    credential_ref = params.get("credential_ref")
    file_path = params.get("file_path")
    temp_path: str | None = None
    try:
        if credential_ref:
            # AD-706f forward-compatible hook.
            vault = getattr(params.get("_runtime"), "credential_vault", None) if params.get("_runtime") else None
            if vault is None:
                return {
                    "session_id": session.session_id,
                    "ok": False,
                    "skipped_reason": "credential_vault_unavailable",
                    "message": (
                        "upload_file received credential_ref but no credential_vault "
                        "is wired on the runtime. AD-706f required."
                    ),
                }
            temp_path = await vault.materialize_to_temp(credential_ref)
            file_path = temp_path
        if not file_path or not isinstance(file_path, str):
            raise ValueError("upload_file requires 'file_path' (or 'credential_ref' with vault)")
        await page.set_input_files(selector, file_path)
        return {
            "session_id": session.session_id,
            "ok": True,
            "selector": selector,
            "file_path": file_path,
            "used_credential": bool(credential_ref),
        }
    finally:
        if temp_path:
            try:
                import os as _os
                _os.unlink(temp_path)
            except OSError:
                logger.debug("AD-706e: tempfile unlink failed for %s", temp_path, exc_info=True)


async def _action_download(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Trigger a download by clicking a selector or navigating to a URL.

    v1 surface: the handler returns metadata about the triggered download
    (suggested filename, target URL); the actual bytes are written by the
    browser to its default downloads dir. AD-706e-3 forward marker covers
    routing into AttachmentStore.
    """
    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    target = params.get("selector_or_url")
    if not target or not isinstance(target, str):
        raise ValueError("download requires 'selector_or_url'")
    suggested_filename: str | None = None
    try:
        if hasattr(page, "expect_download"):
            async with page.expect_download() as dl_info:
                if target.startswith(("http://", "https://")):
                    await page.goto(target)
                else:
                    await page.click(target)
            download = await dl_info.value
            suggested_filename = getattr(download, "suggested_filename", None)
        else:
            if target.startswith(("http://", "https://")):
                await page.goto(target)
            else:
                await page.click(target)
    except Exception:
        logger.warning("AD-706e: download trigger failed for %s", target, exc_info=True)
        raise
    return {
        "session_id": session.session_id,
        "target": target,
        "suggested_filename": suggested_filename,
    }


async def _action_eval_js(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
    """Execute arbitrary JavaScript in the page context. Tier 3 always.

    Captain-supervised escape hatch. Script length capped at
    ``_EVAL_JS_MAX_SCRIPT_LEN`` chars. Result serialised via json.dumps(default=str).
    """
    import json as _json

    page = session.page
    if page is None:
        raise RuntimeError("browser session is not started")
    script = params.get("script")
    if not script or not isinstance(script, str):
        raise ValueError("eval_js requires 'script' (str)")
    if len(script) > _EVAL_JS_MAX_SCRIPT_LEN:
        raise ValueError(
            f"eval_js 'script' too long: {len(script)} > {_EVAL_JS_MAX_SCRIPT_LEN} chars"
        )
    raw_result = await page.evaluate(script)
    try:
        result_str = _json.dumps(raw_result, default=str)
    except (TypeError, ValueError):
        result_str = repr(raw_result)
    return {
        "session_id": session.session_id,
        "script_preview": script[:200],
        "result": result_str,
    }


_HANDLERS: dict[str, Any] = {
    "goto": _action_goto,
    "state": _action_state,
    "click": _action_click,
    "type": _action_type,
    "scroll": _action_scroll,
    "screenshot": _action_screenshot,
    "wait": _action_wait,
    "back": _action_back,
    "forward": _action_forward,
    "extract_text": _action_extract_text,
}


# -- AD-706c-1: visual verification via vision tier ----------------------


def _parse_verify_response(raw: str) -> dict[str, Any]:
    """Parse the vision LLM response into ``{ok, observation}``.

    Tier-2 honest-degrade: malformed JSON yields ``ok=None`` plus a clipped
    observation rather than raising. Verification is observability — it
    must never break the action sequence.
    """
    import json as _json
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": None, "observation": "empty vision response"}
    text = raw.strip()
    # Strip code fences if the model wrapped JSON in ``` blocks.
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        payload = _json.loads(text)
    except (ValueError, TypeError):
        return {"ok": None, "observation": text[:200]}
    if not isinstance(payload, dict):
        return {"ok": None, "observation": text[:200]}
    ok = payload.get("ok")
    if not isinstance(ok, bool):
        ok = None
    observation = payload.get("observation", "")
    if not isinstance(observation, str):
        observation = ""
    return {"ok": ok, "observation": observation[:200]}


async def action_verify(
    session: BrowserSession,
    params: dict[str, Any],
    *,
    runtime: Any,
    emit_event: Any,
) -> dict[str, Any]:
    """AD-706c-1: vision-LLM verification of the current page state.

    Returns ``{ok: bool | None, observation: str, screenshot_ref: str | None,
    skipped_reason: str | None}``. Tier-2 honest-degrade: vision tier
    unavailable / unhealthy / call-error returns ``ok=None`` with a
    ``skipped_reason``. NEVER raises — the browser action sequence is
    load-bearing; verification is observational.
    """
    import hashlib as _hashlib
    from probos.events import EventType

    expectation = params.get("expectation", "")
    if not isinstance(expectation, str) or not expectation.strip():
        return {
            "ok": None,
            "observation": "missing expectation",
            "screenshot_ref": None,
            "skipped_reason": "missing_expectation",
        }
    if len(expectation) > 500:
        expectation = expectation[:500]

    page = session.page
    if page is None:
        return {
            "ok": None,
            "observation": "browser session not started",
            "screenshot_ref": None,
            "skipped_reason": "session_not_started",
        }
    try:
        png_bytes = await page.screenshot()
    except Exception:
        logger.warning("AD-706c-1: page.screenshot failed", exc_info=True)
        return {
            "ok": None,
            "observation": "screenshot capture failed",
            "screenshot_ref": None,
            "skipped_reason": "screenshot_error",
        }

    # AD-731: store via AttachmentStore — refs not blobs through any later
    # bus hop. The vision LLM call resolves the ref via the BF-268 OpenAI
    # shape inside ``build_multimodal_messages``.
    try:
        from probos.routers.chat import _get_attachment_store
        store = _get_attachment_store(runtime)
    except Exception:
        logger.warning(
            "AD-706c-1: AttachmentStore lookup failed; skipping verification",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "attachment store unavailable",
            "screenshot_ref": None,
            "skipped_reason": "attachment_store_unavailable",
        }

    screenshot_ref = _hashlib.sha256(png_bytes).hexdigest()
    try:
        await store.write(screenshot_ref, png_bytes, "image/png")
    except Exception:
        logger.warning(
            "AD-706c-1: AttachmentStore.write failed; skipping verification",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "attachment store write failed",
            "screenshot_ref": None,
            "skipped_reason": "attachment_store_write_error",
        }

    # Vision tier honest-degrade — AD-732 + 10-guard stack.
    try:
        from probos.cognitive.vision_dispatch import is_vision_tier_configured
        cfg = getattr(runtime, "config", None)
        cog_cfg = getattr(cfg, "cognitive", None)
        if cog_cfg is None or not is_vision_tier_configured(cog_cfg, "vision"):
            return {
                "ok": None,
                "observation": "vision tier unconfigured",
                "screenshot_ref": screenshot_ref,
                "skipped_reason": "vision_unconfigured",
            }
    except Exception:
        return {
            "ok": None,
            "observation": "vision tier check failed",
            "screenshot_ref": screenshot_ref,
            "skipped_reason": "vision_check_error",
        }

    prompt_text = (
        f"You are verifying a browser action outcome. The agent expected: "
        f"\"{expectation}\". Look at the screenshot and answer in JSON: "
        f"{{\"ok\": bool, \"observation\": \"<<=200 char description>\"}}. "
        f"Respond with JSON only, no prose."
    )
    raw_response: str = ""
    try:
        from probos.cognitive.vision_dispatch import build_multimodal_messages
        from probos.cognitive.llm_client import LLMRequest

        attach_cfg = getattr(cfg, "attachments", None)
        text_max = int(getattr(attach_cfg, "text_extraction_max_bytes", 32768))
        pdf_on = bool(getattr(attach_cfg, "pdf_extraction_enabled", False))

        async def _mime_lookup(_aid: str) -> str | None:
            return "image/png"

        messages, _image_ids, _per = await build_multimodal_messages(
            prompt=prompt_text,
            attachment_ids=[screenshot_ref],
            store=store,
            mime_lookup=_mime_lookup,
            text_extraction_max_bytes=text_max,
            pdf_extraction_enabled=pdf_on,
        )
        request = LLMRequest(
            prompt=prompt_text,
            tier="vision",
            max_tokens=300,
            messages=messages,
        )
        response = await runtime.llm_client.complete(request)
        raw_response = getattr(response, "text", "") or ""
    except Exception:
        logger.warning(
            "AD-706c-1: vision LLM call failed; honest-degrade",
            exc_info=True,
        )
        return {
            "ok": None,
            "observation": "vision tier call failed",
            "screenshot_ref": screenshot_ref,
            "skipped_reason": "vision_unavailable",
        }

    parsed = _parse_verify_response(raw_response)
    parsed["screenshot_ref"] = screenshot_ref
    parsed["skipped_reason"] = None

    if emit_event is not None:
        try:
            emit_event(
                EventType.BROWSER_VERIFY_OBSERVED,
                {
                    "session_id": session.session_id,
                    "expectation": expectation,
                    "ok": parsed["ok"],
                    "screenshot_ref": screenshot_ref,
                    "observation": parsed["observation"],
                },
            )
        except Exception:
            logger.warning(
                "AD-706c-1: emit_event(BROWSER_VERIFY_OBSERVED) failed",
                exc_info=True,
            )
    return parsed


# -- Tier classifier (D6) ------------------------------------------------


# AD-706c-2: register coordinate-aware click handler. Late-bound after
# ``action_verify`` is defined because compute_use reuses it for the Guard
# #9 verification handshake (avoiding a circular import).
from probos.tools.browser.compute_use import action_compute_use_click  # noqa: E402
_HANDLERS["compute_use_click"] = action_compute_use_click

# AD-706e: vocabulary v2 — register the 7 new verbs alongside compute_use_click.
# fill_credential is added by AD-706f via a separate late-bind block (owns
# that slot). AD-706e is NO-OP for compute_use_click and fill_credential.
_HANDLERS["drag"] = _action_drag
_HANDLERS["key_combo"] = _action_key_combo
_HANDLERS["mouse_move"] = _action_mouse_move
_HANDLERS["mouse_button"] = _action_mouse_button
_HANDLERS["upload_file"] = _action_upload_file
_HANDLERS["download"] = _action_download
_HANDLERS["eval_js"] = _action_eval_js

# AD-706f: credential vault fill action. Tier-3 always (Captain ACK every
# call). Late-bind from credentials.py to avoid forcing the import on
# environments where the vault is disabled.
from probos.tools.browser.credentials import action_fill_credential  # noqa: E402
_HANDLERS["fill_credential"] = action_fill_credential

# AD-1160: focus-scoped typing. Registered here rather than in the literal
# above so the AD-706 block stays byte-identical, matching the AD-706e/706f
# late-bind convention.
_HANDLERS["key_type"] = _action_key_type


def classify_action(
    session: BrowserSession,
    action: str,
    params: dict[str, Any],
) -> int:
    """Return tier 1, 2, or 3 for the given action.

    * Tier 1 (silent): ``state``, ``screenshot``, ``wait``, ``extract_text``,
      ``scroll``, ``back``, ``forward`` — observation only.
    * Tier 2 (logged-and-proceed): ``goto``, ``click``, ``type``, ``key_type``
      against ordinary domains.
    * Tier 3 (Captain ACK required): ``click``, ``type`` or ``key_type`` when
      host matches ``BrowserToolConfig.tier_3_domain_patterns``, OR URL path
      contains checkout/payment/transfer/subscribe/signup/register, OR the
      clicked element's text matches the tier-3 text regex.
    """
    # AD-706c-2: coordinate-aware click is always tier-3 (destructive click
    # at an unverified pixel coordinate). Captain ACK required every call.
    # Checked BEFORE the silent/goto bands so AD-706e's later additive
    # always-tier-3 entries can stack without re-shaping this branch.
    if action == "compute_use_click":
        return 3
    # AD-706e: additional always-tier-3 verbs. Each verb has its own
    # short-circuit (vs a set membership) so AD-706f's fill_credential add
    # is a single new branch with no merge conflict on the set literal.
    if action == "upload_file":
        return 3
    if action == "eval_js":
        return 3
    # AD-706f: credential fill always-tier-3 (Captain ACK every credential read).
    if action == "fill_credential":
        return 3
    silent = {"state", "screenshot", "wait", "extract_text", "scroll", "back", "forward", "verify", "mouse_move"}
    if action in silent:
        return 1
    if action == "goto":
        return 2
    # AD-706e: key_combo destructive-pattern check (Control+W, Alt+F4, etc.).
    if action == "key_combo":
        keys = params.get("keys") or []
        if isinstance(keys, list):
            joined = "+".join(str(k).lower() for k in keys)
            if joined in _KEY_COMBO_TIER_3_PATTERNS:
                return 3
        return 2
    # AD-706e: download URL/suffix check for executable types.
    if action == "download":
        target = params.get("selector_or_url") or ""
        if isinstance(target, str) and any(
            target.lower().endswith(suf) for suf in _DOWNLOAD_TIER_3_SUFFIXES
        ):
            return 3
        return 2
    # AD-706e: drag + mouse_button join click/type for the URL/text checks.
    # AD-1160: key_type mutates page state exactly as ``type`` does, so it
    # joins the same branch rather than getting a parallel one.
    if action not in {"click", "type", "key_type", "drag", "mouse_button"}:
        return 2

    # Click / type: inspect URL + element text for tier-3 indicators.
    cfg = session._config  # noqa: SLF001
    url = params.get("url") or session.last_url or ""
    host, path = _split_url(url)
    if _host_matches_tier_3(host, cfg.tier_3_domain_patterns):
        return 3
    if path and any(token in path.lower() for token in _TIER_3_PATH_TOKENS):
        return 3

    # Inspect the element from the most recent state() snapshot, if available.
    record: dict[str, Any] | None = None
    selector = params.get("selector")
    if selector is None:
        idx = params.get("index")
        if isinstance(idx, int):
            record = session.resolve_index(idx)
    if record is not None:
        text = record.get("text") or ""
        if isinstance(text, str) and _TIER_3_TEXT_RE.search(text):
            return 3
    return 2


def _split_url(url: str) -> tuple[str, str]:
    """Return (host, path) from a URL string. Empty strings on parse failure."""
    if not url:
        return "", ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return (parsed.hostname or "").lower(), parsed.path or ""
    except Exception:
        return "", ""


def _host_matches_tier_3(host: str, patterns: list[str]) -> bool:
    if not host or not patterns:
        return False
    import fnmatch

    host_lower = host.lower()
    for pat in patterns:
        if not isinstance(pat, str) or not pat:
            continue
        if fnmatch.fnmatchcase(host_lower, pat.lower()):
            return True
    return False
