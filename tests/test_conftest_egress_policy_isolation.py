"""tests/conftest.py resets HttpFetchAgent's class-level egress policy at each test's setup.

``HttpFetchAgent._egress_policy`` is a class attribute. ``finalize_startup`` installs it
through ``HttpFetchAgent.set_egress_policy`` when ``security_infra.egress_active_enforcement``
is on, and a test rig with a ``MagicMock`` config reads that flag as on. A policy left set
that way made a later test on the same worker fail with an egress refusal
(``test_ad152_regressions.py::TestHttpFetchTimeoutMessage::test_timeout_error_message_value``;
AD-1270 S5-F1, #1324). The autouse ``_ad682_clear_module_caches`` fixture resets the policy
to ``None`` when ``probos.agents.http_fetch`` is already loaded, which it is here: this
module imports it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from probos.agents.http_fetch import HttpFetchAgent


@pytest.fixture(scope="module")
def policy_left_by_an_earlier_test() -> Iterator[object]:
    """Installs a policy the way an earlier finalize_startup rig on the worker would.

    Module scope is set up before the function-scoped autouse fixture under
    test, so the policy is installed when that fixture runs.
    """
    left = object()
    HttpFetchAgent.set_egress_policy(left)
    yield left
    HttpFetchAgent.set_egress_policy(None)  # the class default


def test_each_test_starts_without_an_egress_policy_left_by_an_earlier_one(
    policy_left_by_an_earlier_test: object,
) -> None:
    assert HttpFetchAgent._egress_policy is not policy_left_by_an_earlier_test, (
        "an egress policy an earlier test installed survived into this one"
    )
    assert HttpFetchAgent._egress_policy is None
