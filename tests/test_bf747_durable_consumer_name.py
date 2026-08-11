"""BF-747 (#1195): a dot in an agent id made NATS time out, silently.

`perception.vision_aggregator` failed to get a JetStream dispatch consumer at
every boot for weeks. The log said `nats: timeout` and named nothing useful.

The code said what the rule was and then broke it:

    # Durable name must be NATS-safe (alphanumeric + dash).
    durable_name = f"agent-dispatch-{agent_id}"

A dot is NATS's subject separator and is not legal in a durable consumer name.
The server does not reject it -- it **times out**, which is why three retries
and a raised RuntimeError produced no usable diagnosis.

Proven live 2026-08-11 against the running server, one variable changed:

    agent-dispatch-probe_no_dot                  -> OK
    agent-dispatch-perception.vision_aggregator  -> TIMEOUT

Found because the Captain said ProbOS should not be running. It wasn't; NATS
was. With the runtime down and the broker up, everything in JetStream was
residue -- and the consumer that fails every boot was conspicuously absent from
the three that survived.

The load-bearing property of the fix is what it does NOT touch: an id needing no
sanitising is returned unchanged, so every durable currently live on the server
keeps its exact name. A fix that renamed working consumers would orphan them.
"""

from __future__ import annotations

import pytest

from probos.mesh.intent import _durable_consumer_name


# ── the failing case ──────────────────────────────────────────────


def test_a_dotted_agent_id_no_longer_produces_a_dotted_durable() -> None:
    name = _durable_consumer_name("perception.vision_aggregator")
    assert "." not in name
    assert name.startswith("agent-dispatch-perception_vision_aggregator-")


@pytest.mark.parametrize("bad", [".", " ", "*", ">", "\t", "\n", "/", "\\"])
def test_every_character_nats_forbids_is_replaced(bad: str) -> None:
    name = _durable_consumer_name(f"agent{bad}id")
    assert bad not in name, f"{bad!r} survived into {name!r}"


# ── and the working cases are untouched ───────────────────────────


@pytest.mark.parametrize("agent_id", [
    "group_chat_coordinator",        # live on the reference server
    "yeoman-proactive-yeoman_y",     # live on the reference server
    "counselor_counselor_0_67c601cb",
    "architect_architect_0_de7afd07",
])
def test_a_safe_id_keeps_the_exact_name_it_already_has(agent_id: str) -> None:
    """The property that makes this safe to ship against a live server: a fix
    that renamed a working consumer would orphan it, and the old one would sit
    in JetStream forever holding its filter subject.
    """
    assert _durable_consumer_name(agent_id) == f"agent-dispatch-{agent_id}"


def test_sanitising_is_the_exception_not_the_rule() -> None:
    """Only ids that cannot work today are changed."""
    safe = ["a", "a_b", "a-b", "a1", "AGENT", "x" * 60]
    for agent_id in safe:
        assert _durable_consumer_name(agent_id) == f"agent-dispatch-{agent_id}"


# ── distinct agents cannot collapse onto one consumer ─────────────


def test_two_ids_differing_only_in_an_unsafe_character_stay_distinct() -> None:
    """Without the hash, `a.b` and `a_b` would both become
    `agent-dispatch-a_b` -- two agents sharing one durable, each stealing the
    other's messages. That is worse than the bug being fixed.
    """
    dotted = _durable_consumer_name("a.b")
    scored = _durable_consumer_name("a_b")

    assert dotted != scored
    assert scored == "agent-dispatch-a_b"        # the safe one is unchanged
    assert dotted.startswith("agent-dispatch-a_b-")


def test_the_same_id_always_produces_the_same_name() -> None:
    """Create and delete call this independently. A non-deterministic name
    would mean teardown targeting a consumer setup never made.
    """
    a = _durable_consumer_name("perception.vision_aggregator")
    b = _durable_consumer_name("perception.vision_aggregator")
    assert a == b


def test_different_dotted_ids_do_not_collide() -> None:
    names = {
        _durable_consumer_name(f"perception.{n}")
        for n in ("vision_aggregator", "audio_aggregator", "vision", "v")
    }
    assert len(names) == 4


# ── both call sites use it ────────────────────────────────────────


def test_create_and_delete_agree_on_the_name() -> None:
    """Two sites built this string by hand. If only one is sanitised, an agent
    with a dot can never be torn down -- the delete targets a name the server
    never held.
    """
    import inspect

    from probos.mesh import intent

    src = inspect.getsource(intent)
    assert src.count('f"agent-dispatch-{agent_id}"') == 1, (
        "the only remaining literal should be the one INSIDE "
        "_durable_consumer_name; a second means a call site was missed"
    )
    assert src.count("_durable_consumer_name(agent_id)") == 2


def test_the_comment_that_lied_is_gone() -> None:
    """It said "Durable name must be NATS-safe (alphanumeric + dash)" directly
    above a line that interpolated the id raw. Third instance this week of a
    comment asserting a property the next line does not provide.
    """
    import inspect

    from probos.mesh import intent

    src = inspect.getsource(intent)
    assert "Durable name must be NATS-safe (alphanumeric + dash)." not in src
