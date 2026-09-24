# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Propiedades (PropertyGroups).

Todo el estado del addon vive aquí y se guarda con el ``.blend``:

``SceneProperties``     ajustes globales de bake/export (uno por escena).
``ObjectProperties``    estado por objeto: estilo, escala de UV, zonas usadas.
``ZoneItem``            entrada de la lista de zonas del panel.

Las propiedades se registran en ``bpy.types.Scene`` y ``bpy.types.Object`` con
los prefijos ``pcm_`` para no chocar con nada.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .i18n import T
from .log import log
from .styles import style_enum_items
from . import zones as zones_mod
from .zones import zone_enum_items

try:  # pragma: no cover
    import bpy
    from bpy.props import (
        BoolProperty,
        CollectionProperty,
        EnumProperty,
        FloatProperty,
        FloatVectorProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
    )
    from bpy.types import Object, PropertyGroup, Scene
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = ("PCM_SceneProps", "PCM_ObjectProps", "PCM_ZoneItem",
           "PCM_ZoneParams", "PCM_Proposal", "param_ident",
           "get_scene", "get_object", "map_flags", "register", "unregister")


RESOLUTION_ITEMS = [
    ("512", "512 px", "Mapas pequeños, para props o LOD lejanos"),
    ("1024", "1024 px", "Bajo presupuesto / móvil"),
    ("2048", "2048 px", "Estándar de juego"),
    ("4096", "4096 px", "Alta calidad / primer plano"),
    ("8192", "8192 px", "Máxima calidad (lento y pesado)"),
]

ENGINE_ITEMS = [
    ("unity", "Unity", "Convención OpenGL (+Y), ORM empaquetado opcional"),
    ("unreal", "Unreal Engine", "Convención DirectX (-Y) opcional y máscara ORM"),
    ("godot", "Godot", "Convención OpenGL (+Y)"),
    ("generic", "Genérico / glTF", "Nomenclatura estándar glTF"),
]

FORMAT_ITEMS = [
    ("PNG", "PNG", "Sin pérdida, 8 bits. Recomendado para casi todo"),
    ("TARGA", "TGA", "Targa 8 bits, compatible con todos los motores"),
    ("TIFF", "TIFF", "TIFF 8/16 bits"),
    ("OPEN_EXR", "EXR", "16 bits flotante: sólo para altura y máscaras"),
    ("WEBP", "WebP", "Comprimido con pérdida ligera (Blender 4.1+)"),
]

NORMAL_MODE_ITEMS = [
    ("geometry", "Sólo geometría", "Normal de la malla sin micro-detalle. Rápido"),
    ("displaced", "Geometría + detalle (recomendado)",
     "Bakea la normal con desplazamiento adaptativo: los poros y arrugas salen "
     "de verdad en el mapa. Requiere subdivisión temporal"),
    ("overlay", "Detalle aparte (overlay)",
     "Normal de geometría + un segundo mapa con sólo el micro-detalle, para "
     "mezclar en el motor con Detail Normal"),
]


