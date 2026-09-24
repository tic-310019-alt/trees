# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Operadores.

El flujo de trabajo completo, en el orden en que lo usa un artista:

1. :class:`PCM_OT_prepare_object`    prepara UVs y atributo de zonas.
2. Seleccionar caras + :class:`PCM_OT_assign_zone` (o ``pcm.propose_zones``,
   que sugiere zonas a partir de la geometría y pide confirmación).
3. :class:`PCM_OT_build_material`    genera el material procedural.
4. Ajustar parámetros en el panel (edición en vivo).
5. :class:`PCM_OT_bake`              modal: bakea un mapa por paso.
6. :class:`PCM_OT_export_maps`       escribe ficheros + manifiesto + guía.

Todos los operadores son defensivos: si falta algo (UVs, Cycles, un socket de
Blender 5.x) avisan con un mensaje accionable en lugar de lanzar una excepción.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from . import (assembler, bake, diagnostics, export, properties, select_tools,
               styles, uv as uvmod, zones as zones_mod)
from .i18n import T, get_language
from .log import log

try:  # pragma: no cover
    import bpy
    from bpy.types import Operator
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

    class Operator:  # type: ignore[no-redef]
        pass


__all__ = ("CLASSES", "register", "unregister")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sp(context: Any) -> Optional[Any]:
    """Propiedades de escena."""
    return properties.get_scene(context)


def _op(context: Any, obj: Any = None) -> Optional[Any]:
    """Propiedades del objeto activo (o del indicado)."""
    o = obj if obj is not None else getattr(context, "active_object", None)
    return properties.get_object(o)


def _target(context: Any) -> Optional[Any]:
    """Objeto malla activo."""
    obj = getattr(context, "active_object", None)
    if obj is None or getattr(obj, "type", "") != "MESH":
        return None
    return obj


def _report(op: Any, level: str, message: str) -> None:
    """Aviso al usuario + log."""
    try:
        op.report({level}, message)
    except Exception:
        pass
    (log.warning if level in ("WARNING", "ERROR") else log.info)("%s", message)


def _style_of(obj: Any) -> Any:
    props = properties.get_object(obj)
    sid = getattr(props, "style", None) or styles.default_style_id()
    return styles.get_style(sid)


def refresh_zone_items(obj: Any) -> None:
    """Sincroniza la lista de zonas del panel con la malla."""
    props = properties.get_object(obj)
    if props is None:
        return
    data = getattr(obj, "data", None)
    if data is None:
        return
    lang = get_language()
    counts = assembler.assigned_zones(data)
    items = props.zone_items
    try:
        items.clear()
    except Exception:
        pass
    total = len(getattr(data, "polygons", ()))
    assigned = sum(counts.values())
    for zid, count in sorted(counts.items()):
        zone = zones_mod.get_zone(zid)
        entry = items.add()
        entry.zone_id = zid
        entry.zone_key = zone.key if zone else "custom"
        entry.zone_name = zone.name(lang) if zone else f"Zona {zid}"
        entry.face_count = count
        entry.color = tuple(zone.color) if zone else (0.5, 0.5, 0.5)
    # la fila "sin asignar" siempre la última, si procede
    if total - assigned > 0:
        entry = items.add()
        entry.zone_id = 0
        entry.zone_key = ""
        entry.zone_name = T("Sin asignar")
        entry.face_count = total - assigned
        entry.color = (0.35, 0.35, 0.38)


def refresh_zone_params(context: Any, obj: Any) -> None:
    """Carga en el editor los valores actuales de la zona activa."""
    props = properties.get_object(obj)
    if props is None:
        return
    editor = getattr(props, "zone_params", None)
    if editor is None:
        return
    zone = zones_mod.get_zone_by_key(getattr(props, "active_zone", ""))
    if zone is None:
        return
    mat = assembler._existing_pcm_material(obj)
    saved = assembler.load_user_params(mat).get(zone.key, {})
    setattr(editor, "current_zone", zone.key)
    for prm in zone.params:
        ident = properties.param_ident(zone.key, prm.name)
        if not hasattr(editor, ident):
            continue
        value = saved.get(prm.name, prm.default)
        try:
            setattr(editor, ident, value)
        except Exception:
            try:
                setattr(editor, ident, tuple(value))
            except Exception:
                pass


def apply_zone_params(context: Any, obj: Any) -> int:
    """Vuelca el editor de parámetros al material. Devuelve nº de cambios."""
    props = properties.get_object(obj)
    if props is None:
        return 0
    editor = getattr(props, "zone_params", None)
    zone = zones_mod.get_zone_by_key(getattr(props, "active_zone", ""))
    if editor is None or zone is None:
        return 0
    changed = 0
    for prm in zone.params:
        ident = properties.param_ident(zone.key, prm.name)
        if not hasattr(editor, ident):
            continue
        value = getattr(editor, ident)
        if hasattr(value, "__len__"):
            value = tuple(float(x) for x in value)
        if assembler.set_zone_param(obj, zone.key, prm.name, value, rebuild=False):
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# 1. Preparación del objeto
# ---------------------------------------------------------------------------

