# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Capa de compatibilidad con la API de Blender.

Blender 4.x -> 5.x renombró y reorganizó buena parte del nodo *Principled BSDF*
(``Subsurface`` -> ``Subsurface Weight``, ``Specular`` -> ``Specular IOR
Level``, ``Clearcoat`` -> ``Coat Weight``, ``Sheen`` -> ``Sheen Weight``,
eliminación de ``Subsurface Color`` a favor de ``Subsurface Radius``/``IOR``,
aparición de ``Thin Film``, ``Diffuse Roughness``, ``Thin Wall``…).  También
``TexMusgrave`` pasó a ser un alias de ``TexNoise`` y en 5.x aparecieron nodos
nuevos (``TexGabor``, ``RadialTiling``, ``BsdfVelvet``…).

Este módulo centraliza **toda** esa detección para que el resto del addon no
tenga ni un solo ``inputs["..."]`` a pelo: así nunca revienta por un nombre de
socket que cambie en una versión futura.

Todo lo que se consulta se cachea la primera vez.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = (
    "BLENDER_VERSION",
    "BLENDER_VERSION_STR",
    "is_blender_at_least",
    "has_node",
    "node_class",
    "NODE_FALLBACKS",
    "PRINCIPLED_ALIASES",
    "GENERIC_ALIASES",
    "resolve_socket_names",
    "principal_socket",
    "set_principled",
    "sock",
    "set_sock",
    "feature_report",
    "NodeAvailability",
)


# ---------------------------------------------------------------------------
# Versión
# ---------------------------------------------------------------------------

def _read_version() -> Tuple[Tuple[int, int, int], str]:
    try:
        import bpy

        return tuple(bpy.app.version), bpy.app.version_string  # type: ignore[return-value]
    except Exception:  # fuera de Blender (tests, herramientas)
        return (0, 0, 0), "unknown"


BLENDER_VERSION, BLENDER_VERSION_STR = _read_version()


def is_blender_at_least(major: int, minor: int = 0, patch: int = 0) -> bool:
    return BLENDER_VERSION >= (major, minor, patch)


# ---------------------------------------------------------------------------
# Disponibilidad de tipos de nodo
# ---------------------------------------------------------------------------

# Nodos "modernos" que el addon usa cuando existen.  Si no existen se aplica el
# fallback declarado en ``NODE_FALLBACKS``.
_MODERN_NODES = (
    "ShaderNodeTexGabor",
    "ShaderNodeRadialTiling",
    "ShaderNodeBsdfVelvet",
    "ShaderNodeBsdfMetallic",
    "ShaderNodeVertexColor",
    "ShaderNodeSeparateColor",
    "ShaderNodeCombineColor",
    "ShaderNodeMix",
    "ShaderNodeMapRange",
    "ShaderNodeClamp",
    "ShaderNodeVectorRotate",
    "ShaderNodeSqueeze",
    "ShaderNodeTexWhiteNoise",
)

# De aquí NO nos podemos caer: si falta alguno de estos el addon no funciona y
# el diagnóstico debe avisar con claridad.
_REQUIRED_NODES = (
    "ShaderNodeBsdfPrincipled",
    "ShaderNodeOutputMaterial",
    "ShaderNodeTexNoise",
    "ShaderNodeTexVoronoi",
    "ShaderNodeBump",
    "ShaderNodeNormalMap",
    "ShaderNodeMixRGB",
    "ShaderNodeMath",
    "ShaderNodeVectorMath",
    "ShaderNodeValToRGB",
    "ShaderNodeRGBCurve",
    "ShaderNodeTexCoord",
    "ShaderNodeUVMap",
    "ShaderNodeMapping",
    "ShaderNodeGroup",
    "ShaderNodeMixShader",
    "ShaderNodeTexImage",
    "ShaderNodeEmission",
    "ShaderNodeAttribute",
    "ShaderNodeNewGeometry",
    "ShaderNodeBevel",
    "ShaderNodeAmbientOcclusion",
)

_availability_cache: Dict[str, bool] = {}


def has_node(bl_idname_class: str) -> bool:
    """¿Existe la clase de nodo ``ShaderNodeXxx`` en este Blender?"""
    cached = _availability_cache.get(bl_idname_class)
    if cached is not None:
        return cached
    try:
        import bpy

        ok = hasattr(bpy.types, bl_idname_class)
    except Exception:
        ok = False
    _availability_cache[bl_idname_class] = ok
    return ok


# Sustitutos cuando un nodo moderno no está disponible.
NODE_FALLBACKS: Dict[str, str] = {
    "ShaderNodeTexGabor": "ShaderNodeTexWave",
    "ShaderNodeRadialTiling": "ShaderNodeMapping",
    "ShaderNodeBsdfVelvet": "ShaderNodeBsdfSheen",
    "ShaderNodeBsdfMetallic": "ShaderNodeBsdfGlossy",
    "ShaderNodeVertexColor": "ShaderNodeAttribute",
    "ShaderNodeSeparateColor": "ShaderNodeSeparateRGB",
    "ShaderNodeCombineColor": "ShaderNodeCombineRGB",
    "ShaderNodeTexMusgrave": "ShaderNodeTexNoise",
    "ShaderNodeTexWhiteNoise": "ShaderNodeTexVoronoi",
}


