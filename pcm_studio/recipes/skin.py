# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Recetas de piel.

Cómo se construye la piel aquí (y por qué se ve "profesional"):

**Color.** No se pinta un color plano con ruido encima.  Se parte de una rampa
de melanina calibrada con albedos de referencia (:data:`base.MELANIN_STOPS`) y
sobre ella se aplican, en este orden:

1. *Moteado multi-escala*: dos fBm a escalas muy distintas (una ~40× la otra)
   que mueven la posición dentro de la rampa de melanina.  Es lo que produce la
   transición suave entre frente, mejilla y cuello.
2. * undertone sanguíneo*: la oclusión de cavidad y un fBm de baja frecuencia
   enrojecen las zonas cóncavas (surco nasogeniano, aletas, pliegues).
3. *Pecas y lunares*: motas Voronoi muy dispersas, **agrupadas** por un ruido
   regional, porque así es como aparecen de verdad.
4. *Rubor / zonas T*: máscaras de posición en UV (paramétricas, ajustables).
5. *Tinte, saturación, brillo y contraste* del usuario y del estilo.
6. *Recorte a 0..1* para que el albedo sea válido en Unity/Unreal.

**Micro-relieve.** Cuatro capas de altura independientes, cada una con su firma
correcta: poros (Voronoi ``Smooth F1`` invertido), grano direccional (ruido
anisótropo siguiendo las líneas de Langer), pliegues (ruido *ridged* con domain
warp, que es lo que evita el aspecto de "azulejos") y vello.  Se suman con pesos
y el resultado alimenta tanto el ``Bump`` (para el viewport) como el
``Displacement`` (para bakear la normal con el detalle de verdad).

**Rugosidad.** Nunca es constante: la piel grasa de la zona T baja la
rugosidad, la pared del poro la sube, y las zonas secas la disparan.

**SSS.** Random Walk con radio dependiente de la melanina (a más melanina menos
componente roja emergente) y color de sangre por rampa propia.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from .. import compat, texlib
from ..shaderkit import NodeOut, in_socket, out_socket
from .base import (
    RecipeContext,
    RecipeResult,
    apply_tint,
    brightness,
    clamp_color,
    contrast,
    melanin_color,
    safe_float,
    saturate,
    sss_ramp,
)

__all__ = ("skin", "skin_face", "skin_extremity", "skin_thin", "lips")


# ---------------------------------------------------------------------------
# Constantes calibradas
# ---------------------------------------------------------------------------

#: Profundidad de un poro humano en metros (Blender usa unidades métricas).
PORE_DEPTH = 0.00022
#: Relieve de una arruga fina.
WRINKLE_DEPTH = 0.00075
#: Relieve del vello (apenas perceptible pero rompe el specular).
VELLUS_DEPTH = 0.00008
#: Grano de la piel.
GRAIN_DEPTH = 0.00012
#: Undulación grande (grasa subcutánea, músculos).
UNDULATION_DEPTH = 0.0012

#: Rugosidad de piel seca / grasa.
SKIN_ROUGH_DRY = 0.62
SKIN_ROUGH_OILY = 0.24


# ---------------------------------------------------------------------------
# Helpers locales
# ---------------------------------------------------------------------------

def _pore_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                strength: float, softness: float = 0.30,
                seed: Sequence[float] = (0.0, 0.0, 0.0)) -> Optional[NodeOut]:
    """
    Poros: Voronoi ``Smooth F1`` invertido con perfil endurecido.

    El truco es el exponente: sin él las celdas Voronoi dan "manchas", con él
    sólo sobrevive el fondo de la celda y aparece el hoyo del poro.
    """
    if strength <= 1e-4:
        return None
    cells = texlib.voronoi_cells(
        ctx.b, coords, scale=scale, smoothness=softness, feature="Smooth F1",
        randomness=1.0, seed_offset=seed, label="Poros")
    if cells is None:
        return None
    b = ctx.b
    pore = b.map_range(cells, 0.0, 0.42, 1.0, 0.0, interpolation="SMOOTHSTEP",
                       clamp=True, label="Hoyo del poro")
    if pore is None:
        return None
    shaped = b.math("POWER", pore, 1.8, label="Perfil")
    if shaped is None:
        shaped = pore
    return b.math("MULTIPLY", shaped, strength, label="Peso poro")


def _grain_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                 strength: float, angle_deg: float = 25.0,
                 seed: Sequence[float] = (3.0, 7.0, 11.0)) -> Optional[NodeOut]:
    """
    Grano direccional: sigue las líneas de Langer (la piel no es isotrópica).

    Se usa el ruido anisótropo (Gabor en Blender 5.x, Wave estirado si no).
    """
    if strength <= 1e-4:
        return None
    fib = texlib.fiber(ctx.b, coords, scale=scale, anisotropy=0.85,
                       use_gabor=ctx.on("use_gabor"), seed_offset=seed,
                       label="Grano de piel")
    if fib is None:
        return None
    b = ctx.b
    centered = b.math("SUBTRACT", fib, 0.5, label="Centrar")
    if centered is None:
        return None
    return b.math("MULTIPLY", centered, strength, label="Peso grano")