if bpy is not None:

    class PCM_OT_prepare_object(Operator):
        """Prepara el objeto: comprueba o crea las UVs y el atributo de zonas"""

        bl_idname = "pcm.prepare_object"
        bl_label = "Preparar objeto"
        bl_description = ("Comprueba que el objeto tiene UVs (las crea con Smart UV "
                          "Project si no), añade el atributo de zonas y activa la "
                          "visualización por colores. No modifica nada más")
        bl_options = {"REGISTER", "UNDO"}

        create_uv: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Crear UVs si faltan",
            description="Genera un mapa UV con Smart UV Project si el objeto no "
                        "tiene ninguno. Nunca toca los UVs existentes",
            default=True,
        )
        show_colors: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Ver zonas en el viewport",
            description="Activa el atributo de color para ver cada zona de su color",
            default=True,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                _report(self, "ERROR", T("Selecciona un objeto de malla"))
                return {"CANCELLED"}
            props = _op(context, obj)

            # UVs
            had_uv = uvmod.has_uv(obj)
            if not had_uv:
                if not self.create_uv:
                    _report(self, "ERROR",
                            T("El objeto necesita UVs") + " — " +
                            "activa «Crear UVs si faltan» o proyéctalas a mano")
                    return {"CANCELLED"}
                prefs = _prefs()
                angle = getattr(prefs, "uv_margin_angle", 66.0) if prefs else 66.0
                if not uvmod.ensure_uv(obj, margin_angle=angle):
                    _report(self, "ERROR", "No se pudieron crear las UVs")
                    return {"CANCELLED"}
                _report(self, "INFO", "UVs creadas con Smart UV Project "
                                      f"(ángulo {angle:.0f}°)")

            # atributo de zonas
            assembler.ensure_zone_attribute(obj.data)
            if self.show_colors and props is not None:
                props.show_zone_colors = True
                assembler.zone_color_attribute(obj.data)

            # material vacío listo para recibir zonas
            assembler.ensure_material(obj, style=_style_of(obj))
            if props is not None:
                props.prepared = True
            refresh_zone_items(obj)
            refresh_zone_params(context, obj)

            quality = uvmod.check_uv_quality(obj, _resolution(context))
            msg = quality.get("verdict", "")
            _report(self, "INFO", f"{obj.name}: {T('Preparado')}. {msg}")
            for w in quality.get("warnings", []):
                _report(self, "WARNING", w)
            return {"FINISHED"}

    class PCM_OT_uv_report(Operator):
        """Analiza las UVs: cobertura, densidad de texel y caras fuera del mapa"""

        bl_idname = "pcm.uv_report"
        bl_label = "Comprobar UVs"
        bl_description = ("Informa de la cobertura del mapa UV, la densidad de "
                          "texel a la resolución elegida y cuántas caras quedan "
                          "fuera del espacio 0..1")
        bl_options = {"REGISTER"}

        select_outside: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Seleccionar las caras fuera del mapa",
            description="Además de informar, selecciona en modo edición las caras "
                        "que caen fuera del espacio UV",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            res = _resolution(context)
            q = uvmod.check_uv_quality(obj, res)
            lines = [
                f"{T('Capas UV')}: {', '.join(q.get('layers', [])) or '—'}",
                f"{T('Cobertura')}: {q.get('coverage', 0.0) * 100:.1f} %",
                f"Densidad de texel: {q.get('texel_density', 0.0):.2f} tex/cm² "
                f"a {res} px",
                f"Caras fuera del mapa: {q.get('outside', 0)}",
                f"Veredicto: {q.get('verdict', '—')}",
            ]
            for w in q.get("warnings", []):
                lines.append(f"· {w}")
            text = "\n".join(lines)
            log.info("UVs de %s:\n%s", obj.name, text)
            _report(self, "WARNING" if q.get("warnings") else "INFO",
                    f"{q.get('verdict', '')} · fuera del mapa: {q.get('outside', 0)}")
            if self.select_outside and q.get("outside", 0):
                n = uvmod.select_outside_uv(obj)
                _report(self, "INFO", f"{n} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_uv_pack(Operator):
        """Reempaqueta las islas UV con margen"""

        bl_idname = "pcm.uv_pack"
        bl_label = "Empaquetar islas UV"
        bl_description = ("Vuelve a empaquetar las islas UV dejando margen para "
                          "evitar sangrado entre islas al bakear")
        bl_options = {"REGISTER", "UNDO"}

        margin: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Margen", description="Separación entre islas (0..1 del mapa)",
            default=0.01, min=0.0, max=0.2, precision=4, step=1,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            if not uvmod.has_uv(obj):
                _report(self, "ERROR", T("El objeto necesita UVs"))
                return {"CANCELLED"}
            ok = uvmod.pack_islands(obj, margin=self.margin)
            _report(self, "INFO" if ok else "WARNING",
                    "Islas empaquetadas" if ok else "No se pudieron empaquetar las islas")
            return {"FINISHED"} if ok else {"CANCELLED"}

    # -----------------------------------------------------------------------
    # 2. Asignación de zonas
    # -----------------------------------------------------------------------

    class PCM_OT_assign_zone(Operator):
        """Asigna la zona activa a las caras seleccionadas"""

        bl_idname = "pcm.assign_zone"
        bl_label = "Asignar zona a la selección"
        bl_description = ("Pinta la zona activa sobre las caras seleccionadas y "
                          "actualiza el material. Equivale a elegir un color en "
                          "un editor de textura, pero en vez de pintar píxeles "
                          "se pinta qué receta procedural se aplica")
        bl_options = {"REGISTER", "UNDO"}

        mode: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Modo",
            items=[("SET", "Sustituir", "La zona sustituye a la anterior"),
                   ("ADD", "Añadir", "Igual que sustituir; las caras ya "
                                     "pertenecientes a la zona no cambian"),
                   ("CLEAR", "Borrar", "Devuelve las caras a «sin zona»")],
            default="SET",
        )
        whole_islands: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Extender a la isla UV completa",
            description="Si está activo, la zona se aplica a toda la isla UV de "
                        "las caras seleccionadas (útil para ojos, dientes y "
                        "boca, que suelen ser islas propias)",
            default=False,
        )
        rebuild: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Reconstruir el material",
            description="Regenera el árbol de nodos tras asignar. Desactívalo si "
                        "vas a asignar varias zonas seguidas y pulsa «Generar "
                        "material» al final",
            default=True,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            obj = _target(context)
            if obj is None:
                return False
            props = _op(context, obj)
            return props is not None and getattr(props, "active_zone", "") != ""

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                _report(self, "ERROR", T("Selecciona un objeto de malla"))
                return {"CANCELLED"}
            props = _op(context, obj)
            key = getattr(props, "active_zone", "")
            if not key:
                _report(self, "ERROR", "Elige una zona en el panel")
                return {"CANCELLED"}
            zone = zones_mod.get_zone_by_key(key)
            if zone is None:
                _report(self, "ERROR", f"Zona desconocida: {key}")
                return {"CANCELLED"}

            faces = select_tools.selected_face_indices(obj)
            if not faces:
                _report(self, "WARNING",
                        "No hay caras seleccionadas. Entra en modo edición y "
                        "selecciona las caras de la zona")
                return {"CANCELLED"}

            if self.whole_islands:
                islands = select_tools.select_uv_islands(obj, mode="NONE")
                chosen = set(faces)
                extra: List[int] = []
                for island in islands:
                    if chosen.intersection(island):
                        extra.extend(f for f in island if f not in chosen)
                if extra:
                    faces = faces + sorted(set(extra))
                    _report(self, "INFO",
                            f"Se añadieron {len(set(extra))} caras de las islas UV")

            if self.mode == "CLEAR":
                n = assembler.set_zone_faces(obj.data, faces, 0)
                msg = f"{n} {T('caras')} sin zona"
            else:
                n = assembler.set_zone_faces(obj.data, faces, zone.id)
                msg = f"{n} {T('caras')} → {zone.name(get_language())}"

            assembler.ensure_zone_attribute(obj.data)
            refresh_zone_items(obj)

            if getattr(props, "show_zone_colors", False):
                assembler.zone_color_attribute(obj.data)

            want_rebuild = self.rebuild and getattr(props, "auto_rebuild", True)
            if want_rebuild or self.mode == "CLEAR":
                mat = assembler.build_material(obj, _style_of(obj))
                if mat is None:
                    _report(self, "ERROR", "No se pudo construir el material")
                    return {"CANCELLED"}
                _report(self, "INFO", f"{msg} · {T('Material reconstruido')}")
            else:
                # sólo hace falta refrescar la máscara: la zona ya existe o se
                # añadirá en la próxima reconstrucción.
                if zone.id not in assembler.assigned_zones(obj.data):
                    assembler.build_material(obj, _style_of(obj))
                _report(self, "INFO", msg)
            return {"FINISHED"}

    class PCM_OT_clear_zones(Operator):
        """Borra todas las zonas asignadas del objeto"""

        bl_idname = "pcm.clear_zones"
        bl_label = "Borrar todas las zonas"
        bl_description = "Devuelve todas las caras a «sin zona» y retira el material"
        bl_options = {"REGISTER", "UNDO"}

        remove_material: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Eliminar también el material",
            description="Borra el material PCM y sus grupos de nodos del .blend",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def invoke(self, context: Any, event: Any) -> set:
            return context.window_manager.invoke_confirm(self, event)

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            assembler.ensure_zone_attribute(obj.data)
            total = len(obj.data.polygons)
            assembler.set_zone_faces(obj.data, range(total), 0)
            refresh_zone_items(obj)
            props = _op(context, obj)
            if props is not None:
                props.show_zone_colors = False
                props.prepared = False
            if self.remove_material:
                assembler.cleanup_orphan_groups()
                _remove_pcm_material(obj)
            else:
                assembler.build_material(obj, _style_of(obj))
            _report(self, "INFO", f"{total} {T('caras')} sin zona")
            return {"FINISHED"}

    class PCM_OT_select_zone(Operator):
        """Selecciona las caras de una zona"""

        bl_idname = "pcm.select_zone"
        bl_label = "Seleccionar caras de la zona"
        bl_description = ("Selecciona en modo edición todas las caras que ya "
                          "tienen la zona activa, para revisarlas o ampliarlas")
        bl_options = {"REGISTER", "UNDO"}

        zone_id: bpy.props.IntProperty(name="ID de zona", default=0)  # type: ignore[name-defined]
        mode: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Modo",
            items=[("SET", "Sustituir selección", ""),
                   ("ADD", "Añadir a la selección", ""),
                   ("SUBTRACT", "Quitar de la selección", "")],
            default="SET",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            props = _op(context, obj)
            zid = self.zone_id
            if zid == 0 and props is not None:
                zone = zones_mod.get_zone_by_key(getattr(props, "active_zone", ""))
                zid = zone.id if zone else 0
            n = select_tools.select_zone_faces(obj, zid, mode=self.mode)
            _report(self, "INFO" if n else "WARNING",
                    f"{n} {T('caras')} {T('seleccionadas')}" if n else
                    "Esa zona no tiene caras asignadas")
            return {"FINISHED"}

    class PCM_OT_refresh_zones(Operator):
        """Vuelve a leer las zonas de la malla y actualiza la lista del panel"""

        bl_idname = "pcm.refresh_zones"
        bl_label = "Actualizar lista de zonas"
        bl_description = ("Recalcula cuántas caras tiene cada zona. Úsalo tras "
                          "editar la malla o borrar geometría")
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            refresh_zone_items(obj)
            refresh_zone_params(context, obj)
            props = _op(context, obj)
            n = len(props.zone_items) if props is not None else 0
            _report(self, "INFO", f"{n} {T('zonas')} en la lista")
            return {"FINISHED"}

    class PCM_OT_select_grow(Operator):
        """Amplía o reduce la selección de caras"""

        bl_idname = "pcm.select_grow"
        bl_label = "Ampliar / reducir selección"
        bl_description = ("Crece o encoge la selección de caras por vecindad, "
                          "como Seleccionar > Más/Menos de Blender pero "
                          "disponible en el panel de zonas")
        bl_options = {"REGISTER", "UNDO"}

        shrink: bpy.props.BoolProperty(name="Reducir", default=False)  # type: ignore[name-defined]
        iterations: bpy.props.IntProperty(  # type: ignore[name-defined]
            name="Pasos", default=1, min=1, max=32,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            fn = select_tools.shrink_selection if self.shrink \
                else select_tools.grow_selection
            n = fn(obj, self.iterations)
            _report(self, "INFO", f"{n} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_select_by_normal(Operator):
        """Selecciona caras por su orientación"""

        bl_idname = "pcm.select_by_normal"
        bl_label = "Seleccionar por orientación"
        bl_description = ("Selecciona las caras cuya normal esté dentro de un "
                          "ángulo respecto a una dirección. Ideal para separar "
                          "la cara frontal del cráneo o el lomo del vientre")
        bl_options = {"REGISTER", "UNDO"}

        direction: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Dirección",
            items=[("+Z", "Arriba", ""), ("-Z", "Abajo", ""),
                   ("+X", "Derecha", ""), ("-X", "Izquierda", ""),
                   ("+Y", "Frente", ""), ("-Y", "Detrás", "")],
            default="+Z",
        )
        angle: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Ángulo", default=45.0, min=1.0, max=180.0, subtype="ANGLE",
        )
        mode: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Modo",
            items=[("SET", "Sustituir", ""), ("ADD", "Añadir", ""),
                   ("SUBTRACT", "Quitar", "")],
            default="SET",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            dirs = {"+Z": (0, 0, 1), "-Z": (0, 0, -1), "+X": (1, 0, 0),
                    "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}
            n = select_tools.select_by_normal(obj, dirs[self.direction],
                                              self.angle, mode=self.mode)
            _report(self, "INFO", f"{n} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_select_by_curvature(Operator):
        """Selecciona pliegues o zonas abultadas por su curvatura"""

        bl_idname = "pcm.select_by_curvature"
        bl_label = "Seleccionar por curvatura"
        bl_description = ("Selecciona las caras cóncavas (pliegues: cuello, "
                          "axilas, ingle, alrededor de los ojos) o convexas "
                          "(pómulos, nariz, nudillos). Es la forma más rápida de "
                          "marcar dónde van las arrugas y el enrojecimiento")
        bl_options = {"REGISTER", "UNDO"}

        convex: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Convexo (abultado)",
            description="Desactivado selecciona cóncavo (pliegues)",
            default=False,
        )
        threshold: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Umbral", default=0.35, min=0.0, max=1.0,
            description="Cuánta curvatura hace falta para incluir una cara",
        )
        mode: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Modo",
            items=[("SET", "Sustituir", ""), ("ADD", "Añadir", ""),
                   ("SUBTRACT", "Quitar", "")],
            default="ADD",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            n = select_tools.select_by_curvature(
                obj, concave=not self.convex, threshold=self.threshold,
                mode=self.mode)
            _report(self, "INFO", f"{n} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_select_by_position(Operator):
        """Selecciona caras dentro de una esfera o caja"""

        bl_idname = "pcm.select_by_position"
        bl_label = "Seleccionar por posición"
        bl_description = ("Selecciona las caras que caen dentro de una esfera o "
                          "una caja centradas en el cursor 3D. Perfecto para "
                          "aislar ojos, nariz o pezuñas en un modelo importado")
        bl_options = {"REGISTER", "UNDO"}

        shape: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Forma",
            items=[("sphere", "Esfera", ""), ("box", "Caja", "")],
            default="sphere",
        )
        radius: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Radio", default=0.05, min=0.001, soft_max=2.0,
            unit="LENGTH", precision=4,
            description="Radio de la esfera o semiancho de la caja",
        )
        use_cursor: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Centrar en el cursor 3D", default=True,
        )
        mode: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Modo",
            items=[("SET", "Sustituir", ""), ("ADD", "Añadir", ""),
                   ("SUBTRACT", "Quitar", "")],
            default="SET",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            if self.use_cursor:
                loc = tuple(context.scene.cursor.location)
                # a espacio local del objeto
                try:
                    loc = tuple(obj.matrix_world.inverted() @
                                context.scene.cursor.location)
                except Exception:
                    pass
            else:
                loc = (0.0, 0.0, 0.0)
            box = (self.radius * 2.0,) * 3 if self.shape == "box" else None
            n = select_tools.select_by_position(obj, center=loc,
                                                radius=self.radius, box=box,
                                                mode=self.mode)
            _report(self, "INFO", f"{n} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_select_uv_islands(Operator):
        """Selecciona islas UV completas a partir de la selección"""

        bl_idname = "pcm.select_uv_islands"
        bl_label = "Seleccionar islas UV"
        bl_description = ("Amplía la selección hasta las islas UV completas que "
                          "toquen las caras seleccionadas")
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            islands = select_tools.select_uv_islands(obj, mode="NONE")
            chosen = set(select_tools.selected_face_indices(obj))
            faces: List[int] = []
            touched = 0
            for island in islands:
                if chosen.intersection(island):
                    faces.extend(f for f in island if f not in chosen)
                    touched += 1
            if not faces:
                _report(self, "WARNING",
                        "Ninguna isla UV nueva: selecciona antes algunas caras")
                return {"CANCELLED"}
            select_tools.set_face_selection(obj, faces, mode="ADD")
            _report(self, "INFO",
                    f"{touched} islas · {len(chosen) + len(faces)} "
                    f"{T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    class PCM_OT_smooth_groups(Operator):
        """Divide la malla en grupos de suavizado y muestra la lista"""

        bl_idname = "pcm.smooth_groups"
        bl_label = "Detectar grupos de suavizado"
        bl_description = ("Analiza la malla y la divide en grupos por ángulo de "
                          "suavizado. En cabezas importadas separa "
                          "automáticamente ojos, dientes y lengua, que es lo más "
                          "tedioso de marcar a mano")
        bl_options = {"REGISTER", "UNDO"}

        angle: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Ángulo límite", default=30.0, min=1.0, max=89.0,
            description="Dos caras vecinas pertenecen a grupos distintos si su "
                        "ángulo supera este valor",
        )
        min_faces: bpy.props.IntProperty(  # type: ignore[name-defined]
            name="Tamaño mínimo", default=4, min=1, max=100000,
            description="Descarta grupos más pequeños (ruido de la malla)",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            groups = select_tools.smooth_groups(obj, self.angle)
            kept = [g for g in groups if len(g) >= self.min_faces]
            kept.sort(key=len, reverse=True)
            lines = [f"Grupo {i + 1}: {len(g)} caras" for i, g in enumerate(kept[:24])]
            if len(kept) > 24:
                lines.append(f"… y {len(kept) - 24} grupos más")
            text = "\n".join(lines) or "Sin grupos"
            log.info("Grupos de suavizado de %s (ángulo %.0f°):\n%s",
                     obj.name, self.angle, text)
            _write_text_block(context, f"PCM grupos — {obj.name}",
                              f"Grupos de suavizado de {obj.name}\n"
                              f"Ángulo límite: {self.angle:.0f}°\n"
                              f"Total: {len(kept)} grupos, "
                              f"{sum(len(g) for g in kept)} caras\n\n" + text)
            _report(self, "INFO",
                    f"{len(kept)} grupos detectados — mira el editor de texto")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 3. Sugerencias automáticas de zona
    # -----------------------------------------------------------------------

    class PCM_OT_propose_zones(Operator):
        """Sugiere zonas a partir de la geometría y pide confirmación"""

        bl_idname = "pcm.propose_zones"
        bl_label = "Sugerir zonas automáticamente"
        bl_description = ("Analiza la malla (grupos de suavizado, tamaño, "
                          "posición y curvatura) y propone qué zona aplicar a "
                          "cada grupo. Nada se aplica hasta que lo confirmes en "
                          "la lista")
        bl_options = {"REGISTER", "UNDO"}

        angle: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Ángulo límite", default=30.0, min=1.0, max=89.0,
        )
        overwrite: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Sobrescribir zonas existentes",
            description="Si está desactivado, sólo se proponen caras que aún no "
                        "tengan zona asignada",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            proposals = select_tools.propose_zones(obj, angle_deg=self.angle)
            props = _op(context, obj)
            if props is None:
                return {"CANCELLED"}
            items = props.proposals
            try:
                items.clear()
            except Exception:
                pass
            lang = get_language()
            already = set()
            if not self.overwrite:
                zmap = assembler.assigned_zones(obj.data)
                already = set(zmap.keys())
            for p in proposals:
                faces = p.get("faces") or []
                if not faces:
                    continue
                zid = int(p.get("zone_id", 0))
                zone = zones_mod.get_zone(zid)
                entry = items.add()
                entry.zone_key = zone.key if zone else "custom"
                entry.zone_name = zone.name(lang) if zone else T("Zona personalizada")
                entry.face_count = len(faces)
                entry.confidence = float(p.get("confidence", 0.0))
                entry.reason = str(p.get("reason", ""))
                entry.apply = bool(entry.confidence >= 0.5)
                # los índices de cara viajan como IDProperty del elemento
                try:
                    entry["faces"] = list(faces)
                    entry["zone_id"] = zid
                    entry["skip"] = bool(already and zid in already)
                except Exception:
                    pass
            if len(items) == 0:
                _report(self, "WARNING",
                        "No se detectaron grupos sugestivos. Usa las herramientas "
                        "de selección y asigna las zonas a mano")
                return {"CANCELLED"}
            _report(self, "INFO",
                    f"{len(items)} propuestas — revísalas en el panel "
                    "«Zonas sugeridas» y pulsa «Aplicar»")
            return {"FINISHED"}

    class PCM_OT_apply_proposals(Operator):
        """Aplica las sugerencias de zona marcadas"""

        bl_idname = "pcm.apply_proposals"
        bl_label = "Aplicar zonas sugeridas"
        bl_description = ("Asigna las zonas marcadas en la lista de propuestas y "
                          "reconstruye el material")
        bl_options = {"REGISTER", "UNDO"}

        only_confident: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Sólo confianza ≥ 50 %",
            description="Ignora las propuestas poco seguras",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            obj = _target(context)
            props = _op(context, obj) if obj is not None else None
            return props is not None and len(getattr(props, "proposals", ())) > 0

        def execute(self, context: Any) -> set:
            obj = _target(context)
            props = _op(context, obj)
            if obj is None or props is None:
                return {"CANCELLED"}
            assembler.ensure_zone_attribute(obj.data)
            applied = 0
            faces_total = 0
            for entry in props.proposals:
                if not getattr(entry, "apply", False):
                    continue
                if self.only_confident and entry.confidence < 0.5:
                    continue
                if entry.get("skip", False):
                    continue
                zid = int(entry.get("zone_id", 0))
                if zid <= 0:
                    zone = zones_mod.get_zone_by_key(entry.zone_key)
                    zid = zone.id if zone else 0
                if zid <= 0:
                    continue
                faces = list(entry.get("faces", []))
                if not faces:
                    continue
                n = assembler.set_zone_faces(obj.data, faces, zid)
                applied += 1
                faces_total += n
            if applied == 0:
                _report(self, "WARNING", "Ninguna propuesta marcada para aplicar")
                return {"CANCELLED"}
            refresh_zone_items(obj)
            if getattr(props, "show_zone_colors", False):
                assembler.zone_color_attribute(obj.data)
            mat = assembler.build_material(obj, _style_of(obj))
            if mat is None:
                _report(self, "ERROR", "Zonas asignadas, pero el material falló")
                return {"CANCELLED"}
            _report(self, "INFO",
                    f"{applied} zonas · {faces_total} {T('caras')} · "
                    f"{T('Material reconstruido')}")
            return {"FINISHED"}

    class PCM_OT_clear_proposals(Operator):
        """Vacía la lista de zonas sugeridas"""

        bl_idname = "pcm.clear_proposals"
        bl_label = "Limpiar sugerencias"
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            props = _op(context)
            return props is not None and len(getattr(props, "proposals", ())) > 0

        def execute(self, context: Any) -> set:
            props = _op(context)
            try:
                props.proposals.clear()
            except Exception:
                return {"CANCELLED"}
            return {"FINISHED"}

    class PCM_OT_proposal_select(Operator):
        """Selecciona las caras de una propuesta para revisarlas"""

        bl_idname = "pcm.proposal_select"
        bl_label = "Ver caras de esta propuesta"
        bl_options = {"REGISTER", "UNDO"}

        index: bpy.props.IntProperty(name="Índice", default=0)  # type: ignore[name-defined]

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            props = _op(context, obj)
            if obj is None or props is None:
                return {"CANCELLED"}
            if self.index < 0 or self.index >= len(props.proposals):
                return {"CANCELLED"}
            faces = list(props.proposals[self.index].get("faces", []))
            if not faces:
                return {"CANCELLED"}
            select_tools.set_face_selection(obj, faces, mode="SET")
            _enter_edit_mode(context)
            _report(self, "INFO", f"{len(faces)} {T('caras')} {T('seleccionadas')}")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 4. Material
    # -----------------------------------------------------------------------

    class PCM_OT_build_material(Operator):
        """Genera o reconstruye el material procedural del objeto"""

        bl_idname = "pcm.build_material"
        bl_label = "Generar material"
        bl_description = ("Construye el árbol de nodos completo: una receta por "
                          "cada zona asignada, mezcladas por la máscara de zonas "
                          "y conectadas a un único Principled BSDF. El resultado "
                          "es un solo material, listo para bakear")
        bl_options = {"REGISTER", "UNDO"}

        force: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Forzar reconstrucción",
            description="Borra los grupos existentes y los crea desde cero "
                        "(necesario tras actualizar el addon)",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            style = _style_of(obj)
            t0 = time.time()
            if self.force:
                assembler.cleanup_orphan_groups()
                mat = assembler.build_material(obj, style, force=True,
                                               uv_scale=_uv_scale(obj))
            else:
                mat = assembler.build_material(obj, style, uv_scale=_uv_scale(obj))
            dt = time.time() - t0
            if mat is None:
                _report(self, "ERROR",
                        "No se pudo construir el material. Abre Diagnóstico para "
                        "ver qué nodo o socket falta")
                return {"CANCELLED"}
            props = _op(context, obj)
            if props is not None:
                props.prepared = True
            refresh_zone_items(obj)
            refresh_zone_params(context, obj)
            zmap = assembler.assigned_zones(obj.data)
            nodes = diagnostics.count_nodes(getattr(mat, "node_tree", None))
            _report(self, "INFO",
                    f"{style.name(get_language())} · {len(zmap)} zonas · "
                    f"{nodes} nodos · {dt:.1f} s")
            if not zmap:
                _report(self, "WARNING",
                        "Todavía no hay zonas asignadas: el material usa la piel "
                        "corporal en todo el modelo")
            return {"FINISHED"}

    class PCM_OT_apply_zone_params(Operator):
        """Aplica los ajustes del panel al material"""

        bl_idname = "pcm.apply_zone_params"
        bl_label = "Aplicar parámetros"
        bl_description = ("Vuelca los valores del editor de parámetros al "
                          "material. Se guardan dentro del .blend, así que "
                          "sobreviven a recargas y a la exportación")
        bl_options = {"REGISTER", "UNDO"}

        rebuild: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Reconstrucción completa",
            description="Regenera el árbol entero. Sólo hace falta si cambiaste "
                        "algo que afecta a la estructura",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            if self.rebuild:
                props = _op(context, obj)
                editor = getattr(props, "zone_params", None)
                zone = zones_mod.get_zone_by_key(
                    getattr(props, "active_zone", "")) if props else None
                if editor is not None and zone is not None:
                    for prm in zone.params:
                        ident = properties.param_ident(zone.key, prm.name)
                        if hasattr(editor, ident):
                            assembler.set_zone_param(obj, zone.key, prm.name,
                                                     getattr(editor, ident),
                                                     rebuild=False)
                mat = assembler.rebuild_material(obj, _style_of(obj),
                                                 uv_scale=_uv_scale(obj))
                ok = mat is not None
                n = -1
            else:
                n = apply_zone_params(context, obj)
                ok = n > 0
            refresh_zone_params(context, obj)
            if ok:
                _report(self, "INFO",
                        (T("Material reconstruido") if self.rebuild else
                         f"{n} {T('parámetros')} aplicados"))
                return {"FINISHED"}
            _report(self, "WARNING",
                    "No se aplicó ningún parámetro: genera el material primero o "
                    "comprueba que la zona activa tenga controles")
            return {"CANCELLED"}

    class PCM_OT_reload_zone_params(Operator):
        """Recarga los parámetros guardados en el material"""

        bl_idname = "pcm.reload_zone_params"
        bl_label = "Recargar parámetros"
        bl_description = ("Descarta los cambios del editor y vuelve a leer los "
                          "valores guardados en el material")
        bl_options = {"REGISTER", "UNDO"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            refresh_zone_params(context, obj)
            _report(self, "INFO", "Parámetros recargados")
            return {"FINISHED"}

    class PCM_OT_set_uv_scale(Operator):
        """Aplica la escala de UV global del material"""

        bl_idname = "pcm.set_uv_scale"
        bl_label = "Aplicar escala de detalle"
        bl_description = ("Reconstruye el material con la escala de UV indicada. "
                          "Es el ajuste que más cambia el aspecto: si el detalle "
                          "se ve demasiado fino, súbela")
        bl_options = {"REGISTER", "UNDO"}

        scale: bpy.props.FloatProperty(  # type: ignore[name-defined]
            name="Escala", default=1.0, min=0.05, max=20.0,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            props = _op(context, obj)
            if props is not None:
                props.uv_scale = self.scale
            mat = assembler.rebuild_material(obj, _style_of(obj),
                                             uv_scale=self.scale)
            if mat is None:
                _report(self, "ERROR", "No se pudo aplicar la escala")
                return {"CANCELLED"}
            _report(self, "INFO", f"Escala de detalle ×{self.scale:.2f}")
            return {"FINISHED"}

    class PCM_OT_show_zone_colors(Operator):
        """Activa o desactiva la visualización de zonas en el viewport"""

        bl_idname = "pcm.show_zone_colors"
        bl_label = "Ver zonas en el viewport"
        bl_description = ("Rellena un atributo de color con el color de cada "
                          "zona. Actívalo en Material Preview y elige el "
                          "atributo «pcm_zone_color» en el nodo Color Attribute "
                          "del material de vista, o usa Vertex Paint")
        bl_options = {"REGISTER", "UNDO"}

        enable: bpy.props.BoolProperty(name="Activar", default=True)  # type: ignore[name-defined]

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            props = _op(context, obj)
            if props is not None:
                props.show_zone_colors = self.enable
            if self.enable:
                assembler.zone_color_attribute(obj.data)
                _report(self, "INFO",
                        "Atributo «pcm_zone_color» actualizado — elígelo en el "
                        "viewport para ver las zonas")
            else:
                _report(self, "INFO", "Visualización de zonas desactivada")
            return {"FINISHED"}

    class PCM_OT_select_zone_from_list(Operator):
        """Convierte la zona de una fila de la lista en la zona activa"""

        bl_idname = "pcm.select_zone_from_list"
        bl_label = "Editar esta zona"
        bl_options = {"REGISTER", "UNDO"}

        index: bpy.props.IntProperty(name="Índice", default=-1)  # type: ignore[name-defined]

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            props = _op(context, obj)
            if obj is None or props is None:
                return {"CANCELLED"}
            idx = self.index if self.index >= 0 else len(props.zone_items) - 1
            if idx < 0 or idx >= len(props.zone_items):
                return {"CANCELLED"}
            key = props.zone_items[idx].zone_key
            if not key:
                _report(self, "INFO", "Esa fila es «sin asignar»")
                return {"CANCELLED"}
            props.active_zone = key
            refresh_zone_params(context, obj)
            _report(self, "INFO", f"Zona activa: {props.zone_items[idx].zone_name}")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 5. Bake
    # -----------------------------------------------------------------------

    class PCM_OT_bake(Operator):
        """Bakea los mapas seleccionados (modal, con barra de progreso)"""

        bl_idname = "pcm.bake"
        bl_label = "Bakear mapas"
        bl_description = ("Convierte el material procedural en texturas. Se "
                          "ejecuta un mapa por paso para que puedas seguir el "
                          "progreso y cancelar en cualquier momento. Usa Cycles, "
                          "crea un material temporal que no toca el tuyo y "
                          "restaura todos los ajustes al terminar")
        bl_options = {"REGISTER"}

        export_after: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Exportar al terminar",
            description="Escribe los ficheros en el directorio de salida en "
                        "cuanto acabe el bake",
            default=True,
        )
        only_selected_maps: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Sólo los mapas marcados",
            description="Desactívalo para bakear los diez mapas del pipeline",
            default=True,
        )

        _timer: Any = None
        _bc: Any = None
        _step: int = 0
        _cancelled: bool = False
        _t0: float = 0.0

        @classmethod
        def poll(cls, context: Any) -> bool:
            obj = _target(context)
            sp = _sp(context)
            if obj is None or sp is None:
                return False
            if getattr(sp, "is_baking", False):
                return False
            return True

        def invoke(self, context: Any, event: Any) -> set:
            obj = _target(context)
            sp = _sp(context)
            if obj is None or sp is None:
                _report(self, "ERROR", T("Selecciona un objeto de malla"))
                return {"CANCELLED"}

            checks = diagnostics.validate_scene(context)
            fatal: List[str] = []
            for section in checks.get("sections", []):
                fatal.extend(section.get("errors", []))
            if fatal:
                _write_text_block(context, "PCM — Diagnóstico de bake",
                                  diagnostics.build_report_text(context),
                                  open_editor=True)
                _report(self, "ERROR",
                        f"No se puede bakear: {fatal[0]} — informe completo en el "
                        "editor de texto")
                return {"CANCELLED"}

            keys = properties.map_flags(sp)
            if self.only_selected_maps:
                keys = [k for k in keys if k in bake.MAPS]
            else:
                keys = [k for k in bake.MAPS if k != "orm"]
            if not keys:
                _report(self, "ERROR",
                        "No hay ningún mapa marcado. Activa al menos uno en "
                        "«Mapas a bakear»")
                return {"CANCELLED"}

            if not uvmod.has_uv(obj):
                _report(self, "ERROR", T("El objeto necesita UVs") +
                        " — pulsa «Preparar objeto» primero")
                return {"CANCELLED"}

            # motor de destino -> convención de normales coherente por defecto
            engine = getattr(sp, "engine", "unity")
            try:
                if getattr(sp, "normal_convention", "") == "":
                    sp.normal_convention = bake.normal_convention_for_engine(engine)
            except Exception:
                pass

            props = _op(context, obj)
            style = _style_of(obj)
            self._bc = bake.prepare_bake(context, obj, style, sp, keys)
            if self._bc is None:
                _report(self, "ERROR",
                        "No se pudo preparar el bake — mira la consola o el "
                        "informe de diagnóstico")
                return {"CANCELLED"}

            try:
                sp.is_baking = True
                sp.bake_progress = 0.0
                sp.bake_status = T("Preparando")
            except Exception:
                pass

            self._t0 = time.time()
            self._cancelled = False
            self._step = 0
            context.window_manager.progress_begin(0, len(self._bc.maps))
            self._timer = context.window_manager.event_timer_add(
                0.05, window=context.window)
            context.window_manager.modal_handler_add(self)
            _report(self, "INFO",
                    f"Bakeando {len(self._bc.maps)} mapas a "
                    f"{getattr(sp, 'resolution', '4096')} px — Esc cancela")
            return {"RUNNING_MODAL"}

        def modal(self, context: Any, event: Any) -> set:
            sp = _sp(context)
            if event.type == "TIMER":
                bc = self._bc
                if bc is None:
                    return self._finish(context, cancelled=True)
                if self._step >= len(bc.maps):
                    return self._finish(context)
                key = bc.maps[self._step]
                cfg = bake.MAPS[key]
                try:
                    if sp is not None:
                        sp.bake_status = f"{T('Bakeando')}: {cfg['label']} " \
                                         f"({self._step + 1}/{len(bc.maps)})"
                except Exception:
                    pass
                t0 = time.time()
                ok = bake.bake_one(context, bc, key)
                dt = time.time() - t0
                log.info("Bake %s: %s (%.1f s)", key, "ok" if ok else "FALLÓ", dt)
                self._step += 1
                try:
                    context.window_manager.progress_update(self._step)
                    if sp is not None:
                        sp.bake_progress = self._step / max(1, len(bc.maps))
                except Exception:
                    pass
                return {"RUNNING_MODAL"}

            if event.type in {"ESC"}:
                self._cancelled = True
                _report(self, "WARNING", "Bake cancelado por el usuario")
                return self._finish(context, cancelled=True)

            return {"PASS_THROUGH"}

        def _finish(self, context: Any, cancelled: bool = False) -> set:
            sp = _sp(context)
            bc = self._bc
            try:
                if self._timer is not None:
                    context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
            try:
                context.window_manager.progress_end()
            except Exception:
                pass
            try:
                bake.finish_bake(context, bc)
            except Exception as exc:
                log.error("La limpieza del bake falló: %s", exc)
            try:
                if sp is not None:
                    sp.is_baking = False
                    sp.bake_progress = 0.0
                    sp.bake_status = ""
            except Exception:
                pass
            self._bc = None

            if bc is None:
                return {"CANCELLED"}
            dt = time.time() - self._t0
            for w in bc.warnings:
                _report(self, "WARNING", w)
            for e in bc.errors:
                _report(self, "ERROR", e)
            if cancelled and not bc.done:
                _report(self, "WARNING", f"Bake cancelado tras {dt:.0f} s")
                return {"CANCELLED"}

            summary = f"{len(bc.done)} mapas en {dt:.0f} s"
            names = ", ".join(bake.MAPS[k]["label"] for k in bc.done)
            log.info("Bake terminado: %s (%s)", summary, names)
            _report(self, "INFO", f"{T('Listo')}: {summary}")

            # informe de bake en el editor de texto
            _write_text_block(
                context, f"PCM — Bake {bc.obj.name if bc.obj else ''}",
                _bake_report(bc, dt))

            if self.export_after and bc.done and not cancelled:
                res = export.export_maps(context, bc.obj, sp, map_keys=bc.done)
                if res["files"]:
                    out = res["dir"]
                    export.export_manifest(context, bc.obj, sp, out, _style_of(bc.obj))
                    export.write_instructions(out, getattr(sp, "engine", "unity"),
                                              bc.obj.name)
                    _report(self, "INFO",
                            f"{len(res['files'])} ficheros en {out}")
                    _write_text_block(
                        context, f"PCM — Export {bc.obj.name}",
                        _export_report(res, sp, bc.obj))
                for e in res["errors"]:
                    _report(self, "ERROR", e)
                for w in res["warnings"]:
                    _report(self, "WARNING", w)
            return {"FINISHED"}

    class PCM_OT_cancel_bake(Operator):
        """Cancela el bake en curso"""

        bl_idname = "pcm.cancel_bake"
        bl_label = "Cancelar bake"
        bl_description = ("Pide la cancelación. El mapa que se esté bakeando en "
                          "ese momento termina (Cycles no interrumpe un bake a "
                          "mitad) y se descartan los siguientes")
        bl_options = {"REGISTER"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            sp = _sp(context)
            return sp is not None and bool(getattr(sp, "is_baking", False))

        def execute(self, context: Any) -> set:
            sp = _sp(context)
            try:
                sp.is_baking = False
                sp.bake_status = ""
            except Exception:
                pass
            try:
                bpy.ops.render.render(cancel=True)
            except Exception:
                pass
            _report(self, "WARNING", "Cancelación solicitada")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 6. Exportación
    # -----------------------------------------------------------------------

    class PCM_OT_export_maps(Operator):
        """Guarda los mapas bakeados en disco"""

        bl_idname = "pcm.export_maps"
        bl_label = "Exportar mapas"
        bl_description = ("Escribe las texturas en el directorio de salida con la "
                          "nomenclatura del motor elegido, más un manifiesto JSON "
                          "con los ajustes del material y una guía de importación")
        bl_options = {"REGISTER"}

        open_folder: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Abrir la carpeta al terminar",
            description="Abre el explorador de ficheros en el directorio de salida",
            default=True,
        )
        save_blend_copy: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Guardar copia .blend del material",
            description="Exporta además un .blend con sólo el material, para "
                        "reutilizarlo en otros personajes",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None and _sp(context) is not None

        def execute(self, context: Any) -> set:
            obj = _target(context)
            sp = _sp(context)
            if obj is None or sp is None:
                return {"CANCELLED"}
            keys = properties.map_flags(sp)
            if getattr(sp, "export_orm", True) and getattr(sp, "pack_channels", True):
                keys = keys + ["orm"]
            res = export.export_maps(context, obj, sp, map_keys=keys)
            for w in res["warnings"]:
                _report(self, "WARNING", w)
            for e in res["errors"]:
                _report(self, "ERROR", e)
            if not res["files"]:
                _report(self, "ERROR",
                        "No se exportó nada. Haz el bake primero (los mapas se "
                        "guardan en el .blend hasta que los exportas)")
                return {"CANCELLED"}
            style = _style_of(obj)
            manifest = export.export_manifest(context, obj, sp, res["dir"], style)
            guide = export.write_instructions(res["dir"], getattr(sp, "engine", "unity"),
                                              obj.name)
            _write_text_block(context, f"PCM — Export {obj.name}",
                              _export_report(res, sp, obj, manifest, guide))
            if self.save_blend_copy or getattr(sp, "save_blend_copy", False):
                copy = _save_material_blend(context, obj, res["dir"])
                if copy:
                    _report(self, "INFO", f"Copia del material: {copy}")
            _report(self, "INFO",
                    f"{len(res['files'])} mapas en {res['dir']}")
            if self.open_folder:
                _open_path(res["dir"])
            return {"FINISHED"}

    class PCM_OT_show_import_guide(Operator):
        """Abre la guía de importación del motor elegido"""

        bl_idname = "pcm.show_import_guide"
        bl_label = "Guía de importación"
        bl_description = ("Abre en el editor de texto las instrucciones exactas "
                          "de importación para el motor de destino: compresión, "
                          "sRGB, orden de canales y conexiones del shader")
        bl_options = {"REGISTER"}

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _sp(context) is not None

        def execute(self, context: Any) -> set:
            sp = _sp(context)
            engine = getattr(sp, "engine", "unity")
            text = export.import_instructions(engine)
            name = {"unity": "Unity", "unreal": "Unreal Engine",
                    "godot": "Godot", "generic": "glTF"}.get(engine, engine)
            path = _write_text_block(context, f"PCM — Importación {name}", text,
                                     open_editor=True)
            _report(self, "INFO", f"Guía de {name} abierta en el editor de texto")
            return {"FINISHED"}

    class PCM_OT_set_engine(Operator):
        """Cambia el motor de destino y ajusta la convención de normales"""

        bl_idname = "pcm.set_engine"
        bl_label = "Cambiar motor de destino"
        bl_options = {"REGISTER", "UNDO"}

        engine: bpy.props.EnumProperty(  # type: ignore[name-defined]
            name="Motor",
            items=[("unity", "Unity", ""), ("unreal", "Unreal Engine", ""),
                   ("godot", "Godot", ""), ("generic", "Genérico / glTF", "")],
            default="unity",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _sp(context) is not None

        def execute(self, context: Any) -> set:
            sp = _sp(context)
            sp.engine = self.engine
            sp.normal_convention = bake.normal_convention_for_engine(self.engine)
            if self.engine == "unreal":
                sp.pack_channels = True
                sp.export_orm = True
            _report(self, "INFO",
                    f"Motor: {self.engine.capitalize()} · normales "
                    f"{sp.normal_convention.upper()}")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 7. Presets de material
    # -----------------------------------------------------------------------

    class PCM_OT_save_preset(Operator):
        """Guarda el material actual como preset reutilizable"""

        bl_idname = "pcm.save_preset"
        bl_label = "Guardar preset de material"
        bl_description = ("Guarda estilo, escala de UV, zonas asignadas y todos "
                          "los parámetros ajustados en un JSON reutilizable. Se "
                          "guarda junto a tus preferencias, no dentro del .blend")
        bl_options = {"REGISTER"}

        name: bpy.props.StringProperty(  # type: ignore[name-defined]
            name="Nombre", default="",
            description="Identificador del preset (vacío = nombre del objeto)",
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def invoke(self, context: Any, event: Any) -> set:
            obj = _target(context)
            if obj is not None and not self.name:
                self.name = obj.name
            return context.window_manager.invoke_props_dialog(self)

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            props = _op(context, obj)
            style = _style_of(obj)
            sp = _sp(context)
            data = {
                "preset": self.name or obj.name,
                "addon": "PCM Studio",
                "style": style.id,
                "uv_scale": getattr(props, "uv_scale", 1.0) if props else 1.0,
                "parameters": assembler.load_user_params(
                    assembler._existing_pcm_material(obj)),
                "zones": [
                    {"id": z["id"], "key": z["key"], "faces": z["faces"]}
                    for z in assembler.material_report(obj)["zones"]
                ],
                "bake": {
                    "engine": getattr(sp, "engine", "unity") if sp else "unity",
                    "resolution": getattr(sp, "resolution", "4096") if sp else "4096",
                    "normal_mode": getattr(sp, "normal_mode", "displaced")
                    if sp else "displaced",
                    "normal_convention": getattr(sp, "normal_convention", "opengl")
                    if sp else "opengl",
                },
            }
            folder = _preset_dir(context)
            if folder is None:
                _report(self, "ERROR", "No se pudo localizar la carpeta de presets")
                return {"CANCELLED"}
            safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                           for c in data["preset"]).strip() or "preset"
            path = os.path.join(folder, f"{safe}.json")
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
            except Exception as exc:
                _report(self, "ERROR", f"No se pudo guardar el preset: {exc}")
                return {"CANCELLED"}
            _report(self, "INFO", f"Preset guardado en {path}")
            return {"FINISHED"}

    class PCM_OT_load_preset(Operator):
        """Carga un preset de material guardado"""

        bl_idname = "pcm.load_preset"
        bl_label = "Cargar preset de material"
        bl_description = ("Aplica a otro objeto el estilo, la escala de detalle y "
                          "los parámetros de un preset guardado. Las zonas no se "
                          "copian: dependen de la topología de cada modelo")
        bl_options = {"REGISTER", "UNDO"}

        filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore[name-defined]
        filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})  # type: ignore[name-defined]
        apply_zones: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Intentar aplicar también las zonas",
            description="Sólo tiene sentido si el objeto destino tiene la misma "
                        "topología que el original",
            default=False,
        )

        @classmethod
        def poll(cls, context: Any) -> bool:
            return _target(context) is not None

        def invoke(self, context: Any, event: Any) -> set:
            folder = _preset_dir(context)
            if folder:
                self.filepath = folder
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        def execute(self, context: Any) -> set:
            obj = _target(context)
            if obj is None:
                return {"CANCELLED"}
            path = bpy.path.abspath(self.filepath) if self.filepath else ""
            if not path or not os.path.isfile(path):
                _report(self, "ERROR", "Elige un fichero .json de preset")
                return {"CANCELLED"}
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                _report(self, "ERROR", f"Preset no válido: {exc}")
                return {"CANCELLED"}

            props = _op(context, obj)
            sp = _sp(context)
            style = styles.get_style(data.get("style", styles.default_style_id()))
            if props is not None:
                props.style = style.id
                try:
                    props.uv_scale = float(data.get("uv_scale", 1.0))
                except Exception:
                    pass
            if sp is not None:
                for key in ("engine", "resolution", "normal_mode", "normal_convention"):
                    value = (data.get("bake") or {}).get(key)
                    if value:
                        try:
                            setattr(sp, key, value)
                        except Exception:
                            pass

            if self.apply_zones:
                _report(self, "WARNING",
                        "Las zonas dependen de la topología y no se copian: usa "
                        "«Sugerir zonas automáticamente» sobre el objeto nuevo")

            params = data.get("parameters") or {}
            mat = assembler.build_material(obj, style, uv_scale=float(
                data.get("uv_scale", 1.0)), force=True)
            if mat is None:
                _report(self, "ERROR", "No se pudo construir el material del preset")
                return {"CANCELLED"}
            applied = 0
            for zone_key, values in params.items():
                if not isinstance(values, dict):
                    continue
                for name, value in values.items():
                    if assembler.set_zone_param(obj, zone_key, name, value):
                        applied += 1
            refresh_zone_items(obj)
            refresh_zone_params(context, obj)
            _report(self, "INFO",
                    f"Preset «{data.get('preset', os.path.basename(path))}» · "
                    f"{style.name(get_language())} · {applied} parámetros")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # 8. Mantenimiento
    # -----------------------------------------------------------------------

    class PCM_OT_cleanup(Operator):
        """Limpia datos huérfanos del addon"""

        bl_idname = "pcm.cleanup"
        bl_label = "Limpiar datos huérfanos"
        bl_description = ("Borra los grupos de nodos, materiales e imágenes de "
                          "bake que ya no usa ningún objeto. Reduce el tamaño "
                          "del .blend tras varias iteraciones")
        bl_options = {"REGISTER", "UNDO"}

        images: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Borrar también las imágenes de bake",
            description="Ojo: perderás los mapas bakeados que aún no hayas "
                        "exportado a disco",
            default=False,
        )

        def invoke(self, context: Any, event: Any) -> set:
            return context.window_manager.invoke_confirm(self, event)

        def execute(self, context: Any) -> set:
            removed = assembler.cleanup_orphan_groups()
            mats = _remove_unused_pcm_materials()
            imgs = 0
            if self.images:
                imgs = _remove_pcm_images()
            _report(self, "INFO",
                    f"Limpieza: {removed} grupos, {mats} materiales, "
                    f"{imgs} imágenes")
            return {"FINISHED"}

    class PCM_OT_report(Operator):
        """Genera el informe de diagnóstico completo"""

        bl_idname = "pcm.report"
        bl_label = "Informe y diagnóstico"
        bl_description = ("Analiza Blender, los nodos disponibles, las UVs, las "
                          "zonas y el árbol de material, y escribe un informe "
                          "completo en el editor de texto. Es lo primero que hay "
                          "que mirar cuando algo no sale como esperabas")
        bl_options = {"REGISTER"}

        copy_to_clipboard: bpy.props.BoolProperty(  # type: ignore[name-defined]
            name="Copiar al portapapeles", default=False,
        )

        def execute(self, context: Any) -> set:
            text = diagnostics.build_report_text(context)
            _write_text_block(context, "PCM — Informe de diagnóstico", text,
                              open_editor=True)
            if self.copy_to_clipboard:
                try:
                    context.window_manager.clipboard = text
                except Exception:
                    pass
            checks = diagnostics.validate_scene(context)
            level = "ERROR" if checks.get("errors") else \
                ("WARNING" if checks.get("warnings") else "INFO")
            _report(self, level,
                    f"{checks.get('errors', 0)} errores · "
                    f"{checks.get('warnings', 0)} avisos — informe abierto")
            return {"FINISHED"}

    class PCM_OT_toggle_english(Operator):
        """Cambia el idioma de la interfaz del addon"""

        bl_idname = "pcm.toggle_language"
        bl_label = "Cambiar idioma (ES / EN)"
        bl_description = "Alterna entre español e inglés para los textos del addon"
        bl_options = {"REGISTER"}

        def execute(self, context: Any) -> set:
            from .i18n import set_language

            current = get_language()
            new = "en" if current == "es" else "es"
            set_language(new)
            prefs = _prefs()
            if prefs is not None:
                try:
                    prefs.language = new
                except Exception:
                    log.debug("No se pudo sincronizar el idioma con las preferencias")
            _report(self, "INFO",
                    "Language: English" if new == "en" else "Idioma: español")
            for area in getattr(context.screen, "areas", ()):
                try:
                    area.tag_redraw()
                except Exception:
                    pass
            return {"FINISHED"}

    class PCM_OT_open_docs(Operator):
        """Abre la documentación del addon"""

        bl_idname = "pcm.open_docs"
        bl_label = "Abrir documentación"
        bl_options = {"REGISTER"}

        def execute(self, context: Any) -> set:
            folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
            readme = os.path.join(os.path.dirname(folder), "README.md")
            target = folder if os.path.isdir(folder) else readme
            if os.path.exists(target):
                _open_path(target)
                _report(self, "INFO", f"Documentación: {target}")
            else:
                _report(self, "WARNING",
                        "No se encontró la documentación en el paquete del addon")
            return {"FINISHED"}

