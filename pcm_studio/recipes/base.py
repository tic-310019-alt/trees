# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Contexto y utilidades compartidas por todas las recetas.

Aquí vive lo que hace que las recetas sean cortas y consistentes:

* :class:`RecipeContext` da acceso a los parámetros ya resueltos (usuario >
  estilo > defecto), a las coordenadas y a los multiplicadores globales del
  estilo.
* :class:`RecipeResult` es el contrato de salida: canales PBR que el
  ensamblador cablea al *Principled BSDF*.
* Funciones de utilidad PBR reutilizables: rampa de melanina, micro-relieve,
  cavidad, rugosidad compuesta, SSS…
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import compat, texlib
from ..log import log
from ..shaderkit import Builder, NodeOut, in_socket, out_socket

__all__ = (
    "RecipeContext",
    "RecipeResult",
    "melanin_color",
    "melanin_ramp",
    "sss_ramp",
    "apply_tint",
    "contrast",
    "saturate",
    "brightness",
    "clamp_color",
    "wetness_to_roughness",
    "principled_from_channels",
    "safe_float",
    "MELANIN_STOPS",
    "SSS_STOPS",
)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convierte a float sin explotar (los colores de Blender dan secuencias)."""
    try:
        return float(value)
    except Exception:
        try:
            return float(value[0])  # type: ignore[index]
        except Exception:
            return float(default)


# ---------------------------------------------------------------------------
# Resultado de una receta
# ---------------------------------------------------------------------------

class RecipeResult:
    """
    Canales PBR producidos por una receta.

    Todo es opcional: lo que no se rellena se deja al valor por defecto del
    shader.  ``detail_height`` es el mapa de altura *sin* aplicar la escala del
    estilo; el ensamblador la aplica y la usa para la normal (vía ``Bump``) y
    para el ``Displacement`` cuando se bakea con desplazamiento.
    """

    __slots__ = (
        "base_color", "roughness", "metallic", "specular", "normal_detail",
        "detail_height", "sss_weight", "sss_radius", "sss_color", "sss_scale",
        "transmission", "ior", "emission_color", "emission_strength", "alpha",
        "coat_weight", "coat_roughness", "coat_ior", "coat_normal",
        "sheen_weight", "sheen_roughness", "sheen_tint",
        "anisotropic", "anisotropic_rotation", "tangent",
        "thin_film_thickness", "thin_film_ior",
        "ao", "extra",
    )

    def __init__(self) -> None:
        self.base_color: Any = None
        self.roughness: Any = None
        self.metallic: Any = None
        self.specular: Any = None
        self.normal_detail: Any = None
        self.detail_height: Any = None
        self.sss_weight: Any = None
        self.sss_radius: Any = None
        self.sss_color: Any = None
        self.sss_scale: Any = None
        self.transmission: Any = None
        self.ior: Any = None
        self.emission_color: Any = None
        self.emission_strength: Any = None
        self.alpha: Any = None
        self.coat_weight: Any = None
        self.coat_roughness: Any = None
        self.coat_ior: Any = None
        self.coat_normal: Any = None
        self.sheen_weight: Any = None
        self.sheen_roughness: Any = None
        self.sheen_tint: Any = None
        self.anisotropic: Any = None
        self.anisotropic_rotation: Any = None
        self.tangent: Any = None
        self.thin_film_thickness: Any = None
        self.thin_film_ior: Any = None
        self.ao: Any = None
        self.extra: Dict[str, Any] = {}

    def __repr__(self) -> str:  # pragma: no cover
        filled = [k for k in self.__slots__ if getattr(self, k, None) is not None]
        return f"<RecipeResult {', '.join(filled)}>"


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------

class RecipeContext:
    """Todo lo que una receta necesita para construir su zona."""

    def __init__(self, builder: Builder, zone: Any, style: Any,
                 params: Dict[str, Any], *, uv_scale: float = 1.0,
                 coord_space: str = "UV"):
        self.b = builder
        self.zone = zone
        self.style = style
        self.params = dict(params)
        self.uv_scale = float(uv_scale or 1.0)
        self.coord_space = coord_space
        self._coords_cache: Dict[str, Any] = {}
        self.result = RecipeResult()

    # -- parámetros -------------------------------------------------------
    def p(self, name: str, default: Any = 0.0) -> Any:
        """Valor efectivo del parámetro ``name`` (usuario > estilo > defecto)."""
        if name in self.params:
            return self.params[name]
        return default

    def f(self, name: str, default: float = 0.0) -> float:
        """Como :meth:`p` pero garantizando ``float``."""
        return safe_float(self.p(name, default), default)

    def c(self, name: str, default: Sequence[float] = (0.8, 0.8, 0.8, 1.0)
          ) -> Tuple[float, float, float, float]:
        """Parámetro de color como tupla RGBA."""
        v = self.p(name, default)
        try:
            seq = [float(x) for x in v]
        except Exception:
            seq = [float(default[0]), float(default[1]), float(default[2]), 1.0]
        while len(seq) < 4:
            seq.append(1.0)
        return (seq[0], seq[1], seq[2], seq[3])

    def flag(self, name: str, default: bool = False) -> bool:
        return bool(self.p(name, default))

    # -- globales del estilo ----------------------------------------------
    def g(self, key: str, default: float = 1.0) -> float:
        return float(self.style.globals.get(key, default))

    def on(self, key: str) -> bool:
        return float(self.style.globals.get(key, 1.0)) > 0.5

    # -- coordenadas --------------------------------------------------------
    def coords(self, space: Optional[str] = None, *, scaled: bool = True) -> Any:
        """
        Socket de coordenadas listo para enchufar a una textura.

        ``space`` = ``"UV"`` | ``"Object"`` | ``"Generated"`` | ``"Normal"``.
        Si ``scaled`` es cierto se aplica ``tiling_scale`` del estilo y la
        escala de UV del material (para personajes grandes o pequeños).
        """
        space = (space or self.coord_space).upper()
        key = f"{space}:{int(bool(scaled))}"
        if key in self._coords_cache:
            return self._coords_cache[key]

        tc = self.b.add("ShaderNodeTexCoord", label="Coordenadas")
        if tc is None:
            return None
        src = out_socket(tc, space.capitalize() if space != "UV" else "UV", 0)
        if space == "UV":
            src = out_socket(tc, "UV", 0)
        elif space == "OBJECT":
            src = out_socket(tc, "Object", 0)
        elif space == "GENERATED":
            src = out_socket(tc, "Generated", 0)
        elif space == "NORMAL":
            src = out_socket(tc, "Normal", 0)

        out: Any = src
        if scaled:
            factor = self.g("tiling_scale", 1.0) * self.uv_scale
            if abs(factor - 1.0) > 1e-4:
                mapped = self.b.add("ShaderNodeMapping", label="Escala UV")
                if mapped is not None:
                    try:
                        mapped.vector_type = "TEXTURE"
                    except Exception:
                        pass
                    compat.set_sock(mapped, "Scale", (factor, factor, factor))
                    self.b.link(src, in_socket(mapped, "Vector", 0))
                    out = out_socket(mapped, "Vector", 0)
        self._coords_cache[key] = out
        return out

    def object_dir(self) -> Optional[Any]:
        """
        Dirección unitaria desde el origen del objeto hacia el punto.

        En un globo ocular centrado en su origen esto da coordenadas polares
        perfectas: el iris queda en el polo frontal, sin depender del UV.
        """
        cached = self._coords_cache.get("OBJDIR")
        if cached is not None:
            return cached
        tc = self.b.add("ShaderNodeTexCoord", label="Coordenadas (objeto)")
        if tc is None:
            return None
        obj = out_socket(tc, "Object", 0)
        norm = self.b.vector_math("NORMALIZE", obj, label="Dirección")
        self._coords_cache["OBJDIR"] = norm
        return norm

    def radial_from_origin(self, *, forward: Sequence[float] = (0.0, 1.0, 0.0)
                           ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        ``(ángulo 0..1, radio 0..1)`` alrededor del eje ``forward`` en espacio
        de objeto.  Base de iris, pupila y patrones radiales de caparazón.
        """
        d = self.object_dir()
        if d is None:
            return None, None
        sep = self.b.add("ShaderNodeSeparateXYZ", label="Separar dirección")
        if sep is None:
            sep = self.b.add("ShaderNodeSeparateColor")
        if sep is None:
            return None, None
        self.b.link(d, in_socket(sep, "Vector", "Color", 0))
        x = out_socket(sep, "X", "Red", 0)
        y = out_socket(sep, "Y", "Green", 1)
        z = out_socket(sep, "Z", "Blue", 2)

        # Elegimos el plano perpendicular al eje "forward".
        fx, fy, fz = forward
        if abs(fz) >= max(abs(fx), abs(fy)):
            u, v = x, y                      # eje Z hacia delante
        elif abs(fx) >= abs(fy):
            u, v = y, z                      # eje X hacia delante
        else:
            u, v = x, z                      # eje Y hacia delante (por defecto)

        angle = _atan2_norm(self.b, u, v)
        # radio = distancia al eje: sqrt(1 - componente_eje²)
        axis_comp = z if abs(fz) >= max(abs(fx), abs(fy)) else (
            x if abs(fx) >= abs(fy) else y)
        sq = self.b.math("MULTIPLY", axis_comp, axis_comp, label="eje²")
        comp = self.b.math("SUBTRACT", 1.0, sq, label="1-eje²")
        radius = self.b.math("SQRT", comp, 0.0, label="Radio")
        return angle, radius

    def equirect(self, direction: Any) -> Optional[Any]:
        """Convierte una dirección en coordenadas UV equirectangulares."""
        if direction is None:
            return None
        n = self.b.vector_math("NORMALIZE", direction, label="Normalizar dir")
        if n is None:
            return None
        sep = self.b.add("ShaderNodeSeparateXYZ", label="Separar dir")
        if sep is None:
            return None
        self.b.link(n, in_socket(sep, "Vector", 0))
        x = out_socket(sep, "X", 0)
        y = out_socket(sep, "Y", 1)
        z = out_socket(sep, "Z", 2)
        u_node = _atan2_norm(self.b, x, y)
        if u_node is None:
            return None
        v_node = self.b.math("ARCCOSINE", z, 0.0, label="V")
        v_norm = self.b.math("DIVIDE", v_node, math.pi, label="V 0..1")
        comb = self.b.add("ShaderNodeCombineXYZ", label="UV esférico")
        if comb is None:
            return None
        self.b.link(u_node, in_socket(comb, "X", 0))
        self.b.link(v_norm, in_socket(comb, "Y", 1))
        zero = self.b.value(0.0)
        if zero is not None:
            self.b.link(zero, in_socket(comb, "Z", 2))
        return out_socket(comb, "Vector", 0)

    # -- utilidades de color ----------------------------------------------
    def ramp(self, stops: Sequence[Tuple[float, Sequence[float]]], src: Any,
             *, label: str = "", interpolation: str = "LINEAR") -> Optional[NodeOut]:
        node = self.b.color_ramp(stops, interpolation=interpolation, label=label)
        if node is None:
            return None
        self.b.link(src, in_socket(node.node, "Fac", 0))
        return node

    def micro_detail(self, layers: Sequence[Tuple[Any, float]], *,
                     label: str = "Micro-relieve") -> Optional[NodeOut]:
        """
        Combina capas de altura y aplica los multiplicadores del estilo.

        Devuelve la altura *final* (ya escalada); el ensamblador la usa para la
        normal y para el displacement.
        """
        h = texlib.height_combine(self.b, layers, label=label)
        if h is None:
            return None
        amount = self.g("detail_amount", 1.0) * self.g("micro_contrast", 1.0)
        if abs(amount - 1.0) > 1e-4:
            h = self.b.math("MULTIPLY", h, amount, label="Intensidad detalle")
        # recentrar en 0.5 para que el bump no desplace la superficie
        h = self.b.math("MULTIPLY_ADD", h, 0.5, 0.25, label="Recentrar")
        return h

    def detail_scale(self, base: float = 1.0) -> float:
        """Escala de textura resultante tras aplicar el multiplicador de estilo."""
        return float(base) * self.g("detail_scale", 1.0) * self.f("Escala de detalle", 1.0)

    def bump_from(self, height: Any, distance: float = 0.0006, *,
                  normal: Any = None, label: str = "Bump") -> Optional[NodeOut]:
        """
        ``Bump`` con la distancia ya escalada por el estilo.

        ``distance`` está en **metros de mundo real** (Blender usa unidades
        métricas): 0.6 mm es la profundidad típica de un poro.
        """
        if height is None:
            return normal
        d = float(distance) * self.g("normal_strength", 1.0) * self.g("detail_amount", 1.0)
        return self.b.bump(height, d, normal=normal, label=label)

    def cavity(self, radius: float = 0.004, *, contrast: Optional[float] = None,
               label: str = "Cavidad") -> Optional[NodeOut]:
        c = self.f("Cavidad", 0.5)
        strength = self.g("cavity_strength", 1.0) * c
        if strength <= 1e-4:
            return None
        out = texlib.cavity(self.b, radius=radius,
                            contrast=float(contrast if contrast is not None else 1.4),
                            label=label)
        if out is None:
            return None
        return self.b.math("MULTIPLY", out, strength, label="Cavidad ×")

    def finalize(self) -> RecipeResult:
        return self.result


