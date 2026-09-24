# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Biblioteca de texturas procedurales.

Funciones de bajo nivel que devuelven :class:`~pcm_studio.shaderkit.NodeOut`
listos para enchufar.  Todas aceptan ``coords`` (un socket vector) y usan los
helpers tolerantes del :mod:`~pcm_studio.shaderkit`.

Vocabulario que se repite en las recetas:

``fiber``      ruido direccional (Gabor si existe, si no Wave): pelo, músculo,
               fibras de cuerno, barbas de pluma.
``ridged``     ruido con pliegues ``1-|2n-1|``: arrugas, surcos, grietas.
``cellular``   Voronoi con bordes marcados: poros, escamas, células, adoquines.
``warp``       *domain warping*: rompe la regularidad del ruido y es lo que
               separa un material "de IA" de uno creíble.
``cavity``     oclusión de concavidad a partir de la normal geométrica + Bevel:
               ensucia pliegues, comisuras y poros sin necesidad de bakear.
``scratch``    rayado fino direccional (desgaste de esmalte, queratina).
``stipple``    punteado (piel de naranja de la encía, trufa, pecas).
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence, Tuple

from . import compat
from .shaderkit import Builder, NodeOut, in_socket, out_socket

__all__ = (
    "fbm",
    "ridged",
    "cellular",
    "voronoi_cells",
    "warp",
    "fiber",
    "stipple",
    "scratch",
    "striations",
    "polar",
    "cavity",
    "mask_range",
    "smoothstep",
    "stretch",
    "tiling_offset",
    "height_combine",
    "speckle_field",
    "vein_network",
    "growth_rings",
    "crackle",
    "anisotropic_roughness",
)


# ---------------------------------------------------------------------------
# Coordenadas y utilidades vectoriales
# ---------------------------------------------------------------------------

def _default_coords(b: Builder, coords: Any, *, label: str = "Coords") -> Any:
    """Si no se pasan coordenadas, crea un Texture Coordinate (UV)."""
    if coords is not None:
        return coords
    tc = b.add("ShaderNodeTexCoord", label=label)
    if tc is None:
        return None
    return out_socket(tc, "UV", "Generated", 0)


def stretch(b: Builder, coords: Any, sx: float = 1.0, sy: float = 1.0,
            sz: float = 1.0, *, label: str = "") -> Optional[NodeOut]:
    """
    Estira el espacio de coordenadas de forma anisótropa.

    Útil para fibras: ``stretch(uv, 8.0, 1.0)`` comprime el patrón en X y lo
    alarga en Y, creando rayas en lugar de manchas.
    """
    vm = b.vector_math("MULTIPLY", coords, (sx, sy, sz), label=label or "Estirar")
    return vm


def tiling_offset(b: Builder, coords: Any, tiles: float = 1.0,
                  offset: Sequence[float] = (0.0, 0.0, 0.0), *,
                  label: str = "") -> Optional[NodeOut]:
    """``coords * tiles + offset`` en un solo nodo (MULTIPLY_ADD)."""
    if abs(tiles - 1.0) < 1e-6:
        vm = b.vector_math("ADD", coords, tuple(offset), label=label)
    else:
        vm = b.vector_math("MULTIPLY_ADD", coords, (tiles, tiles, tiles),
                           tuple(offset), label=label)
    return vm


def polar(b: Builder, coords: Any, center: Sequence[float] = (0.5, 0.5),
          *, label: str = "Polar") -> Tuple[Optional[NodeOut], Optional[NodeOut]]:
    """
    Convierte UV a coordenadas polares alrededor de ``center``.

    Devuelve ``(ángulo 0..1, radio 0..1)``.  Es la base del iris, de los
    patrones radiales de caparazón y de las pupilas.

    ángulo = atan2(dy, dx) / (2π) + 0.5
    radio  = sqrt(dx² + dy²) * 2
    """
    sep = b.add("ShaderNodeSeparateColor", label=label)
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB", label=label)
    if sep is None:
        return None, None
    b.link(coords, in_socket(sep, "Color", 0))
    u = out_socket(sep, "Red", 0)
    v = out_socket(sep, "Green", 1)

    du = b.math("SUBTRACT", u, center[0], label="dU")
    dv = b.math("SUBTRACT", v, center[1], label="dV")

    angle = _atan2(b, du, dv, label="Ángulo")
    radius = _length(b, du, dv, label="Radio")
    return angle, radius


