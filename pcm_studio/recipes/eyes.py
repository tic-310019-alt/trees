# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Recetas del ojo.

El ojo es la zona donde más se delata un material malo.  Aquí se construye con
la anatomía correcta:

**Esclerótica.** Blanco no es blanco: tiene un tinte azulado por la capa
vascular de debajo, venas que entran desde los ángulos y se ramifican, una
sombra limbal junto a la córnea (porque el limbo la tapa) y amarilleo con la
edad.  Todo en coordenadas radiales del globo, no del UV.

**Iris.** Se trabaja en coordenadas polares alrededor del eje frontal del globo
ocular (espacio de objeto normalizado), así el patrón es perfectamente radial y
no depende de cómo esté cortado el UV.  Capas: estroma con criptas (Voronoi
estirado radialmente), surcos de Brown (fibra radial), colarete en zigzag,
limbo oscuro, halo ámbar peripupilar y pupila con borde suave.  El color se
obtiene por melanina: azul grisáceo → verde → avellana → marrón, con el centro
más cálido que la periferia (que es lo que da la profundidad real).

**Córnea.** Capa transparente encima: IOR 1.376, rugosidad casi nula, un
``Coat`` para el lagrimal y un menisco en el borde del párpado.

**Ojo animal.** Igual que el humano pero con pupila elíptica/hendidura,
tapetum lucidum emisivo y fibra más densa.

**Cejas y pestañas.** Vello corto en tarjeta con alfa: BSDF de pelo si existe
(melanina + rugosidad longitudinal) y, si no, Principled con ``alpha clip``.
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
    contrast,
    saturate,
)

__all__ = ("sclera", "iris", "cornea", "animal_eye", "lashes")


# ---------------------------------------------------------------------------
# Coordenadas polares del globo ocular
# ---------------------------------------------------------------------------

def _eye_polar(ctx: RecipeContext, *, forward: Sequence[float] = (0.0, 1.0, 0.0)
               ) -> Tuple[Any, Any, Any]:
    """
    Devuelve ``(coords_polares, ángulo 0..1, radio 0..1)``.

    Las coordenadas polares son un vector ``(ángulo, radio, 0)`` que se puede
    enchufar directamente a cualquier textura procedural: así el Voronoi del
    iris se estira radialmente y las criptas salen como las de un ojo real.

    Si el espacio de objeto no sirve (globo descentrado) se usa el UV con
    centro ajustable.
    """
    b = ctx.b
    angle, radius = ctx.radial_from_origin(forward=forward)
    if angle is not None and radius is not None:
        comb = b.add("ShaderNodeCombineXYZ", label="Polar (ángulo, radio)")
        if comb is not None:
            b.link(angle, in_socket(comb, "X", 0))
            b.link(radius, in_socket(comb, "Y", 1))
            zero = b.value(0.0)
            if zero is not None:
                b.link(zero, in_socket(comb, "Z", 2))
            polar = out_socket(comb, "Vector", 0)
            if polar is not None:
                return polar, angle, radius

    # --- fallback: polar en UV ---
    center_u = ctx.f("Centro iris U", 0.5)
    center_v = ctx.f("Centro iris V", 0.5)
    uv = ctx.coords("UV", scaled=False)
    sep = b.add("ShaderNodeSeparateColor", label="Separar UV")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None or uv is None:
        return uv, None, None
    b.link(uv, in_socket(sep, "Color", 0))
    u = out_socket(sep, "Red", 0)
    v = out_socket(sep, "Green", 1)
    du = b.math("SUBTRACT", u, center_u)
    dv = b.math("SUBTRACT", v, center_v)
    ang = texlib._atan2(b, du, dv, label="Ángulo UV")
    rad = texlib._length(b, du, dv, label="Radio UV")
    comb = b.add("ShaderNodeCombineXYZ", label="Polar UV")
    if comb is None or ang is None or rad is None:
        return uv, ang, rad
    b.link(ang, in_socket(comb, "X", 0))
    b.link(rad, in_socket(comb, "Y", 1))
    zero = b.value(0.0)
    if zero is not None:
        b.link(zero, in_socket(comb, "Z", 2))
    return out_socket(comb, "Vector", 0), ang, rad


def _pupil_mask(ctx: RecipeContext, radius: Any, pupil_r: float, edge: float,
                *, dilation: float = 0.0, label: str = "Pupila") -> Optional[NodeOut]:
    """Máscara 1 dentro de la pupila, 0 fuera, con borde suave."""
    if radius is None:
        return None
    r = pupil_r + dilation
    lo = max(0.0, r - edge)
    hi = r + edge
    out = ctx.b.map_range(radius, lo, hi, 0.0, 1.0,
                          interpolation="SMOOTHSTEP", clamp=True, label=label)
    return out


