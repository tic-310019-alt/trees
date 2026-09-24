# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Recetas de queratina: uñas, pelo, pezuñas/cuernos y caparazón.

La queratina tiene una firma común (fibra longitudinal, translucidez en los
bordes finos, desgaste en las puntas) y diferencias de forma:

**Uñas.** Placa translúcida sobre el lecho vascular: la lúnula es la matriz
visible, el borde libre es blanco porque ya no hay lecho debajo, y las crestas
longitudinales son las estrías reales de la placa.

**Pelo.** Cuero cabelludo con folículos + BSDF de pelo por melanina con lóbulos
R/TT/TRT (rubor, transmisión y reflejo secundario), canas y mechones aclarados.

**Pezuñas y cuernos.** Anillos de crecimiento irregulares + fibra longitudinal +
grietas + punta desgastada y más oscura + barro en la base.

**Caparazón.** Placas (scutes) con junta oscura, nácar iridiscente por película
fina, anillos de crecimiento, erosión y verdín.
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
    melanin_ramp,
    saturate,
)

__all__ = ("nails", "hair", "hooves", "shell")


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


def _object_component(b, ctx: RecipeContext, axis: str) -> Optional[Any]:
    coords = ctx.coords("Object", scaled=False)
    if coords is None:
        return None
    sep = b.add("ShaderNodeSeparateXYZ", label=f"Eje {axis}")
    if sep is None:
        return None
    b.link(coords, in_socket(sep, "Vector", 0))
    return out_socket(sep, axis.upper(), 0)


def _keratin_fiber(ctx: RecipeContext, coords: Any, *, scale: float,
                   anisotropy: float = 0.9, label: str = "Fibra"
                   ) -> Optional[NodeOut]:
    return texlib.fiber(ctx.b, coords, scale=ctx.detail_scale(scale),
                        anisotropy=anisotropy, use_gabor=ctx.on("use_gabor"),
                        seed_offset=(13.0, 47.0, 7.0), label=label)


def _wear_tip(ctx: RecipeContext, *, axis: str = "Z", lo: float = 0.0,
              hi: float = 1.0) -> Optional[NodeOut]:
    """Máscara 0 en la base → 1 en la punta, usando el eje del objeto."""
    b = ctx.b
    comp = _object_component(b, ctx, axis)
    if comp is None:
        return None
    if hi < lo:
        lo, hi = hi, lo
    if abs(hi - lo) < 1e-5:
        hi = lo + 1.0
    return b.map_range(comp, lo, hi, 0.0, 1.0, interpolation="SMOOTHSTEP",
                       clamp=True, label="Base → punta")


# ---------------------------------------------------------------------------
# UÑAS
# ---------------------------------------------------------------------------

