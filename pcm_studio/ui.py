# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Interfaz.

Todo vive en un panel del *Properties* (pestaña Material) con subpaneles que
siguen el orden real de trabajo:

    1. Objeto          → preparar, UVs, estado
    2. Zonas           → lista de zonas asignadas + asignar a la selección
    3. Sugerencias     → detección automática con confirmación
    4. Selección       → herramientas tipo selección de caras
    5. Material        → estilo, escala de detalle, generador
    6. Parámetros      → controles de la zona activa, en vivo
    7. Bake            → mapas, calidad, modo de normal, progreso
    8. Exportar        → motor, formato, carpeta, guía

Además hay un panel espejo en la barra N del 3D Viewport para poder asignar
zonas sin salir del modelado, y menús en ``Object`` y ``Mesh``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import (assembler, bake, diagnostics, export, operators, properties,
               select_tools, uv as uvmod, zones as zones_mod)
from .i18n import T, get_language
from .log import log

try:  # pragma: no cover
    import bpy
    from bpy.types import Panel, UIList
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

    class Panel:  # type: ignore[no-redef]
        pass

    class UIList:  # type: ignore[no-redef]
        pass


__all__ = ("CLASSES", "register", "unregister")


# ---------------------------------------------------------------------------
# Iconos (con red de seguridad: los nombres cambian entre versiones)
# ---------------------------------------------------------------------------

_ICON_CACHE: Dict[str, str] = {}


def _icon(name: str, *fallbacks: str) -> str:
    """Devuelve el primer nombre de icono que exista en este Blender."""
    key = name + "|" + "|".join(fallbacks)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    out = "NONE"
    if bpy is not None:
        for cand in (name,) + fallbacks:
            if _icon_exists(cand):
                out = cand
                break
    _ICON_CACHE[key] = out
    return out


def _icon_exists(name: str) -> bool:
    """Comprueba si un icono existe en este Blender sin lanzar excepción."""
    if bpy is None:
        return False
    try:
        from bpy.types import UILayout

        enum = UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
        return name in enum
    except Exception:
        return False


# ---------------------------------------------------------------------------
# UILists
# ---------------------------------------------------------------------------

if bpy is not None:

    class PCM_UL_zones(UIList):
        """Zonas asignadas al objeto, con su color y nº de caras."""

        bl_idname = "PCM_UL_zones"
        bl_label = "Zonas"

        def draw_item(self, context: Any, layout: Any, data: Any, item: Any,
                      icon: Any, active_data: Any, active_property: str,
                      index: int = 0, flt_flag: int = 0) -> None:
            if self.layout_type in {"DEFAULT", "COMPACT"}:
                row = layout.row(align=True)
                row.label(text="", icon=_icon("SEQUENCE_COLOR", "MESH_DATA"))
                # el swatch de color real: un prop deshabilitado
                sub = row.row()
                sub.scale_x = 0.55
                sub.prop(item, "color", text="")
                sub.active = False
                if item.zone_key:
                    row.label(text=f"{item.zone_name}  ·  {item.face_count}")
                    op = row.operator("pcm.select_zone_from_list",
                                      text="", icon=_icon("PENCIL_ACTIVE", "EDITMODE_HLT"))
                    op.index = index
                    sel = row.operator("pcm.select_zone", text="",
                                       icon=_icon("RESTRICT_SELECT_OFF", "ZOOM_SELECTED"))
                    sel.zone_id = item.zone_id
                    sel.mode = "SET"
                else:
                    row.label(text=f"{item.zone_name}  ·  {item.face_count}",
                              icon=_icon("ERROR", "QUESTION"))
            else:
                layout.label(text=item.zone_name, icon_value=icon)

        def filter_items(self, context: Any, data: Any, prop: str) -> Tuple[List[int], List[int]]:
            """Filtrado por nombre de zona."""
            items = getattr(data, prop)
            flt = (self.filter_name or "").lower()
            flags = [
                self.bitflag_visible_item
                if not flt or flt in (it.zone_name or "").lower()
                else 0
                for it in items
            ]
            return flags, []

    class PCM_UL_proposals(UIList):
        """Zonas sugeridas por el analizador, pendientes de confirmación."""

        bl_idname = "PCM_UL_proposals"
        bl_label = "Zonas sugeridas"

        def draw_item(self, context: Any, layout: Any, data: Any, item: Any,
                      icon: Any, active_data: Any, active_property: str,
                      index: int = 0, flt_flag: int = 0) -> None:
            row = layout.row(align=True)
            row.prop(item, "apply", text="")
            col = row.column(align=True)
            head = col.row(align=True)
            head.prop(item, "zone_name", text="", emboss=False)
            head.label(text=f"{item.face_count} caras")
            conf = item.confidence
            bar = head.row()
            bar.scale_x = 0.6
            if conf >= 0.6:
                bar.label(text="●●●", icon=_icon("CHECKMARK", "NONE"))
            elif conf >= 0.4:
                bar.label(text="●●○")
            else:
                bar.label(text="●○○")
                bar.alert = True
            detail = col.row(align=True)
            detail.scale_y = 0.75
            detail.label(text=f"{item.reason} · {conf * 100:.0f} %",
                         icon=_icon("INFO", "QUESTION"))
            op = row.operator("pcm.proposal_select", text="",
                              icon=_icon("RESTRICT_SELECT_OFF", "ZOOM_SELECTED"))
            op.index = index