def _ring_mask(ctx: RecipeContext, radius: Any, inner: float, outer: float,
               soft: float = 0.03, *, label: str = "Anillo") -> Optional[NodeOut]:
    """Máscara 1 dentro del anillo ``[inner, outer]``."""
    if radius is None:
        return None
    return texlib.mask_range(ctx.b, radius, inner, outer, smooth=soft, label=label)


# ---------------------------------------------------------------------------
# ESCLERÓTICA
# ---------------------------------------------------------------------------

def sclera(ctx: RecipeContext) -> RecipeResult:
    """Blanco del ojo con red vascular, sombra limbal y tinte cálido."""
    b = ctx.b
    res = RecipeResult()
    polar, angle, radius = _eye_polar(ctx)
    if radius is None:
        ctx.result = res
        return res

    detail = ctx.f("Detalle", 1.0)
    veins_p = ctx.f("Venas", 0.45)
    vein_w = ctx.f("Grosor venas", 0.5)
    irritation = ctx.f("Irritación", 0.10)
    limbal = ctx.f("Sombra limbal", 0.45)
    yellowing = ctx.f("Amarilleo", 0.15)
    whiteness = ctx.f("Blancura", 0.75)

    # ------------------------------------------------------------------
    # Altura: las venas tienen un relieve mínimo pero real (conjuntiva)
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    vein_map: Any = None
    if veins_p > 1e-4:
        vein_map = texlib.vein_network(
            b, polar, scale=ctx.detail_scale(14.0),
            thickness=0.045 * max(0.2, vein_w), branching=0.65,
            warp_amount=0.5, seed_offset=(13.0, 71.0, 29.0),
            label="Venas escleróticas")
        if vein_map is not None:
            # las venas sólo aparecen fuera del limbo y más hacia los ángulos
            zone = b.map_range(radius, 0.30, 0.75, 0.15, 1.0, clamp=True,
                               label="Zona de venas")
            vein_map = b.math("MULTIPLY", vein_map, zone, label="Venas recortadas")
            layers.append((vein_map, 0.00006 * detail))

    micro = texlib.fbm(b, polar, scale=ctx.detail_scale(240.0), detail=5.0,
                       roughness=0.5, seed_offset=(7.0, 3.0, 91.0),
                       label="Micro conjuntiva")
    if micro is not None:
        layers.append((micro, 0.000035 * detail))

    height = ctx.micro_detail(layers, label="Altura esclerótica")
    normal = ctx.bump_from(height, distance=1.0, label="Normal esclerótica") if height else None

    # ------------------------------------------------------------------
    # Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Base esclerótica")
    cool = b.rgb((0.82, 0.86, 0.95, 1.0), label="Tinte frío")
    color: Any = base
    if base is not None and cool is not None:
        # la esclerótica es ligeramente azulada en el centro y más cálida en los
        # ángulos (donde la conjuntiva es más gruesa).
        warm_zone = b.map_range(radius, 0.35, 1.0, 0.0, 1.0, clamp=True,
                                label="Zona cálida")
        warm = b.rgb(ctx.c("Tinte cálido"), label="Tinte cálido")
        if warm is not None:
            color = b.mix_rgb("MIX", b.math("MULTIPLY", warm_zone, 0.55),
                              color, warm, label="Ángulos cálidos")
        color = b.mix_rgb("MIX", b.math("MULTIPLY",
                                        b.math("SUBTRACT", 1.0, warm_zone),
                                        0.28 * whiteness),
                          color, cool, label="Azulado central")

    # venas
    if color is not None and vein_map is not None and veins_p > 1e-4:
        vein_col = b.rgb(ctx.c("Color venas"), label="Color venas")
        if vein_col is not None:
            strength = b.math("MULTIPLY", vein_map, min(1.0, veins_p), label="Venas ×")
            tinted = b.mix_rgb("MIX", strength, color, vein_col, label="Venas")
            if tinted is not None:
                color = tinted

    # irritación general
    if color is not None and irritation > 1e-4:
        red = b.mix_rgb("MULTIPLY", irritation * 0.6, color,
                        (1.0, 0.72, 0.70, 1.0), label="Irritación")
        if red is not None:
            color = red

    # sombra limbal: el borde de la córnea proyecta sobre la esclerótica
    if color is not None and limbal > 1e-4:
        shadow = _ring_mask(ctx, radius, 0.16, 0.30, soft=0.05,
                            label="Sombra limbal")
        if shadow is not None:
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", shadow, limbal * 0.55),
                             color, (0.52, 0.56, 0.62, 1.0), label="Sombra limbal")
            if dark is not None:
                color = dark

    # amarilleo por edad (arcos lipídicos)
    if color is not None and yellowing > 1e-4:
        y_noise = texlib.fbm(b, polar, scale=ctx.detail_scale(5.0), detail=3.0,
                             roughness=0.6, seed_offset=(37.0, 11.0, 3.0),
                             label="Amarilleo")
        if y_noise is not None:
            ymask = b.map_range(y_noise, 0.45, 0.85, 0.0, 1.0, clamp=True)
            ymask = b.math("MULTIPLY", ymask, b.map_range(radius, 0.4, 0.95,
                                                          0.0, 1.0, clamp=True),
                           label="Amarilleo periférico")
            yellow = b.mix_rgb("MIX", b.math("MULTIPLY", ymask, yellowing * 0.7),
                               color, (0.90, 0.84, 0.60, 1.0), label="Amarilleo")
            if yellow is not None:
                color = yellow

    # cavidad (el globo tiene concavidad junto al párpado)
    cavity = ctx.cavity(radius=0.006, label="Cavidad esclerótica")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.30),
                          color, (0.62, 0.60, 0.62, 1.0), label="Sombra párpado")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.g("color_saturation", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # Rugosidad: húmeda, pero las venas rompen el reflejo
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.12)
    rough_val = 0.30 - 0.24 * base_rough
    rough: Any = b.value(rough_val, label="Rugosidad esclerótica")
    if vein_map is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", vein_map, 0.045),
                       label="Venas matan brillo")
    rough = b.clamp(rough, 0.01, 0.6, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.62
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.35) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.35, sss_w * 0.35), label="SSS esclerótica")
        res.sss_radius = (0.0025, 0.0009, 0.0007)
        res.sss_color = b.rgb((0.86, 0.30, 0.28, 1.0), label="Conjuntiva")
    if ctx.on("use_coat"):
        res.coat_weight = b.value(0.35, label="Lágrima")
        res.coat_roughness = 0.02
        res.coat_ior = 1.334

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# IRIS
# ---------------------------------------------------------------------------

