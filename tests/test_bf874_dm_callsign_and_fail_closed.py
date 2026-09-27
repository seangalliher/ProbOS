"""BF-874 (#1429): a DM to a multi-word callsign is sent, and no DM block is ever posted publicly.

Two defects, one invariant. The AD-612 open tag captured the callsign with ``(\\S+)``, so
``[DM @Number One]`` never parsed and its body went to the author's department channel; and
every text that still held a DM block -- unreadable syntax, an author below
``communications.dm_min_rank``, a block inside a [REPLY], a Ward Room reply with no proactive
loop -- was posted after the BF-203 catch-all removed the tag and left the body. The invariant
these tests hold: a DM body is delivered or withheld with a WARNING, never posted.

Real components throughout (``ProactiveCognitiveLoop``, ``WardRoomService`` on ``tmp_path``,
``AgentRegistry``, ``CallsignRegistry``, ``TrustNetwork``, ``SystemConfig``, ``DmSanityGate``,
``WardRoomPostPipeline``, ``DmReplyPipeline``, ``MessageReceiptsTool``); the only doubles are
``SimpleNamespace`` agents and a one-method ontology.
"""
from __future__ import annotations

import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.proactive import (
    _DM_CLOSED_PATTERN,
    _DM_UNCLOSED_PATTERN,
    DmStrip,
    ProactiveCognitiveLoop,
    strip_dm_blocks,
    withhold_dm_blocks,
)
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.tools.message_receipts_tool import MessageReceiptsTool
from probos.tools.registry import ToolRegistry
from probos.ward_room.receipt_facts import addressed_callsign
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"

CREW = (
    ("security_officer", "Worf", "security"),
    ("architect", "Number One", "science"),
    ("counselor", "Troi", "medical"),
    ("operations_officer", "O'Brien", "operations"),
)


def _agent(agent_type: str, callsign: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type,
        pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
    )


class _Rig:
    """A proactive loop over a real Ward Room, with Worf (a lieutenant at the default prior) as sender."""

    def __init__(self, ws: WardRoomService, *, dm_min_rank: str, aboard: set[str] | None) -> None:
        self.ws = ws
        self.dm_min_rank = dm_min_rank
        self.aboard = aboard

    async def start(self) -> "_Rig":
        await self.ws.start()
        self.registry = AgentRegistry()
        self.agents = {cs: _agent(t, cs) for t, cs, _ in CREW}
        for cs, a in self.agents.items():
            if self.aboard is None or cs in self.aboard:
                await self.registry.register(a)
        self.callsigns = CallsignRegistry()
        for t, cs, _ in CREW:
            self.callsigns.set_callsign(t, cs)
        self.callsigns.bind_registry(self.registry)
        depts = {t: d for t, _, d in CREW}
        self.config = SystemConfig()
        self.config.communications.dm_min_rank = self.dm_min_rank
        self.rt = SimpleNamespace(
            ward_room=self.ws, registry=self.registry, callsign_registry=self.callsigns,
            ontology=SimpleNamespace(get_agent_department=lambda t: depts.get(t)),
            config=self.config, trust_network=TrustNetwork(), ward_room_router=None,
            episodic_memory=None, hebbian_router=None, dispatcher=None, _records_store=None,
            working_memory=None, dm_sanity_gate=DmSanityGate(), skill_service=None,
            boot_camp=None, emit_event=lambda *a, **k: None,
        )
        self.loop = ProactiveCognitiveLoop(cooldown=300.0)
        self.loop.set_runtime(self.rt)
        self.sender = self.agents["Worf"]
        return self

    async def department_thread(self, title: str, body: str) -> str:
        dept = next(c for c in await self.ws.list_channels() if c.channel_type == "department" and c.department == "security")
        thread = await self.ws.create_thread(channel_id=dept.id, author_id=self.agents["Troi"].id,
                                             title=title, body=body, author_callsign="Troi")
        return thread.id

    async def where(self, secret: str) -> tuple[list[str], list[str]]:
        """Return (public places holding ``secret``, titles of DM threads holding it)."""
        public: list[str] = []
        dm_titles: list[str] = []
        for ch in await self.ws.list_channels():
            for th in await self.ws.list_threads(ch.id, limit=500):
                full = await self.ws.get_thread(th.id) or {}
                texts = [th.title, th.body, *_bodies(full.get("posts", []))]
                if not any(secret in t for t in texts if t):
                    continue
                if ch.channel_type in ("department", "ship"):
                    public.append(f"{ch.channel_type}:{th.title}")
                elif ch.channel_type == "dm":
                    dm_titles.append(th.title)
        return public, dm_titles

    async def dm_titles(self) -> list[str]:
        """Titles of every DM thread, whatever it holds."""
        titles: list[str] = []
        for ch in await self.ws.list_channels():
            if ch.channel_type == "dm":
                titles.extend(th.title for th in await self.ws.list_threads(ch.id, limit=500))
        return sorted(titles)

    async def dm_bodies(self) -> list[str]:
        bodies: list[str] = []
        for ch in await self.ws.list_channels():
            if ch.channel_type == "dm":
                bodies.extend(th.body for th in await self.ws.list_threads(ch.id, limit=500))
        return bodies


