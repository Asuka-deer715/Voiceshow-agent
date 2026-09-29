from __future__ import annotations

import logging
import time

from sqlalchemy import event

from .database import SLOW_QUERY_MS, read_engine, write_engine

logger = logging.getLogger("voiceshop.sql")


def _before_execute(conn, cursor, statement, parameters, context, executemany):
    context._voiceshop_started = time.perf_counter()


def _after_execute(conn, cursor, statement, parameters, context, executemany):
    started = getattr(context, "_voiceshop_started", None)
    if started is None:
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= SLOW_QUERY_MS:
        logger.warning("slow_sql elapsed_ms=%.2f statement=%s", elapsed_ms, statement[:500])


for engine in (read_engine, write_engine):
    event.listen(engine, "before_cursor_execute", _before_execute)
    event.listen(engine, "after_cursor_execute", _after_execute)