else:  # pragma: no cover - fuera de Blender

    class PCM_UL_zones:  # type: ignore[no-redef]
        pass

    class PCM_UL_proposals:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Paneles
# ---------------------------------------------------------------------------

if bpy is not None:

    class PCM_PT_base(Panel):
        """Panel raíz en la pestaña Material del editor de Propiedades."""

        bl_space_type = "PROPERTIES"
        bl_region_type = "WINDOW"
        bl_context = "material"
        bl_label = "PCM Studio"
        bl_category = "PCM"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            sp = properties.get_scene(context)
            lang = get_language()

            col = layout.column(align=True)
            if obj is None or obj.type != "MESH":
                box = col.box()
                box.label(text=T("Selecciona un objeto de malla"),
                          icon=_icon("ERROR", "CANCEL"))
                box.label(text="Este addon trabaja sobre mallas con UVs.")
                return

            props = properties.get_object(obj)
            data = obj.data
            nfaces = len(data.polygons)
            zmap = assembler.assigned_zones(data)
            assigned = sum(zmap.values())

            # --- cabecera de estado -------------------------------------
            row = col.row(align=True)
            row.label(text=obj.name, icon=_icon("OUTLINER_OB_MESH", "MESH_DATA"))
            row.label(text=f"{nfaces} caras", icon=_icon("MESH_DATA", "MOD_MESHDEFORM"))

            pct = (assigned / nfaces * 100.0) if nfaces else 0.0
            sub = col.column(align=True)
            r = sub.row(align=True)
            r.label(text=f"{T('Zonas asignadas')}: {pct:.0f} %",
                    icon=_icon("PAINTFACE", "GROUP_VCOL"))
            if pct < 100.0:
                r2 = sub.row(align=True)
                r2.alert = nfaces - assigned > 0
                r2.label(text=f"{nfaces - assigned} caras sin zona "
                              f"(usarán piel corporal)")
            style = operators._style_of(obj)
            col.label(text=f"{T('Estilo')}: {style.name(lang)}",
                      icon=_icon("BRUSH_DATA", "NODETREE"))
            if not uvmod.has_uv(obj):
                w = col.column()
                w.alert = True
                w.label(text=T("El objeto necesita UVs"),
                        icon=_icon("ERROR", "MOD_UVPROJECT"))

            # --- botones principales -------------------------------------
            box = col.box()
            row = box.row(align=True)
            row.scale_y = 1.35
            row.operator("pcm.prepare_object",
                         icon=_icon("MOD_UVPROJECT", "MESH_DATA"))
            row.operator("pcm.build_material",
                         icon=_icon("NODETREE", "MATERIAL"))

            if sp is not None and getattr(sp, "is_baking", False):
                prog = box.column(align=True)
                prog.label(text=getattr(sp, "bake_status", "") or T("Bakeando"),
                           icon=_icon("RENDER_ANIMATION", "PLAY"))
                prog.prop(sp, "bake_progress", text="Progreso")
                prog.operator("pcm.cancel_bake", icon=_icon("X", "CANCEL"))

            row = col.row(align=True)
            row.scale_y = 1.15
            op = row.operator("pcm.bake", icon=_icon("RENDER_STILL", "PLAY"))
            op.export_after = True
            row.operator("pcm.export_maps", icon=_icon("FILE_FOLDER", "EXPORT"))

            # --- idioma ----------------------------------------------------
            rr = col.row(align=True)
            rr.scale_y = 0.85
            rr.operator("pcm.toggle_language", text="EN / ES",
                        icon=_icon("WORLD", "LANGUAGE"))
            rr.operator("pcm.report", text="", icon=_icon("INFO", "TEXT"))
            rr.operator("pcm.show_diagnostics", text="",
                        icon=_icon("WORDWRAP_ON", "TEXT"))

    class PCM_Panel:
        """Base para los subpaneles."""

        bl_space_type = "PROPERTIES"
        bl_region_type = "WINDOW"
        bl_context = "material"
        bl_parent_id = "PCM_PT_base"
        bl_options = {"DEFAULT_CLOSED"}

    class PCM_PT_object(PCM_Panel, Panel):
        bl_label = "1 · Objeto y UVs"
        bl_options = set()

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                return
            props = properties.get_object(obj)
            sp = properties.get_scene(context)
            res = operators._resolution(context)

            col = layout.column(align=True)
            col.label(text=f"Objeto: {obj.name}")
            info = uvmod.check_uv_quality(obj, res)
            col.label(text=f"{T('Capas UV')}: {', '.join(info.get('layers', [])) or '—'}")
            col.label(text=f"{T('Cobertura')}: {info.get('coverage', 0.0) * 100:.1f} %")
            col.label(text=f"Densidad: {info.get('texel_density', 0.0):.2f} tex/cm²")
            if info.get("outside", 0):
                r = col.row()
                r.alert = True
                r.label(text=f"{info['outside']} caras fuera del mapa",
                        icon=_icon("ERROR", "CANCEL"))
            verdict = info.get("verdict", "")
            if verdict:
                col.label(text=verdict, icon=_icon("INFO", "TEXT"))

            row = col.row(align=True)
            row.operator("pcm.uv_report", icon=_icon("VIEWZOOM", "ZOOM_ALL"))
            row.operator("pcm.uv_pack", icon=_icon("UV_ISLANDSEL", "MOD_UVPROJECT"))

            col.separator()
            if props is not None:
                col.prop(props, "show_zone_colors",
                         icon=_icon("GROUP_VCOL", "SEQUENCE_COLOR"))
                col.operator("pcm.cleanup", icon=_icon("FILE_REFRESH", "X"))

    class PCM_PT_zones(PCM_Panel, Panel):
        bl_label = "2 · Zonas"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                return
            props = properties.get_object(obj)
            if props is None:
                return
            lang = get_language()

            # selector de zona activa, agrupado por categoría
            box = layout.box()
            box.label(text=T("Zona") + " (se aplicará a la selección):",
                      icon=_icon("PAINTFACE", "BRUSH_DATA"))
            row = box.row(align=True)
            row.scale_y = 1.3
            row.prop(props, "active_zone", text="")

            zone = zones_mod.get_zone_by_key(props.active_zone)
            if zone is not None:
                d = box.row()
                d.label(text=zone.desc(lang) or "—",
                        icon=_icon("INFO", "TEXT"))
                meta = box.column(align=True)
                meta.scale_y = 0.8
                tags = []
                if zone.sss:
                    tags.append("SSS")
                if zone.transmissive:
                    tags.append("Translúcido")
                if zone.emissive:
                    tags.append("Emisivo")
                if zone.alpha:
                    tags.append("Alfa")
                if zone.two_sided:
                    tags.append("Doble cara")
                if tags:
                    meta.label(text="· ".join(tags))
                meta.label(text=f"{len(zone.params)} controles · "
                                f"categoría {zone.category}")

            # lista de zonas asignadas
            row = layout.row()
            row.template_list("PCM_UL_zones", "", props, "zone_items",
                              props, "zone_items", rows=4)
            col = row.column(align=True)
            col.operator("pcm.propose_zones", text="",
                         icon=_icon("LIGHTPROBE_GRID", "AUTO"))
            col.operator("pcm.refresh_zones", text="",
                         icon=_icon("FILE_REFRESH", "NONE"))

            layout.separator()
            split = layout.split(factor=0.55)
            c1 = split.column(align=True)
            c1.label(text="Aplicar a la selección:", icon=_icon("PAINTFACE", "NONE"))
            r = c1.row(align=True)
            op = r.operator("pcm.assign_zone", text="Asignar")
            op.mode = "SET"
            op2 = r.operator("pcm.assign_zone", text="", icon=_icon("X", "NONE"))
            op2.mode = "CLEAR"
            op2.rebuild = True

            c2 = split.column(align=True)
            c2.label(text="Opciones:")
            sub = c2.column(align=True)
            sub.scale_y = 0.85
            sub.prop(props, "auto_rebuild")
            r2 = c2.row(align=True)
            r2.operator("pcm.assign_zone", text="Isla UV completa").whole_islands = True
            c2.operator("pcm.select_zone", text="Seleccionar la zona activa",
                        icon=_icon("RESTRICT_SELECT_OFF", "ZOOM_SELECTED"))

            layout.separator()
            row = layout.row(align=True)
            row.operator("pcm.clear_zones", icon=_icon("TRASH", "X"))
            g = layout.column(align=True)
            g.label(text="Ampliar selección:", icon=_icon("SELECT_EXTEND", "ZOOM_IN"))
            r = g.row(align=True)
            op = r.operator("pcm.select_grow", text="Más")
            op.shrink = False
            op.iterations = 1
            op = r.operator("pcm.select_grow", text="Menos")
            op.shrink = True
            op.iterations = 1
            r.operator("pcm.select_uv_islands", text="Islas UV",
                       icon=_icon("UV_ISLANDSEL", "GROUP_UVS"))

    class PCM_PT_proposals(PCM_Panel, Panel):
        bl_label = "3 · Zonas sugeridas"

        @classmethod
        def poll(cls, context: Any) -> bool:
            obj = context.active_object
            props = properties.get_object(obj) if obj is not None else None
            return props is not None and len(props.proposals) > 0

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            props = properties.get_object(obj)
            if props is None:
                return
            layout.label(text="Revisa cada propuesta y marca las que quieras aplicar.",
                         icon=_icon("INFO", "TEXT"))
            layout.template_list("PCM_UL_proposals", "", props, "proposals",
                                 props, "proposals", rows=min(8, len(props.proposals)))
            row = layout.row(align=True)
            row.scale_y = 1.2
            op = row.operator("pcm.apply_proposals", text="Aplicar marcadas",
                              icon=_icon("CHECKMARK", "FILE_TICK"))
            op.only_confident = False
            op = row.operator("pcm.apply_proposals", text="Sólo ≥ 50 %")
            op.only_confident = True
            row = layout.row(align=True)
            row.operator("pcm.clear_proposals", text="Descartar todas",
                         icon=_icon("X", "TRASH"))

    class PCM_PT_selection(PCM_Panel, Panel):
        bl_label = "4 · Herramientas de selección"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                return
            n = len(select_tools.selected_face_indices(obj))
            head = layout.row()
            head.label(text=f"{n} {T('caras')} {T('seleccionadas')}",
                       icon=_icon("RESTRICT_SELECT_OFF", "ZOOM_SELECTED"))

            layout.label(text="Por orientación:", icon=_icon("ORIENT_NORMAL", "NONE"))
            flow = layout.grid_flow(row_major=True, columns=3, even_columns=True)
            for direction, text in (("+Z", "Arriba"), ("-Z", "Abajo"),
                                    ("+Y", "Frente"), ("-Y", "Detrás"),
                                    ("+X", "Derecha"), ("-X", "Izquierda")):
                op = flow.operator("pcm.select_by_normal", text=text)
                op.direction = direction
                op.angle = 45.0
                op.mode = "ADD"
            row = layout.row(align=True)
            op = row.operator("pcm.select_by_normal", text="Añadir")
            op.mode = "ADD"
            op = row.operator("pcm.select_by_normal", text="Quitar")
            op.mode = "SUBTRACT"

            layout.separator()
            layout.label(text="Por forma:", icon=_icon("SPHERE", "MESH_UVSPHERE"))
            row = layout.row(align=True)
            op = row.operator("pcm.select_by_curvature", text="Pliegues (cóncavo)")
            op.convex = False
            op.mode = "ADD"
            op = row.operator("pcm.select_by_curvature", text="Relieve (convexo)")
            op.convex = True
            op.mode = "ADD"

            layout.separator()
            row = layout.row(align=True)
            row.operator("pcm.select_by_position", text="Esfera / caja en el cursor",
                         icon=_icon("EMPTY_ARROWS", "SPHERE"))
            layout.operator("pcm.smooth_groups",
                            icon=_icon("MOD_SMOOTH", "MOD_SUBSURF"))
            layout.label(text="«Grupos de suavizado» separa ojos, dientes y lengua "
                              "en cabezas importadas.", icon=_icon("INFO", "TEXT"))

    class PCM_PT_material(PCM_Panel, Panel):
        bl_label = "5 · Estilo y material"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                return
            props = properties.get_object(obj)
            if props is None:
                return
            lang = get_language()
            style = operators._style_of(obj)

            layout.prop(props, "style", text=T("Estilo"))
            box = layout.box()
            box.label(text=style.desc(lang), icon=_icon("INFO", "TEXT"))
            meta = box.column(align=True)
            meta.scale_y = 0.8
            meta.label(text=f"Resolución recomendada: {style.bake_resolution} px · "
                            f"{style.bake_samples} muestras")
            meta.label(text=f"ORM empaquetado: {'sí' if style.pack_orm else 'no'}")

            layout.separator()
            layout.prop(props, "uv_scale", slider=True)
            op = layout.operator("pcm.set_uv_scale", text="Aplicar escala y reconstruir",
                                 icon=_icon("FILE_REFRESH", "NONE"))
            op.scale = props.uv_scale

            layout.separator()
            row = layout.row(align=True)
            row.scale_y = 1.2
            op = row.operator("pcm.build_material", icon=_icon("NODETREE", "MATERIAL"))
            op.force = False
            op = row.operator("pcm.build_material", text="Forzar",
                              icon=_icon("FILE_REFRESH", "NONE"))
            op.force = True

            mat = assembler._existing_pcm_material(obj)
            if mat is not None:
                info = diagnostics.count_nodes(getattr(mat, "node_tree", None))
                layout.label(text=f"{mat.name} · {info} nodos",
                             icon=_icon("NODE", "NODETREE"))
                row = layout.row(align=True)
                row.operator("pcm.save_preset", icon=_icon("FILEBLANK", "ADD"))
                row.operator("pcm.load_preset", icon=_icon("FILE_FOLDER", "ZOOM_PREV"))

    class PCM_PT_params(PCM_Panel, Panel):
        bl_label = "6 · Parámetros de la zona"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                return
            props = properties.get_object(obj)
            if props is None:
                return
            editor = getattr(props, "zone_params", None)
            zone = zones_mod.get_zone_by_key(props.active_zone)
            if editor is None or zone is None:
                layout.label(text="Elige una zona", icon=_icon("INFO", "TEXT"))
                return

            head = layout.row(align=True)
            head.label(text=zone.name(get_language()), icon=_icon("BRUSH_DATA", "NONE"))
            head.prop(editor, "live", text="", icon=_icon("PLAY", "RENDER_ANIMATION"))

            if getattr(editor, "current_zone", "") != zone.key:
                w = layout.column()
                w.label(text="Los valores mostrados son de otra zona.",
                        icon=_icon("ERROR", "INFO"))
                w.operator("pcm.reload_zone_params", text="Cargar los de esta zona",
                           icon=_icon("FILE_REFRESH", "NONE"))

            # controles agrupados
            groups: Dict[str, List[Any]] = {}
            for prm in zone.params:
                groups.setdefault(prm.group or "General", []).append(prm)
            for gname, params in groups.items():
                box = layout.box()
                box.label(text=gname)
                col = box.column(align=True)
                for prm in params:
                    ident = properties.param_ident(zone.key, prm.name)
                    if not hasattr(editor, ident):
                        continue
                    if prm.kind == "COLOR":
                        col.prop(editor, ident, text=prm.name)
                    elif prm.kind == "BOOL":
                        col.prop(editor, ident, text=prm.name)
                    elif prm.kind == "INT":
                        col.prop(editor, ident, text=prm.name, slider=False)
                    else:
                        col.prop(editor, ident, text=prm.name, slider=True)

            layout.separator()
            row = layout.row(align=True)
            row.scale_y = 1.15
            op = row.operator("pcm.apply_zone_params",
                              icon=_icon("CHECKMARK", "FILE_TICK"))
            op.rebuild = False
            op = row.operator("pcm.apply_zone_params", text="Reconstruir")
            op.rebuild = True
            row.operator("pcm.reload_zone_params", text="",
                         icon=_icon("FILE_REFRESH", "NONE"))
            layout.label(text="Los parámetros se guardan dentro del .blend y en el "
                              "manifiesto de exportación.", icon=_icon("INFO", "TEXT"))

    class PCM_PT_bake(PCM_Panel, Panel):
        bl_label = "7 · Bake"

        def draw(self, context: Any) -> None:
            layout = self.layout
            sp = properties.get_scene(context)
            obj = context.active_object
            if sp is None or obj is None:
                return
            lang = get_language()
            busy = bool(getattr(sp, "is_baking", False))

            layout.enabled = not busy

            layout.prop(sp, "engine", text=T("Motor de destino"))
            row = layout.row(align=True)
            for engine, text in (("unity", "Unity"), ("unreal", "Unreal"),
                                 ("godot", "Godot"), ("generic", "glTF")):
                op = row.operator("pcm.set_engine", text=text)
                op.engine = engine

            layout.separator()
            layout.label(text=T("Mapas") + ":", icon=_icon("TEXTURE", "IMAGE_DATA"))
            grid = layout.grid_flow(row_major=True, columns=2, even_columns=True)
            for key in ("basecolor", "normal", "roughness", "metallic", "ao",
                        "height", "emission", "alpha"):
                grid.prop(sp, f"bake_{key}", text=bake.MAPS[key]["label"])
            layout.prop(sp, "bake_normal_overlay")

            layout.separator()
            box = layout.box()
            box.label(text="Calidad:", icon=_icon("RENDER_STILL", "PLAY"))
            box.prop(sp, "resolution", text=T("Resolución de bake"))
            box.prop(sp, "samples")
            box.prop(sp, "use_denoise")
            box.prop(sp, "margin")
            box.prop(sp, "margin_type")

            box = layout.box()
            box.label(text="Normal:", icon=_icon("NORMALS_FACE", "MESH_DATA"))
            box.prop(sp, "normal_mode", text="")
            box.prop(sp, "normal_convention", text="")
            if sp.normal_mode == "displaced":
                box.prop(sp, "dicing_rate", slider=True)
                box.prop(sp, "max_subdivisions")
                w = box.column()
                w.scale_y = 0.8
                w.label(text="El micro-detalle se convierte en geometría y acaba "
                             "en el mapa: es lo que da una normal creíble.",
                        icon=_icon("INFO", "TEXT"))
                w.label(text="Lento a 4K con teselado bajo. Sube el teselado si "
                             "tarda demasiado.", icon=_icon("SORTTIME", "TIME"))
            elif sp.normal_mode == "overlay":
                box.label(text="Marca también «Normal de detalle» arriba para "
                             "obtener el segundo mapa.", icon=_icon("INFO", "TEXT"))
            box.prop(sp, "use_multires")

            layout.separator()
            row = layout.row(align=True)
            row.scale_y = 1.4
            if busy:
                row.operator("pcm.cancel_bake", icon=_icon("X", "CANCEL"))
            else:
                op = row.operator("pcm.bake", icon=_icon("RENDER_STILL", "PLAY"))
                op.export_after = False
                op = row.operator("pcm.bake", text="Bakear y exportar")
                op.export_after = True
            if busy:
                col = layout.column(align=True)
                col.label(text=getattr(sp, "bake_status", "") or T("Bakeando"),
                          icon=_icon("RENDER_ANIMATION", "PLAY"))
                col.prop(sp, "bake_progress", text="")

    class PCM_PT_export(PCM_Panel, Panel):
        bl_label = "8 · Exportar al motor"

        def draw(self, context: Any) -> None:
            layout = self.layout
            sp = properties.get_scene(context)
            obj = context.active_object
            if sp is None or obj is None:
                return

            col = layout.column(align=True)
            col.prop(sp, "output_dir")
            col.prop(sp, "prefix")
            row = col.row(align=True)
            row.prop(sp, "file_format", text="")
            row.prop(sp, "color_depth", text="")

            col.separator()
            col.prop(sp, "pack_channels")
            if sp.pack_channels:
                col.prop(sp, "export_orm")
                r = col.row()
                r.scale_y = 0.8
                engine = getattr(sp, "engine", "unity")
                order = "R=AO, G=Rugosidad, B=Metálico" if engine != "unity" \
                    else "R=AO, G=Suavizado, B=Metálico (Mask Map)"
                r.label(text=order, icon=_icon("INFO", "TEXT"))
            col.prop(sp, "save_blend_copy")

            col.separator()
            row = col.row(align=True)
            row.scale_y = 1.3
            op = row.operator("pcm.export_maps", icon=_icon("FILE_FOLDER", "EXPORT"))
            op.open_folder = True
            op.save_blend_copy = sp.save_blend_copy
            op = row.operator("pcm.export_maps", text="",
                              icon=_icon("FILEBROWSER", "FILE_FOLDER"))
            op.open_folder = False

            col.separator()
            col.operator("pcm.show_import_guide",
                         icon=_icon("FILE_TEXT", "WORDWRAP_ON"))

            # nomenclatura de lo que se va a generar
            box = col.box()
            box.label(text="Ficheros que se generarán:",
                      icon=_icon("TEXT", "FILE_TEXT"))
            prefix = (sp.prefix or "").strip() or bake.clean_name(obj.name)
            try:
                res = int(sp.resolution)
            except Exception:
                res = 4096
            engine = getattr(sp, "engine", "unity")
            keys = properties.map_flags(sp)
            if sp.export_orm and sp.pack_channels and "ao" in keys and "roughness" in keys:
                keys = keys + ["orm"]
            inner = box.column(align=True)
            inner.scale_y = 0.8
            if not keys:
                inner.label(text="Ninguno: marca mapas en «7 · Bake»")
            for key in keys:
                inner.label(text=export.texture_file_name(prefix, key, engine, res,
                                                          export.ext_for_format(
                                                              sp.file_format)))

    # -----------------------------------------------------------------------
    # Panel del 3D Viewport (barra N)
    # -----------------------------------------------------------------------

    class PCM_PT_viewport(Panel):
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "PCM"
        bl_label = "PCM Studio"

        def draw(self, context: Any) -> None:
            layout = self.layout
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                layout.label(text=T("Selecciona un objeto de malla"),
                             icon=_icon("ERROR", "CANCEL"))
                return
            props = properties.get_object(obj)
            sp = properties.get_scene(context)
            if props is None:
                return
            n = len(select_tools.selected_face_indices(obj))

            col = layout.column(align=True)
            col.label(text=obj.name, icon=_icon("OUTLINER_OB_MESH", "MESH_DATA"))
            col.prop(props, "active_zone", text="")
            row = col.row(align=True)
            row.scale_y = 1.25
            op = row.operator("pcm.assign_zone", text=f"Asignar ({n})",
                              icon=_icon("PAINTFACE", "BRUSH_DATA"))
            op.mode = "SET"
            op2 = row.operator("pcm.assign_zone", text="", icon=_icon("X", "NONE"))
            op2.mode = "CLEAR"

            col.separator()
            col.prop(props, "show_zone_colors", text="Ver zonas",
                     icon=_icon("GROUP_VCOL", "SEQUENCE_COLOR"))
            row = col.row(align=True)
            op = row.operator("pcm.select_grow", text="Más",
                              icon=_icon("SELECT_EXTEND", "ZOOM_IN"))
            op.shrink = False
            op = row.operator("pcm.select_grow", text="Menos",
                              icon=_icon("SELECT_SUBTRACT", "ZOOM_OUT"))
            op.shrink = True
            row = col.row(align=True)
            row.operator("pcm.select_zone", text="Sel. zona",
                         icon=_icon("RESTRICT_SELECT_OFF", "ZOOM_SELECTED"))
            row.operator("pcm.select_uv_islands", text="Islas UV",
                         icon=_icon("UV_ISLANDSEL", "GROUP_UVS"))

            col.separator()
            row = col.row(align=True)
            row.operator("pcm.propose_zones", text="Sugerir",
                         icon=_icon("LIGHTPROBE_GRID", "AUTO"))
            if len(props.proposals):
                op = row.operator("pcm.apply_proposals", text=f"Aplicar ({len(props.proposals)})",
                                  icon=_icon("CHECKMARK", "FILE_TICK"))
                op.only_confident = True

            col.separator()
            row = col.row(align=True)
            row.scale_y = 1.2
            row.operator("pcm.build_material", text="Material",
                         icon=_icon("NODETREE", "MATERIAL"))
            if sp is not None and getattr(sp, "is_baking", False):
                row.operator("pcm.cancel_bake", text="Parar",
                             icon=_icon("X", "CANCEL"))
            else:
                op = row.operator("pcm.bake", text="Bake",
                                  icon=_icon("RENDER_STILL", "PLAY"))
                op.export_after = True

    # -----------------------------------------------------------------------
    # Menús
    # -----------------------------------------------------------------------

    def _menu_object(self: Any, context: Any) -> None:
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return
        self.layout.separator()
        self.layout.label(text="PCM Studio", icon=_icon("BRUSH_DATA", "NODETREE"))
        self.layout.operator("pcm.prepare_object")
        self.layout.operator("pcm.propose_zones")
        self.layout.operator("pcm.build_material")
        self.layout.operator("pcm.bake")
        self.layout.operator("pcm.export_maps")
        self.layout.operator("pcm.report")

    def _menu_mesh(self: Any, context: Any) -> None:
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return
        self.layout.separator()
        self.layout.label(text="PCM Studio", icon=_icon("BRUSH_DATA", "NODETREE"))
        props = properties.get_object(obj)
        if props is not None:
            op = self.layout.operator("pcm.assign_zone", text="Asignar zona PCM")
            op.mode = "SET"
        self.layout.operator("pcm.select_by_curvature", text="Seleccionar pliegues")
        self.layout.operator("pcm.smooth_groups")
        self.layout.operator("pcm.uv_report")

    def _menu_node_editor(self: Any, context: Any) -> None:
        self.layout.separator()
        self.layout.operator("pcm.report", text="PCM: informe del material")