def nails(ctx: RecipeContext) -> RecipeResult:
    """Placa ungueal translúcida con lecho, lúnula y borde libre."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    u, v = _uv_components(b, ctx)
    if coords is None or v is None:
        ctx.result = res
        return res

    tone = ctx.f("Tono", 0.55)
    free_edge = ctx.f("Borde libre", 0.28)
    lunula_p = ctx.f("Lúnula", 0.35)
    ridges_p = ctx.f("Crestas", 0.35)
    cuticle_p = ctx.f("Cutícula", 0.5)
    trans_p = ctx.f("Translucidez", 0.45)
    wear_p = ctx.f("Desgaste", 0.15)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Zonificación a lo largo de la uña (V)
    # ------------------------------------------------------------------
    # Borde libre: la parte distal (V alta) sin lecho debajo → blanca.
    edge_start = 1.0 - max(0.02, min(0.95, free_edge))
    edge_mask = b.map_range(v, edge_start - 0.04, edge_start + 0.03, 0.0, 1.0,
                            interpolation="SMOOTHSTEP", clamp=True,
                            label="Borde libre")
    # Lúnula: media luna en la base.
    lunula_center = ctx.f("Centro lúnula V", 0.16)
    lunula_rad = ctx.f("Radio lúnula", 0.17)
    du = b.math("SUBTRACT", u, 0.5, label="ΔU") if u is not None else None
    dv = b.math("SUBTRACT", v, lunula_center, label="ΔV")
    lunula: Any = None
    if du is not None:
        du2 = b.math("MULTIPLY", du, du)
        dv2 = b.math("MULTIPLY", dv, dv)
        d = b.math("SQRT", b.math("ADD", du2, dv2), 0.0, label="Distancia")
        lunula = b.map_range(d, lunula_rad * 0.55, lunula_rad, 1.0, 0.0,
                             interpolation="SMOOTHSTEP", clamp=True,
                             label="Lúnula")
    # Cutícula: banda en la base.
    cuticle = b.map_range(v, 0.0, ctx.f("Ancho cutícula", 0.055), 1.0, 0.0,
                          interpolation="SMOOTHSTEP", clamp=True,
                          label="Cutícula")

    # ------------------------------------------------------------------
    # 2. Color
    # ------------------------------------------------------------------
    ramp = b.color_ramp([
        (0.00, ctx.c("Color lecho")),
        (0.55, ctx.c("Color lecho")),
        (1.00, (0.92, 0.86, 0.82, 1.0)),
    ], interpolation="LINEAR", label="Lecho ungueal")
    color: Any = ramp
    if ramp is not None:
        b.link(b.value(max(0.0, min(1.0, tone)), label="Tono"),
               in_socket(ramp.node, "Fac", 0))

    # borde libre blanco
    if color is not None:
        white = b.mix_rgb("MIX", edge_mask, color, ctx.c("Color borde"),
                          label="Borde libre")
        if white is not None:
            color = white
    # lúnula más pálida y opaca
    if color is not None and lunula is not None and lunula_p > 1e-4:
        pale = b.mix_rgb("MIX", b.math("MULTIPLY", lunula, lunula_p * 0.85),
                         color, ctx.c("Color lúnula"), label="Lúnula")
        if pale is not None:
            color = pale
    # cutícula: piel muerta, ligeramente grisácea y desaturada
    if color is not None and cuticle_p > 1e-4:
        dead = b.mix_rgb("MIX", b.math("MULTIPLY", cuticle, cuticle_p * 0.7),
                         color, (0.78, 0.68, 0.62, 1.0), label="Cutícula")
        if dead is not None:
            color = dead

    # veteado sanguíneo bajo la placa (se ve a través)
    if trans_p > 1e-4:
        blood = texlib.vein_network(b, coords, scale=ctx.detail_scale(26.0),
                                    thickness=0.10, branching=0.5,
                                    warp_amount=0.5,
                                    seed_offset=(67.0, 11.0, 23.0),
                                    label="Lecho vascular")
        if blood is not None and color is not None:
            mask = b.math("MULTIPLY", blood,
                          b.math("SUBTRACT", 1.0, edge_mask), label="Sólo bajo placa")
            tinted = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", mask, trans_p * 0.5),
                               color, (1.0, 0.66, 0.62, 1.0), label="Sangre")
            if tinted is not None:
                color = tinted

    # manchas / golpes en la punta
    if wear_p > 1e-4:
        spots = texlib.speckle_field(b, coords, scale=ctx.detail_scale(55.0),
                                     density=wear_p * 0.5, size=0.18,
                                     seed_offset=(31.0, 59.0, 7.0),
                                     label="Golpes")
        if spots is not None and color is not None:
            tinted = b.mix_rgb("MULTIPLY",
                               b.math("MULTIPLY", b.math("MULTIPLY", spots, edge_mask),
                                      wear_p * 1.4),
                               color, (0.80, 0.76, 0.70, 1.0), label="Desgaste")
            if tinted is not None:
                color = tinted

    cavity = ctx.cavity(radius=0.0025, label="Cavidad de uña")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.35),
                          color, (0.60, 0.52, 0.50, 1.0), label="Bordes")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. Altura: crestas longitudinales
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if ridges_p > 1e-4:
        ridge = texlib.striations(b, coords, count=ctx.detail_scale(38.0),
                                  wobble=0.05, thickness=0.55, axis="V",
                                  seed_offset=(5.0, 71.0, 17.0),
                                  label="Crestas longitudinales")
        if ridge is not None:
            layers.append((ridge, 0.00022 * ridges_p * detail))
    if cuticle_p > 1e-4:
        layers.append((cuticle, 0.00030 * cuticle_p * detail))
    micro = texlib.fbm(b, coords, scale=ctx.detail_scale(1400.0), detail=5.0,
                       roughness=0.5, seed_offset=(19.0, 43.0, 3.0),
                       label="Micro queratina")
    if micro is not None:
        layers.append((micro, 0.000018 * detail))

    height = ctx.micro_detail(layers, label="Altura de uña")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de uña") if height else None

    # ------------------------------------------------------------------
    # 4. Rugosidad / transmisión
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.10)
    rough: Any = b.value(0.22 - 0.18 * base_rough, label="Rugosidad uña")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.14),
                       label="Cresta matea")
    if cuticle_p > 1e-4:
        rough = b.math("ADD", rough, b.math("MULTIPLY", cuticle, cuticle_p * 0.35),
                       label="Cutícula matea")
    rough = b.clamp(rough, 0.006, 0.9, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = b.value(min(1.4, 0.45 + 0.5 * ctx.f("Brillo", 1.0) * 0.5),
                           label="Specular uña")
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.54

    if trans_p > 1e-4:
        # la placa deja pasar luz sobre todo en el borde libre
        t: Any = b.value(min(0.4, trans_p * 0.4), label="Transmisión")
        boost = b.math("MULTIPLY", edge_mask, trans_p * 0.35, label="Borde translúcido")
        t = b.clamp(b.math("ADD", t, boost), 0.0, 0.85, label="Transmisión uña")
        res.transmission = t

    sss_w = ctx.g("sss_scale", 1.0) * 0.35
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.3, sss_w * 0.3), label="SSS uña")
        res.sss_radius = (0.0020, 0.0010, 0.0008)
        res.sss_color = b.rgb((0.84, 0.46, 0.42, 1.0), label="Lecho")

    if ctx.on("use_coat"):
        gloss = ctx.f("Brillo", 1.0)
        res.coat_weight = b.clamp(b.math("MULTIPLY",
                                         b.math("SUBTRACT", 1.0, cuticle),
                                         0.35 * gloss), 0.0, 0.9,
                                  label="Barniz de la uña")
        res.coat_roughness = 0.02
        res.coat_ior = 1.54

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# PELO Y CUERO CABELLUDO
# ---------------------------------------------------------------------------

#: Color del pelo por melanina (eumelanina): rubio → castaño → moreno → negro.
HAIR_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.76, 0.58, 0.30)),   # rubio
    (0.20, (0.44, 0.26, 0.11)),   # rubio oscuro
    (0.42, (0.18, 0.10, 0.045)),  # castaño
    (0.65, (0.070, 0.040, 0.024)),# moreno
    (0.85, (0.022, 0.014, 0.011)),# negro
    (1.00, (0.008, 0.006, 0.005)),
)


def hair(ctx: RecipeContext) -> RecipeResult:
    """Cuero cabelludo con folículos y fibra de pelo."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    melanin = ctx.f("Melanina", 0.72)
    red_mel = ctx.f("Melanina roja", 0.12)
    variation = ctx.f("Variación", 0.30)
    grey_p = ctx.f("Canas", 0.0)
    rough_p = ctx.f("Rugosidad", 0.32)
    aniso = ctx.f("Anisotropía", 0.85)
    follicles_p = ctx.f("Folículos", 0.5)
    tips_p = ctx.f("Aclarado de puntas", 0.25)
    oil_p = ctx.f("Grasa", 0.25)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Color de la fibra
    # ------------------------------------------------------------------
    ramp = b.color_ramp([(p, (r, g, bl, 1.0)) for p, (r, g, bl) in HAIR_STOPS],
                        interpolation="LINEAR", label="Melanina del pelo")
    color: Any = ramp
    mel_val = b.value(max(0.0, min(1.0, melanin)), label="Melanina")
    if ramp is not None and mel_val is not None:
        b.link(mel_val, in_socket(ramp.node, "Fac", 0))

    # feomelanina (rojizo): empuja el tono hacia el cobre
    if color is not None and red_mel > 1e-4:
        red = b.mix_rgb("MIX", red_mel * 0.75, color,
                        (0.42, 0.13, 0.035, 1.0), label="Feomelanina")
        if red is not None:
            color = red

    # mechones de distinto tono
    if color is not None and variation > 1e-4:
        strand_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(28.0),
                                  detail=5.0, roughness=0.55,
                                  seed_offset=(37.0, 3.0, 89.0),
                                  label="Mechones")
        if strand_noise is not None:
            mod = b.map_range(strand_noise, 0.30, 0.75, 0.70, 1.45, clamp=True,
                              label="Variación de mechón")
            varied = b.mix_rgb("MULTIPLY", variation, color,
                               b.math("MULTIPLY", color, mod), label="Pelo variado")
            if varied is not None:
                color = varied

    # canas: mechones blancos dispersos
    if color is not None and grey_p > 1e-4:
        grey_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(18.0),
                                detail=4.0, roughness=0.6,
                                seed_offset=(83.0, 29.0, 11.0), label="Canas")
        if grey_noise is not None:
            grey_mask = b.map_range(grey_noise, 1.0 - grey_p * 0.9, 1.0,
                                    0.0, 1.0, clamp=True, label="Máscara de canas")
            greyed = b.mix_rgb("MIX", grey_mask, color,
                               (0.78, 0.78, 0.80, 1.0), label="Canas")
            if greyed is not None:
                color = greyed

    # puntas aclaradas por el sol (la melanina se degrada en la punta)
    tips = _wear_tip(ctx, axis=ctx.p("Eje del pelo", "Z"),
                     lo=ctx.f("Base del pelo", -0.5),
                     hi=ctx.f("Punta del pelo", 0.5))
    if color is not None and tips is not None and tips_p > 1e-4:
        bleached = b.mix_rgb("MIX", b.math("MULTIPLY", tips, tips_p),
                             color, ctx.c("Color puntas"), label="Puntas")
        if bleached is not None:
            color = bleached

    # tinte directo del usuario
    tint = ctx.c("Color")
    if color is not None and not all(abs(x - 1.0) < 1e-3 for x in tint[:3]):
        direct = b.mix_rgb("MIX", 0.35, color, tint, label="Tinte directo")
        if direct is not None:
            color = direct

    # ------------------------------------------------------------------
    # 2. Cuero cabelludo: folículos
    # ------------------------------------------------------------------
    scalp: Any = None
    if follicles_p > 1e-4:
        follicles = texlib.stipple(b, coords, scale=ctx.detail_scale(210.0),
                                   density=0.26, softness=0.38,
                                   seed_offset=(17.0, 61.0, 5.0),
                                   label="Folículos")
        if follicles is not None:
            scalp_color = b.rgb(ctx.c("Color cuero"), label="Cuero cabelludo")
            if scalp_color is not None:
                scalp = b.mix_rgb("MIX", b.math("MULTIPLY", follicles, 0.6),
                                  scalp_color, (0.30, 0.18, 0.14, 1.0),
                                  label="Folículo oscuro")

    # ------------------------------------------------------------------
    # 3. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if follicles_p > 1e-4:
        f = texlib.stipple(b, coords, scale=ctx.detail_scale(210.0), density=0.26,
                           softness=0.38, seed_offset=(17.0, 61.0, 5.0),
                           label="Relieve de folículos")
        if f is not None:
            layers.append((f, -0.00035 * follicles_p * detail))
    fib = _keratin_fiber(ctx, coords, scale=780.0, anisotropy=0.96,
                         label="Fibra del pelo")
    if fib is not None:
        layers.append((b.math("SUBTRACT", fib, 0.5), 0.00010 * detail))

    height = ctx.micro_detail(layers, label="Altura del pelo")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del pelo") if height else None

    # ------------------------------------------------------------------
    # 4. Rugosidad / anisotropía
    # ------------------------------------------------------------------
    rough_val = 0.18 + 0.5 * max(0.0, min(1.0, rough_p))
    rough: Any = b.value(rough_val, label="Rugosidad del pelo")
    if oil_p > 1e-4:
        # la grasa se acumula en la raíz
        tip_mask = _wear_tip(ctx, axis="Z", lo=-0.5, hi=0.5)
        if tip_mask is not None:
            root = b.map_range(tip_mask, 0.0, 0.35, 1.0, 0.0, clamp=True,
                               label="Raíz")
            if root is not None:
                rough = b.math("ADD", rough,
                               b.math("MULTIPLY", root, -0.18 * oil_p),
                               label="Raíz grasa")
    rough = b.clamp(rough, 0.03, 0.95, label="Rugosidad final")

    # ------------------------------------------------------------------
    # 5. Salida: BSDF de pelo si existe
    # ------------------------------------------------------------------
    if compat.has_node("ShaderNodeBsdfHairPrincipled"):
        hair_node = b.add("ShaderNodeBsdfHairPrincipled", label="BSDF de pelo")
        if hair_node is not None:
            cs = in_socket(hair_node, "Color", 0)
            if cs is not None and color is not None:
                b.link(color, cs)
            compat.set_sock(hair_node, "Melanin", max(0.0, min(1.0, melanin)))
            compat.set_sock(hair_node, "Melanin Redness", max(0.0, min(1.0, red_mel)))
            compat.set_sock(hair_node, "Roughness",
                            max(0.05, min(1.0, rough_p)))
            compat.set_sock(hair_node, "Radial Roughness",
                            max(0.05, min(1.0, rough_p * (1.25 - 0.5 * aniso))))
            compat.set_sock(hair_node, "Coat", 1.0)
            compat.set_sock(hair_node, "Random Color", min(1.0, variation))
            compat.set_sock(hair_node, "Random Roughness", min(1.0, variation * 0.7))
            compat.set_sock(hair_node, "Absorption Coefficient", 0.0)
            res.extra["surface"] = hair_node
            # Aun así rellenamos los canales: el bakeador los necesita.
    res.base_color = color if scalp is None else scalp
    res.extra["fiber_color"] = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.45
    res.normal_detail = normal
    res.detail_height = height
    res.anisotropic = b.value(min(1.0, aniso), label="Anisotropía")
    if ctx.on("use_sheen"):
        res.sheen_weight = b.value(0.25, label="Sheen del pelo")
        res.sheen_roughness = max(0.05, rough_p)
    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# PEZUÑAS Y CUERNOS