def _wrinkle_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                   strength: float, warp: float = 0.45,
                   seed: Sequence[float] = (17.0, 23.0, 5.0)) -> Optional[NodeOut]:
    """
    Pliegues: ruido *ridged* con domain warping.

    El warp es imprescindible: un pliegue recto y paralelo se ve falso al
    instante.  Con warp aparecen bifurcaciones y curvatura, que es lo que hace
    una arruga real.
    """
    if strength <= 1e-4:
        return None
    b = ctx.b
    warped = texlib.warp(b, coords, amount=warp, warp_scale=max(1.0, scale * 0.08),
                         detail=3.0, seed_offset=seed, label="Warp de arrugas")
    src = warped if warped is not None else coords
    ridged = texlib.ridged(b, src, scale=scale, detail=5.0, roughness=0.52,
                           sharpness=1.6, seed_offset=seed, label="Pliegues")
    if ridged is None:
        return None
    # El ridged devuelve crestas claras; queremos surcos (oscuros => altura baja)
    groove = b.math("SUBTRACT", 1.0, ridged, label="Surco")
    if groove is None:
        return None
    # Un segundo pase a escala mayor da los pliegues anchos (nasogeniano, frente)
    broad = texlib.ridged(b, src, scale=max(1.0, scale * 0.22), detail=3.0,
                          roughness=0.5, sharpness=1.2,
                          seed_offset=(seed[0] + 9.0, seed[1] + 4.0, seed[2] + 1.0),
                          label="Pliegues anchos")
    if broad is not None:
        broad_g = b.math("SUBTRACT", 1.0, broad, label="Surco ancho")
        groove = b.math("MAXIMUM", groove, b.math("MULTIPLY", broad_g, 0.65),
                        label="Pliegue total")
    return b.math("MULTIPLY", groove, strength, label="Peso arrugas")


def _vellus_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                  strength: float) -> Optional[NodeOut]:
    """Vello corporal: fibra finísima y muy poco profunda."""
    if strength <= 1e-4:
        return None
    fib = texlib.fiber(ctx.b, coords, scale=scale, anisotropy=0.95,
                       use_gabor=ctx.on("use_gabor"),
                       seed_offset=(41.0, 13.0, 7.0), label="Vello")
    if fib is None:
        return None
    return ctx.b.math("MULTIPLY", fib, strength, label="Peso vello")


def _undulation_layer(ctx: RecipeContext, coords: Any, *, scale: float,
                      strength: float) -> Optional[NodeOut]:
    """Undulación de baja frecuencia: grasa subcutánea, músculo, hueso bajo la piel."""
    if strength <= 1e-4:
        return None
    fbm = texlib.fbm(ctx.b, coords, scale=scale, detail=4.0, roughness=0.55,
                     seed_offset=(61.0, 29.0, 3.0), label="Undulación")
    if fbm is None:
        return None
    centered = ctx.b.math("SUBTRACT", fbm, 0.5, label="Centrar")
    return ctx.b.math("MULTIPLY", centered, strength, label="Peso undulación")


def _uv_mask(ctx: RecipeContext, center_u: float, center_v: float,
             radius: float, *, softness: float = 0.5,
             label: str = "Máscara") -> Optional[NodeOut]:
    """
    Máscara radial suave en espacio UV, 1 en el centro y 0 fuera.

    Se usa para rubor de mejillas, zona T, sombra de barba…  Al ser UV es
    independiente del modelo, y los centros son parámetros ajustables para que
    el artista los coloque en su topología concreta.
    """
    if radius <= 1e-4:
        return None
    b = ctx.b
    coords = ctx.coords("UV", scaled=False)
    if coords is None:
        return None
    sep = b.add("ShaderNodeSeparateColor", label=label)
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None:
        return None
    b.link(coords, in_socket(sep, "Color", 0))
    u = out_socket(sep, "Red", 0)
    v = out_socket(sep, "Green", 1)
    du = b.math("SUBTRACT", u, center_u)
    dv = b.math("SUBTRACT", v, center_v)
    du2 = b.math("MULTIPLY", du, du)
    dv2 = b.math("MULTIPLY", dv, dv)
    d = b.math("SQRT", b.math("ADD", du2, dv2), 0.0, label="Distancia UV")
    if d is None:
        return None
    inner = radius * max(0.05, 1.0 - softness)
    return b.map_range(d, inner, radius, 1.0, 0.0,
                       interpolation="SMOOTHSTEP", clamp=True, label=label)


def _combine_masks(b, masks: Sequence[Any], mode: str = "MAXIMUM"
                   ) -> Optional[Any]:
    """Combina varias máscaras 0..1 (máximo o suma recortada)."""
    acc: Any = None
    for m in masks:
        if m is None:
            continue
        acc = m if acc is None else b.math(mode, acc, m)
    if acc is not None and mode == "ADD":
        acc = b.clamp(acc, 0.0, 1.0, label="Recorte máscara")
    return acc


# ---------------------------------------------------------------------------
# Núcleo compartido de piel
# ---------------------------------------------------------------------------

