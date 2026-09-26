# SPDX-License-Identifier: GPL-3.0-or-later
"""Ruido determinista pequeño para la silueta de Stylized Rock Forge.

Se implementa aquí, en vez de usar ``mathutils.noise``, para que la misma roca
sea reproducible en Blender, en un render de granja y en las comprobaciones que
se ejecutan fuera de Blender. Las funciones no mantienen estado global.
"""

from __future__ import annotations

import math
from typing import Tuple


Vec3 = Tuple[float, float, float]


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def hash01(ix: int, iy: int, iz: int, seed: int = 0) -> float:
    """Hash entero rápido que devuelve un valor en ``[0, 1)``."""
    # Constantes grandes y diferentes para evitar bandas visibles en los ejes.
    n = _u32(
        ix * 0x1F123BB5
        + iy * 0x5F356495
        + iz * 0x7F4A7C15
        + int(seed) * 0x6C8E9CF5
        + 0x9E3779B9
    )
    n ^= n >> 16
    n = _u32(n * 0x45D9F3B)
    n ^= n >> 16
    n = _u32(n * 0x45D9F3B)
    n ^= n >> 16
    return n / 4294967296.0


def _smooth(t: float) -> float:
    # Quintic fade: la primera y segunda derivada son cero en los extremos.
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(x: float, y: float, z: float, seed: int = 0) -> float:
    """Ruido de valor trilineal suave en ``[0, 1]``."""
    x0 = math.floor(x)
    y0 = math.floor(y)
    z0 = math.floor(z)
    tx = _smooth(x - x0)
    ty = _smooth(y - y0)
    tz = _smooth(z - z0)

    def sample(dx: int, dy: int, dz: int) -> float:
        return hash01(x0 + dx, y0 + dy, z0 + dz, seed)

    x00 = sample(0, 0, 0) + (sample(1, 0, 0) - sample(0, 0, 0)) * tx
    x10 = sample(0, 1, 0) + (sample(1, 1, 0) - sample(0, 1, 0)) * tx
    x01 = sample(0, 0, 1) + (sample(1, 0, 1) - sample(0, 0, 1)) * tx
    x11 = sample(0, 1, 1) + (sample(1, 1, 1) - sample(0, 1, 1)) * tx
    y0v = x00 + (x10 - x00) * ty
    y1v = x01 + (x11 - x01) * ty
    return y0v + (y1v - y0v) * tz


def fbm(
    x: float,
    y: float,
    z: float,
    seed: int = 0,
    octaves: int = 4,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> float:
    """Fractal Brownian Motion normalizado aproximadamente a ``[0, 1]``."""
    octaves = max(1, int(octaves))
    frequency = 1.0
    amplitude = 1.0
    total = 0.0
    weight = 0.0
    for octave in range(octaves):
        total += value_noise(
            x * frequency,
            y * frequency,
            z * frequency,
            int(seed) + octave * 1013,
        ) * amplitude
        weight += amplitude
        frequency *= lacunarity
        amplitude *= gain
    return total / weight if weight else 0.5


def ridged_fbm(
    x: float,
    y: float,
    z: float,
    seed: int = 0,
    octaves: int = 3,
) -> float:
    """Variante con crestas, útil para cortes angulares y vetas de roca."""
    value = fbm(x, y, z, seed=seed, octaves=octaves)
    return 1.0 - abs(value * 2.0 - 1.0)