def node_class(bl_idname_class: str) -> str:
    """Devuelve el nombre de clase a usar, aplicando fallback si hace falta."""
    if has_node(bl_idname_class):
        return bl_idname_class
    return NODE_FALLBACKS.get(bl_idname_class, bl_idname_class)


# ---------------------------------------------------------------------------
# Alias de sockets del Principled BSDF
# ---------------------------------------------------------------------------
#
# Clave  = nombre "lógico" que usa el addon (el de Blender 4.0+).
# Valor  = nombres aceptables en orden de preferencia.
PRINCIPLED_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Base Color": ("Base Color", "BaseColor"),
    "Subsurface Weight": ("Subsurface Weight", "Subsurface"),
    "Subsurface Radius": ("Subsurface Radius",),
    "Subsurface Scale": ("Subsurface Scale",),
    "Subsurface IOR": ("Subsurface IOR",),
    "Subsurface Anisotropy": ("Subsurface Anisotropy",),
    "Subsurface Color": ("Subsurface Color",),
    "Metallic": ("Metallic",),
    "Roughness": ("Roughness",),
    "Anisotropic": ("Anisotropic",),
    "Anisotropic Rotation": ("Anisotropic Rotation",),
    "Tangent": ("Tangent",),
    "Transmission Weight": ("Transmission Weight", "Transmission"),
    "IOR": ("IOR",),
    "Diffuse Roughness": ("Diffuse Roughness",),
    "Thin Film Thickness": ("Thin Film Thickness",),
    "Thin Film IOR": ("Thin Film IOR",),
    "Thin Wall": ("Thin Wall",),
    "Normal": ("Normal",),
    "Clearcoat Normal": ("Clearcoat Normal", "Coat Normal"),
    "Coat Weight": ("Coat Weight", "Clearcoat"),
    "Coat Roughness": ("Coat Roughness", "Clearcoat Roughness"),
    "Coat IOR": ("Coat IOR", "Clearcoat IOR"),
    "Coat Tint": ("Coat Tint", "Clearcoat Tint"),
    "Coat Affect Color": ("Coat Affect Color", "Clearcoat Affect Color"),
    "Coat Affect Roughness": ("Coat Affect Roughness", "Clearcoat Affect Roughness"),
    "Sheen Weight": ("Sheen Weight", "Sheen"),
    "Sheen Roughness": ("Sheen Roughness",),
    "Sheen Tint": ("Sheen Tint",),
    "Specular IOR Level": ("Specular IOR Level", "Specular"),
    "Specular Tint": ("Specular Tint",),
    "Emission Color": ("Emission Color", "Emission"),
    "Emission Strength": ("Emission Strength",),
    "Alpha": ("Alpha",),
}

_principled_cache: Dict[str, Optional[str]] = {}


def resolve_socket_names(node: Any, wanted: Iterable[str]) -> Dict[str, Optional[str]]:
    """
    Resuelve, para un nodo concreto, qué nombre real tiene cada socket pedido.

    Devuelve ``{nombre_lógico: nombre_real | None}``.  Busca por nombre de
    socket y, si no aparece, por ``identifier`` (Blender 5.0+ expone
    ``NodeSocket.identifier``, p.ej. ``Subsurface_Weight``).
    """
    inputs = getattr(node, "inputs", ())
    by_name: Dict[str, Any] = {}
    by_ident: Dict[str, Any] = {}
    for sock in inputs:
        try:
            by_name[sock.name] = sock
        except Exception:
            pass
        ident = getattr(sock, "identifier", None)
        if isinstance(ident, str):
            by_ident[ident] = sock

    out: Dict[str, Optional[str]] = {}
    for logical in wanted:
        found: Optional[str] = None
        for candidate in PRINCIPLED_ALIASES.get(logical, (logical,)):
            if candidate in by_name:
                found = candidate
                break
        if found is None:
            ident_guess = logical.replace(" ", "_")
            for key in (ident_guess, ident_guess.lower()):
                if key in by_ident:
                    try:
                        found = by_ident[key].name
                    except Exception:
                        found = None
                    break
        out[logical] = found
    return out


def principal_socket(principled: Any, logical: str) -> Optional[Any]:
    """
    Devuelve el socket del *Principled BSDF* para el nombre lógico ``logical``
    o ``None`` si no existe en esta versión de Blender.

    Nunca lanza excepción: el código que construye materiales puede simplemente
    saltarse los sockets opcionales (``Coat``, ``Sheen``, ``Thin Film``…).
    """
    if principled is None:
        return None
    try:
        inputs = principled.inputs
    except Exception:
        return None

    for candidate in PRINCIPLED_ALIASES.get(logical, (logical,)):
        try:
            if candidate in inputs:
                return inputs[candidate]
        except Exception:
            pass

    ident_guess = logical.replace(" ", "_")
    try:
        for sock in inputs:
            ident = getattr(sock, "identifier", "")
            if ident in (ident_guess, ident_guess.lower(), logical):
                return sock
    except Exception:
        pass
    return None