class SkinBuild:
    """Resultado intermedio del núcleo de piel, reutilizado por las variantes."""

    def __init__(self) -> None:
        self.color: Any = None
        self.roughness: Any = None
        self.height: Any = None
        self.normal: Any = None
        self.sss_color: Any = None
        self.cavity: Any = None
        self.oil: Any = None
        self.melanin: Any = None


def _build_skin_core(ctx: RecipeContext, *,
                     pore_scale: float = 420.0,
                     grain_scale: float = 900.0,
                     wrinkle_scale: float = 26.0,
                     undulation_scale: float = 3.2,
                     has_vellus: bool = True,
                     has_freckles: bool = True,
                     pore_weight: float = 1.0,
                     wrinkle_weight: float = 1.0) -> SkinBuild:
    """Construye color + rugosidad + altura de una zona de piel."""
    b = ctx.b
    out = SkinBuild()
    coords = ctx.coords()
    if coords is None:
        return out

    melanin = ctx.f("Melanina", 0.45)
    detail = ctx.f("Detalle", 1.0)
    pores_p = ctx.f("Poros", 0.55) * pore_weight
    wrinkles_p = ctx.f("Arrugas", 0.35) * wrinkle_weight
    vellus_p = ctx.f("Vello", 0.20) if has_vellus else 0.0
    age = ctx.f("Edad", 0.30)
    variation = ctx.f("Variación", 0.5) * ctx.g("color_variation", 1.0)
    redness = ctx.f("Rojizo", 0.35)
    oil_p = ctx.f("Aceite", 0.25)
    dryness = ctx.f("Sequedad", 0.0)

    use_pores = ctx.on("use_pores")
    use_wrinkles = ctx.on("use_wrinkles")

    # ------------------------------------------------------------------
    # 1. ALTURA (micro-relieve)
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []

    pore_strength = (pores_p * detail * PORE_DEPTH) if use_pores else 0.0
    if pore_strength > 1e-8:
        layer = _pore_layer(ctx, coords, scale=ctx.detail_scale(pore_scale),
                            strength=1.0, softness=0.28)
        if layer is not None:
            layers.append((layer, pore_strength))

    if GRAIN_DEPTH * detail > 1e-8:
        layer = _grain_layer(ctx, coords, scale=ctx.detail_scale(grain_scale),
                             strength=GRAIN_DEPTH * detail)
        if layer is not None:
            layers.append((layer, 1.0))

    wrinkle_strength = wrinkles_p * detail * WRINKLE_DEPTH * (0.35 + age)
    if use_wrinkles and wrinkle_strength > 1e-8:
        layer = _wrinkle_layer(ctx, coords, scale=ctx.detail_scale(wrinkle_scale),
                               strength=1.0, warp=0.35 + 0.4 * age)
        if layer is not None:
            layers.append((layer, wrinkle_strength))

    if has_vellus and vellus_p * detail * VELLUS_DEPTH > 1e-9:
        layer = _vellus_layer(ctx, coords, scale=ctx.detail_scale(grain_scale * 1.8),
                              strength=vellus_p * detail * VELLUS_DEPTH)
        if layer is not None:
            layers.append((layer, 1.0))

    und = _undulation_layer(ctx, coords, scale=undulation_scale,
                            strength=UNDULATION_DEPTH * (0.4 + 0.6 * detail))
    if und is not None:
        layers.append((und, 1.0))

    if dryness > 1e-3:
        # Piel seca: descamación en placas finas
        crack = texlib.crackle(b, coords, scale=ctx.detail_scale(90.0),
                               width=0.05 * dryness, warp_amount=0.5,
                               seed_offset=(83.0, 19.0, 47.0), label="Descamación")
        if crack is not None:
            layers.append((crack, -0.00025 * dryness * detail))

    height = ctx.micro_detail(layers, label="Altura de piel")
    out.height = height
    if height is not None:
        out.normal = ctx.bump_from(height, distance=1.0, label="Normal de piel")

    # ------------------------------------------------------------------
    # 2. CAVIDAD (ensucia poros y pliegues)
    # ------------------------------------------------------------------
    cavity = ctx.cavity(radius=0.0035, label="Cavidad de piel")
    out.cavity = cavity

    # ------------------------------------------------------------------
    # 3. COLOR
    # ------------------------------------------------------------------
    mel_node = b.value(melanin, label="Melanina")
    out.melanin = mel_node

    # 3.1 moteado multi-escala sobre la rampa de melanina
    mottle_big = texlib.fbm(b, coords, scale=ctx.detail_scale(3.4), detail=4.0,
                            roughness=0.55, seed_offset=(13.0, 71.0, 7.0),
                            label="Moteado grande")
    mottle_small = texlib.fbm(b, coords, scale=ctx.detail_scale(38.0), detail=5.0,
                              roughness=0.5, seed_offset=(29.0, 11.0, 83.0),
                              label="Moteado fino")
    mel_mod = mel_node
    if mottle_big is not None and variation > 1e-4:
        d_big = b.math("MULTIPLY", b.math("SUBTRACT", mottle_big, 0.5),
                       0.30 * variation, label="Δ melanina grande")
        mel_mod = b.math("ADD", mel_mod, d_big)
    if mottle_small is not None and variation > 1e-4:
        d_small = b.math("MULTIPLY", b.math("SUBTRACT", mottle_small, 0.5),
                         0.12 * variation, label="Δ melanina fino")
        mel_mod = b.math("ADD", mel_mod, d_small)
    mel_mod = b.clamp(mel_mod, 0.0, 1.0, label="Melanina modulada")

    color = melanin_color(b, mel_mod, ctx.c("Color base"), label="Rampa de melanina")

    # 3.2 undertone sanguíneo: cavidad + ruido cálido
    if cavity is not None and redness > 1e-4:
        blood_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(6.5), detail=4.0,
                                 roughness=0.6, seed_offset=(5.0, 97.0, 31.0),
                                 label="Vascularización")
        red_mask = cavity
        if blood_noise is not None:
            red_mask = b.math("MULTIPLY", cavity,
                              b.map_range(blood_noise, 0.25, 0.8, 0.35, 1.0,
                                          clamp=True), label="Zona roja")
        warm = b.rgb((0.86, 0.30, 0.24, 1.0), label="Sangre")
        if warm is not None:
            tinted = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", red_mask, redness * 0.9),
                               color, warm, label="Undertone")
            if tinted is not None:
                color = tinted

    # 3.3 oscurecer los surcos (la cavidad también oscurece el albedo)
    if cavity is not None:
        shade = b.math("MULTIPLY", cavity, 0.45, label="Sombra de cavidad")
        dark = b.mix_rgb("MULTIPLY", shade, color, (0.42, 0.34, 0.32, 1.0),
                         label="Surco oscuro")
        if dark is not None:
            color = dark

    # 3.4 pecas y lunares
    if has_freckles:
        freckle_p = ctx.f("Pecas", 0.05)
        if freckle_p > 1e-4:
            freckles = texlib.speckle_field(b, coords,
                                            scale=ctx.detail_scale(160.0),
                                            density=freckle_p * 2.0, size=0.16,
                                            seed_offset=(7.0, 43.0, 19.0),
                                            label="Pecas")
            if freckles is not None:
                dark_freckle = b.mix_rgb("MULTIPLY",
                                         b.math("MULTIPLY", freckles, 0.75),
                                         color, (0.42, 0.24, 0.16, 1.0),
                                         label="Pecas")
                if dark_freckle is not None:
                    color = dark_freckle

    # 3.5 vello: aclara y desatura ligeramente (la pelusa difunde la luz)
    if has_vellus and vellus_p > 1e-3:
        vellus_mask = texlib.fiber(b, coords, scale=ctx.detail_scale(grain_scale * 1.8),
                                   anisotropy=0.95, use_gabor=ctx.on("use_gabor"),
                                   seed_offset=(41.0, 13.0, 7.0), label="Vello color")
        if vellus_mask is not None:
            light = b.mix_rgb("SCREEN",
                              b.math("MULTIPLY", vellus_mask, vellus_p * 0.16),
                              color, (0.80, 0.78, 0.74, 1.0), label="Pelusa")
            if light is not None:
                color = light

    # 3.6 ajustes globales de color
    color = saturate(b, color, ctx.f("Saturación", 1.0) * ctx.g("color_saturation", 1.0))
    color = brightness(b, color, ctx.f("Brillo", 1.0))
    color = contrast(b, color, ctx.g("color_contrast", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5:
        color = clamp_color(b, color, lo=0.0, hi=1.0)
    out.color = color

    # ------------------------------------------------------------------
    # 4. COLOR DE SSS
    # ------------------------------------------------------------------
    sss_col = sss_ramp(b, mel_mod, label="Color SSS")
    user_sss = ctx.c("Color SSS")
    if sss_col is not None and not all(abs(x - 1.0) < 1e-3 for x in user_sss[:3]):
        sss_col = b.mix_rgb("MULTIPLY", 0.65, sss_col, user_sss, label="SSS teñido")
    out.sss_color = sss_col

    # ------------------------------------------------------------------
    # 5. RUGOSIDAD
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.5)
    rough_value = SKIN_ROUGH_DRY - (SKIN_ROUGH_DRY - SKIN_ROUGH_OILY) * base_rough
    rough: Any = b.value(rough_value, label="Rugosidad base")

    # 5.1 pared del poro: más rugosa que la meseta
    if use_pores and pores_p > 1e-4 and height is not None:
        pore_rough = b.math("MULTIPLY", height, 0.055 * pores_p, label="Δ poro")
        rough = b.math("ADD", rough, pore_rough)

    # 5.2 zonas grasas
    if oil_p > 1e-4:
        oil_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(4.2), detail=4.0,
                               roughness=0.55, seed_offset=(91.0, 17.0, 23.0),
                               label="Grasa")
        if oil_noise is not None:
            out.oil = b.map_range(oil_noise, 0.45, 0.9, 0.0, 1.0, clamp=True,
                                  label="Máscara de grasa")
            rough = b.math("MULTIPLY_ADD", rough, 1.0 - 0.42 * oil_p, 0.0,
                           label="Grasa reduce rugosidad")
            if out.oil is not None:
                delta = b.math("MULTIPLY", out.oil, -0.16 * oil_p, label="Δ grasa")
                rough = b.math("ADD", rough, delta)

    # 5.3 piel seca / descamación
    if dryness > 1e-3 and cavity is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", cavity, 0.10 * dryness))

    # 5.4 variación de baja frecuencia
    var = ctx.f("Variación de rugosidad", 0.35)
    if var > 1e-4:
        rough_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(7.0), detail=3.0,
                                 roughness=0.5, seed_offset=(37.0, 3.0, 61.0),
                                 label="Variación rugosidad")
        if rough_noise is not None:
            delta = b.math("MULTIPLY", b.math("SUBTRACT", rough_noise, 0.5),
                           0.18 * var, label="Δ rugosidad")
            rough = b.math("ADD", rough, delta)

    wet = ctx.f("Humedad", 0.0)
    if wet > 1e-3:
        rough = b.math("MULTIPLY", rough, 1.0 - 0.55 * wet, label="Humedad")

    rough = b.clamp(rough, 0.035, 0.95, label="Rugosidad final")
    out.roughness = rough

    return out