else:  # pragma: no cover - fuera de Blender

    class PCM_OT_prepare_object:  # type: ignore[no-redef]
        bl_idname = "pcm.prepare_object"

    class PCM_OT_uv_report:  # type: ignore[no-redef]
        bl_idname = "pcm.uv_report"

    class PCM_OT_uv_pack:  # type: ignore[no-redef]
        bl_idname = "pcm.uv_pack"

    class PCM_OT_assign_zone:  # type: ignore[no-redef]
        bl_idname = "pcm.assign_zone"

    class PCM_OT_clear_zones:  # type: ignore[no-redef]
        bl_idname = "pcm.clear_zones"

    class PCM_OT_select_zone:  # type: ignore[no-redef]
        bl_idname = "pcm.select_zone"

    class PCM_OT_refresh_zones:  # type: ignore[no-redef]
        bl_idname = "pcm.refresh_zones"

    class PCM_OT_select_grow:  # type: ignore[no-redef]
        bl_idname = "pcm.select_grow"

    class PCM_OT_select_by_normal:  # type: ignore[no-redef]
        bl_idname = "pcm.select_by_normal"

    class PCM_OT_select_by_curvature:  # type: ignore[no-redef]
        bl_idname = "pcm.select_by_curvature"

    class PCM_OT_select_by_position:  # type: ignore[no-redef]
        bl_idname = "pcm.select_by_position"

    class PCM_OT_select_uv_islands:  # type: ignore[no-redef]
        bl_idname = "pcm.select_uv_islands"

    class PCM_OT_smooth_groups:  # type: ignore[no-redef]
        bl_idname = "pcm.smooth_groups"

    class PCM_OT_propose_zones:  # type: ignore[no-redef]
        bl_idname = "pcm.propose_zones"

    class PCM_OT_apply_proposals:  # type: ignore[no-redef]
        bl_idname = "pcm.apply_proposals"

    class PCM_OT_clear_proposals:  # type: ignore[no-redef]
        bl_idname = "pcm.clear_proposals"

    class PCM_OT_proposal_select:  # type: ignore[no-redef]
        bl_idname = "pcm.proposal_select"

    class PCM_OT_build_material:  # type: ignore[no-redef]
        bl_idname = "pcm.build_material"

    class PCM_OT_apply_zone_params:  # type: ignore[no-redef]
        bl_idname = "pcm.apply_zone_params"

    class PCM_OT_reload_zone_params:  # type: ignore[no-redef]
        bl_idname = "pcm.reload_zone_params"

    class PCM_OT_set_uv_scale:  # type: ignore[no-redef]
        bl_idname = "pcm.set_uv_scale"

    class PCM_OT_show_zone_colors:  # type: ignore[no-redef]
        bl_idname = "pcm.show_zone_colors"

    class PCM_OT_select_zone_from_list:  # type: ignore[no-redef]
        bl_idname = "pcm.select_zone_from_list"

    class PCM_OT_bake:  # type: ignore[no-redef]
        bl_idname = "pcm.bake"

    class PCM_OT_cancel_bake:  # type: ignore[no-redef]
        bl_idname = "pcm.cancel_bake"

    class PCM_OT_export_maps:  # type: ignore[no-redef]
        bl_idname = "pcm.export_maps"

    class PCM_OT_show_import_guide:  # type: ignore[no-redef]
        bl_idname = "pcm.show_import_guide"

    class PCM_OT_set_engine:  # type: ignore[no-redef]
        bl_idname = "pcm.set_engine"

    class PCM_OT_save_preset:  # type: ignore[no-redef]
        bl_idname = "pcm.save_preset"

    class PCM_OT_load_preset:  # type: ignore[no-redef]
        bl_idname = "pcm.load_preset"

    class PCM_OT_cleanup:  # type: ignore[no-redef]
        bl_idname = "pcm.cleanup"

    class PCM_OT_report:  # type: ignore[no-redef]
        bl_idname = "pcm.report"

    class PCM_OT_toggle_english:  # type: ignore[no-redef]
        bl_idname = "pcm.toggle_language"

    class PCM_OT_open_docs:  # type: ignore[no-redef]
        bl_idname = "pcm.open_docs"


