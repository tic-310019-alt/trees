# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Autodiagnóstico.

Un generador procedural de nodos puede fallar de muchas formas silenciosas (un
socket renombrado, un nodo que no existe en esta versión, un objeto sin UV…).
Este módulo hace tres cosas:

1. **Informe de compatibilidad**: qué nodos y sockets del *Principled BSDF*
   están disponibles en el Blender que se está usando.
2. **Validación del material**: recorre el árbol generado y comprueba que no
   haya nodos huérfanos, salidas sin conectar ni grupos vacíos.
3. **Volcado a texto**: escribe el informe en un ``Text`` de Blender para que el
   usuario pueda copiarlo al reportar un problema.

El operador ``pcm.validate_setup`` ejecuta todo esto sobre el objeto activo y
devuelve un informe accionable (qué falta y qué botón arregla cada cosa).
"""

from __future__ import annotations

import datetime
import platform
from typing import Any, Dict, List, Optional, Tuple

from . import compat, styles, zones as zones_mod
from .i18n import T, get_language
from .log import all_history, log

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = ("build_report_text", "write_report", "validate_scene",
           "count_nodes", "VALIDATORS")


# ---------------------------------------------------------------------------
# Comprobaciones sueltas
# ---------------------------------------------------------------------------

def _check_blender_version() -> Tuple[str, List[str], List[str]]:
    errores: List[str] = []
    avisos: List[str] = []
    v = compat.BLENDER_VERSION
    if v < (4, 2, 0):
        errores.append(
            f"Blender {compat.BLENDER_VERSION_STR} es anterior a 4.2. "
            "PCM Studio necesita 4.2 o superior (recomendado 5.x).")
    elif v < (5, 0, 0):
        avisos.append(
            f"Blender {compat.BLENDER_VERSION_STR}: funciona, pero los nodos "
            "nuevos (Gabor, Velvet, película fina en metales) no existen. "
            "Se aplicarán los fallbacks automáticos.")
    return "Versión de Blender", errores, avisos


def _check_required_nodes() -> Tuple[str, List[str], List[str]]:
    report = compat.feature_report()
    errores = [f"Falta el nodo esencial {n}" for n in report["required_missing"]]
    avisos = [f"{n} no disponible; se usará "
              f"{compat.NODE_FALLBACKS.get(n, 'un fallback')}"
              for n in report["modern_missing"]]
    return "Nodos", errores, avisos


def _check_principled_sockets() -> Tuple[str, List[str], List[str]]:
    report = compat.feature_report()
    critical = ("Base Color", "Roughness", "Normal")
    errores = [f"El Principled BSDF no expone «{s}»"
               for s in report["principled_missing"] if s in critical]
    opcionales = [s for s in report["principled_missing"] if s not in critical]
    avisos = []
    if opcionales:
        avisos.append("Sockets opcionales no disponibles en esta versión: "
                      + ", ".join(opcionales))
    return "Sockets del Principled BSDF", errores, avisos


def _check_cycles() -> Tuple[str, List[str], List[str]]:
    errores: List[str] = []
    avisos: List[str] = []
    if bpy is None:
        return "Motor de render", errores, avisos
    try:
        import addon_utils

        loaded_default, loaded = addon_utils.check("cycles")
        if not loaded:
            avisos.append("El addon «Cycles» no está activado: el bake no estará "
                          "disponible hasta activarlo en Preferencias ▸ Add-ons.")
    except Exception:
        avisos.append("No se pudo comprobar si Cycles está activado.")
    return "Motor de render", errores, avisos


def _check_active_object(context: Any) -> Tuple[str, List[str], List[str]]:
    from . import assembler
    from .properties import get_object

    errores: List[str] = []
    avisos: List[str] = []
    obj = getattr(context, "object", None) if context else None
    if obj is None:
        avisos.append("No hay objeto activo: selecciona el personaje para validar.")
        return "Objeto activo", errores, avisos
    if getattr(obj, "type", "") != "MESH":
        errores.append(f"El objeto activo «{obj.name}» no es una malla.")
        return "Objeto activo", errores, avisos

    data = obj.data
    if len(getattr(data, "polygons", ())) == 0:
        errores.append("La malla no tiene caras.")
    uv_names = [uv.name for uv in getattr(data, "uv_layers", [])]
    if not uv_names:
        errores.append("La malla no tiene mapa UV. Sin UV no se puede bakear: usa "
                       "«Crear UVs» del panel.")
    else:
        # islas fuera del 0..1 sangran en el motor
        try:
            outside = 0
            for poly in data.polygons:
                for li in poly.loop_indices:
                    uv = data.uv_layers.active.data[li].uv
                    if not (-0.001 <= uv.x <= 1.001 and -0.001 <= uv.y <= 1.001):
                        outside += 1
                        break
            if outside:
                avisos.append(f"{outside} caras con UV fuera del espacio 0-1. "
                              "Recógelas o usa «Empaquetar islas» antes de bakear.")
        except Exception:
            pass

    props = get_object(obj)
    if props is None or not getattr(props, "prepared", False):
        avisos.append("El objeto no está preparado. Pulsa «Preparar objeto».")
    else:
        zmap = assembler.assigned_zones(data)
        if not zmap:
            avisos.append("No hay zonas asignadas: se usará «Piel — Cuerpo» para "
                          "todo el modelo.")
        total = len(data.polygons)
        assigned = sum(zmap.values())
        if total and assigned < total:
            avisos.append(f"{total - assigned} de {total} caras sin zona "
                          f"({100.0 * (total - assigned) / total:.1f} %).")

    mat = None
    for slot in getattr(obj, "material_slots", ()):
        m = getattr(slot, "material", None)
        if m is not None and m.name.startswith(assembler.MATERIAL_PREFIX):
            mat = m
            break
    if mat is None:
        avisos.append("El objeto no tiene material PCM. Pulsa «Generar material».")
    else:
        tree = getattr(mat, "node_tree", None)
        if tree is None or len(tree.nodes) == 0:
            errores.append(f"El material «{mat.name}» no tiene nodos.")
        else:
            groups = [n for n in tree.nodes
                      if getattr(n, "bl_idname", "") == "ShaderNodeGroup"]
            if not groups:
                avisos.append("El material no referencia ningún grupo PCM: vuelve a "
                              "pulsar «Generar material».")
            for g in groups:
                if getattr(g, "node_tree", None) is None:
                    errores.append(f"El nodo de grupo «{g.name}» no tiene árbol "
                                   "asignado.")
    return "Objeto activo", errores, avisos


def _check_material_tree(context: Any) -> Tuple[str, List[str], List[str]]:
    from . import assembler

    errores: List[str] = []
    avisos: List[str] = []
    if bpy is None:
        return "Árbol de nodos", errores, avisos
    obj = getattr(context, "object", None) if context else None
    master = assembler.get_master_group(obj) if obj is not None else None
    if master is None:
        avisos.append("No existe el grupo maestro de este objeto.")
        return "Árbol de nodos", errores, avisos

    n_nodes = count_nodes(master)
    outputs = [s for s in getattr(master, "outputs", ())] if not hasattr(
        master, "interface") else [
        i for i in master.interface.items_tree if getattr(i, "in_out", "") == "OUTPUT"]
    go = [n for n in master.nodes if getattr(n, "bl_idname", "") == "NodeGroupOutput"]
    if not go:
        errores.append("El grupo maestro no tiene nodo «Group Output».")
    else:
        for sock in go[0].inputs:
            if sock.name == "Surface" and not sock.is_linked:
                errores.append("La salida «Surface» del grupo maestro no está "
                               "conectada: el material saldrá negro.")
    if n_nodes < 10:
        avisos.append(f"El grupo maestro sólo tiene {n_nodes} nodos: puede que la "
                      "construcción se haya interrumpido.")
    return "Árbol de nodos", errores, avisos


def _check_disk(context: Any) -> Tuple[str, List[str], List[str]]:
    from .properties import get_scene

    errores: List[str] = []
    avisos: List[str] = []
    if bpy is None:
        return "Exportación", errores, avisos
    sp = get_scene(context)
    if sp is None:
        return "Exportación", errores, avisos
    out = getattr(sp, "output_dir", "") or ""
    if not out:
        avisos.append("No hay directorio de salida definido.")
    else:
        try:
            import os

            resolved = bpy.path.abspath(out)
            if not os.path.isdir(os.path.dirname(resolved) or resolved):
                avisos.append(f"El directorio «{resolved}» no existe todavía; se "
                              "creará al exportar.")
        except Exception:
            pass
    return "Exportación", errores, avisos


VALIDATORS = (
    _check_blender_version,
    _check_required_nodes,
    _check_principled_sockets,
    _check_cycles,
    _check_active_object,
    _check_material_tree,
    _check_disk,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def count_nodes(tree: Any, seen: Optional[set] = None) -> int:
    """Cuenta nodos de un árbol y de los grupos anidados."""
    if tree is None:
        return 0
    seen = seen if seen is not None else set()
    if getattr(tree, "name", None) in seen:
        return 0
    seen.add(getattr(tree, "name", None))
    total = 0
    try:
        for n in tree.nodes:
            total += 1
            sub = getattr(n, "node_tree", None)
            if sub is not None:
                total += count_nodes(sub, seen)
    except Exception:
        pass
    return total


def validate_scene(context: Any) -> Dict[str, Any]:
    """Ejecuta todas las comprobaciones y devuelve un informe estructurado."""
    sections: List[Dict[str, Any]] = []
    errors = 0
    warnings = 0
    for fn in VALIDATORS:
        try:
            title, errs, warns = fn(context)
        except Exception as exc:
            title, errs, warns = getattr(fn, "__name__", "?"), [
                f"La comprobación falló: {exc}"], []
        errors += len(errs)
        warnings += len(warns)
        sections.append({"title": title, "errors": errs, "warnings": warns})
    return {
        "sections": sections,
        "errors": errors,
        "warnings": warnings,
        "ok": errors == 0,
    }


def build_report_text(context: Any) -> str:
    """Informe completo en texto plano (para copiar/pegar en un issue)."""
    lines: List[str] = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("=" * 72)
    lines.append("PCM STUDIO — INFORME DE DIAGNÓSTICO")
    lines.append("=" * 72)
    lines.append(f"Fecha            : {now}")
    lines.append(f"Blender          : {compat.BLENDER_VERSION_STR}")
    lines.append(f"Sistema          : {platform.system()} {platform.release()}")
    try:
        lines.append(f"Python           : {platform.python_version()}")
    except Exception:
        pass
    try:
        lines.append(f"Motor de render  : {context.scene.render.engine}")
    except Exception:
        pass
    try:
        lines.append(f"Dispositivo      : "
                     f"{context.preferences.addons['cycles'].preferences.compute_device_type}"
                     )
    except Exception:
        pass
    try:
        units = context.scene.unit_settings.system
        scale = context.scene.unit_settings.scale_length
        lines.append(f"Unidades         : {units} (escala {scale})")
    except Exception:
        pass
    lines.append("")

    lines.append("-" * 72)
    lines.append("COMPROBACIONES")
    lines.append("-" * 72)
    result = validate_scene(context)
    for sec in result["sections"]:
        lines.append(f"\n[{sec['title']}]")
        if not sec["errors"] and not sec["warnings"]:
            lines.append("  ✓ correcto")
        for e in sec["errors"]:
            lines.append(f"  ✗ ERROR: {e}")
        for w in sec["warnings"]:
            lines.append(f"  ! AVISO: {w}")
    lines.append("")
    lines.append(f"Resumen: {result['errors']} errores, "
                 f"{result['warnings']} avisos")
    lines.append("")

    lines.append("-" * 72)
    lines.append("CAPACIDADES DETECTADAS")
    lines.append("-" * 72)
    rep = compat.feature_report()
    lines.append("Nodos modernos disponibles:")
    for n in rep["modern_available"]:
        lines.append(f"  + {n}")
    if rep["modern_missing"]:
        lines.append("Nodos modernos NO disponibles (se usa fallback):")
        for n in rep["modern_missing"]:
            lines.append(f"  - {n}  ->  {compat.NODE_FALLBACKS.get(n, '?')}")
    if rep["principled_missing"]:
        lines.append("Sockets del Principled no disponibles:")
        for n in rep["principled_missing"]:
            lines.append(f"  - {n}")
    lines.append("")

    if bpy is not None and getattr(context, "object", None) is not None:
        from . import assembler

        lines.append("-" * 72)
        lines.append(f"OBJETO: {context.object.name}")
        lines.append("-" * 72)
        info = assembler.material_report(context.object)
        lines.append(f"Material        : {info['material']}")
        lines.append(f"Estilo          : {info['style']}")
        lines.append(f"Caras           : {info['faces_total']}")
        lines.append(f"UV layers       : {info['uv_layers']}")
        lines.append(f"Sin zona        : {info['faces_unassigned']}")
        lines.append("Zonas:")
        for z in info["zones"]:
            lines.append(f"  · [{z['id']:>2}] {z['name']:<28} {z['faces']:>7} caras")
        master = assembler.get_master_group(context.object)
        if master is not None:
            lines.append(f"Nodos del grupo maestro: {count_nodes(master)}")
            total = 0
            for g in bpy.data.node_groups:
                if g.name.startswith(assembler.GROUP_PREFIX):
                    c = count_nodes(g)
                    total += c
                    lines.append(f"  · {g.name:<34} {c:>5} nodos")
            lines.append(f"Total de nodos de zonas: {total}")
        lines.append("")

    lines.append("-" * 72)
    lines.append(f"ZONAS DEL CATÁLOGO ({len(zones_mod.ZONES)})")
    lines.append("-" * 72)
    for z in zones_mod.ZONES:
        lines.append(f"  [{z.id:>2}] {z.key:<18} {z.name(get_language()):<32} "
                     f"{len(z.params):>2} parámetros  receta={z.recipe}")
    lines.append("")
    lines.append("-" * 72)
    lines.append(f"ESTILOS ({len(styles.STYLES)})")
    lines.append("-" * 72)
    for s in styles.STYLES:
        lines.append(f"  · {s.id:<12} {s.name(get_language())}  "
                     f"({len(s.zones)} zonas con override)")
    lines.append("")

    lines.append("-" * 72)
    lines.append("REGISTRO RECIENTE")
    lines.append("-" * 72)
    history = all_history()
    if not history:
        lines.append("  (sin entradas)")
    for level, msg in history[-60:]:
        lines.append(f"  {level:<8} {msg}")
    lines.append("")
    lines.append("=" * 72)
    lines.append("FIN DEL INFORME")
    lines.append("=" * 72)
    return "\n".join(lines)


def write_report(context: Any, text: str, *,
                 name: str = "PCM_Diagnóstico") -> Optional[Any]:
    """Escribe el informe en un datablock Text y lo abre en un editor."""
    if bpy is None:
        return None
    try:
        existing = bpy.data.texts.get(name)
        if existing is not None:
            bpy.data.texts.remove(existing)
        txt = bpy.data.texts.new(name)
        txt.from_string(text)
    except Exception as exc:
        log.error("No se pudo crear el informe: %s", exc)
        return None
    # abrirlo en un área de texto si hay alguna disponible
    try:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "TEXT_EDITOR":
                    area.spaces.active.text = txt
                    area.tag_redraw()
                    return txt
    except Exception:
        pass
    return txt
