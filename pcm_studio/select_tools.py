# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Herramientas de selección.

El flujo del addon es "selecciona caras → asigna zona", así que la calidad de la
experiencia depende de lo rápido que el artista consiga **seleccionar justo la
región que quiere**.  Aquí están los ayudantes:

``select_zone_faces``      recupera la selección de una zona ya asignada.
``grow`` / ``shrink``      expande y contrae la selección actual.
``select_by_normal``       caras cuya normal apunta en una dirección (útil para
                           separar la cara del cráneo, o el pecho de la espalda).
``select_by_position``     caras dentro de una caja/esfera en espacio local.
``select_by_curvature``    zonas cóncavas (cuencas, fosas nasales, axilas) o
                           convexas (pómulos, nudillos).
``select_smooth_groups``   islas por ángulo de suavizado: separa ojos, dientes y
                           lengua de la cabeza en modelos importados, que es el
                           caso más común.
``select_uv_islands``      islas UV contiguas.
``propose_zones``          sugerencias de asignación automática por grupos de
                           suavizado + posición (el usuario confirma una a una).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .i18n import T
from .log import log

try:  # pragma: no cover
    import bpy
    from mathutils import Vector
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

    class Vector(tuple):  # type: ignore[no-redef]
        def __new__(cls, seq=(0.0, 0.0, 0.0)):
            return super().__new__(cls, tuple(seq))

__all__ = (
    "select_zone_faces",
    "grow_selection",
    "shrink_selection",
    "select_by_normal",
    "select_by_position",
    "select_by_curvature",
    "select_smooth_groups",
    "select_uv_islands",
    "smooth_groups",
    "propose_zones",
    "selected_face_indices",
    "set_face_selection",
)


# ---------------------------------------------------------------------------
# Utilidades básicas
# ---------------------------------------------------------------------------

def selected_face_indices(obj: Any) -> List[int]:
    """Índices de las caras seleccionadas (funciona en Object y Edit Mode)."""
    data = getattr(obj, "data", None)
    if data is None:
        return []
    try:
        return [p.index for p in data.polygons if p.select]
    except Exception:
        return []


def set_face_selection(obj: Any, indices: Iterable[int], *,
                       mode: str = "SET") -> int:
    """Fija la selección de caras. ``mode`` ∈ SET | ADD | SUBTRACT."""
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    was_edit = obj.mode == "EDIT" if bpy is not None else False
    count = 0
    try:
        if bpy is not None and was_edit:
            bpy.ops.object.mode_set(mode="OBJECT")
        if mode == "SET":
            for p in data.polygons:
                p.select = False
        target = set(int(i) for i in indices)
        for p in data.polygons:
            if p.index in target:
                if mode == "SUBTRACT":
                    p.select = False
                else:
                    p.select = True
                    count += 1
            elif mode == "SET":
                p.select = False
        # los vértices y aristas deben acompañar o Blender ignora la selección
        _sync_selection(data)
        if bpy is not None and was_edit:
            bpy.ops.object.mode_set(mode="EDIT")
    except Exception as exc:
        log.error("No se pudo fijar la selección: %s", exc)
    return count


def _sync_selection(data: Any) -> None:
    """Propaga la selección de caras a vértices y aristas."""
    try:
        for v in data.vertices:
            v.select = False
        for e in data.edges:
            e.select = False
        for p in data.polygons:
            if p.select:
                for vi in p.vertices:
                    data.vertices[vi].select = True
        # aristas: sólo si ambos vértices están seleccionados
        for e in data.edges:
            if data.vertices[e.vertices[0]].select and data.vertices[e.vertices[1]].select:
                e.select = True
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Selección por zona asignada
# ---------------------------------------------------------------------------

def select_zone_faces(obj: Any, zone_id: int, *, mode: str = "SET") -> int:
    """Selecciona las caras que tienen asignada la zona ``zone_id``."""
    from . import assembler

    data = getattr(obj, "data", None)
    if data is None:
        return 0
    values = assembler.read_zone_attribute(data)
    if not values:
        return 0
    indices = [i for i, v in enumerate(values) if int(round(float(v))) == int(zone_id)]
    return set_face_selection(obj, indices, mode=mode)


