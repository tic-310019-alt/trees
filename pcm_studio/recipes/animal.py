# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Recetas animales.

**Pelaje.** Pelo corto y denso: la clave es que el color no es plano sino que va
de raíz oscura a punta aclarada, con un halo (``Sheen``/``Velvet``) en los
bordes donde la luz atraviesa las puntas.  La dirección de crecimiento se
controla con un ángulo, y los patrones (manchado, atigrado) se construyen sobre
la misma coordenada para que coincidan con la fibra.

**Escamas.** Placas con borde levantado: el interior de la celda Voronoi se
abomba y la junta se hunde, así la luz rasante dibuja cada escama.  Se añade
gradación de tamaño, desgaste en el centro de la placa e iridiscencia opcional.

**Plumas.** Raquis central + barbas perpendiculares + teselación de plumas de
cobertura que se solapan como tejas.

**Hocico.** Trufa húmeda con punteado grueso, philtrum, fosas nasales oscuras y
borde seco.

**Anfibio.** Piel granulada con mucosidad muy brillante, manchas de aviso y
translucidez.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence, Tuple

from .. import compat, texlib
from ..shaderkit import NodeOut, in_socket, out_socket
from .base import (
    RecipeContext,
    RecipeResult,
    clamp_color,
    saturate,
)

__all__ = ("fur", "scales", "feathers", "snout", "amphibian")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uv_components(b, ctx: RecipeContext) -> Tuple[Any, Any]:
    uv = ctx.coords("UV", scaled=False)
    sep = b.add("ShaderNodeSeparateColor", label="Separar UV")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None or uv is None:
        return None, None
    b.link(uv, in_socket(sep, "Color", 0))
    return out_socket(sep, "Red", 0), out_socket(sep, "Green", 1)


def _ventral_mask(ctx: RecipeContext) -> Optional[NodeOut]:
    """
    Máscara 1 en la zona ventral (abajo) → 0 en el dorso.

    Usa el eje Z en espacio de objeto: es la convención estándar de Blender y
    funciona en cualquier personaje sin tocar nada.
    """
    b = ctx.b
    coords = ctx.coords("Object", scaled=False)
    if coords is None:
        return None
    sep = b.add("ShaderNodeSeparateXYZ", label="Separar objeto")
    if sep is None:
        return None
    b.link(coords, in_socket(sep, "Vector", 0))
    z = out_socket(sep, "Z", 2)
    lo = ctx.f("Vientre abajo", -0.6)
    hi = ctx.f("Vientre arriba", 0.1)
    if abs(hi - lo) < 1e-4:
        hi = lo + 1.0
    return b.map_range(z, min(lo, hi), max(lo, hi), 1.0, 0.0,
                       interpolation="SMOOTHSTEP", clamp=True,
                       label="Zona ventral")


def _growth_direction(b, angle_deg: float, coords: Any) -> Optional[Any]:
    """Coordenadas rotadas para alinear la fibra con la dirección de crecimiento."""
    rot = b.add("ShaderNodeVectorRotate", label="Dirección de crecimiento")
    if rot is None:
        return coords
    try:
        rot.rotation_type = "EULER_XYZ"
    except Exception:
        pass
    b.link(coords, in_socket(rot, "Vector", 0))
    compat.set_sock(rot, "Angle", (0.0, 0.0, math.radians(angle_deg)))
    return out_socket(rot, "Vector", 0)


# ---------------------------------------------------------------------------
# PELAJE
# ---------------------------------------------------------------------------

