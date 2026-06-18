"""BF-631: query-echo filtering in per-message recall + recall observability.

Root cause (proven 2026-06-18, offline reproduction against the live store):
after BF-630 fixed the keyword axis, ``recall_weighted`` DOES surface the dog
answer ("My dog, Grim, is a giant snouser") for the query "What do you know
about my dogs?" — but it ranks 4th of 5 because the top 3 slots are filled by
the Captain's OWN prior identical askings of the same question. Those
query-echoes carry no information for answering the question yet, being a
near-perfect match to the query text, they out-rank and bury the genuine
answer in the rendered memory section. ``_filter_query_echoes`` drops them.
"""

from __future__ import annotations

import time

import pytest

from probos.cognitive.cognitive_agent import _filter_query_echoes
from probos.types import Episode


def _ep(text: str) -> Episode:
    return Episode(
        user_input=text,
        timestamp=time.time(),
        agent_ids=["agent-001"],
        source="direct",
        outcomes=[{"intent": "direct_message", "success": True}],
    )


class TestFilterQueryEchoes:
    def test_drops_echoes_keeps_answer_the_dog_scenario(self) -> None:
        query = "What do you know about my dogs?"
        echo = "[1:1 with yeoman] Captain: What do you know about my dogs? Captain had a"
        answer = "[1:1 with yeoman] Captain: My dog, Grim, is a giant snouser. Captain h"
        baseline = "[1:1 with yeoman] Captain: I am doing some baseline checks on systems"
        episodes = [_ep(echo), _ep(echo), _ep(echo), _ep(answer), _ep(baseline)]

        result = _filter_query_echoes(episodes, query)

        texts = [e.user_input for e in result]
        assert answer in texts, "the genuine answer must be retained"
        assert baseline in texts
        assert echo not in texts, "all three query-echoes must be dropped"
        assert len(result) == 2

    def test_case_and_whitespace_insensitive(self) -> None:
        query = "What  do you   KNOW about my Dogs?"
        echo = "captain: what do you know about my dogs?"
        answer = "my dog grim is a schnauzer"
        result = _filter_query_echoes([_ep(echo), _ep(answer)], query)
        assert [e.user_input for e in result] == [answer]

    def test_all_echo_returns_originals_never_empty(self) -> None:
        query = "What do you know about my dogs?"
        echo = "Captain: What do you know about my dogs?"
        episodes = [_ep(echo), _ep(echo)]
        result = _filter_query_echoes(episodes, query)
        assert result == episodes, "must not strip to empty when everything is an echo"

    def test_short_query_not_filtered(self) -> None:
        # A <12-char query is too generic to safely substring-match.
        query = "dogs"
        episodes = [_ep("I have dogs"), _ep("something else")]
        result = _filter_query_echoes(episodes, query)
        assert result == episodes

    def test_empty_inputs(self) -> None:
        assert _filter_query_echoes([], "What do you know about my dogs?") == []
        eps = [_ep("anything at all here")]
        assert _filter_query_echoes(eps, "") == eps

    def test_non_echo_unaffected(self) -> None:
        query = "What do you know about my dogs?"
        a = _ep("My dog Grim is a giant schnauzer")
        b = _ep("The warp core is stable")
        result = _filter_query_echoes([a, b], query)
        assert result == [a, b]

    def test_does_not_mutate_input(self) -> None:
        query = "What do you know about my dogs?"
        echo = _ep("Captain: What do you know about my dogs?")
        answer = _ep("My dog Grim is a schnauzer")
        episodes = [echo, answer]
        _filter_query_echoes(episodes, query)
        assert episodes == [echo, answer], "input list must not be mutated"