# ---------------------------------------------------------------------------
# Utilidades de color reutilizables
# ---------------------------------------------------------------------------

def _atan2_norm(b: Builder, x: Any, y: Any) -> Optional[NodeOut]:
    """``atan2(y, x) / (2π) + 0.5`` → 0..1."""
    ratio = b.math("DIVIDE", y, x, label="y/x")
    if ratio is None:
        return None
    base = b.math("ARCTANGENT", ratio, 0.0, label="atan")
    neg = b.math("LESS_THAN", x, 0.0, label="x<0")
    add_pi = b.math("MULTIPLY", neg, math.pi, label="π")
    shifted = b.math("ADD", base, add_pi)
    still_neg = b.math("LESS_THAN", shifted, 0.0)
    add_2pi = b.math("MULTIPLY", still_neg, 2.0 * math.pi)
    final = b.math("ADD", shifted, add_2pi)
    norm = b.math("DIVIDE", final, 2.0 * math.pi)
    return b.math("ADD", norm, 0.5, label="Ángulo 0..1")


#: Rampa de melanina medida.  Valores lineales aproximados de piel humana
#: (Fitzpatrick I→VI) obtenidos de albedos de referencia de escaneo.
MELANIN_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.635, 0.447, 0.357)),   # muy claro
    (0.18, (0.521, 0.332, 0.258)),   # claro
    (0.36, (0.412, 0.247, 0.188)),   # medio
    (0.54, (0.300, 0.168, 0.124)),   # oliva
    (0.72, (0.206, 0.107, 0.077)),   # oscuro
    (0.88, (0.128, 0.062, 0.043)),   # muy oscuro
    (1.00, (0.075, 0.037, 0.027)),   # profundo
)

