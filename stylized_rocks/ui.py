# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Interfaz en español para crear y revisar rocas en la Vista 3D."""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

from .mesh import is_rock
from .properties import STYLE_ITEMS


if bpy is not None:

    class SR_PT_rock_forge(bpy.types.Panel):
        bl_idname = "SR_PT_rock_forge"
        bl_label = "Stylized Rock Forge"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Roca Forge"
        bl_options = {"DEFAULT_CLOSED"}

        def draw(self, context: Any) -> None:
            layout = self.layout
            scene = context.scene
            scene_settings = scene.sr_rock_settings
            obj = getattr(context, "active_object", None)
            active = obj if is_rock(obj) else None
            settings = active.sr_rock_settings if active is not None else scene_settings

            intro = layout.box()
            intro.label(text="Roca estilizada procedural", icon="OUTLINER_OB_MESH")
            intro.label(text="Geometría + material + normales", icon="NODETREE")

            creation = layout.box()
            creation.label(text="Crear", icon="ADD")
            row = creation.row(align=True)
            row.operator("sr.create_rock", text="Crear roca", icon="MESH_ICOSPHERE")
            row.operator("sr.randomize_seed", text="Nueva semilla", icon="FILE_REFRESH")
            if active is not None:
                row = creation.row(align=True)
                row.operator("sr.regenerate_rock", text="Regenerar", icon="FILE_REFRESH")
                row.operator("sr.duplicate_variation", text="Variación", icon="DUPLICATE")

            shape = layout.box()
            shape.label(text="Forma", icon="MESH_DATA")
            shape.prop(settings, "seed")
            shape.prop(settings, "detail")
            row = shape.row(align=True)
            row.prop(settings, "width")
            row.prop(settings, "depth")
            shape.prop(settings, "height")
            shape.prop(settings, "surface_roughness", slider=True)
            shape.prop(settings, "asymmetry", slider=True)
            row = shape.row(align=True)
            row.prop(settings, "flatten_bottom", slider=True)
            row.prop(settings, "taper", slider=True)

            normals = layout.box()
            normals.label(text="Normales geométricas", icon="NORMALS_FACE")
            normals.prop(settings, "normal_mode")
            if settings.normal_mode == "HYBRID":
                normals.prop(settings, "facet_angle")
            normals.prop(settings, "normal_strength", slider=True)
            normals.prop(settings, "normal_distance", slider=True)
            normals.prop(settings, "use_bevel")
            if settings.use_bevel:
                row = normals.row(align=True)
                row.prop(settings, "bevel_width")
                row.prop(settings, "bevel_segments")

            material = layout.box()
            material.label(text="Material procedural", icon="MATERIAL")
            material.prop(settings, "style")
            material.prop(settings, "color_tint")
            material.prop(settings, "use_material")
            if active is not None:
                material.operator("sr.refresh_material", text="Actualizar material", icon="FILE_REFRESH")

            bake = layout.box()
            bake.label(text="Normal tangente", icon="RENDER_STILL")
            bake.label(text="El Bump procedural ya está conectado", icon="CHECKMARK")
            bake.prop(settings, "normal_bake_resolution")
            bake.prop(settings, "normal_margin")
            bake.prop(settings, "normal_file_path")
            row = bake.row(align=True)
            row.enabled = active is not None
            row.operator("sr.bake_normal", text="Hornear normal", icon="RENDER_STILL")
            row.operator("sr.restore_procedural_normal", text="Procedural", icon="NODETREE")

            if active is None:
                note = layout.box()
                note.label(text="Crea o selecciona una roca Forge", icon="INFO")
            else:
                info = layout.box()
                info.label(text=f"Activa: {active.name}", icon="OUTLINER_OB_MESH")
                info.label(text=f"Seed: {active.sr_rock_settings.seed} · {active.sr_rock_settings.normal_mode}")
                mat = active.active_material
                source = mat.get("sr_normal_source", "sin material") if mat else "sin material"
                info.label(text=f"Normal shader: {source}")


    CLASSES = (SR_PT_rock_forge,)

    def _menu_add_rock(self: Any, context: Any) -> None:
        self.layout.separator()
        self.layout.operator("sr.create_rock", text="Roca estilizada procedural", icon="MESH_ICOSPHERE")

else:  # pragma: no cover
    CLASSES = ()

    def _menu_add_rock(self: Any, context: Any) -> None:
        return None


def register() -> None:
    if bpy is None:  # pragma: no cover
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    menu = getattr(bpy.types, "VIEW3D_MT_add", None)
    if menu is not None:
        menu.append(_menu_add_rock)


def unregister() -> None:
    if bpy is None:  # pragma: no cover
        return
    menu = getattr(bpy.types, "VIEW3D_MT_add", None)
    if menu is not None:
        try:
            menu.remove(_menu_add_rock)
        except (AttributeError, RuntimeError):
            pass
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