def _atan2(b: Builder, x: Any, y: Any, *, label: str = "") -> Optional[NodeOut]:
    """
    ``atan2(y, x)`` normalizado a 0..1 usando Arctangent + corrección de
    cuadrante.  Blender no tiene Arctan2, así que:

        a = atan(y / x)                 (x != 0)
        a += π  si x < 0
        a += 2π si a < 0
        out = a / (2π)
    """
    ratio = b.math("DIVIDE", y, x, label=label)
    if ratio is None:
        return None
    base = b.math("ARCTANGENT", ratio, 0.0, label=label)
    # x < 0 -> sumar π
    is_neg = b.math("LESS_THAN", x, 0.0, label="x<0")
    add_pi = b.math("MULTIPLY", is_neg, math.pi, label="π?")
    shifted = b.math("ADD", base, add_pi, label=label)
    # negativo -> sumar 2π
    still_neg = b.math("LESS_THAN", shifted, 0.0)
    add_2pi = b.math("MULTIPLY", still_neg, 2.0 * math.pi)
    final = b.math("ADD", shifted, add_2pi, label=label)
    norm = b.math("DIVIDE", final, 2.0 * math.pi, label="0..1")
    return norm


def _length(b: Builder, x: Any, y: Any, *, label: str = "") -> Optional[NodeOut]:
    """``sqrt(x² + y²) * 2`` para que un radio de 0.5 en UV ocupe 0..1."""
    comb = b.add("ShaderNodeCombineColor")
    if comb is None:
        comb = b.add("ShaderNodeCombineRGB")
    if comb is not None:
        b.link(x, in_socket(comb, "Red", 0))
        b.link(y, in_socket(comb, "Green", 1))
        zero = b.value(0.0)
        if zero is not None:
            b.link(zero, in_socket(comb, "Blue", 2))
        vm = b.vector_math("LENGTH", out_socket(comb, "Color", "Vector", 0), label=label)
        if vm is not None:
            return b.math("MULTIPLY", vm, 2.0, label="Radio")
    # fallback escalar
    xs = b.math("MULTIPLY", x, x)
    ys = b.math("MULTIPLY", y, y)
    s = b.math("ADD", xs, ys)
    r = b.math("SQRT", s, 0.0, label=label)
    return b.math("MULTIPLY", r, 2.0, label="Radio")


def mask_range(b: Builder, value: Any, lo: float, hi: float, *,
               smooth: float = 0.08, label: str = "") -> Optional[NodeOut]:
    """
    Máscara 0..1 que es 1 entre ``lo`` y ``hi`` con bordes suaves.

    Se compone con dos ``SmoothStep`` (MapRange tipo ``SMOOTHSTEP``), que es la
    forma correcta de hacer un intervalo suave sin bordes duros.
    """
    rise = b.map_range(value, lo - smooth, lo + smooth, 0.0, 1.0,
                       interpolation="SMOOTHSTEP", clamp=True,
                       label=label or "Subida")
    if rise is None:
        return None
    fall = b.map_range(rise, hi - smooth, hi + smooth, 1.0, 0.0,
                       interpolation="SMOOTHSTEP", clamp=True,
                       label=label or "Bajada")
    return fall


def smoothstep(b: Builder, value: Any, lo: float, hi: float, *,
               label: str = "") -> Optional[NodeOut]:
    return b.map_range(value, lo, hi, 0.0, 1.0, interpolation="SMOOTHSTEP",
                       clamp=True, label=label)


# ---------------------------------------------------------------------------
# Ruidos base
# ---------------------------------------------------------------------------

def fbm(b: Builder, coords: Any = None, *, scale: float = 8.0, detail: float = 8.0,
        roughness: float = 0.55, lacunarity: float = 2.0, distortion: float = 0.0,
        w: float = 0.0, seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
        use_color: bool = False, label: str = "fBm") -> Optional[NodeOut]:
    """Ruido fractal (fBm) — la base de casi todo."""
    coords = _default_coords(b, coords)
    n = b.add("ShaderNodeTexNoise", label=label)
    if n is None:
        return None
    _set_noise(n, b, scale, detail, roughness, lacunarity, distortion, w)
    _apply_offset(b, n, coords, seed_offset)
    return NodeOut(n, out_socket(n, "Color" if use_color else "Fac", 0))


