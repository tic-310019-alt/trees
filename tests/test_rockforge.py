# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Comprobaciones rápidas de la parte pura de Stylized Rock Forge."""

from __future__ import annotations

import math
import os
import sys
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from stylized_rocks.geometry import generate_rock_geometry, triangle_normal  # noqa: E402


Vec3 = Tuple[float, float, float]


def _check(condition: bool, message: str, failures: List[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: List[str] = []
    for detail, expected_faces in enumerate((20, 80, 320, 1280, 5120)):
        settings = {
            "seed": 1337,
            "detail": detail,
            "width": 2.4,
            "depth": 2.0,
            "height": 2.2,
            "surface_roughness": 0.38,
            "asymmetry": 0.32,
            "flatten_bottom": 0.45,
            "taper": 0.16,
        }
        vertices, faces = generate_rock_geometry(settings)
        _check(len(faces) == expected_faces, f"detail {detail}: nº de caras", failures)
        _check(len(vertices) > 0, f"detail {detail}: vértices", failures)
        _check(all(len(set(face)) == 3 for face in faces), f"detail {detail}: caras degeneradas", failures)
        for face in faces:
            normal = triangle_normal(vertices, face)
            center = tuple(sum(vertices[index][axis] for index in face) / 3.0 for axis in range(3))
            # La forma se apoya en z=0; el centro aproximado de la roca está a
            # media altura. Las normales deben seguir mirando hacia fuera.
            radial = (center[0], center[1], center[2] - 1.1)
            _check(sum(normal[axis] * radial[axis] for axis in range(3)) > 0.0,
                   f"detail {detail}: orientación de normal", failures)
            if failures:
                break

    first, _ = generate_rock_geometry({"seed": 9, "detail": 2})
    same, _ = generate_rock_geometry({"seed": 9, "detail": 2})
    other, _ = generate_rock_geometry({"seed": 10, "detail": 2})
    _check(first == same, "la misma semilla debe ser determinista", failures)
    _check(first != other, "dos semillas deben producir variación", failures)

    vertices, _ = generate_rock_geometry({"seed": 1, "detail": 2, "width": 3.0, "depth": 1.5, "height": 4.0})
    spans = [max(v[axis] for v in vertices) - min(v[axis] for v in vertices) for axis in range(3)]
    for axis, (actual, expected) in enumerate(zip(spans, (3.0, 1.5, 4.0))):
        _check(math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6),
               f"dimensión {axis}: {actual} != {expected}", failures)

    if failures:
        print(f"Stylized Rock Forge: {len(failures)} FALLOS")
        for failure in failures[:20]:
            print("  ✗", failure)
        return 1
    print("Stylized Rock Forge: geometría determinista, dimensiones y normales OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