def fur(ctx: RecipeContext) -> RecipeResult:
    """Pelaje corto y denso con dirección de crecimiento."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    length = ctx.f("Longitud de fibra", 0.6)
    density = ctx.f("Densidad", 0.75)
    direction = math.degrees(ctx.f("Dirección", 0.0))
    spots_p = ctx.f("Manchado", 0.0)
    stripes_p = ctx.f("Atigrado", 0.0)
    sheen_p = ctx.f("Sheen", 0.55)
    aniso = ctx.f("Anisotropía", 0.8)
    dirt_p = ctx.f("Suciedad", 0.15)
    belly_p = ctx.f("Vientre", 0.5)
    detail = ctx.f("Detalle", 1.0)

    # coordenadas alineadas con el crecimiento del pelo
    aligned = _growth_direction(b, direction, coords)
    fiber_scale = ctx.detail_scale(220.0 + 620.0 * max(0.05, 1.0 - length))

    # ------------------------------------------------------------------
    # 1. Altura: fibra individual
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    fiber = texlib.fiber(b, aligned, scale=fiber_scale, anisotropy=0.96,
                         use_gabor=ctx.on("use_gabor"),
                         seed_offset=(17.0, 43.0, 7.0), label="Fibra de pelaje")
    if fiber is not None and density > 1e-4:
        centered = b.math("SUBTRACT", fiber, 0.5, label="Centrar fibra")
        layers.append((centered, 0.00055 * density * detail))
    # ondulación del manto (el pelo no es perfectamente liso)
    wave = texlib.fbm(b, aligned, scale=ctx.detail_scale(16.0), detail=5.0,
                      roughness=0.55, seed_offset=(71.0, 11.0, 29.0),
                      label="Ondulación del manto")
    if wave is not None:
        layers.append((b.math("SUBTRACT", wave, 0.5), 0.0011 * detail))

    height = ctx.micro_detail(layers, label="Altura del pelaje")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del pelaje") if height else None

    # ------------------------------------------------------------------
    # 2. Color
    # ------------------------------------------------------------------
    color: Any = b.rgb(ctx.c("Color base"), label="Pelaje")

    # raíz oscura → punta clara (cada pelo, no sólo el manto)
    if color is not None and fiber is not None:
        root = b.map_range(fiber, 0.0, 1.0, 1.0, 0.0, clamp=True,
                           label="Raíz / punta")
        dark = b.mix_rgb("MIX", b.math("MULTIPLY", root, 0.45),
                         color, ctx.c("Color raíces"), label="Raíces")
        if dark is not None:
            color = dark
        light = b.mix_rgb("MIX", b.math("MULTIPLY", b.math("SUBTRACT", 1.0, root), 0.40),
                          color, ctx.c("Color puntas"), label="Puntas")
        if light is not None:
            color = light

    # variación de mechones
    variation = ctx.f("Variación", 0.35)
    if color is not None and variation > 1e-4:
        tuft = texlib.fbm(b, coords, scale=ctx.detail_scale(9.0), detail=4.0,
                          roughness=0.6, seed_offset=(37.0, 83.0, 5.0),
                          label="Mechones")
        if tuft is not None:
            mod = b.map_range(tuft, 0.30, 0.75, 0.80, 1.25, clamp=True,
                              label="Modulación")
            varied = b.mix_rgb("MULTIPLY", variation, color,
                               b.math("MULTIPLY", color, mod), label="Pelaje variado")
            if varied is not None:
                color = varied

    # zona ventral clara
    belly = _ventral_mask(ctx)
    if color is not None and belly is not None and belly_p > 1e-4:
        pale = b.mix_rgb("MIX", b.math("MULTIPLY", belly, belly_p),
                         color, ctx.c("Color vientre"), label="Vientre claro")
        if pale is not None:
            color = pale

    # manchas grandes
    if color is not None and spots_p > 1e-4:
        blotch = texlib.voronoi_cells(b, coords, scale=ctx.detail_scale(5.0),
                                      smoothness=0.55, feature="Smooth F1",
                                      randomness=1.0,
                                      seed_offset=(23.0, 61.0, 13.0),
                                      label="Manchas")
        if blotch is not None:
            mask = b.map_range(blotch, 0.25, 0.62, 0.0, 1.0,
                               interpolation="SMOOTHSTEP", clamp=True,
                               label="Máscara de manchas")
            dark_spots = b.mix_rgb("MIX", b.math("MULTIPLY", mask, spots_p),
                                   color, ctx.c("Color raíces"), label="Manchado")
            if dark_spots is not None:
                color = dark_spots

    # rayas (atigrado)
    if color is not None and stripes_p > 1e-4:
        warp = texlib.warp(b, aligned, amount=0.35, warp_scale=4.0,
                           seed_offset=(53.0, 17.0, 71.0), label="Warp de rayas")
        src = warp if warp is not None else aligned
        stri = texlib.striations(b, src, count=ctx.detail_scale(11.0),
                                 wobble=0.30, thickness=0.42, axis="U",
                                 seed_offset=(5.0, 91.0, 23.0), label="Rayas")
        if stri is not None:
            dark_stripes = b.mix_rgb("MIX", b.math("MULTIPLY", stri, stripes_p),
                                     color, ctx.c("Color raíces"), label="Atigrado")
            if dark_stripes is not None:
                color = dark_stripes

    # suciedad en la raíz
    if color is not None and dirt_p > 1e-4:
        dirt = texlib.fbm(b, coords, scale=ctx.detail_scale(7.0), detail=5.0,
                          roughness=0.6, seed_offset=(83.0, 29.0, 11.0),
                          label="Suciedad")
        if dirt is not None:
            mask = b.map_range(dirt, 0.40, 0.85, 0.0, 1.0, clamp=True)
            if belly is not None:
                mask = b.math("MULTIPLY", mask, b.math("SUBTRACT", 1.0, belly),
                              label="Suciedad en el lomo")
            dirty = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", mask, dirt_p),
                              color, (0.34, 0.28, 0.20, 1.0), label="Sucio")
            if dirty is not None:
                color = dirty

    cavity = ctx.cavity(radius=0.006, label="Cavidad del pelaje")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.55),
                          color, (0.30, 0.22, 0.16, 1.0), label="Sombras del manto")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.g("color_saturation", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.55)
    rough: Any = b.value(0.35 + 0.45 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad pelaje")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.16),
                       label="Fibra matea")
    if dirt_p > 1e-4:
        rough = b.math("ADD", rough, b.math("MULTIPLY", dirt_p, 0.12))
    rough = b.clamp(rough, 0.05, 1.0, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.40
    res.normal_detail = normal
    res.detail_height = height
    res.anisotropic = b.value(min(1.0, aniso), label="Anisotropía del pelo")

    # Sheen / Velvet: el halo de las puntas iluminadas a contraluz.
    if sheen_p > 1e-4 and (ctx.on("use_sheen")):
        if compat.has_node("ShaderNodeBsdfVelvet"):
            # Velvet es la forma correcta de un halo de pelo en Blender 5.x,
            # pero se mezcla con el cierre principal en el ensamblador.
            res.extra["velvet_weight"] = b.value(min(1.0, sheen_p), label="Velvet")
            res.extra["velvet_color"] = b.rgb(ctx.c("Color puntas"),
                                              label="Color del halo")
        res.sheen_weight = b.value(min(1.0, sheen_p), label="Sheen del pelaje")
        res.sheen_roughness = 0.55
        res.sheen_tint = b.rgb(ctx.c("Color puntas"), label="Tinte del sheen")

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# ESCAMAS
# ---------------------------------------------------------------------------

def scales(ctx: RecipeContext) -> RecipeResult:
    """Placas de escamas con borde levantado y gradación."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    density = ctx.f("Densidad", 60.0)
    gradation = ctx.f("Gradación", 0.5)
    plate_h = ctx.f("Altura de placa", 0.6)
    edge_p = ctx.f("Borde", 0.55)
    irregular = ctx.f("Irregularidad", 0.35)
    wear_p = ctx.f("Desgaste", 0.25)
    mottle_p = ctx.f("Manchado", 0.25)
    iridescence = ctx.f("Iridiscencia", 0.0)
    wet_p = ctx.f("Humedad", 0.0)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Gradación de tamaño: las escamas son más pequeñas hacia las
    #    extremidades.  Se usa la posición en el objeto para variar la escala
    #    del Voronoi (no se puede variar la escala por píxel, así que se hacen
    #    dos capas y se cruzan con una máscara).
    # ------------------------------------------------------------------
    scale_a = max(2.0, density)
    scale_b = max(4.0, density * 2.1)
    warp = None
    if irregular > 1e-4:
        warp = texlib.warp(b, coords, amount=irregular * 0.35,
                           warp_scale=max(1.0, density * 0.05),
                           seed_offset=(41.0, 17.0, 83.0),
                           label="Irregularidad de escamas")
    src = warp if warp is not None else coords

    plates_a = texlib.voronoi_cells(b, src, scale=scale_a, smoothness=0.06,
                                    feature="F1", randomness=1.0,
                                    seed_offset=(7.0, 23.0, 5.0),
                                    label="Escamas grandes")
    plates_b = texlib.voronoi_cells(b, src, scale=scale_b, smoothness=0.06,
                                    feature="F1", randomness=1.0,
                                    seed_offset=(71.0, 13.0, 29.0),
                                    label="Escamas pequeñas")

    plates: Any = plates_a
    if gradation > 1e-4 and plates_a is not None and plates_b is not None:
        zone = _ventral_mask(ctx)
        if zone is None:
            # sin eje Z fiable: usar ruido para repartir tamaños
            zone = texlib.fbm(b, coords, scale=ctx.detail_scale(2.0), detail=3.0,
                              roughness=0.5, seed_offset=(19.0, 53.0, 7.0),
                              label="Zona de tamaño")
        if zone is not None:
            mix_f = b.math("MULTIPLY", zone, gradation, label="Gradación")
            # cruzamos las dos capas: a mayor mezcla, más peso de la escama fina
            plates = b.math("ADD",
                            b.math("MULTIPLY", plates_a, b.math("SUBTRACT", 1.0, mix_f)),
                            b.math("MULTIPLY", plates_b, mix_f),
                            label="Escamas mezcladas")

    edges = texlib.cellular(b, src, scale=scale_a, smoothness=0.09,
                            edge_width=0.28, invert=True,
                            seed_offset=(7.0, 23.0, 5.0),
                            label="Borde de escama")

    # ------------------------------------------------------------------
    # 2. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if plates is not None:
        # domo de la placa: el centro sobresale, el borde cae
        dome = b.map_range(plates, 0.0, 0.55, 1.0, 0.0,
                           interpolation="SMOOTHSTEP", clamp=True,
                           label="Domo de escama")
        if dome is not None:
            layers.append((dome, 0.0011 * plate_h * detail))
    if edges is not None and edge_p > 1e-4:
        layers.append((edges, 0.00055 * edge_p * detail))
    # desgaste en el centro de la placa
    if wear_p > 1e-4 and plates is not None:
        worn = texlib.crackle(b, coords, scale=ctx.detail_scale(scale_a * 2.2),
                              width=0.05 * wear_p, warp_amount=0.6,
                              seed_offset=(97.0, 31.0, 11.0), label="Desgaste")
        if worn is not None:
            layers.append((worn, -0.00075 * wear_p * detail))
    # grano de queratina
    grain = _fiber_layer(ctx, coords, scale=520.0, weight=0.00016 * detail)
    if grain is not None:
        layers.append((grain, 1.0))

    height = ctx.micro_detail(layers, label="Altura de escamas")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de escamas") if height else None

    # ------------------------------------------------------------------
    # 3. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Escama")
    color: Any = base
    if color is not None and plates is not None:
        per_scale = b.map_range(plates, 0.0, 0.7, 0.85, 1.18, clamp=True,
                                label="Tono por escama")
        varied = b.mix_rgb("MULTIPLY", 0.7, color,
                           b.math("MULTIPLY", color, per_scale), label="Escamas variadas")
        if varied is not None:
            color = varied
    if color is not None and edges is not None:
        joint = b.mix_rgb("MIX", b.math("MULTIPLY", edges, edge_p * 1.3),
                          color, ctx.c("Color borde"), label="Bordes")
        if joint is not None:
            color = joint

    # moteado grande (camuflaje)
    if color is not None and mottle_p > 1e-4:
        blotch = texlib.fbm(b, coords, scale=ctx.detail_scale(3.2), detail=5.0,
                            roughness=0.6, seed_offset=(67.0, 7.0, 41.0),
                            label="Moteado")
        if blotch is not None:
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", blotch, mottle_p * 0.75),
                             color, (0.55, 0.60, 0.50, 1.0), label="Moteado aplicado")
            if dark is not None:
                color = dark

    # vientre claro
    belly = _ventral_mask(ctx)
    if color is not None and belly is not None:
        pale = b.mix_rgb("MIX", b.math("MULTIPLY", belly, ctx.f("Vientre", 0.35)),
                         color, ctx.c("Color vientre"), label="Vientre")
        if pale is not None:
            color = pale

    cavity = ctx.cavity(radius=0.005, label="Cavidad de escamas")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.6),
                          color, (0.22, 0.28, 0.18, 1.0), label="Juntas")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.g("color_saturation", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 4. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.32)
    rough: Any = b.value(0.18 + 0.55 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad escama")
    if plates is not None:
        # el centro de la placa se pule con el roce; el borde es más mate
        rough = b.math("ADD", rough, b.math("MULTIPLY", plates, -0.10),
                       label="Placa pulida")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.20),
                       label="Relieve matea")
    if wet_p > 1e-4:
        rough = b.math("MULTIPLY", rough, 1.0 - 0.65 * wet_p, label="Mojado")
    rough = b.clamp(rough, 0.02, 0.98, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.5
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.53

    if iridescence > 1e-4 and ctx.on("use_thin_film"):
        film: Any = b.value(480.0, label="Película fina")
        if plates is not None:
            film = b.map_range(plates, 0.0, 0.8, 380.0, 620.0, clamp=True,
                               label="Película por escama")
        res.thin_film_thickness = b.clamp(film, 100.0, 1000.0)
        res.thin_film_ior = b.value(min(2.0, 1.35 + iridescence * 0.4),
                                    label="IOR película")

    if wet_p > 1e-3 and ctx.on("use_coat"):
        res.coat_weight = b.value(min(1.0, wet_p * 0.9), label="Mojado")
        res.coat_roughness = 0.015
        res.coat_ior = 1.333

    ctx.result = res
    return res


def _fiber_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                 weight: float) -> Optional[NodeOut]:
    fib = texlib.fiber(ctx.b, coords, scale=ctx.detail_scale(scale),
                       anisotropy=0.9, use_gabor=ctx.on("use_gabor"),
                       seed_offset=(13.0, 47.0, 7.0), label="Fibra")
    if fib is None:
        return None
    return ctx.b.math("MULTIPLY", ctx.b.math("SUBTRACT", fib, 0.5), weight,
                      label="Fibra ponderada")


