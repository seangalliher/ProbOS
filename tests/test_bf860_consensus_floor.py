"""BF-860 (#1242 finding 3): the descriptor sets the consensus floor.

`TaskNode.use_consensus` came straight from the model's JSON with a `False`
default, and nothing reconciled it against the agent's own
`IntentDescriptor.requires_consensus`. A model that simply omitted the field
silently downgraded a destructive intent to no consensus.

Measured before the fix, with descriptors registered and the field omitted::

    run_command    use_consensus=False
    write_file     use_consensus=False

`requires_consensus` is this repo's stated marker for a destructive operation,
and reviewers are told to flag any new destructive intent that lacks it. It only
means anything if something enforces it.

Scope, stated rather than implied: this closes finding 3 of #1242 only. It makes
the FLAG honest -- it does not make the generic consensus path propose-then-commit.
That path still executes and then votes, which is findings 1 and 2 and remains open.
"""

from __future__ import annotations

import pytest

from probos.cognitive.decomposer import IntentDecomposer
from probos.types import IntentDescriptor


def _decomposer(*descriptors: IntentDescriptor) -> IntentDecomposer:
    d = IntentDecomposer(llm_client=None, working_memory=None)
    d.refresh_descriptors(list(descriptors))
    return d


def _destructive(name: str) -> IntentDescriptor:
    return IntentDescriptor(
        name=name, params={}, description=name, requires_consensus=True
    )


def _benign(name: str) -> IntentDescriptor:
    return IntentDescriptor(
        name=name, params={}, description=name, requires_consensus=False
    )


class TestTheDescriptorSetsTheFloor:
    def test_an_omitted_flag_does_not_downgrade_a_destructive_intent(self):
        d = _decomposer(_destructive("run_command"), _destructive("write_file"))
        # PREMISE: the descriptors really are registered, or nothing is proven.
        assert d.intent_descriptor_count == 2

        dag = d._build_dag(
            {
                "intents": [
                    {"id": "t1", "intent": "run_command", "params": {}},
                    {"id": "t2", "intent": "write_file", "params": {}},
                ]
            },
            source_text="probe",
        )

        assert len(dag.nodes) == 2, "the DAG is empty; this asserts nothing"
        assert [n.use_consensus for n in dag.nodes] == [True, True]

    def test_an_explicit_false_does_not_downgrade_it_either(self):
        """The model asserting `false` is the same downgrade, stated openly."""
        d = _decomposer(_destructive("run_command"))

        dag = d._build_dag(
            {
                "intents": [
                    {
                        "id": "t1",
                        "intent": "run_command",
                        "params": {},
                        "use_consensus": False,
                    }
                ]
            },
            source_text="probe",
        )

        assert dag.nodes[0].use_consensus is True

    def test_the_model_can_still_raise_consensus_on_a_benign_intent(self):
        """A FLOOR, not an override. Clamping to the descriptor would remove a
        judgement the model is well placed to make, and this test is what stops
        a future 'simplification' from turning the floor into an equals."""
        d = _decomposer(_benign("http_fetch"))

        dag = d._build_dag(
            {
                "intents": [
                    {
                        "id": "t1",
                        "intent": "http_fetch",
                        "params": {},
                        "use_consensus": True,
                    }
                ]
            },
            source_text="probe",
        )

        assert dag.nodes[0].use_consensus is True

    def test_a_benign_intent_is_not_given_a_gate_it_never_asked_for(self):
        d = _decomposer(_benign("http_fetch"))

        dag = d._build_dag(
            {"intents": [{"id": "t1", "intent": "http_fetch", "params": {}}]},
            source_text="probe",
        )

        assert dag.nodes[0].use_consensus is False

    def test_an_unregistered_intent_contributes_no_floor(self):
        """The floor comes from the registry, so an intent nobody registered
        cannot acquire a gate by accident."""
        d = _decomposer(_destructive("run_command"))

        dag = d._build_dag(
            {"intents": [{"id": "t1", "intent": "totally_unknown", "params": {}}]},
            source_text="probe",
        )

        assert dag.nodes[0].use_consensus is False

    def test_with_no_descriptors_registered_the_model_still_decides(self):
        """Legacy/degraded boot: an empty registry must not change behaviour."""
        d = _decomposer()
        assert d.intent_descriptor_count == 0

        dag = d._build_dag(
            {
                "intents": [
                    {"id": "t1", "intent": "run_command", "params": {}},
                    {
                        "id": "t2",
                        "intent": "write_file",
                        "params": {},
                        "use_consensus": True,
                    },
                ]
            },
            source_text="probe",
        )

        assert [n.use_consensus for n in dag.nodes] == [False, True]

    def test_the_raise_is_logged_so_a_lying_model_is_visible(self, caplog):
        """Silent correction would hide a model that keeps omitting the flag."""
        import logging

        d = _decomposer(_destructive("run_command"))

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.decomposer"):
            d._build_dag(
                {"intents": [{"id": "t1", "intent": "run_command", "params": {}}]},
                source_text="probe",
            )

        assert any("BF-860" in r.message for r in caplog.records), (
            "the downgrade was corrected silently"
        )

    def test_a_correctly_flagged_destructive_intent_is_not_logged(self, caplog):
        """The control: the warning must mean something. If it fired on the
        happy path too, its presence above would prove nothing."""
        import logging

        d = _decomposer(_destructive("run_command"))

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.decomposer"):
            dag = d._build_dag(
                {
                    "intents": [
                        {
                            "id": "t1",
                            "intent": "run_command",
                            "params": {},
                            "use_consensus": True,
                        }
                    ]
                },
                source_text="probe",
            )

        assert dag.nodes[0].use_consensus is True
        assert not any("BF-860" in r.message for r in caplog.records)