def _apply_skin_result(ctx: RecipeContext, s: SkinBuild, *,
                       sss_weight: Optional[float] = None,
                       sss_radius_mm: Optional[float] = None,
                       specular: float = 0.42,
                       coat: bool = True) -> RecipeResult:
    """Vuelca un :class:`SkinBuild` en el :class:`RecipeResult` de la zona."""
    res = ctx.result
    b = ctx.b
    res.base_color = s.color
    res.roughness = s.roughness
    res.metallic = 0.0
    res.specular = specular
    res.normal_detail = s.normal
    res.detail_height = s.height

    w = ctx.f("SSS", 0.6) * ctx.g("sss_scale", 1.0)
    if sss_weight is not None:
        w = sss_weight * ctx.g("sss_scale", 1.0)
    if w > 1e-4:
        res.sss_weight = b.clamp(w * 0.5, 0.0, 1.0, label="Peso SSS")
        r_mm = ctx.f("Radio SSS (mm)", 8.0) if sss_radius_mm is None else sss_radius_mm
        r_mm *= ctx.g("sss_radius_scale", 1.0)
        radius_m = max(0.0001, r_mm / 1000.0)
        # Radio por canal: la piel absorbe mucho más el azul/verde que el rojo,
        # por eso el rojo penetra más lejos (orejas rojas a contraluz).
        res.sss_radius = (radius_m * 1.0, radius_m * 0.36, radius_m * 0.22)
        res.sss_color = s.sss_color
        res.sss_scale = 1.0

    # Capa húmeda (sudor / sebo) sólo si el estilo la permite y el usuario la pide
    wet = ctx.f("Humedad", 0.0)
    if coat and ctx.on("use_coat") and wet > 1e-3:
        res.coat_weight = b.clamp(wet * 0.6, 0.0, 1.0, label="Coat húmedo")
        res.coat_roughness = 0.06
        res.coat_ior = 1.33
    return res