def _bodies(node: Any) -> list[str]:
    if isinstance(node, dict):
        out = [node["body"]] if isinstance(node.get("body"), str) else []
        for value in node.values():
            if isinstance(value, (dict, list)):
                out.extend(_bodies(value))
        return out
    if isinstance(node, list):
        return [b for item in node for b in _bodies(item)]
    return []


@pytest.fixture
async def rig_factory(tmp_path):
    made: list[_Rig] = []

    async def make(*, dm_min_rank: str = "ensign", aboard: set[str] | None = None) -> _Rig:
        rig = _Rig(WardRoomService(db_path=str(tmp_path / f"wr{len(made)}.db")), dm_min_rank=dm_min_rank, aboard=aboard)
        made.append(rig)
        return await rig.start()

    yield make
    for rig in made:
        await rig.ws.stop()


@pytest.fixture
async def rig(rig_factory):
    return await rig_factory()


def _bf874(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "BF-874" in r.getMessage()]


# --- U: the patterns ---------------------------------------------------------------------------

READABLE = [
    ("[DM @Number One]", "Number One"),
    ("[DM Number One]", "Number One"),
    ("[DM @number one]", "number one"),
    ("[dm @Troi]", "Troi"),
    ("[DM @O'Brien]", "O'Brien"),
    ("[DM @Troi ]", "Troi "),
    ("[DM @ Troi]", " Troi"),
    ("[DM @" + "X" * 64 + "]", "X" * 64),
]


@pytest.mark.parametrize(("tag", "callsign"), READABLE)
def test_open_tag_reads_the_whole_callsign(tag: str, callsign: str) -> None:
    for pattern in (_DM_CLOSED_PATTERN, _DM_UNCLOSED_PATTERN):
        match = pattern.search(f"{tag} body [/DM]")
        assert match is not None and match.group(1) == callsign, (pattern.pattern, tag)


@pytest.mark.parametrize("tag", [
    "[DM @" + "X" * 65 + "]",
    "[DM@Troi]",
    "[DM @Number\nOne]",
    "[DM @Tr[oi]",
])
def test_open_tag_refuses_what_it_cannot_read(tag: str) -> None:
    assert _DM_CLOSED_PATTERN.search(f"{tag} body [/DM]") is None
    assert _DM_UNCLOSED_PATTERN.search(f"{tag} body") is None


def test_every_readable_callsign_titles_back_through_ad1229() -> None:
    for _tag, captured in READABLE:
        callsign = captured.strip()
        assert addressed_callsign(f"[DM to @{callsign}]") == callsign