CLASSES: Tuple[Any, ...] = (
    PCM_OT_prepare_object,
    PCM_OT_uv_report,
    PCM_OT_uv_pack,
    PCM_OT_assign_zone,
    PCM_OT_clear_zones,
    PCM_OT_select_zone,
    PCM_OT_refresh_zones,
    PCM_OT_select_grow,
    PCM_OT_select_by_normal,
    PCM_OT_select_by_curvature,
    PCM_OT_select_by_position,
    PCM_OT_select_uv_islands,
    PCM_OT_smooth_groups,
    PCM_OT_propose_zones,
    PCM_OT_apply_proposals,
    PCM_OT_clear_proposals,
    PCM_OT_proposal_select,
    PCM_OT_build_material,
    PCM_OT_apply_zone_params,
    PCM_OT_reload_zone_params,
    PCM_OT_set_uv_scale,
    PCM_OT_show_zone_colors,
    PCM_OT_select_zone_from_list,
    PCM_OT_bake,
    PCM_OT_cancel_bake,
    PCM_OT_export_maps,
    PCM_OT_show_import_guide,
    PCM_OT_set_engine,
    PCM_OT_save_preset,
    PCM_OT_load_preset,
    PCM_OT_cleanup,
    PCM_OT_report,
    PCM_OT_toggle_english,
    PCM_OT_open_docs,
)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _prefs() -> Any:
    try:
        from .preferences import get_prefs

        return get_prefs()
    except Exception:
        return None