if bpy is not None:

    class PCM_ZoneItem(PropertyGroup):
        """Una zona asignada, para mostrarla en la lista del panel."""

        zone_id: IntProperty(name="ID de zona", default=0)
        zone_key: StringProperty(name="Clave", default="")
        zone_name: StringProperty(name="Zona", default="")
        face_count: IntProperty(name="Caras", default=0)
        color: FloatProperty(name="Color", size=3, default=(0.5, 0.5, 0.5),
                             subtype="COLOR", min=0.0, max=1.0)

    class PCM_Proposal(PropertyGroup):
        """Sugerencia de zona detectada automáticamente (se confirma a mano)."""

        zone_key: StringProperty(name="Zona", default="custom")
        zone_name: StringProperty(name="Nombre", default="")
        face_count: IntProperty(name="Caras", default=0)
        confidence: FloatProperty(name="Confianza", default=0.0, min=0.0, max=1.0,
                                  subtype="FACTOR")
        reason: StringProperty(name="Motivo", default="")
        apply: BoolProperty(name="Aplicar", default=True)

    class PCM_ZoneParams(PropertyGroup):
        """
        Editor de parámetros de la zona activa.

        Las propiedades se crean dinámicamente al registrar (una por cada
        parámetro de cada zona), de modo que ``layout.prop`` pueda dibujarlas
        con su rango y descripción originales.  Sólo se muestra el subconjunto
        que corresponde a la zona activa.
        """

        live: BoolProperty(
            name="Aplicar en vivo",
            description="Aplica cada cambio al material sin necesidad de pulsar "
                        "«Aplicar». Puede ser lento en materiales grandes",
            default=False,
        )
        current_zone: StringProperty(name="Zona actual", default="")

    class PCM_ObjectProps(PropertyGroup):
        """Estado del addon para un objeto concreto."""

        prepared: BoolProperty(
            name="Preparado",
            description="El objeto ya tiene atributo de zonas y material PCM",
            default=False,
        )
        style: EnumProperty(
            name=T("Estilo"),
            description="Preset de estilo del material",
            items=style_enum_items,
            default="realistic",
        )
        uv_scale: FloatProperty(
            name="Escala de UV",
            description="Multiplica la escala de todas las texturas procedurales. "
                        "Súbela si el personaje es muy grande o el detalle se ve "
                        "demasiado fino; bájala si se ve demasiado grueso",
            default=1.0, min=0.05, max=20.0, soft_min=0.2, soft_max=5.0,
            step=10,
        )
        active_zone: EnumProperty(
            name=T("Zona"),
            description="Zona que se aplicará a las caras seleccionadas",
            items=zone_enum_items,
            default="skin_body",
        )
        zone_items: CollectionProperty(type=PCM_ZoneItem)
        zone_params: PointerProperty(type=PCM_ZoneParams)
        proposals: CollectionProperty(type=PCM_Proposal)
        auto_rebuild: BoolProperty(
            name=T("Auto-reconstruir"),
            description="Reconstruir el material automáticamente al asignar una zona",
            default=True,
        )
        show_zone_colors: BoolProperty(
            name="Ver zonas en el viewport",
            description="Mantiene actualizado el atributo de color con el color de "
                        "cada zona para verlas en el viewport",
            default=False,
            update=lambda self, context: _update_zone_colors(self, context),
        )
        isolate_zone: IntProperty(
            name="Aislar zona",
            description="Oculta temporalmente las caras que no sean de esta zona "
                        "(0 = mostrar todo)",
            default=0,
        )
        last_report: StringProperty(name="Último informe", default="")

    class PCM_SceneProps(PropertyGroup):
        """Ajustes globales de bake y exportación."""

        # --- motor / convención ---
        engine: EnumProperty(
            name=T("Motor de destino"),
            description="Ajusta la nomenclatura, la convención de normales y el "
                        "empaquetado de canales al motor elegido",
            items=ENGINE_ITEMS,
            default="unity",
        )
        normal_convention: EnumProperty(
            name=T("Convención de normales"),
            description="OpenGL (+Y, verde arriba) es lo que usan Unity, Godot y "
                        "glTF. DirectX (-Y) es lo que usa Unreal",
            items=[("opengl", T("OpenGL (+Y)"), "Unity, Godot, glTF, Blender"),
                   ("directx", T("DirectX (-Y)"), "Unreal Engine, 3ds Max")],
            default="opengl",
        )
        pack_channels: BoolProperty(
            name="Empaquetar canales (ORM)",
            description="Genera una textura adicional con Oclusión en R, "
                        "Rugosidad en G y Metálico en B. Unreal usa la máscara "
                        "ORM tal cual; Unity puede usarla con el shader "
                        "estándar (A = suavizado)",
            default=True,
        )

        # --- bake ---
        resolution: EnumProperty(
            name=T("Resolución de bake"),
            description="Tamaño de los mapas generados",
            items=RESOLUTION_ITEMS,
            default="4096",
        )
        samples: IntProperty(
            name=T("Muestras"),
            description="Muestras por píxel del bake. Con denoising activado 32-64 "
                        "suele bastar",
            default=64, min=1, max=4096, soft_max=512,
        )
        use_denoise: BoolProperty(
            name="Denoiser",
            description="Aplica el denoiser de Cycles al bake. Imprescindible con "
                        "pocas muestras",
            default=True,
        )
        normal_mode: EnumProperty(
            name="Modo de la normal",
            description="Cómo se genera el mapa de normales",
            items=NORMAL_MODE_ITEMS,
            default="displaced",
        )
        dicing_rate: FloatProperty(
            name="Teselado (mm)",
            description="Tamaño de triángulo del desplazamiento adaptativo al "
                        "bakear la normal con detalle. Más bajo = más fiel y "
                        "mucho más lento",
            default=0.8, min=0.05, max=20.0, soft_min=0.2, soft_max=4.0,
            precision=3, unit="LENGTH",
        )
        max_subdivisions: IntProperty(
            name="Subdivisiones máx.",
            description="Límite de subdivisión adaptativa. Súbelo sólo si la "
                        "normal sale pixelada",
            default=6, min=0, max=12,
        )
        margin: IntProperty(
            name=T("Tamaño del borde"),
            description="Píxeles de relleno alrededor de las islas UV. Evita el "
                        "sangrado de color entre islas en el motor",
            default=16, min=0, max=256,
        )
        margin_type: EnumProperty(
            name="Tipo de borde",
            description="EXTEND repite el píxel del borde (mejor para color); "
                        "ADJACENT_FACES rellena con las caras vecinas",
            items=[("EXTEND", "Extender", "Repite los píxeles del borde"),
                   ("ADJACENT_FACES", "Caras adyacentes", "Rellena proyectando "
                                                          "las caras vecinas")],
            default="EXTEND",
        )
        # --- selección de mapas ---
        bake_basecolor: BoolProperty(name=T("Color base"), default=True)
        bake_normal: BoolProperty(name=T("Normal"), default=True)
        bake_roughness: BoolProperty(name=T("Rugosidad"), default=True)
        bake_metallic: BoolProperty(name=T("Metálico"), default=False)
        bake_ao: BoolProperty(name=T("Oclusión ambiental"), default=True)
        bake_height: BoolProperty(name=T("Altura"), default=True)
        bake_emission: BoolProperty(name=T("Emisivo"), default=False)
        bake_alpha: BoolProperty(name="Alfa", default=False)
        bake_normal_overlay: BoolProperty(
            name="Normal de detalle (overlay)",
            description="Genera además un mapa con sólo el micro-detalle, para "
                        "usarlo como Detail Normal en el motor",
            default=False,
        )

        # --- exportación ---
        output_dir: StringProperty(
            name=T("Directorio de salida"),
            description="Carpeta donde se guardan los mapas",
            subtype="DIR_PATH",
            default="//PCM_Export/",
        )
        prefix: StringProperty(
            name=T("Prefijo"),
            description="Prefijo de los ficheros. Vacío = nombre del objeto",
            default="",
        )
        file_format: EnumProperty(
            name="Formato",
            description="Formato de imagen de los mapas exportados",
            items=FORMAT_ITEMS,
            default="PNG",
        )
        color_depth: EnumProperty(
            name="Profundidad de color",
            description="8 bits para casi todo; 16 bits sólo si el motor lo "
                        "soporta y necesitas precisión en la altura",
            items=[("8", "8 bits", "Estándar"), ("16", "16 bits", "Precisión")],
            default="8",
        )
        save_blend_copy: BoolProperty(
            name="Guardar copia del material",
            description="Exporta además un .blend con sólo el material, útil "
                        "para reutilizarlo en otros personajes",
            default=False,
        )
        export_orm: BoolProperty(
            name="Exportar mapa empaquetado",
            description="Guarda también la textura ORM/Mask además de los "
                        "canales sueltos",
            default=True,
        )
        use_multires: BoolProperty(
            name="Usar multiresolución si existe",
            description="Si el objeto tiene un modificador Multires, bakea desde "
                        "él en lugar de usar desplazamiento adaptativo",
            default=False,
        )

        # --- estado ---
        is_baking: BoolProperty(name="Bakeando", default=False)
        bake_progress: FloatProperty(name=T("Progreso"), default=0.0,
                                     min=0.0, max=1.0, subtype="FACTOR")
        bake_status: StringProperty(name="Estado", default="")

