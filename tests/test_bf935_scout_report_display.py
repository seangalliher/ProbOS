"""BF-935 A1 (#1674): ``/scout report`` shows the saved Scout report and does nothing else.

``scout_report`` is the intent that shows the latest saved report: ``/scout report`` sends it, and the agent's intent descriptor,
which natural-language routing reads, offers it. Before A1 the model was asked about it all the same and its answer went through
the classify, store and notify chain, so showing a report rewrote the day's file (with the model's wording, or with no findings),
told the Captain again and marked the names of an earlier failed search as seen. These cases run the real command, intent handler
and lifecycle on a real ScoutAgent over a temporary data directory, with the model's ``decide`` and the GitHub search replaced: no
network. The report cases fail on the tree without A1; the two search cases pass on both and keep the new ``decide`` from
answering a search itself. The A2 cases (review round 2) print through a real Rich console, which the world's own console
does not (it only collects what it is given): a bracket in a saved or model-written summary raised or vanished before A2.
The A3 case (review round 3) holds that console to what it promises: it reads nothing, from the environment or the platform,
that could change what the cases compare.
"""

from __future__ import annotations

import builtins
import io
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.process_chains import ProcessChainRegistry
from probos.cognitive.scout import SCOUT_REPORT_CHAIN, ScoutAgent
from probos.experience.commands.commands_knowledge import cmd_scout
from probos.types import IntentMessage

ALPHA, BETA = "o/alpha", "o/beta"
NONE_YET = "No scout reports found yet. Run /scout to generate one."


def _block(name: str, relevance: int, summary: str = "the model's summary") -> str:
    """One classification block as the Scout's instructions ask for it (absorb; composite 4.5 at relevance 5, 4.0 at 4)."""
    return (f"===SCOUT_REPORT===\nREPO: {name}\nSTARS: 120\nURL: https://github.com/{name}\nCLASS: absorb\nRELEVANCE: {relevance}\n"
            f"CREDIBILITY: 4\nRELIABILITY: 4\nSUMMARY: {summary}\nINSIGHT: the model's insight\n===END===\n")


