"""File-based diagnostic logging (#5).

kbcode's normal, user-facing output goes through TerminalUI — that's for the
person at the keyboard. This adds a separate, quiet log on disk so that when
something fails in the field the user has an actionable trace to share, not just
what happened to scroll past. It never prints to the console.

Design:
  - one rotating file at ``<project>/.kbcode/kbcode.log`` (capped, a few backups);
  - level from ``KBCODE_LOG_LEVEL`` (default ``INFO``; set ``DEBUG`` for full
    tracing, or ``off``/``none``/``0`` to write nothing);
  - configured on the ``kbcode`` logger, so every module just does the standard
    ``logging.getLogger(__name__)`` (that yields ``kbcode.<module>``, a child that
    propagates up to our handler). ``propagate`` is off on our logger so records
    never bubble to the root logger and double-print.

Never raises: an unwritable location or bad level just means no file log — the
run continues exactly as before.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_OFF = {"off", "none", "no", "0", "false", ""}
_configured = False


def setup_logging(kbcode_dir: Path) -> None:
    """Attach the rotating file handler to the ``kbcode`` logger. Idempotent —
    safe to call more than once (later calls are no-ops), so retargeting the
    project via /open doesn't stack handlers."""
    global _configured
    if _configured:
        return
    _configured = True  # set first: even a failure below shouldn't be retried

    level_name = os.environ.get("KBCODE_LOG_LEVEL", "INFO").strip()
    logger = logging.getLogger("kbcode")
    logger.propagate = False  # our own file sink; don't also hit the root logger
    if level_name.lower() in _OFF:
        logger.addHandler(logging.NullHandler())  # silence "no handlers" warnings
        return

    level = getattr(logging, level_name.upper(), logging.INFO)
    try:
        kbcode_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            kbcode_dir / "kbcode.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        logger.addHandler(logging.NullHandler())
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    logger.setLevel(level)
    logger.addHandler(handler)