#: Color del iris por melanina.  Orden real: azul (poca melanina) → verde →
#: avellana → marrón → marrón muy oscuro.
IRIS_OUTER_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.16, 0.30, 0.42)),   # azul grisáceo
    (0.22, (0.13, 0.34, 0.34)),   # verde azulado
    (0.42, (0.28, 0.30, 0.15)),   # avellana
    (0.66, (0.20, 0.11, 0.05)),   # marrón
    (1.00, (0.05, 0.028, 0.018)), # marrón profundo
)

IRIS_INNER_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.62, 0.58, 0.30)),   # ámbar claro
    (0.25, (0.66, 0.52, 0.18)),   # dorado
    (0.50, (0.52, 0.33, 0.11)),   # ámbar marrón
    (0.75, (0.30, 0.16, 0.06)),
    (1.00, (0.10, 0.05, 0.03)),
)


def _iris_color(b, melanin: Any, outer_stops, inner_stops, *,
                label: str = "Color del iris") -> Optional[Tuple[Any, Any]]:
    ramp_o = b.color_ramp([(p, (r, g, bl, 1.0)) for p, (r, g, bl) in outer_stops],
                          interpolation="LINEAR", label=f"{label} · exterior")
    ramp_i = b.color_ramp([(p, (r, g, bl, 1.0)) for p, (r, g, bl) in inner_stops],
                          interpolation="LINEAR", label=f"{label} · interior")
    if ramp_o is None or ramp_i is None:
        return ramp_o or ramp_i
    b.link(melanin, in_socket(ramp_o.node, "Fac", 0))
    b.link(melanin, in_socket(ramp_i.node, "Fac", 0))
    return ramp_o, ramp_i  # type: ignore[return-value]


