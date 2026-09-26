# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Operadores de creación, variación y bake de normales."""

from __future__ import annotations

import os
from typing import Any, List, Optional

try:  # pragma: no cover - Blender sólo está disponible dentro de Blender
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

from .material import build_rock_material, connect_baked_normal, restore_procedural_normal
from .mesh import build_rock, is_rock
from .properties import SETTING_FIELDS, copy_settings


def _active_rock(context: Any) -> Optional[Any]:
    obj = getattr(context, "active_object", None)
    return obj if is_rock(obj) else None


def _settings_for(context: Any) -> Any:
    obj = _active_rock(context)
    if obj is not None and hasattr(obj, "sr_rock_settings"):
        return obj.sr_rock_settings
    return context.scene.sr_rock_settings


def _next_seed(seed: int) -> int:
    # LCG de 31 bits: rápido, reproducible y sin depender del estado global de
    # ``random`` del usuario.
    return (int(seed) * 1664525 + 1013904223) & 0x7FFFFFFF


def _select_only(context: Any, obj: Any) -> None:
    try:
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except (AttributeError, RuntimeError):
        pass


if bpy is not None:

    class SR_OT_create_rock(bpy.types.Operator):
        """Crea una roca nueva desde la configuración de la escena."""

        bl_idname = "sr.create_rock"
        bl_label = "Crear roca procedural"
        bl_description = "Genera una roca estilizada nueva con geometría y normales"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context: Any) -> set[str]:
            settings = context.scene.sr_rock_settings
            try:
                obj = build_rock(
                    settings,
                    context=context,
                    name=f"SR_Rock_{int(settings.seed):04d}",
                )
            except Exception as exc:
                self.report({"ERROR"}, f"No se pudo crear la roca: {exc}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Roca creada: {obj.name} · seed {settings.seed}")
            return {"FINISHED"}


    class SR_OT_regenerate_rock(bpy.types.Operator):
        """Regenera la roca activa sin deformar dos veces la misma malla."""

        bl_idname = "sr.regenerate_rock"
        bl_label = "Regenerar roca activa"
        bl_description = "Reconstruye la malla desde la semilla y ajustes del objeto"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _active_rock(context) is not None

        def execute(self, context: Any) -> set[str]:
            obj = _active_rock(context)
            if obj is None:
                self.report({"WARNING"}, "Selecciona una roca creada por Rock Forge")
                return {"CANCELLED"}
            try:
                build_rock(obj.sr_rock_settings, context=context, target=obj)
            except Exception as exc:
                self.report({"ERROR"}, f"No se pudo regenerar la roca: {exc}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Roca regenerada con seed {obj.sr_rock_settings.seed}")
            return {"FINISHED"}


    class SR_OT_randomize_seed(bpy.types.Operator):
        """Cambia la semilla; no crea una roca hasta pulsar Crear/Regenerar."""

        bl_idname = "sr.randomize_seed"
        bl_label = "Nueva semilla"
        bl_description = "Elige una semilla reproducible para otra variación"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context: Any) -> set[str]:
            settings = _settings_for(context)
            settings.seed = _next_seed(settings.seed)
            self.report({"INFO"}, f"Nueva semilla: {settings.seed}")
            return {"FINISHED"}


    class SR_OT_duplicate_variation(bpy.types.Operator):
        """Duplica la roca activa con una semilla vecina."""

        bl_idname = "sr.duplicate_variation"
        bl_label = "Duplicar variación"
        bl_description = "Crea otra roca conservando los parámetros y cambiando la semilla"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _active_rock(context) is not None

        def execute(self, context: Any) -> set[str]:
            source = _active_rock(context)
            if source is None:
                return {"CANCELLED"}
            scene_settings = context.scene.sr_rock_settings
            copy_settings(source.sr_rock_settings, scene_settings)
            scene_settings.seed = _next_seed(source.sr_rock_settings.seed)
            try:
                obj = build_rock(
                    scene_settings,
                    context=context,
                    name=f"{source.name}_Var",
                )
            except Exception as exc:
                self.report({"ERROR"}, f"No se pudo duplicar la roca: {exc}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Variación creada: {obj.name}")
            return {"FINISHED"}


    class SR_OT_refresh_material(bpy.types.Operator):
        """Reconstruye sólo el grafo de material de la roca activa."""

        bl_idname = "sr.refresh_material"
        bl_label = "Actualizar material procedural"
        bl_description = "Recrea color, rugosidad y la cadena de normal Bump"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _active_rock(context) is not None

        def execute(self, context: Any) -> set[str]:
            obj = _active_rock(context)
            if obj is None:
                return {"CANCELLED"}
            material = build_rock_material(obj, obj.sr_rock_settings)
            if material is None:
                self.report({"ERROR"}, "No se pudo crear el material")
                return {"CANCELLED"}
            self.report({"INFO"}, "Material procedural actualizado; normal Bump conectada")
            return {"FINISHED"}


    class SR_OT_bake_normal(bpy.types.Operator):
        """Hornea la normal procedural a una imagen tangente en Blender/Cycles."""

        bl_idname = "sr.bake_normal"
        bl_label = "Hornear normal tangente"
        bl_description = "Bakea la normal procedural a una imagen Non-Color y la conecta"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            obj = _active_rock(context)
            return obj is not None and bool(getattr(obj.data, "uv_layers", None))

        def execute(self, context: Any) -> set[str]:
            obj = _active_rock(context)
            if obj is None:
                self.report({"WARNING"}, "Selecciona una roca de Rock Forge")
                return {"CANCELLED"}
            settings = obj.sr_rock_settings
            material = obj.active_material
            if material is None or not material.use_nodes:
                material = build_rock_material(obj, settings)
            if material is None:
                self.report({"ERROR"}, "La roca no tiene un material con nodos")
                return {"CANCELLED"}

            resolution = int(settings.normal_bake_resolution)
            image_name = f"{obj.name}_Normal_{resolution}"
            image = bpy.data.images.get(image_name)
            if image is None or image.size[0] != resolution or image.size[1] != resolution:
                if image is not None:
                    try:
                        bpy.data.images.remove(image)
                    except RuntimeError:
                        pass
                image = bpy.data.images.new(
                    image_name,
                    width=resolution,
                    height=resolution,
                    alpha=False,
                    float_buffer=False,
                )
            try:
                image.colorspace_settings.name = "Non-Color"
                image.generated_color = (0.5, 0.5, 1.0, 1.0)
            except (AttributeError, TypeError, ValueError):
                pass

            tree = material.node_tree
            nodes = tree.nodes
            target = nodes.get("SR_BAKED_NORMAL_IMAGE")
            if target is None:
                target = nodes.new("ShaderNodeTexImage")
                target.name = "SR_BAKED_NORMAL_IMAGE"
                target.label = "TARGET · normal tangente bakeada"
                target.location = (0, -520)
            target.image = image
            for node in nodes:
                node.select = False
            target.select = True
            nodes.active = target

            old_engine = context.scene.render.engine
            previous_active = context.view_layer.objects.active
            previous_selected = list(context.selected_objects)
            _select_only(context, obj)
            try:
                # Blender hornea mapas desde Cycles. El motor y la selección se
                # restauran incluso si el usuario cancela o falta Cycles.
                context.scene.render.engine = "CYCLES"
                bpy.ops.object.bake(
                    type="NORMAL",
                    normal_space="TANGENT",
                    margin=int(settings.normal_margin),
                    use_clear=True,
                )
                if not connect_baked_normal(material, image):
                    raise RuntimeError("no se pudo conectar la imagen al Principled")

                filepath = str(settings.normal_file_path or "").strip()
                if filepath:
                    filepath = bpy.path.abspath(filepath)
                    directory = os.path.dirname(filepath)
                    if directory:
                        os.makedirs(directory, exist_ok=True)
                    image.file_format = "PNG"
                    image.filepath_raw = filepath
                    image.save()
                self.report({"INFO"}, f"Normal bakeada: {image.name}")
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, f"Falló el bake de normal: {exc}")
                return {"CANCELLED"}
            finally:
                try:
                    context.scene.render.engine = old_engine
                except (AttributeError, TypeError):
                    pass
                try:
                    for selected in context.selected_objects:
                        selected.select_set(False)
                    for selected in previous_selected:
                        selected.select_set(True)
                    context.view_layer.objects.active = previous_active
                except (AttributeError, RuntimeError):
                    pass


    class SR_OT_restore_procedural_normal(bpy.types.Operator):
        """Quita la conexión bakeada y devuelve el Bump procedural."""

        bl_idname = "sr.restore_procedural_normal"
        bl_label = "Usar normal procedural"
        bl_description = "Vuelve a conectar el ruido procedural al socket Normal"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _active_rock(context) is not None

        def execute(self, context: Any) -> set[str]:
            obj = _active_rock(context)
            material = obj.active_material if obj is not None else None
            if material is None or not restore_procedural_normal(material):
                self.report({"WARNING"}, "No hay una cadena procedural que restaurar")
                return {"CANCELLED"}
            self.report({"INFO"}, "Normal procedural restaurada")
            return {"FINISHED"}


    CLASSES = (
        SR_OT_create_rock,
        SR_OT_regenerate_rock,
        SR_OT_randomize_seed,
        SR_OT_duplicate_variation,
        SR_OT_refresh_material,
        SR_OT_bake_normal,
        SR_OT_restore_procedural_normal,
    )

else:  # pragma: no cover - stubs de importación fuera de Blender
    CLASSES = ()


def register() -> None:
    if bpy is None:  # pragma: no cover
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    if bpy is None:  # pragma: no cover
        return
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