def ridged(b: Builder, coords: Any = None, *, scale: float = 12.0, detail: float = 6.0,
           roughness: float = 0.5, lacunarity: float = 2.1, sharpness: float = 1.0,
           seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
           label: str = "Pliegues") -> Optional[NodeOut]:
    """
    Ruido con pliegues: ``1 - |2n - 1|`` elevado a ``sharpness``.

    Produce crestas finas y valles marcados: exactamente la firma de una
    arruga, un surco o una grieta de queratina.
    """
    coords = _default_coords(b, coords)
    n = b.add("ShaderNodeTexNoise", label=label)
    if n is None:
        return None
    _set_noise(n, b, scale, detail, roughness, lacunarity, 0.0, 0.0)
    _apply_offset(b, n, coords, seed_offset)
    fac = out_socket(n, "Fac", 0)

    doubled = b.math("MULTIPLY", fac, 2.0, label="×2")
    folded = b.math("SUBTRACT", doubled, 1.0, label="-1")
    abs_node = b.math("ABSOLUTE", folded, 0.0, label="|x|")
    if abs_node is None:
        abs_node = b.math("MAXIMUM", folded, b.math("MULTIPLY", folded, -1.0), label="|x|")
    inv = b.math("SUBTRACT", 1.0, abs_node, label="1-|x|")
    if abs(sharpness - 1.0) > 1e-3:
        pw = b.math("POWER", inv, max(0.05, sharpness), label="Nitidez")
        return pw
    return inv


def _set_noise(n: Any, b: Builder, scale: float, detail: float, roughness: float,
               lacunarity: float, distortion: float, w: float) -> None:
    compat.set_sock(n, "Scale", float(scale))
    compat.set_sock(n, "Detail", float(detail))
    compat.set_sock(n, "Roughness", float(roughness))
    compat.set_sock(n, "Lacunarity", float(lacunarity))
    compat.set_sock(n, "Distortion", float(distortion))
    compat.set_sock(n, "W", float(w))


def _apply_offset(b: Builder, node: Any, coords: Any,
                  offset: Sequence[float]) -> None:
    """Enlaza ``coords`` (con desplazamiento si procede) a la entrada Vector."""
    if coords is None:
        return
    if any(abs(o) > 1e-9 for o in offset):
        shifted = b.vector_math("ADD", coords, tuple(offset), label="Semilla")
        b.link(shifted, in_socket(node, "Vector", 0))
    else:
        b.link(coords, in_socket(node, "Vector", 0))


def voronoi_cells(b: Builder, coords: Any = None, *, scale: float = 60.0,
                  randomness: float = 1.0, w: float = 0.0,
                  smoothness: float = 0.1, exponent: float = 1.0,
                  feature: str = "F1", distance: str = "EUCLIDEAN",
                  output: str = "Distance",
                  seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
                  label: str = "Voronoi") -> Optional[NodeOut]:
    """Voronoi configurable (F1..F4, suavizado, métrica)."""
    coords = _default_coords(b, coords)
    n = b.add("ShaderNodeTexVoronoi", label=label)
    if n is None:
        return None
    try:
        n.feature = feature
    except Exception:
        pass
    try:
        n.distance = distance
    except Exception:
        pass
    try:
        n.dimension = "4D" if abs(w) > 1e-9 else "3D"
    except Exception:
        pass
    compat.set_sock(n, "Scale", float(scale))
    compat.set_sock(n, "Randomness", float(randomness))
    compat.set_sock(n, "Smoothness", float(smoothness))
    compat.set_sock(n, "Exponent", float(exponent))
    compat.set_sock(n, "W", float(w))
    _apply_offset(b, n, coords, seed_offset)
    return NodeOut(n, out_socket(n, output, "Distance", "Color", 0))


