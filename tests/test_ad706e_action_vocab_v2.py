"""AD-706e: BrowserTool vocabulary v2 tests.

Covers 7 new action verbs (drag, key_combo, mouse_move, mouse_button,
upload_file, download, eval_js) plus their classify_action rules.
BF-287 enforced: real BrowserToolConfig + dataclass fakes at substrate.
"""
from __future__ import annotations

from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.events import EventType
from probos.tools.browser.actions import (
    _action_download,
    _action_drag,
    _action_eval_js,
    _action_key_combo,
    _action_mouse_button,
    _action_mouse_move,
    _action_upload_file,
    _HANDLERS,
    classify_action,
)
from probos.tools.browser.session import BrowserSession


# -- Fakes ----------------------------------------------------------------


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []
        self.downs: list[str] = []
        self.ups: list[str] = []
        self.clicks: list[tuple[int, int, str]] = []

    async def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))

    async def down(self, button: str = "left") -> None:
        self.downs.append(button)

    async def up(self, button: str = "left") -> None:
        self.ups.append(button)

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))


class _FakeKeyboard:
    def __init__(self) -> None:
        self.combos: list[str] = []

    async def press(self, combo: str) -> None:
        self.combos.append(combo)


class _FakePage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()
        self.drags: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, str]] = []
        self.evals: list[str] = []
        self.clicks: list[str] = []
        self.gotos: list[str] = []

    async def drag_and_drop(self, src: str, dst: str) -> None:
        self.drags.append((src, dst))

    async def set_input_files(self, selector: str, file_path: str) -> None:
        self.uploads.append((selector, file_path))

    async def evaluate(self, script: str) -> Any:
        self.evals.append(script)
        return {"ok": True}

    async def click(self, selector: str) -> None:
        self.clicks.append(selector)

    async def goto(self, url: str) -> None:
        self.gotos.append(url)


def _make_session(*, browser_cfg: BrowserToolConfig | None = None, page: _FakePage | None = None) -> BrowserSession:
    cfg = browser_cfg or BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s-e-1", agent_id="a1", config=cfg)
    sess._page = page or _FakePage()  # noqa: SLF001
    return sess


# -- Handler tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_drag_happy_path() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_drag(sess, {"from_selector": "#a", "to_selector": "#b"})
    assert page.drags == [("#a", "#b")]
    assert result["from_selector"] == "#a"
    assert result["to_selector"] == "#b"


@pytest.mark.asyncio
async def test_drag_missing_selector_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="drag requires"):
        await _action_drag(sess, {"from_selector": "#a"})


@pytest.mark.asyncio
async def test_key_combo_happy_path() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_key_combo(sess, {"keys": ["Control", "s"]})
    assert page.keyboard.combos == ["Control+s"]
    assert result["combo"] == "Control+s"


@pytest.mark.asyncio
async def test_key_combo_missing_keys_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="key_combo requires 'keys'"):
        await _action_key_combo(sess, {})


@pytest.mark.asyncio
async def test_mouse_move_happy_path() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_mouse_move(sess, {"x": 50, "y": 75})
    assert page.mouse.moves == [(50, 75)]
    assert result == {"session_id": "s-e-1", "x": 50, "y": 75}


@pytest.mark.asyncio
async def test_mouse_move_invalid_coord_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="mouse_move requires int"):
        await _action_mouse_move(sess, {"x": "10", "y": 20})


@pytest.mark.asyncio
async def test_mouse_button_happy_path_down() -> None:
    # BF-867: was ``{"action": "down"}``. The handler's sub-verb is now
    # ``press`` because ``action`` is the dispatch key -- ``tool.py`` forwards it
    # in the same dict, so the handler always read "mouse_button" and refused
    # every dispatched call. This test passed against that because it calls the
    # handler directly with a dict the dispatcher can never produce.
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_mouse_button(sess, {"button": "right", "press": "down"})
    assert page.mouse.downs == ["right"]
    assert result == {"session_id": "s-e-1", "button": "right", "press": "down"}


@pytest.mark.asyncio
async def test_mouse_button_invalid_press_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="mouse_button 'press'"):
        await _action_mouse_button(sess, {"button": "left", "press": "tap"})


