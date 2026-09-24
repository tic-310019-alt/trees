# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Catálogo de zonas de material.

Una **zona** es una región semántica del personaje (piel, iris, esmalte,
escamas…).  El flujo del addon es:

1. El usuario selecciona caras en Modo Edición.
2. Pulsa «Asignar zona» y elige la zona.
3. PCM Studio guarda un ``zone_id`` por cara (atributo de malla ``pcm_zone``) y
   reconstruye **un único material** que ramifica por zona.

Cada zona declara:

``recipe``    función de :mod:`pcm_studio.recipes` que construye su shader.
``params``    parámetros expuestos como entradas del grupo de nodos (sliders
              que el usuario toca sin abrir el árbol).
``maps``      qué canales aporta al bake.
``flags``     capacidades (SSS, emisivo, transparencia…) que el ensamblador y
              el bakeador consultan.

Añadir una zona nueva = añadir una entrada aquí + su receta.  Nada más.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = (
    "Param",
    "Zone",
    "ZONES",
    "ZONE_IDS",
    "get_zone",
    "zones_by_category",
    "CATEGORIES",
    "DEFAULT_ZONE_ID",
    "NO_ZONE_ID",
)


NO_ZONE_ID = 0          # caras sin zona asignada
DEFAULT_ZONE_ID = 1     # piel corporal: el fondo del material


# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    """Un control expuesto al usuario (entrada del grupo de nodos)."""

    name: str
    kind: str = "FLOAT"
    default: Any = 0.5
    min: Optional[float] = None
    max: Optional[float] = None
    desc: str = ""
    group: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.kind.upper())


def P(name: str, default: float, min: float = 0.0, max: float = 1.0,
      desc: str = "", group: str = "") -> Param:
    """Atajo para parámetros float."""
    return Param(name, "FLOAT", default, min, max, desc, group)


def C(name: str, default: Sequence[float], desc: str = "", group: str = "") -> Param:
    """Atajo para parámetros color (RGBA)."""
    return Param(name, "COLOR", tuple(default), None, None, desc, group)


def B(name: str, default: bool, desc: str = "", group: str = "") -> Param:
    """Atajo para parámetros booleanos."""
    return Param(name, "BOOL", bool(default), None, None, desc, group)


def I(name: str, default: int, min: int = 0, max: int = 100,
      desc: str = "", group: str = "") -> Param:
    """Atajo para parámetros enteros."""
    return Param(name, "INT", int(default), min, max, desc, group)


# ---------------------------------------------------------------------------
# Zonas
# ---------------------------------------------------------------------------

@dataclass
class Zone:
    """Definición completa de una zona de material."""

    id: int
    key: str
    name_es: str
    name_en: str
    color: Tuple[float, float, float]     # color de visualización en viewport
    category: str                          # "Humano" | "Animal" | "Común"
    group: str                             # subgrupo para la UI ("Cabeza", …)
    recipe: str                            # nombre de la función receta
    desc_es: str = ""
    desc_en: str = ""
    params: Tuple[Param, ...] = ()
    sss: bool = False                      # ¿usa subsurface?
    transmissive: bool = False             # ¿transmisión / translucidez?
    emissive: bool = False
    alpha: bool = False                    # ¿necesita canal alfa (pestañas…)?
    two_sided: bool = False
    contributes: Tuple[str, ...] = ("basecolor", "normal", "roughness")
    style_scale: Tuple[str, ...] = ()      # claves de estilo que la afectan

    def name(self, lang: str = "es") -> str:
        return self.name_en if lang == "en" else self.name_es

    def desc(self, lang: str = "es") -> str:
        return self.desc_en if lang == "en" else self.desc_es


# -- Paletas de color de zona (para verlas en el viewport) -------------------
_SKIN = (0.86, 0.56, 0.47)
_LIP = (0.72, 0.29, 0.31)
_EYE_W = (0.92, 0.93, 0.95)
_IRIS = (0.24, 0.52, 0.68)
_CORNEA = (0.75, 0.88, 0.95)
_LASH = (0.10, 0.08, 0.09)
_TOOTH = (0.94, 0.92, 0.85)
_GUM = (0.84, 0.42, 0.47)
_TONGUE = (0.79, 0.36, 0.40)
_NAIL = (0.90, 0.74, 0.70)
_HAIR = (0.26, 0.17, 0.11)
_FUR = (0.52, 0.38, 0.24)
_SCALE = (0.28, 0.52, 0.34)
_FEATHER = (0.36, 0.56, 0.78)
_HOOF = (0.42, 0.36, 0.30)
_SNOUT = (0.30, 0.20, 0.22)
_SHELL = (0.56, 0.46, 0.26)
_AEYE = (0.86, 0.68, 0.14)
_SLIME = (0.34, 0.74, 0.52)
_CUSTOM = (0.50, 0.50, 0.55)


# -- Parámetros compartidos --------------------------------------------------
_P_MICRO = (
    P("Detalle", 1.0, 0.0, 2.0,
      "Intensidad del micro-relieve (poros, textura) en la normal", "Detalle"),
    P("Escala de detalle", 1.0, 0.1, 4.0,
      "Tamaño del micro-relieve. Súbela para personajes grandes o planos lejanos",
      "Detalle"),
    P("Cavidad", 0.5, 0.0, 2.0,
      "Oscurecimiento de poros y pliegues (oclusión de cavidad)", "Detalle"),
)

_P_TONE = (
    P("Tono", 0.5, 0.0, 1.0, "Posición en la rampa de tonos (claro ↔ oscuro)", "Color"),
    P("Variación", 0.5, 0.0, 1.5, "Cuánto cambia el tono entre regiones", "Color"),
    P("Rojizo", 0.35, 0.0, 1.0, "Aporta de sangre / rubor bajo la piel", "Color"),
    P("Saturación", 1.0, 0.0, 2.0, "Saturación global del color base", "Color"),
    P("Brillo", 1.0, 0.5, 1.6, "Multiplicador de luminosidad", "Color"),
)