# ---------------------------------------------------------------------------

def hooves(ctx: RecipeContext) -> RecipeResult:
    """Queratina compacta con anillos de crecimiento y fibra."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    rings_count = ctx.f("Anillos", 14.0)
    irregular = ctx.f("Irregularidad", 0.5)
    fibers_p = ctx.f("Fibras", 0.6)
    cracks_p = ctx.f("Grietas", 0.25)
    wear_p = ctx.f("Desgaste", 0.35)
    trans_p = ctx.f("Translucidez", 0.2)
    dirt_p = ctx.f("Suciedad", 0.3)
    detail = ctx.f("Detalle", 1.0)

    tip = _wear_tip(ctx, axis=ctx.p("Eje del cuerno", "Z"),
                    lo=ctx.f("Base del cuerno", -0.5),
                    hi=ctx.f("Punta del cuerno", 0.5))

    # ------------------------------------------------------------------
    # 1. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    rings: Any = None
    if rings_count > 0.5:
        rings = texlib.growth_rings(b, coords, count=rings_count,
                                    irregularity=irregular, hardness=0.42,
                                    label="Anillos de crecimiento")
        if rings is not None:
            layers.append((rings, 0.0011 * detail))
    fib = _keratin_fiber(ctx, coords, scale=620.0, anisotropy=0.92,
                         label="Fibra de queratina")
    if fib is not None and fibers_p > 1e-4:
        layers.append((b.math("SUBTRACT", fib, 0.5), 0.00032 * fibers_p * detail))
    cracks: Any = None
    if cracks_p > 1e-4:
        cracks = texlib.crackle(b, coords, scale=ctx.detail_scale(6.5),
                                width=0.05 * cracks_p, warp_amount=0.55,
                                seed_offset=(41.0, 17.0, 83.0), label="Grietas")
        if cracks is not None:
            layers.append((cracks, -0.0014 * cracks_p * detail))
    # desgaste: la punta se pule y se desconcha
    if wear_p > 1e-4 and tip is not None:
        chip = texlib.crackle(b, coords, scale=ctx.detail_scale(22.0),
                              width=0.04 * wear_p, warp_amount=0.7,
                              seed_offset=(71.0, 5.0, 29.0), label="Desconchado")
        if chip is not None:
            masked = b.math("MULTIPLY", chip, tip, label="Sólo en la punta")
            layers.append((masked, -0.00090 * wear_p * detail))

    height = ctx.micro_detail(layers, label="Altura de queratina")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de queratina") if height else None

    # ------------------------------------------------------------------
    # 2. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Queratina")
    color: Any = base

    # los anillos alternan queratina clara y oscura
    if color is not None and rings is not None:
        banded = b.mix_rgb("MULTIPLY", 0.45, color,
                           b.map_range(rings, 0.0, 1.0, 0.78, 1.12, clamp=True,
                                       label="Bandas"), label="Bandas de crecimiento")
        if banded is not None:
            color = banded

    # base más clara, punta más oscura
    if color is not None and tip is not None:
        dark = b.mix_rgb("MIX", b.math("MULTIPLY", tip, 0.85),
                         color, ctx.c("Color punta"), label="Punta")
        if dark is not None:
            color = dark
        light = b.mix_rgb("MIX", b.math("MULTIPLY", b.math("SUBTRACT", 1.0, tip), 0.55),
                          color, ctx.c("Color raíz"), label="Raíz")
        if light is not None:
            color = light

    # grietas oscuras (sombra atrapada)
    if color is not None and cracks is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cracks, 0.8),
                          color, (0.24, 0.20, 0.17, 1.0), label="Grieta oscura")
        if shade is not None:
            color = shade

    # barro en la base
    if color is not None and dirt_p > 1e-4:
        mud = texlib.fbm(b, coords, scale=ctx.detail_scale(11.0), detail=5.0,
                         roughness=0.6, seed_offset=(23.0, 67.0, 11.0),
                         label="Barro")
        if mud is not None and tip is not None:
            zone = b.math("MULTIPLY",
                          b.map_range(mud, 0.42, 0.85, 0.0, 1.0, clamp=True),
                          b.math("SUBTRACT", 1.0, tip), label="Barro en la base")
            dirty = b.mix_rgb("MIX", b.math("MULTIPLY", zone, dirt_p),
                              color, (0.24, 0.19, 0.13, 1.0), label="Barro")
            if dirty is not None:
                color = dirty

    cavity = ctx.cavity(radius=0.008, label="Cavidad de queratina")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.5),
                          color, (0.34, 0.29, 0.24, 1.0), label="Surcos")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. Rugosidad
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.45)
    rough: Any = b.value(0.28 + 0.45 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad queratina")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.22),
                       label="Fibra matea")
    if wear_p > 1e-4 and tip is not None:
        # la punta desgastada se pule
        rough = b.math("ADD", rough, b.math("MULTIPLY", tip, -0.14 * wear_p),
                       label="Punta pulida")
    if dirt_p > 1e-4:
        rough = b.math("ADD", rough, b.math("MULTIPLY", dirt_p, 0.18),
                       label="Barro matea")
    rough = b.clamp(rough, 0.04, 0.98, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.42
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.53

    if trans_p > 1e-4 and tip is not None:
        # los bordes finos de la pezuña dejan pasar luz
        res.transmission = b.math("MULTIPLY", tip, min(0.3, trans_p * 0.35),
                                  label="Translucidez en la punta")

    sss_w = ctx.g("sss_scale", 1.0) * 0.25
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.25, sss_w * 0.25), label="SSS queratina")
        res.sss_radius = (0.0022, 0.0012, 0.0008)
        res.sss_color = b.rgb((0.62, 0.42, 0.26, 1.0), label="Queratina interna")

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# CAPARAZÓN
# ---------------------------------------------------------------------------

def shell(ctx: RecipeContext) -> RecipeResult:
    """Placas con nácar, anillos de crecimiento y verdín."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    plates = ctx.f("Placas", 10.0)
    nacre_p = ctx.f("Nácar", 0.4)
    film_nm = ctx.f("Grosor película", 520.0)
    rings_count = ctx.f("Anillos", 18.0)
    erosion_p = ctx.f("Erosión", 0.35)
    algae_p = ctx.f("Algas", 0.2)
    wet_p = ctx.f("Humedad", 0.0)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # 1. Placas (scutes)
    # ------------------------------------------------------------------
    plates_map = texlib.voronoi_cells(b, coords, scale=max(0.5, plates),
                                      smoothness=0.05, feature="F1",
                                      randomness=0.85,
                                      seed_offset=(7.0, 41.0, 13.0),
                                      label="Placas")
    edges = texlib.cellular(b, coords, scale=max(0.5, plates), smoothness=0.10,
                            edge_width=0.22, invert=True,
                            seed_offset=(7.0, 41.0, 13.0), label="Juntas")

    # ------------------------------------------------------------------
    # 2. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if plates_map is not None:
        # cada placa es un domo suave: F1 da la distancia al centro de la celda
        dome = b.map_range(plates_map, 0.0, 0.6, 1.0, 0.0,
                           interpolation="SMOOTHSTEP", clamp=True,
                           label="Domo de placa")
        if dome is not None:
            layers.append((dome, 0.0022 * detail))
    if edges is not None:
        layers.append((edges, -0.0016 * detail))
    if rings_count > 0.5:
        rings = texlib.growth_rings(b, coords, count=rings_count,
                                    irregularity=0.45, hardness=0.35,
                                    label="Anillos del caparazón")
        if rings is not None:
            layers.append((rings, 0.00055 * detail))
    if erosion_p > 1e-4:
        pit = texlib.crackle(b, coords, scale=ctx.detail_scale(14.0),
                             width=0.06 * erosion_p, warp_amount=0.6,
                             seed_offset=(97.0, 23.0, 5.0), label="Erosión")
        if pit is not None:
            layers.append((pit, -0.0011 * erosion_p * detail))
    grain = texlib.fbm(b, coords, scale=ctx.detail_scale(700.0), detail=5.0,
                       roughness=0.5, seed_offset=(31.0, 11.0, 67.0),
                       label="Grano del caparazón")
    if grain is not None:
        layers.append((grain, 0.000060 * detail))

    height = ctx.micro_detail(layers, label="Altura del caparazón")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del caparazón") if height else None

    # ------------------------------------------------------------------
    # 3. Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Placa")
    color: Any = base
    if color is not None and plates_map is not None:
        # cada placa tiene un tono ligeramente distinto (crecimiento no uniforme)
        per_plate = b.map_range(plates_map, 0.0, 1.0, 0.86, 1.16, clamp=True,
                                label="Tono por placa")
        varied = b.mix_rgb("MULTIPLY", 0.65, color,
                           b.math("MULTIPLY", color, per_plate), label="Placas variadas")
        if varied is not None:
            color = varied
    if color is not None and edges is not None:
        joint = b.mix_rgb("MIX", b.math("MULTIPLY", edges, 0.9),
                          color, ctx.c("Color borde"), label="Juntas")
        if joint is not None:
            color = joint

    # verdín / algas en las juntas y bordes
    if color is not None and algae_p > 1e-4 and edges is not None:
        algae_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(8.0), detail=5.0,
                                 roughness=0.6, seed_offset=(53.0, 7.0, 29.0),
                                 label="Algas")
        if algae_noise is not None:
            mask = b.math("MULTIPLY", edges,
                          b.map_range(algae_noise, 0.35, 0.8, 0.0, 1.0, clamp=True),
                          label="Zona de algas")
            green = b.mix_rgb("MIX", b.math("MULTIPLY", mask, algae_p),
                              color, (0.20, 0.34, 0.14, 1.0), label="Verdín")
            if green is not None:
                color = green

    # erosión aclara (queratina gastada)
    if color is not None and erosion_p > 1e-4:
        worn = texlib.fbm(b, coords, scale=ctx.detail_scale(5.5), detail=4.0,
                          roughness=0.6, seed_offset=(19.0, 83.0, 41.0),
                          label="Erosión color")
        if worn is not None:
            mask = b.map_range(worn, 0.5, 0.9, 0.0, 1.0, clamp=True)
            pale = b.mix_rgb("MIX", b.math("MULTIPLY", mask, erosion_p * 0.55),
                             color, (0.72, 0.66, 0.52, 1.0), label="Gastado")
            if pale is not None:
                color = pale

    cavity = ctx.cavity(radius=0.010, label="Cavidad del caparazón")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.55),
                          color, (0.22, 0.19, 0.14, 1.0), label="Juntas oscuras")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 4. Superficie
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.38)
    rough: Any = b.value(0.22 + 0.5 * max(0.0, min(1.0, base_rough)),
                         label="Rugosidad caparazón")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.18),
                       label="Relieve matea")
    if edges is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", edges, 0.22),
                       label="Juntas rugosas")
    if wet_p > 1e-4:
        rough = b.math("MULTIPLY", rough, 1.0 - 0.6 * wet_p, label="Mojado")
    rough = b.clamp(rough, 0.02, 0.98, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.5
    res.normal_detail = normal
    res.detail_height = height
    res.ior = 1.55

    # Nácar: iridiscencia por película fina (Blender 4.2+ / 5.x)
    if nacre_p > 1e-4 and ctx.on("use_thin_film"):
        # el grosor varía por placa: eso es lo que produce el arcoíris irregular
        thickness: Any = b.value(float(film_nm), label="Grosor película")
        if plates_map is not None:
            varied_film = b.map_range(plates_map, 0.0, 1.0,
                                      film_nm * 0.72, film_nm * 1.28, clamp=True,
                                      label="Película por placa")
            if varied_film is not None:
                thickness = varied_film
        if edges is not None:
            thickness = b.math("MULTIPLY_ADD", thickness,
                               b.math("SUBTRACT", 1.0, edges), 0.0,
                               label="Menos nácar en la junta")
        res.thin_film_thickness = b.clamp(thickness, 100.0, 1000.0,
                                          label="Grosor (nm)")
        res.thin_film_ior = b.value(min(2.2, 1.3 + nacre_p * 0.55),
                                    label="IOR de la película")
        pearl = b.rgb(ctx.c("Color nácar"), label="Nácar")
        if color is not None and pearl is not None:
            res.base_color = b.mix_rgb("OVERLAY", min(0.5, nacre_p * 0.6),
                                       color, pearl, label="Reflejo perlado")

    if wet_p > 1e-3 and ctx.on("use_coat"):
        res.coat_weight = b.value(min(1.0, wet_p * 0.85), label="Mojado")
        res.coat_roughness = 0.02
        res.coat_ior = 1.333

    ctx.result = res
    return res