def _resolution(context: Any) -> int:
    sp = _sp(context)
    try:
        return int(getattr(sp, "resolution", "4096"))
    except Exception:
        return 4096


def _uv_scale(obj: Any) -> float:
    props = properties.get_object(obj)
    try:
        return float(getattr(props, "uv_scale", 1.0))
    except Exception:
        return 1.0


def _enter_edit_mode(context: Any) -> None:
    obj = getattr(context, "active_object", None)
    if obj is None:
        return
    try:
        if context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
    except Exception as exc:
        log.debug("No se pudo entrar en modo edición: %s", exc)


def _preset_dir(context: Any) -> Optional[str]:
    """Carpeta de presets del usuario, junto a sus preferencias."""
    try:
        base = bpy.utils.user_resource("CONFIG")
    except Exception:
        base = None
    if not base:
        base = os.path.expanduser("~/.config/blender")
    folder = os.path.join(base, "pcm_studio_presets")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as exc:
        log.error("No se pudo crear la carpeta de presets %s: %s", folder, exc)
        return None
    return folder


def _write_text_block(context: Any, name: str, text: str, *,
                      open_editor: bool = False) -> Optional[str]:
    """Escribe un bloque de texto reutilizable y, si se pide, lo muestra."""
    if bpy is None:
        return None
    try:
        existing = bpy.data.texts.get(name)
        if existing is not None:
            bpy.data.texts.remove(existing)
        txt = bpy.data.texts.new(name)
        txt.write(text)
    except Exception as exc:
        log.debug("No se pudo escribir el bloque de texto: %s", exc)
        return None
    if open_editor:
        try:
            for area in context.screen.areas:
                if area.type == "TEXT_EDITOR":
                    for space in area.spaces:
                        if space.type == "TEXT_EDITOR":
                            space.text = txt
                    area.tag_redraw()
                    break
        except Exception:
            pass
    return name