def iris(ctx: RecipeContext) -> RecipeResult:
    """Iris humano completo."""
    b = ctx.b
    res = RecipeResult()
    polar, angle, radius = _eye_polar(ctx)
    if radius is None or angle is None:
        ctx.result = res
        return res

    detail = ctx.f("Detalle", 1.0)
    melanin = ctx.f("Melanina", 0.45)
    crypts_p = ctx.f("Criptas", 0.70)
    furrows_p = ctx.f("Surcos", 0.55)
    collarette_p = ctx.f("Colarete", 0.50)
    limbus_p = ctx.f("Limbo", 0.75)
    limbus_w = ctx.f("Grosor limbo", 0.18)
    pupil_r = ctx.f("Pupila", 0.20)
    pupil_edge = max(0.002, ctx.f("Borde pupila", 0.02))
    dilation = ctx.f("Dilatación", 0.0)
    radial_contrast = ctx.f("Contraste radial", 0.6)
    hetero = ctx.f("Heterocromía", 0.0)
    emission = ctx.f("Emisivo", 0.0)

    # ------------------------------------------------------------------
    # 1. ALTURA / RELIEVE DEL ESTROMA
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []

    # 1.1 Criptas: Voronoi estirado radialmente.  Al usar (ángulo, radio) como
    #     coordenada, el patrón se alinea con las fibras del iris.
    if crypts_p > 1e-4:
        crypts = texlib.voronoi_cells(
            b, polar, scale=ctx.detail_scale(26.0), smoothness=0.30,
            feature="Smooth F1", randomness=1.0,
            seed_offset=(3.0, 17.0, 0.0), label="Criptas del iris")
        if crypts is not None:
            shaped = b.map_range(crypts, 0.05, 0.55, 0.0, 1.0,
                                 interpolation="SMOOTHSTEP", clamp=True,
                                 label="Criptas perfil")
            # las criptas sólo existen entre la pupila y el limbo
            zone = _ring_mask(ctx, radius, pupil_r + 0.02, 0.86, soft=0.06,
                              label="Zona de criptas")
            if shaped is not None:
                shaped = b.math("MULTIPLY", shaped, zone if zone is not None else 1.0,
                                label="Criptas recortadas")
                layers.append((shaped, -0.00022 * crypts_p * detail))

    # 1.2 Surcos de Brown: fibra radial
    if furrows_p > 1e-4:
        furrows = texlib.fiber(b, polar, scale=ctx.detail_scale(320.0),
                               anisotropy=0.95, use_gabor=ctx.on("use_gabor"),
                               seed_offset=(11.0, 43.0, 0.0),
                               label="Surcos de Brown")
        if furrows is not None:
            zone = _ring_mask(ctx, radius, pupil_r + 0.03, 0.9, soft=0.08)
            centered = b.math("SUBTRACT", furrows, 0.5, label="Centrar fibra")
            if zone is not None:
                centered = b.math("MULTIPLY", centered, zone)
            layers.append((centered, 0.00016 * furrows_p * detail))

    # 1.3 Colarete: anillo en zigzag que separa la zona pupilar de la ciliar
    collarette: Any = None
    if collarette_p > 1e-4:
        zig = texlib.fbm(b, angle, scale=ctx.detail_scale(48.0), detail=4.0,
                         roughness=0.55, seed_offset=(29.0, 7.0, 0.0),
                         label="Zigzag del colarete")
        if zig is not None:
            center = b.math("MULTIPLY_ADD", zig, 0.055, 0.40, label="Radio zigzag")
            diff = b.math("SUBTRACT", radius, center, label="Distancia al colarete")
            absd = b.math("ABSOLUTE", diff, 0.0)
            if absd is not None:
                collarette = b.map_range(absd, 0.0, 0.035, 1.0, 0.0,
                                         interpolation="SMOOTHSTEP", clamp=True,
                                         label="Colarete")
                layers.append((collarette, 0.00020 * collarette_p * detail))

    height = ctx.micro_detail(layers, label="Altura del iris")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del iris") if height else None

    # ------------------------------------------------------------------
    # 2. COLOR
    # ------------------------------------------------------------------
    mel = b.value(max(0.0, min(1.0, melanin)), label="Melanina del iris")
    ramps = _iris_color(b, mel, IRIS_OUTER_STOPS, IRIS_INNER_STOPS)
    color: Any = None
    if isinstance(ramps, tuple):
        outer, inner = ramps
        # el centro (junto a la pupila) es más cálido; la periferia más oscura
        blend = b.map_range(radius, pupil_r + 0.02, 0.80, 1.0, 0.0, clamp=True,
                            label="Centro → periferia")
        blend = b.math("MULTIPLY_ADD", blend, radial_contrast,
                       1.0 - radial_contrast, label="Contraste radial")
        color = b.mix_rgb("MIX", blend, inner, outer, label="Color del iris")

        # heterocromía: mezcla sectorial con un segundo color
        if hetero > 1e-4:
            alt = b.rgb(ctx.c("Color alternativo"), label="Color alternativo")
            sector = b.map_range(angle, 0.25, 0.75, 0.0, 1.0,
                                 interpolation="SMOOTHSTEP", clamp=True,
                                 label="Sector")
            if alt is not None:
                color = b.mix_rgb("MIX", b.math("MULTIPLY", sector, hetero),
                                  color, alt, label="Heterocromía")

    # el usuario puede teñir por encima
    user_outer = ctx.c("Color exterior")
    user_inner = ctx.c("Color interior")
    if color is not None and not all(abs(x - 1.0) < 1e-3 for x in user_outer[:3]):
        color = b.mix_rgb("MULTIPLY", 0.35, color, user_outer, label="Tinte usuario")

    # criptas oscurecidas (dan la textura visible en el color, no sólo en la normal)
    if color is not None and height is not None and crypts_p > 1e-4:
        shade = b.map_range(height, 0.30, 0.62, 1.0, 0.72, clamp=True,
                            label="Sombra de criptas")
        mod = b.mix_rgb("MULTIPLY", 0.55, color, b.math("MULTIPLY", color, shade),
                        label="Iris texturizado")
        if mod is not None:
            color = mod

    # limbo: anillo oscuro del borde
    if color is not None and limbus_p > 1e-4:
        limbus = _ring_mask(ctx, radius, 1.0 - limbus_w, 1.02, soft=limbus_w * 0.5,
                            label="Limbo")
        if limbus is not None:
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", limbus, limbus_p * 0.85),
                             color, (0.10, 0.08, 0.07, 1.0), label="Limbo oscuro")
            if dark is not None:
                color = dark

    # pupila: negro absoluto con borde suave
    pupil = _pupil_mask(ctx, radius, pupil_r, pupil_edge, dilation=dilation,
                        label="Pupila")
    if color is not None and pupil is not None:
        color = b.mix_rgb("MIX", pupil, color, (0.004, 0.004, 0.005, 1.0),
                          label="Pupila")

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 3. RUGOSIDAD / SSS / EMISIVO
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.06)
    rough_val = 0.18 - 0.15 * base_rough
    rough: Any = b.value(rough_val, label="Rugosidad del iris")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.05),
                       label="Criptas matan el brillo")
    # la pupila es mate (no refleja, absorbe)
    if pupil is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", pupil, 0.35),
                       label="Pupila mate")
    rough = b.clamp(rough, 0.005, 0.9, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.55
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.4) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.35, sss_w * 0.4), label="SSS del iris")
        res.sss_radius = (0.0009, 0.0005, 0.0004)
        res.sss_color = b.rgb((0.55, 0.28, 0.16, 1.0), label="Estroma")

    if emission > 1e-4:
        zone = _ring_mask(ctx, radius, pupil_r, 0.95, soft=0.1)
        glow: Any = b.value(emission, label="Emisivo")
        if zone is not None:
            glow = b.math("MULTIPLY", glow, zone, label="Emisivo del iris")
        if pupil is not None:
            # la pupila no brilla
            glow = b.math("MULTIPLY", glow, b.math("SUBTRACT", 1.0, pupil))
        res.emission_color = b.rgb(ctx.c("Color emisivo"), label="Tinte emisivo")
        res.emission_strength = glow

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# CÓRNEA
# ---------------------------------------------------------------------------

