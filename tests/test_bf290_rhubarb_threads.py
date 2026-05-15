"""BF-290: rhubarb-lip-sync subprocess must pass a positive ``--threads`` value.

Some rhubarb releases (observed: 1.13.0) reject ``--threads 0`` with
"Thread count must be 1 or higher" and exit 1, breaking every lip-sync
viseme generation. Older docs implied 0 meant "all cores"; current
binaries require a positive integer.

Guards the contract that the subprocess args carry an integer threads
value computed from ``os.cpu_count()`` (clamped 1..16), not a literal 0.
"""

from __future__ import annotations

import inspect


def test_bf290_rhubarb_threads_is_positive_integer() -> None:
    from probos.avatars import rhubarb_backend

    src = inspect.getsource(rhubarb_backend)

    # The literal ``"0"`` thread argument is the regression we're guarding.
    # The argv block must NOT pass ``"--threads", "0"`` (literal zero string).
    assert '"--threads", "0"' not in src, (
        "BF-290: rhubarb subprocess must not pass --threads 0 "
        "(rhubarb 1.13.0 rejects 0 with 'Thread count must be 1 or higher')."
    )

    # The replacement uses os.cpu_count clamped to >= 1.
    assert "os.cpu_count()" in src, (
        "BF-290: rhubarb subprocess must compute threads from os.cpu_count()."
    )
    assert "max(1," in src, (
        "BF-290: thread count must be clamped to a minimum of 1."
    )


def test_bf290_threads_arg_uses_computed_value() -> None:
    """Argv must read ``str(_threads)`` (or equivalent) — not a hardcoded string."""
    from probos.avatars import rhubarb_backend

    src = inspect.getsource(rhubarb_backend)
    assert '"--threads", str(_threads)' in src, (
        "BF-290: --threads argument must use the computed _threads value."
    )
