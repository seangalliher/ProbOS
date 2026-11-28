"""BF-993: put back every named logger's level that a block changed.

``probos.__main__._setup_logging`` pins eleven named loggers at WARNING for the life
of the process (src/probos/__main__.py:187-197). A test that calls it and restores only
the root logger leaves them pinned, and a later test in the same worker that captures
DEBUG or INFO through the root logger alone loses those loggers' records and their
children's (#1523, #1815).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def restored_logger_levels() -> Iterator[None]:
    """Snapshot every named logger's level; on exit set back each that changed.

    A logger created inside the block goes back to NOTSET, its default.
    """
    manager = logging.Logger.manager
    saved = {
        name: logger.level
        for name, logger in list(manager.loggerDict.items())
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        for name, logger in list(manager.loggerDict.items()):
            if not isinstance(logger, logging.Logger):
                continue
            level = saved.get(name, logging.NOTSET)
            if logger.level != level:  # setLevel clears every logger's cache
                logger.setLevel(level)
