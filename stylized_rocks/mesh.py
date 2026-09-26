# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Puente entre la geometría pura y la API de mallas de Blender 5.2."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - Blender sólo está disponible dentro de Blender
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

from .geometry import Face, Vec3, generate_rock_geometry
from .material import build_rock_material
from .properties import copy_settings


NORMAL_MODIFIER_NAME = "SR Weighted Normals"
BEVEL_MODIFIER_NAME = "SR Silhouette Bevel"


def _get(settings: Any, name: str, default: Any) -> Any:
    if settings is None:
        return default
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _set_uvs(mesh: Any, vertices: List[Vec3], height: float) -> None:
    """Crea una UV esférica sencilla para poder hornear la normal tangente."""
    try:
        uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    except (AttributeError, RuntimeError):
        return
    extent = max(float(height), 1.0e-8)
    for loop in mesh.loops:
        x, y, z = vertices[loop.vertex_index]
        u = 0.5 + math.atan2(y, x) / (2.0 * math.pi)
        v = max(0.0, min(1.0, z / extent))
        try:
            uv_layer.data[loop.index].uv = (u, v)
        except (AttributeError, IndexError, TypeError):
            pass


def _replace_mesh(target: Optional[Any], vertices: List[Vec3], faces: List[Face], name: str) -> Any:
    """Construye una malla nueva; en una regeneración sustituye la anterior."""
    if bpy is None:  # pragma: no cover
        raise RuntimeError("Stylized Rock Forge necesita Blender")
    new_mesh = bpy.data.meshes.new(f"{name}_Mesh")
    new_mesh.from_pydata(vertices, [], faces)
    new_mesh.update(calc_edges=True)
    _set_uvs(new_mesh, vertices, max(v[2] for v in vertices) if vertices else 1.0)
    try:
        new_mesh.validate(verbose=False, clean_customdata=False)
    except TypeError:
        try:
            new_mesh.validate()
        except RuntimeError:
            pass

    if target is not None and getattr(target, "type", "") == "MESH":
        old_mesh = target.data
        target.data = new_mesh
        if old_mesh is not None and getattr(old_mesh, "users", 0) == 0:
            try:
                bpy.data.meshes.remove(old_mesh)
            except (RuntimeError, ReferenceError):
                pass
        return new_mesh
    return new_mesh


def _configure_normals(mesh: Any, settings: Any) -> None:
    """Configura las normales geométricas sin usar APIs eliminadas en 5.2."""
    mode = str(_get(settings, "normal_mode", "HYBRID"))
    angle_limit = float(_get(settings, "facet_angle", 0.62))
    mesh.update(calc_edges=True)

    if mode == "FLAT":
        for polygon in mesh.polygons:
            polygon.use_smooth = False
        for edge in mesh.edges:
            try:
                edge.use_edge_sharp = True
            except AttributeError:
                pass
        return

    for polygon in mesh.polygons:
        polygon.use_smooth = True

    if mode != "HYBRID":
        return

    # MeshEdge no expone link_faces de forma estable entre versiones, por eso
    # hacemos el pequeño mapa de adyacencia con los índices de cada polígono.
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for polygon in mesh.polygons:
        indices = list(polygon.vertices)
        for index, a in enumerate(indices):
            b = indices[(index + 1) % len(indices)]
            key = (a, b) if a < b else (b, a)
            edge_faces.setdefault(key, []).append(polygon.index)

    cosine_limit = math.cos(max(0.01, min(math.pi, angle_limit)))
    for edge in mesh.edges:
        a, b = edge.vertices
        key = (a, b) if a < b else (b, a)
        linked = edge_faces.get(key, [])
        sharp = False
        if len(linked) == 2:
            first = mesh.polygons[linked[0]].normal
            second = mesh.polygons[linked[1]].normal
            dot = first.x * second.x + first.y * second.y + first.z * second.z
            sharp = dot < cosine_limit
        try:
            edge.use_edge_sharp = sharp
        except AttributeError:
            pass


def _remove_modifier(obj: Any, name: str) -> None:
    try:
        modifier = obj.modifiers.get(name)
        if modifier is not None:
            obj.modifiers.remove(modifier)
    except (AttributeError, RuntimeError):
        pass