def cornea(ctx: RecipeContext) -> RecipeResult:
    """Capa transparente y húmeda sobre el iris."""
    b = ctx.b
    res = RecipeResult()
    polar, angle, radius = _eye_polar(ctx)

    transparency = ctx.f("Transparencia", 0.92)
    ior = ctx.f("IOR", 1.376)
    rough_p = ctx.f("Rugosidad", 0.02)
    gloss = ctx.f("Brillo", 1.0)
    meniscus = ctx.f("Menisco", 0.25)
    cloudiness = ctx.f("Turbidez", 0.0)

    rough_val = 0.20 - 0.18 * max(0.0, min(1.0, rough_p))
    res.roughness = b.value(max(0.002, rough_val), label="Rugosidad córnea")
    res.metallic = 0.0
    res.specular = b.value(min(2.0, 0.85 * gloss), label="Specular córnea")
    res.ior = ior
    res.transmission = b.value(min(1.0, transparency), label="Transmisión")

    # Menisco lagrimal: el borde junto al párpado acumula líquido y se ve más
    # oscuro y más brillante.
    if radius is not None and meniscus > 1e-4:
        ring = _ring_mask(ctx, radius, 0.90, 1.05, soft=0.06, label="Menisco")
        if ring is not None:
            strength = b.math("MULTIPLY", ring, meniscus, label="Menisco ×")
            res.base_color = b.mix_rgb("MIX", strength,
                                       b.rgb(ctx.c("Tinte"), label="Tinte córnea"),
                                       (0.30, 0.32, 0.34, 1.0),
                                       label="Menisco oscuro")
            if ctx.on("use_coat"):
                res.coat_weight = b.clamp(b.math("MULTIPLY_ADD", strength, 0.6, 0.25),
                                          0.0, 1.0, label="Coat del menisco")
                res.coat_roughness = 0.01
                res.coat_ior = 1.334
    if res.base_color is None:
        res.base_color = b.rgb(ctx.c("Tinte"), label="Tinte córnea")

    # Turbidez (catarata): velo blanquecino con transmisión parcial
    if cloudiness > 1e-4:
        cloud = texlib.fbm(b, polar, scale=ctx.detail_scale(18.0), detail=4.0,
                           roughness=0.6, seed_offset=(53.0, 7.0, 19.0),
                           label="Turbidez")
        if cloud is not None:
            mask = b.math("MULTIPLY", cloud, min(1.0, cloudiness), label="Velo")
            res.base_color = b.mix_rgb("MIX", mask, res.base_color,
                                       (0.86, 0.87, 0.88, 1.0), label="Catarata")
            res.transmission = b.math("MULTIPLY", res.transmission,
                                      b.math("SUBTRACT", 1.0,
                                             b.math("MULTIPLY", mask, 0.7)),
                                      label="Menos transmisión")
            res.roughness = b.math("ADD", res.roughness,
                                    b.math("MULTIPLY", mask, 0.25),
                                    label="Más rugosidad")

    # El lagrimal siempre aporta un coat global aunque no haya menisco
    if res.coat_weight is None and ctx.on("use_coat"):
        res.coat_weight = b.value(0.55, label="Lágrima")
        res.coat_roughness = 0.012
        res.coat_ior = 1.334

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# OJO ANIMAL
# ---------------------------------------------------------------------------