# ---------------------------------------------------------------------------
# Zonas
# ---------------------------------------------------------------------------

def skin(ctx: RecipeContext) -> RecipeResult:
    """Piel corporal."""
    s = _build_skin_core(ctx, pore_scale=380.0, grain_scale=820.0,
                         wrinkle_scale=22.0, undulation_scale=3.0)
    return _apply_skin_result(ctx, s, specular=0.40)


def skin_face(ctx: RecipeContext) -> RecipeResult:
    """
    Piel facial: añade zona T grasa, rubor de mejillas, ojeras, sombra de barba
    y poro más visible en nariz y frente.
    """
    b = ctx.b
    s = _build_skin_core(ctx, pore_scale=480.0, grain_scale=900.0,
                         wrinkle_scale=28.0, undulation_scale=3.4)

    coords = ctx.coords()
    color = s.color
    rough = s.roughness

    # --- máscaras de posición en UV (paramétricas) ------------------------
    nose = _uv_mask(ctx, ctx.f("Nariz U", 0.50), ctx.f("Nariz V", 0.52),
                    ctx.f("Radio nariz", 0.075), softness=0.75, label="Zona nariz")
    cheek_l = _uv_mask(ctx, ctx.f("Mejilla izq. U", 0.405),
                       ctx.f("Mejilla izq. V", 0.475),
                       ctx.f("Radio mejilla", 0.085), softness=0.85,
                       label="Mejilla izquierda")
    cheek_r = _uv_mask(ctx, ctx.f("Mejilla der. U", 0.595),
                       ctx.f("Mejilla der. V", 0.475),
                       ctx.f("Radio mejilla", 0.085), softness=0.85,
                       label="Mejilla derecha")
    forehead = _uv_mask(ctx, ctx.f("Frente U", 0.50), ctx.f("Frente V", 0.66),
                        ctx.f("Radio frente", 0.13), softness=0.9,
                        label="Frente")
    chin = _uv_mask(ctx, ctx.f("Mentón U", 0.50), ctx.f("Mentón V", 0.34),
                    ctx.f("Radio mentón", 0.09), softness=0.8, label="Mentón")
    eye_l = _uv_mask(ctx, ctx.f("Ojo izq. U", 0.425), ctx.f("Ojo izq. V", 0.565),
                     ctx.f("Radio ojera", 0.055), softness=0.7, label="Ojera izq.")
    eye_r = _uv_mask(ctx, ctx.f("Ojo der. U", 0.575), ctx.f("Ojo der. V", 0.565),
                     ctx.f("Radio ojera", 0.055), softness=0.7, label="Ojera der.")
    beard = _combine_masks(b, [chin,
                               _uv_mask(ctx, 0.50, 0.415, 0.075, softness=0.6,
                                        label="Labio superior"),
                               _uv_mask(ctx, 0.415, 0.545, 0.035, softness=0.6,
                                        label="Patilla izq."),
                               _uv_mask(ctx, 0.585, 0.545, 0.035, softness=0.6,
                                        label="Patilla der.")], mode="MAXIMUM")

    t_zone = _combine_masks(b, [nose, forehead], mode="MAXIMUM")
    cheeks = _combine_masks(b, [cheek_l, cheek_r], mode="MAXIMUM")
    eyes = _combine_masks(b, [eye_l, eye_r], mode="MAXIMUM")

    # --- rubor de mejillas y nariz ---------------------------------------
    flush_p = ctx.f("Rubor", 0.35)
    if color is not None and flush_p > 1e-4 and cheeks is not None:
        flush_mask = cheeks
        if nose is not None:
            flush_mask = b.math("MAXIMUM", cheeks, b.math("MULTIPLY", nose, 0.55),
                                label="Rubor + nariz")
        # la intensidad del rubor depende de la melanina: en pieles oscuras se
        # manifiesta menos como rojo y más como saturación.
        mel = ctx.f("Melanina", 0.45)
        gain = flush_p * (0.55 + 0.45 * (1.0 - mel))
        blush = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", flush_mask, gain),
                          color, (1.0, 0.62, 0.58, 1.0), label="Rubor")
        if blush is not None:
            color = blush

    # --- ojeras ------------------------------------------------------------
    dark_p = ctx.f("Ojeras", 0.25)
    if color is not None and dark_p > 1e-4 and eyes is not None:
        ring = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", eyes, dark_p * 0.85),
                         color, (0.62, 0.58, 0.72, 1.0), label="Ojera")
        if ring is not None:
            color = ring

    # --- sombra de barba ----------------------------------------------------
    beard_p = ctx.f("Barba / sombra", 0.20)
    if color is not None and beard_p > 1e-4 and beard is not None:
        stubble = texlib.stipple(b, coords, scale=ctx.detail_scale(700.0),
                                 density=0.22, softness=0.35,
                                 seed_offset=(77.0, 5.0, 29.0), label="Barba")
        mask = beard
        if stubble is not None:
            mask = b.math("MULTIPLY", beard, b.map_range(stubble, 0.0, 1.0, 0.45, 1.0,
                                                         clamp=True),
                          label="Barba moteada")
        shadow = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", mask, beard_p * 0.8),
                           color, (0.46, 0.44, 0.48, 1.0), label="Sombra de barba")
        if shadow is not None:
            color = shadow

    # --- zona T: más grasa y poro más visible -------------------------------
    oil_p = ctx.f("Aceite", 0.45)
    if rough is not None and t_zone is not None and oil_p > 1e-4:
        delta = b.math("MULTIPLY", t_zone, -0.14 * oil_p, label="Grasa zona T")
        rough = b.clamp(b.math("ADD", rough, delta), 0.03, 0.95,
                        label="Rugosidad facial")
        if ctx.on("use_coat"):
            ctx.result.coat_weight = b.clamp(
                b.math("MULTIPLY", t_zone, 0.25 * oil_p), 0.0, 0.6,
                label="Brillo zona T")
            ctx.result.coat_roughness = 0.05
            ctx.result.coat_ior = 1.40

    # --- poros más marcados en nariz y frente --------------------------------
    if s.height is not None and t_zone is not None:
        boost = b.math("MULTIPLY_ADD", s.height, b.math("MULTIPLY", t_zone, 0.35),
                       s.height, label="Poro zona T")
        s.height = boost
        s.normal = ctx.bump_from(boost, distance=1.0, label="Normal facial")

    s.color = color
    s.roughness = rough
    return _apply_skin_result(ctx, s, specular=0.45)


