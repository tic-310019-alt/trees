# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Stylized Rock Forge — rocas estilizadas procedurales para Blender 5.2.

La extensión combina tres capas que se pueden editar después de crear la roca:

* una malla de icosfera deformada de forma determinista por ``seed``;
* sombreado procedural de color, rugosidad y micro-relieve;
* normales geométricas (facetas, suavizado o weighted normals) y un flujo
  opcional para hornear una normal tangente a una imagen.

No se descargan datos ni se depende de librerías externas.
"""

from __future__ import annotations

from typing import Any, Tuple

try:  # Blender sólo está disponible al ejecutar la extensión dentro de Blender.
    import bpy
except Exception:  # pragma: no cover - permite inspeccionar el paquete fuera de Blender
    bpy = None  # type: ignore[assignment]

bl_info = {
    "name": "Stylized Rock Forge",
    "author": "Stylized Rock Forge",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "Vista 3D › barra lateral › Roca Forge",
    "description": (
        "Crea rocas estilizadas procedurales con deformación por semilla, "
        "material PBR y normales geométricas/procedurales"
    ),
    "doc_url": "https://github.com/tic-310019-alt/trees",
    "tracker_url": "https://github.com/tic-310019-alt/trees/issues",
    "category": "Add Mesh",
}

from . import geometry, material, mesh, operators, properties, ui  # noqa: E402

__all__ = ("bl_info", "register", "unregister")

_REGISTER_ORDER: Tuple[Any, ...] = (properties, operators, ui)


def register() -> None:
    """Registra la extensión en Blender."""
    if bpy is None:  # pragma: no cover
        return
    for module in _REGISTER_ORDER:
        module.register()


def unregister() -> None:
    """Desregistra la extensión en orden inverso."""
    if bpy is None:  # pragma: no cover
        return
    for module in reversed(_REGISTER_ORDER):
        module.unregister()
