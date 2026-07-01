"""File-based diagnostic logging (#5)."""

from __future__ import annotations

import logging

from kbcode import logs


def _reset_kbcode_logger():
    """Detach any handlers this process left on the shared 'kbcode' logger and
    return the originals so a test can restore them."""
    logger = logging.getLogger("kbcode")
    old = logger.handlers[:]
    logger.handlers = []
    return logger, old


def test_setup_logging_writes_file_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("KBCODE_LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(logs, "_configured", False)
    logger, old = _reset_kbcode_logger()
    try:
        logs.setup_logging(tmp_path)
        logs.setup_logging(tmp_path)  # second call is a no-op — no stacked handlers
        real = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
        assert len(real) == 1

        logging.getLogger("kbcode.somewhere").debug("hello trace")
        for h in logger.handlers:
            h.flush()
        log_file = tmp_path / "kbcode.log"
        assert log_file.exists()
        assert "hello trace" in log_file.read_text(encoding="utf-8")
    finally:
        for h in logger.handlers:
            h.close()
        logger.handlers = old


def test_setup_logging_off_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KBCODE_LOG_LEVEL", "off")
    monkeypatch.setattr(logs, "_configured", False)
    logger, old = _reset_kbcode_logger()
    try:
        logs.setup_logging(tmp_path)
        logging.getLogger("kbcode.somewhere").warning("should not be written")
        assert not (tmp_path / "kbcode.log").exists()
    finally:
        for h in logger.handlers:
            h.close()
        logger.handlers = old