def cellular(b: Builder, coords: Any = None, *, scale: float = 60.0,
             randomness: float = 1.0, smoothness: float = 0.35,
             edge_width: float = 0.35, invert: bool = False,
             seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
             label: str = "Celdas") -> Optional[NodeOut]:
    """
    Celdas con borde marcado (placas, escamas, poros, adoquinado).

    Mezcla ``F1`` (interior de la celda) con ``Smooth F1`` (borde dilatado) para
    obtener un borde nítido y controlable, que es lo que da el aspecto de
    "placa" y no de simple ruido.
    """
    coords = _default_coords(b, coords)
    inner = voronoi_cells(b, coords, scale=scale, randomness=randomness,
                          smoothness=0.0, feature="F1",
                          seed_offset=seed_offset, label=f"{label} · interior")
    edge = voronoi_cells(b, coords, scale=scale, randomness=randomness,
                         smoothness=max(0.001, smoothness), feature="Smooth F1",
                         seed_offset=seed_offset, label=f"{label} · borde")
    if inner is None or edge is None:
        return inner or edge
    diff = b.math("SUBTRACT", edge, inner, label="Borde")
    if diff is None:
        return inner
    norm = b.map_range(diff, 0.0, max(1e-4, smoothness * 1.2), 0.0, 1.0,
                       clamp=True, label="Normalizar")
    shaped = b.math("POWER", norm, max(0.05, 1.0 / max(0.05, edge_width)),
                    label="Perfil")
    if shaped is None:
        shaped = norm
    if invert:
        shaped = b.math("SUBTRACT", 1.0, shaped, label="Invertir")
    return shaped


def warp(b: Builder, coords: Any, amount: float = 0.35, *, warp_scale: float = 3.0,
         detail: float = 4.0, roughness: float = 0.5,
         seed_offset: Sequence[float] = (11.3, 7.7, 3.1),
         label: str = "Deformar") -> Optional[NodeOut]:
    """
    *Domain warping*: desplaza las coordenadas con otro ruido.

    Es el truco que rompe la repetición y la simetría de los ruidos simples.
    Sin esto, una arruga parece un patrón de azulejos.
    """
    if coords is None:
        return None
    wx = fbm(b, coords, scale=warp_scale, detail=detail, roughness=roughness,
             seed_offset=seed_offset, label=f"{label} X")
    wy = fbm(b, coords, scale=warp_scale, detail=detail, roughness=roughness,
             seed_offset=(seed_offset[0] + 31.7, seed_offset[1] + 17.3,
                          seed_offset[2] + 5.9), label=f"{label} Y")
    if wx is None or wy is None:
        return coords
    dx = b.math("MULTIPLY", b.math("SUBTRACT", wx, 0.5), amount, label="ΔX")
    dy = b.math("MULTIPLY", b.math("SUBTRACT", wy, 0.5), amount, label="ΔY")
    comb = b.add("ShaderNodeCombineColor")
    if comb is None:
        comb = b.add("ShaderNodeCombineRGB")
    if comb is None:
        return coords
    b.link(dx, in_socket(comb, "Red", 0))
    b.link(dy, in_socket(comb, "Green", 1))
    zero = b.value(0.0)
    if zero is not None:
        b.link(zero, in_socket(comb, "Blue", 2))
    return b.vector_math("ADD", coords, out_socket(comb, "Color", "Vector", 0),
                         label=label)


def fiber(b: Builder, coords: Any = None, *, scale: float = 300.0,
          anisotropy: float = 0.9, direction: Sequence[float] = (1.0, 0.0, 0.0),
          frequency: float = 80.0, use_gabor: bool = True,
          seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
          label: str = "Fibra") -> Optional[NodeOut]:
    """
    Ruido direccional para estructuras fibrosas (pelo, músculo, queratina,
    barbas de pluma).

    Usa el nodo **Gabor** de Blender 5.x cuando existe — es ruido de banda
    limitada, alias-free y con anisotropía real, exactamente lo que se necesita
    para fibras finas sin *moire* al bakear.  Si no existe se degrada a
    ``Wave`` con coordenadas estiradas.
    """
    coords = _default_coords(b, coords)
    if use_gabor and compat.has_node("ShaderNodeTexGabor"):
        n = b.add("ShaderNodeTexGabor", label=label)
        if n is not None:
            try:
                n.gabor_type = "ANISOTROPIC"
            except Exception:
                pass
            compat.set_sock(n, "Scale", float(scale))
            compat.set_sock(n, "Anisotropy", float(anisotropy))
            compat.set_sock(n, "Frequency", float(frequency))
            # Direction puede ser un socket vector con propiedad "Direction"
            dir_sock = in_socket(n, "Direction")
            if dir_sock is not None:
                try:
                    dir_sock.default_value = tuple(direction)
                except Exception:
                    pass
            _apply_offset(b, n, coords, seed_offset)
            out = out_socket(n, "Noise", "Fac", "Color", 0)
            if out is not None:
                # Gabor devuelve valores con signo: normalizar a 0..1
                return b.map_range(out, -1.0, 1.0, 0.0, 1.0, clamp=True,
                                   label="Fibra 0..1")
    # --- fallback: Wave estirado ---
    stretched = stretch(b, coords, 1.0, max(1.0, scale / 8.0), 1.0,
                        label=f"{label} · estirar")
    n = b.add("ShaderNodeTexWave", label=label)
    if n is None:
        return fbm(b, coords, scale=scale, detail=6.0, roughness=0.35,
                   seed_offset=seed_offset, label=label)
    try:
        n.wave_type = "BANDS"
        n.bands_direction = "X"
    except Exception:
        pass
    compat.set_sock(n, "Scale", 1.0)
    compat.set_sock(n, "Detail", 6.0)
    compat.set_sock(n, "Detail Scale", 1.0)
    compat.set_sock(n, "Detail Roughness", 0.5)
    compat.set_sock(n, "Distortion", 3.0)
    b.link(stretched if stretched is not None else coords, in_socket(n, "Vector", 0))
    return NodeOut(n, out_socket(n, "Fac", "Color", 0))