#: Iris animal: ámbar/dorado dominante, con variantes verdes y marrones.
ANIMAL_OUTER_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.86, 0.72, 0.20)),   # amarillo brillante (ave)
    (0.25, (0.70, 0.44, 0.10)),   # ámbar
    (0.50, (0.42, 0.26, 0.08)),   # cobre
    (0.75, (0.16, 0.10, 0.05)),   # marrón
    (1.00, (0.035, 0.024, 0.018)),
)

ANIMAL_INNER_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.95, 0.86, 0.34)),
    (0.30, (0.88, 0.66, 0.16)),
    (0.60, (0.56, 0.34, 0.09)),
    (1.00, (0.14, 0.08, 0.04)),
)


def animal_eye(ctx: RecipeContext) -> RecipeResult:
    """
    Iris animal con pupila deformable y tapetum lucidum.

    ``Forma pupila``: 0 = redonda (perro, ave), 1 = hendidura vertical (gato,
    reptil), 2 = hendidura horizontal (cabra, caballo, pulpo).
    """
    b = ctx.b
    res = RecipeResult()
    polar, angle, radius = _eye_polar(ctx)
    if radius is None:
        ctx.result = res
        return res

    detail = ctx.f("Detalle", 1.0)
    melanin = ctx.f("Melanina", 0.35)
    shape = ctx.f("Forma pupila", 0.0)
    pupil_r = ctx.f("Pupila", 0.22)
    dilation = ctx.f("Dilatación", 0.0)
    fibers_p = ctx.f("Fibras", 0.8)
    crypts_p = ctx.f("Criptas", 0.6)
    tapetum = ctx.f("Tapetum", 0.35)
    limbus_p = ctx.f("Limbo", 0.7)

    # ------------------------------------------------------------------
    # 1. Radio deformado para la pupila
    # ------------------------------------------------------------------
    # Para hendiduras se estira la coordenada en el eje adecuado: una elipse muy
    # alargada en X da una hendidura vertical, y al revés una horizontal.
    r_eff: Any = radius
    if abs(shape - 1.0) > 1e-3 or abs(shape - 2.0) > 1e-3:
        sep = b.add("ShaderNodeSeparateXYZ", label="Separar dirección")
        dir_node = ctx.object_dir()
        if sep is not None and dir_node is not None:
            b.link(dir_node, in_socket(sep, "Vector", 0))
            x = out_socket(sep, "X", 0)
            y = out_socket(sep, "Y", 1)
            z = out_socket(sep, "Z", 2)
            # mezcla entre hendidura vertical (1) y horizontal (2)
            t_v = b.value(max(0.0, 1.0 - abs(shape - 1.0)), label="Peso vertical")
            t_h = b.value(max(0.0, 1.0 - abs(shape - 2.0)), label="Peso horizontal")
            # componente a lo largo del eje "adelante" (+Y por defecto)
            axis = y
            perp_x = x
            perp_z = z
            # radio elíptico: estira el eje perpendicular a la hendidura
            # hendidura vertical -> estrecha en X;  horizontal -> estrecha en Z
            stretch_v = b.math("MULTIPLY", b.math("ABSOLUTE", perp_x, 0.0), 6.0)
            stretch_h = b.math("MULTIPLY", b.math("ABSOLUTE", perp_z, 0.0), 6.0)
            along = b.math("ABSOLUTE", axis, 0.0)
            r_v = b.math("ADD", b.math("MULTIPLY_ADD", stretch_v, t_v, along),
                         b.math("MULTIPLY", along, b.math("SUBTRACT", 1.0, t_v)))
            r_h = b.math("ADD", b.math("MULTIPLY_ADD", stretch_h, t_h, along),
                         b.math("MULTIPLY", along, b.math("SUBTRACT", 1.0, t_h)))
            # El nodo Math no tiene MIX: la interpolación se hace a mano.
            mixed = b.math("ADD",
                           b.math("MULTIPLY", r_v, b.math("SUBTRACT", 1.0, t_h)),
                           b.math("MULTIPLY", r_h, t_h),
                           label="Mezcla de hendidura")
            r_round = radius
            slit_amount = b.clamp(b.math("MAXIMUM", t_v, t_h), 0.0, 1.0,
                                  label="Cuánta hendidura")
            r_eff = b.math("ADD",
                           b.math("MULTIPLY", r_round,
                                  b.math("SUBTRACT", 1.0, slit_amount)),
                           b.math("MULTIPLY", mixed, slit_amount),
                           label="Radio efectivo")
            r_eff = b.clamp(r_eff, 0.0, 2.0)

    # ------------------------------------------------------------------
    # 2. Relieve: fibra densa
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if fibers_p > 1e-4:
        fib = texlib.fiber(b, polar, scale=ctx.detail_scale(420.0),
                           anisotropy=0.97, use_gabor=ctx.on("use_gabor"),
                           seed_offset=(7.0, 53.0, 0.0), label="Fibra del iris")
        if fib is not None:
            centered = b.math("SUBTRACT", fib, 0.5)
            layers.append((centered, 0.00018 * fibers_p * detail))
    if crypts_p > 1e-4:
        cry = texlib.voronoi_cells(b, polar, scale=ctx.detail_scale(22.0),
                                   smoothness=0.32, feature="Smooth F1",
                                   seed_offset=(19.0, 3.0, 0.0), label="Criptas")
        if cry is not None:
            shaped = b.map_range(cry, 0.05, 0.5, 0.0, 1.0,
                                 interpolation="SMOOTHSTEP", clamp=True)
            layers.append((shaped, -0.00020 * crypts_p * detail))

    height = ctx.micro_detail(layers, label="Altura del ojo animal")
    normal = ctx.bump_from(height, distance=1.0) if height else None

    # ------------------------------------------------------------------
    # 3. Color
    # ------------------------------------------------------------------
    mel = b.value(max(0.0, min(1.0, melanin)), label="Melanina animal")
    ramps = _iris_color(b, mel, ANIMAL_OUTER_STOPS, ANIMAL_INNER_STOPS)
    color: Any = None
    if isinstance(ramps, tuple):
        outer, inner = ramps
        blend = b.map_range(r_eff, pupil_r + 0.02, 0.85, 1.0, 0.0, clamp=True)
        color = b.mix_rgb("MIX", blend, inner, outer, label="Color ojo animal")
        color = b.mix_rgb("MULTIPLY", 0.3, color, ctx.c("Color exterior"),
                          label="Tinte usuario") if color is not None else color
        if color is not None:
            color = b.mix_rgb("SCREEN", 0.25, color, ctx.c("Color interior"),
                              label="Centro dorado")

    if color is not None and height is not None:
        shade = b.map_range(height, 0.30, 0.60, 1.0, 0.74, clamp=True)
        mod = b.mix_rgb("MULTIPLY", 0.5, color, b.math("MULTIPLY", color, shade),
                        label="Textura en color")
        if mod is not None:
            color = mod

    if color is not None and limbus_p > 1e-4:
        limbus = _ring_mask(ctx, radius, 0.86, 1.02, soft=0.07, label="Limbo")
        if limbus is not None:
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", limbus, limbus_p * 0.9),
                             color, (0.08, 0.06, 0.05, 1.0), label="Limbo")
            if dark is not None:
                color = dark

    pupil = _pupil_mask(ctx, r_eff, pupil_r, 0.025, dilation=dilation,
                        label="Pupila animal")
    if color is not None and pupil is not None:
        color = b.mix_rgb("MIX", pupil, color, (0.003, 0.003, 0.004, 1.0),
                          label="Pupila")
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    base_rough = ctx.f("Rugosidad", 0.05)
    rough: Any = b.value(max(0.003, 0.16 - 0.14 * base_rough), label="Rugosidad")
    if pupil is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", pupil, 0.4))
    rough = b.clamp(rough, 0.003, 0.9)

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.62
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.g("sss_scale", 1.0) * 0.35
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.3, sss_w * 0.3), label="SSS animal")
        res.sss_radius = (0.0008, 0.0004, 0.0003)
        res.sss_color = b.rgb((0.60, 0.34, 0.14, 1.0), label="Estroma animal")

    # Tapetum lucidum: reflejo emisivo alrededor de la pupila
    if tapetum > 1e-4:
        zone = _ring_mask(ctx, r_eff, pupil_r * 0.9, 0.80, soft=0.25,
                          label="Zona tapetum")
        glow: Any = b.value(tapetum, label="Tapetum")
        if zone is not None:
            glow = b.math("MULTIPLY", glow, zone, label="Tapetum ×")
        if pupil is not None:
            glow = b.math("MULTIPLY", glow, b.math("SUBTRACT", 1.0, pupil),
                          label="Pupila sin brillo")
        res.emission_color = b.rgb(ctx.c("Color tapetum"), label="Color tapetum")
        res.emission_strength = glow

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# CEJAS Y PESTAÑAS
# ---------------------------------------------------------------------------

