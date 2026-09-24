# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Presets de estilo.

Un **estilo** reescribe de forma coherente los parámetros de todas las zonas y
los ajustes globales del material.  Es lo que separa "piel fotográfica" de
"piel estilo Sims 4": no es sólo menos detalle, es otra *filosofía* de
sombreado (SSS, cavidad, contraste de color, rugosidad, nitidez de la normal).

El orden de resolución de un parámetro es:

    valor del usuario  >  override de zona del estilo  >  override global del
    estilo  >  valor por defecto de la zona

Los overrides se declaran por **nombre de parámetro**, de modo que un preset
funciona aunque una zona añada parámetros nuevos más adelante.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = (
    "Style",
    "STYLES",
    "STYLE_IDS",
    "get_style",
    "default_style_id",
    "resolve_param",
    "resolve_params",
    "GLOBAL_KEYS",
)


# ---------------------------------------------------------------------------
# Definición
# ---------------------------------------------------------------------------

@dataclass
class Style:
    """Preset de estilo."""

    id: str
    name_es: str
    name_en: str
    desc_es: str
    desc_en: str

    #: multiplicadores y ajustes globales del material
    globals: Dict[str, float] = field(default_factory=dict)

    #: overrides por nombre de parámetro, aplicados a TODAS las zonas
    common: Dict[str, Any] = field(default_factory=dict)

    #: overrides por clave de zona -> {nombre de parámetro: valor}
    zones: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    #: overrides por categoría ("Humano" / "Animal" / "Común")
    categories: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    #: resolución de bake recomendada y muestras
    bake_resolution: int = 4096
    bake_samples: int = 64
    pack_orm: bool = True

    def name(self, lang: str = "es") -> str:
        return self.name_en if lang == "en" else self.name_es

    def desc(self, lang: str = "es") -> str:
        return self.desc_en if lang == "en" else self.desc_es

    def override(self, zone_key: str, category: str, param: str) -> Any:
        """Devuelve el override del estilo para un parámetro, o ``None``."""
        z = self.zones.get(zone_key)
        if z and param in z:
            return z[param]
        c = self.categories.get(category)
        if c and param in c:
            return c[param]
        if param in self.common:
            return self.common[param]
        return None


#: claves globales reconocidas por el ensamblador y el bakeador
GLOBAL_KEYS: Tuple[str, ...] = (
    "detail_scale",        # multiplicador de escala del micro-relieve
    "detail_amount",       # multiplicador de la intensidad del relieve
    "normal_strength",     # fuerza global de la normal
    "cavity_strength",     # fuerza de la oclusión de cavidad
    "sss_scale",           # multiplicador del peso de subsurface
    "sss_radius_scale",    # multiplicador del radio de subsurface
    "roughness_scale",     # multiplicador de rugosidad
    "specular_scale",      # multiplicador de Specular IOR Level
    "color_variation",     # multiplicador de la variación cromática
    "color_contrast",      # contraste aplicado al color base
    "color_saturation",    # saturación aplicada al color base
    "micro_contrast",      # contraste del micro-detalle en la normal
    "wear",                # suciedad / desgaste general
    "tiling_scale",        # escala global de coordenadas (personaje grande/pequeño)
    "height_scale",        # escala de la altura para displacement/bake
    "use_pores",           # 0/1: poros visibles
    "use_veins",           # 0/1: red vascular
    "use_wrinkles",        # 0/1: arrugas
    "use_sheen",           # 0/1: sheen / velvet
    "use_coat",            # 0/1: capa de barniz (Coat) para superficies húmedas
    "use_thin_film",       # 0/1: iridiscencia por película fina
    "use_gabor",           # 0/1: usar el nodo Gabor cuando exista
    "smooth_normals",      # 0/1: suavizar la normal geométrica
    "clamp_basecolor",     # 0/1: evitar basecolor fuera de rango para el motor
)


