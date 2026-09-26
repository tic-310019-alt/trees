# SPDX-License-Identifier: GPL-3.0-or-later
"""Generación pura de la forma de una roca estilizada.

Este módulo no importa ``bpy``. La geometría se construye como una icosfera
subdividida y se deforma con ruido determinista en la esfera. Así el mismo
``seed`` siempre produce exactamente la misma topología y permite regenerar una
variación sin acumular deformaciones.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .noise import fbm, ridged_fbm

Vec3 = Tuple[float, float, float]
Face = Tuple[int, int, int]


def _value(settings: Any, name: str, default: Any) -> Any:
    """Lee tanto un PropertyGroup como un diccionario o un objeto simple."""
    if settings is None:
        return default
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _normalize(v: Vec3) -> Vec3:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 1.0e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _orient_faces(vertices: Sequence[Vec3], faces: Iterable[Face]) -> List[Face]:
    """Asegura que todas las caras miran hacia fuera de la esfera."""
    oriented: List[Face] = []
    for a, b, c in faces:
        ab = _sub(vertices[b], vertices[a])
        ac = _sub(vertices[c], vertices[a])
        normal = _cross(ab, ac)
        center = (
            (vertices[a][0] + vertices[b][0] + vertices[c][0]) / 3.0,
            (vertices[a][1] + vertices[b][1] + vertices[c][1]) / 3.0,
            (vertices[a][2] + vertices[b][2] + vertices[c][2]) / 3.0,
        )
        if _dot(normal, center) < 0.0:
            oriented.append((a, c, b))
        else:
            oriented.append((a, b, c))
    return oriented


def icosphere(subdivisions: int = 2) -> Tuple[List[Vec3], List[Face]]:
    """Devuelve una icosfera triangulada con ``20 * 4**subdivisions`` caras."""
    subdivisions = max(0, min(4, int(subdivisions)))
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    raw_vertices: List[Vec3] = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    vertices = [_normalize(tuple(float(c) for c in v)) for v in raw_vertices]
    faces: List[Face] = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]

    for _level in range(subdivisions):
        midpoint_cache: Dict[Tuple[int, int], int] = {}

        def midpoint(a: int, b: int) -> int:
            key = (a, b) if a < b else (b, a)
            cached = midpoint_cache.get(key)
            if cached is not None:
                return cached
            va, vb = vertices[a], vertices[b]
            index = len(vertices)
            vertices.append(_normalize((
                (va[0] + vb[0]) * 0.5,
                (va[1] + vb[1]) * 0.5,
                (va[2] + vb[2]) * 0.5,
            )))
            midpoint_cache[key] = index
            return index

        next_faces: List[Face] = []
        for a, b, c in faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            next_faces.extend(((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)))
        faces = next_faces

    return vertices, _orient_faces(vertices, faces)


def _axis_normalize(
    coordinates: Sequence[Vec3],
    axis: int,
    target_size: float,
    center: bool = True,
) -> List[Vec3]:
    values = [v[axis] for v in coordinates]
    low, high = min(values), max(values)
    extent = max(high - low, 1.0e-8)
    midpoint = (low + high) * 0.5 if center else low
    scale = float(target_size) / extent
    result: List[Vec3] = []
    for value in coordinates:
        values3 = list(value)
        values3[axis] = (value[axis] - midpoint) * scale
        result.append((values3[0], values3[1], values3[2]))
    return result


def generate_rock_geometry(settings: Any) -> Tuple[List[Vec3], List[Face]]:
    """Genera vértices y caras a partir de un conjunto de ajustes.

    Parámetros relevantes (todos tienen fallback para poder llamar a la función
    desde un script): ``seed``, ``detail``, ``width``, ``depth``, ``height``,
    ``surface_roughness``, ``asymmetry``, ``flatten_bottom`` y ``taper``.
    """
    seed = int(_value(settings, "seed", 1))
    detail = max(0, min(4, int(_value(settings, "detail", 2))))
    width = max(0.05, float(_value(settings, "width", 2.4)))
    depth = max(0.05, float(_value(settings, "depth", 2.0)))
    height = max(0.05, float(_value(settings, "height", 2.2)))
    roughness = _clamp(_value(settings, "surface_roughness", 0.38), 0.0, 1.0)
    asymmetry = _clamp(_value(settings, "asymmetry", 0.32), 0.0, 1.0)
    flatten = _clamp(_value(settings, "flatten_bottom", 0.45), 0.0, 1.0)
    taper = _clamp(_value(settings, "taper", 0.16), -0.5, 0.7)

    directions, faces = icosphere(detail)
    shaped: List[Vec3] = []
    for direction in directions:
        x, y, z = direction
        macro = fbm(x * 2.35, y * 2.35, z * 2.35, seed=seed + 11, octaves=4)
        medium = fbm(x * 4.8, y * 4.8, z * 4.8, seed=seed + 47, octaves=3)
        fine = fbm(x * 10.5, y * 10.5, z * 10.5, seed=seed + 89, octaves=2)
        ridge = ridged_fbm(x * 3.2, y * 3.2, z * 3.2, seed=seed + 131, octaves=3)

        # Macro controla la silueta; medium/fine conservan suficiente energía
        # para que el modo de normales planas tenga caras interesantes.
        radial = 1.0
        radial += roughness * (macro - 0.5) * 0.46
        radial += roughness * (medium - 0.5) * 0.18
        radial += roughness * (fine - 0.5) * 0.065
        radial += asymmetry * (ridge - 0.5) * 0.14
        radial = max(0.55, radial)

        # Hace la base algo más ancha o estrecha sin convertirla en un cono.
        vertical = (z + 1.0) * 0.5
        taper_factor = 1.0 + taper * (0.5 - vertical)
        taper_factor = max(0.55, taper_factor)

        # Una deformación suave en X/Y evita que cada roca sea una esfera sólo
        # escalada, incluso con roughness baja.
        side_x = 1.0 + asymmetry * (medium - 0.5) * 0.20
        side_y = 1.0 + asymmetry * (ridge - 0.5) * 0.18
        shaped.append((
            x * radial * taper_factor * side_x * width * 0.5,
            y * radial * taper_factor * side_y * depth * 0.5,
            z * radial * height * 0.5,
        ))

    # ``flatten_bottom`` crea una base que realmente puede apoyar en el suelo.
    # El plano se aplica antes de normalizar la dimensión final para que el
    # valor de Height siga siendo predecible.
    z_values = [v[2] for v in shaped]
    z_low = min(z_values)
    flat_level = z_low + height * 0.095 * flatten
    if flatten > 0.0:
        shaped = [(x, y, max(z, flat_level)) for x, y, z in shaped]

    shaped = _axis_normalize(shaped, 0, width, center=True)
    shaped = _axis_normalize(shaped, 1, depth, center=True)
    shaped = _axis_normalize(shaped, 2, height, center=False)
    return shaped, faces


def triangle_normal(vertices: Sequence[Vec3], face: Face) -> Vec3:
    """Normal unitaria de una cara, útil para diagnósticos y tests."""
    a, b, c = (vertices[i] for i in face)
    return _normalize(_cross(_sub(b, a), _sub(c, a)))
