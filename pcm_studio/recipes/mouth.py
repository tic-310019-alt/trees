# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Recetas de la cavidad bucal.

**Dientes.** El error típico es pintar el diente de blanco plano.  Un diente
real es esmalte *translúcido* sobre dentina *amarilla*: por eso el borde incisal
se ve más claro y azulado (no hay dentina detrás) y el tercio cervical más
saturado y cálido.  Aquí se construye así:

* gradiente cervical→incisal en espacio de objeto (funciona en cualquier
  topología de dentadura, sin depender del UV),
* periquimatias (estrías horizontales finísimas del esmalte),
* micro-desgaste y rayado,
* placa y manchas concentradas en el cuello,
* transmisión creciente hacia el borde,
* SSS cálido para la luz que entra por el esmalte y sale teñida por la dentina,
* oscurecimiento interdental.

**Encías.** Punteado de piel de naranja, festoneado pálido en el margen,
melanosis en manchas y vascularización difusa.

**Lengua.** Papilas filiformes (punteado fino) y fungiformes (mota roja
dispersa), surco medio y gradiente de humedad.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from .. import compat, texlib
from ..shaderkit import NodeOut, in_socket, out_socket
from .base import (
    RecipeContext,
    RecipeResult,
    clamp_color,
    saturate,
)

__all__ = ("teeth", "gums", "tongue")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _separate_axis(b, coords: Any, axis: str = "Z") -> Optional[Any]:
    """Componente X/Y/Z de un vector."""
    sep = b.add("ShaderNodeSeparateXYZ", label=f"Separar {axis}")
    if sep is None:
        sep = b.add("ShaderNodeSeparateColor")
        if sep is None:
            return None
        b.link(coords, in_socket(sep, "Vector", "Color", 0))
        return out_socket(sep, {"X": "Red", "Y": "Green", "Z": "Blue"}[axis], 0)
    b.link(coords, in_socket(sep, "Vector", 0))
    return out_socket(sep, axis, 0)


def _tooth_gradient(ctx: RecipeContext, *,
                    axis: str = "Z") -> Optional[Any]:
    """
    Gradiente 0 (cuello/cervical) → 1 (borde incisal) en espacio de objeto.

    Se normaliza con ``MapRange`` entre los extremos reales del modelo usando
    una rampa suave; si el objeto no está alineado el usuario puede cambiar el
    eje con el parámetro ``Eje del gradiente``.
    """
    b = ctx.b
    axis = ctx.p("Eje del diente", axis)
    coords = ctx.coords("Object", scaled=False)
    if coords is None:
        return None
    comp = _separate_axis(b, coords, str(axis).upper()[-1])
    if comp is None:
        return None
    lo = ctx.f("Base del diente", -0.5)
    hi = ctx.f("Punta del diente", 0.5)
    if abs(hi - lo) < 1e-4:
        hi = lo + 1.0
    return b.map_range(comp, min(lo, hi), max(lo, hi), 0.0, 1.0,
                       interpolation="SMOOTHSTEP", clamp=True,
                       label="Gradiente incisal")


# ---------------------------------------------------------------------------
# DIENTES
# ---------------------------------------------------------------------------