def stipple(b: Builder, coords: Any = None, *, scale: float = 250.0,
            density: float = 0.35, softness: float = 0.4,
            seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
            label: str = "Punteado") -> Optional[NodeOut]:
    """
    Puntos dispersos y redondeados (poros, pecas, punteado gingival, trufa).

    Voronoi ``F1`` con ``Smoothness`` alta y umbral: sólo los núcleos de celda
    sobreviven, así que salen motas aisladas y no un mosaico.
    """
    coords = _default_coords(b, coords)
    v = voronoi_cells(b, coords, scale=scale, smoothness=softness,
                      feature="Smooth F1", seed_offset=seed_offset, label=label)
    if v is None:
        return None
    dot = b.map_range(v, 0.0, max(0.01, density), 1.0, 0.0,
                      interpolation="SMOOTHSTEP", clamp=True, label="Mota")
    return dot


def speckle_field(b: Builder, coords: Any = None, *, scale: float = 120.0,
                  density: float = 0.06, size: float = 0.25,
                  seed_offset: Sequence[float] = (5.0, 9.0, 2.0),
                  label: str = "Lunares") -> Optional[NodeOut]:
    """
    Manchas dispersas *muy* poco frecuentes (lunares, pecas grandes).

    Combina Voronoi para la posición con un ruido de baja frecuencia que
    modula la densidad, de modo que las manchas se agrupen en zonas (mejillas,
    frente) en vez de repartirse uniformemente: así es como aparecen de verdad.
    """
    coords = _default_coords(b, coords)
    dots = stipple(b, coords, scale=scale, density=size, softness=0.5,
                   seed_offset=seed_offset, label=label)
    if dots is None:
        return None
    region = fbm(b, coords, scale=max(0.5, scale * 0.02), detail=3.0,
                 roughness=0.5, seed_offset=(seed_offset[0] + 40.0, 3.0, 71.0),
                 label="Zona de pecas")
    if region is None:
        return dots
    gate = b.map_range(region, 1.0 - density, 1.0, 0.0, 1.0, clamp=True,
                       label="Densidad")
    return b.math("MULTIPLY", dots, gate, label=label)