@pytest.mark.asyncio
async def test_upload_file_happy_path_literal_path() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_upload_file(
        sess,
        {"selector": "input[type=file]", "file_path": "/tmp/x.txt"},
    )
    assert result["ok"] is True
    assert page.uploads == [("input[type=file]", "/tmp/x.txt")]
    assert result["used_credential"] is False


@pytest.mark.asyncio
async def test_upload_file_credential_ref_degrades_when_vault_missing() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    # No _runtime in params, or _runtime has no credential_vault -> degrade.
    result = await _action_upload_file(
        sess,
        {"selector": "input[type=file]", "credential_ref": "vault://my-secret"},
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "credential_vault_unavailable"
    assert page.uploads == []


@pytest.mark.asyncio
async def test_download_happy_path_url() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_download(
        sess,
        {"selector_or_url": "https://example.com/file.zip"},
    )
    assert page.gotos == ["https://example.com/file.zip"]
    assert result["target"] == "https://example.com/file.zip"


@pytest.mark.asyncio
async def test_download_missing_target_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="download requires"):
        await _action_download(sess, {})


@pytest.mark.asyncio
async def test_eval_js_happy_path() -> None:
    page = _FakePage()
    sess = _make_session(page=page)
    result = await _action_eval_js(sess, {"script": "document.title"})
    assert page.evals == ["document.title"]
    assert result["script_preview"] == "document.title"
    assert '"ok": true' in result["result"]


@pytest.mark.asyncio
async def test_eval_js_script_too_long_raises() -> None:
    sess = _make_session()
    with pytest.raises(ValueError, match="too long"):
        await _action_eval_js(sess, {"script": "x" * 5000})


# -- _HANDLERS registration -----------------------------------------------


def test_all_new_verbs_registered_in_handlers() -> None:
    for verb in (
        "drag", "key_combo", "mouse_move", "mouse_button",
        "upload_file", "download", "eval_js",
    ):
        assert verb in _HANDLERS, verb
        assert callable(_HANDLERS[verb])


# -- classify_action rules ------------------------------------------------


def test_classify_mouse_move_is_tier_1() -> None:
    sess = _make_session()
    assert classify_action(sess, "mouse_move", {"x": 1, "y": 1}) == 1


def test_classify_drag_default_tier_2() -> None:
    sess = _make_session()
    assert classify_action(sess, "drag", {"from_selector": "#a", "to_selector": "#b"}) == 2


def test_classify_drag_to_tier_3_host_is_tier_3() -> None:
    """drag uses URL/host check via the same code path as click — when the
    session.last_url is on a tier-3 host, drag escalates."""
    sess = _make_session()
    sess.set_last_url("https://bank.example/transfer")
    assert classify_action(sess, "drag", {"from_selector": "#a", "to_selector": "#b"}) == 3


def test_classify_key_combo_destructive_combo_is_tier_3() -> None:
    sess = _make_session()
    assert classify_action(sess, "key_combo", {"keys": ["Control", "w"]}) == 3
    assert classify_action(sess, "key_combo", {"keys": ["Control", "s"]}) == 2


def test_classify_upload_file_always_tier_3() -> None:
    sess = _make_session()
    assert classify_action(sess, "upload_file", {"selector": "#f", "file_path": "/x"}) == 3


def test_classify_eval_js_always_tier_3() -> None:
    sess = _make_session()
    assert classify_action(sess, "eval_js", {"script": "1+1"}) == 3


def test_classify_download_exe_suffix_is_tier_3() -> None:
    sess = _make_session()
    assert classify_action(sess, "download", {"selector_or_url": "https://x/y.exe"}) == 3
    assert classify_action(sess, "download", {"selector_or_url": "https://x/y.zip"}) == 2


def test_classify_action_with_llm_accepts_new_verbs() -> None:
    """Sanity: classify_action_with_llm short-circuits on rule_tier=3 for
    upload_file / eval_js and doesn't call any LLM."""
    from probos.tools.browser.llm_classifier import classify_action_with_llm

    class _Runtime:
        config = None
        llm_client = None

    rt = _Runtime()
    assert classify_action_with_llm(runtime=rt, rule_tier=3, action="upload_file") == 3
    assert classify_action_with_llm(runtime=rt, rule_tier=3, action="eval_js") == 3
    # Rule_tier=2 with no runtime config => degrade to rule_tier.
    assert classify_action_with_llm(runtime=rt, rule_tier=2, action="drag") == 2
