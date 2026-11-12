"""BF-935 (#1674): a Scout run lists each repository once, however many of its topic searches return it.

The real ScoutAgent runs ``perceive`` with ``_search_github`` and ``CognitiveAgent.perceive`` replaced (canned results per topic; no
network) and a runtime double whose data directory is under ``tmp_path``. The seam case runs ``act`` over a classification text built
as a model builds it (one report per REPO block it was shown) through the real SCOUT_REPORT_CHAIN. The class holds the cases the
unfixed tree fails; the functions before it pass on both. No BF-935 name is imported.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.process_chains import ProcessChainRegistry
from probos.cognitive.scout import SCOUT_REPORT_CHAIN, ScoutAgent

TOPICS = {"ai-agents": 50, "llm-agents": 50, "multi-agent": 50, "agent-framework": 50, "ai-coding": 100, "code-generation": 100}
X, Y, Z = "a/x", "b/y", "c/z"
FINDING = {"repo_full_name": X, "stars": 1, "url": "u", "classification": "absorb", "relevance": 5, "credibility": 4,
           "reliability": 4, "summary": "s", "insight": "i"}
CASES = {  # what each search returns | already seen | listed once, first-listed order | repeat listings | topics that returned each
    "overlap": ({"ai-agents": [X, Y], "llm-agents": [Y, Z]}, [], [X, Y, Z], 1,
                {X: ["ai-agents"], Y: ["ai-agents", "llm-agents"], Z: ["llm-agents"]}),
    "three-searches": ({"ai-agents": [Y], "ai-coding": [Y, X], "code-generation": [Y]}, [], [Y, X], 2,
                       {Y: ["ai-agents", "ai-coding", "code-generation"], X: ["ai-coding"]}),
    "no-overlap": ({"ai-agents": [X], "llm-agents": [Y]}, [], [X, Y], 0, {X: ["ai-agents"], Y: ["llm-agents"]}),
    "twice-in-one-search": ({"ai-agents": [X, X]}, [], [X], 1, {X: ["ai-agents"]}),
    "seen-is-not-counted": ({"ai-agents": [X, Y], "llm-agents": [Y, Z]}, [Y], [X, Z], 0, {X: ["ai-agents"], Z: ["llm-agents"]}),
}


def _item(name: str, **over: object) -> dict:
    """One search result as the search API shapes it."""
    return {"full_name": name, "description": f"about {name}", "stargazers_count": 100, "language": "Python",
            "license": {"spdx_id": "MIT"}, "topics": ["ai-agents", "rag"], "html_url": f"https://github.com/{name}", **over}


def _block(name: str, description: str = "") -> str:
    """The prompt block of ``_item(name)``, written out here and not taken from the code."""
    return (f"REPO: {name}\nDESC: {description or 'about ' + name}\nSTARS: 100\nLANG: Python\nLICENSE: MIT\n"
            f"TOPICS: ai-agents, rag\nURL: https://github.com/{name}\n")


def _repos(context: str) -> list[str]:
    return [line[6:] for line in context.splitlines() if line.startswith("REPO: ")]


def _answer(context: str) -> str:
    """What a model that classifies every block it is shown answers: one absorb report (composite 4.5) per REPO block."""
    return "".join(f"===SCOUT_REPORT===\nREPO: {n}\nSTARS: 100\nURL: https://github.com/{n}\nCLASS: absorb\nRELEVANCE: 5\n"
                   "CREDIBILITY: 4\nRELIABILITY: 4\nSUMMARY: s\nINSIGHT: i\n===END===\n" for n in _repos(context))


class _Scene:
    """A real ScoutAgent over a temporary data directory; ``found`` maps a topic to the items its search returns."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.data = tmp_path / "data"
        self.data.mkdir()
        self.found: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, int]] = []
        self.notified: list[str] = []
        registry = ProcessChainRegistry()
        registry.register_chain(SCOUT_REPORT_CHAIN)
        queue = SimpleNamespace(notify=lambda **kw: self.notified.append(kw["title"]))
        runtime = SimpleNamespace(_data_dir=self.data, process_chain_registry=registry, notification_queue=queue)
        self.agent = ScoutAgent(agent_id="scout-935", runtime=runtime)

        async def search(_agent: ScoutAgent, query: str, min_stars: int) -> list[dict]:
            self.calls.append((query, min_stars))
            return self.found.get(query.split(" ", 1)[0].removeprefix("topic:"), [])

        monkeypatch.setattr(ScoutAgent, "_search_github", search)
        monkeypatch.setattr(CognitiveAgent, "perceive",
                            AsyncMock(side_effect=lambda _i: {"intent": "scout_search", "params": {}, "context": ""}))

    def seen(self, *names: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        (self.data / "scout_seen.json").write_text(json.dumps({n: stamp for n in names}), encoding="utf-8")

    def report(self, day: str, finding: dict, **top: object) -> None:
        (self.data / "scout_reports").mkdir(exist_ok=True)
        body = {"date": day, "total_classified": 1, "total_relevant": 1, **top, "findings": [finding]}
        (self.data / "scout_reports" / f"{day}.json").write_text(json.dumps(body), encoding="utf-8")

    async def perceive(self) -> dict:
        return await self.agent.perceive({"intent": "scout_search"})


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Scene:
    return _Scene(tmp_path, monkeypatch)


async def test_the_searches_and_one_prompt_block_are_as_before(scene):
    scene.found = {"ai-agents": [_item(X)]}
    result = await scene.perceive()
    queries = [(re.sub(r"\d{4}-\d{2}-\d{2}$", "DATE", q), stars) for q, stars in scene.calls]
    assert queries == [(f"topic:{t} pushed:>DATE", stars) for t, stars in TOPICS.items()]
    assert result["context"] == "Classify these 1 repositories:\n\n" + _block(X)


async def test_without_a_repeat_the_prompt_the_pending_names_and_the_entries_are_as_before(scene):
    scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(Y)], "multi-agent": [_item(Z)]}
    result = await scene.perceive()
    assert result["context"] == "Classify these 3 repositories:\n\n" + "\n---\n".join(_block(n) for n in (X, Y, Z))
    assert scene.agent._pending_seen_repos == [X, Y, Z]
    old = {n: {"full_name": n, "description": f"about {n}", "stars": 100, "created_at": "", "updated_at": "", "language": "Python",
               "license": "MIT", "topics": ["ai-agents", "rag"], "url": f"https://github.com/{n}"} for n in (X, Y, Z)}
    assert {n: {k: v for k, v in m.items() if k != "matched_topics"} for n, m in scene.agent._repo_metadata.items()} == old