def skin_extremity(ctx: RecipeContext) -> RecipeResult:
    """Manos, pies, codos y rodillas: más seca, pliegues marcados, palmas."""
    b = ctx.b
    s = _build_skin_core(ctx, pore_scale=340.0, grain_scale=760.0,
                         wrinkle_scale=16.0, undulation_scale=4.2,
                         has_vellus=True, has_freckles=True)
    coords = ctx.coords()

    # Pliegues de nudillos: estrías transversales concentradas
    crease_p = ctx.f("Pliegues", 0.70)
    if crease_p > 1e-4 and coords is not None:
        stri = texlib.striations(b, coords, count=34.0, wobble=0.10, thickness=0.42,
                                 axis="V", seed_offset=(3.0, 51.0, 17.0),
                                 label="Pliegues de nudillos")
        if stri is not None and s.height is not None:
            add = b.math("MULTIPLY", stri, crease_p * 0.0009 * ctx.f("Detalle", 1.0),
                         label="Peso pliegues")
            s.height = b.math("ADD", s.height, add, label="Altura con pliegues")
            s.normal = ctx.bump_from(s.height, distance=1.0, label="Normal extremidad")

    # Nudillos y codos enrojecidos
    knuckle_p = ctx.f("Nudillos", 0.45)
    if knuckle_p > 1e-4 and s.color is not None and coords is not None:
        bumps = texlib.stipple(b, coords, scale=ctx.detail_scale(24.0),
                               density=0.55, softness=0.6,
                               seed_offset=(19.0, 73.0, 5.0), label="Nudillos")
        if bumps is not None:
            red = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", bumps, knuckle_p * 0.55),
                            s.color, (1.0, 0.66, 0.62, 1.0), label="Nudillos rojos")
            if red is not None:
                s.color = red

    # Palmas y plantas: sin melanina, más claras y con estrías propias
    palm_p = ctx.f("Palmas", 0.0)
    if palm_p > 1e-3 and s.color is not None:
        palm = b.mix_rgb("MIX", palm_p, s.color, ctx.c("Color palma"),
                         label="Palma")
        if palm is not None:
            s.color = palm

    dryness = ctx.f("Sequedad", 0.55)
    if s.roughness is not None and dryness > 1e-4:
        s.roughness = b.clamp(b.math("ADD", s.roughness, 0.10 * dryness),
                              0.05, 0.97, label="Rugosidad seca")

    return _apply_skin_result(ctx, s, sss_weight=ctx.f("SSS", 0.5),
                              sss_radius_mm=ctx.f("Radio SSS (mm)", 5.0),
                              specular=0.38)