ANSWERS = {  # what a model could answer to the digest it was shown, were it asked
    "blocks": _block(ALPHA, 5) + _block(BETA, 4),  # a classification block for each repository of the digest
    "prose": "Here is a summary of the latest scout report: two repositories look useful.",  # no block at all
    "empty": "",
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _saved(day: str) -> dict:
    """A day's report as BF-935 writes it: provenance on each finding and the repeat count of the run."""
    def finding(name: str, relevance: int, matched: list[str]) -> dict:
        return {"repo_full_name": name, "stars": 120, "url": f"https://github.com/{name}", "classification": "absorb",
                "relevance": relevance, "credibility": 4, "reliability": 4, "summary": f"saved summary of {name}",
                "insight": f"saved insight on {name}", "language": "Python", "license": "MIT", "topics": ["ai-agents", "rag"],
                "matched_topics": matched}
    return {"date": day, "total_classified": 2, "total_relevant": 2, "duplicate_listings": 5,
            "findings": [finding(ALPHA, 5, ["ai-agents", "llm-agents"]), finding(BETA, 4, ["multi-agent"])]}


def _item(name: str) -> dict:
    """One search result as the search API shapes it."""
    return {"full_name": name, "description": f"about {name}", "stargazers_count": 100, "language": "Python",
            "license": {"spdx_id": "MIT"}, "topics": ["ai-agents", "rag"], "html_url": f"https://github.com/{name}"}


def _classify(context: str, summary: str = "the model's summary") -> str:
    """What a model that classifies every block it is shown answers: one absorb report (composite 4.5) per REPO block."""
    return "".join(_block(line[6:], 5, summary) for line in context.splitlines() if line.startswith("REPO: "))


class _World:
    """A real ScoutAgent behind the real ``/scout`` command and ``handle_intent``; ``answer`` is the model's reply to what it is asked."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reports = tmp_path / "data" / "scout_reports"
        self.seen = tmp_path / "data" / "scout_seen.json"
        self.notified: list[str] = []
        self.printed: list[str] = []
        self.asked: list[str] = []  # the intent of each observation the model was asked about
        self.found: list[str] = []  # the repositories the first topic search returns
        self.answer: Callable[[str], str] = lambda context: ""
        registry = ProcessChainRegistry()
        registry.register_chain(SCOUT_REPORT_CHAIN)
        queue = SimpleNamespace(notify=lambda **kw: self.notified.append(kw["title"]))
        self.runtime = SimpleNamespace(_data_dir=tmp_path / "data", process_chain_registry=registry, notification_queue=queue, pools={})
        self.agent = ScoutAgent(agent_id="scout-935a", runtime=self.runtime)
        pool = SimpleNamespace(healthy_agents=[self.agent.id], registry=SimpleNamespace(get=lambda _id: self.agent))
        self.runtime.pools["scout"] = pool
        self.console = SimpleNamespace(print=lambda *args, **kw: self.printed.append(" ".join(str(a) for a in args)))

        async def decide(_agent: CognitiveAgent, observation: dict) -> dict:
            self.asked.append(observation["intent"])
            return {"action": "execute", "llm_output": self.answer(observation["context"])}

        async def search(_agent: ScoutAgent, query: str, min_stars: int) -> list[dict]:
            return [_item(name) for name in self.found] if query.startswith("topic:ai-agents ") else []

        monkeypatch.setattr(CognitiveAgent, "decide", decide)
        monkeypatch.setattr(ScoutAgent, "_search_github", search)

    def save(self, day: str, summary: str | None = None) -> None:
        report = _saved(day)
        if summary is not None:
            report["findings"][0]["summary"] = summary
        self.reports.mkdir(parents=True, exist_ok=True)
        (self.reports / f"{day}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def snapshot(self) -> dict[str, bytes]:
        """Every file of the reports directory, by name; a directory that does not exist is an empty snapshot."""
        return {p.name: p.read_bytes() for p in sorted(self.reports.glob("*"))} if self.reports.exists() else {}


def _the_search_ran(world: _World) -> None:
    """The model was asked once, about a search (perceive renames the duty's intent); its two reports are stored and notified."""
    assert world.asked == ["scout_search"]
    stored = [json.loads(p.read_text(encoding="utf-8")) for p in world.reports.glob("*.json")]
    assert [sorted(f["repo_full_name"] for f in report["findings"]) for report in stored] == [[ALPHA, BETA]]
    assert sorted(world.notified) == [f"Scout: {ALPHA}", f"Scout: {BETA}"]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _World:
    return _World(tmp_path, monkeypatch)


@pytest.mark.parametrize("answer", ANSWERS)
async def test_the_report_command_shows_the_saved_report_and_changes_nothing(world, answer):
    world.answer = lambda _context: ANSWERS[answer]
    world.save(_today())
    before = world.snapshot()
    await cmd_scout(world.runtime, world.console, "report")
    assert world.snapshot() == before, "a file of the reports directory was rewritten or added"
    assert world.notified == [], "the Captain was notified again"
    assert world.asked == [], "the model was asked about a report that only had to be shown"
    digest = world.agent._load_latest_report()
    assert digest is not None and f"saved summary of {ALPHA}" in digest, "premise: the saved report loads"
    assert world.printed == ["[dim]Running scout scout_report...[/dim]", digest]


async def test_the_natural_language_route_gets_the_saved_report_and_changes_nothing(world):
    world.answer = lambda _context: ANSWERS["blocks"]
    world.save("2020-01-02")  # an earlier day: a rewrite would add a file for today, which would then hide this one
    before = world.snapshot()
    result = await world.agent.handle_intent(IntentMessage(intent="scout_report", params={}, context="show me the latest scout report"))
    assert world.snapshot() == before and world.notified == [] and world.asked == []
    assert result.success is True and result.result == world.agent._load_latest_report() and f"saved summary of {BETA}" in result.result


async def test_with_no_saved_report_it_says_so_and_writes_nothing(world):
    world.answer = lambda _context: ANSWERS["prose"]
    await cmd_scout(world.runtime, world.console, "report")
    assert not world.reports.exists(), "a report with no findings was written"
    assert world.notified == [] and world.asked == []
    assert world.printed == ["[dim]Running scout scout_report...[/dim]", NONE_YET]


async def test_a_report_after_a_failed_search_leaves_that_search_unmarked(world):
    world.found, world.answer = [ALPHA, BETA], lambda _context: ""  # the search's model call yields nothing: BF-214 marks nothing seen
    await cmd_scout(world.runtime, world.console, "")
    assert not world.seen.exists() and world.agent._pending_seen_repos == [ALPHA, BETA], "premise: BF-214 defers the marking"
    world.save("2020-01-02")
    world.answer = lambda _context: ANSWERS["blocks"]  # would classify the pending names, if the model were asked
    await cmd_scout(world.runtime, world.console, "report")
    assert not world.seen.exists(), "the repositories of the failed search were marked seen without being classified"
    assert world.agent._pending_seen_repos == [ALPHA, BETA] and world.asked == ["scout_search"]


async def test_the_search_command_still_classifies_stores_and_notifies(world):
    world.found, world.answer = [ALPHA, BETA], _classify
    await cmd_scout(world.runtime, world.console, "")
    _the_search_ran(world)
    assert world.printed[0] == "[dim]Running scout scout_search...[/dim]" and ALPHA in world.printed[-1]


async def test_the_duty_search_still_classifies_stores_and_notifies(world):
    world.found, world.answer = [ALPHA, BETA], _classify
    duty = {"duty_id": "scout_report", "description": "the daily report"}
    result = await world.agent.handle_intent(IntentMessage(intent="proactive_think", params={"duty": duty}, target_agent_id=world.agent.id))
    _the_search_ran(world)
    assert result.success is True and ALPHA in result.result


MARKUP_TEXTS = {  # text Rich reads as markup, as a saved or model-written summary may hold it
    "plain": "A plain summary of the repository.",  # no markup of its own: the digest's own score tags still carry the failure
    "closing-tag": "Parses BBCode closing tags such as [/b].",  # an unmatched closing tag: Rich raises MarkupError
    "style-tag": "Styles its output with [bold red]Rich[/bold red] markup.",  # a matched tag: Rich applies the style and drops the tags
}
FAILURES = {  # the same two shapes in the message of a failed intent
    "closing-tag": "the search failed at [/b]",
    "style-tag": "the search failed at [bold red]step 2[/bold red]",
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _console(*, colour: bool = False) -> tuple[Console, io.StringIO]:
    """A real Rich console that writes to a buffer; the world's own console is a print lambda, which parses no markup.
    Rich reads the environment and the platform for each setting it is not given; all eight that it reads are given here, so
    neither changes what a case compares: a line shorter than 400 columns is never wrapped and, with colour, the codes are the
    ones a terminal gets. ``test_the_display_console_reads_nothing_from_its_surroundings`` sets what Rich reads and checks it."""
    buffer = io.StringIO()
    # Given because Rich would read them: both dimensions together (COLUMNS, LINES, TERM, the terminal: one alone is not enough),
    # force_terminal (FORCE_COLOR, TTY_COMPATIBLE, isatty), force_jupyter (a notebook kernel), force_interactive (TTY_INTERACTIVE, TERM),
    # no_color (NO_COLOR), color_system (COLORTERM, TERM) and legacy_windows (the platform).
    console = Console(
        file=buffer,
        width=400,
        height=25,
        force_terminal=colour,
        force_jupyter=False,
        force_interactive=False,
        no_color=False,
        color_system="standard" if colour else None,
        legacy_windows=False,
    )
    return console, buffer


@pytest.mark.parametrize("text", MARKUP_TEXTS)
async def test_the_report_command_prints_the_saved_report_as_text(world, text):
    world.save(_today(), MARKUP_TEXTS[text])
    digest = world.agent._load_latest_report()
    assert digest is not None and MARKUP_TEXTS[text] in digest and "[score: 4.5]" in digest, "premise: the summary and the score tag are in the digest"
    console, buffer = _console()
    await cmd_scout(world.runtime, console, "report")
    assert buffer.getvalue().rstrip() == f"Running scout scout_report...\n{digest}".rstrip(), "Rich read part of the digest as markup"


@pytest.mark.parametrize("text", MARKUP_TEXTS)
async def test_the_search_command_prints_what_the_model_wrote_as_text(world, text):
    world.found, world.answer = [ALPHA, BETA], lambda context: _classify(context, MARKUP_TEXTS[text])
    console, buffer = _console()
    await cmd_scout(world.runtime, console, "")
    _the_search_ran(world)  # premise: both reports were classified, stored and notified
    shown = buffer.getvalue()
    assert shown.startswith("Running scout scout_search...\n") and ALPHA in shown and BETA in shown
    assert shown.count(MARKUP_TEXTS[text]) == 2 and shown.count("[score: 4.5]") == 2, "Rich read part of the digest as markup"


@pytest.mark.parametrize("message", FAILURES)
async def test_a_failure_whose_message_holds_markup_prints_as_text(world, monkeypatch, message):
    async def fail(_message: IntentMessage) -> None:
        raise RuntimeError(FAILURES[message])

    monkeypatch.setattr(world.agent, "handle_intent", fail)
    console, buffer = _console(colour=True)
    await cmd_scout(world.runtime, console, "")
    shown = buffer.getvalue()
    assert f"Scout error: {FAILURES[message]}" in ANSI.sub("", shown), "Rich read part of the message as markup"
    assert "\x1b[31mScout error: " in shown, "the failure line is not red"


RICH_READS = (  # every variable Rich reads when it prints through a Console, in Rich 13 to 15 (UNICODE_VERSION: Rich 14 only); the case clears them all, then sets its own
    "TERM", "COLUMNS", "LINES", "NO_COLOR", "FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE", "COLORTERM",
    "JUPYTER_COLUMNS", "JUPYTER_LINES", "DATABRICKS_RUNTIME_VERSION", "UNICODE_VERSION",
)
ENVIRONMENTS = {  # what Rich could read: (the variables set, a notebook kernel's get_ipython, a Windows console without VT support)
    "unset": ({}, False, False),
    "dumb-terminal": ({"TERM": "dumb"}, False, False),  # Console.size answers 80 x 25 unless both dimensions are given, and there is no colour
    "narrow-terminal": ({"COLUMNS": "20", "LINES": "5"}, False, False),
    "no-colour": ({"NO_COLOR": "1"}, False, False),
    "forced-colour": ({"FORCE_COLOR": "1", "TTY_INTERACTIVE": "1", "TERM": "xterm-256color", "COLORTERM": "truecolor"}, False, False),
    "not-a-terminal": ({"TTY_COMPATIBLE": "0"}, False, False),
    "notebook": ({"JUPYTER_COLUMNS": "20", "JUPYTER_LINES": "5"}, True, False),  # the render would go to the notebook, not to the buffer
    "old-windows-console": ({}, False, True),  # the width less one, no hyperlinks
}
LONG_FAILURE = "the search failed at " + "x" * 130  # 151 characters: wider than a dumb terminal's 80 columns, narrower than the console's 400


@pytest.mark.parametrize("environment", ENVIRONMENTS)
async def test_the_display_console_reads_nothing_from_its_surroundings(world, monkeypatch, environment):
    variables, notebook, old_windows = ENVIRONMENTS[environment]
    for name in RICH_READS:
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delattr(builtins, "get_ipython", raising=False)  # a suite run inside a notebook must not change the other surroundings
    if notebook:
        monkeypatch.setattr(builtins, "get_ipython", lambda: type("ZMQInteractiveShell", (), {})(), raising=False)
    monkeypatch.setattr("rich.console.detect_legacy_windows", lambda: old_windows)  # not the real platform's answer
    for colour in (False, True):
        console, buffer = _console(colour=colour)
        assert console.size == (400, 25), f"colour={colour}: a dimension came from the surroundings"
        assert (console.is_terminal, console.color_system) == (colour, "standard" if colour else None), f"colour={colour}: the terminal or its colours were detected"
        assert not (console.is_jupyter or console.is_interactive or console.legacy_windows or console.no_color), f"colour={colour}: a notebook, a session, an old Windows console or NO_COLOR was detected"
        console.print(LONG_FAILURE, markup=False)
        assert ANSI.sub("", buffer.getvalue()) == LONG_FAILURE + "\n", f"colour={colour}: the line wrapped, or was not written"

    async def fail(_message: IntentMessage) -> None:
        raise RuntimeError(LONG_FAILURE)

    monkeypatch.setattr(world.agent, "handle_intent", fail)
    console, buffer = _console(colour=True)
    await cmd_scout(world.runtime, console, "")
    shown = buffer.getvalue()
    assert ANSI.sub("", shown) == f"Running scout scout_search...\nScout error: {LONG_FAILURE}\n", "the failure line wrapped, or lost text"
    assert "\x1b[31mScout error: " in shown, "the failure line is not red"