# ---------------------------------------------------------------------------
# PLUMAS
# ---------------------------------------------------------------------------

def feathers(ctx: RecipeContext) -> RecipeResult:
    """Plumas con raquis, barbas y teselación de plumas de cobertura."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    barbs_p = ctx.f("Barbas", 0.7)
    rachis_p = ctx.f("Raquis", 0.6)
    tiling = ctx.f("Teselación", 18.0)
    overlap = ctx.f("Solape", 0.45)
    iridescence = ctx.f("Iridiscencia", 0.0)
    film_nm = ctx.f("Grosor película", 380.0)
    sheen_p = ctx.f("Sheen", 0.4)
    wear_p = ctx.f("Desgaste", 0.2)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Teselación de plumas de cobertura (se solapan como tejas)
    # ------------------------------------------------------------------
    # Cada "pluma" es una celda Voronoi alargada en la dirección del raquis.
    stretched = texlib.stretch(b, coords, 1.0, max(1.5, 3.2 * (1.0 - overlap)), 1.0,
                               label="Alargar pluma")
    src = stretched if stretched is not None else coords
    feather = texlib.voronoi_cells(b, src, scale=max(1.0, tiling),
                                   smoothness=0.18, feature="F1", randomness=0.9,
                                   seed_offset=(11.0, 53.0, 7.0),
                                   label="Plumas de cobertura")
    feather_edge = texlib.cellular(b, src, scale=max(1.0, tiling), smoothness=0.22,
                                   edge_width=0.30, invert=True,
                                   seed_offset=(11.0, 53.0, 7.0),
                                   label="Borde de pluma")

    # ------------------------------------------------------------------
    # 2. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if feather is not None:
        # la pluma se curva hacia arriba en el centro y cae en el borde
        dome = b.map_range(feather, 0.0, 0.6, 1.0, 0.0,
                           interpolation="SMOOTHSTEP", clamp=True,
                           label="Curva de pluma")
        if dome is not None:
            layers.append((dome, 0.0013 * detail))
    if feather_edge is not None:
        layers.append((feather_edge, -0.00095 * detail))

    # raquis: línea central en relieve
    rachis: Any = None
    if rachis_p > 1e-4 and feather is not None:
        # el raquis sigue el eje de alargamiento: distancia al centro de la celda
        rachis = b.map_range(feather, 0.0, 0.18, 1.0, 0.0, clamp=True,
                             label="Raquis")
        layers.append((rachis, 0.00105 * rachis_p * detail))

    # barbas: estría fina perpendicular al raquis
    if barbs_p > 1e-4:
        barb = texlib.fiber(b, src, scale=ctx.detail_scale(560.0), anisotropy=0.95,
                            use_gabor=ctx.on("use_gabor"),
                            seed_offset=(31.0, 17.0, 5.0), label="Barbas")
        if barb is not None:
            layers.append((b.math("SUBTRACT", barb, 0.5), 0.00022 * barbs_p * detail))

    if wear_p > 1e-4:
        torn = texlib.scratch(b, coords, scale=ctx.detail_scale(240.0),
                              density=wear_p * 0.3, length=8.0, angle_deg=80.0,
                              seed_offset=(67.0, 23.0, 11.0), label="Plumas rotas")
        if torn is not None:
            layers.append((torn, -0.00070 * wear_p * detail))

    height = ctx.micro_detail(layers, label="Altura de plumas")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de plumas") if height else None

    # ------------------------------------------------------------------
    # 3. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Pluma")
    color: Any = base
    if color is not None and feather is not None:
        per_feather = b.map_range(feather, 0.0, 0.8, 0.82, 1.20, clamp=True,
                                  label="Tono por pluma")
        varied = b.mix_rgb("MULTIPLY", 0.6, color,
                           b.math("MULTIPLY", color, per_feather), label="Plumas variadas")
        if varied is not None:
            color = varied
    if color is not None and rachis is not None:
        shaft = b.mix_rgb("MIX", b.math("MULTIPLY", rachis, 0.85),
                          color, ctx.c("Color raquis"), label="Raquis claro")
        if shaft is not None:
            color = shaft
    if color is not None and feather_edge is not None:
        tip = b.mix_rgb("MIX", b.math("MULTIPLY", feather_edge, 0.9),
                        color, ctx.c("Color puntas"), label="Bordes oscuros")
        if tip is not None:
            color = tip

    cavity = ctx.cavity(radius=0.006, label="Cavidad de plumas")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.5),
                          color, (0.26, 0.28, 0.32, 1.0), label="Sombra entre plumas")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.g("color_saturation", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 4. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.42)
    rough: Any = b.value(0.25 + 0.5 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad pluma")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.18))
    rough = b.clamp(rough, 0.03, 1.0, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.45
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.53

    if iridescence > 1e-4 and ctx.on("use_thin_film"):
        film: Any = b.value(float(film_nm), label="Película")
        if feather is not None:
            film = b.map_range(feather, 0.0, 0.9,
                               film_nm * 0.7, film_nm * 1.4, clamp=True,
                               label="Película por pluma")
        res.thin_film_thickness = b.clamp(film, 100.0, 1000.0)
        res.thin_film_ior = b.value(min(2.2, 1.4 + iridescence * 0.5),
                                    label="IOR película")

    if sheen_p > 1e-4 and ctx.on("use_sheen"):
        res.sheen_weight = b.value(min(1.0, sheen_p), label="Plumón")
        res.sheen_roughness = 0.7
        res.sheen_tint = b.rgb(ctx.c("Color base"), label="Tinte plumón")

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# HOCICO / TRUFA
# ---------------------------------------------------------------------------

def snout(ctx: RecipeContext) -> RecipeResult:
    """Trufa húmeda con punteado, philtrum y fosas nasales."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    mottle_p = ctx.f("Moteado", 0.35)
    stipple_p = ctx.f("Punteado", 0.8)
    philtrum_p = ctx.f("Surco", 0.55)
    nostril_p = ctx.f("Orificios", 0.6)
    wet_p = ctx.f("Humedad", 0.7)
    dry_edge = ctx.f("Borde seco", 0.3)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Altura: punteado grueso de la trufa
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    stipple: Any = None
    if stipple_p > 1e-4:
        stipple = texlib.stipple(b, coords, scale=ctx.detail_scale(120.0),
                                 density=0.38, softness=0.42,
                                 seed_offset=(23.0, 61.0, 7.0), label="Punteado")
        if stipple is not None:
            layers.append((stipple, 0.00042 * stipple_p * detail))
    # surcos entre lóbulos
    lobes = texlib.crackle(b, coords, scale=ctx.detail_scale(2.6),
                           width=0.10, warp_amount=0.7,
                           seed_offset=(71.0, 13.0, 41.0), label="Lóbulos")
    if lobes is not None:
        layers.append((lobes, -0.0016 * detail))

    # philtrum (surco central): banda vertical en el UV
    u, v = _uv_components(b, ctx)
    philtrum: Any = None
    if u is not None and philtrum_p > 1e-4:
        du = b.math("SUBTRACT", u, ctx.f("Centro del surco U", 0.5), label="ΔU")
        ad = b.math("ABSOLUTE", du, 0.0)
        philtrum = b.map_range(ad, 0.0, ctx.f("Ancho del surco", 0.035), 1.0, 0.0,
                               interpolation="SMOOTHSTEP", clamp=True,
                               label="Philtrum")
        if philtrum is not None:
            layers.append((philtrum, -0.0011 * philtrum_p * detail))

    grain = _fiber_layer(ctx, coords, scale=340.0, weight=0.00012 * detail)
    if grain is not None:
        layers.append((grain, 1.0))

    height = ctx.micro_detail(layers, label="Altura del hocico")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del hocico") if height else None

    # ------------------------------------------------------------------
    # 2. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Trufa")
    color: Any = base
    if color is not None and mottle_p > 1e-4:
        pink = texlib.speckle_field(b, coords, scale=ctx.detail_scale(22.0),
                                    density=mottle_p, size=0.35,
                                    seed_offset=(41.0, 17.0, 83.0),
                                    label="Moteado rosado")
        if pink is not None:
            tinted = b.mix_rgb("MIX", b.math("MULTIPLY", pink, min(1.0, mottle_p * 2.0)),
                               color, ctx.c("Color rosado"), label="Moteado")
            if tinted is not None:
                color = tinted

    # fosas nasales muy oscuras
    if color is not None and nostril_p > 1e-4:
        nostril = texlib.stipple(b, coords, scale=ctx.detail_scale(4.5),
                                 density=0.55, softness=0.7,
                                 seed_offset=(5.0, 91.0, 29.0), label="Fosas")
        if nostril is not None:
            dark = b.mix_rgb("MIX", b.math("MULTIPLY", nostril, nostril_p),
                             color, (0.02, 0.015, 0.015, 1.0), label="Fosas nasales")
            if dark is not None:
                color = dark

    # surco oscurecido
    if color is not None and philtrum is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", philtrum, 0.5),
                          color, (0.45, 0.32, 0.32, 1.0), label="Surco")
        if shade is not None:
            color = shade

    # borde seco: la piel alrededor de la trufa es mate y más clara
    if color is not None and dry_edge > 1e-4:
        edge_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(3.5), detail=4.0,
                                roughness=0.6, seed_offset=(97.0, 7.0, 53.0),
                                label="Borde seco")
        if edge_noise is not None:
            mask = b.map_range(edge_noise, 0.55, 0.9, 0.0, 1.0, clamp=True)
            dry = b.mix_rgb("MIX", b.math("MULTIPLY", mask, dry_edge),
                            color, (0.42, 0.30, 0.28, 1.0), label="Borde seco")
            if dry is not None:
                color = dry

    cavity = ctx.cavity(radius=0.004, label="Cavidad del hocico")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.45),
                          color, (0.28, 0.20, 0.20, 1.0), label="Surcos")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.18)
    rough: Any = b.value(0.10 + 0.45 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad trufa")
    if stipple is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", stipple, 0.10),
                       label="Punteado matea")
    if wet_p > 1e-4:
        rough = b.math("MULTIPLY", rough, 1.0 - 0.75 * wet_p, label="Mojado")
    rough = b.clamp(rough, 0.008, 0.95, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = b.value(0.5 + 0.3 * wet_p, label="Specular húmedo")
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.4) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.45, sss_w * 0.45), label="SSS del hocico")
        res.sss_radius = (0.0028, 0.0010, 0.0008)
        res.sss_color = b.rgb((0.72, 0.22, 0.20, 1.0), label="Vascular")

    if wet_p > 1e-3 and ctx.on("use_coat"):
        res.coat_weight = b.value(min(1.0, wet_p * 0.8), label="Mucosidad")
        res.coat_roughness = 0.02
        res.coat_ior = 1.334

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# ANFIBIO / VISCOSO
# ---------------------------------------------------------------------------

