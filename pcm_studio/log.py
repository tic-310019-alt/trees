# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Logging con historial en memoria.

Además de volcar a la consola de Blender, guarda las últimas ``N`` entradas en
un búfer circular que el operador de **Diagnóstico** muestra en un informe
legible.  Así, cuando algo no se genera como debe, el usuario puede copiar el
informe en vez de abrir la consola.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Deque, List, Tuple

__all__ = ("log", "get_history", "clear_history", "set_verbose", "RingHandler")

_HISTORY_SIZE = 400

log = logging.getLogger("pcm_studio")
log.setLevel(logging.DEBUG)
log.propagate = False


class RingHandler(logging.Handler):
    """Guarda ``(nivel, mensaje)`` en un búfer circular."""

    def __init__(self, maxlen: int = _HISTORY_SIZE):
        super().__init__(level=logging.DEBUG)
        self.records: Deque[Tuple[str, str]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            self.records.append((record.levelname, self.format(record)))
        except Exception:
            pass


class _StreamHandler(logging.Handler):
    """Manda a la consola de Blender si existe; si no, a stderr."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        msg = self.format(record)
        try:
            import bpy

            level = "INFO" if record.levelno < logging.WARNING else (
                "WARNING" if record.levelno < logging.ERROR else "ERROR")
            # report a la UI sólo para avisos importantes
            if record.levelno >= logging.WARNING:
                try:
                    win = bpy.context.window_manager.windows[0]
                    win.report({level}, msg)
                except Exception:
                    pass
            print(f"[PCM] {msg}")
        except Exception:
            import sys

            print(f"[PCM] {msg}", file=sys.stderr)


_ring = RingHandler()
_ring.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
_stream = _StreamHandler()
_stream.setFormatter(logging.Formatter("PCM Studio %(levelname)s: %(message)s"))

if not log.handlers:
    log.addHandler(_ring)
    log.addHandler(_stream)


def get_history(levels: Tuple[str, ...] = ("WARNING", "ERROR")) -> List[Tuple[str, str]]:
    return [(lv, m) for lv, m in _ring.records if lv in levels]


def all_history() -> List[Tuple[str, str]]:
    return list(_ring.records)


def clear_history() -> None:
    _ring.records.clear()


def set_verbose(enabled: bool) -> None:
    _stream.setLevel(logging.DEBUG if enabled else logging.INFO)
