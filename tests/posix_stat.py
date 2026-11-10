"""The ``stat`` module of a POSIX build, for tests that run code which reads ``stat`` as a POSIX host runs it.

AD-1341 S6 wrote it into two of its test modules, ``test_ad1341_s6_records_snapshot.py`` and ``test_ad1341_s6_clean_slate.py``; BF-943 A5 moved it here when
a third test module needed it. It imports the standard library only: an S6 test module imports ``probos.__main__``, which sets ``TQDM_DISABLE`` and loads
more than a thousand further modules, so taking the helper from one of them changed the process state of a test that only wanted the helper.
"""

from __future__ import annotations

import stat
import types
from typing import Any


def _posix_stat() -> Any:
    """A POSIX build's ``stat`` module, stricter: no ``IO_REPARSE_TAG_*`` (Windows-only) and no ``FILE_ATTRIBUTE_*``.

    ``Lib/stat.py`` defines the 17 ``FILE_ATTRIBUTE_*`` constants on every platform; they are removed here too, and no module a test swaps this into reads
    either set (the S6 modules and ``builder_paths`` are scanned for it), so no result depends on the difference. Swapped in for one module's own ``stat``
    name only (``records_snapshot.stat``, ``builder_paths.stat``), never deleted from the interpreter's ``stat``: the standard library reads those names
    itself on Windows (``ntpath.isjunction``)."""
    return types.SimpleNamespace(**{
        name: value for name, value in vars(stat).items()
        if not name.startswith(("_", "IO_REPARSE_TAG_", "FILE_ATTRIBUTE_"))
    })