def amphibian(ctx: RecipeContext) -> RecipeResult:
    """Piel húmeda granulada con mucosidad y manchas de aviso."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    spots_p = ctx.f("Manchas", 0.35)
    granules_p = ctx.f("Gránulos", 0.7)
    glands_p = ctx.f("Glándulas", 0.3)
    mucus_p = ctx.f("Mucosidad", 0.75)
    trans_p = ctx.f("Translucidez", 0.35)
    iridescence = ctx.f("Iridiscencia", 0.0)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if granules_p > 1e-4:
        gran = texlib.stipple(b, coords, scale=ctx.detail_scale(190.0),
                              density=0.36, softness=0.40,
                              seed_offset=(17.0, 43.0, 71.0), label="Gránulos")
        if gran is not None:
            layers.append((gran, 0.00048 * granules_p * detail))
    if glands_p > 1e-4:
        glands = texlib.stipple(b, coords, scale=ctx.detail_scale(26.0),
                                density=0.42, softness=0.62,
                                seed_offset=(83.0, 11.0, 29.0), label="Glándulas")
        if glands is not None:
            layers.append((glands, 0.0016 * glands_p * detail))
    # pliegues dorsales
    folds = texlib.ridged(b, coords, scale=ctx.detail_scale(5.5), detail=4.0,
                          roughness=0.55, sharpness=1.3,
                          seed_offset=(53.0, 7.0, 19.0), label="Pliegues")
    if folds is not None:
        layers.append((b.math("SUBTRACT", 1.0, folds), 0.0012 * detail))

    # gotas de mucosidad: abultan y brillan
    mucus_drops: Any = None
    if mucus_p > 1e-4:
        mucus_drops = texlib.stipple(b, coords, scale=ctx.detail_scale(46.0),
                                     density=0.22 * mucus_p, softness=0.55,
                                     seed_offset=(37.0, 91.0, 5.0),
                                     label="Gotas de mucus")
        if mucus_drops is not None:
            layers.append((mucus_drops, 0.00055 * mucus_p * detail))

    height = ctx.micro_detail(layers, label="Altura de anfibio")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de anfibio") if height else None

    # ------------------------------------------------------------------
    # 2. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Piel")
    color: Any = base
    if color is not None:
        mottle = texlib.fbm(b, coords, scale=ctx.detail_scale(4.0), detail=5.0,
                            roughness=0.6, seed_offset=(67.0, 23.0, 11.0),
                            label="Moteado")
        if mottle is not None:
            mod = b.map_range(mottle, 0.30, 0.78, 0.80, 1.25, clamp=True)
            varied = b.mix_rgb("MULTIPLY", 0.7, color,
                               b.math("MULTIPLY", color, mod), label="Piel variada")
            if varied is not None:
                color = varied

    if color is not None and spots_p > 1e-4:
        spots = texlib.speckle_field(b, coords, scale=ctx.detail_scale(16.0),
                                     density=spots_p, size=0.40,
                                     seed_offset=(29.0, 71.0, 17.0),
                                     label="Manchas de aviso")
        if spots is not None:
            tinted = b.mix_rgb("MIX", b.math("MULTIPLY", spots, min(1.0, spots_p * 2.5)),
                               color, ctx.c("Color manchas"), label="Manchas")
            if tinted is not None:
                color = tinted

    belly = _ventral_mask(ctx)
    if color is not None and belly is not None:
        pale = b.mix_rgb("MIX", b.math("MULTIPLY", belly, ctx.f("Vientre", 0.5)),
                         color, ctx.c("Color vientre"), label="Vientre")
        if pale is not None:
            color = pale

    cavity = ctx.cavity(radius=0.005, label="Cavidad de anfibio")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.5),
                          color, (0.16, 0.24, 0.18, 1.0), label="Pliegues")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.g("color_saturation", 1.0) * 1.08)
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.09)
    rough: Any = b.value(0.06 + 0.42 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad anfibio")
    if mucus_drops is not None:
        # las gotas son casi espejo
        rough = b.math("ADD", rough, b.math("MULTIPLY", mucus_drops, -0.05 * mucus_p),
                       label="Gotas brillantes")
    if granules_p > 1e-4:
        rough = b.math("ADD", rough, b.math("MULTIPLY", granules_p, 0.05),
                       label="Gránulos matean")
    rough = b.clamp(rough, 0.004, 0.95, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = b.value(0.55 + 0.35 * mucus_p, label="Specular húmedo")
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.42

    if trans_p > 1e-4:
        res.transmission = b.value(min(0.35, trans_p * 0.35), label="Translucidez")

    sss_w = ctx.f("SSS", 0.8) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.55, sss_w * 0.55), label="SSS anfibio")
        res.sss_radius = (0.0042, 0.0022, 0.0014)
        res.sss_color = b.rgb((0.52, 0.72, 0.38, 1.0), label="Bajo la piel")

    if iridescence > 1e-4 and ctx.on("use_thin_film"):
        res.thin_film_thickness = b.value(460.0, label="Película")
        res.thin_film_ior = b.value(min(2.0, 1.35 + iridescence * 0.4),
                                    label="IOR película")

    if mucus_p > 1e-3 and ctx.on("use_coat"):
        coat: Any = b.value(min(1.0, mucus_p * 0.85), label="Mucus")
        if mucus_drops is not None:
            coat = b.math("MULTIPLY_ADD", mucus_drops, 0.5, coat, label="Gotas")
            coat = b.clamp(coat, 0.0, 1.0)
        res.coat_weight = coat
        res.coat_roughness = 0.008
        res.coat_ior = 1.334

    ctx.result = res
    return res