else:  # pragma: no cover - fuera de Blender

    class PCM_ZoneItem:  # type: ignore[no-redef]
        pass

    class PCM_ZoneParams:  # type: ignore[no-redef]
        pass

    class PCM_Proposal:  # type: ignore[no-redef]
        pass

    class PCM_ObjectProps:  # type: ignore[no-redef]
        pass

    class PCM_SceneProps:  # type: ignore[no-redef]
        pass


def _update_zone_colors(self: Any, context: Any) -> None:
    """Refresca el atributo de color cuando se activa la visualización."""
    try:
        from . import assembler

        obj = getattr(context, "object", None)
        if obj is None:
            return
        if self.show_zone_colors:
            assembler.zone_color_attribute(obj.data)
        else:
            attr = obj.data.attributes.get(assembler.ZONE_COLOR_ATTR)
            if attr is not None:
                obj.data.attributes.remove(attr)
    except Exception:
        pass


def _scene_props(context: Any) -> Optional[Any]:
    return getattr(context.scene, "pcm", None) if bpy else None


def _object_props(obj: Any) -> Optional[Any]:
    return getattr(obj, "pcm", None) if obj is not None and bpy else None


def get_scene(context: Any) -> Optional[Any]:
    """Acceso seguro a los ajustes de escena."""
    return getattr(getattr(context, "scene", None), "pcm", None)


def get_object(obj: Any) -> Optional[Any]:
    """Acceso seguro a los ajustes de objeto."""
    return getattr(obj, "pcm", None) if obj is not None else None


