# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Utilidades de UV.

Para bakear hace falta un mapa UV razonable.  Este módulo:

* comprueba si el objeto tiene UVs y si las islas caben en 0..1,
* crea un UV con *Smart UV Project* cuando no existe (con los parámetros que
  usa un pipeline de personaje: margen entre islas, sin solapes),
* empaqueta las islas para aprovechar el espacio y dejar margen de bleeding,
* mide la cobertura real del mapa para avisar de resolución insuficiente,
* estima la densidad de texels/cm² — el dato que decide si 2K basta o hacen
  falta 4K para un primer plano.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .i18n import T
from .log import log

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = (
    "has_uv",
    "ensure_uv",
    "pack_islands",
    "uv_coverage",
    "texel_density",
    "check_uv_quality",
    "select_outside_uv",
)


def _is_edit_mode(context: Any) -> bool:
    try:
        return context.object is not None and context.object.mode == "EDIT"
    except Exception:
        return False


def has_uv(obj: Any) -> bool:
    """¿El objeto tiene al menos un mapa UV?"""
    data = getattr(obj, "data", None)
    if data is None:
        return False
    try:
        return len(data.uv_layers) > 0
    except Exception:
        return False


def ensure_uv(obj: Any, *, margin_angle: float = 66.0,
              island_margin: float = 0.02, name: str = "UVMap",
              force: bool = False) -> bool:
    """
    Garantiza que exista un mapa UV usable.

    Si ya hay uno (y ``force`` es falso) no lo toca: nunca destruimos el
    trabajo de un artista.  Si no hay, se proyecta con *Smart UV Project*, que
    para un bake de material procedural da islas válidas sin solapes.
    """
    if bpy is None or obj is None:
        return False
    data = getattr(obj, "data", None)
    if data is None:
        return False

    if not force and has_uv(obj):
        return True

    was_edit = _is_edit_mode(bpy.context)
    try:
        if was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        # seleccionar todo para que la proyección cubra el modelo entero
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(
                angle_limit=math.radians(max(1.0, min(89.0, margin_angle))),
                island_margin=max(0.0, island_margin),
                area_weight=0.0,
                correct_aspect=True,
                scale_to_bounds=True,
            )
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            log.warning("Smart UV Project falló (%s); se crea un UV vacío", exc)
            try:
                if was_edit:
                    bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            try:
                data.uv_layers.new(name=name)
            except Exception as exc2:
                log.error("No se pudo crear el mapa UV: %s", exc2)
                return False
        if was_edit:
            try:
                bpy.ops.object.mode_set(mode="EDIT")
            except Exception:
                pass
        return has_uv(obj)
    except Exception as exc:
        log.error("ensure_uv falló: %s", exc)
        return False


def pack_islands(obj: Any, *, margin: float = 0.01) -> bool:
    """Empaqueta las islas UV dejando margen (reduce el bleeding en el motor)."""
    if bpy is None or obj is None:
        return False
    was_edit = _is_edit_mode(bpy.context)
    try:
        if not was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.select_all(action="SELECT")
        except Exception:
            pass
        try:
            bpy.ops.uv.pack_islands(margin=margin)
        except TypeError:
            # Blender antiguo: el parámetro se llama rotate
            try:
                bpy.ops.uv.pack_islands(rotate=True, margin=margin)
            except Exception as exc:
                log.warning("No se pudo empaquetar islas: %s", exc)
                return False
        if not was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        return True
    except Exception as exc:
        log.error("pack_islands falló: %s", exc)
        return False