def _g(**kw: float) -> Dict[str, float]:
    """Construye el dict de globales rellenando con neutros lo que falte."""
    base: Dict[str, float] = {
        "detail_scale": 1.0,
        "detail_amount": 1.0,
        "normal_strength": 1.0,
        "cavity_strength": 1.0,
        "sss_scale": 1.0,
        "sss_radius_scale": 1.0,
        "roughness_scale": 1.0,
        "specular_scale": 1.0,
        "color_variation": 1.0,
        "color_contrast": 1.0,
        "color_saturation": 1.0,
        "micro_contrast": 1.0,
        "wear": 0.0,
        "tiling_scale": 1.0,
        "height_scale": 1.0,
        "use_pores": 1.0,
        "use_veins": 1.0,
        "use_wrinkles": 1.0,
        "use_sheen": 1.0,
        "use_coat": 1.0,
        "use_thin_film": 1.0,
        "use_gabor": 1.0,
        "smooth_normals": 1.0,
        "clamp_basecolor": 1.0,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

STYLES: List[Style] = [
    # =======================================================================
    # REALISTA
    # =======================================================================
    Style(
        id="realistic",
        name_es="Realista",
        name_en="Realistic",
        desc_es="PBR fotográfico: micro-superficie completa, SSS por Random Walk, "
                "cavidad, variación cromática y normales con relieve real. "
                "Pensado para primer plano y escaneo.",
        desc_en="Photographic PBR: full micro-surface, Random-Walk SSS, cavity, "
                "chromatic variation and normals with real relief. Meant for "
                "close-ups and scan-quality work.",
        globals=_g(
            detail_scale=1.0,
            detail_amount=1.0,
            normal_strength=1.0,
            cavity_strength=1.0,
            sss_scale=1.0,
            sss_radius_scale=1.0,
            roughness_scale=1.0,
            specular_scale=1.0,
            color_variation=1.0,
            color_contrast=1.0,
            color_saturation=1.0,
            micro_contrast=1.0,
            wear=0.15,
            height_scale=1.0,
        ),
        common={
            "Detalle": 1.0,
            "Escala de detalle": 1.0,
            "Cavidad": 0.55,
            "Rugosidad": None,   # None = no tocar
        },
        zones={
            "skin_body": {"Poros": 0.55, "Arrugas": 0.30, "Vello": 0.22, "SSS": 0.65,
                          "Radio SSS (mm)": 8.0, "Aceite": 0.25},
            "skin_face": {"Poros": 0.75, "Arrugas": 0.50, "SSS": 0.80,
                          "Radio SSS (mm)": 6.0, "Rubor": 0.32, "Aceite": 0.45},
            "skin_thin": {"Translucidez": 0.70, "SSS": 1.10, "Radio SSS (mm)": 12.0},
            "lips": {"Estrías": 0.80, "Brillo": 0.62, "Rugosidad": 0.26},
            "sclera": {"Venas": 0.45, "Rugosidad": 0.11, "Sombra limbal": 0.45},
            "iris": {"Criptas": 0.75, "Surcos": 0.60, "Rugosidad": 0.05},
            "cornea": {"Rugosidad": 0.018, "Transparencia": 0.93},
            "teeth": {"Periquimatias": 0.35, "Desgaste": 0.22, "Rugosidad": 0.13,
                      "Translucidez incisal": 0.55},
            "gums": {"Punteado": 0.65, "Rugosidad": 0.21},
            "tongue": {"Papilas": 0.70, "Humedad": 0.55},
            "nails": {"Crestas": 0.32, "Rugosidad": 0.09, "Translucidez": 0.45},
            "hair": {"Rugosidad": 0.30, "Anisotropía": 0.88},
            "fur": {"Sheen": 0.55, "Rugosidad": 0.52, "Densidad": 0.85},
            "scales": {"Rugosidad": 0.30, "Altura de placa": 0.65, "Desgaste": 0.28},
            "feathers": {"Barbas": 0.72, "Rugosidad": 0.40},
            "hooves": {"Grietas": 0.28, "Rugosidad": 0.44, "Desgaste": 0.38},
            "snout": {"Humedad": 0.72, "Punteado": 0.82, "Rugosidad": 0.17},
            "shell": {"Nácar": 0.42, "Rugosidad": 0.36, "Erosión": 0.35},
            "animal_eye": {"Tapetum": 0.35, "Rugosidad": 0.04},
            "amphibian": {"Mucosidad": 0.78, "Rugosidad": 0.08, "Gránulos": 0.72},
        },
        bake_resolution=4096,
        bake_samples=64,
        pack_orm=True,
    ),

    # =======================================================================
    # ESTILO SIMS 4
    # =======================================================================
    Style(
        id="sims4",
        name_es="Estilo Sims 4",
        name_en="Sims 4 style",
        desc_es="Estilizado limpio tipo The Sims 4: piel satinada sin poros, "
                "color con gradación pintada, rubor y labios planos, ojos "
                "grandes y brillantes, normal casi plana y rugosidad media-alta "
                "uniforme. Se ve bien a cualquier distancia y con poca luz.",
        desc_en="Clean stylised look in the vein of The Sims 4: poreless satin "
                "skin, painterly colour gradation, flat blush and lips, big "
                "glossy eyes, near-flat normals and uniform mid-high roughness. "
                "Reads well at any distance and under cheap lighting.",
        globals=_g(
            detail_scale=0.35,
            detail_amount=0.18,
            normal_strength=0.28,
            cavity_strength=0.22,
            sss_scale=0.35,
            sss_radius_scale=0.60,
            roughness_scale=1.18,
            specular_scale=0.85,
            color_variation=0.42,
            color_contrast=0.88,
            color_saturation=1.14,
            micro_contrast=0.35,
            wear=0.0,
            height_scale=0.25,
            use_pores=0.0,
            use_veins=0.0,
            use_wrinkles=0.0,
            use_sheen=1.0,
            use_coat=0.0,
            use_thin_film=0.0,
            use_gabor=0.0,
            smooth_normals=1.0,
            clamp_basecolor=1.0,
        ),
        common={
            "Detalle": 0.18,
            "Escala de detalle": 0.5,
            "Cavidad": 0.10,
            "Variación": 0.28,
            "Variación de rugosidad": 0.12,
            "Edad": 0.05,
            "Desgaste": 0.0,
            "Suciedad": 0.0,
            "Manchas": None,
        },
        zones={
            # Piel satinada: sin poro, con rubor pintado y brillo suave.
            "skin_body": {"Poros": 0.0, "Arrugas": 0.0, "Vello": 0.0, "SSS": 0.28,
                          "Radio SSS (mm)": 4.0, "Aceite": 0.18, "Rugosidad": 0.52,
                          "Pecas": 0.0},
            "skin_face": {"Poros": 0.0, "Arrugas": 0.0, "SSS": 0.32,
                          "Radio SSS (mm)": 3.5, "Rubor": 0.55, "Ojeras": 0.10,
                          "Barba / sombra": 0.08, "Aceite": 0.22,
                          "Rugosidad": 0.48, "Pecas": 0.0},
            "skin_extremity": {"Sequedad": 0.05, "Pliegues": 0.15, "Nudillos": 0.30,
                               "Rugosidad": 0.55},
            "skin_thin": {"Translucidez": 0.30, "Capilares": 0.05, "SSS": 0.35,
                          "Radio SSS (mm)": 6.0, "Rugosidad": 0.45},
            # Labios planos, saturados, con un solo brillo ancho.
            "lips": {"Estrías": 0.10, "Grietas": 0.0, "Borde": 0.30, "Brillo": 0.72,
                     "Rugosidad": 0.20, "Saturación": 1.30, "SSS": 0.30,
                     "Translucidez": 0.10},
            # Ojos grandes, muy limpios y muy brillantes (marca Sims).
            "sclera": {"Venas": 0.04, "Irritación": 0.0, "Sombra limbal": 0.30,
                       "Amarilleo": 0.0, "Rugosidad": 0.05, "Blancura": 0.90},
            "iris": {"Criptas": 0.16, "Surcos": 0.12, "Colarete": 0.35,
                     "Contraste radial": 0.85, "Limbo": 0.90, "Grosor limbo": 0.14,
                     "Pupila": 0.24, "Rugosidad": 0.02, "SSS": 0.15},
            "cornea": {"Rugosidad": 0.01, "Transparencia": 0.96, "Brillo": 1.25,
                       "Menisco": 0.10},
            "lashes": {"Rugosidad": 0.28, "Anisotropía": 0.5},
            # Dientes blancos uniformes, sin desgaste.
            "teeth": {"Blancura": 0.88, "Amarilleo": 0.14, "Periquimatias": 0.05,
                      "Desgaste": 0.0, "Placa": 0.0, "Manchas": 0.0,
                      "Rugosidad": 0.07, "Translucidez incisal": 0.28,
                      "Separación": 0.15, "SSS": 0.10},
            "gums": {"Punteado": 0.10, "Festoneado": 0.25, "Rugosidad": 0.16,
                     "Melanosis": 0.0, "SSS": 0.30},
            "tongue": {"Papilas": 0.15, "Humedad": 0.70, "Rugosidad": 0.22},
            # Uñas limpias y brillantes.
            "nails": {"Crestas": 0.06, "Desgaste": 0.0, "Rugosidad": 0.05,
                      "Translucidez": 0.30, "Brillo": 1.15},
            "hair": {"Rugosidad": 0.22, "Anisotropía": 0.6, "Folículos": 0.12,
                     "Grasa": 0.10, "Variación": 0.18},
            # Animal: pelaje liso y legible, sin fibra individual.
            "fur": {"Sheen": 0.70, "Rugosidad": 0.62, "Longitud de fibra": 0.25,
                    "Densidad": 0.35, "Anisotropía": 0.45, "Suciedad": 0.0},
            "scales": {"Rugosidad": 0.24, "Altura de placa": 0.35, "Borde": 0.30,
                       "Irregularidad": 0.15, "Desgaste": 0.0},
            "feathers": {"Barbas": 0.20, "Rugosidad": 0.34, "Sheen": 0.55,
                         "Desgaste": 0.0},
            "hooves": {"Grietas": 0.08, "Rugosidad": 0.35, "Desgaste": 0.08},
            "snout": {"Humedad": 0.85, "Punteado": 0.30, "Rugosidad": 0.12},
            "shell": {"Nácar": 0.55, "Rugosidad": 0.22, "Erosión": 0.08},
            "animal_eye": {"Tapetum": 0.55, "Rugosidad": 0.02, "Fibras": 0.30,
                           "Criptas": 0.20},
            "amphibian": {"Mucosidad": 0.95, "Rugosidad": 0.05, "Gránulos": 0.20},
        },
        bake_resolution=2048,
        bake_samples=32,
        pack_orm=True,
    ),

    # =======================================================================
    # PBR ESTILIZADO
    # =======================================================================
    Style(
        id="stylized",
        name_es="PBR estilizado",
        name_en="Stylized PBR",
        desc_es="A medio camino: mantiene la legibilidad del PBR (SSS, cavidad, "
                "rugosidad variada) pero con detalle de baja frecuencia y colores "
                "empujados. Ideal para juegos third-person y móvil de gama alta.",
        desc_en="Halfway house: keeps PBR readability (SSS, cavity, varied "
                "roughness) but with large, low-frequency detail and pushed "
                "colours. Ideal for third-person and high-end mobile.",
        globals=_g(
            detail_scale=0.6,
            detail_amount=0.55,
            normal_strength=0.62,
            cavity_strength=0.65,
            sss_scale=0.70,
            sss_radius_scale=0.85,
            roughness_scale=1.05,
            specular_scale=0.95,
            color_variation=0.72,
            color_contrast=1.10,
            color_saturation=1.10,
            micro_contrast=0.70,
            wear=0.10,
            height_scale=0.6,
            use_pores=0.0,
            use_veins=0.35,
            use_wrinkles=0.45,
            use_sheen=1.0,
            use_coat=0.5,
            use_thin_film=0.35,
            use_gabor=1.0,
        ),
        common={
            "Detalle": 0.55,
            "Escala de detalle": 0.65,
            "Cavidad": 0.35,
            "Variación": 0.65,
            "Edad": 0.20,
        },
        zones={
            "skin_body": {"Poros": 0.12, "Arrugas": 0.35, "SSS": 0.45},
            "skin_face": {"Poros": 0.15, "Arrugas": 0.40, "Rubor": 0.45, "SSS": 0.55},
            "lips": {"Estrías": 0.35, "Brillo": 0.68},
            "sclera": {"Venas": 0.22, "Rugosidad": 0.09},
            "iris": {"Criptas": 0.45, "Surcos": 0.35, "Rugosidad": 0.04},
            "teeth": {"Periquimatias": 0.15, "Desgaste": 0.10, "Rugosidad": 0.10},
            "nails": {"Crestas": 0.15, "Rugosidad": 0.08},
            "fur": {"Sheen": 0.65, "Longitud de fibra": 0.45},
            "scales": {"Altura de placa": 0.55, "Rugosidad": 0.28},
        },
        bake_resolution=2048,
        bake_samples=48,
        pack_orm=True,
    ),

    # =======================================================================
    # ARCILLA / ESCANEO
    # =======================================================================
    Style(
        id="clayscan",
        name_es="Arcilla / escaneo",
        name_en="Clay / scan",
        desc_es="Look de escaneo 3D en arcilla: color casi neutro, todo el peso "
                "en la normal y la rugosidad. Útil para revisar el modelado y "
                "para presentar turnartables.",
        desc_en="Clay-scan look: near-neutral colour, all the weight on the "
                "normal and roughness. Useful to review modelling and for "
                "turntables.",
        globals=_g(
            detail_scale=1.0,
            detail_amount=1.25,
            normal_strength=1.35,
            cavity_strength=1.25,
            sss_scale=0.0,
            roughness_scale=1.0,
            specular_scale=0.65,
            color_variation=0.10,
            color_contrast=0.95,
            color_saturation=0.12,
            micro_contrast=1.25,
            wear=0.0,
            use_thin_film=0.0,
            use_sheen=0.0,
        ),
        common={
            "Color base": (0.62, 0.60, 0.58, 1.0),
            "Color A": (0.62, 0.60, 0.58, 1.0),
            "Color B": (0.40, 0.39, 0.38, 1.0),
            "Saturación": 0.05,
            "Variación": 0.06,
            "SSS": 0.0,
            "Rugosidad": 0.62,
            "Detalle": 1.15,
            "Cavidad": 0.75,
        },
        zones={
            "cornea": {"Transparencia": 0.0, "Rugosidad": 0.35},
            "iris": {"Emisivo": 0.0},
            "amphibian": {"Mucosidad": 0.2, "Rugosidad": 0.55},
            "snout": {"Humedad": 0.2, "Rugosidad": 0.55},
        },
        bake_resolution=4096,
        bake_samples=32,
        pack_orm=False,
    ),
]


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

_BY_ID: Dict[str, Style] = {s.id: s for s in STYLES}

STYLE_IDS: List[Tuple[str, str, str]] = [
    (s.id, s.name_es, s.desc_es) for s in STYLES
]


def get_style(style_id: str) -> Style:
    return _BY_ID.get(style_id, STYLES[0])


def default_style_id() -> str:
    return STYLES[0].id


def style_enum_items(self=None, context=None) -> List[Tuple[str, str, str]]:
    from .i18n import get_language

    lang = get_language()
    return [(s.id, s.name(lang), s.desc(lang)) for s in STYLES]


def global_of(style: Style, key: str, default: float = 0.0) -> float:
    """Valor global del estilo con fallback."""
    return float(style.globals.get(key, default))


def enabled(style: Style, key: str) -> bool:
    """¿Está activa una capacidad del estilo? (``use_*``)."""
    return float(style.globals.get(key, 1.0)) > 0.5


def resolve_param(style: Style, zone: Any, param: Any,
                  user_value: Any = None) -> Any:
    """
    Resuelve el valor efectivo de un parámetro.

    ``zone`` es un :class:`~pcm_studio.zones.Zone` y ``param`` un
    :class:`~pcm_studio.zones.Param`.  ``user_value`` (si no es ``None``) gana
    siempre: es lo que el usuario ha tocado en el panel.
    """
    if user_value is not None:
        return user_value
    override = style.override(zone.key, zone.category, param.name)
    if override is None:
        return param.default
    # respeta el tipo del parámetro
    if param.kind == "FLOAT":
        try:
            v = float(override)
        except Exception:
            return param.default
        if param.min is not None:
            v = max(float(param.min), v)
        if param.max is not None:
            v = min(float(param.max), v)
        return v
    if param.kind == "INT":
        try:
            return int(override)
        except Exception:
            return param.default
    if param.kind == "BOOL":
        return bool(override)
    if param.kind == "COLOR":
        try:
            seq = tuple(float(c) for c in override)
        except Exception:
            return param.default
        while len(seq) < 4:
            seq = seq + (1.0,)
        return seq[:4]
    return override


def resolve_params(style: Style, zone: Any,
                   user_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resuelve todos los parámetros de una zona en un dict."""
    user_values = user_values or {}
    out: Dict[str, Any] = {}
    for p in zone.params:
        uv = user_values.get(p.name)
        out[p.name] = resolve_param(style, zone, p, uv)
    return out