def scratch(b: Builder, coords: Any = None, *, scale: float = 400.0,
            density: float = 0.02, length: float = 20.0, angle_deg: float = 35.0,
            seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
            label: str = "Rayado") -> Optional[NodeOut]:
    """
    Micro-rayado direccional (desgaste de esmalte, queratina, cuero).

    Se consigue estirando muchísimo un Voronoi en una dirección y quedándose
    con los bordes: salen filamentos largos y finos con orientación coherente.
    """
    coords = _default_coords(b, coords)
    rad = math.radians(angle_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    rot = b.add("ShaderNodeVectorRotate", label="Rotar rayado")
    src = coords
    if rot is not None:
        try:
            rot.rotation_type = "EULER_XYZ"
        except Exception:
            pass
        b.link(coords, in_socket(rot, "Vector", 0))
        compat.set_sock(rot, "Angle", (0.0, 0.0, rad))
        src = out_socket(rot, "Vector", 0)
    stretched = stretch(b, src, length, 1.0, 1.0, label="Alargar")
    cells = cellular(b, stretched if stretched is not None else src, scale=scale,
                     smoothness=0.25, edge_width=0.15, invert=True,
                     seed_offset=seed_offset, label=label)
    if cells is None:
        return None
    return b.map_range(cells, 1.0 - density, 1.0, 0.0, 1.0, clamp=True,
                       label="Densidad")


def striations(b: Builder, coords: Any = None, *, count: float = 60.0,
               wobble: float = 0.05, thickness: float = 0.5,
               axis: str = "U", seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
               label: str = "Estrías") -> Optional[NodeOut]:
    """
    Estrías paralelas con ondulación (estrías de los labios, periquimatias del
    esmalte, anillos de crecimiento, fibras de cuerno).

    Se toma una sola componente del UV, se ondula ligeramente con un ruido de
    baja frecuencia y se pasa por ``Ping-Pong`` / ``Modulo`` para repetirla.
    """
    coords = _default_coords(b, coords)
    sep = b.add("ShaderNodeSeparateColor")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None:
        return None
    b.link(coords, in_socket(sep, "Color", 0))
    comp = "Red" if axis.upper().startswith("U") else "Green"
    line = out_socket(sep, comp, 0)

    if wobble > 1e-6:
        wob = fbm(b, coords, scale=max(1.0, count * 0.15), detail=3.0,
                  roughness=0.5, seed_offset=seed_offset, label="Ondulación")
        if wob is not None:
            delta = b.math("MULTIPLY", b.math("SUBTRACT", wob, 0.5), wobble)
            line = b.math("ADD", line, delta)

    scaled = b.math("MULTIPLY", line, float(count), label="Repetir")
    ping = b.math("PINGPONG", scaled, 1.0, label="Triangular")
    shaped = b.map_range(ping, 0.5 - thickness * 0.5, 0.5 + thickness * 0.5,
                         0.0, 1.0, interpolation="SMOOTHSTEP", clamp=True,
                         label=label)
    return shaped


def growth_rings(b: Builder, coords: Any = None, *, count: float = 24.0,
                 irregularity: float = 0.35, hardness: float = 0.5,
                 label: str = "Anillos") -> Optional[NodeOut]:
    """Anillos de crecimiento concéntricos con separación irregular."""
    coords = _default_coords(b, coords)
    noise = fbm(b, coords, scale=max(1.0, count * 0.25), detail=4.0,
                roughness=0.6, label="Irregularidad")
    if noise is None:
        return None
    # El anillo se construye a partir de la distancia radial del UV.
    sep = b.add("ShaderNodeSeparateColor")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None:
        return None
    b.link(coords, in_socket(sep, "Color", 0))
    u = b.math("SUBTRACT", out_socket(sep, "Red", 0), 0.5)
    v = b.math("SUBTRACT", out_socket(sep, "Green", 1), 0.5)
    radius = _length(b, u, v, label="Radio")
    wob = b.math("MULTIPLY", b.math("SUBTRACT", noise, 0.5), irregularity)
    ring = b.math("ADD", radius, wob, label="Radio deformado")
    scaled = b.math("MULTIPLY", ring, float(count))
    ping = b.math("PINGPONG", scaled, 1.0)
    shaped = b.map_range(ping, 0.5 - hardness * 0.5, 0.5 + hardness * 0.5,
                         0.0, 1.0, interpolation="SMOOTHSTEP", clamp=True,
                         label=label)
    return shaped


def crackle(b: Builder, coords: Any = None, *, scale: float = 12.0,
            width: float = 0.06, depth: float = 1.0, warp_amount: float = 0.4,
            seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
            label: str = "Grietas") -> Optional[NodeOut]:
    """
    Red de grietas (piel reseca, escamas gastadas, barro, queratina rota).

    Voronoi ``F2 - F1`` (diferencia entre la segunda y la primera celda más
    cercana) da exactamente las paredes de la teselación.
    """
    coords = _default_coords(b, coords)
    if warp_amount > 1e-6:
        warped = warp(b, coords, amount=warp_amount, warp_scale=scale * 0.35,
                      seed_offset=seed_offset, label=f"{label} · warp")
        coords = warped if warped is not None else coords
    f1 = voronoi_cells(b, coords, scale=scale, smoothness=0.0, feature="F1",
                       seed_offset=seed_offset, label="F1")
    f2 = voronoi_cells(b, coords, scale=scale, smoothness=0.0, feature="F2",
                       seed_offset=seed_offset, label="F2")
    if f1 is None or f2 is None:
        return None
    diff = b.math("SUBTRACT", f2, f1, label="F2-F1")
    crack = b.map_range(diff, 0.0, max(0.001, width), 1.0, 0.0,
                        interpolation="SMOOTHSTEP", clamp=True, label=label)
    if abs(depth - 1.0) > 1e-6:
        crack = b.math("MULTIPLY", crack, float(depth), label="Profundidad")
    return crack


def vein_network(b: Builder, coords: Any = None, *, scale: float = 22.0,
                 thickness: float = 0.06, branching: float = 0.5,
                 warp_amount: float = 0.55,
                 seed_offset: Sequence[float] = (0.0, 0.0, 0.0),
                 label: str = "Venas") -> Optional[NodeOut]:
    """
    Red ramificada tipo vasculatura (venas de la esclerótica, capilares,
    nervadura de hoja, vetas de nácar).

    Dos Voronoi a distinta escala restados y deformados: las ramas gruesas
    salen de la escala baja y la ramificación fina de la alta.
    """
    coords = _default_coords(b, coords)
    if warp_amount > 1e-6:
        warped = warp(b, coords, amount=warp_amount, warp_scale=scale * 0.6,
                      seed_offset=seed_offset, label=f"{label} · warp")
        coords = warped if warped is not None else coords

    trunk = crackle(b, coords, scale=scale, width=thickness,
                    warp_amount=0.0, seed_offset=seed_offset,
                    label=f"{label} · gruesas")
    twigs = crackle(b, coords, scale=scale * 3.2, width=thickness * branching,
                    warp_amount=0.0,
                    seed_offset=(seed_offset[0] + 17.0, seed_offset[1] + 4.0,
                                 seed_offset[2] + 23.0),
                    label=f"{label} · finas")
    if trunk is None or twigs is None:
        return trunk or twigs
    combined = b.math("MAXIMUM", trunk, b.math("MULTIPLY", twigs, 0.55),
                      label=label)
    return combined


def cavity(b: Builder, *, radius: float = 0.004, samples: int = 4,
           contrast: float = 1.4, label: str = "Cavidad") -> Optional[NodeOut]:
    """
    Oclusión de cavidad en tiempo real: normal geométrica vs. normal suavizada
    con ``Bevel``.  Oscurece poros, pliegues y comisuras sin bakear nada.

    ``cavity = 1 - dot(N_geo, N_bevel)`` remapeado.
    """
    geo = b.add("ShaderNodeNewGeometry", label="Geometría")
    bev = b.add("ShaderNodeBevel", label="Bisel")
    if geo is None or bev is None:
        return None
    try:
        bev.samples = max(1, int(samples))
    except Exception:
        pass
    compat.set_sock(bev, "Radius", float(radius))
    true_normal = out_socket(geo, "True Normal", "Normal", 0)
    b.link(true_normal, in_socket(bev, "Normal", 0))
    dot = b.vector_math("DOT_PRODUCT", out_socket(bev, "Normal", 0), true_normal,
                        label="N·N'")
    if dot is None:
        return None
    inv = b.math("SUBTRACT", 1.0, dot, label="1 - N·N'")
    shaped = b.math("MULTIPLY", inv, float(contrast), label=label)
    return b.math("MAXIMUM", shaped, 0.0, label="Recorte")


def height_combine(b: Builder, layers: Sequence[Tuple[Any, float]], *,
                   label: str = "Altura") -> Optional[NodeOut]:
    """Suma capas de altura con su peso: ``Σ layer_i * weight_i``."""
    result: Any = None
    for i, (layer, weight) in enumerate(layers):
        if layer is None:
            continue
        scaled = b.math("MULTIPLY", layer, float(weight),
                        label=f"{label} {i + 1}") if abs(weight - 1.0) > 1e-6 else layer
        if scaled is None:
            continue
        result = scaled if result is None else b.math("ADD", result, scaled,
                                                      label=label)
    return result


def anisotropic_roughness(b: Builder, base: Any, fiber_map: Any,
                          amount: float = 0.25, *,
                          label: str = "Rugosidad anisótropa") -> Optional[NodeOut]:
    """
    Modula la rugosidad con un mapa fibroso: las fibras reflejan de forma
    alargada (pelo, seda, músculo, plumas).
    """
    if base is None:
        return None
    if fiber_map is None or amount <= 1e-6:
        return base
    delta = b.math("MULTIPLY", b.math("SUBTRACT", fiber_map, 0.5), amount,
                   label=label)
    out = b.math("ADD", base, delta)
    return b.clamp(out, 0.004, 1.0, label="Rugosidad final")
