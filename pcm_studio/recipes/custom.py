# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Receta genérica.

Zona "comodín" para todo lo que no encaje en el catálogo (ropa, cuero, metal de
un piercing, una prótesis…).  Expone los controles esenciales y aplica las
mismas utilidades de micro-relieve y cavidad que las zonas especializadas, de
modo que el resultado sigue siendo coherente con el resto del personaje.

También sirve como **fallback**: si una zona declara una receta que no existe,
el ensamblador usa esta en vez de fallar.
"""

from __future__ import annotations

from typing import Any, Tuple

from .. import texlib
from ..shaderkit import in_socket, out_socket
from .base import (
    RecipeContext,
    RecipeResult,
    clamp_color,
    contrast,
    saturate,
)

__all__ = ("custom", "fallback")


def custom(ctx: RecipeContext) -> RecipeResult:
    """Material genérico ajustable."""
    b = ctx.b
    res = RecipeResult()
    coords = ctx.coords()
    if coords is None:
        ctx.result = res
        return res

    mix_f = ctx.f("Mezcla", 0.5)
    spot_scale = ctx.f("Escala de mancha", 6.0)
    metallic = ctx.f("Metalicidad", 0.0)
    rough_p = ctx.f("Rugosidad", 0.5)
    sss_w = ctx.f("SSS", 0.0)
    transmission = ctx.f("Transmisión", 0.0)
    ior = ctx.f("IOR", 1.5)
    wet = ctx.f("Humedad", 0.0)
    detail = ctx.f("Detalle", 1.0)

    # ------------------------------------------------------------------
    # Color: dos tintes mezclados por un patrón orgánico
    # ------------------------------------------------------------------
    pattern = texlib.fbm(b, coords, scale=ctx.detail_scale(max(0.2, spot_scale)),
                         detail=6.0, roughness=0.55,
                         seed_offset=(17.0, 43.0, 7.0), label="Patrón")
    color: Any = b.rgb(ctx.c("Color A"), label="Color A")
    color_b = b.rgb(ctx.c("Color B"), label="Color B")
    if pattern is not None and color_b is not None and color is not None:
        # la posición de mezcla combina el slider del usuario con el patrón
        blend = b.math("MULTIPLY_ADD", pattern, 0.6, max(0.0, min(1.0, mix_f)) * 0.7 + 0.15,
                       label="Mezcla")
        blend = b.clamp(blend, 0.0, 1.0)
        mixed = b.mix_rgb("MIX", blend, color, color_b, label="Mezcla de colores")
        if mixed is not None:
            color = mixed

    # cavidad: ensucia los huecos (da profundidad inmediata)
    cavity = ctx.cavity(radius=0.006, label="Cavidad")
    if color is not None and cavity is not None:
        shade = b.mix_rgb("MULTIPLY", b.math("MULTIPLY", cavity, 0.55),
                          color, (0.42, 0.40, 0.40, 1.0), label="Huecos")
        if shade is not None:
            color = shade

    color = saturate(b, color, ctx.f("Saturación", 1.0) * ctx.g("color_saturation", 1.0))
    color = brightness_safe(b, color, ctx.f("Brillo", 1.0))
    color = contrast(b, color, ctx.g("color_contrast", 1.0))
    if ctx.g("clamp_basecolor", 1.0) > 0.5 and color is not None:
        color = clamp_color(b, color)

    # ------------------------------------------------------------------
    # Altura: relieve genérico multi-escala
    # ------------------------------------------------------------------
    layers: list[Tuple[Any, float]] = []
    macro = texlib.fbm(b, coords, scale=ctx.detail_scale(max(0.5, spot_scale * 3.0)),
                       detail=4.0, roughness=0.55,
                       seed_offset=(71.0, 13.0, 29.0), label="Relieve grande")
    if macro is not None:
        layers.append((b.math("SUBTRACT", macro, 0.5), 0.0014 * detail))
    micro = texlib.fbm(b, coords, scale=ctx.detail_scale(620.0), detail=6.0,
                       roughness=0.5, seed_offset=(37.0, 91.0, 5.0),
                       label="Relieve fino")
    if micro is not None:
        layers.append((b.math("SUBTRACT", micro, 0.5), 0.00018 * detail))

    height = ctx.micro_detail(layers, label="Altura genérica")
    normal = ctx.bump_from(height, distance=1.0, label="Normal genérica") if height else None

    # ------------------------------------------------------------------
    # Superficie
    # ------------------------------------------------------------------
    rough_val = max(0.02, min(1.0, rough_p)) * ctx.g("roughness_scale", 1.0)
    rough: Any = b.value(max(0.02, min(1.0, rough_val)), label="Rugosidad")
    if height is not None:
        var = ctx.f("Variación de rugosidad", 0.35)
        rough = b.math("ADD", rough, b.math("MULTIPLY", height, 0.22 * var),
                       label="Relieve modifica rugosidad")
    if wet > 1e-4:
        rough = b.math("MULTIPLY", rough, 1.0 - 0.6 * wet, label="Humedad")
    rough = b.clamp(rough, 0.02, 1.0, label="Rugosidad final")

    res.base_color = color
    res.roughness = rough
    res.metallic = b.value(max(0.0, min(1.0, metallic)), label="Metálico")
    res.specular = 0.5
    res.normal_detail = normal
    res.detail_height = height
    res.ior = max(1.0, ior)

    if transmission > 1e-4:
        res.transmission = b.value(min(1.0, transmission), label="Transmisión")

    if sss_w > 1e-4:
        res.sss_weight = b.value(min(1.0, sss_w * ctx.g("sss_scale", 1.0) * 0.6),
                                 label="SSS")
        res.sss_radius = (0.0030, 0.0012, 0.0009)
        res.sss_color = b.rgb(ctx.c("Color SSS"), label="Color SSS")

    if wet > 1e-3 and ctx.on("use_coat"):
        res.coat_weight = b.value(min(1.0, wet), label="Coat")
        res.coat_roughness = 0.02
        res.coat_ior = 1.333

    ctx.result = res
    return res


def brightness_safe(b, color: Any, amount: float) -> Any:
    """Atajo local para no importar todo el módulo base."""
    from .base import brightness

    return brightness(b, color, amount)


#: alias semántico: el ensamblador usa ``fallback`` cuando falta una receta
fallback = custom