@pytest.mark.parametrize(("text", "public", "readable", "unreadable", "stray"), [
    ("a [DM @Number One] x [/DM] b", "a b", 1, 0, 0),
    ("[DM @Troi] only an unclosed body", "", 1, 0, 0),
    ("[dm @troi] lower [/dm]", "", 1, 0, 0),
    ("x [DM@Troi] y [/DM] z", "x z", 0, 1, 0),
    ("x [DM @Number One y", "x", 0, 1, 0),
    ("x [DM @" + "X" * 65 + "] y [/DM] z", "x z", 0, 1, 0),
    # A-2: "c" ends in a second [/DM], so it was inside the block. This case used to expect "a c" --
    # it pinned the review round 1 defect (the text before a stray closer was posted).
    ("a [DM @Troi] b [/DM] c [/DM]", "a", 1, 0, 1),
    ("[DM @Troi] p [DM@Bad] n [/DM] TAIL [/DM] after", "after", 1, 0, 1),
    ("lead [DM @Troi] p [DM@Bad] n [/DM] TAIL [/DM] after", "lead after", 1, 0, 1),
    ("lead [DM@Bad] n [DM @Troi] p [/DM] TAIL [/DM] after", "lead after", 1, 1, 0),
    ("lead [DM @Troi] p [/DM] [DM@Bad] n [/DM] TAIL [/DM] after", "lead after", 1, 1, 1),
    ("lead [DM@Bad] n [/DM] TAIL [/DM] after", "lead after", 0, 1, 1),
    ("lead [DM@A] p [DM@B] n [/DM] TAIL [/DM] after", "lead after", 0, 1, 0),
    ("lead [DM @Troi] p [/DM][/DM] after", "lead after", 1, 0, 1),
    ("TAIL [/DM] lead [DM @Troi] p [/DM] after", "lead after", 1, 0, 1),
    ("lead TAIL [/DM] after", "after", 0, 0, 1),
    ("lead [DM @Troi] p [DM] n [/DM] after", "lead after", 1, 0, 0),
    ("a [DM @Troi] b [/DM] c [DM@Bad] d [/DM] e", "a c e", 1, 1, 0),
    ("lead [DM @Troi] p [DM @Worf] n [/DM] TAIL [/DM] after", "lead", 2, 0, 0),
    ("no block here: [DMZ] and [DMs]", "no block here: [DMZ] and [DMs]", 0, 0, 0),
    ("", "", 0, 0, 0),
])
def test_strip_dm_blocks_removes_every_block_and_counts_it(text, public, readable, unreadable, stray) -> None:
    got = strip_dm_blocks(text)
    assert isinstance(got, DmStrip)
    assert " ".join(got.text.split()) == public
    assert (got.readable, got.unreadable, got.stray_closers) == (readable, unreadable, stray)