def _remove_pcm_material(obj: Any) -> None:
    """Borra el material PCM de un objeto y sus grupos."""
    if bpy is None or obj is None:
        return
    mat = assembler._existing_pcm_material(obj)
    if mat is None:
        return
    idx = None
    for i, slot in enumerate(getattr(obj, "material_slots", ())):
        if getattr(slot, "material", None) is mat:
            idx = i
            break
    try:
        if idx is not None:
            obj.data.materials.pop(index=idx, update_data=True)
    except Exception as exc:
        log.debug("No se pudo retirar el material de %s: %s", obj.name, exc)
    try:
        mat.user_clear()
        bpy.data.materials.remove(mat)
    except Exception:
        pass
    assembler.cleanup_orphan_groups()


def _remove_unused_pcm_materials() -> int:
    if bpy is None:
        return 0
    n = 0
    for mat in list(bpy.data.materials):
        if not mat.name.startswith(assembler.MATERIAL_PREFIX):
            continue
        try:
            if mat.users == 0:
                bpy.data.materials.remove(mat)
                n += 1
        except Exception:
            continue
    return n


def _remove_pcm_images() -> int:
    if bpy is None:
        return 0
    n = 0
    for img in list(bpy.data.images):
        if not img.name.startswith(bake.BAKE_IMAGE_PREFIX):
            continue
        try:
            if img.users == 0:
                bpy.data.images.remove(img)
                n += 1
        except Exception:
            continue
    return n


