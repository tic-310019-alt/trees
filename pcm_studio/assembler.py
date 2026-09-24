# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Ensamblador de materiales.

Convierte el mapa de zonas de un objeto en **un único material game-ready**.

Arquitectura del árbol generado::

    Material «PCM_<objeto>»
    └── Grupo «PCM_Master_<objeto>»
        ├── Attribute  (lee pcm_zone, float por cara)
        ├── Compare × N ──→ máscara de cada zona
        ├── Group «PCM_Z_<key>» × N   (una receta por zona)
        │     ├── entradas = parámetros de la zona (sliders en el panel)
        │     ├── Surface, Displacement
        │     └── Base Color / Roughness / Metallic / Normal / Height /
        │         Emission / Emission Strength / Alpha / AO  ← para el bake
        ├── Mix Shader encadenado por máscara
        └── Group Output

Ventajas de hacerlo así:

* **Un solo material y un solo set de mapas**: el personaje entero exporta como
  un asset, que es lo que pide un pipeline de juego.
* **Los parámetros viven en el grupo**: el usuario mueve sliders en el panel de
  PCM Studio sin abrir nunca el editor de nodos.
* **El bakeador sólo tiene que reenlazar una salida**: todos los canales ya
  están mezclados por zona, así que bakear "Roughness" es cambiar un link.
* **Reconstrucción barata**: al asignar una zona nueva sólo se añade el grupo
  de esa zona; el resto se reutiliza.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import compat, recipes, styles, zones as zones_mod
from .recipes.base import principled_from_channels as _principled_from_channels
from .i18n import T, get_language
from .log import log
from .shaderkit import Builder, GroupBuilder, NodeOut, in_socket, out_socket

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = (
    "ZONE_ATTR",
    "set_zone_faces",
    "write_zone_faces",
    "zone_color_attribute",
    "GROUP_PREFIX",
    "MASTER_PREFIX",
    "MATERIAL_PREFIX",
    "ensure_zone_attribute",
    "read_zone_attribute",
    "assigned_zones",
    "ensure_material",
    "build_material",
    "rebuild_material",
    "get_master_group",
    "get_zone_group",
    "save_user_params",
    "load_user_params",
    "set_zone_param",
    "material_report",
    "cleanup_orphan_groups",
)


ZONE_ATTR = "pcm_zone"
ZONE_COLOR_ATTR = "pcm_zone_color"
GROUP_PREFIX = "PCM_Z_"
MASTER_PREFIX = "PCM_Master_"
MATERIAL_PREFIX = "PCM_"

#: canales que expone cada grupo de zona (además del shader)
CHANNELS: Tuple[Tuple[str, str], ...] = (
    ("Surface", "SHADER"),
    ("Displacement", "FLOAT"),
    ("Base Color", "COLOR"),
    ("Roughness", "FLOAT"),
    ("Metallic", "FLOAT"),
    ("Normal", "VECTOR"),
    ("Height", "FLOAT"),
    ("Ambient Occlusion", "FLOAT"),
    ("Emission Color", "COLOR"),
    ("Emission Strength", "FLOAT"),
    ("Alpha", "FLOAT"),
    ("Specular", "FLOAT"),
    ("Subsurface Weight", "FLOAT"),
)


# ---------------------------------------------------------------------------
# Atributo de zonas
# ---------------------------------------------------------------------------

def ensure_zone_attribute(mesh: Any) -> Any:
    """
    Crea (si no existe) el atributo ``pcm_zone`` en el dominio de caras.

    Se usa un atributo *float* en vez de *int* porque el nodo ``Attribute`` de
    shader puede leerlo directamente y compararlo con un ``Math``; así no hace
    falta un canal de color por zona ni un Attribute Map.
    """
    if mesh is None:
        return None
    try:
        attrs = mesh.attributes
    except Exception:
        return None
    existing = attrs.get(ZONE_ATTR)
    if existing is not None:
        # asegurar dominio y tipo correctos
        if getattr(existing, "domain", "") != "FACE":
            try:
                attrs.remove(existing)
            except Exception:
                return existing
            existing = None
    if existing is None:
        try:
            existing = attrs.new(ZONE_ATTR, "FLOAT", "FACE")
        except Exception as exc:
            log.error("No se pudo crear el atributo %s: %s", ZONE_ATTR, exc)
            return None
    return existing


def read_zone_attribute(mesh: Any) -> Optional[List[float]]:
    attr = ensure_zone_attribute(mesh)
    if attr is None:
        return None
    try:
        return [d.value for d in attr.data]
    except Exception as exc:
        log.error("No se pudo leer el atributo %s: %s", ZONE_ATTR, exc)
        return None