_P_WET = (
    P("Rugosidad", 0.5, 0.0, 1.0, "Rugosidad base (0 = mojado, 1 = mate)", "Superficie"),
    P("Variación de rugosidad", 0.35, 0.0, 1.0,
      "Cuánto varía la rugosidad sobre la superficie", "Superficie"),
    P("Humedad", 0.0, 0.0, 1.0, "Añade un brillo húmedo especular", "Superficie"),
)


ZONES: List[Zone] = [
    # =======================================================================
    # HUMANO — PIEL
    # =======================================================================
    Zone(
        id=1, key="skin_body",
        name_es="Piel — Cuerpo", name_en="Skin — Body",
        color=_SKIN, category="Humano", group="Piel", recipe="skin",
        desc_es="Piel corporal: poros, vello, pecas, variación de tono y SSS.",
        desc_en="Body skin: pores, vellus hair, freckles, tone variation and SSS.",
        sss=True,
        params=_P_TONE + _P_MICRO + _P_WET + (
            P("Melanina", 0.45, 0.0, 1.0,
              "Concentración de melanina: controla el tono base de forma "
              "físicamente coherente (no es sólo un color más oscuro)", "Color"),
            P("Edad", 0.30, 0.0, 1.0,
              "Aporta arrugas finas, manchas y pérdida de uniformidad", "Detalle"),
            P("Poros", 0.55, 0.0, 1.5, "Tamaño y profundidad del poro", "Detalle"),
            P("Arrugas", 0.35, 0.0, 1.5, "Intensidad del pliegue fino", "Detalle"),
            P("Vello", 0.20, 0.0, 1.0, "Vello corporal (aclara y matea)", "Detalle"),
            P("Pecas", 0.05, 0.0, 0.5, "Densidad de pecas/lunares", "Color"),
            P("Aceite", 0.25, 0.0, 1.0, "Zonas grasas (pecho, espalda)", "Superficie"),
            P("SSS", 0.6, 0.0, 1.5, "Peso de la dispersión subsuperficial", "SSS"),
            P("Radio SSS (mm)", 8.0, 0.1, 40.0,
              "Profundidad de penetración de la luz en la piel", "SSS"),
            C("Color base", (0.72, 0.48, 0.39, 1.0),
              "Tinte base; la rampa de melanina se multiplica sobre él", "Color"),
            C("Color SSS", (0.72, 0.16, 0.13, 1.0),
              "Color de la sangre bajo la piel", "SSS"),
        ),
    ),
    Zone(
        id=2, key="skin_face",
        name_es="Piel — Cara", name_en="Skin — Face",
        color=(0.90, 0.60, 0.50), category="Humano", group="Piel", recipe="skin_face",
        desc_es="Piel facial con zonas T: rubor en mejillas, poros en nariz y "
                "frente, arrugas de expresión y línea de la mandíbula.",
        desc_en="Facial skin with T-zone: cheek flush, nose/forehead pores, "
                "expression lines and jaw transition.",
        sss=True,
        params=_P_TONE + _P_MICRO + _P_WET + (
            P("Melanina", 0.45, 0.0, 1.0, "Concentración de melanina", "Color"),
            P("Edad", 0.30, 0.0, 1.0, "Arrugas de expresión y manchas", "Detalle"),
            P("Poros", 0.75, 0.0, 1.5, "La cara tiene poro más visible", "Detalle"),
            P("Arrugas", 0.55, 0.0, 1.5, "Frente, entrecejo y patas de gallo", "Detalle"),
            P("Rubor", 0.35, 0.0, 1.0, "Enrojecimiento de mejillas y nariz", "Color"),
            P("Ojeras", 0.25, 0.0, 1.0, "Oscurecimiento bajo los ojos", "Color"),
            P("Barba / sombra", 0.20, 0.0, 1.0,
              "Sombra de vello en mentón, labio superior y patillas", "Color"),
            P("Pecas", 0.06, 0.0, 0.5, "Densidad de pecas", "Color"),
            P("Aceite", 0.45, 0.0, 1.0, "Grasa en frente, nariz y mentón", "Superficie"),
            P("SSS", 0.75, 0.0, 1.5, "Peso de la dispersión subsuperficial", "SSS"),
            P("Radio SSS (mm)", 6.0, 0.1, 40.0, "Profundidad de la luz en la piel", "SSS"),
            C("Color base", (0.74, 0.50, 0.41, 1.0), "Tinte base", "Color"),
            C("Color SSS", (0.74, 0.17, 0.14, 1.0), "Color de la sangre", "SSS"),
        ),
    ),
    Zone(
        id=3, key="skin_extremity",
        name_es="Piel — Manos y pies", name_en="Skin — Hands and feet",
        color=(0.83, 0.53, 0.45), category="Humano", group="Piel", recipe="skin_extremity",
        desc_es="Piel de manos, pies, codos y rodillas: más seca, con pliegues "
                "marcados, nudillos enrojecidos y palmas sin melanina.",
        desc_en="Hands, feet, elbows and knees: drier, deep creases, reddened "
                "knuckles and melanin-free palms.",
        sss=True,
        params=_P_TONE + _P_MICRO + _P_WET + (
            P("Melanina", 0.42, 0.0, 1.0, "Concentración de melanina", "Color"),
            P("Sequedad", 0.55, 0.0, 1.0, "Descamación y grietas finas", "Detalle"),
            P("Pliegues", 0.70, 0.0, 1.5, "Arrugas de nudillos y articulaciones", "Detalle"),
            P("Nudillos", 0.45, 0.0, 1.0, "Enrojecimiento en nudillos y codos", "Color"),
            P("Palmas", 0.0, 0.0, 1.0, "Mezcla hacia piel de palma (sin melanina)", "Color"),
            P("SSS", 0.5, 0.0, 1.5, "Peso de la dispersión subsuperficial", "SSS"),
            C("Color base", (0.70, 0.46, 0.38, 1.0), "Tinte base", "Color"),
            C("Color palma", (0.85, 0.63, 0.55, 1.0), "Tono de palmas y plantas", "Color"),
        ),
    ),
    Zone(
        id=4, key="skin_thin",
        name_es="Piel — Párpados y orejas", name_en="Skin — Eyelids and ears",
        color=(0.93, 0.66, 0.58), category="Humano", group="Piel", recipe="skin_thin",
        desc_es="Piel muy fina y translúcida: párpados, orejas, aletas nasales y "
                "cuello. SSS fuerte, capilares visibles y sin poros gruesos.",
        desc_en="Very thin translucent skin: eyelids, ears, nostrils and neck. "
                "Strong SSS, visible capillaries, no coarse pores.",
        sss=True, transmissive=True,
        params=_P_TONE + _P_MICRO + _P_WET + (
            P("Translucidez", 0.65, 0.0, 1.0, "Cuánta luz atraviesa la piel", "SSS"),
            P("Capilares", 0.35, 0.0, 1.0, "Red vascular visible", "Color"),
            P("SSS", 1.0, 0.0, 2.0, "Peso de la dispersión subsuperficial", "SSS"),
            P("Radio SSS (mm)", 12.0, 0.1, 40.0, "Más radio = más translúcida", "SSS"),
            C("Color base", (0.80, 0.55, 0.48, 1.0), "Tinte base", "Color"),
        ),
    ),
    Zone(
        id=5, key="lips",
        name_es="Labios", name_en="Lips",
        color=_LIP, category="Humano", group="Cabeza", recipe="lips",
        desc_es="Labios con estrías verticales, borde bermellón, brillo húmedo y "
                "grietas finas.",
        desc_en="Lips with vertical striations, vermilion border, wet gloss and "
                "fine cracks.",
        sss=True,
        params=(
            P("Tono", 0.5, 0.0, 1.0, "De rosa pálido a granate", "Color"),
            P("Saturación", 1.15, 0.0, 2.0, "Saturación del bermellón", "Color"),
            C("Color claro", (0.80, 0.45, 0.44, 1.0), "Labio claro", "Color"),
            C("Color medio", (0.62, 0.25, 0.27, 1.0), "Labio medio", "Color"),
            C("Color oscuro", (0.38, 0.13, 0.17, 1.0), "Labio oscuro", "Color"),
            P("Estrías", 0.75, 0.0, 1.5, "Líneas verticales del labio", "Detalle"),
            P("Grietas", 0.25, 0.0, 1.0, "Resequedad y grietas finas", "Detalle"),
            P("Borde", 0.6, 0.0, 1.0, "Oscurecimiento del contorno bermellón", "Color"),
            P("Brillo", 0.65, 0.0, 1.0, "Humedad / gloss del labio", "Superficie"),
            P("Rugosidad", 0.28, 0.0, 1.0, "Rugosidad base", "Superficie"),
            P("SSS", 0.9, 0.0, 2.0, "Peso de la dispersión subsuperficial", "SSS"),
            P("Translucidez", 0.35, 0.0, 1.0, "Luz atravesando el labio", "SSS"),
        ) + _P_MICRO,
    ),
    # =======================================================================
    # HUMANO — OJO
    # =======================================================================
    Zone(
        id=6, key="sclera",
        name_es="Esclerótica (blanco del ojo)", name_en="Sclera (eye white)",
        color=_EYE_W, category="Humano", group="Ojos", recipe="sclera",
        desc_es="Blanco del ojo con red vascular, sombra limbal, tinte cálido en "
                "los ángulos y brillo húmedo.",
        desc_en="Eye white with vascular network, limbal shadow, warm tint in the "
                "corners and wet gloss.",
        sss=True,
        params=(
            P("Blancura", 0.75, 0.0, 1.0, "De marfil a blanco azulado", "Color"),
            C("Color base", (0.88, 0.88, 0.86, 1.0), "Tinte de la esclerótica", "Color"),
            C("Tinte cálido", (0.86, 0.72, 0.58, 1.0), "Ángulos y zona lagrimal", "Color"),
            C("Color venas", (0.62, 0.18, 0.16, 1.0), "Color de los capilares", "Color"),
            P("Venas", 0.45, 0.0, 1.5, "Densidad de la red vascular", "Detalle"),
            P("Grosor venas", 0.5, 0.0, 1.5, "Calibre de los capilares", "Detalle"),
            P("Irritación", 0.10, 0.0, 1.0, "Enrojecimiento general", "Color"),
            P("Sombra limbal", 0.45, 0.0, 1.0, "Oscurecimiento junto a la córnea", "Color"),
            P("Amarilleo", 0.15, 0.0, 1.0, "Tinte amarillento por edad", "Color"),
            P("Rugosidad", 0.12, 0.0, 1.0, "Superficie húmeda", "Superficie"),
            P("SSS", 0.35, 0.0, 1.5, "Dispersión bajo la conjuntiva", "SSS"),
        ) + _P_MICRO,
    ),
    Zone(
        id=7, key="iris",
        name_es="Iris", name_en="Iris",
        color=_IRIS, category="Humano", group="Ojos", recipe="iris",
        desc_es="Iris con criptas, surcos, colarete, limbo, pupila y fibra radial. "
                "Color por melanina (marrón → avellana → verde → azul).",
        desc_en="Iris with crypts, furrows, collarette, limbus, pupil and radial "
                "fibres. Melanin-driven colour (brown → hazel → green → blue).",
        sss=True,
        params=(
            P("Melanina", 0.45, 0.0, 1.0,
              "Del azul grisáceo (0) al marrón casi negro (1)", "Color"),
            C("Color exterior", (0.16, 0.32, 0.42, 1.0), "Anillo externo del iris", "Color"),
            C("Color interior", (0.62, 0.48, 0.20, 1.0),
              "Halo ámbar alrededor de la pupila", "Color"),
            P("Contraste radial", 0.6, 0.0, 1.5, "Diferencia centro/borde", "Color"),
            P("Criptas", 0.7, 0.0, 1.5, "Huecos del estroma (textura principal)", "Detalle"),
            P("Surcos", 0.55, 0.0, 1.5, "Fibras radiales (furrows of Brown)", "Detalle"),
            P("Colarete", 0.5, 0.0, 1.0, "Anillo zigzag que separa las dos zonas", "Detalle"),
            P("Limbo", 0.75, 0.0, 1.0, "Anillo oscuro del borde", "Color"),
            P("Grosor limbo", 0.18, 0.02, 0.5, "Anchura del anillo oscuro", "Color"),
            P("Pupila", 0.20, 0.05, 0.5, "Radio de la pupila (en UV)", "Color"),
            P("Borde pupila", 0.02, 0.0, 0.15, "Suavidad del borde de la pupila", "Color"),
            P("Dilatación", 0.0, -0.15, 0.25, "Desplaza el radio de la pupila", "Color"),
            P("Heterocromía", 0.0, 0.0, 1.0, "Mezcla con un segundo color", "Color"),
            C("Color alternativo", (0.42, 0.56, 0.30, 1.0),
              "Segundo color si hay heterocromía", "Color"),
            P("Rugosidad", 0.06, 0.0, 1.0, "Superficie húmeda bajo la córnea", "Superficie"),
            P("SSS", 0.4, 0.0, 1.5, "Translucidez del estroma", "SSS"),
            P("Emisivo", 0.0, 0.0, 3.0, "Brillo propio (ojos fantásticos)", "Extra"),
            C("Color emisivo", (1.0, 0.85, 0.55, 1.0), "Tinte del brillo propio", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=8, key="cornea",
        name_es="Córnea", name_en="Cornea",
        color=_CORNEA, category="Humano", group="Ojos", recipe="cornea",
        desc_es="Capa transparente y húmeda sobre el iris: IOR 1.376, reflejo "
                "especular y menisco del párpado.",
        desc_en="Transparent wet layer over the iris: IOR 1.376, specular "
                "highlight and eyelid meniscus.",
        transmissive=True,
        params=(
            P("Transparencia", 0.92, 0.0, 1.0, "Cuánto deja ver el iris", "Superficie"),
            P("IOR", 1.376, 1.0, 2.0, "Índice de refracción de la córnea", "Superficie"),
            P("Rugosidad", 0.02, 0.0, 0.4, "0 = ojo perfectamente húmedo", "Superficie"),
            P("Brillo", 1.0, 0.0, 2.0, "Intensidad del reflejo", "Superficie"),
            P("Menisco", 0.25, 0.0, 1.0, "Sombra/agua en el borde del párpado", "Detalle"),
            P("Turbidez", 0.0, 0.0, 1.0, "Catarata / ojo velado", "Extra"),
            C("Tinte", (0.96, 0.98, 1.0, 1.0), "Ligero tinte de la lágrima", "Extra"),
        ),
    ),
    Zone(
        id=9, key="lashes",
        name_es="Cejas y pestañas", name_en="Brows and lashes",
        color=_LASH, category="Humano", group="Ojos", recipe="lashes",
        alpha=True, two_sided=True,
        desc_es="Vello corto con alfa (pestañas, cejas, vello facial en tarjeta). "
                "Usa BSDF de pelo con melanina y rugosidad longitudinal.",
        desc_en="Short hair with alpha (lashes, brows, carded facial hair). Uses "
                "the hair BSDF with melanin and longitudinal roughness.",
        params=(
            P("Melanina", 0.75, 0.0, 1.0, "Rubio (0) → negro (1)", "Color"),
            P("Melanina roja", 0.15, 0.0, 1.0, "Aporte de feomelanina (rojizo)", "Color"),
            C("Color", (0.05, 0.035, 0.03, 1.0), "Tinte directo (si melanina = 0)", "Color"),
            P("Variación", 0.25, 0.0, 1.0, "Vello de distinto tono entre sí", "Color"),
            P("Rugosidad", 0.35, 0.0, 1.0, "Brillo del vello", "Superficie"),
            P("Anisotropía", 0.8, 0.0, 1.0, "Reflejo alargado a lo largo del pelo", "Superficie"),
            P("Alfa", 1.0, 0.0, 1.0, "Opacidad de la tarjeta", "Extra"),
            B("Recorte por alfa", True, "Activa alpha clip para el motor de juego", "Extra"),
        ),
    ),
    # =======================================================================
    # HUMANO — BOCA
    # =======================================================================
    Zone(
        id=10, key="teeth",
        name_es="Dientes", name_en="Teeth",
        color=_TOOTH, category="Humano", group="Boca", recipe="teeth",
        desc_es="Esmalte translúcido sobre dentina: borde incisial más claro y "
                "transparente, periquimatias, desgaste y placa en el cuello.",
        desc_en="Translucent enamel over dentin: brighter translucent incisal "
                "edge, perikymata, wear and plaque at the gumline.",
        sss=True, transmissive=True,
        params=(
            P("Blancura", 0.65, 0.0, 1.0, "De marfil a blanco clínico", "Color"),
            P("Amarilleo", 0.35, 0.0, 1.0, "Tinte cálido de la dentina", "Color"),
            C("Color esmalte", (0.90, 0.89, 0.84, 1.0), "Esmalte", "Color"),
            C("Color dentina", (0.82, 0.70, 0.48, 1.0), "Dentina bajo el esmalte", "Color"),
            P("Translucidez incisal", 0.55, 0.0, 1.0,
              "El borde del diente deja pasar la luz", "Superficie"),
            P("Gradiente cervical", 0.5, 0.0, 1.0, "Más saturado junto a la encía", "Color"),
            P("Periquimatias", 0.35, 0.0, 1.5, "Estrías verticales del esmalte", "Detalle"),
            P("Desgaste", 0.25, 0.0, 1.0, "Micro-rayado y pérdida de brillo", "Detalle"),
            P("Placa", 0.10, 0.0, 1.0, "Mancha amarillenta en el cuello", "Color"),
            P("Manchas", 0.08, 0.0, 1.0, "Decoloraciones puntuales", "Color"),
            P("Rugosidad", 0.14, 0.0, 1.0, "Esmalte húmedo", "Superficie"),
            P("Brillo", 0.9, 0.0, 1.5, "Intensidad del reflejo", "Superficie"),
            P("SSS", 0.30, 0.0, 1.5, "Translucidez del esmalte", "SSS"),
            P("Separación", 0.0, 0.0, 1.0, "Oscurece el hueco entre dientes", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=11, key="gums",
        name_es="Encías", name_en="Gums",
        color=_GUM, category="Humano", group="Boca", recipe="gums",
        desc_es="Encía con punteado (piel de naranja), festoneado en el margen, "
                "melanosis y brillo húmedo.",
        desc_en="Gums with stippled texture (orange peel), scalloped margin, "
                "melanosis and wet gloss.",
        sss=True,
        params=(
            P("Tono", 0.5, 0.0, 1.0, "De rosa pálido a granate", "Color"),
            C("Color claro", (0.88, 0.56, 0.58, 1.0), "Encía clara", "Color"),
            C("Color oscuro", (0.55, 0.22, 0.26, 1.0), "Encía oscura", "Color"),
            C("Color melanosis", (0.42, 0.26, 0.26, 1.0), "Manchas de melanina", "Color"),
            P("Melanosis", 0.12, 0.0, 1.0, "Densidad de manchas oscuras", "Color"),
            P("Punteado", 0.65, 0.0, 1.5, "Textura de piel de naranja", "Detalle"),
            P("Festoneado", 0.55, 0.0, 1.0, "Arco pálido junto al diente", "Detalle"),
            P("Vascularización", 0.25, 0.0, 1.0, "Enrojecimiento difuso", "Color"),
            P("Rugosidad", 0.22, 0.0, 1.0, "Mucosa húmeda", "Superficie"),
            P("SSS", 0.85, 0.0, 2.0, "Dispersión subsuperficial", "SSS"),
        ) + _P_MICRO,
    ),
    Zone(
        id=12, key="tongue",
        name_es="Lengua", name_en="Tongue",
        color=_TONGUE, category="Humano", group="Boca", recipe="tongue",
        desc_es="Lengua con papilas, surco medio, dorso más seco y punta húmeda.",
        desc_en="Tongue with papillae, median sulcus, drier dorsum and wet tip.",
        sss=True,
        params=(
            P("Tono", 0.5, 0.0, 1.0, "De rosa a violáceo", "Color"),
            C("Color base", (0.76, 0.34, 0.38, 1.0), "Tinte base", "Color"),
            C("Color dorso", (0.82, 0.58, 0.52, 1.0), "Dorso (más pálido)", "Color"),
            P("Papilas", 0.7, 0.0, 1.5, "Punteado de la superficie", "Detalle"),
            P("Surco medio", 0.5, 0.0, 1.0, "Línea central", "Detalle"),
            P("Humedad", 0.55, 0.0, 1.0, "Brillo de la saliva", "Superficie"),
            P("Rugosidad", 0.30, 0.0, 1.0, "Superficie base", "Superficie"),
            P("SSS", 0.95, 0.0, 2.0, "Dispersión subsuperficial", "SSS"),
        ) + _P_MICRO,
    ),
    # =======================================================================
    # HUMANO — UÑAS, PELO
    # =======================================================================
    Zone(
        id=13, key="nails",
        name_es="Uñas", name_en="Nails",
        color=_NAIL, category="Humano", group="Extremidades", recipe="nails",
        desc_es="Placa de queratina translúcida sobre el lecho: lúnula, borde "
                "libre blanco, crestas longitudinales y cutícula.",
        desc_en="Translucent keratin plate over the bed: lunula, white free edge, "
                "longitudinal ridges and cuticle.",
        transmissive=True, sss=True,
        params=(
            P("Tono", 0.55, 0.0, 1.0, "Del lecho rosado al marfil", "Color"),
            C("Color lecho", (0.86, 0.62, 0.60, 1.0), "Lecho ungueal (rosado)", "Color"),
            C("Color borde", (0.90, 0.89, 0.84, 1.0), "Borde libre (blanco)", "Color"),
            C("Color lúnula", (0.93, 0.90, 0.90, 1.0), "Lúnula (media luna)", "Color"),
            P("Borde libre", 0.28, 0.0, 0.7, "Cuánto ocupa el borde blanco (en V)", "Color"),
            P("Lúnula", 0.35, 0.0, 1.0, "Visibilidad de la media luna", "Color"),
            P("Crestas", 0.35, 0.0, 1.5, "Estrías longitudinales", "Detalle"),
            P("Cutícula", 0.5, 0.0, 1.0, "Piel muerta en la base", "Detalle"),
            P("Translucidez", 0.45, 0.0, 1.0, "Luz atravesando la placa", "Superficie"),
            P("Rugosidad", 0.10, 0.0, 1.0, "0 = uña pulida", "Superficie"),
            P("Brillo", 1.0, 0.0, 1.5, "Intensidad del reflejo", "Superficie"),
            P("Desgaste", 0.15, 0.0, 1.0, "Rayado y golpes en la punta", "Detalle"),
        ) + _P_MICRO,
    ),
    Zone(
        id=14, key="hair",
        name_es="Pelo y cuero cabelludo", name_en="Hair and scalp",
        color=_HAIR, category="Humano", group="Cabeza", recipe="hair",
        desc_es="Cuero cabelludo con folículos y pelo (BSDF de pelo por melanina, "
                "con reflejo anisótropo R/TT/TRT).",
        desc_en="Scalp with follicles plus hair (melanin-based hair BSDF with "
                "anisotropic R/TT/TRT lobes).",
        params=(
            P("Melanina", 0.72, 0.0, 1.0, "Rubio (0) → negro (1)", "Color"),
            P("Melanina roja", 0.12, 0.0, 1.0, "Feomelanina (pelirrojo)", "Color"),
            C("Color", (0.09, 0.055, 0.035, 1.0), "Tinte directo del pelo", "Color"),
            C("Color puntas", (0.16, 0.11, 0.07, 1.0), "Puntas aclaradas por el sol", "Color"),
            P("Aclarado de puntas", 0.25, 0.0, 1.0, "Mezcla hacia las puntas", "Color"),
            P("Variación", 0.30, 0.0, 1.0, "Mechas de distinto tono", "Color"),
            P("Canas", 0.0, 0.0, 1.0, "Proporción de pelo blanco", "Color"),
            P("Rugosidad", 0.32, 0.0, 1.0, "Brillo del pelo", "Superficie"),
            P("Anisotropía", 0.85, 0.0, 1.0, "Reflejo alargado", "Superficie"),
            P("Folículos", 0.5, 0.0, 1.5, "Puntos del cuero cabelludo", "Detalle"),
            C("Color cuero", (0.66, 0.45, 0.38, 1.0), "Tono del cuero cabelludo", "Detalle"),
            P("Grasa", 0.25, 0.0, 1.0, "Raíces más brillantes", "Superficie"),
        ) + _P_MICRO,
    ),
    # =======================================================================
    # ANIMAL
    # =======================================================================
    Zone(
        id=20, key="fur",
        name_es="Pelaje", name_en="Fur coat",
        color=_FUR, category="Animal", group="Piel animal", recipe="fur",
        desc_es="Pelaje corto/denso con dirección de crecimiento, sheen "
                "anisótropo, raíces oscuras y puntas aclaradas.",
        desc_en="Short dense coat with growth direction, anisotropic sheen, dark "
                "roots and sun-bleached tips.",
        params=(
            C("Color base", (0.42, 0.28, 0.16, 1.0), "Color del pelaje", "Color"),
            C("Color raíces", (0.18, 0.11, 0.07, 1.0), "Raíz más oscura", "Color"),
            C("Color puntas", (0.66, 0.52, 0.34, 1.0), "Puntas aclaradas", "Color"),
            C("Color vientre", (0.78, 0.70, 0.58, 1.0), "Zona ventral clara", "Color"),
            P("Vientre", 0.5, 0.0, 1.0, "Cuánto se aclara la zona baja", "Color"),
            P("Longitud de fibra", 0.6, 0.0, 1.5, "Escala del pelo individual", "Detalle"),
            P("Densidad", 0.75, 0.0, 1.5, "Cuánto pelo por unidad", "Detalle"),
            P("Variación", 0.35, 0.0, 1.0, "Mechas de distinto tono", "Color"),
            P("Dirección", 0.0, -3.1416, 3.1416, "Ángulo de crecimiento (radianes)", "Detalle"),
            P("Manchado", 0.0, 0.0, 1.0, "Manchas grandes (vacas, guepardos)", "Color"),
            P("Atigrado", 0.0, 0.0, 1.0, "Rayas (tabby, tigre)", "Color"),
            P("Sheen", 0.55, 0.0, 1.5, "Halo de luz en los bordes del pelaje", "Superficie"),
            P("Rugosidad", 0.55, 0.0, 1.0, "Pelo mate o brillante", "Superficie"),
            P("Anisotropía", 0.8, 0.0, 1.0, "Reflejo alargado a lo largo del pelo", "Superficie"),
            P("Suciedad", 0.15, 0.0, 1.0, "Barro y grasa en raíces", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=21, key="scales",
        name_es="Escamas", name_en="Scales",
        color=_SCALE, category="Animal", group="Piel animal", recipe="scales",
        desc_es="Escamas en placas con borde levantado, gradación de tamaño, "
                "desgaste en el centro y brillo de queratina.",
        desc_en="Plated scales with raised edge, size gradation, centre wear and "
                "keratin gloss.",
        params=(
            C("Color base", (0.24, 0.42, 0.26, 1.0), "Color de la escama", "Color"),
            C("Color borde", (0.10, 0.20, 0.12, 1.0), "Borde/valle más oscuro", "Color"),
            C("Color vientre", (0.72, 0.70, 0.48, 1.0), "Placas ventrales", "Color"),
            P("Densidad", 60.0, 8.0, 400.0, "Número de escamas", "Detalle"),
            P("Gradación", 0.5, 0.0, 1.0, "Escamas más pequeñas hacia extremidades", "Detalle"),
            P("Vientre", 0.35, 0.0, 1.0, "Cuánto se aclara la zona ventral", "Color"),
            P("Altura de placa", 0.6, 0.0, 1.5, "Relieve de cada escama", "Detalle"),
            P("Borde", 0.55, 0.0, 1.5, "Realce del contorno", "Detalle"),
            P("Irregularidad", 0.35, 0.0, 1.0, "Rompe la rejilla perfecta", "Detalle"),
            P("Desgaste", 0.25, 0.0, 1.0, "Abrasión en el centro de la placa", "Detalle"),
            P("Manchado", 0.25, 0.0, 1.0, "Variación de tono entre escamas", "Color"),
            P("Iridiscencia", 0.0, 0.0, 1.0, "Película fina (reptiles brillantes)", "Extra"),
            P("Rugosidad", 0.32, 0.0, 1.0, "Queratina seca o húmeda", "Superficie"),
            P("Humedad", 0.0, 0.0, 1.0, "Brillo de anfibio mojado", "Superficie"),
        ) + _P_MICRO,
    ),
    Zone(
        id=22, key="feathers",
        name_es="Plumas", name_en="Feathers",
        color=_FEATHER, category="Animal", group="Piel animal", recipe="feathers",
        desc_es="Plumas con raquis, barbas y bárbulas, teselación de plumas de "
                "cobertura e iridiscencia estructural.",
        desc_en="Feathers with rachis, barbs and barbules, covert tiling and "
                "structural iridescence.",
        params=(
            C("Color base", (0.30, 0.48, 0.66, 1.0), "Color de la pluma", "Color"),
            C("Color raquis", (0.86, 0.84, 0.78, 1.0), "Cañón central", "Color"),
            C("Color puntas", (0.12, 0.14, 0.18, 1.0), "Bordes oscuros", "Color"),
            P("Barbas", 0.7, 0.0, 1.5, "Estría fina perpendicular al raquis", "Detalle"),
            P("Raquis", 0.6, 0.0, 1.5, "Línea central en relieve", "Detalle"),
            P("Teselación", 18.0, 4.0, 80.0, "Número de plumas de cobertura", "Detalle"),
            P("Solape", 0.45, 0.0, 1.0, "Cuánto se montan unas sobre otras", "Detalle"),
            P("Iridiscencia", 0.0, 0.0, 1.5, "Color estructural (colibrí, cuervo)", "Extra"),
            P("Grosor película", 380.0, 100.0, 900.0, "Espesor de la película (nm)", "Extra"),
            P("Rugosidad", 0.42, 0.0, 1.0, "Pluma seca", "Superficie"),
            P("Sheen", 0.4, 0.0, 1.5, "Halo suave del plumón", "Superficie"),
            P("Desgaste", 0.2, 0.0, 1.0, "Puntas rotas y suciedad", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=23, key="hooves",
        name_es="Pezuñas y cuernos", name_en="Hooves and horns",
        color=_HOOF, category="Animal", group="Extremidades", recipe="hooves",
        desc_es="Queratina compacta con anillos de crecimiento, fibras "
                "longitudinales, grietas y punta desgastada.",
        desc_en="Compact keratin with growth rings, longitudinal fibres, cracks "
                "and a worn tip.",
        params=(
            C("Color base", (0.32, 0.26, 0.20, 1.0), "Queratina", "Color"),
            C("Color punta", (0.12, 0.10, 0.09, 1.0), "Punta más oscura", "Color"),
            C("Color raíz", (0.55, 0.45, 0.34, 1.0), "Base más clara", "Color"),
            P("Anillos", 14.0, 2.0, 60.0, "Número de anillos de crecimiento", "Detalle"),
            P("Irregularidad", 0.5, 0.0, 1.5, "Anillos no uniformes", "Detalle"),
            P("Fibras", 0.6, 0.0, 1.5, "Estriado longitudinal", "Detalle"),
            P("Grietas", 0.25, 0.0, 1.0, "Fisuras y descamación", "Detalle"),
            P("Desgaste", 0.35, 0.0, 1.0, "Abrasión en la punta", "Detalle"),
            P("Translucidez", 0.2, 0.0, 1.0, "Bordes que dejan pasar luz", "Superficie"),
            P("Rugosidad", 0.45, 0.0, 1.0, "Queratina pulida o mate", "Superficie"),
            P("Suciedad", 0.3, 0.0, 1.0, "Barro en la base", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=24, key="snout",
        name_es="Hocico y trufa", name_en="Snout and nose leather",
        color=_SNOUT, category="Animal", group="Cabeza", recipe="snout",
        desc_es="Trufa húmeda con punteado, surco central (philtrum), orificios "
                "oscuros y borde seco.",
        desc_en="Wet nose leather with stippling, central philtrum groove, dark "
                "nostrils and dry edge.",
        sss=True,
        params=(
            C("Color base", (0.14, 0.10, 0.11, 1.0), "Trufa oscura", "Color"),
            C("Color rosado", (0.62, 0.38, 0.36, 1.0), "Trufas rosadas/moteadas", "Color"),
            P("Moteado", 0.35, 0.0, 1.0, "Manchas rosadas irregulares", "Color"),
            P("Punteado", 0.8, 0.0, 1.5, "Textura granular de la trufa", "Detalle"),
            P("Surco", 0.55, 0.0, 1.0, "Philtrum central", "Detalle"),
            P("Orificios", 0.6, 0.0, 1.0, "Oscurecimiento de las fosas", "Detalle"),
            P("Humedad", 0.7, 0.0, 1.0, "Brillo mojado", "Superficie"),
            P("Rugosidad", 0.18, 0.0, 1.0, "Superficie", "Superficie"),
            P("Borde seco", 0.3, 0.0, 1.0, "Resequedad en el contorno", "Detalle"),
            P("SSS", 0.4, 0.0, 1.5, "Dispersión subsuperficial", "SSS"),
        ) + _P_MICRO,
    ),
    Zone(
        id=25, key="shell",
        name_es="Caparazón", name_en="Shell",
        color=_SHELL, category="Animal", group="Extremidades", recipe="shell",
        desc_es="Placas (scutes) con nácar iridiscente, anillos de crecimiento, "
                "algas en los bordes y desgaste.",
        desc_en="Scute plates with iridescent nacre, growth rings, edge algae and "
                "wear.",
        params=(
            C("Color base", (0.46, 0.36, 0.18, 1.0), "Placa", "Color"),
            C("Color borde", (0.16, 0.13, 0.09, 1.0), "Junta entre placas", "Color"),
            C("Color nácar", (0.86, 0.84, 0.90, 1.0), "Reflejo perlado", "Extra"),
            P("Placas", 10.0, 3.0, 60.0, "Número de scutes", "Detalle"),
            P("Nácar", 0.4, 0.0, 1.5, "Intensidad de la iridiscencia", "Extra"),
            P("Grosor película", 520.0, 100.0, 900.0, "Espesor de la película (nm)", "Extra"),
            P("Anillos", 18.0, 2.0, 80.0, "Anillos de crecimiento", "Detalle"),
            P("Erosión", 0.35, 0.0, 1.0, "Desgaste en el centro de la placa", "Detalle"),
            P("Algas", 0.2, 0.0, 1.0, "Verdín en bordes y juntas", "Extra"),
            P("Rugosidad", 0.38, 0.0, 1.0, "Superficie", "Superficie"),
            P("Humedad", 0.0, 0.0, 1.0, "Caparazón mojado", "Superficie"),
        ) + _P_MICRO,
    ),
    Zone(
        id=26, key="animal_eye",
        name_es="Ojo animal", name_en="Animal eye",
        color=_AEYE, category="Animal", group="Ojos", recipe="animal_eye",
        desc_es="Iris animal con tapetum, pupila redonda/vertical/horizontal, "
                "fibra densa y color ámbar.",
        desc_en="Animal iris with tapetum, round/vertical/horizontal pupil, dense "
                "fibres and amber colour.",
        emissive=True, sss=True,
        params=(
            P("Melanina", 0.35, 0.0, 1.0, "Del ámbar al negro", "Color"),
            C("Color exterior", (0.72, 0.48, 0.10, 1.0), "Borde del iris", "Color"),
            C("Color interior", (0.90, 0.76, 0.22, 1.0), "Centro dorado", "Color"),
            P("Forma pupila", 0.0, 0.0, 2.0,
              "0 = redonda · 1 = hendidura vertical (gato) · 2 = horizontal (cabra)",
              "Color"),
            P("Pupila", 0.22, 0.03, 0.6, "Tamaño de la pupila", "Color"),
            P("Dilatación", 0.0, -0.15, 0.3, "Desplaza el radio", "Color"),
            P("Fibras", 0.8, 0.0, 1.5, "Densidad de la fibra radial", "Detalle"),
            P("Criptas", 0.6, 0.0, 1.5, "Textura del estroma", "Detalle"),
            P("Tapetum", 0.35, 0.0, 3.0,
              "Brillo reflectante nocturno (emisivo)", "Extra"),
            C("Color tapetum", (0.55, 0.95, 0.55, 1.0), "Verde/amarillo del reflejo", "Extra"),
            P("Limbo", 0.7, 0.0, 1.0, "Anillo oscuro del borde", "Color"),
            P("Rugosidad", 0.05, 0.0, 1.0, "Superficie húmeda", "Superficie"),
        ) + _P_MICRO,
    ),
    Zone(
        id=27, key="amphibian",
        name_es="Viscoso / anfibio", name_en="Slime / amphibian",
        color=_SLIME, category="Animal", group="Piel animal", recipe="amphibian",
        desc_es="Piel húmeda de anfibio: granulada, con mucosidad brillante, "
                "manchas de aviso y glándulas.",
        desc_en="Wet amphibian skin: granular, glossy mucus, warning patches and "
                "glands.",
        sss=True, transmissive=True,
        params=(
            C("Color base", (0.20, 0.52, 0.34, 1.0), "Piel", "Color"),
            C("Color manchas", (0.88, 0.62, 0.12, 1.0), "Manchas de aviso", "Color"),
            C("Color vientre", (0.82, 0.80, 0.62, 1.0), "Vientre claro", "Color"),
            P("Manchas", 0.35, 0.0, 1.0, "Densidad de manchas", "Color"),
            P("Gránulos", 0.7, 0.0, 1.5, "Punteado de la piel", "Detalle"),
            P("Glándulas", 0.3, 0.0, 1.0, "Bultos de las glándulas parótidas", "Detalle"),
            P("Mucosidad", 0.75, 0.0, 1.5, "Brillo húmedo", "Superficie"),
            P("Rugosidad", 0.09, 0.0, 1.0, "Superficie muy lisa", "Superficie"),
            P("Translucidez", 0.35, 0.0, 1.0, "Luz atravesando la piel", "SSS"),
            P("SSS", 0.8, 0.0, 2.0, "Dispersión subsuperficial", "SSS"),
            P("Vientre", 0.5, 0.0, 1.0, "Cuánto se aclara la zona ventral", "Color"),
            P("Iridiscencia", 0.0, 0.0, 1.5, "Brillo estructural", "Extra"),
        ) + _P_MICRO,
    ),
    Zone(
        id=30, key="custom",
        name_es="Zona personalizada", name_en="Custom zone",
        color=_CUSTOM, category="Común", group="Otros", recipe="custom",
        desc_es="Zona genérica ajustable: te da color, rugosidad, SSS, detalle y "
                "normal para que compongas lo que necesites.",
        desc_en="Generic tunable zone: colour, roughness, SSS, detail and normal "
                "so you can compose whatever you need.",
        sss=True,
        params=(
            C("Color A", (0.62, 0.60, 0.58, 1.0), "Color primario", "Color"),
            C("Color B", (0.30, 0.29, 0.28, 1.0), "Color secundario", "Color"),
            P("Mezcla", 0.5, 0.0, 1.0, "Proporción entre A y B", "Color"),
            P("Escala de mancha", 6.0, 0.5, 60.0, "Tamaño del patrón", "Detalle"),
            P("Metalicidad", 0.0, 0.0, 1.0, "Metálico", "Superficie"),
            P("Rugosidad", 0.5, 0.0, 1.0, "Rugosidad base", "Superficie"),
            P("SSS", 0.0, 0.0, 1.5, "Dispersión subsuperficial", "SSS"),
            C("Color SSS", (0.7, 0.2, 0.15, 1.0), "Tinte SSS", "SSS"),
            P("Transmisión", 0.0, 0.0, 1.0, "Transparencia del material", "Extra"),
            P("IOR", 1.5, 1.0, 2.5, "Índice de refracción", "Extra"),
        ) + _P_MICRO + _P_WET,
    ),
]


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

_BY_ID: Dict[int, Zone] = {z.id: z for z in ZONES}
_BY_KEY: Dict[str, Zone] = {z.key: z for z in ZONES}

#: ids válidos para EnumProperty
ZONE_IDS: List[Tuple[str, str, str, int, int]] = [
    (z.key, z.name_es, z.desc_es, z.id, i) for i, z in enumerate(ZONES)
]

CATEGORIES: Tuple[str, ...] = ("Humano", "Animal", "Común")
DEFAULT_ZONE_ID = _BY_ID.get(1, ZONES[0]).id


def get_zone(zone_id: int) -> Optional[Zone]:
    return _BY_ID.get(int(zone_id))


def get_zone_by_key(key: str) -> Optional[Zone]:
    return _BY_KEY.get(key)


def zones_by_category() -> Dict[str, List[Zone]]:
    out: Dict[str, List[Zone]] = {c: [] for c in CATEGORIES}
    for z in ZONES:
        out.setdefault(z.category, []).append(z)
    return out


def all_zone_ids() -> List[int]:
    return [z.id for z in ZONES]


def zone_enum_items(self=None, context=None) -> List[Tuple[str, str, str, int, int]]:
    """Elementos para un ``EnumProperty`` (con icono vacío y orden explícito)."""
    from .i18n import get_language

    lang = get_language()
    return [(z.key, z.name(lang), z.desc(lang), z.id, i) for i, z in enumerate(ZONES)]


def zone_color_hex(zone: Zone) -> str:
    r, g, b = (max(0, min(255, int(c * 255))) for c in zone.color)
    return f"#{r:02X}{g:02X}{b:02X}"