def uv_coverage(obj: Any) -> float:
    """
    Fracción del espacio UV ocupada (0..1), estimada con el área de los
    triángulos UV.  Sirve para saber cuánta resolución efectiva recibe el modelo.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return 0.0
    try:
        layer = data.uv_layers.active
        if layer is None:
            return 0.0
        uv_data = layer.data
        total = 0.0
        for poly in data.polygons:
            idx = list(poly.loop_indices)
            if len(idx) < 3:
                continue
            pts = [uv_data[i].uv for i in idx]
            # fan triangulation
            for k in range(1, len(pts) - 1):
                a, b, c = pts[0], pts[k], pts[k + 1]
                total += abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) * 0.5
        return max(0.0, min(1.0, total))
    except Exception as exc:
        log.debug("No se pudo calcular la cobertura UV: %s", exc)
        return 0.0


def texel_density(obj: Any, resolution: int) -> float:
    """
    Texels por centímetro² en la superficie del modelo.

    Regla práctica de pipeline: >20 texels/cm² aguanta primer plano; <5 se ve
    borroso incluso a distancia media.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return 0.0
    try:
        area_3d = 0.0
        for poly in data.polygons:
            area_3d += poly.area
        if area_3d <= 0:
            return 0.0
        scale = 1.0
        try:
            scale = float(bpy.context.scene.unit_settings.scale_length) or 1.0
        except Exception:
            pass
        area_cm2 = area_3d * (scale * 100.0) ** 2
        coverage = uv_coverage(obj)
        texels = float(resolution) * float(resolution) * max(1e-6, coverage)
        return texels / max(1e-6, area_cm2)
    except Exception:
        return 0.0


def check_uv_quality(obj: Any, resolution: int = 4096) -> Dict[str, Any]:
    """Informe de calidad del UV, para mostrar en el panel."""
    out: Dict[str, Any] = {
        "has_uv": has_uv(obj),
        "layers": [],
        "coverage": 0.0,
        "texel_density": 0.0,
        "outside": 0,
        "overlapping": False,
        "verdict": "",
        "warnings": [],
    }
    data = getattr(obj, "data", None)
    if data is None:
        out["verdict"] = T("El objeto debe ser una malla")
        return out
    try:
        out["layers"] = [uv.name for uv in data.uv_layers]
    except Exception:
        pass
    if not out["has_uv"]:
        out["verdict"] = T("El objeto necesita UVs")
        out["warnings"].append("Crea un mapa UV antes de bakear.")
        return out

    out["coverage"] = uv_coverage(obj)
    out["texel_density"] = texel_density(obj, resolution)

    # caras fuera de 0..1
    try:
        layer = data.uv_layers.active
        uv_data = layer.data
        outside = 0
        for poly in data.polygons:
            for li in poly.loop_indices:
                uv = uv_data[li].uv
                if not (-0.001 <= uv.x <= 1.001 and -0.001 <= uv.y <= 1.001):
                    outside += 1
                    break
        out["outside"] = outside
        if outside:
            out["warnings"].append(
                f"{outside} caras con UV fuera del espacio 0-1: sangrarán en el "
                "motor. Empaqueta las islas.")
    except Exception:
        pass

    density = out["texel_density"]
    if density <= 0:
        out["verdict"] = "Cobertura UV nula: revisa la proyección."
    elif density < 3:
        out["verdict"] = (f"{density:.1f} texels/cm² a {resolution} px — muy baja. "
                          "Sube la resolución o reescala las islas.")
    elif density < 10:
        out["verdict"] = (f"{density:.1f} texels/cm² a {resolution} px — correcta "
                          "para plano medio.")
    elif density < 30:
        out["verdict"] = (f"{density:.1f} texels/cm² a {resolution} px — buena, "
                          "aguanta primer plano.")
    else:
        out["verdict"] = (f"{density:.1f} texels/cm² a {resolution} px — excelente "
                          "(o estás desperdiciando resolución).")

    if out["coverage"] < 0.35 and out["coverage"] > 0:
        out["warnings"].append(
            f"Cobertura UV del {out['coverage'] * 100:.0f} %: se desperdicia "
            "textura. Empaqueta las islas para aprovecharla.")
    return out


def select_outside_uv(obj: Any) -> int:
    """Selecciona las caras con UV fuera de 0..1. Devuelve cuántas."""
    if bpy is None or obj is None:
        return 0
    data = getattr(obj, "data", None)
    if data is None or not has_uv(obj):
        return 0
    was_edit = _is_edit_mode(bpy.context)
    count = 0
    try:
        if not was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        layer = data.uv_layers.active
        uv_data = layer.data
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        for poly in data.polygons:
            bad = False
            for li in poly.loop_indices:
                uv = uv_data[li].uv
                if not (-0.001 <= uv.x <= 1.001 and -0.001 <= uv.y <= 1.001):
                    bad = True
                    break
            poly.select = bad
            if bad:
                count += 1
        try:
            bpy.ops.object.mode_set(mode="EDIT")
        except Exception:
            pass
        if not was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as exc:
        log.error("No se pudieron seleccionar las caras fuera de UV: %s", exc)
    return count