class TestACacheHitCannotReplayADowngrade:
    """Review caught this as a High and reproduced it: a workflow cache HIT
    returns a prebuilt DAG and never reaches ``_build_dag``, so a workflow
    cached BEFORE the floor existed replayed straight past it --
    ``returned_use_consensus False, llm_called False``.

    This is the repo's half-chain defect class: the floor was correct, the
    consumer was correct, and nothing enforced it across the cache seam.
    """

    @pytest.mark.asyncio
    async def test_an_exact_cache_hit_is_raised_to_the_floor(self):
        from probos.types import TaskDAG, TaskNode

        d = _decomposer(_destructive("run_command"))

        cached = TaskDAG(
            source_text="clean up the logs",
            nodes=[
                TaskNode(
                    id="t1",
                    intent="run_command",
                    params={"command": "rm -rf /tmp/logs"},
                    depends_on=[],
                    use_consensus=False,  # cached before the floor existed
                )
            ],
        )

        class _Cache:
            def __init__(self) -> None:
                self.lookups = 0

            def lookup(self, text):
                self.lookups += 1
                return cached

            def lookup_fuzzy(self, text, intents):
                return None

        cache = _Cache()
        d.workflow_cache = cache

        dag = await d.decompose("clean up the logs")

        # PREMISE: the cache really was hit, or this tests the LLM path.
        assert cache.lookups == 1, "the cache was never consulted"
        assert dag is not None and len(dag.nodes) == 1
        assert dag.nodes[0].use_consensus is True, (
            "a cached destructive workflow replayed without consensus"
        )

    @pytest.mark.asyncio
    async def test_a_fuzzy_cache_hit_is_raised_to_the_floor(self):
        from probos.types import TaskDAG, TaskNode

        d = _decomposer(_destructive("write_file"))
        d._pre_warm_intents = ["write_file"]

        cached = TaskDAG(
            source_text="save the report",
            nodes=[
                TaskNode(
                    id="t1",
                    intent="write_file",
                    params={"path": "/x", "content": "y"},
                    depends_on=[],
                    use_consensus=False,
                )
            ],
        )

        class _Cache:
            def __init__(self) -> None:
                self.fuzzy_lookups = 0

            def lookup(self, text):
                return None

            def lookup_fuzzy(self, text, intents):
                self.fuzzy_lookups += 1
                return cached

        cache = _Cache()
        d.workflow_cache = cache

        dag = await d.decompose("save the report")

        assert cache.fuzzy_lookups == 1, "the fuzzy path was never taken"
        assert dag.nodes[0].use_consensus is True

    @pytest.mark.asyncio
    async def test_a_cache_hit_does_not_invent_a_gate_for_a_benign_intent(self):
        """The control: re-applying the floor on replay must not turn every
        cached node into a consensus node."""
        from probos.types import TaskDAG, TaskNode

        d = _decomposer(_benign("http_fetch"))

        cached = TaskDAG(
            source_text="fetch it",
            nodes=[
                TaskNode(
                    id="t1",
                    intent="http_fetch",
                    params={},
                    depends_on=[],
                    use_consensus=False,
                )
            ],
        )

        class _Cache:
            def lookup(self, text):
                return cached

            def lookup_fuzzy(self, text, intents):
                return None

        d.workflow_cache = _Cache()

        dag = await d.decompose("fetch it")

        assert dag.nodes[0].use_consensus is False

    @pytest.mark.asyncio
    async def test_a_cache_hit_preserves_consensus_the_model_had_raised(self):
        """Floor, not clamp -- on the replay path too.

        Found by a surviving mutant: replacing ``node.use_consensus`` with
        ``False`` when re-applying the floor passed every other test here. A
        cached node whose consensus the model had deliberately RAISED on a
        benign intent would have been silently downgraded on every replay.
        """
        from probos.types import TaskDAG, TaskNode

        d = _decomposer(_benign("http_fetch"))

        cached = TaskDAG(
            source_text="fetch the payroll export",
            nodes=[
                TaskNode(
                    id="t1",
                    intent="http_fetch",
                    params={},
                    depends_on=[],
                    use_consensus=True,  # the model judged this one worth gating
                )
            ],
        )

        class _Cache:
            def lookup(self, text):
                return cached

            def lookup_fuzzy(self, text, intents):
                return None

        d.workflow_cache = _Cache()

        dag = await d.decompose("fetch the payroll export")

        assert dag.nodes[0].use_consensus is True, (
            "replay clamped to the descriptor and dropped a raise"
        )