#: Color de dispersión subsuperficial: a más melanina, menos componente roja
#: visible (la melanina absorbe), y el radio efectivo baja.
SSS_STOPS: Tuple[Tuple[float, Tuple[float, float, float]], ...] = (
    (0.00, (0.830, 0.320, 0.270)),
    (0.35, (0.760, 0.220, 0.185)),
    (0.65, (0.610, 0.145, 0.120)),
    (1.00, (0.430, 0.095, 0.080)),
)


def melanin_ramp(b: Builder, melanin: Any, *, label: str = "Melanina") -> Optional[NodeOut]:
    """Color de piel a partir de la concentración de melanina (0..1)."""
    ramp = b.color_ramp(
        [(pos, (r, g, bb, 1.0)) for pos, (r, g, bb) in MELANIN_STOPS],
        interpolation="LINEAR", label=label)
    if ramp is None:
        return None
    b.link(melanin, in_socket(ramp.node, "Fac", 0))
    return ramp


def sss_ramp(b: Builder, melanin: Any, *, label: str = "SSS por melanina") -> Optional[NodeOut]:
    """Color de la sangre bajo la piel, atenuado por la melanina."""
    ramp = b.color_ramp(
        [(pos, (r, g, bb, 1.0)) for pos, (r, g, bb) in SSS_STOPS],
        interpolation="LINEAR", label=label)
    if ramp is None:
        return None
    b.link(melanin, in_socket(ramp.node, "Fac", 0))
    return ramp


