# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Preferencias del addon.

Ajustes que no pertenecen a la escena: idioma, calidad por defecto, rutas y
acceso al diagnóstico.  Se guardan en el ``userpref.blend`` del usuario.
"""

from __future__ import annotations

from typing import Any, List

from . import compat
from .i18n import T, set_language
from .log import log

try:  # pragma: no cover
    import bpy
    from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        StringProperty,
    )
    from bpy.types import AddonPreferences, Operator
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = ("PCM_Preferences", "get_prefs", "register", "unregister",
           "PCM_OT_show_diagnostics")


PREF_PACKAGE = __package__.split(".")[0] if __package__ else "pcm_studio"


def _on_language_change(self: Any, context: Any) -> None:
    try:
        set_language(self.language)
    except Exception:
        pass
    # refresca las regiones dibujadas para que el cambio se vea al instante
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


if bpy is not None:

    class PCM_Preferences(AddonPreferences):
        bl_idname = PREF_PACKAGE

        language: EnumProperty(
            name=T("Idioma"),
            description="Idioma de la interfaz del addon",
            items=[
                ("es", T("Español"), "Interfaz en español"),
                ("en", T("Inglés"), "Interfaz en inglés"),
                ("auto", T("Automático (idioma de Blender)"),
                 "Sigue el idioma configurado en Blender"),
            ],
            default="es",
            update=_on_language_change,
        )

        default_style: EnumProperty(
            name="Estilo por defecto",
            description="Preset que se usa al preparar un objeto nuevo",
            items=[
                ("realistic", T("Realista"), "PBR fotográfico con micro-superficie completa"),
                ("sims4", T("Estilo Sims 4"), "Estilizado limpio, sin poros, colores planos"),
                ("stylized", "PBR estilizado", "PBR legible con detalle de baja frecuencia"),
                ("clayscan", T("Arcilla / escaneo"), "Neutro, todo el peso en la normal"),
            ],
            default="realistic",
        )

        default_resolution: EnumProperty(
            name=T("Resolución por defecto"),
            description="Resolución inicial de los mapas al preparar el bake",
            items=[
                ("1024", "1024 px", ""),
                ("2048", "2048 px", ""),
                ("4096", "4096 px", ""),
                ("8192", "8192 px", ""),
            ],
            default="4096",
        )

        default_samples: IntProperty(
            name=T("Muestras") + " por defecto",
            description="Muestras por píxel al bakear",
            default=64, min=1, max=4096,
        )

        default_engine: EnumProperty(
            name=T("Motor de destino") + " por defecto",
            description="Motor para el que se preparan los mapas",
            items=[
                ("unity", "Unity", ""),
                ("unreal", "Unreal Engine", ""),
                ("godot", "Godot", ""),
                ("generic", "Genérico / glTF", ""),
            ],
            default="unity",
        )

        default_export_dir: StringProperty(
            name="Ruta de exportación",
            description="Carpeta por defecto para los mapas (admite // relativo al .blend)",
            subtype="DIR_PATH",
            default="//PCM_Export/",
        )

        uv_margin_angle: FloatProperty(
            name="Ángulo de Smart UV",
            description="Ángulo límite usado al crear UVs automáticamente",
            default=66.0, min=1.0, max=89.0, subtype="ANGLE",
        )

        show_tips: BoolProperty(
            name=T("Mostrar consejos"),
            description="Muestra pistas de flujo de trabajo en los paneles",
            default=True,
        )

        verbose_log: BoolProperty(
            name=T("Modo desarrollador"),
            description="Registra todo en la consola y en el informe de diagnóstico",
            default=False,
            update=lambda self, context: _on_verbose(self),
        )

        auto_cleanup: BoolProperty(
            name="Limpiar grupos huérfanos",
            description="Al reconstruir un material, borra los grupos de nodos PCM "
                        "que ya no se usan",
            default=True,
        )

        def draw(self, context: Any) -> None:  # noqa: D102
            layout = self.layout
            layout.use_property_split = True
            layout.use_property_decorate = False

            box = layout.box()
            box.label(text="Interfaz", icon="PREFERENCES")
            col = box.column()
            col.prop(self, "language")
            col.prop(self, "show_tips")
            col.prop(self, "verbose_log")

            box = layout.box()
            box.label(text="Valores por defecto", icon="PRESET")
            col = box.column()
            col.prop(self, "default_style")
            col.prop(self, "default_engine")
            col.prop(self, "default_resolution")
            col.prop(self, "default_samples")
            col.prop(self, "default_export_dir")
            col.prop(self, "uv_margin_angle")
            col.prop(self, "auto_cleanup")

            box = layout.box()
            box.label(text="Compatibilidad", icon="CHECKMARK")
            col = box.column(align=True)
            col.label(text=f"Blender detectado: {compat.BLENDER_VERSION_STR}",
                      icon="BLENDER")
            report = compat.feature_report()
            missing = report.get("required_missing") or []
            if missing:
                col.label(text=f"Faltan nodos esenciales: {len(missing)}",
                          icon="ERROR")
                for m in missing[:6]:
                    col.label(text=f"  · {m}", icon="BLANK1")
            else:
                col.label(text="Todos los nodos esenciales disponibles",
                          icon="CHECKMARK")
            modern_missing = report.get("modern_missing") or []
            if modern_missing:
                col.label(
                    text=f"Opcionales no disponibles (se usa fallback): "
                         f"{len(modern_missing)}", icon="INFO")
                for m in modern_missing[:8]:
                    col.label(text=f"  · {m}", icon="BLANK1")
            else:
                col.label(text="Todos los nodos opcionales disponibles",
                          icon="CHECKMARK")
            col.separator()
            col.operator(PCM_OT_show_diagnostics.bl_idname, icon="WORDWRAP_ON")

    class PCM_OT_show_diagnostics(Operator):
        """Abre el informe completo de compatibilidad en un editor de texto"""

        bl_idname = "pcm.show_diagnostics"
        bl_label = "Informe de compatibilidad"
        bl_description = "Genera un informe detallado de nodos, sockets y versión"
        bl_options = {"REGISTER"}

        def execute(self, context: Any):  # noqa: D102
            from .diagnostics import build_report_text, write_report

            text = build_report_text(context)
            write_report(context, text)
            self.report({"INFO"}, "Informe de diagnóstico generado")
            return {"FINISHED"}

else:  # pragma: no cover

    class PCM_Preferences:  # type: ignore[no-redef]
        pass

    class PCM_OT_show_diagnostics:  # type: ignore[no-redef]
        bl_idname = "pcm.show_diagnostics"


def _on_verbose(self: Any) -> None:
    from .log import set_verbose

    set_verbose(bool(getattr(self, "verbose_log", False)))


def get_prefs() -> Any:
    """Preferencias del addon, o ``None`` si no están disponibles."""
    if bpy is None:
        return None
    try:
        return bpy.context.preferences.addons[PREF_PACKAGE].preferences
    except Exception:
        try:
            for key, addon in bpy.context.preferences.addons.items():
                if key.endswith(PREF_PACKAGE) or PREF_PACKAGE in key:
                    return addon.preferences
        except Exception:
            pass
    return None


_CLASSES: List[Any] = []


def register() -> None:
    if bpy is None:
        return
    global _CLASSES
    _CLASSES = [PCM_OT_show_diagnostics, PCM_Preferences]
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    prefs = get_prefs()
    if prefs is not None:
        set_language(getattr(prefs, "language", "es"))
        _on_verbose(prefs)


def unregister() -> None:
    if bpy is None:
        return
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
