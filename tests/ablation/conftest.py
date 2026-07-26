"""AD-1143 DD-1 — directory-local, conditional collection gate.

``tests/conftest.py`` already establishes ``collect_ignore_glob`` as the house
mechanism for excluding a module pytest must not open. This is the same tool,
applied conditionally: with ``PROBOS_ABLATION`` unset (or set to anything other
than the two named modes) pytest never opens the ``test_*.py`` files in this
package.

Why not ``pytestmark = pytest.mark.skipif(...)`` as the three existing opt-in
benches do: ``skipif`` still *imports* the module during collection. The runner
here imports ``CrewOrchestrator``, ``CrewTaskExecutor``,
``WorkItemAgenticExecutor`` and the store layer — so an import-time failure in
the harness would break the default gate for everyone. ``collect_ignore_glob``
means the file is never opened.

The cost, stated honestly: a file that is never collected is a file whose
syntax rot is invisible to CI. ``tests/test_ad1143_ablation_gating.py`` pays
that down with an AST-level ``compile()`` sweep (no import, no execution). That
is the whole mitigation — it does not catch import errors or type errors.

Fail closed: only the two named modes open collection. ``"1"``, ``"true"`` and
``""`` are **not** modes.
"""

import os

VALID_MODES = frozenset({"structural", "live"})

_MODE = os.environ.get("PROBOS_ABLATION", "")
collect_ignore_glob = [] if _MODE in VALID_MODES else ["test_*.py"]