def skin_thin(ctx: RecipeContext) -> RecipeResult:
    """Párpados, orejas, aletas nasales: fina, translúcida, con capilares."""
    b = ctx.b
    s = _build_skin_core(ctx, pore_scale=260.0, grain_scale=620.0,
                         wrinkle_scale=34.0, undulation_scale=5.0,
                         has_vellus=False, has_freckles=False,
                         pore_weight=0.45, wrinkle_weight=0.8)
    coords = ctx.coords()

    # Capilares visibles a través de la piel fina
    cap_p = ctx.f("Capilares", 0.35)
    if cap_p > 1e-4 and coords is not None and s.color is not None:
        veins = texlib.vein_network(b, coords, scale=ctx.detail_scale(34.0),
                                    thickness=0.05, branching=0.6,
                                    warp_amount=0.6,
                                    seed_offset=(23.0, 67.0, 11.0),
                                    label="Capilares")
        if veins is not None:
            tinted = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", veins, cap_p * 0.8),
                               s.color, (0.92, 0.42, 0.40, 1.0), label="Capilares")
            if tinted is not None:
                s.color = tinted

    trans = ctx.f("Translucidez", 0.65)
    res = _apply_skin_result(ctx, s, sss_weight=ctx.f("SSS", 1.0),
                             sss_radius_mm=ctx.f("Radio SSS (mm)", 12.0),
                             specular=0.50)
    if trans > 1e-3:
        # La piel muy fina deja pasar algo de luz: transmisión mínima + SSS alto.
        res.transmission = b.value(min(0.25, trans * 0.22), label="Translucidez")
        res.ior = 1.40
    return res