def melanin_color(b: Builder, melanin: Any, tint: Sequence[float], *,
                  label: str = "Tono de piel") -> Optional[NodeOut]:
    """
    Color de piel = rampa de melanina × tinte del usuario.

    El tinte permite calidez/frío (piel cetrina, rosada, olivácea) sin romper la
    relación física entre tonos.
    """
    base = melanin_ramp(b, melanin, label=label)
    if base is None:
        return None
    return apply_tint(b, base, tint, label="Tinte")


def apply_tint(b: Builder, color: Any, tint: Sequence[float], *,
               mode: str = "MULTIPLY", label: str = "Tinte") -> Optional[NodeOut]:
    if color is None:
        return None
    if all(abs(t - 1.0) < 1e-3 for t in tint[:3]):
        return color
    return b.mix_rgb(mode, 1.0, color, tuple(tint), label=label)


def contrast(b: Builder, color: Any, amount: float, *,
             label: str = "Contraste") -> Optional[NodeOut]:
    """Contraste alrededor del gris medio (``BrightContrast``)."""
    if color is None or abs(amount - 1.0) < 1e-3:
        return color
    n = b.add("ShaderNodeBrightContrast", label=label)
    if n is None:
        return color
    b.link(color, in_socket(n, "Color", 0))
    compat.set_sock(n, "Bright", 0.0)
    compat.set_sock(n, "Contrast", (amount - 1.0) * 100.0)
    return NodeOut(n, out_socket(n, "Color", 0))