def map_flags(scene_props: Any) -> List[str]:
    """Lista de claves de mapa activas, en orden de bake."""
    if scene_props is None:
        return []
    order = [
        ("basecolor", "bake_basecolor"),
        ("normal", "bake_normal"),
        ("roughness", "bake_roughness"),
        ("metallic", "bake_metallic"),
        ("ao", "bake_ao"),
        ("height", "bake_height"),
        ("emission", "bake_emission"),
        ("alpha", "bake_alpha"),
        ("normal_overlay", "bake_normal_overlay"),
    ]
    return [key for key, attr in order if getattr(scene_props, attr, False)]


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

_CLASSES: List[Any] = []


def _declare_zone_param_props() -> None:
    """Añade a ``PCM_ZoneParams`` una propiedad por parámetro de zona."""
    import bpy.props as _p

    declared = 0
    for zone in zones_mod.ZONES:
        for prm in zone.params:
            ident = _param_ident(zone.key, prm.name)
            if hasattr(PCM_ZoneParams, ident):
                continue
            if prm.kind == "FLOAT":
                prop = _p.FloatProperty(
                    name=prm.name, description=prm.desc or prm.name,
                    default=float(prm.default),
                    min=float(prm.min) if prm.min is not None else -1e6,
                    max=float(prm.max) if prm.max is not None else 1e6,
                    update=_on_param_changed,
                )
            elif prm.kind == "INT":
                prop = _p.IntProperty(
                    name=prm.name, description=prm.desc or prm.name,
                    default=int(prm.default),
                    min=int(prm.min) if prm.min is not None else -10000,
                    max=int(prm.max) if prm.max is not None else 10000,
                    update=_on_param_changed,
                )
            elif prm.kind == "BOOL":
                prop = _p.BoolProperty(
                    name=prm.name, description=prm.desc or prm.name,
                    default=bool(prm.default), update=_on_param_changed,
                )
            elif prm.kind == "COLOR":
                prop = _p.FloatVectorProperty(
                    name=prm.name, description=prm.desc or prm.name,
                    default=tuple(float(x) for x in prm.default),
                    size=max(3, len(prm.default)), subtype="COLOR",
                    min=0.0, max=1.0, update=_on_param_changed,
                )
            else:
                continue
            try:
                setattr(PCM_ZoneParams, ident, prop)
                declared += 1
            except Exception:
                continue
    log.debug("PCM_ZoneParams: %d propiedades de zona declaradas", declared)


def _param_ident(zone_key: str, param_name: str) -> str:
    """Identificador estable y válido en Python para un parámetro de zona."""
    safe = "".join(c if c.isalnum() else "_" for c in f"{zone_key}__{param_name}")
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return safe


def _on_param_changed(self: Any, context: Any) -> None:
    """Aplica el cambio en vivo si el usuario lo pidió."""
    try:
        if not getattr(self, "live", False):
            return
        obj = getattr(context, "active_object", None)
        if obj is None:
            return
        props = getattr(obj, "pcm", None)
        if props is None:
            return
        zone_key = getattr(props, "active_zone", "")
        if not zone_key:
            return
        # reconstruir el mapa completo de la zona activa desde el editor
        from . import assembler as _asm

        zone = zones_mod.get_zone_by_key(zone_key)
        if zone is None:
            return
        values: Dict[str, Any] = {}
        for prm in zone.params:
            ident = _param_ident(zone_key, prm.name)
            if hasattr(self, ident):
                v = getattr(self, ident)
                values[prm.name] = tuple(v) if hasattr(v, "__len__") else v
        for name, val in values.items():
            _asm.set_zone_param(obj, zone_key, name, val, rebuild=False)
    except Exception as exc:  # pragma: no cover - defensivo
        log.debug("No se pudo aplicar el parámetro en vivo: %s", exc)


def param_ident(zone_key: str, param_name: str) -> str:
    """API pública del identificador (la usa ``ui.py``)."""
    return _param_ident(zone_key, param_name)


def register() -> None:
    if bpy is None:
        return
    global _CLASSES
    _declare_zone_param_props()
    _CLASSES = [PCM_ZoneItem, PCM_Proposal, PCM_ZoneParams, PCM_ObjectProps,
                PCM_SceneProps]
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:  # ya registrado
            if "already registered" not in str(exc).lower():
                raise
    Object.pcm = PointerProperty(type=PCM_ObjectProps)
    Scene.pcm = PointerProperty(type=PCM_SceneProps)


def unregister() -> None:
    if bpy is None:
        return
    for attr, typ in (("pcm", Object), ("pcm", Scene)):
        try:
            delattr(typ, attr)
        except Exception:
            pass
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