def write_zone_faces(mesh: Any, face_indices: Iterable[int], zone_id: int) -> int:
    """Escribe ``zone_id`` en las caras indicadas. Devuelve cuántas escribió."""
    attr = ensure_zone_attribute(mesh)
    if attr is None:
        return 0
    n = 0
    try:
        data = attr.data
        for fi in face_indices:
            if 0 <= fi < len(data):
                data[fi].value = float(zone_id)
                n += 1
    except Exception as exc:
        log.error("No se pudo escribir el atributo %s: %s", ZONE_ATTR, exc)
    try:
        mesh.update()
    except Exception:
        pass
    return n


def set_zone_faces(mesh: Any, face_indices: Iterable[int], zone_id: int) -> int:
    """API pública para asignar (o quitar, con ``zone_id=0``) zonas a caras."""
    return write_zone_faces(mesh, face_indices, zone_id)


def assigned_zones(mesh: Any) -> Dict[int, int]:
    """``{zone_id: nº de caras}`` para las zonas con alguna cara asignada."""
    values = read_zone_attribute(mesh)
    out: Dict[int, int] = {}
    if not values:
        return out
    for v in values:
        zid = int(round(float(v)))
        if zid > 0:
            out[zid] = out.get(zid, 0) + 1
    return out


def zone_color_attribute(mesh: Any) -> Optional[Any]:
    """
    Crea/actualiza un atributo de color ``pcm_zone_color`` para ver las zonas en
    el viewport (modo *Attribute* o *Vertex Paint*).
    """
    if mesh is None:
        return None
    try:
        attrs = mesh.attributes
        col = attrs.get("pcm_zone_color")
        if col is None or getattr(col, "domain", "") != "FACE":
            if col is not None:
                try:
                    attrs.remove(col)
                except Exception:
                    pass
            col = attrs.new("pcm_zone_color", "FLOAT_COLOR", "FACE")
        values = read_zone_attribute(mesh)
        if not values:
            return col
        data = col.data
        for i, v in enumerate(values):
            if i >= len(data):
                break
            z = zones_mod.get_zone(int(round(float(v))))
            if z is None:
                data[i].color = (0.35, 0.35, 0.38, 1.0)
            else:
                data[i].color = (z.color[0], z.color[1], z.color[2], 1.0)
        try:
            mesh.update()
        except Exception:
            pass
        return col
    except Exception as exc:
        log.debug("No se pudo actualizar el color de zonas: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Construcción de un grupo de zona
# ---------------------------------------------------------------------------

def _group_name(zone: zones_mod.Zone) -> str:
    return f"{GROUP_PREFIX}{zone.key}"


def _master_name(obj_name: str) -> str:
    return f"{MASTER_PREFIX}{obj_name}"


def _declare_params(gb: GroupBuilder, zone: zones_mod.Zone, style: Any,
                    values: Dict[str, Any]) -> None:
    """Crea las entradas del grupo con sus valores resueltos."""
    for p in zone.params:
        default = values.get(p.name, p.default)
        gb.param(p.name, p.kind, default, min_value=p.min, max_value=p.max,
                 description=p.desc)


def _wire_outputs(gb: GroupBuilder, res: Any, style: Any) -> None:
    """
    Conecta el resultado de la receta a las salidas del grupo.

    Todo pasa por el *Principled BSDF* para el canal ``Surface``, y **además**
    se exponen los canales sueltos: el bakeador los necesita para generar los
    mapas sin depender del motor de render.
    """
    b = gb
    out_node = gb.group_output()
    for name, kind in CHANNELS:
        gb.output(name, kind)
    if out_node is None:
        return

    use_coat = float(style.globals.get("use_coat", 1.0)) > 0.5
    use_sheen = float(style.globals.get("use_sheen", 1.0)) > 0.5
    use_thin = float(style.globals.get("use_thin_film", 1.0)) > 0.5
    sss_method = "RANDOM_WALK_SKIN" if float(
        style.globals.get("sss_scale", 1.0)) > 0.5 else "RANDOM_WALK"

    # algunas recetas (pelo, pestañas) devuelven su propio shader
    surface_override = res.extra.get("surface") if hasattr(res, "extra") else None

    principled = None
    if surface_override is None:
        principled = _principled_from_channels(
            b, res, name="PCM_Principled", use_coat=use_coat,
            use_sheen=use_sheen, use_thin_film=use_thin,
            sss_method=sss_method, label="Shader")
        surface_override = principled

    def connect(out_name: str, value: Any) -> None:
        s = in_socket(out_node, out_name)
        if s is None or value is None:
            return
        if isinstance(value, NodeOut):
            b.link(value.socket, s)
        elif hasattr(value, "links"):
            b.link(value, s)
        else:
            try:
                if isinstance(value, (tuple, list)) and hasattr(s.default_value, "__len__"):
                    for i, v in enumerate(value):
                        if i < len(s.default_value):
                            s.default_value[i] = float(v)
                elif isinstance(value, (int, float)):
                    s.default_value = float(value)
            except Exception:
                pass

    connect("Surface", surface_override)
    connect("Base Color", getattr(res, "base_color", None))
    connect("Roughness", getattr(res, "roughness", None))
    connect("Metallic", getattr(res, "metallic", None))
    connect("Specular", getattr(res, "specular", None))
    connect("Normal", getattr(res, "normal_detail", None))
    connect("Subsurface Weight", getattr(res, "sss_weight", None))
    connect("Emission Color", getattr(res, "emission_color", None))
    connect("Emission Strength", getattr(res, "emission_strength", None))
    connect("Alpha", getattr(res, "alpha", None))
    connect("Ambient Occlusion", getattr(res, "ao", None))

    # Altura: ya viene escalada por el estilo; se deja tal cual para el
    # displacement y para el mapa de altura.
    height = getattr(res, "detail_height", None)
    if height is not None:
        h_scale = float(style.globals.get("height_scale", 1.0))
        if abs(h_scale - 1.0) > 1e-4:
            height = b.math("MULTIPLY", height, h_scale, label="Escala de altura")
        connect("Height", height)
        # Displacement real (se activa sólo al bakear con desplazamiento)
        disp = b.add("ShaderNodeDisplacement", label="Desplazamiento")
        if disp is not None:
            try:
                disp.mid_level = 0.5
            except Exception:
                compat.set_sock(disp, "Midlevel", 0.5)
            compat.set_sock(disp, "Scale", 0.02)
            b.link(height, in_socket(disp, "Height", 0))
            connect("Displacement", out_socket(disp, "Displacement", 0))


def zone_uses_skin(style: Any) -> bool:
    """(Reservado para futuras variantes de SSS por estilo.)"""
    return float(style.globals.get("sss_scale", 1.0)) > 0.01


def build_zone_group(zone: zones_mod.Zone, style: Any,
                     values: Optional[Dict[str, Any]] = None, *,
                     uv_scale: float = 1.0, reuse: bool = True) -> Optional[Any]:
    """
    Crea (o reconstruye) el grupo de nodos de una zona.

    ``values`` son los overrides del usuario; si no se pasan se usan los del
    estilo.  Con ``reuse=True`` se conserva el grupo existente y sólo se
    actualizan los valores por defecto (rápido al mover un slider).
    """
    if bpy is None:
        return None
    values = dict(values or {})
    name = _group_name(zone)
    existing = bpy.data.node_groups.get(name)

    if existing is not None and reuse:
        # sólo actualizar valores por defecto
        for p in zone.params:
            target = styles.resolve_param(style, zone, p, values.get(p.name))
            _set_group_input_default(existing, p.name, target)
        return existing

    if existing is not None:
        saved = _snapshot_group_inputs(existing)
        try:
            _force_remove_group(existing)
        except Exception:
            pass
        for k, v in saved.items():
            values.setdefault(k, v)

    tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
    if tree is None:
        return None
    try:
        tree.use_fake_user = True
    except Exception:
        pass
    gb = GroupBuilder(tree, label_prefix=zone.key)
    _declare_params(gb, zone, style, values)

    # resuelve los valores efectivos para pasarlos a la receta
    resolved = styles.resolve_params(style, zone, values)

    ctx = recipes.RecipeContext(gb, zone, style, resolved, uv_scale=uv_scale,
                                coord_space=_coord_space_for(zone))
    recipe_fn = recipes.get_recipe(zone.recipe)
    try:
        result = recipe_fn(ctx)
    except Exception as exc:  # una receta rota no debe tumbar todo el material
        log.error("La receta «%s» falló (%s); se usa la receta genérica",
                  zone.recipe, exc)
        try:
            ctx = recipes.RecipeContext(gb, zone, style, resolved,
                                        uv_scale=uv_scale,
                                        coord_space=_coord_space_for(zone))
            result = recipes.get_recipe("custom")(ctx)
        except Exception as exc2:
            log.error("La receta genérica también falló: %s", exc2)
            result = ctx.result

    if result is None:
        result = ctx.result
    _wire_outputs(gb, result, style)
    _tidy_group(tree)
    return tree


def _coord_space_for(zone: zones_mod.Zone) -> str:
    """Espacio de coordenadas por defecto según la zona."""
    if zone.key in ("iris", "cornea", "sclera", "animal_eye"):
        return "OBJECT"
    return "UV"


def _set_group_input_default(tree: Any, name: str, value: Any) -> bool:
    try:
        interface = getattr(tree, "interface", None)
        items = []
        if interface is not None:
            items = [i for i in interface.items_tree
                     if getattr(i, "in_out", "") == "INPUT"]
        else:
            items = list(getattr(tree, "inputs", []))
    except Exception:
        return False
    for it in items:
        try:
            if it.name != name:
                continue
        except Exception:
            continue
        try:
            if isinstance(value, (tuple, list)) and hasattr(it.default_value, "__len__"):
                for i, v in enumerate(value):
                    if i < len(it.default_value):
                        it.default_value[i] = float(v)
            elif isinstance(value, bool):
                it.default_value = bool(value)
            elif isinstance(value, int) and getattr(it, "type", "") == "INT":
                it.default_value = int(value)
            else:
                it.default_value = float(value)
            return True
        except Exception as exc:
            log.debug("No se pudo actualizar %s: %s", name, exc)
            return False
    return False


def _snapshot_group_inputs(tree: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        interface = getattr(tree, "interface", None)
        items = []
        if interface is not None:
            items = [i for i in interface.items_tree
                     if getattr(i, "in_out", "") == "INPUT"]
        else:
            items = list(getattr(tree, "inputs", []))
        for it in items:
            try:
                v = it.default_value
                if hasattr(v, "__len__") and not isinstance(v, (str, bytes)):
                    out[it.name] = tuple(float(x) for x in v)
                else:
                    out[it.name] = v
            except Exception:
                continue
    except Exception:
        pass
    return out


def _force_remove_group(tree: Any) -> None:
    """Borra un grupo de nodos aunque tenga usuarios falsos."""
    if bpy is None or tree is None:
        return
    try:
        tree.use_fake_user = False
    except Exception:
        pass
    try:
        tree.user_clear()
    except Exception:
        pass
    try:
        bpy.data.node_groups.remove(tree)
    except Exception as exc:
        log.debug("No se pudo borrar el grupo %s: %s", getattr(tree, "name", "?"), exc)


def _tidy_group(tree: Any) -> None:
    """Coloca Group Input/Output y oculta lo que sobra."""
    if tree is None:
        return
    try:
        gi = go = None
        for n in tree.nodes:
            if getattr(n, "bl_idname", "") == "NodeGroupInput":
                gi = n
            elif getattr(n, "bl_idname", "") == "NodeGroupOutput":
                go = n
        if gi is not None:
            gi.location = (-1600, 0)
        if go is not None:
            go.location = (1400, 0)
        for n in tree.nodes:
            if getattr(n, "bl_idname", "") == "ShaderNodeTexCoord":
                n.hide = True
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Grupo maestro
# ---------------------------------------------------------------------------

def get_master_group(obj: Any) -> Optional[Any]:
    if bpy is None or obj is None:
        return None
    return bpy.data.node_groups.get(_master_name(obj.name))


def get_zone_group(zone: zones_mod.Zone) -> Optional[Any]:
    if bpy is None:
        return None
    return bpy.data.node_groups.get(_group_name(zone))


def build_master_group(obj: Any, zone_ids: Sequence[int], style: Any, *,
                       values: Optional[Dict[str, Any]] = None,
                       uv_scale: float = 1.0) -> Optional[Any]:
    """
    Construye el grupo maestro: máscara por zona + mezcla de shaders + mezcla
    de canales para el bake.
    """
    if bpy is None or obj is None:
        return None
    values = values or {}
    name = _master_name(obj.name)
    old = bpy.data.node_groups.get(name)
    if old is not None:
        _force_remove_group(old)

    tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
    if tree is None:
        return None
    try:
        tree.use_fake_user = True
    except Exception:
        pass
    gb = GroupBuilder(tree)

    zone_list = [zones_mod.get_zone(z) for z in zone_ids]
    zone_list = [z for z in zone_list if z is not None]
    if not zone_list:
        z = zones_mod.get_zone(zones_mod.DEFAULT_ZONE_ID)
        if z is not None:
            zone_list = [z]

    # -- salidas del maestro -------------------------------------------------
    out_node = gb.group_output()
    for cname, kind in CHANNELS:
        gb.output(cname, kind)

    # -- lector de zonas -----------------------------------------------------
    zone_value = _zone_reader(gb)

    # -- grupos de zona y máscaras -------------------------------------------
    shader_chain: Any = None
    disp_acc: Any = None
    channel_mixers: Dict[str, Any] = {}

    for index, zone in enumerate(zone_list):
        zone_values = values.get(zone.key, {})
        ztree = build_zone_group(zone, style, zone_values, uv_scale=uv_scale,
                                 reuse=True)
        if ztree is None:
            continue
        gnode = gb.add("ShaderNodeGroup", name=f"PCM_Zone_{zone.key}",
                       label=zone.name(get_language()))
        if gnode is None:
            continue
        try:
            gnode.node_tree = ztree
        except Exception as exc:
            log.error("No se pudo asignar el grupo de %s: %s", zone.key, exc)
            continue
        try:
            gnode.use_custom_color = True
            gnode.color = (zone.color[0] * 0.45, zone.color[1] * 0.45,
                           zone.color[2] * 0.45)
        except Exception:
            pass

        mask = _zone_mask(gb, zone_value, zone.id, label=zone.name(get_language()))

        # --- cadena de shaders ---
        shader_out = out_socket(gnode, "Surface")
        if shader_out is not None:
            if shader_chain is None:
                shader_chain = shader_out
            else:
                mixsh = gb.add("ShaderNodeMixShader",
                               name=f"PCM_Mix_{zone.key}",
                               label=f"Mezcla · {zone.name(get_language())}")
                if mixsh is not None:
                    gb.link(mask, in_socket(mixsh, "Fac", 0))
                    a = in_socket(mixsh, "Shader", 1)
                    bb = in_socket(mixsh, "Shader_001", 2)
                    if bb is None:
                        shaders = [s for s in mixsh.inputs
                                   if getattr(s, "type", "") == "SHADER"]
                        a = shaders[0] if shaders else a
                        bb = shaders[1] if len(shaders) > 1 else bb
                    gb.link(shader_chain, a)
                    gb.link(shader_out, bb)
                    shader_chain = out_socket(mixsh, "Shader", 0)

        # --- displacement acumulado ---
        disp = out_socket(gnode, "Displacement")
        if disp is not None:
            if mask is not None:
                mul = gb.math("MULTIPLY", disp, mask, label=f"Desplazamiento · {zone.key}")
                disp_acc = mul if disp_acc is None else gb.math("ADD", disp_acc, mul)
            else:
                disp_acc = disp if disp_acc is None else disp_acc

        # --- mezcla de canales para el bake ---
        for cname, kind in CHANNELS:
            if cname in ("Surface", "Displacement"):
                continue
            z_out = out_socket(gnode, cname)
            if z_out is None:
                continue
            prev = channel_mixers.get(cname)
            if prev is None:
                channel_mixers[cname] = z_out
                continue
            if mask is None:
                continue
            if kind == "SHADER":
                continue
            data_type = "FLOAT" if kind == "FLOAT" else (
                "VECTOR" if kind == "VECTOR" else "RGBA")
            mixed = gb.mix(data_type, "MIX", mask, prev, z_out,
                           label=f"{cname} · {zone.key}")
            if mixed is not None:
                channel_mixers[cname] = mixed

    # -- salidas -------------------------------------------------------------
    if out_node is not None:
        if shader_chain is not None:
            gb.link(shader_chain, in_socket(out_node, "Surface"))
        if disp_acc is not None:
            gb.link(disp_acc, in_socket(out_node, "Displacement"))
        for cname, kind in CHANNELS:
            if cname in ("Surface", "Displacement"):
                continue
            src = channel_mixers.get(cname)
            if src is not None:
                gb.link(src, in_socket(out_node, cname))

    _layout_master(gb, zone_list)
    return tree


def _zone_reader(gb: Builder) -> Optional[Any]:
    """
    Nodo que lee el atributo ``pcm_zone`` por cara.

    Ruta principal: nodo ``Attribute`` en modo ``FLOAT``, que es la forma
    documentada de leer un atributo genérico en un shader y devuelve el valor en
    la salida ``Fac``.  Ruta alternativa (Blender muy antiguo sin el modo
    FLOAT): ``Vertex Color`` sobre un atributo de color que codifica el id en
    gris, multiplicado por 255 para recuperarlo.
    """
    n = gb.add("ShaderNodeAttribute", name="PCM_ZoneReader",
               label="Lector de zonas")
    if n is not None:
        try:
            n.attribute_type = "FLOAT"
            ok_float = True
        except Exception:
            ok_float = False
        try:
            n.attribute_name = ZONE_ATTR
        except Exception:
            pass
        if ok_float:
            out = out_socket(n, "Fac", "Value", 0)
            if out is not None:
                return out

    # --- alternativa: atributo de color ---
    if compat.has_node("ShaderNodeVertexColor"):
        vc = gb.add("ShaderNodeVertexColor", name="PCM_ZoneReaderColor",
                    label="Lector de zonas (color)")
        if vc is not None:
            try:
                vc.layer_name = ZONE_COLOR_ATTR
            except Exception:
                pass
            col = out_socket(vc, "Color", 0)
            sep = gb.add("ShaderNodeSeparateColor", label="ID de zona")
            if sep is not None and col is not None:
                gb.link(col, in_socket(sep, "Color", 0))
                red = out_socket(sep, "Red", 0)
                return gb.math("MULTIPLY", red, 255.0, label="ID de zona")
    if n is not None:
        return out_socket(n, "Fac", "Color", 0)
    return None


def _zone_mask(gb: Builder, zone_value: Any, zone_id: int, *,
               label: str = "") -> Optional[Any]:
    """Máscara 0/1 para la zona ``zone_id``."""
    if zone_value is None:
        return None
    # Comparar contra id-0.5 con GREATER_THAN y contra id+0.5 con LESS_THAN y
    # hacer AND da un intervalo exacto, robusto frente a precisión de float.
    lo = gb.math("GREATER_THAN", zone_value, zone_id - 0.5, label=f"{label} ≥")
    hi = gb.math("LESS_THAN", zone_value, zone_id + 0.5, label=f"{label} ≤")
    if lo is None or hi is None:
        return lo or hi
    return gb.math("MINIMUM", lo, hi, label=f"Máscara · {label}")


def _layout_master(gb: Builder, zone_list: Sequence[zones_mod.Zone]) -> None:
    """Ordena el grupo maestro en columnas legibles."""
    try:
        tree = gb.tree
        gi = go = None
        groups: List[Any] = []
        mixes: List[Any] = []
        others: List[Any] = []
        for n in tree.nodes:
            bid = getattr(n, "bl_idname", "")
            if bid == "NodeGroupInput":
                gi = n
            elif bid == "NodeGroupOutput":
                go = n
            elif bid == "ShaderNodeGroup":
                groups.append(n)
            elif bid in ("ShaderNodeMixShader", "ShaderNodeMix"):
                mixes.append(n)
            else:
                others.append(n)
        if gi is not None:
            gi.location = (-2200, 0)
        y = 400
        for n in groups:
            n.location = (-1200, y)
            y -= 420
        y = 400
        for n in mixes:
            n.location = (200, y)
            y -= 260
        if go is not None:
            go.location = (1200, 0)
        y = -600
        for n in others:
            if n.location == (0.0, 0.0):
                n.location = (-2200, y)
                y -= 180
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Material del objeto
# ---------------------------------------------------------------------------

def ensure_material(obj: Any, *, style: Any = None) -> Optional[Any]:
    """
    Garantiza que el objeto tenga un material PCM en el primer slot y devuelve
    ese material.  No reconstruye el árbol.
    """
    if bpy is None or obj is None:
        return None
    style = style or styles.get_style(styles.default_style_id())
    data = getattr(obj, "data", None)
    if data is None:
        return None

    # buscar un material PCM existente
    mat = None
    for slot in getattr(obj, "material_slots", ()):
        m = getattr(slot, "material", None)
        if m is not None and m.name.startswith(MATERIAL_PREFIX):
            mat = m
            break
    if mat is None:
        name = f"{MATERIAL_PREFIX}{obj.name}"
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name)
        if mat is None:
            return None
        try:
            if len(obj.material_slots) == 0:
                obj.data.materials.append(mat)
            else:
                obj.material_slots[0].material = mat
        except Exception as exc:
            log.error("No se pudo asignar el material al objeto: %s", exc)
            return None
    _init_material_settings(mat, obj, style)
    return mat


def _init_material_settings(mat: Any, obj: Any, style: Any) -> None:
    """Prepara el material para juego: backface culling, alpha, sin nodos sueltos."""
    if mat is None:
        return
    try:
        mat.use_nodes = True
    except Exception:
        pass
    try:
        mat.blend_method = "OPAQUE"
    except Exception:
        pass
    try:
        mat.shadow_method = "OPAQUE"
    except Exception:
        pass
    try:
        mat.use_backface_culling = True
    except Exception:
        pass
    try:
        mat.show_transparent_back = False
    except Exception:
        pass
    # guardar ajustes propios del addon en el material (sobreviven al guardado)
    try:
        mat["pcm_style"] = style.id
        mat["pcm_object"] = obj.name
        if "pcm_params" not in mat.keys():
            mat["pcm_params"] = {}
    except Exception:
        pass


def build_material(obj: Any, style: Any, *, uv_scale: float = 1.0,
                   force: bool = False) -> Optional[Any]:
    """
    Construye/reconstruye el material completo del objeto.

    Lee las zonas asignadas en la malla, crea los grupos de cada zona y el grupo
    maestro, y deja el material listo en el viewport.
    """
    if bpy is None or obj is None:
        return None
    data = getattr(obj, "data", None)
    if data is None:
        log.error("El objeto %s no tiene malla", getattr(obj, "name", "?"))
        return None

    ensure_zone_attribute(data)
    zone_map = assigned_zones(data)
    if not zone_map:
        zone_ids = [zones_mod.DEFAULT_ZONE_ID]
    else:
        # la zona por defecto va la primera en la cadena (fondo del material)
        ids = sorted(zone_map.keys())
        if zones_mod.DEFAULT_ZONE_ID not in ids:
            ids = [zones_mod.DEFAULT_ZONE_ID] + ids
        zone_ids = ids

    mat = ensure_material(obj, style=style)
    if mat is None:
        return None

    values = load_user_params(mat)
    master = build_master_group(obj, zone_ids, style, values=values,
                                uv_scale=uv_scale)
    if master is None:
        return None

    # conectar el grupo maestro a la salida del material
    try:
        mat.use_nodes = True
    except Exception:
        pass
    tree = getattr(mat, "node_tree", None)
    if tree is None:
        return mat
    b = Builder(tree)
    # limpiar nodos viejos de PCM
    for n in list(tree.nodes):
        if n.name.startswith("PCM_"):
            try:
                tree.nodes.remove(n)
            except Exception:
                pass
    gnode = b.add("ShaderNodeGroup", name="PCM_MasterNode",
                  label=f"PCM · {style.name(get_language())}")
    out = b.output_material()
    if gnode is not None:
        try:
            gnode.node_tree = master
        except Exception as exc:
            log.error("No se pudo conectar el grupo maestro: %s", exc)
            return mat
        gnode.location = (-400, 0)
        if out is not None:
            out.location = (200, 0)
            b.link(out_socket(gnode, "Surface"), in_socket(out, "Surface"))
            disp = out_socket(gnode, "Displacement")
            disp_in = in_socket(out, "Displacement")
            if disp is not None and disp_in is not None:
                # El desplazamiento sólo se conecta si el material lo tiene
                # activado; por defecto se deja desconectado para que el
                # viewport vaya fluido.
                try:
                    if mat.get("pcm_connect_displacement", False):
                        b.link(disp, disp_in)
                except Exception:
                    pass
    try:
        mat["pcm_style"] = style.id
        mat["pcm_zones"] = [int(z) for z in zone_ids]
    except Exception:
        pass
    return mat


def rebuild_material(obj: Any, style: Any = None, *, uv_scale: float = 1.0) -> Optional[Any]:
    """Reconstrucción forzada (tras cambiar de estilo o editar zonas)."""
    if style is None:
        mat = _existing_pcm_material(obj)
        style = styles.get_style(mat.get("pcm_style", styles.default_style_id())
                                 if mat is not None else styles.default_style_id())
    return build_material(obj, style, uv_scale=uv_scale, force=True)


def _existing_pcm_material(obj: Any) -> Optional[Any]:
    if obj is None:
        return None
    for slot in getattr(obj, "material_slots", ()):
        m = getattr(slot, "material", None)
        if m is not None and m.name.startswith(MATERIAL_PREFIX):
            return m
    return None


# ---------------------------------------------------------------------------
# Parámetros de usuario persistentes
# ---------------------------------------------------------------------------

def save_user_params(mat: Any, zone_key: str, values: Dict[str, Any]) -> None:
    """Guarda los overrides del usuario dentro del material (sobreviven al .blend)."""
    if mat is None:
        return
    try:
        store = mat.get("pcm_params")
        if not isinstance(store, dict):
            store = {}
        current = dict(store)
        entry = dict(current.get(zone_key, {}))
        for k, v in values.items():
            if isinstance(v, (tuple, list)):
                entry[k] = tuple(float(x) for x in v)
            elif isinstance(v, bool):
                entry[k] = bool(v)
            elif isinstance(v, (int, float)):
                entry[k] = float(v)
            else:
                entry[k] = v
        current[zone_key] = entry
        mat["pcm_params"] = current
    except Exception as exc:
        log.debug("No se pudieron guardar los parámetros: %s", exc)


def load_user_params(mat: Any) -> Dict[str, Dict[str, Any]]:
    if mat is None:
        return {}
    try:
        store = mat.get("pcm_params")
        if isinstance(store, dict):
            return {str(k): dict(v) for k, v in store.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def set_zone_param(obj: Any, zone_key: str, param: str, value: Any, *,
                   rebuild: bool = False) -> bool:
    """
    Cambia un parámetro de una zona en caliente.

    Sin ``rebuild`` sólo se toca el valor por defecto de la entrada del grupo,
    que es instantáneo.  Con ``rebuild`` se regenera todo el árbol.
    """
    if bpy is None or obj is None:
        return False
    mat = _existing_pcm_material(obj)
    if mat is None:
        return False
    save_user_params(mat, zone_key, {param: value})
    zone = zones_mod.get_zone_by_key(zone_key)
    if zone is None:
        return False
    tree = bpy.data.node_groups.get(_group_name(zone))
    if tree is None:
        return rebuild_material(obj) is not None
    ok = _set_group_input_default(tree, param, value)
    if not ok or rebuild:
        return rebuild_material(obj) is not None
    _tag_update(obj)
    return True


def _tag_update(obj: Any) -> None:
    try:
        obj.update_tag()
        for d in bpy.context.view_layer.depsgraph.updates:
            pass
    except Exception:
        pass
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Informes y limpieza
# ---------------------------------------------------------------------------

def material_report(obj: Any) -> Dict[str, Any]:
    """Estado del material de un objeto, para el panel y el diagnóstico."""
    info: Dict[str, Any] = {
        "object": getattr(obj, "name", None),
        "material": None,
        "style": None,
        "zones": [],
        "faces_total": 0,
        "faces_unassigned": 0,
        "has_uv": False,
        "uv_layers": [],
        "master_group": None,
        "zone_groups": [],
        "warnings": [],
    }
    if obj is None:
        return info
    data = getattr(obj, "data", None)
    mat = _existing_pcm_material(obj)
    info["material"] = mat.name if mat is not None else None
    if mat is not None:
        info["style"] = mat.get("pcm_style")
    if data is not None:
        info["faces_total"] = len(getattr(data, "polygons", ()))
        try:
            info["uv_layers"] = [uv.name for uv in data.uv_layers]
            info["has_uv"] = len(data.uv_layers) > 0
        except Exception:
            pass
        zmap = assigned_zones(data)
        info["zones"] = [
            {"id": zid, "key": z.key if (z := zones_mod.get_zone(zid)) else "?",
             "name": z.name(get_language()) if z else f"Zona {zid}",
             "faces": count}
            for zid, count in sorted(zmap.items())
        ]
        info["faces_unassigned"] = info["faces_total"] - sum(zmap.values())
        if not info["has_uv"]:
            info["warnings"].append(T("El objeto necesita UVs"))
        if info["faces_unassigned"] > 0:
            info["warnings"].append(
                f"{info['faces_unassigned']} {T('caras')} {T('Sin zonas asignadas')}")
    info["master_group"] = _master_name(obj.name) if get_master_group(obj) else None
    info["zone_groups"] = [g.name for g in (bpy.data.node_groups if bpy else [])
                           if g.name.startswith(GROUP_PREFIX)]
    return info


def cleanup_orphan_groups() -> int:
    """Borra los grupos de PCM que ya no usa ningún material. Devuelve cuántos."""
    if bpy is None:
        return 0
    used = set()
    for mat in bpy.data.materials:
        for tree in _iter_used_groups(getattr(mat, "node_tree", None)):
            used.add(tree.name)
    removed = 0
    for g in list(bpy.data.node_groups):
        if not g.name.startswith((GROUP_PREFIX, MASTER_PREFIX)):
            continue
        if g.name in used:
            continue
        try:
            users = g.users
        except Exception:
            users = 0
        if users <= (1 if getattr(g, "use_fake_user", False) else 0):
            _force_remove_group(g)
            removed += 1
    return removed


def _iter_used_groups(tree: Any, seen: Optional[set] = None) -> Iterable[Any]:
    if tree is None:
        return
    seen = seen if seen is not None else set()
    if tree.name in seen:
        return
    seen.add(tree.name)
    yield tree
    try:
        for n in tree.nodes:
            sub = getattr(n, "node_tree", None)
            if sub is not None:
                yield from _iter_used_groups(sub, seen)
    except Exception:
        pass