def _open_path(path: str) -> None:
    """Abre una carpeta o fichero en el explorador del sistema."""
    if bpy is None:
        return
    try:
        if os.path.isdir(path):
            bpy.ops.wm.path_open(filepath=path)
        else:
            folder = os.path.dirname(path)
            bpy.ops.wm.path_open(filepath=folder)
    except Exception as exc:
        log.debug("No se pudo abrir %s: %s", path, exc)


def _save_material_blend(context: Any, obj: Any, out_dir: str) -> Optional[str]:
    """Guarda un .blend con sólo el material, para reutilizarlo."""
    if bpy is None or obj is None:
        return None
    mat = assembler._existing_pcm_material(obj)
    if mat is None:
        return None
    path = os.path.join(out_dir, f"PCM_material_{bake.clean_name(obj.name)}.blend")
    try:
        # marcar el material como "fake user" para que sobreviva
        try:
            mat.use_fake_user = True
        except Exception:
            pass
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    except Exception as exc:
        log.error("No se pudo guardar la copia .blend: %s", exc)
        return None
    finally:
        try:
            bpy.data.filepath = prev
        except Exception:
            pass
    return path


def _bake_report(bc: Any, dt: float) -> str:
    """Informe legible del bake, para el editor de texto."""
    lines = [
        "PCM Studio — Informe de bake",
        "=" * 46,
        f"Objeto:        {getattr(bc.obj, 'name', '?')}",
        f"Duración:      {dt:.1f} s",
        f"Modo normal:   {getattr(bc.settings, 'normal_mode', '?')}",
        f"Muestras:      {getattr(bc.settings, 'samples', '?')}",
        f"Denoiser:      {getattr(bc.settings, 'use_denoise', '?')}",
        f"Convención:    {getattr(bc.settings, 'normal_convention', '?')}",
        "",
        f"Mapas generados ({len(bc.done)}):",
    ]
    for key in bc.done:
        cfg = bake.MAPS[key]
        img = bc.images.get(key)
        size = f"{img.size[0]}×{img.size[1]}" if img is not None else "?"
        lines.append(f"  · {cfg['label']:<22} {size:<11} {cfg['colorspace']}")
    if bc.errors:
        lines += ["", "ERRORES:"] + [f"  ! {e}" for e in bc.errors]
    if bc.warnings:
        lines += ["", "AVISOS:"] + [f"  · {w}" for w in bc.warnings]
    lines += [
        "",
        "Recuerda:",
        "  · Color base y emisivo van en sRGB; el resto en lineal / Non-Color.",
        "  · La altura es lineal 0..1 en unidades del material.",
        "  · El perfil de Subsurface no se puede bakear: está en el manifiesto JSON.",
    ]
    return "\n".join(lines)


