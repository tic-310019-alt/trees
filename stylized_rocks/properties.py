# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Propiedades persistentes de Stylized Rock Forge."""

from __future__ import annotations

from typing import Any, Iterable

try:  # pragma: no cover - Blender sólo está disponible dentro de Blender
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]


STYLE_ITEMS = (
    ("SLATE", "Pizarra", "Gris azulado con estratos sutiles"),
    ("GRANITE", "Granito", "Gris cálido moteado"),
    ("SANDSTONE", "Arenisca", "Arena cálida con variación de tono"),
    ("OBSIDIAN", "Obsidiana", "Oscura, brillante y con bordes fríos"),
    ("MOSS", "Roca con musgo", "Verde apagado para escenas de fantasía"),
)

NORMAL_MODE_ITEMS = (
    ("FLAT", "Facetas planas", "Cada triángulo conserva su normal plana"),
    ("HYBRID", "Híbrida", "Suaviza las caras y conserva aristas pronunciadas"),
    ("SMOOTH", "Suave", "Suavizado continuo con el micro-relieve del material"),
)

SETTING_FIELDS = (
    "seed", "detail", "width", "depth", "height", "surface_roughness",
    "asymmetry", "flatten_bottom", "taper", "normal_mode", "facet_angle",
    "style", "color_tint", "normal_strength", "normal_distance", "use_bevel",
    "bevel_width", "bevel_segments", "use_material", "normal_bake_resolution",
    "normal_margin", "normal_file_path",
)