else:  # pragma: no cover - fuera de Blender

    class PCM_PT_base:  # type: ignore[no-redef]
        pass

    class PCM_PT_object:  # type: ignore[no-redef]
        pass

    class PCM_PT_zones:  # type: ignore[no-redef]
        pass

    class PCM_PT_proposals:  # type: ignore[no-redef]
        pass

    class PCM_PT_selection:  # type: ignore[no-redef]
        pass

    class PCM_PT_material:  # type: ignore[no-redef]
        pass

    class PCM_PT_params:  # type: ignore[no-redef]
        pass

    class PCM_PT_bake:  # type: ignore[no-redef]
        pass

    class PCM_PT_export:  # type: ignore[no-redef]
        pass

    class PCM_PT_viewport:  # type: ignore[no-redef]
        pass

    def _menu_object(self: Any, context: Any) -> None:  # type: ignore[no-redef]
        pass

    def _menu_mesh(self: Any, context: Any) -> None:  # type: ignore[no-redef]
        pass

    def _menu_node_editor(self: Any, context: Any) -> None:  # type: ignore[no-redef]
        pass


CLASSES: Tuple[Any, ...] = (
    PCM_UL_zones,
    PCM_UL_proposals,
    PCM_PT_base,
    PCM_PT_object,
    PCM_PT_zones,
    PCM_PT_proposals,
    PCM_PT_selection,
    PCM_PT_material,
    PCM_PT_params,
    PCM_PT_bake,
    PCM_PT_export,
    PCM_PT_viewport,
)

_MENU_TARGETS = (
    ("VIEW_3D_MT_object_context_menu", _menu_object),
    ("VIEW_3D_MT_select_mesh_context_menu", _menu_mesh),
    ("NODE_EDITOR_MT_editor_menus", _menu_node_editor),
)

_APPENDED: List[Tuple[Any, Any]] = []


def register() -> None:
    if bpy is None:
        return
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            if "already registered" not in str(exc).lower():
                log.error("No se pudo registrar %s: %s", getattr(cls, "__name__", cls), exc)
                raise
    for name, fn in _MENU_TARGETS:
        menu = getattr(bpy.types, name, None)
        if menu is None:
            continue
        try:
            menu.append(fn)
            _APPENDED.append((menu, fn))
        except Exception as exc:
            log.debug("No se pudo añadir el menú %s: %s", name, exc)


def unregister() -> None:
    if bpy is None:
        return
    for menu, fn in reversed(_APPENDED):
        try:
            menu.remove(fn)
        except Exception:
            pass
    _APPENDED.clear()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
