# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Procedural Character Materials
===========================================

Genera materiales PBR **profesionales y listos para juego** sobre personajes
humanos y animales, con un flujo tipo *texture paint*: seleccionas caras →
asignas una zona (piel, iris, dientes, pelaje, escamas…) → el addon construye
un único material procedural con color base, rugosidad, normal y micro-detalle
para cada zona, y lo bakea a mapas exportables a Unity / Unreal / Godot / glTF.

Arquitectura (cada módulo es independiente y se importa sin efectos secundarios
fuera de Blender)::

    i18n          textos ES/EN
    log           logger con historial en memoria
    compat        capa de compatibilidad de nodos/sockets 4.x ↔ 5.2
    shaderkit     constructores de nodos (Builder / GroupBuilder)
    texlib        biblioteca de texturas procedurales (fbm, voronoi, fibras…)
    zones         catálogo de zonas + parámetros
    styles        presets de estilo (Realista, Sims 4, Estilizado, ClayScan)
    recipes/      una receta procedural por familia de zonas
    assembler     construye el grupo maestro + el material del objeto
    properties    PropertyGroups (escena, objeto, editor de zonas)
    preferences   preferencias del addon
    diagnostics   validadores + informe de texto
    uv            calidad de UVs, cobertura, densidad de texel
    select_tools  selección por normal/curvatura/posición + sugerencias
    bake          motor de bake (Cycles, EMIT, normales con desplazamiento)
    export        nomenclatura por motor, ORM, manifiesto, guía de importación
    operators     todos los operadores (incl. el bake modal)
    ui            paneles, listas y menús

Este ``__init__`` sólo orquesta el registro; no contiene lógica de nodos.

Licencia: GPL-3.0-or-later (ver ``blender_manifest.toml``).
"""

from __future__ import annotations

from typing import Any, Tuple

# ``bl_info`` se mantiene para compatibilidad con el gestor clásico de addons y
# para que ``export._addon_version`` pueda leer la versión sin el manifiesto.
bl_info = {
    "name": "PCM Studio — Procedural Character Materials",
    "author": "PCM Studio",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Properties › Material · View3D › barra N › PCM",
    "description": ("Materiales PBR procedurales game-ready para personajes "
                    "humanos y animales, por selección de caras, con bake y "
                    "exportación a Unity/Unreal/Godot/glTF"),
    "doc_url": "https://github.com/tic-310019-alt/trees",
    "tracker_url": "https://github.com/tic-310019-alt/trees/issues",
    "category": "Material",
}

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

# El orden de importación es deliberado: de las capas sin dependencias a las que
# registran clases.  Importar aquí (y no dentro de ``register``) hace que un
# error de sintaxis o de API salga al activar el addon, no al usarlo.
from . import (compat, i18n, log, preferences, properties, operators, ui)
from .log import log as _log

__all__ = ("bl_info", "register", "unregister")


# Orden de registro: preferencias (fijan el idioma y exponen el operador de
# diagnóstico) → propiedades (crean Object.pcm / Scene.pcm que usan todos) →
# operadores (los paneles los dibujan por ``bl_idname``) → interfaz.
_REGISTER_ORDER: Tuple[Any, ...] = (
    preferences,
    properties,
    operators,
    ui,
)


def _blender_version() -> str:
    try:
        return getattr(bpy.app, "version_string", "?")
    except Exception:
        return "?"


def register() -> None:
    """Activa el addon en Blender."""
    if bpy is None:  # pragma: no cover - fuera de Blender
        return

    # Comprobación de versión mínima antes de tocar nada.
    if not compat.is_blender_at_least(4, 2, 0):
        _log.error(
            "PCM Studio necesita Blender 4.2 o superior (detectado %s). "
            "El addon no se registrará.", _blender_version())
        # Se registra igualmente: las capas de compatibilidad degradan con
        # avisos en vez de romperse, y el usuario ve el diagnóstico.

    failed = []
    for mod in _REGISTER_ORDER:
        name = getattr(mod, "__name__", mod)
        try:
            mod.register()
        except Exception as exc:
            failed.append((name, exc))
            _log.error("No se pudo registrar %s: %s", name, exc)

    # Resumen de capacidades, útil en el primer arranque y en el informe.
    try:
        report = compat.feature_report()
        missing = report.get("required_missing") or []
        if missing:
            _log.warning(
                "PCM Studio: faltan nodos esenciales en este Blender (%s). "
                "Abre «Informe y diagnóstico» para ver el detalle.",
                ", ".join(map(str, missing)))
        else:
            _log.info("PCM Studio %s registrado en Blender %s · idioma %s",
                      ".".join(str(x) for x in bl_info["version"]),
                      _blender_version(), i18n.get_language())
    except Exception as exc:  # pragma: no cover - defensivo
        _log.debug("feature_report falló: %s", exc)

    if failed:
        # Dejar constancia clara: un registro parcial suele ser un addon roto.
        names = ", ".join(n for n, _ in failed)
        _log.error("PCM Studio: registro incompleto en %s", names)


def unregister() -> None:
    """Desactiva el addon, en orden inverso al registro."""
    if bpy is None:  # pragma: no cover
        return
    for mod in reversed(_REGISTER_ORDER):
        name = getattr(mod, "__name__", mod)
        try:
            mod.unregister()
        except Exception as exc:
            _log.debug("No se pudo desregistrar %s: %s", name, exc)