if bpy is not None:

    class SR_RockSettings(bpy.types.PropertyGroup):
        """Ajustes de una roca; se guardan en la escena y en cada objeto creado."""

        seed: bpy.props.IntProperty(
            name="Semilla",
            description="Cambia la silueta de forma reproducible sin añadir deformaciones",
            default=1337,
            min=0,
            max=2147483647,
        )
        detail: bpy.props.IntProperty(
            name="Detalle geométrico",
            description="Subdivisiones de la icosfera; 2 es un buen equilibrio",
            default=2,
            min=0,
            max=4,
        )
        width: bpy.props.FloatProperty(
            name="Ancho",
            description="Dimensión final aproximada en X",
            default=2.4,
            min=0.05,
            max=100.0,
            soft_min=0.2,
            soft_max=10.0,
            unit="LENGTH",
        )
        depth: bpy.props.FloatProperty(
            name="Profundidad",
            description="Dimensión final aproximada en Y",
            default=2.0,
            min=0.05,
            max=100.0,
            soft_min=0.2,
            soft_max=10.0,
            unit="LENGTH",
        )
        height: bpy.props.FloatProperty(
            name="Altura",
            description="Dimensión final aproximada en Z",
            default=2.2,
            min=0.05,
            max=100.0,
            soft_min=0.2,
            soft_max=10.0,
            unit="LENGTH",
        )
        surface_roughness: bpy.props.FloatProperty(
            name="Rugosidad de silueta",
            description="Cuánto se separa la silueta de una forma redonda",
            default=0.38,
            min=0.0,
            max=1.0,
            soft_min=0.0,
            soft_max=0.8,
            subtype="FACTOR",
        )
        asymmetry: bpy.props.FloatProperty(
            name="Asimetría",
            description="Variación de escala lateral para evitar rocas repetidas",
            default=0.32,
            min=0.0,
            max=1.0,
            soft_max=0.8,
            subtype="FACTOR",
        )
        flatten_bottom: bpy.props.FloatProperty(
            name="Base plana",
            description="Aplana la parte inferior para apoyar la roca en el suelo",
            default=0.45,
            min=0.0,
            max=1.0,
            subtype="FACTOR",
        )
        taper: bpy.props.FloatProperty(
            name="Conicidad",
            description="Ancho extra en la base frente a la parte superior",
            default=0.16,
            min=-0.5,
            max=0.7,
            soft_min=-0.2,
            soft_max=0.5,
        )
        normal_mode: bpy.props.EnumProperty(
            name="Normales de malla",
            description="Cómo se interpolan las normales geométricas",
            items=NORMAL_MODE_ITEMS,
            default="HYBRID",
        )
        facet_angle: bpy.props.FloatProperty(
            name="Ángulo de arista",
            description="Ángulo a partir del cual la normal híbrida conserva una arista",
            default=0.62,
            min=0.05,
            max=3.14159,
            subtype="ANGLE",
        )
        style: bpy.props.EnumProperty(
            name="Estilo de material",
            description="Paleta procedural conectada al material de la roca",
            items=STYLE_ITEMS,
            default="GRANITE",
        )
        color_tint: bpy.props.FloatVectorProperty(
            name="Tinte",
            description="Multiplicador de color sobre la paleta del estilo",
            subtype="COLOR",
            size=4,
            default=(1.0, 1.0, 1.0, 1.0),
            min=0.0,
            max=2.0,
        )
        normal_strength: bpy.props.FloatProperty(
            name="Fuerza de normal procedural",
            description="Intensidad del nodo Bump conectado a Principled Normal",
            default=0.34,
            min=0.0,
            max=2.0,
            soft_max=1.0,
        )
        normal_distance: bpy.props.FloatProperty(
            name="Distancia de normal",
            description="Escala del micro-relieve usado por el Bump",
            default=0.075,
            min=0.001,
            max=1.0,
            soft_max=0.25,
        )
        use_bevel: bpy.props.BoolProperty(
            name="Bisel de silueta",
            description="Añade un bisel no destructivo antes de las weighted normals",
            default=False,
        )
        bevel_width: bpy.props.FloatProperty(
            name="Ancho del bisel",
            default=0.025,
            min=0.0,
            max=1.0,
            soft_max=0.2,
            unit="LENGTH",
        )
        bevel_segments: bpy.props.IntProperty(
            name="Segmentos del bisel",
            default=2,
            min=1,
            max=6,
        )
        use_material: bpy.props.BoolProperty(
            name="Crear material procedural",
            description="Crea o actualiza el material de color, roughness y normales",
            default=True,
        )
        normal_bake_resolution: bpy.props.IntProperty(
            name="Resolución normal",
            description="Resolución cuadrada de la imagen normal tangente",
            default=1024,
            min=128,
            max=8192,
            step=128,
        )
        normal_margin: bpy.props.IntProperty(
            name="Margen del bake",
            description="Padding en píxeles para evitar costuras en la normal bakeada",
            default=16,
            min=1,
            max=64,
        )
        normal_file_path: bpy.props.StringProperty(
            name="Ruta de normal",
            description="Ruta opcional; vacía deja la imagen guardada dentro del .blend",
            subtype="FILE_PATH",
            default="",
        )

else:  # Permite importar geometry/material desde un intérprete normal.

    class SR_RockSettings:  # pragma: no cover - sólo stub de importación
        pass


def copy_settings(source: Any, destination: Any) -> None:
    """Copia los ajustes conocidos sin depender del tipo concreto de RNA."""
    for name in SETTING_FIELDS:
        if not hasattr(source, name) or not hasattr(destination, name):
            continue
        try:
            value = getattr(source, name)
            if name == "color_tint":
                value = tuple(value)
            setattr(destination, name, value)
        except (AttributeError, TypeError, ValueError):
            # Una propiedad puede ser de sólo lectura si se usa con un objeto
            # simulado; no debe impedir la creación de la roca.
            continue


def register() -> None:
    if bpy is None:  # pragma: no cover
        return
    bpy.utils.register_class(SR_RockSettings)
    bpy.types.Scene.sr_rock_settings = bpy.props.PointerProperty(type=SR_RockSettings)
    bpy.types.Object.sr_rock_settings = bpy.props.PointerProperty(type=SR_RockSettings)


def unregister() -> None:
    if bpy is None:  # pragma: no cover
        return
    for owner, name in ((bpy.types.Object, "sr_rock_settings"),
                        (bpy.types.Scene, "sr_rock_settings")):
        if hasattr(owner, name):
            delattr(owner, name)
    bpy.utils.unregister_class(SR_RockSettings)