def _configure_modifiers(obj: Any, settings: Any) -> None:
    use_bevel = bool(_get(settings, "use_bevel", False))
    normal_mode = str(_get(settings, "normal_mode", "HYBRID"))

    if use_bevel:
        try:
            bevel = obj.modifiers.get(BEVEL_MODIFIER_NAME)
            if bevel is None:
                bevel = obj.modifiers.new(BEVEL_MODIFIER_NAME, "BEVEL")
            bevel.width = float(_get(settings, "bevel_width", 0.025))
            bevel.segments = int(_get(settings, "bevel_segments", 2))
            bevel.limit_method = "ANGLE"
            bevel.angle_limit = 0.35
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    else:
        _remove_modifier(obj, BEVEL_MODIFIER_NAME)

    if normal_mode in ("HYBRID", "SMOOTH"):
        try:
            weighted = obj.modifiers.get(NORMAL_MODIFIER_NAME)
            if weighted is None:
                weighted = obj.modifiers.new(NORMAL_MODIFIER_NAME, "WEIGHTED_NORMAL")
            weighted.keep_sharp = True
            weighted.weight = 50
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Las normales de la malla ya están calculadas; el modificador es
            # una mejora opcional y no debe impedir crear la roca.
            pass
    else:
        _remove_modifier(obj, NORMAL_MODIFIER_NAME)


def _collection_for(context: Any) -> Any:
    if context is not None:
        collection = getattr(context, "collection", None)
        if collection is not None:
            return collection
        scene = getattr(context, "scene", None)
        if scene is not None and getattr(scene, "collection", None) is not None:
            return scene.collection
    if bpy is not None:
        return getattr(bpy.context, "collection", None) or bpy.context.scene.collection
    return None


def _select_active(obj: Any, context: Any) -> None:
    if context is None:
        return
    try:
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except (AttributeError, RuntimeError):
        pass


def build_rock(
    settings: Any,
    context: Optional[Any] = None,
    target: Optional[Any] = None,
    name: Optional[str] = None,
) -> Any:
    """Crea o regenera una roca y devuelve su objeto Blender."""
    if bpy is None:  # pragma: no cover
        raise RuntimeError("Stylized Rock Forge necesita ejecutarse en Blender 5.2")

    vertices, faces = generate_rock_geometry(settings)
    if target is not None and getattr(target, "type", "") == "MESH":
        obj = target
        object_name = obj.name
        mesh = _replace_mesh(obj, vertices, faces, object_name)
    else:
        object_name = name or f"SR_Rock_{int(_get(settings, 'seed', 1)):04d}"
        mesh = _replace_mesh(None, vertices, faces, object_name)
        collection = _collection_for(context)
        if collection is None:
            raise RuntimeError("No hay una colección activa para enlazar la roca")
        obj = bpy.data.objects.new(object_name, mesh)
        collection.objects.link(obj)

    _configure_normals(mesh, settings)
    _configure_modifiers(obj, settings)

    # Las propiedades de la escena se copian al objeto para que cada roca pueda
    # regenerarse de manera independiente después de cambiar de selección.
    if hasattr(obj, "sr_rock_settings"):
        copy_settings(settings, obj.sr_rock_settings)
    obj["sr_is_rock"] = True
    obj["sr_addon"] = "Stylized Rock Forge"
    obj["sr_seed"] = int(_get(settings, "seed", 1))
    obj["sr_normal_mode"] = str(_get(settings, "normal_mode", "HYBRID"))
    obj["sr_has_geometry_normals"] = True
    obj["sr_geometry_detail"] = int(_get(settings, "detail", 2))

    if bool(_get(settings, "use_material", True)):
        build_rock_material(obj, settings)
    else:
        try:
            mesh.materials.clear()
        except (AttributeError, RuntimeError):
            pass
    _select_active(obj, context)
    return obj


def is_rock(obj: Any) -> bool:
    return bool(obj is not None and getattr(obj, "type", "") == "MESH" and obj.get("sr_is_rock", False))