def saturate(b: Builder, color: Any, amount: float, *,
             label: str = "Saturación") -> Optional[NodeOut]:
    if color is None or abs(amount - 1.0) < 1e-3:
        return color
    n = b.add("ShaderNodeHueSaturation", label=label)
    if n is None:
        return color
    compat.set_sock(n, "Saturation", float(amount))
    compat.set_sock(n, "Hue", 0.5)
    compat.set_sock(n, "Value", 1.0)
    compat.set_sock(n, "Fac", 1.0)
    b.link(color, in_socket(n, "Color", 1))
    return NodeOut(n, out_socket(n, "Color", 0))


def brightness(b: Builder, color: Any, amount: float, *,
               label: str = "Brillo") -> Optional[NodeOut]:
    if color is None or abs(amount - 1.0) < 1e-3:
        return color
    n = b.add("ShaderNodeHueSaturation", label=label)
    if n is None:
        return color
    compat.set_sock(n, "Saturation", 1.0)
    compat.set_sock(n, "Hue", 0.5)
    compat.set_sock(n, "Value", float(amount))
    compat.set_sock(n, "Fac", 1.0)
    b.link(color, in_socket(n, "Color", 1))
    return NodeOut(n, out_socket(n, "Color", 0))


def wetness_to_roughness(b: Builder, wet: Any, dry_roughness: float,
                         wet_roughness: float = 0.03, *,
                         label: str = "Rugosidad húmeda") -> Optional[NodeOut]:
    """Interpola rugosidad seca ↔ mojada según el factor de humedad."""
    if wet is None:
        return b.value(dry_roughness, label=label)
    return b.map_range(wet, 0.0, 1.0, dry_roughness, wet_roughness,
                       interpolation="LINEAR", clamp=True, label=label)