# ---------------------------------------------------------------------------
# Crecer / reducir
# ---------------------------------------------------------------------------

def grow_selection(obj: Any, iterations: int = 1) -> int:
    """Expande la selección a las caras vecinas."""
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    adjacency = _face_adjacency(data)
    current = set(selected_face_indices(obj))
    for _ in range(max(1, iterations)):
        nxt = set(current)
        for fi in current:
            nxt.update(adjacency.get(fi, ()))
        if not nxt - current:
            break
        current = nxt
    return set_face_selection(obj, current, mode="SET")


def shrink_selection(obj: Any, iterations: int = 1) -> int:
    """Contrae la selección quitando el borde."""
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    adjacency = _face_adjacency(data)
    current = set(selected_face_indices(obj))
    for _ in range(max(1, iterations)):
        keep = set()
        for fi in current:
            if all(nb in current for nb in adjacency.get(fi, ())):
                keep.add(fi)
        if not keep or keep == current:
            break
        current = keep
    return set_face_selection(obj, current, mode="SET")


def _face_adjacency(data: Any) -> Dict[int, Tuple[int, ...]]:
    """Mapa cara → caras vecinas (comparten arista)."""
    out: Dict[int, List[int]] = {}
    try:
        edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
        for p in data.polygons:
            for ei in p.edge_keys:
                key = (min(ei), max(ei))
                edge_to_faces.setdefault(key, []).append(p.index)
        for faces in edge_to_faces.values():
            if len(faces) == 2:
                a, b = faces
                out.setdefault(a, []).append(b)
                out.setdefault(b, []).append(a)
            else:
                for f in faces:
                    for g in faces:
                        if f != g:
                            out.setdefault(f, []).append(g)
    except Exception as exc:
        log.debug("No se pudo calcular la adyacencia: %s", exc)
    return {k: tuple(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Selección por normal
# ---------------------------------------------------------------------------

def select_by_normal(obj: Any, direction: Sequence[float], angle_deg: float, *,
                     mode: str = "SET", only_selected: bool = False) -> int:
    """
    Selecciona las caras cuya normal forma menos de ``angle_deg`` con
    ``direction`` (en espacio local del objeto).

    Casos típicos: ``+Y`` = cara frontal del rostro, ``-Y`` = nuca, ``+Z`` =
    coronilla/hombros, ``-Z`` = plantas y barbilla.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    try:
        d = Vector(direction).normalized()
    except Exception:
        d = Vector((0.0, 1.0, 0.0))
    limit = math.cos(math.radians(max(0.5, min(180.0, angle_deg))))
    indices = []
    restrict = set(selected_face_indices(obj)) if only_selected else None
    try:
        for p in data.polygons:
            if restrict is not None and p.index not in restrict:
                continue
            try:
                n = p.normal
            except Exception:
                continue
            if n.dot(d) >= limit:
                indices.append(p.index)
    except Exception as exc:
        log.error("select_by_normal falló: %s", exc)
        return 0
    return set_face_selection(obj, indices, mode=mode)


# ---------------------------------------------------------------------------
# Selección por posición
# ---------------------------------------------------------------------------

def select_by_position(obj: Any, *, center: Sequence[float] = (0.0, 0.0, 0.0),
                       radius: float = 0.1, box: Optional[Sequence[float]] = None,
                       mode: str = "SET", only_selected: bool = False) -> int:
    """
    Selecciona caras dentro de una esfera (``radius``) o de una caja (``box`` =
    dimensiones X/Y/Z) centradas en ``center``, en espacio local.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    restrict = set(selected_face_indices(obj)) if only_selected else None
    indices: List[int] = []
    try:
        c = Vector(center)
        half = Vector(box) * 0.5 if box else None
        for p in data.polygons:
            if restrict is not None and p.index not in restrict:
                continue
            try:
                pc = p.center
            except Exception:
                continue
            if half is not None:
                d = pc - c
                if abs(d.x) <= half.x and abs(d.y) <= half.y and abs(d.z) <= half.z:
                    indices.append(p.index)
            else:
                if (pc - c).length <= radius:
                    indices.append(p.index)
    except Exception as exc:
        log.error("select_by_position falló: %s", exc)
        return 0
    return set_face_selection(obj, indices, mode=mode)


# ---------------------------------------------------------------------------
# Selección por curvatura
# ---------------------------------------------------------------------------

def _face_curvatures(data: Any) -> Dict[int, float]:
    """
    Curvatura media aproximada por cara: diferencia entre la normal de la cara y
    las normales de sus vecinas.  Positiva = convexa, negativa = cóncava.
    """
    adjacency = _face_adjacency(data)
    out: Dict[int, float] = {}
    try:
        normals = {p.index: p.normal for p in data.polygons}
        for fi, n in normals.items():
            neigh = adjacency.get(fi, ())
            if not neigh:
                out[fi] = 0.0
                continue
            acc = 0.0
            for nb in neigh:
                on = normals.get(nb)
                if on is None:
                    continue
                # ángulo firmado con respecto al vector que une los centros
                acc += (1.0 - n.dot(on))
            out[fi] = acc / len(neigh)
    except Exception:
        pass
    # el signo real (cóncavo/convexo) sale de si la vecina "se abre" o "se cierra"
    try:
        for fi, p in ((p.index, p) for p in data.polygons):
            neigh = adjacency.get(fi, ())
            if not neigh:
                continue
            signed = 0.0
            for nb in neigh:
                np_ = data.polygons[nb] if nb < len(data.polygons) else None
                if np_ is None:
                    continue
                delta = np_.center - p.center
                if delta.length < 1e-9:
                    continue
                # si la normal vecina apunta hacia nuestra cara => cóncavo
                signed += -delta.normalized().dot(np_.normal)
            out[fi] = signed / len(neigh)
    except Exception:
        pass
    return out


def select_by_curvature(obj: Any, *, concave: bool = True, threshold: float = 0.35,
                        mode: str = "SET", only_selected: bool = False) -> int:
    """
    Selecciona zonas cóncavas (cuencas de los ojos, fosas nasales, axilas,
    entrepierna) o convexas (pómulos, nudillos, frente).
    """
    data = getattr(obj, "data", None)
    if data is None:
        return 0
    curv = _face_curvatures(data)
    restrict = set(selected_face_indices(obj)) if only_selected else None
    indices = []
    for fi, c in curv.items():
        if restrict is not None and fi not in restrict:
            continue
        if concave and c >= threshold:
            indices.append(fi)
        elif not concave and c <= -threshold:
            indices.append(fi)
    return set_face_selection(obj, indices, mode=mode)


# ---------------------------------------------------------------------------
# Grupos de suavizado / islas
# ---------------------------------------------------------------------------

def smooth_groups(obj: Any, angle_deg: float = 30.0) -> List[List[int]]:
    """
    Agrupa las caras en islas conectadas cuyo ángulo entre vecinas no supere
    ``angle_deg``.

    Es la forma más fiable de separar los elementos de una cabeza importada
    (globo ocular, dientes, lengua, pestañas) sin depender de cómo estén
    nombrados los materiales.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return []
    adjacency = _face_adjacency(data)
    limit = math.cos(math.radians(max(0.0, min(180.0, angle_deg))))
    visited: set = set()
    groups: List[List[int]] = []
    try:
        normals = {p.index: p.normal for p in data.polygons}
    except Exception:
        return []
    for p in data.polygons:
        fi = p.index
        if fi in visited:
            continue
        stack = [fi]
        comp: List[int] = []
        visited.add(fi)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            nc = normals.get(cur)
            for nb in adjacency.get(cur, ()):
                if nb in visited:
                    continue
                nn = normals.get(nb)
                if nc is None or nn is None or nc.dot(nn) < limit:
                    continue
                visited.add(nb)
                stack.append(nb)
        if comp:
            groups.append(sorted(comp))
    groups.sort(key=len, reverse=True)
    return groups


def select_smooth_groups(obj: Any, angle_deg: float = 30.0) -> List[List[int]]:
    """Calcula los grupos de suavizado y devuelve sus listas de caras."""
    return smooth_groups(obj, angle_deg)


def select_uv_islands(obj: Any, *, mode: str = "SET") -> List[List[int]]:
    """
    Islas UV (caras conectadas en el espacio UV).  Devuelve la lista de islas;
    si ``mode`` es SET además selecciona la primera.
    """
    data = getattr(obj, "data", None)
    if data is None or bpy is None:
        return []
    try:
        layer = data.uv_layers.active
        if layer is None:
            return []
        uv_data = layer.data
    except Exception:
        return []
    # adyacencia en UV: dos caras vecinas pertenecen a la misma isla si
    # comparten vértices con UV idéntico
    adjacency = _face_adjacency(data)
    uv_of: Dict[int, List[Tuple[float, float]]] = {}
    try:
        for p in data.polygons:
            uv_of[p.index] = [(uv_data[li].uv.x, uv_data[li].uv.y)
                              for li in p.loop_indices]
    except Exception:
        return []
    visited: set = set()
    islands: List[List[int]] = []
    for p in data.polygons:
        fi = p.index
        if fi in visited:
            continue
        stack = [fi]
        comp: List[int] = []
        visited.add(fi)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adjacency.get(cur, ()):
                if nb in visited:
                    continue
                if _uv_connected(uv_of.get(cur, []), uv_of.get(nb, [])):
                    visited.add(nb)
                    stack.append(nb)
        islands.append(sorted(comp))
    islands.sort(key=len, reverse=True)
    if islands and mode == "SET":
        set_face_selection(obj, islands[0], mode="SET")
    return islands


def _uv_connected(a: Sequence[Tuple[float, float]],
                  b: Sequence[Tuple[float, float]], eps: float = 1e-5) -> bool:
    """¿Comparten al menos dos vértices con las mismas coordenadas UV?"""
    shared = 0
    for pa in a:
        for pb in b:
            if abs(pa[0] - pb[0]) < eps and abs(pa[1] - pb[1]) < eps:
                shared += 1
                break
        if shared >= 2:
            return True
    return False


# ---------------------------------------------------------------------------
# Sugerencias automáticas
# ---------------------------------------------------------------------------

def _bbox(obj: Any) -> Tuple[Vector, Vector]:
    data = getattr(obj, "data", None)
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    if data is None:
        return lo, hi
    try:
        for v in data.vertices:
            co = v.co
            lo.x = min(lo.x, co.x); lo.y = min(lo.y, co.y); lo.z = min(lo.z, co.z)
            hi.x = max(hi.x, co.x); hi.y = max(hi.y, co.y); hi.z = max(hi.z, co.z)
    except Exception:
        pass
    return lo, hi


def propose_zones(obj: Any, *, angle_deg: float = 30.0,
                  min_faces: int = 8) -> List[Dict[str, Any]]:
    """
    Propone una asignación de zonas a partir de los grupos de suavizado.

    No asigna nada: devuelve una lista de sugerencias
    ``{"zone_id": int, "faces": [...], "reason": str, "confidence": float}``
    para que el usuario las confirme una a una en el panel.  Así la detección
    automática nunca rompe un modelo: siempre es reversible y visible.

    Heurísticas (en orden de fiabilidad):

    1. Grupo **desconectado y pequeño** → ojo / diente / lengua / uña.
    2. Grupo **esférico y compacto** con tamaño ~1/10 de la cabeza → globo ocular.
    3. Grupo grande en la **parte alta** y frontal → piel de cara.
    4. Resto del grupo grande → piel de cuerpo.
    """
    from . import zones as zones_mod

    data = getattr(obj, "data", None)
    if data is None:
        return []
    groups = smooth_groups(obj, angle_deg)
    if not groups:
        return []
    lo, hi = _bbox(obj)
    size = hi - lo
    total = max(1, len(data.polygons))
    proposals: List[Dict[str, Any]] = []
    body_faces: List[int] = []

    for gi, faces in enumerate(groups):
        if len(faces) < min_faces:
            body_faces.extend(faces)
            continue
        center, extent, sphericity = _group_stats(data, faces)
        frac = len(faces) / total
        # posición relativa en el objeto
        rz = _rel(center.z, lo.z, size.z)
        ry = _rel(center.y, lo.y, size.y)

        zone_id = zones_mod.DEFAULT_ZONE_ID
        reason = ""
        confidence = 0.35

        if frac < 0.035 and sphericity > 0.72:
            zone_id = _zone_id("sclera")
            reason = "Grupo pequeño, cerrado y esférico → globo ocular"
            confidence = 0.72
        elif frac < 0.03 and sphericity > 0.6:
            zone_id = _zone_id("teeth")
            reason = "Grupo pequeño y compacto → probable dentadura"
            confidence = 0.45
        elif frac < 0.02:
            zone_id = _zone_id("lashes")
            reason = "Grupo muy pequeño → pestañas/cejas o accesorio"
            confidence = 0.35
        elif frac > 0.35:
            # grupo dominante: separar cabeza del cuerpo por altura
            head = [f for f in faces
                    if _rel(_face_center(data, f).z, lo.z, size.z) > 0.72]
            head_set = set(head)
            rest = [f for f in faces if f not in head_set]
            if head:
                proposals.append({
                    "zone_id": _zone_id("skin_face"),
                    "faces": head,
                    "reason": "Parte superior del grupo principal → cabeza",
                    "confidence": 0.55,
                })
            if rest:
                proposals.append({
                    "zone_id": _zone_id("skin_body"),
                    "faces": rest,
                    "reason": "Resto del grupo principal → cuerpo",
                    "confidence": 0.6,
                })
            continue
        else:
            zone_id = zones_mod.DEFAULT_ZONE_ID
            reason = "Grupo grande sin forma reconocible → piel"
            confidence = 0.3

        proposals.append({
            "zone_id": zone_id, "faces": faces,
            "reason": reason, "confidence": confidence,
        })

    if body_faces:
        proposals.append({
            "zone_id": zones_mod.DEFAULT_ZONE_ID,
            "faces": body_faces,
            "reason": "Caras sueltas / grupos diminutos → piel",
            "confidence": 0.25,
        })
    proposals.sort(key=lambda p: (-p["confidence"], -len(p["faces"])))
    return proposals


def _zone_id(key: str) -> int:
    from . import zones as zones_mod

    z = zones_mod.get_zone_by_key(key)
    return z.id if z is not None else zones_mod.DEFAULT_ZONE_ID


def _rel(value: float, lo: float, size: float) -> float:
    if abs(size) < 1e-9:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / size))


def _face_center(data: Any, index: int) -> Vector:
    try:
        return data.polygons[index].center
    except Exception:
        return Vector((0.0, 0.0, 0.0))


def _group_stats(data: Any, faces: Sequence[int]
                 ) -> Tuple[Vector, Vector, float]:
    """Centro, extensión y esfericidad (0..1) de un grupo de caras."""
    try:
        centers = [data.polygons[f].center for f in faces if f < len(data.polygons)]
    except Exception:
        centers = []
    if not centers:
        return Vector((0, 0, 0)), Vector((0, 0, 0)), 0.0
    lo = Vector((min(c.x for c in centers), min(c.y for c in centers),
                 min(c.z for c in centers)))
    hi = Vector((max(c.x for c in centers), max(c.y for c in centers),
                 max(c.z for c in centers)))
    center = (lo + hi) * 0.5
    extent = hi - lo
    longest = max(extent.x, extent.y, extent.z, 1e-9)
    shortest = min(extent.x, extent.y, extent.z)
    sphericity = shortest / longest if longest > 1e-9 else 0.0
    return center, extent, sphericity