def _export_report(res: Dict[str, Any], sp: Any, obj: Any,
                   manifest: Optional[str] = None,
                   guide: Optional[str] = None) -> str:
    engine = getattr(sp, "engine", "unity")
    lines = [
        "PCM Studio — Exportación",
        "=" * 46,
        f"Objeto:     {getattr(obj, 'name', '?')}",
        f"Motor:      {engine}",
        f"Directorio: {res.get('dir', '?')}",
        f"Normales:   {getattr(sp, 'normal_convention', '?')}",
        "",
        f"Ficheros ({len(res.get('files', []))}):",
    ]
    for f in res.get("files", []):
        cfg = bake.MAPS.get(f["map"], {})
        lines.append(f"  · {f['name']:<44} {cfg.get('colorspace', '')}")
    if manifest:
        lines += ["", f"Manifiesto: {manifest}"]
    if guide:
        lines += [f"Guía:       {guide}"]
    if res.get("errors"):
        lines += ["", "ERRORES:"] + [f"  ! {e}" for e in res["errors"]]
    if res.get("warnings"):
        lines += ["", "AVISOS:"] + [f"  · {w}" for w in res["warnings"]]
    lines += ["", "-" * 46, ""]
    lines += export.import_instructions(engine).splitlines()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def register() -> None:
    if bpy is None:
        return
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            if "already registered" not in str(exc).lower():
                log.error("No se pudo registrar %s: %s",
                          getattr(cls, "bl_idname", cls), exc)
                raise


def unregister() -> None:
    if bpy is None:
        return
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