def set_principled(principled: Any, logical: str, value: Any) -> bool:
    """Fija ``default_value`` de un socket del Principled si existe."""
    sock = principal_socket(principled, logical)
    if sock is None:
        return False
    try:
        sock.default_value = value
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sockets genéricos (resto de nodos)
# ---------------------------------------------------------------------------

GENERIC_ALIASES: Dict[str, Tuple[str, ...]] = {
    # Texturas procedurales
    "Vector": ("Vector",),
    "Scale": ("Scale",),
    "Detail": ("Detail",),
    "Roughness": ("Roughness",),
    "Lacunarity": ("Lacunarity",),
    "Distortion": ("Distortion",),
    "W": ("W",),
    "Smoothness": ("Smoothness",),
    "Exponent": ("Exponent",),
    "Randomness": ("Randomness",),
    "Color": ("Color",),
    "Fac": ("Fac", "Factor"),
    "Factor": ("Factor", "Fac"),
    # Voronoi
    "Position": ("Position",),
    "Radius": ("Radius",),
    # Bump / Normal
    "Height": ("Height",),
    "Strength": ("Strength",),
    "Distance": ("Distance",),
    "Midlevel": ("Midlevel",),
    # Matemáticas
    "Value": ("Value",),
    "Min": ("Min",),
    "Max": ("Max",),
    "Steps": ("Steps",),
    # Mapping
    "Location": ("Location",),
    "Rotation": ("Rotation",),
    # A/B de nodos Mix
    "A": ("A",),
    "B": ("B",),
    "Result": ("Result",),
    # Shader
    "Shader": ("Shader",),
    "BSDF": ("BSDF",),
    # Salida
    "Surface": ("Surface",),
    "Displacement": ("Displacement",),
    "Volume": ("Volume",),
}


def sock(node: Any, logical: str) -> Optional[Any]:
    """Acceso seguro a un socket de entrada/salida por nombre lógico."""
    if node is None:
        return None
    for collection in ("inputs", "outputs"):
        items = getattr(node, collection, None)
        if items is None:
            continue
        for candidate in GENERIC_ALIASES.get(logical, (logical,)):
            try:
                if candidate in items:
                    return items[candidate]
            except Exception:
                continue
        # búsqueda por identificador
        ident_guess = logical.replace(" ", "_")
        try:
            for s in items:
                if getattr(s, "identifier", "") in (ident_guess, logical):
                    return s
        except Exception:
            pass
    return None


def set_sock(node: Any, logical: str, value: Any) -> bool:
    s = sock(node, logical)
    if s is None:
        return False
    try:
        s.default_value = value
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

class NodeAvailability:
    """Foto fija de qué puede usarse en el Blender actual."""

    __slots__ = ("modern", "required_missing", "principled", "version")

    def __init__(self) -> None:
        self.version = BLENDER_VERSION_STR
        self.modern: Dict[str, bool] = {n: has_node(n) for n in _MODERN_NODES}
        self.required_missing: List[str] = [n for n in _REQUIRED_NODES if not has_node(n)]
        self.principled: Dict[str, Optional[str]] = {}

    def probe_principled(self, node_tree: Any) -> None:
        """Rellena ``self.principled`` creando un Principled temporal."""
        try:
            import bpy

            tmp = node_tree or bpy.data.node_groups.new("PCM__probe", "ShaderNodeTree")
            owns = node_tree is None
            try:
                p = tmp.nodes.new("ShaderNodeBsdfPrincipled")
                self.principled = resolve_socket_names(p, list(PRINCIPLED_ALIASES.keys()))
                tmp.nodes.remove(p)
            finally:
                if owns:
                    bpy.data.node_groups.remove(tmp)
        except Exception:
            self.principled = {}

    @property
    def supported(self) -> Sequence[str]:
        return tuple(k for k, v in self.modern.items() if v)

    @property
    def unsupported(self) -> Sequence[str]:
        return tuple(k for k, v in self.modern.items() if not v)

    @property
    def principled_missing(self) -> Sequence[str]:
        return tuple(k for k, v in self.principled.items() if v is None)


def feature_report() -> Dict[str, Any]:
    av = NodeAvailability()
    av.probe_principled(None)
    return {
        "blender": av.version,
        "version_tuple": BLENDER_VERSION,
        "required_missing": list(av.required_missing),
        "modern_available": list(av.supported),
        "modern_missing": list(av.unsupported),
        "principled_available": [k for k, v in av.principled.items() if v],
        "principled_missing": list(av.principled_missing),
    }