def lips(ctx: RecipeContext) -> RecipeResult:
    """
    Labios: estrías verticales, borde del bermellón, gradación de tono y un
    brillo húmedo que sólo aparece en el centro del labio.
    """
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        return ctx.result

    tone = ctx.f("Tono", 0.5)
    detail = ctx.f("Detalle", 1.0)
    striae_p = ctx.f("Estrías", 0.75)
    crack_p = ctx.f("Grietas", 0.25)
    border_p = ctx.f("Borde", 0.6)
    gloss_p = ctx.f("Brillo", 0.65)

    # ------------------------------------------------------------------
    # Altura: estrías verticales del labio
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if striae_p > 1e-4:
        stri = texlib.striations(b, coords, count=ctx.detail_scale(46.0),
                                 wobble=0.06, thickness=0.55, axis="U",
                                 seed_offset=(5.0, 83.0, 13.0),
                                 label="Estrías del labio")
        if stri is not None:
            layers.append((stri, -0.00035 * striae_p * detail))
    grain = texlib.fbm(b, coords, scale=ctx.detail_scale(900.0), detail=6.0,
                       roughness=0.5, seed_offset=(31.0, 7.0, 59.0),
                       label="Grano del labio")
    if grain is not None:
        layers.append((grain, 0.00008 * detail))
    cracks: Any = None
    if crack_p > 1e-4:
        cracks = texlib.crackle(b, coords, scale=ctx.detail_scale(16.0),
                                width=0.035 * crack_p, warp_amount=0.55,
                                seed_offset=(71.0, 17.0, 43.0),
                                label="Grietas del labio")
        if cracks is not None:
            layers.append((cracks, -0.00045 * crack_p * detail))

    height = ctx.micro_detail(layers, label="Altura del labio")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del labio") if height else None

    # ------------------------------------------------------------------
    # Color
    # ------------------------------------------------------------------
    ramp = b.color_ramp([
        (0.00, ctx.c("Color claro")),
        (0.55, ctx.c("Color medio")),
        (1.00, ctx.c("Color oscuro")),
    ], interpolation="LINEAR", label="Rampa del labio")
    color: Any = None
    if ramp is not None:
        b.link(b.value(tone, label="Tono"), in_socket(ramp.node, "Fac", 0))
        color = ramp

    # Variación vertical: el labio es más oscuro cerca de la comisura y de la
    # línea de contacto entre labios.
    sep = b.add("ShaderNodeSeparateColor", label="Separar UV")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    v_grad: Any = None
    if sep is not None:
        b.link(ctx.coords("UV", scaled=False), in_socket(sep, "Color", 0))
        v_grad = out_socket(sep, "Green", 1)
    if color is not None and v_grad is not None:
        vertical = b.map_range(v_grad, 0.0, 1.0, 0.75, 1.05, clamp=True,
                               label="Gradación vertical")
        mod = b.mix_rgb("MULTIPLY", 0.55, color, b.math("MULTIPLY", color, vertical),
                        label="Labio graduado")
        if mod is not None:
            color = mod

    # Borde del bermellón: línea más saturada y oscura en el contorno.
    if color is not None and border_p > 1e-4:
        border = texlib.cellular(b, coords, scale=ctx.detail_scale(2.2),
                                 smoothness=0.55, edge_width=0.10, invert=True,
                                 seed_offset=(3.0, 11.0, 29.0),
                                 label="Borde bermellón")
        if border is not None:
            edge = b.map_range(border, 0.55, 0.95, 0.0, 1.0, clamp=True)
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", edge, border_p * 0.55),
                             color, (0.62, 0.34, 0.38, 1.0), label="Borde")
            if dark is not None:
                color = dark

    # Grietas oscurecidas
    if color is not None and cracks is not None:
        dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cracks, 0.65),
                         color, (0.40, 0.22, 0.24, 1.0), label="Grieta oscura")
        if dark is not None:
            color = dark

    # Cavidad: oscurece la línea entre labios
    cavity = ctx.cavity(radius=0.004, label="Cavidad del labio")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.5),
                          color, (0.48, 0.34, 0.34, 1.0), label="Surco")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.f("Saturación", 1.15) * ctx.g("color_saturation", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # Rugosidad / brillo húmedo
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.28)
    rough_val = 0.55 - 0.42 * base_rough
    rough: Any = b.value(rough_val, label="Rugosidad del labio")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.10),
                       label="Estría matea")
    # El brillo húmedo se concentra en el centro del labio, no en el borde.
    wet_zone: Any = None
    if v_grad is not None:
        wet_zone = b.map_range(v_grad, 0.25, 0.62, 0.0, 1.0,
                               interpolation="SMOOTHSTEP", clamp=True,
                               label="Zona húmeda")
    if rough is not None and wet_zone is not None and gloss_p > 1e-4:
        rough = b.math("MULTIPLY_ADD", rough, 1.0 - 0.65 * gloss_p, 0.0,
                       label="Base")
        rough = b.math("ADD", rough, b.math("MULTIPLY", wet_zone, -0.10 * gloss_p))
    rough = b.clamp(rough, 0.02, 0.9, label="Rugosidad final")

    # ------------------------------------------------------------------
    # Salida
    # ------------------------------------------------------------------
    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.55
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.9) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.clamp(sss_w * 0.55, 0.0, 1.0)
        r_mm = 9.0 * ctx.g("sss_radius_scale", 1.0)
        res.sss_radius = (r_mm / 1000.0, r_mm / 1000.0 * 0.30, r_mm / 1000.0 * 0.22)
        res.sss_color = b.rgb((0.78, 0.16, 0.16, 1.0), label="Sangre del labio")
    trans = ctx.f("Translucidez", 0.35)
    if trans > 1e-3:
        res.transmission = b.value(min(0.2, trans * 0.18), label="Translúcido")
        res.ior = 1.42

    if gloss_p > 1e-3 and ctx.on("use_coat"):
        coat_w: Any = b.value(gloss_p * 0.55, label="Barniz")
        if wet_zone is not None:
            coat_w = b.math("MULTIPLY", wet_zone, gloss_p * 0.75, label="Barniz")
        res.coat_weight = b.clamp(coat_w, 0.0, 1.0)
        res.coat_roughness = 0.035
        res.coat_ior = 1.36

    ctx.result = res
    return res