def teeth(ctx: RecipeContext) -> RecipeResult:
    """Esmalte translúcido sobre dentina."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    obj_coords = ctx.coords("Object", scaled=False)

    whiteness = ctx.f("Blancura", 0.65)
    yellowing = ctx.f("Amarilleo", 0.35)
    perikymata_p = ctx.f("Periquimatias", 0.35)
    wear_p = ctx.f("Desgaste", 0.25)
    plaque_p = ctx.f("Placa", 0.10)
    stain_p = ctx.f("Manchas", 0.08)
    incisal_p = ctx.f("Translucidez incisal", 0.55)
    cervical_p = ctx.f("Gradiente cervical", 0.5)
    sep_p = ctx.f("Separación", 0.0)
    detail = ctx.f("Detalle", 1.0)

    grad = _tooth_gradient(ctx)

    # ------------------------------------------------------------------
    # 1. Color
    # ------------------------------------------------------------------
    enamel = b.rgb(ctx.c("Color esmalte"), label="Esmalte")
    dentin = b.rgb(ctx.c("Color dentina"), label="Dentina")
    color: Any = enamel

    # 1.1 la dentina asoma más en el tercio cervical
    if color is not None and dentin is not None and grad is not None and cervical_p > 1e-4:
        dentin_mask = b.map_range(grad, 0.0, 0.75, 1.0, 0.0, clamp=True,
                                  label="Zona de dentina")
        dentin_mask = b.math("MULTIPLY", dentin_mask, cervical_p, label="Cervical ×")
        mixed = b.mix_rgb("MIX", dentin_mask, color, dentin, label="Dentina bajo esmalte")
        if mixed is not None:
            color = mixed

    # 1.2 blancura / amarilleo globales
    if color is not None:
        ramp = b.color_ramp([
            (0.00, (0.78, 0.70, 0.52, 1.0)),   # amarillento
            (0.50, (0.88, 0.86, 0.79, 1.0)),   # marfil
            (1.00, (0.96, 0.96, 0.94, 1.0)),   # blanco clínico
        ], interpolation="LINEAR", label="Blancura")
        if ramp is not None:
            b.link(b.value(max(0.0, min(1.0, whiteness)), label="Blancura"),
                   in_socket(ramp.node, "Fac", 0))
            color = b.mix_rgb("MULTIPLY", 0.55, color, ramp, label="Blancura aplicada")
        warm = b.mix_rgb("MULTIPLY", yellowing * 0.45, color,
                         (1.0, 0.94, 0.78, 1.0), label="Cálido")
        if warm is not None:
            color = warm

    # 1.3 periquimatias: estrías finas del esmalte (apenas visibles pero dan vida)
    if perikymata_p > 1e-4 and coords is not None:
        stri = texlib.striations(b, coords, count=ctx.detail_scale(110.0),
                                 wobble=0.04, thickness=0.6, axis="V",
                                 seed_offset=(3.0, 41.0, 17.0),
                                 label="Periquimatias")
        if stri is not None:
            mod = b.map_range(stri, 0.0, 1.0, 0.965, 1.015, clamp=True,
                              label="Modulación")
            tinted = b.mix_rgb("MULTIPLY", perikymata_p * 0.8, color,
                               b.math("MULTIPLY", color, mod), label="Estrías")
            if tinted is not None:
                color = tinted

    # 1.4 placa en el cuello
    if plaque_p > 1e-4 and grad is not None:
        plaque_zone = b.map_range(grad, 0.0, 0.28, 1.0, 0.0, clamp=True,
                                  label="Zona de placa")
        rough_noise = texlib.fbm(b, coords, scale=ctx.detail_scale(90.0),
                                 detail=4.0, roughness=0.6,
                                 seed_offset=(61.0, 7.0, 23.0), label="Placa")
        if rough_noise is not None:
            plaque = b.math("MULTIPLY", plaque_zone,
                            b.map_range(rough_noise, 0.35, 0.85, 0.0, 1.0,
                                        clamp=True), label="Placa")
            tinted = b.mix_rgb("MIX", b.math("MULTIPLY", plaque, plaque_p),
                               color, (0.82, 0.74, 0.50, 1.0), label="Placa")
            if tinted is not None:
                color = tinted

    # 1.5 manchas puntuales (café, tabaco, decoloración)
    if stain_p > 1e-4 and coords is not None:
        spots = texlib.speckle_field(b, coords, scale=ctx.detail_scale(70.0),
                                     density=stain_p, size=0.10,
                                     seed_offset=(97.0, 13.0, 41.0),
                                     label="Manchas")
        if spots is not None:
            tinted = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", spots, stain_p * 2.2),
                               color, (0.66, 0.55, 0.40, 1.0), label="Mancha")
            if tinted is not None:
                color = tinted

    # 1.6 separación interdental: oscurece los laterales del diente
    if sep_p > 1e-4 and obj_coords is not None:
        x = _separate_axis(b, obj_coords, "X")
        if x is not None:
            # el borde del diente en X es la zona de contacto
            side = b.map_range(b.math("ABSOLUTE", x, 0.0), 0.02, 0.10, 0.0, 1.0,
                               clamp=True, label="Lateral del diente")
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", side, sep_p * 0.75),
                             color, (0.44, 0.42, 0.40, 1.0), label="Separación")
            if dark is not None:
                color = dark

    # 1.7 cavidad: ensucia el surco gingival y los huecos
    cavity = ctx.cavity(radius=0.004, label="Cavidad dental")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.45),
                          color, (0.52, 0.50, 0.47, 1.0), label="Surco")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # 2. Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if perikymata_p > 1e-4:
        stri = texlib.striations(b, coords, count=ctx.detail_scale(110.0),
                                 wobble=0.04, thickness=0.6, axis="V",
                                 seed_offset=(3.0, 41.0, 17.0),
                                 label="Relieve periquimatias")
        if stri is not None:
            layers.append((stri, 0.000035 * perikymata_p * detail))
    if wear_p > 1e-4:
        scuff = texlib.scratch(b, coords, scale=ctx.detail_scale(520.0),
                               density=wear_p * 0.35, length=14.0, angle_deg=22.0,
                               seed_offset=(29.0, 5.0, 67.0), label="Desgaste")
        if scuff is not None:
            layers.append((scuff, -0.00012 * wear_p * detail))
    micro = texlib.fbm(b, coords, scale=ctx.detail_scale(1200.0), detail=5.0,
                       roughness=0.5, seed_offset=(11.0, 83.0, 5.0),
                       label="Micro esmalte")
    if micro is not None:
        layers.append((micro, 0.000020 * detail))

    height = ctx.micro_detail(layers, label="Altura del diente")
    normal = ctx.bump_from(height, distance=1.0, label="Normal del diente") if height else None

    # ------------------------------------------------------------------
    # 3. Rugosidad / transmisión / SSS
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.14)
    rough_val = 0.30 - 0.24 * base_rough
    rough: Any = b.value(rough_val, label="Rugosidad esmalte")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.10),
                       label="Desgaste matea")
    # la placa es mate
    if plaque_p > 1e-4 and grad is not None:
        plaque_zone = b.map_range(grad, 0.0, 0.25, 1.0, 0.0, clamp=True)
        rough = b.math("ADD", rough, b.math("MULTIPLY", plaque_zone, plaque_p * 0.22),
                       label="Placa matea")
    rough = b.clamp(rough, 0.008, 0.85, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = b.value(min(1.5, 0.5 * ctx.f("Brillo", 0.9) + 0.1),
                           label="Specular esmalte")
    res.normal_detail = normal
    res.detail_height = height

    # Transmisión en el borde incisal (no hay dentina detrás)
    if incisal_p > 1e-4 and grad is not None:
        edge = b.map_range(grad, 0.62, 1.0, 0.0, 1.0, clamp=True,
                           label="Borde incisal")
        res.transmission = b.math("MULTIPLY", edge, min(0.45, incisal_p * 0.5),
                                  label="Transmisión incisal")
        # el borde se ve más frío y claro
        if color is not None:
            cool = b.mix_rgb("MIX", b.math("MULTIPLY", edge, incisal_p * 0.45),
                             color, (0.90, 0.93, 0.95, 1.0), label="Borde frío")
            if cool is not None:
                res.base_color = cool
        res.ior = 1.63
    else:
        res.ior = 1.63

    sss_w = ctx.f("SSS", 0.30) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        weight: Any = b.value(min(0.45, sss_w * 0.45), label="SSS del diente")
        if grad is not None:
            # menos SSS en el borde (ahí domina la transmisión)
            weight = b.math("MULTIPLY", weight,
                            b.map_range(grad, 0.0, 0.85, 1.0, 0.25, clamp=True),
                            label="SSS cervical")
        res.sss_weight = weight
        res.sss_radius = (0.0016, 0.0011, 0.0007)
        res.sss_color = b.rgb((0.86, 0.72, 0.48, 1.0), label="Dentina")

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# ENCÍAS
# ---------------------------------------------------------------------------

def gums(ctx: RecipeContext) -> RecipeResult:
    """Mucosa masticatoria: punteada, festoneada, húmeda."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    tone = ctx.f("Tono", 0.5)
    stipple_p = ctx.f("Punteado", 0.65)
    scallop_p = ctx.f("Festoneado", 0.55)
    melanosis_p = ctx.f("Melanosis", 0.12)
    vascular_p = ctx.f("Vascularización", 0.25)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # Color
    # ------------------------------------------------------------------
    ramp = b.color_ramp([
        (0.00, ctx.c("Color claro")),
        (0.60, _mix_colors(ctx.c("Color claro"), ctx.c("Color oscuro"), 0.62)),
        (1.00, ctx.c("Color oscuro")),
    ], interpolation="LINEAR", label="Rampa de encía")
    color: Any = ramp
    if ramp is not None:
        b.link(b.value(max(0.0, min(1.0, tone)), label="Tono"),
               in_socket(ramp.node, "Fac", 0))

    # variación regional
    mottle = texlib.fbm(b, coords, scale=ctx.detail_scale(9.0), detail=4.0,
                        roughness=0.55, seed_offset=(17.0, 43.0, 7.0),
                        label="Variación de encía")
    if color is not None and mottle is not None:
        mod = b.map_range(mottle, 0.35, 0.72, 0.88, 1.12, clamp=True,
                          label="Modulación")
        tinted = b.mix_rgb("MULTIPLY", 0.7, color, b.math("MULTIPLY", color, mod),
                           label="Encía moteada")
        if tinted is not None:
            color = tinted

    # vascularización difusa (enrojecimiento)
    if vascular_p > 1e-4:
        vasc = texlib.fbm(b, coords, scale=ctx.detail_scale(4.5), detail=3.0,
                          roughness=0.6, seed_offset=(83.0, 11.0, 29.0),
                          label="Vascularización")
        if vasc is not None and color is not None:
            mask = b.map_range(vasc, 0.45, 0.85, 0.0, 1.0, clamp=True)
            red = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", mask, vascular_p * 0.8),
                            color, (1.0, 0.58, 0.56, 1.0), label="Rojo difuso")
            if red is not None:
                color = red

    # melanosis: manchas marrones irregulares
    if melanosis_p > 1e-4:
        mel = texlib.speckle_field(b, coords, scale=ctx.detail_scale(28.0),
                                   density=melanosis_p, size=0.30,
                                   seed_offset=(37.0, 5.0, 91.0),
                                   label="Melanosis")
        if mel is not None and color is not None:
            tinted = b.mix_rgb("MIX", b.math("MULTIPLY", mel, min(1.0, melanosis_p * 3.0)),
                               color, ctx.c("Color melanosis"), label="Melanosis")
            if tinted is not None:
                color = tinted

    # festoneado: arco pálido junto al diente (la encía se afina ahí)
    scallop: Any = None
    if scallop_p > 1e-4:
        scallop = texlib.cellular(b, coords, scale=ctx.detail_scale(11.0),
                                  smoothness=0.55, edge_width=0.16, invert=True,
                                  seed_offset=(3.0, 71.0, 19.0),
                                  label="Festoneado")
        if scallop is not None and color is not None:
            pale = b.mix_rgb("MIX", b.math("MULTIPLY", scallop, scallop_p * 0.55),
                             color, ctx.c("Color claro"), label="Margen pálido")
            if pale is not None:
                color = pale

    cavity = ctx.cavity(radius=0.005, label="Cavidad gingival")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.40),
                          color, (0.52, 0.28, 0.30, 1.0), label="Surco gingival")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # Altura: punteado (piel de naranja)
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if stipple_p > 1e-4:
        stip = texlib.stipple(b, coords, scale=ctx.detail_scale(170.0),
                              density=0.30, softness=0.42,
                              seed_offset=(13.0, 47.0, 5.0), label="Punteado")
        if stip is not None:
            layers.append((stip, 0.00022 * stipple_p * detail))
    if scallop is not None:
        layers.append((scallop, -0.00035 * scallop_p * detail))
    micro = texlib.fbm(b, coords, scale=ctx.detail_scale(1100.0), detail=5.0,
                       roughness=0.5, seed_offset=(23.0, 9.0, 61.0),
                       label="Micro mucosa")
    if micro is not None:
        layers.append((micro, 0.000022 * detail))

    height = ctx.micro_detail(layers, label="Altura de encía")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de encía") if height else None

    # ------------------------------------------------------------------
    # Rugosidad
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.22)
    rough: Any = b.value(0.40 - 0.30 * base_rough, label="Rugosidad encía")
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.12),
                       label="Punteado matea")
    rough = b.clamp(rough, 0.02, 0.85, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.52
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.85) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.6, sss_w * 0.55), label="SSS encía")
        res.sss_radius = (0.0035, 0.0012, 0.0009)
        res.sss_color = b.rgb((0.80, 0.20, 0.20, 1.0), label="Sangre gingival")
    if ctx.on("use_coat"):
        res.coat_weight = b.value(0.22, label="Saliva")
        res.coat_roughness = 0.05
        res.coat_ior = 1.334

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# LENGUA
# ---------------------------------------------------------------------------