def clamp_color(b: Builder, color: Any, *, lo: float = 0.0, hi: float = 1.0,
                label: str = "Recorte color") -> Optional[NodeOut]:
    """
    Recorta el color base al rango del motor de juego.

    Los motores trabajan con albedo en 0..1; dejar valores fuera produce
    materiales que "queman" bajo luz fuerte.
    """
    if color is None:
        return None
    sep = b.add("ShaderNodeSeparateColor")
    if sep is None:
        sep = b.add("ShaderNodeSeparateRGB")
    if sep is None:
        return color
    b.link(color, in_socket(sep, "Color", 0))
    outs: List[Any] = []
    for i, name in enumerate(("Red", "Green", "Blue")):
        s = out_socket(sep, name, i)
        outs.append(b.clamp(s, lo, hi))
    comb = b.add("ShaderNodeCombineColor")
    if comb is None:
        comb = b.add("ShaderNodeCombineRGB")
    if comb is None:
        return color
    for i, nm in enumerate(("Red", "Green", "Blue")):
        if outs[i] is not None:
            b.link(outs[i], in_socket(comb, nm, i))
    return NodeOut(comb, out_socket(comb, "Color", 0))


# ---------------------------------------------------------------------------
# Ensamblado de un Principled BSDF a partir de los canales
# ---------------------------------------------------------------------------

def principled_from_channels(b: Builder, res: RecipeResult, *,
                             name: str = "Principled BSDF",
                             use_coat: bool = True, use_sheen: bool = True,
                             use_thin_film: bool = True,
                             sss_method: str = "RANDOM_WALK",
                             label: str = "") -> Optional[Any]:
    """
    Crea un *Principled BSDF* y lo alimenta con los canales de la receta.

    Todos los sockets se resuelven por alias: si Blender cambia un nombre en una
    versión futura el canal simplemente no se conecta (y queda registrado) en
    vez de lanzar una excepción a mitad de la construcción.
    """
    node = b.add("ShaderNodeBsdfPrincipled", name=name, label=label or "Shader")
    if node is None:
        return None

    def put(logical: str, value: Any) -> None:
        if value is None:
            return
        sock_ = compat.principal_socket(node, logical)
        if sock_ is None:
            log.debug("Socket del Principled no disponible: %s", logical)
            return
        if isinstance(value, NodeOut):
            b.link(value.socket, sock_)
        elif hasattr(value, "links"):
            b.link(value, sock_)
        else:
            try:
                if isinstance(value, (tuple, list)) and hasattr(sock_.default_value, "__len__"):
                    for i, v in enumerate(value):
                        if i < len(sock_.default_value):
                            sock_.default_value[i] = float(v)
                else:
                    sock_.default_value = float(value) if isinstance(value, (int, float)) else value
            except Exception:
                log.debug("No se pudo fijar %s = %r", logical, value)

    put("Base Color", res.base_color)
    put("Roughness", res.roughness)
    put("Metallic", res.metallic)
    put("Specular IOR Level", res.specular)
    put("Normal", res.normal_detail)
    put("Alpha", res.alpha)

    if res.sss_weight is not None:
        put("Subsurface Weight", res.sss_weight)
        put("Subsurface Radius", res.sss_radius)
        put("Subsurface Scale", res.sss_scale)
        put("Subsurface Color", res.sss_color)
        put("Subsurface IOR", res.ior if res.ior is not None else None)
        try:
            node.subsurface_method = sss_method
        except Exception:
            try:
                node.subsurface_method = "RANDOM_WALK_SKIN"
            except Exception:
                pass

    put("Transmission Weight", res.transmission)
    if res.transmission is None or res.sss_weight is None:
        put("IOR", res.ior)

    put("Emission Color", res.emission_color)
    put("Emission Strength", res.emission_strength)

    if use_coat:
        put("Coat Weight", res.coat_weight)
        put("Coat Roughness", res.coat_roughness)
        put("Coat IOR", res.coat_ior)
        put("Coat Normal", res.coat_normal)
        put("Clearcoat Normal", res.coat_normal)

    if use_sheen:
        put("Sheen Weight", res.sheen_weight)
        put("Sheen Roughness", res.sheen_roughness)
        put("Sheen Tint", res.sheen_tint)

    if use_thin_film:
        put("Thin Film Thickness", res.thin_film_thickness)
        put("Thin Film IOR", res.thin_film_ior)

    put("Anisotropic", res.anisotropic)
    put("Anisotropic Rotation", res.anisotropic_rotation)
    put("Tangent", res.tangent)

    return node