async def test_a_seen_repository_is_skipped_and_perceive_marks_nothing_seen(scene):
    scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Z)]}
    scene.seen(Y)
    before = (scene.data / "scout_seen.json").read_bytes()
    result = await scene.perceive()
    assert _repos(result["context"]) == [X, Z] and scene.agent._pending_seen_repos == [X, Z]
    assert (scene.data / "scout_seen.json").read_bytes() == before


@pytest.mark.parametrize("seen", [[], [X]])
async def test_when_nothing_is_new_the_answer_is_as_before(scene, seen):
    scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(X)]} if seen else {}
    scene.seen(*seen)
    result = await scene.perceive()
    assert result["context"] == "No new repositories found since last scan." and scene.agent._pending_seen_repos == []


def test_an_older_report_still_loads(scene):
    scene.report("2026-01-01", FINDING)
    assert X in (scene.agent._load_latest_report() or "")


class TestARepeatIsMerged:
    # BF-935 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-935 M2 builds it")

    @pytest.mark.parametrize("case", CASES)
    async def test_each_repository_is_listed_once_with_its_topics_and_the_repeats_are_counted(self, scene, case):
        found, seen, listed, repeats, topics = CASES[case]
        assert sum(n not in seen for names in found.values() for n in names) - len(listed) == repeats, "premise: the table"
        scene.found = {t: [_item(n) for n in names] for t, names in found.items()}
        scene.seen(*seen)
        result = await scene.perceive()
        assert getattr(scene.agent, "_duplicate_listings", None) == repeats
        assert result["context"].startswith(f"Classify these {len(listed)} repositories:\n\n")
        assert _repos(result["context"]) == listed and scene.agent._pending_seen_repos == listed
        assert {n: m.get("matched_topics") for n, m in scene.agent._repo_metadata.items()} == topics

    async def test_the_first_listing_is_kept_and_the_prompt_is_one_block_of_the_old_text(self, scene):
        scene.found = {"ai-agents": [_item(Y, description="first listing")],
                       "llm-agents": [_item(Y, description="later listing", stargazers_count=900, topics=["other"])]}
        result = await scene.perceive()
        assert result["context"] == "Classify these 1 repositories:\n\n" + _block(Y, "first listing")
        assert scene.agent._repo_metadata[Y]["description"] == "first listing" and scene.agent._repo_metadata[Y]["stars"] == 100

    async def test_the_count_belongs_to_the_last_search_alone(self, scene):
        scene.found = {"ai-agents": [_item(X)], "llm-agents": [_item(X)]}
        await scene.perceive()
        assert getattr(scene.agent, "_duplicate_listings", None) == 1
        scene.seen(X)  # the next search finds nothing new, so perceive returns early
        result = await scene.perceive()
        assert result["context"] == "No new repositories found since last scan." and scene.agent._duplicate_listings == 0

    async def test_one_line_per_search_run_records_the_counts(self, scene, caplog):
        scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Y), _item(Z)]}
        with caplog.at_level(logging.INFO, logger="probos.cognitive.scout"):
            await scene.perceive()
        assert [(r.levelno, r.args) for r in caplog.records if r.name == "probos.cognitive.scout"] == [(logging.INFO, (4, 3, 6, 1))]

    async def test_the_chain_scores_and_notifies_each_repository_once_and_records_the_repeats(self, scene):
        scene.found = {"ai-agents": [_item(X), _item(Y)], "llm-agents": [_item(Y), _item(Z)], "ai-coding": [_item(Y)]}
        context = (await scene.perceive())["context"]
        decision = {"intent": "scout_search", "duty": {"duty_id": "scout_report"}, "llm_output": _answer(context)}
        out = await scene.agent.act(decision)
        report = json.loads(next((scene.data / "scout_reports").glob("*.json")).read_text(encoding="utf-8"))
        assert sorted(f["repo_full_name"] for f in report["findings"]) == [X, Y, Z] and report["total_classified"] == 3
        assert report.get("duplicate_listings") == 2
        assert {f["repo_full_name"]: f.get("matched_topics") for f in report["findings"]} == {
            X: ["ai-agents"], Y: ["ai-agents", "llm-agents", "ai-coding"], Z: ["llm-agents"]}
        assert sorted(scene.notified) == [f"Scout: {n}" for n in (X, Y, Z)]
        assert out["success"] is True and out["result"].count(f"- **{Y}**") == 1 and "3 findings" in out["result"]
        assert sorted(json.loads((scene.data / "scout_seen.json").read_text(encoding="utf-8"))) == [X, Y, Z]

    def test_a_report_with_the_new_keys_loads(self, scene):
        scene.report("2026-01-02", {**FINDING, "repo_full_name": Y, "matched_topics": ["ai-agents", "llm-agents"]}, duplicate_listings=1)
        digest = scene.agent._load_latest_report()
        assert digest is not None and Y in digest