def tongue(ctx: RecipeContext) -> RecipeResult:
    """Papilas, surco medio y gradiente de humedad."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    tone = ctx.f("Tono", 0.5)
    papillae_p = ctx.f("Papilas", 0.70)
    sulcus_p = ctx.f("Surco medio", 0.50)
    wet_p = ctx.f("Humedad", 0.55)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # Color
    # ------------------------------------------------------------------
    base = b.rgb(ctx.c("Color base"), label="Base de lengua")
    dorsum = b.rgb(ctx.c("Color dorso"), label="Dorso")
    color: Any = base

    # el dorso (centro) es más pálido que los bordes
    sep = b.add("ShaderNodeSeparateColor", label="Separar UV")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    center_mask: Any = None
    if sep is not None:
        b.link(ctx.coords("UV", scaled=False), in_socket(sep, "Color", 0))
        u = out_socket(sep, "Red", 0)
        du = b.math("SUBTRACT", u, ctx.f("Centro U", 0.5), label="ΔU")
        ad = b.math("ABSOLUTE", du, 0.0)
        center_mask = b.map_range(ad, 0.0, ctx.f("Ancho del dorso", 0.22),
                                  1.0, 0.0, interpolation="SMOOTHSTEP",
                                  clamp=True, label="Dorso")
    if color is not None and dorsum is not None and center_mask is not None:
        mixed = b.mix_rgb("MIX", b.math("MULTIPLY", center_mask, 0.65),
                          color, dorsum, label="Dorso pálido")
        if mixed is not None:
            color = mixed

    # tono global
    if color is not None:
        ramp = b.color_ramp([
            (0.00, (0.72, 0.30, 0.34, 1.0)),
            (0.50, (0.78, 0.36, 0.40, 1.0)),
            (1.00, (0.60, 0.24, 0.34, 1.0)),
        ], interpolation="LINEAR", label="Tono de lengua")
        if ramp is not None:
            b.link(b.value(max(0.0, min(1.0, tone)), label="Tono"),
                   in_socket(ramp.node, "Fac", 0))
            color = b.mix_rgb("MULTIPLY", 0.5, color, ramp, label="Tono aplicado")

    # papilas fungiformes: motas rojas dispersas en la punta y bordes
    if papillae_p > 1e-4:
        fung = texlib.speckle_field(b, coords, scale=ctx.detail_scale(38.0),
                                    density=0.16, size=0.22,
                                    seed_offset=(41.0, 17.0, 7.0),
                                    label="Papilas fungiformes")
        if fung is not None and color is not None:
            red = b.mix_rgb("MIX", b.math("MULTIPLY", fung, papillae_p * 0.85),
                            color, (0.86, 0.28, 0.30, 1.0), label="Papilas rojas")
            if red is not None:
                color = red

    # surco medio
    sulcus: Any = None
    if sulcus_p > 1e-4 and center_mask is not None:
        sulcus = b.map_range(center_mask, 0.85, 1.0, 0.0, 1.0, clamp=True,
                             label="Surco medio")
        if sulcus is not None and color is not None:
            dark = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", sulcus, sulcus_p * 0.5),
                             color, (0.62, 0.42, 0.44, 1.0), label="Surco")
            if dark is not None:
                color = dark

    cavity = ctx.cavity(radius=0.006, label="Cavidad de lengua")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.35),
                          color, (0.58, 0.32, 0.34, 1.0), label="Pliegues")
        if shade is not None:
            color = shade

    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # Altura
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    if papillae_p > 1e-4:
        filiform = texlib.stipple(b, coords, scale=ctx.detail_scale(230.0),
                                  density=0.34, softness=0.40,
                                  seed_offset=(7.0, 83.0, 29.0),
                                  label="Papilas filiformes")
        if filiform is not None:
            layers.append((filiform, 0.00028 * papillae_p * detail))
    if sulcus is not None:
        layers.append((sulcus, -0.00090 * sulcus_p * detail))
    # pliegues anchos de la lengua
    folds = texlib.ridged(b, coords, scale=ctx.detail_scale(7.0), detail=3.0,
                          roughness=0.5, sharpness=1.1,
                          seed_offset=(53.0, 11.0, 19.0), label="Pliegues")
    if folds is not None:
        layers.append((b.math("SUBTRACT", 1.0, folds, label="Surco ancho"),
                       0.00055 * detail))

    height = ctx.micro_detail(layers, label="Altura de lengua")
    normal = ctx.bump_from(height, distance=1.0, label="Normal de lengua") if height else None

    # ------------------------------------------------------------------
    # Rugosidad: húmeda en la punta, más seca en el dorso
    # ------------------------------------------------------------------
    base_rough = ctx.f("Rugosidad", 0.30)
    rough: Any = b.value(0.46 - 0.30 * base_rough, label="Rugosidad lengua")
    if wet_p > 1e-4:
        wet_zone: Any = b.value(wet_p, label="Humedad")
        if center_mask is not None:
            # el dorso es más seco que la punta y los bordes
            wet_zone = b.math("MULTIPLY_ADD", center_mask, -0.45 * wet_p, wet_p,
                              label="Humedad por zona")
        delta = b.math("MULTIPLY", wet_zone, -0.22, label="Δ humedad")
        rough = b.math("ADD", rough, delta)
    if height is not None:
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.10))
    rough = b.clamp(rough, 0.02, 0.9, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = 0.0
    res.specular = 0.55
    res.normal_detail = normal
    res.detail_height = height

    sss_w = ctx.f("SSS", 0.95) * ctx.g("sss_scale", 1.0)
    if sss_w > 1e-4:
        res.sss_weight = b.value(min(0.65, sss_w * 0.6), label="SSS lengua")
        res.sss_radius = (0.0045, 0.0016, 0.0012)
        res.sss_color = b.rgb((0.82, 0.19, 0.19, 1.0), label="Sangre")
    if ctx.on("use_coat") and wet_p > 1e-3:
        coat_w: Any = b.value(wet_p * 0.5, label="Saliva")
        if wet_zone is not None:
            coat_w = b.math("MULTIPLY", wet_zone, 0.55, label="Saliva por zona")
        res.coat_weight = b.clamp(coat_w, 0.0, 0.7, label="Coat de saliva")
        res.coat_roughness = 0.03
        res.coat_ior = 1.334

    ctx.result = res
    return res


# ---------------------------------------------------------------------------
# Utilidades de color en CPU (para rampas precalculadas)
# ---------------------------------------------------------------------------

def _mix_colors(a: Sequence[float], c: Sequence[float], t: float
                ) -> Tuple[float, float, float, float]:
    t = max(0.0, min(1.0, t))
    out = []
    for i in range(4):
        va = a[i] if i < len(a) else 1.0
        vc = c[i] if i < len(c) else 1.0
        out.append(va * (1.0 - t) + vc * t)
    return (out[0], out[1], out[2], out[3])