def test_withhold_dm_blocks_warns_with_who_where_and_what(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out = withhold_dm_blocks("Keep this. [DM@Troi] private [/DM]", agent_id="agent-7", where="observation")
    assert out == "Keep this."
    [msg] = _bf874(caplog)
    assert "agent-7" in msg and "observation" in msg and "1 unsent" in msg and "1 unreadable" in msg


def test_withhold_dm_blocks_is_silent_and_exact_without_a_block(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    text = "Status nominal. See arr[0] and [DMZ]."
    assert withhold_dm_blocks(text, agent_id="agent-7", where="observation") == text
    assert _bf874(caplog) == []


def test_withhold_dm_blocks_after_the_dm_step_reports_only_what_the_step_left(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    sent = "Status. [DM @Troi] private [/DM] Done."
    out = withhold_dm_blocks(sent, agent_id="agent-7", where="response", dm_step_ran=True)
    assert " ".join(out.split()) == "Status. Done."
    assert _bf874(caplog) == []  # the DM step already sent, or logged, its readable blocks
    out = withhold_dm_blocks("Status. [DM @Troi] private [/DM] tail [/DM] Done.", agent_id="agent-7",
                             where="response", dm_step_ran=True)
    assert " ".join(out.split()) == "Status. Done."
    [msg] = _bf874(caplog)
    assert "0 unsent" in msg and "1 stray" in msg and "agent-7" in msg
    caplog.clear()
    withhold_dm_blocks(sent, agent_id="agent-7", where="response")
    [msg] = _bf874(caplog)
    assert "1 unsent" in msg  # without the DM step, a readable block was never sent


def test_dm_patterns_stay_linear_on_a_long_whitespace_run() -> None:
    text = "[DM" + " " * 40_000
    t0 = time.perf_counter()
    strip_dm_blocks(text)
    assert time.perf_counter() - t0 < 1.0


@pytest.mark.parametrize("text", [
    "[DM" * 50_000,
    "[/DM]" * 40_000,
    "[DM @Troi] x [/DM]" * 10_000,
    "[DM @Troi] a [DM@B] b [/DM] c [/DM] " * 5_000,
    "[" + " " * 100_000 + "/DM]",
], ids=["openers", "closers", "blocks", "orphans", "spaced-closer"])
def test_dm_scanner_stays_linear_on_long_tag_runs(text: str) -> None:
    t0 = time.perf_counter()
    strip_dm_blocks(text)
    assert time.perf_counter() - t0 < 1.0


# --- B: extract_and_execute_dms --------------------------------------------------------------

@pytest.mark.parametrize(("text", "title"), [
    ("Status nominal. [DM @Number One] {s} [/DM]", "[DM to @Number One]"),
    ("Status nominal. [DM @Number One] {s}", "[DM to @Number One]"),
    ("[DM @number one] {s} [/DM]", "[DM to @number one]"),
    ("[DM Number One] {s} [/DM]", "[DM to @Number One]"),
    ("[DM @ Troi] {s} [/DM]", "[DM to @Troi]"),
    ("[DM @Troi ] {s} [/DM]", "[DM to @Troi]"),
    ("[DM @Number One]\n{s}\n[/DM]", "[DM to @Number One]"),
])
async def test_dm_to_a_multiword_or_spaced_callsign_is_delivered(rig, text, title) -> None:
    secret = "SECRET-B1"
    out, actions = await rig.loop.extract_and_execute_dms(rig.sender, text.replace("{s}", secret))
    public, dm_titles = await rig.where(secret)
    assert dm_titles == [title]
    assert public == [] and secret not in out
    assert [a["type"] for a in actions] == ["dm"]


async def test_delivered_multiword_dm_is_an_exact_ad1229_receipt(rig) -> None:
    await rig.loop.extract_and_execute_dms(
        rig.sender, "[DM @Troi] Control check-in. [/DM] [DM @number one ] The drill moves to 1400. [/DM]",
    )
    tools = ToolRegistry()
    tools.register(MessageReceiptsTool(runtime=rig.rt), provider="AD-1229", tags=["message_receipts", "ward_room"])
    res = await tools.check_and_invoke(rig.sender.id, "message_receipts", {}, agent_rank="ensign")
    assert res.error is None, res.error
    got = {(m["to"], m["recipient_basis"], m["delivery"]) for m in res.output["messages"]}
    assert ("Troi", "exact", "delivered") in got  # premise: the tool proves a single-word receipt
    assert ("Number One", "exact", "delivered") in got


async def test_two_dms_in_one_text_are_both_delivered(rig) -> None:
    out, _ = await rig.loop.extract_and_execute_dms(
        rig.sender, "[DM @Troi] SECRET-B3a [/DM] Status. [DM @Number One] SECRET-B3b [/DM]",
    )
    assert (await rig.where("SECRET-B3a"))[1] == ["[DM to @Troi]"]
    assert (await rig.where("SECRET-B3b"))[1] == ["[DM to @Number One]"]
    assert out == "Status."


@pytest.mark.parametrize(("tag", "named"), [
    ("[DM @Nobody Here]", ("Nobody", "Here")),
    ("[DM @Troi meet me at 1400]", ("Troi meet", "meet me", "1400")),
])
async def test_unresolvable_callsign_warns_and_is_not_posted(rig, caplog, tag, named) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, actions = await rig.loop.extract_and_execute_dms(rig.sender, f"{tag} SECRET-B4 [/DM]")
    assert actions == [] and "SECRET-B4" not in out
    assert await rig.where("SECRET-B4") == ([], [])
    [msg] = _bf874(caplog)
    assert "Worf" in msg and "not sent" in msg
    assert not any(word in msg for word in named)  # A-2: what the model put inside the tag is never logged


@pytest.mark.parametrize("tag", ["[DM @Number One]", "[DM @number one ]"])
async def test_dm_to_crew_not_aboard_warns_and_is_not_posted(rig_factory, caplog, tag) -> None:
    rig = await rig_factory(aboard={"Worf", "Troi", "O'Brien"})
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, actions = await rig.loop.extract_and_execute_dms(rig.sender, f"{tag} SECRET-B5 [/DM]")
    assert actions == [] and "SECRET-B5" not in out
    [msg] = _bf874(caplog)
    assert "no architect is aboard" in msg
    assert "number one" not in msg.lower()  # A-2: only the registry's agent type is logged


@pytest.mark.parametrize("tag", ["[DM @captain]", "[DM @Captain ]"])
async def test_captain_dm_still_reaches_the_captain(rig, tag) -> None:
    await rig.loop.extract_and_execute_dms(rig.sender, f"{tag} SECRET-B6 [/DM]")
    public, dm_titles = await rig.where("SECRET-B6")
    assert public == [] and dm_titles == ["[DM to Captain from @Worf]"]


async def test_bf163_cooldown_covers_a_multiword_callsign_in_any_case(rig, caplog) -> None:
    await rig.loop.extract_and_execute_dms(rig.sender, "[DM @Number One] SECRET-B7a [/DM]")
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, actions = await rig.loop.extract_and_execute_dms(rig.sender, "[DM @number one ] SECRET-B7b [/DM]")
    assert (await rig.where("SECRET-B7a"))[1] == ["[DM to @Number One]"]
    assert actions == [] and await rig.where("SECRET-B7b") == ([], [])
    assert "SECRET-B7b" not in out
    assert _bf874(caplog) == []  # the BF-163 throttle dropped it, not the resolver


def _dm_ctx(rig: _Rig, body: str) -> DmReplyContext:
    return DmReplyContext(
        runtime=SimpleNamespace(proactive_loop=rig.loop), agent=rig.sender, agent_id=rig.sender.id,
        callsign="Worf", req_message="x", reply=DmReply(body=body), has_image_attachment=False,
        per_attachment=[], sanity_gate=None, params={}, message_text="x", sampling_state=None,
        avatar_event_bus=None,
    )


async def test_bf296_reply_delivers_a_multiword_dm(rig) -> None:
    ctx = _dm_ctx(rig, "On it. [DM @Number One] SECRET-B8 [/DM] Done.")
    await DmReplyPipeline(ctx).step_4b_dm_outbound_parse()
    assert (await rig.where("SECRET-B8")) == ([], ["[DM to @Number One]"])
    assert "SECRET-B8" not in ctx.response_text


async def test_bf296_unreadable_block_stays_visible_to_the_captain(rig) -> None:
    # Decision C-1: step 4b answers the Captain directly; an unsendable block stays in that
    # 1:1 reply (the Captain has oversight of DMs) and is never posted anywhere public.
    ctx = _dm_ctx(rig, "On it. [DM@Troi] SECRET-B9 [/DM] Done.")
    await DmReplyPipeline(ctx).step_4b_dm_outbound_parse()
    assert "[DM@Troi] SECRET-B9 [/DM]" in ctx.response_text
    assert await rig.where("SECRET-B9") == ([], [])


async def test_bf296_text_before_a_stray_closer_stays_visible_to_the_captain(rig) -> None:
    # Decision C-1 (A-2): step 4b sends the block and keeps the unsent text before the stray
    # [/DM] in the Captain's 1:1 reply; none of it is posted anywhere public.
    ctx = _dm_ctx(rig, "On it. [DM @Troi] SECRET-B9b-sent [/DM] SECRET-B9b-tail [/DM] Done.")
    await DmReplyPipeline(ctx).step_4b_dm_outbound_parse()
    assert await rig.where("SECRET-B9b-sent") == ([], ["[DM to @Troi]"])
    assert "SECRET-B9b-tail [/DM]" in ctx.response_text
    assert await rig.where("SECRET-B9b-tail") == ([], [])


@pytest.mark.parametrize(("body", "clear_cooldown", "gate"), [
    ("x", False, "BF-163:"),
    ("same words here", True, "AD-614:"),
], ids=["throttled", "similar"])
async def test_throttled_or_similar_dm_logs_no_tag_text(rig, caplog, body, clear_cooldown, gate) -> None:
    # A-3 (F-11): both gates drop the repeat before its callsign is resolved, so neither may log the tag text.
    caplog.set_level(logging.DEBUG, logger="probos.proactive")
    text = f"[DM @Worf meet me at 1400] {body} [/DM]"
    await rig.loop.extract_and_execute_dms(rig.sender, text)
    if clear_cooldown:
        rig.loop._dm_send_cooldowns.clear()  # so BF-163 lets the repeat reach the AD-614 gate
    await rig.loop.extract_and_execute_dms(rig.sender, text)
    messages = [r.getMessage() for r in caplog.records]
    assert any(gate in m for m in messages)  # premise: that gate dropped the repeat
    assert [m for m in messages if "meet me at 1400" in m] == []


# --- G/S: the public sinks fail closed ---------------------------------------------------------

async def test_unreadable_dm_in_proactive_text_is_withheld(rig, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, _ = await rig.loop._extract_and_execute_actions(rig.sender, "Status nominal. [DM@Troi] SECRET-G1 [/DM]")
    assert out == "Status nominal."
    assert any("'s response" in m for m in _bf874(caplog))


@pytest.mark.parametrize(("text", "dm_min_rank", "public", "dm_titles"), [
    ("[DM @Troi] private-prefix [DM@Bad] private-nested [/DM] {s} [/DM] public-after", "ensign",
     "public-after", ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] ok [/DM] {s} [/DM] public-after", "ensign",
     "Status nominal. public-after", ["[DM to @Troi]"]),
    ("Status nominal. [DM @Troi] ok [/DM] [DM@Bad] no [/DM] {s} [/DM]", "ensign",
     "Status nominal.", ["[DM to @Troi]"]),
    ("[DM @Troi] private-prefix [DM@Bad] private-nested [/DM] {s} [/DM] public-after", "commander",
     "public-after", []),
], ids=["review-r1-input", "closer-text-closer", "malformed-opener-after", "below-dm-min-rank"])
async def test_text_before_a_stray_closer_is_withheld(rig_factory, caplog, text, dm_min_rank, public, dm_titles) -> None:
    rig = await rig_factory(dm_min_rank=dm_min_rank)
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, _ = await rig.loop._extract_and_execute_actions(rig.sender, text.replace("{s}", "SECRET-G1b"))
    assert " ".join(out.split()) == public
    assert await rig.where("SECRET-G1b") == ([], [])
    assert await rig.dm_titles() == dm_titles
    assert any("1 stray" in m for m in _bf874(caplog))


async def test_a_sent_dm_logs_no_bf874_warning_on_the_response(rig, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, actions = await rig.loop._extract_and_execute_actions(
        rig.sender, "Status nominal. [DM @Number One] SECRET-G1c [/DM]",
    )
    assert out == "Status nominal." and [a["type"] for a in actions if a.get("type") == "dm"] == ["dm"]
    assert (await rig.where("SECRET-G1c"))[1] == ["[DM to @Number One]"]
    assert _bf874(caplog) == []  # the guard reads the DM step's input; a block it sent is not unsent


async def test_dm_below_dm_min_rank_is_withheld_not_posted(rig_factory, caplog) -> None:
    rig = await rig_factory(dm_min_rank="commander")
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    out, actions = await rig.loop._extract_and_execute_actions(rig.sender, "Status nominal. [DM @Troi] SECRET-G1b [/DM]")
    assert out == "Status nominal." and not any(a.get("type") == "dm" for a in actions)
    assert await rig.where("SECRET-G1b") == ([], [])
    assert _bf874(caplog)


async def test_dm_nested_in_a_reply_is_withheld(rig, caplog) -> None:
    tid = await rig.department_thread("Patrol plan", "Proposed patrol plan.")
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    await rig.loop._extract_and_execute_actions(
        rig.sender, f"[REPLY {tid}] Agreed on the patrol plan. [DM @Troi] SECRET-G2 [/DM] [/REPLY]",
    )
    posts = _bodies((await rig.ws.get_thread(tid) or {}).get("posts", []))
    assert any("Agreed on the patrol plan." in p for p in posts)  # premise: the reply was posted
    assert await rig.where("SECRET-G2") == ([], [])
    assert any("thread reply" in m for m in _bf874(caplog))


async def test_text_before_a_stray_closer_in_a_reply_is_withheld(rig, caplog) -> None:
    tid = await rig.department_thread("Patrol plan", "Proposed patrol plan.")
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    await rig.loop._extract_and_execute_actions(
        rig.sender, f"[REPLY {tid}] Agreed. [DM @Troi] ok [/DM] SECRET-G2b [/DM] See you there. [/REPLY]",
    )
    posts = _bodies((await rig.ws.get_thread(tid) or {}).get("posts", []))
    assert any("Agreed." in p and "See you there." in p for p in posts)  # premise: the reply was posted
    assert await rig.where("SECRET-G2b") == ([], [])
    assert any("thread reply" in m and "1 stray" in m for m in _bf874(caplog))


def _pipeline(rig: _Rig, *, with_loop: bool) -> WardRoomPostPipeline:
    return WardRoomPostPipeline(
        ward_room=rig.ws, ward_room_router=None, proactive_loop=rig.loop if with_loop else None,
        trust_network=rig.rt.trust_network, callsign_registry=rig.callsigns, config=rig.config, runtime=rig.rt,
    )


async def test_pipeline_without_a_loop_withholds_the_dm_block(rig, caplog) -> None:
    tid = await rig.department_thread("Drill timing", "When is the drill?")
    caplog.set_level(logging.WARNING, logger="probos.proactive")
    posted = await _pipeline(rig, with_loop=False).process_and_post(
        agent=rig.sender, response_text="I concur. [DM @Troi] SECRET-G3a [/DM]", thread_id=tid,
        event_type="ward_room_thread_created",
    )
    assert posted
    assert await rig.where("SECRET-G3a") == ([], [])
    assert any("Ward Room reply" in m for m in _bf874(caplog))


async def test_pipeline_with_the_loop_delivers_a_multiword_dm(rig) -> None:
    tid = await rig.department_thread("Drill timing", "When is the drill?")
    posted = await _pipeline(rig, with_loop=True).process_and_post(
        agent=rig.sender, response_text="I concur. [DM @Number One] SECRET-G3b [/DM]", thread_id=tid,
        event_type="ward_room_thread_created",
    )
    assert posted
    assert await rig.where("SECRET-G3b") == ([], ["[DM to @Number One]"])


async def test_pipeline_reply_that_is_only_a_dm_block_posts_nothing(rig) -> None:
    tid = await rig.department_thread("Drill timing", "When is the drill?")
    posted = await _pipeline(rig, with_loop=False).process_and_post(
        agent=rig.sender, response_text="[DM@Troi] SECRET-G3c [/DM]", thread_id=tid,
        event_type="ward_room_thread_created",
    )
    assert posted is False
    assert _bodies((await rig.ws.get_thread(tid) or {}).get("posts", [])) == []


@pytest.mark.parametrize(("with_loop", "dm_titles"), [(False, []), (True, ["[DM to @Troi]"])], ids=["no-loop", "with-loop"])
async def test_pipeline_withholds_the_text_before_a_stray_closer(rig, with_loop, dm_titles) -> None:
    tid = await rig.department_thread("Drill timing", "When is the drill?")
    posted = await _pipeline(rig, with_loop=with_loop).process_and_post(
        agent=rig.sender, response_text="I concur. [DM @Troi] ok [/DM] SECRET-G3d [/DM] Drill at 1400.",
        thread_id=tid, event_type="ward_room_thread_created",
    )
    assert posted
    posts = _bodies((await rig.ws.get_thread(tid) or {}).get("posts", []))
    assert any("I concur." in p and "Drill at 1400." in p for p in posts)
    assert await rig.where("SECRET-G3d") == ([], [])
    assert await rig.dm_titles() == dm_titles


async def test_observation_that_is_only_a_dm_block_posts_nothing(rig) -> None:
    dept = next(c for c in await rig.ws.list_channels() if c.channel_type == "department" and c.department == "security")
    await rig.loop._post_to_ward_room(rig.sender, "[DM@Troi] SECRET-S1 [/DM]")
    assert await rig.ws.list_threads(dept.id) == []


# --- X: census ---------------------------------------------------------------------------------

def test_every_public_sink_that_strips_markers_also_withholds_dm_blocks() -> None:
    paired: list[str] = []
    for rel in ("proactive.py", "ward_room_pipeline.py"):
        tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            strips = [c.lineno for c in calls if c.func.id == "_strip_bracket_markers"]
            if not strips or fn.name == "_strip_bracket_markers":
                continue
            guards = [c.lineno for c in calls if c.func.id == "withhold_dm_blocks"]
            assert guards and min(guards) > min(strips), f"{rel}:{fn.name} strips markers but posts DM blocks"
            paired.append(fn.name)
    assert sorted(paired) == ["_extract_and_execute_replies", "_post_to_ward_room", "process_and_post"]


# A-2: the G1 guard strips the DM step's INPUT, so it must remove at least what the DM step removed.
CORPUS = [
    "Status nominal. [DM @Number One] X2A [/DM] tail",
    "[DM @Troi] X2B [DM@Bad] X2C [/DM] X2D [/DM] after",
    "lead [DM@Bad] X2E [DM @Troi] X2F [/DM] X2G [/DM] after",
    "lead [DM @Troi] X2H [DM @O'Brien] X2I [/DM] X2J [/DM] after",
    "lead [DM @Troi] X2K [DM] X2L [/DM] after",
    "lead [DM @Troi] X2M [/ DM] X2N [/DM] after",
    "[DM @Troi] X2O then [DM @Number One] X2P [/DM] after",
    "[D[DM @Troi] X2Q [/DM]M @O'Brien] X2R joined",
    "a [DM @Troi] X2S [/DM] c [DM@Bad] X2T [/DM] e",
    "X2U [/DM] lead [DM @Troi] X2V [/DM] after",
]


def _is_subsequence(short: str, long: str) -> bool:
    rest = iter(long)
    return all(ch in rest for ch in short)


@pytest.mark.parametrize("text", CORPUS)
async def test_guard_never_posts_what_the_dm_step_removed(rig, text) -> None:
    cleaned, _ = await rig.loop.extract_and_execute_dms(rig.sender, text)
    public = strip_dm_blocks(text).text
    assert _is_subsequence(public, cleaned), (public, cleaned)
    for body in await rig.dm_bodies():
        assert body not in public