def lashes(ctx: RecipeContext) -> RecipeResult:
    """
    Vello corto en tarjeta (pestañas, cejas, vello facial).

    Usa el *Principled Hair* de Cycles cuando está disponible (melanina +
    rugosidad longitudinal, que es lo que da el brillo alargado del pelo) y
    cae a un Principled normal con alfa si no.
    """
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()

    melanin = ctx.f("Melanina", 0.75)
    red_mel = ctx.f("Melanina roja", 0.15)
    variation = ctx.f("Variación", 0.25)
    rough_p = ctx.f("Rugosidad", 0.35)
    aniso = ctx.f("Anisotropía", 0.8)
    alpha = ctx.f("Alfa", 1.0)

    # --- color por melanina (mismo modelo que el pelo) ---------------------
    ramp = b.color_ramp([
        (0.00, (0.72, 0.55, 0.28, 1.0)),   # rubio
        (0.30, (0.34, 0.18, 0.07, 1.0)),   # castaño claro
        (0.55, (0.13, 0.07, 0.03, 1.0)),   # castaño
        (0.80, (0.035, 0.022, 0.016, 1.0)),# negro
        (1.00, (0.012, 0.008, 0.006, 1.0)),
    ], interpolation="LINEAR", label="Melanina del vello")
    color: Any = ramp
    if ramp is not None:
        b.link(b.value(max(0.0, min(1.0, melanin)), label="Melanina"),
               in_socket(ramp.node, "Fac", 0))
        # variación entre vellos: motas que aclaran/oscurecen
        if variation > 1e-4 and coords is not None:
            v = texlib.fbm(b, coords, scale=ctx.detail_scale(140.0), detail=4.0,
                           roughness=0.5, seed_offset=(17.0, 3.0, 71.0),
                           label="Variación de vello")
            if v is not None:
                mod = b.map_range(v, 0.35, 0.72, 0.82, 1.22, clamp=True,
                                  label="Modulación")
                color = b.mix_rgb("MULTIPLY", variation, color,
                                  b.math("MULTIPLY", color, mod), label="Vello variado")
        tint = ctx.c("Color")
        if not all(abs(x - 1.0) < 1e-3 for x in tint[:3]):
            color = b.mix_rgb("MIX", 0.55, color, tint, label="Tinte directo")

    # --- alfa: recorte de la tarjeta --------------------------------------
    alpha_val: Any = b.value(alpha, label="Alfa")
    if coords is not None and alpha < 0.999:
        strand = texlib.fiber(b, coords, scale=ctx.detail_scale(300.0),
                              anisotropy=0.98, use_gabor=ctx.on("use_gabor"),
                              seed_offset=(23.0, 11.0, 5.0), label="Hebras")
        if strand is not None:
            cut = b.map_range(strand, 0.35, 0.55, 0.0, 1.0,
                              interpolation="SMOOTHSTEP", clamp=True,
                              label="Recorte de hebra")
            alpha_val = b.math("MULTIPLY", alpha_val, cut, label="Alfa final")

    # --- shader ------------------------------------------------------------
    hair: Any = None
    if compat.has_node("ShaderNodeBsdfHairPrincipled"):
        hair = b.add("ShaderNodeBsdfHairPrincipled", label="BSDF de pelo")
        if hair is not None:
            if color is not None:
                hair_color = in_socket(hair, "Color", 0)
                if hair_color is not None:
                    b.link(color, hair_color)
            compat.set_sock(hair, "Melanin", max(0.0, min(1.0, melanin)))
            compat.set_sock(hair, "Melanin Redness", max(0.0, min(1.0, red_mel)))
            compat.set_sock(hair, "Roughness", max(0.05, min(1.0, rough_p)))
            compat.set_sock(hair, "Radial Roughness",
                            max(0.05, min(1.0, rough_p * (1.2 - 0.4 * aniso))))
            compat.set_sock(hair, "Coat", 1.0)
            compat.set_sock(hair, "Random Color", min(1.0, variation))
            compat.set_sock(hair, "Random Roughness", min(1.0, variation * 0.6))
            # el BSDF de pelo no soporta alfa: mezclamos con Transparent
            if alpha_val is not None:
                trans = b.add("ShaderNodeBsdfTransparent", label="Transparente")
                mixsh = b.add("ShaderNodeMixShader", label="Alfa del vello")
                if trans is not None and mixsh is not None:
                    b.link(alpha_val, in_socket(mixsh, "Fac", 0))
                    b.link(trans, in_socket(mixsh, "Shader", 1))
                    shader_b = in_socket(mixsh, "Shader_001")
                    if shader_b is None:
                        shaders = [x for x in mixsh.inputs
                                   if getattr(x, "type", "") == "SHADER"]
                        shader_b = shaders[-1] if len(shaders) > 1 else None
                    if shader_b is not None:
                        b.link(hair, shader_b)
                    res.extra["surface"] = mixsh
                    ctx.result = res
                    return res

    if hair is not None:
        res.extra["surface"] = hair
        ctx.result = res
        return res

    # --- fallback: Principled con alfa ------------------------------------
    res.base_color = color
    res.roughness = b.value(max(0.05, min(1.0, rough_p)), label="Rugosidad vello")
    res.metallic = 0.0
    res.specular = 0.45
    res.alpha = alpha_val
    res.anisotropic = b.value(min(1.0, aniso), label="Anisotropía")
    res.sheen_weight = b.value(0.35, label="Sheen del vello") if ctx.on("use_sheen") else None
    res.sheen_roughness = 0.55
    ctx.result = res
    return res
