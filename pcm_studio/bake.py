# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Motor de bake.

Convierte el material procedural en **mapas de textura**, que es lo único que un
motor de juego entiende.

Decisiones de diseño importantes:

* **Material temporal de bake.** Se crea ``PCM_BAKE_<objeto>`` con el grupo
  maestro dentro, una salida por canal y un nodo de imagen por mapa.  El
  material real del personaje no se modifica nunca, y al terminar se retira el
  slot temporal.  Así un fallo a mitad del bake no deja el asset roto.

* **Normales con micro-detalle de verdad.** Un bake ``NORMAL`` estándar de
  Cycles sólo captura la geometría: los poros procedurales no aparecerían.  Por
  eso el modo por defecto (``displaced``) activa temporalmente el
  ``Displacement`` del material + subdivisión adaptativa, de modo que el relieve
  se convierte en geometría real y acaba en el mapa.  Es lo que separa una
  normal "de IA" de una normal de personaje.

* **Canales sueltos por Emission.** Color base, rugosidad, metálico, altura,
  emisivo y alfa se bakean enchufando el canal a un ``Emission`` de fuerza 1 y
  usando el tipo ``EMIT``: da el valor exacto del canal, sin iluminación ni
  dependencia del color de vértice (que es lo que hace el tipo ``DIFFUSE``).

* **Normal de detalle (overlay).** Además se puede generar un segundo mapa con
  sólo el micro-relieve en espacio tangente, para usarlo como *Detail Normal*
  en Unity/Unreal y ganar nitidez en primer plano sin subir la resolución.

* **Post-proceso barato.** Invertir el verde para DirectX se hace con
  ``image.invert()`` (nativo y rápido); el empaquetado ORM con un nodo de
  imagen adicional en el propio material de bake, sin tocar píxeles a mano.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import assembler, compat, styles
from .i18n import T, get_language
from .log import log
from .shaderkit import Builder, in_socket, out_socket

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = (
    "MAPS",
    "clean_name",
    "BakeJob",
    "BakeContext",
    "prepare_bake",
    "finish_bake",
    "bake_one",
    "image_name",
    "get_or_create_image",
    "suffix_for_engine",
    "normal_convention_for_engine",
)


BAKE_MATERIAL_PREFIX = "PCM_BAKE_"
BAKE_IMAGE_PREFIX = "PCM_"

#: orden de bake y configuración de cada mapa
MAPS: Dict[str, Dict[str, Any]] = {
    "basecolor": {
        "suffix": "_BaseColor",
        "label": "Color base",
        "channel": "Base Color",
        "method": "emit",
        "colorspace": "sRGB",
        "float": False,
    },
    "normal": {
        "suffix": "_Normal",
        "label": "Normal",
        "channel": None,
        "method": "normal",
        "colorspace": "Non-Color",
        "float": False,
    },
    "roughness": {
        "suffix": "_Roughness",
        "label": "Rugosidad",
        "channel": "Roughness",
        "method": "emit",
        "colorspace": "Non-Color",
        "float": False,
    },
    "metallic": {
        "suffix": "_Metallic",
        "label": "Metálico",
        "channel": "Metallic",
        "method": "emit",
        "colorspace": "Non-Color",
        "float": False,
    },
    "ao": {
        "suffix": "_AO",
        "label": "Oclusión ambiental",
        "channel": "Ambient Occlusion",
        "method": "ao",
        "colorspace": "Non-Color",
        "float": False,
    },
    "height": {
        "suffix": "_Height",
        "label": "Altura",
        "channel": "Height",
        "method": "emit",
        "colorspace": "Non-Color",
        "float": True,
    },
    "emission": {
        "suffix": "_Emissive",
        "label": "Emisivo",
        "channel": "Emission Color",
        "method": "emit_color",
        "colorspace": "sRGB",
        "float": False,
    },
    "alpha": {
        "suffix": "_Opacity",
        "label": "Alfa",
        "channel": "Alpha",
        "method": "emit",
        "colorspace": "Non-Color",
        "float": False,
    },
    "normal_overlay": {
        "suffix": "_NormalDetail",
        "label": "Normal de detalle",
        "channel": "Normal",
        "method": "normal_overlay",
        "colorspace": "Non-Color",
        "float": False,
    },
    "orm": {
        "suffix": "_ORM",
        "label": "ORM empaquetado",
        "channel": None,
        "method": "orm",
        "colorspace": "Non-Color",
        "float": False,
    },
}

#: sufijo alternativo por motor (para quien prefiera la nomenclatura propia)
ENGINE_SUFFIX: Dict[str, Dict[str, str]] = {
    "unreal": {
        "basecolor": "_BaseColor",
        "normal": "_Normal",
        "roughness": "_Roughness",
        "metallic": "_Metallic",
        "ao": "_AO",
        "height": "_Height",
        "emission": "_Emissive",
        "alpha": "_Opacity",
        "normal_overlay": "_NormalDetail",
        "orm": "_ORM",
    },
    "unity": {
        "basecolor": "_Albedo",
        "normal": "_Normal",
        "roughness": "_Smoothness",
        "metallic": "_Metallic",
        "ao": "_AO",
        "height": "_Height",
        "emission": "_Emission",
        "alpha": "_Alpha",
        "normal_overlay": "_NormalDetail",
        "orm": "_MaskMap",
    },
    "godot": {},
    "generic": {},
}

#: convención de normales por defecto según motor
ENGINE_NORMAL: Dict[str, str] = {
    "unity": "opengl",
    "unreal": "directx",
    "godot": "opengl",
    "generic": "opengl",
}


def suffix_for_engine(engine: str, map_key: str) -> str:
    table = ENGINE_SUFFIX.get(engine) or {}
    return table.get(map_key) or MAPS[map_key]["suffix"]


def normal_convention_for_engine(engine: str) -> str:
    return ENGINE_NORMAL.get(engine, "opengl")


def image_name(prefix: str, map_key: str, engine: str, resolution: int) -> str:
    return f"{prefix}{suffix_for_engine(engine, map_key)}_{resolution}"


# ---------------------------------------------------------------------------
# Estado del bake
# ---------------------------------------------------------------------------

class BakeContext:
    """Todo lo que el operador modal necesita entre pasos."""

    def __init__(self) -> None:
        self.obj: Any = None
        self.style: Any = None
        self.settings: Any = None
        self.maps: List[str] = []
        self.images: Dict[str, Any] = {}
        self.bake_material: Any = None
        self.master_group: Any = None
        self.image_nodes: Dict[str, Any] = {}
        self.channel_nodes: Dict[str, Any] = {}
        self.emission: Any = None
        self.output: Any = None
        # estado original a restaurar
        self.prev_engine: Optional[str] = None
        self.prev_samples: Optional[int] = None
        self.prev_denoise: Any = None
        self.prev_dicing: Optional[float] = None
        self.prev_offline_dicing: Optional[float] = None
        self.prev_max_subdiv: Optional[int] = None
        self.prev_adaptive: Optional[bool] = None
        self.prev_margin: Optional[int] = None
        self.prev_margin_type: Optional[str] = None
        self.prev_use_clear: Optional[bool] = None
        self.prev_normal_space: Optional[str] = None
        self.prev_resolution: Optional[Tuple[int, int]] = None
        self.prev_slot_index: int = -1
        self.subdiv_mod: Any = None
        self.step: int = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.done: List[str] = []


class BakeJob:
    """Describe la secuencia de pasos de un bake completo."""

    def __init__(self, steps: Sequence[str]):
        self.steps = list(steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)


# ---------------------------------------------------------------------------
# Preparación
# ---------------------------------------------------------------------------

def get_or_create_image(name: str, resolution: int, *, colorspace: str = "Non-Color",
                        float_buffer: bool = False, alpha: bool = False) -> Any:
    """Crea (o reutiliza y redimensiona) una imagen de bake."""
    if bpy is None:
        return None
    img = bpy.data.images.get(name)
    if img is not None:
        try:
            if img.size[0] != resolution or img.size[1] != resolution:
                img.scale(resolution, resolution)
        except Exception:
            pass
    else:
        try:
            img = bpy.data.images.new(name, width=resolution, height=resolution,
                                      alpha=alpha, float_buffer=float_buffer)
        except Exception as exc:
            log.error("No se pudo crear la imagen %s: %s", name, exc)
            return None
    if img is None:
        return None
    try:
        _set_colorspace(img, colorspace)
    except Exception:
        pass
    try:
        img.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    try:
        img.filepath_raw = ""
    except Exception:
        pass
    return img


def _set_colorspace(img: Any, colorspace: str) -> None:
    """Fija el espacio de color aceptando los nombres de 4.x y 5.x."""
    cs = getattr(img, "colorspace_settings", None)
    if cs is None:
        return
    candidates = [colorspace]
    if colorspace == "Non-Color":
        candidates += ["Non-Color", "Linear", "Raw"]
    elif colorspace == "sRGB":
        candidates += ["sRGB", "sRGB OETF"]
    for name in candidates:
        try:
            cs.name = name
            return
        except Exception:
            continue
    try:
        cs.name = "Non-Color"
    except Exception:
        pass


def prepare_bake(context: Any, obj: Any, style: Any, settings: Any,
                 map_keys: Sequence[str]) -> Optional[BakeContext]:
    """
    Deja todo listo para bakear: motor, UVs, imágenes y material temporal.

    Devuelve ``None`` si algo impide bakear (y deja el aviso en el log).
    """
    if bpy is None or obj is None:
        return None
    bc = BakeContext()
    bc.obj = obj
    bc.style = style
    bc.settings = settings
    bc.maps = [m for m in map_keys if m in MAPS]
    if not bc.maps:
        log.warning("No hay ningún mapa seleccionado para bakear")
        return None

    scene = context.scene
    engine = getattr(settings, "engine", "unity")
    resolution = int(getattr(settings, "resolution", "4096"))
    prefix = (getattr(settings, "prefix", "") or "").strip() or clean_name(obj.name)

    # --- motor de render ---------------------------------------------------
    bc.prev_engine = scene.render.engine
    if scene.render.engine != "CYCLES":
        try:
            scene.render.engine = "CYCLES"
        except Exception as exc:
            log.error("No se pudo activar Cycles (necesario para bakear): %s", exc)
            return None
        bc.warnings.append("Se cambió el motor a Cycles para poder bakear.")
    if not hasattr(scene, "cycles"):
        log.error("Cycles no está disponible en este Blender")
        return None

    # --- UVs ---------------------------------------------------------------
    from . import uv as uvmod

    if not uvmod.has_uv(obj):
        ok = uvmod.ensure_uv(obj, margin_angle=getattr(_prefs(), "uv_margin_angle", 66.0)
                             if _prefs() else 66.0)
        if not ok:
            log.error(T("El objeto necesita UVs") + " y no se pudieron crear")
            return None
        bc.warnings.append("Se creó un mapa UV con Smart UV Project.")
    quality = uvmod.check_uv_quality(obj, resolution)
    for w in quality.get("warnings", []):
        bc.warnings.append(w)
    if quality.get("outside", 0):
        uvmod.pack_islands(obj, margin=max(0.005, getattr(settings, "margin", 16) / resolution))

    # --- imágenes ----------------------------------------------------------
    keys = list(bc.maps)
    need_orm = bool(getattr(settings, "pack_channels", True)) and \
        bool(getattr(settings, "export_orm", True)) and \
        _channels_available(settings, keys)
    if need_orm and "orm" not in keys:
        keys.append("orm")
    bc.maps = keys

    for key in keys:
        cfg = MAPS[key]
        name = image_name(prefix, key, engine, resolution)
        img = get_or_create_image(name, resolution,
                                  colorspace=cfg["colorspace"],
                                  float_buffer=bool(cfg["float"]),
                                  alpha=(key == "alpha"))
        if img is None:
            bc.errors.append(f"No se pudo crear la imagen de {cfg['label']}")
            continue
        bc.images[key] = img

    if not bc.images:
        log.error("No se pudo crear ninguna imagen de bake")
        return None

    # --- material de bake --------------------------------------------------
    master = assembler.get_master_group(obj)
    if master is None:
        mat = assembler.build_material(obj, style)
        master = assembler.get_master_group(obj)
    if master is None:
        log.error("No existe el grupo maestro: genera el material primero")
        return None
    bc.master_group = master

    bake_mat = _create_bake_material(context, bc, prefix, resolution, need_orm)
    if bake_mat is None:
        log.error("No se pudo crear el material de bake")
        return None
    bc.bake_material = bake_mat

    # --- ajustes de Cycles -------------------------------------------------
    _save_and_apply_cycles_settings(context, bc, settings)

    return bc


def _channels_available(settings: Any, keys: Sequence[str]) -> bool:
    """El ORM sólo tiene sentido si hay oclusión y rugosidad."""
    return "ao" in keys and "roughness" in keys


def clean_name(name: str) -> str:
    """Nombre de fichero seguro (sin rutas, espacios ni caracteres prohibidos)."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in name)
    return out.strip().replace(" ", "_") or "PCM"


def _prefs() -> Any:
    try:
        from .preferences import get_prefs

        return get_prefs()
    except Exception:
        return None


def _create_bake_material(context: Any, bc: BakeContext, prefix: str,
                          resolution: int, need_orm: bool) -> Optional[Any]:
    """
    Material temporal con el grupo maestro + un nodo de imagen por mapa.

    Estructura::

        Group (maestro) ── Base Color / Roughness / ... ──┐
                                                          ├── Emission ── Output
        Image Texture (activo) <──────────────────────────┘
    """
    name = f"{BAKE_MATERIAL_PREFIX}{prefix}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        try:
            mat.user_clear()
        except Exception:
            pass
        try:
            bpy.data.materials.remove(mat)
        except Exception:
            pass
    mat = bpy.data.materials.new(name)
    if mat is None:
        return None
    mat.use_nodes = True
    tree = mat.node_tree
    for n in list(tree.nodes):
        try:
            tree.nodes.remove(n)
        except Exception:
            pass

    b = Builder(tree)
    group_node = b.add("ShaderNodeGroup", name="PCM_Master",
                       label="Material PCM")
    if group_node is None:
        return None
    try:
        group_node.node_tree = bc.master_group
    except Exception as exc:
        log.error("No se pudo conectar el grupo maestro al material de bake: %s", exc)
        return None
    group_node.location = (-1400, 0)

    emission = b.add("ShaderNodeEmission", name="PCM_BakeEmission",
                     label="Emisión de bake")
    if emission is not None:
        compat.set_sock(emission, "Strength", 1.0)
        emission.location = (200, 0)
    bc.emission = emission

    output = b.add("ShaderNodeOutputMaterial", name="PCM_BakeOutput")
    if output is not None:
        try:
            output.is_active_output = True
        except Exception:
            pass
        output.location = (500, 0)
        if emission is not None:
            b.link(out_socket(emission, "Emission", 0), in_socket(output, "Surface"))
    bc.output = output

    # un nodo de imagen por mapa
    row = 0
    for key, img in bc.images.items():
        node = b.add("ShaderNodeTexImage", name=f"PCM_Img_{key}",
                     label=MAPS[key]["label"])
        if node is None:
            continue
        try:
            node.image = img
        except Exception as exc:
            log.error("No se pudo asignar la imagen a %s: %s", key, exc)
            continue
        _set_node_colorspace(node, MAPS[key]["colorspace"])
        node.location = (-200, 300 - row * 300)
        try:
            node.select = False
            node.hide = False
        except Exception:
            pass
        bc.image_nodes[key] = node
        row += 1

    # --- cableado por canal -------------------------------------------------
    # Cada mapa se bakea de una forma distinta; el operador llama a
    # ``_route_channel`` antes de cada paso.
    bc.channel_nodes = {}
    if need_orm and "orm" in bc.image_nodes:
        _build_orm_router(b, bc, group_node)

    # asignar el material al objeto en un slot temporal
    try:
        slots = list(getattr(obj, "material_slots", ()))
        bc.prev_slot_index = len(slots)
        obj.data.materials.append(mat)
        # y hacerlo activo
        try:
            obj.active_material_index = bc.prev_slot_index
        except Exception:
            pass
    except Exception as exc:
        log.error("No se pudo añadir el material de bake al objeto: %s", exc)
        return None
    return mat


def _set_node_colorspace(node: Any, colorspace: str) -> None:
    img = getattr(node, "image", None)
    if img is not None:
        _set_colorspace(img, colorspace)


def _build_orm_router(b: Builder, bc: BakeContext, group_node: Any) -> None:
    """
    Construye el enrutado del mapa ORM (O en R, R en G, M en B).

    Se hace con nodos, no tocando píxeles: es más rápido y no depende de numpy.
    """
    combine = b.add("ShaderNodeCombineColor", name="PCM_ORM_Combine",
                    label="ORM (R=AO, G=Rough, B=Metal)")
    if combine is None:
        combine = b.add("ShaderNodeCombineRGB", name="PCM_ORM_Combine")
    if combine is None:
        bc.warnings.append("No se pudo construir el enrutado ORM; se omite.")
        return
    combine.location = (-500, -1400)
    ao = out_socket(group_node, "Ambient Occlusion")
    rough = out_socket(group_node, "Roughness")
    metal = out_socket(group_node, "Metallic")

    if ao is not None:
        b.link(ao, in_socket(combine, "Red", 0))
    else:
        _set_input(b, combine, ("Red", 0), 1.0)
    if rough is not None:
        b.link(rough, in_socket(combine, "Green", 1))
    else:
        _set_input(b, combine, ("Green", 1), 0.5)
    if metal is not None:
        b.link(metal, in_socket(combine, "Blue", 2))
    else:
        _set_input(b, combine, ("Blue", 2), 0.0)
    bc.channel_nodes["orm"] = out_socket(combine, "Color", "Vector", 0)


def _set_input(b: Builder, node: Any, names: Sequence[Any], value: float) -> None:
    s = in_socket(node, *names)
    if s is None:
        return
    try:
        s.default_value = float(value)
    except Exception:
        pass


def _save_and_apply_cycles_settings(context: Any, bc: BakeContext,
                                    settings: Any) -> None:
    """Guarda los ajustes actuales y aplica los de bake."""
    scene = context.scene
    cscene = getattr(scene, "cycles", None)
    cbk = getattr(scene.render, "bake", None)
    if cscene is None or cbk is None:
        return
    bc.prev_samples = getattr(cscene, "samples", None)
    bc.prev_denoise = getattr(cscene, "use_denoising", None)
    bc.prev_dicing = getattr(cscene, "dicing_rate", None)
    bc.prev_offline_dicing = getattr(cscene, "offline_dicing_rate", None)
    bc.prev_max_subdiv = getattr(cscene, "max_subdivisions", None)
    bc.prev_adaptive = getattr(cscene, "use_adaptive_subdivision", None)
    bc.prev_margin = getattr(cbk, "margin", None)
    bc.prev_margin_type = getattr(cbk, "margin_type", None)
    bc.prev_use_clear = getattr(cbk, "use_clear", None)
    bc.prev_normal_space = getattr(cbk, "normal_space", None)
    try:
        bc.prev_resolution = (scene.render.resolution_x, scene.render.resolution_y)
    except Exception:
        bc.prev_resolution = None

    try:
        cscene.samples = max(1, int(getattr(settings, "samples", 64)))
    except Exception:
        pass
    try:
        cscene.use_denoising = bool(getattr(settings, "use_denoise", True))
    except Exception:
        pass
    try:
        cscene.use_adaptive_subdivision = True
        cscene.dicing_rate = max(0.05, float(getattr(settings, "dicing_rate", 0.8)))
    except Exception:
        pass
    try:
        cbk.margin = max(0, int(getattr(settings, "margin", 16)))
        cbk.margin_type = getattr(settings, "margin_type", "EXTEND")
        cbk.use_clear = True
        cbk.normal_space = "TANGENT"
    except Exception:
        pass
    # la resolución de render no afecta al bake, pero la dejamos coherente
    try:
        res = _resolution_from_settings(settings)
        scene.render.resolution_x = res
        scene.render.resolution_y = res
    except Exception:
        pass


def _resolution_from_settings(settings: Any) -> int:
    try:
        return int(getattr(settings, "resolution", "4096"))
    except Exception:
        return 4096


# ---------------------------------------------------------------------------
# Enrutado de canales
# ---------------------------------------------------------------------------

def _route_channel(bc: BakeContext, key: str) -> Optional[str]:
    """
    Deja el material de bake preparado para el mapa ``key``.

    Devuelve el ``bake_type`` de Cycles que hay que usar, o ``None`` si el mapa
    no se puede bakear.
    """
    cfg = MAPS[key]
    method = cfg["method"]
    tree = getattr(bc.bake_material, "node_tree", None)
    if tree is None:
        return None
    group_node = tree.nodes.get("PCM_Master")
    emission = bc.emission
    if group_node is None or emission is None:
        return None

    # desconectar todo lo anterior y dejar la fuerza a 1.0 (bake lineal exacto)
    for sock in list(emission.inputs):
        for l in list(getattr(sock, "links", ())):
            try:
                tree.links.remove(l)
            except Exception:
                pass
    _set_input(bc_builder(tree), emission, ("Strength", 1), 1.0)

    if method == "normal":
        # Bake NORMAL nativo de Cycles: no necesita enrutado, sólo que el
        # material exista y el nodo de imagen esté activo.
        _activate_image_node(bc, key)
        _set_surface_to_holding(tree, bc)
        return "NORMAL"

    if method == "normal_overlay":
        normal = out_socket(group_node, "Normal")
        if normal is None:
            bc.errors.append("El grupo maestro no expone la normal de detalle")
            return None
        encoded = _encode_normal(bc_builder(tree), normal)
        b = bc_builder(tree)
        b.link(encoded, in_socket(emission, "Color", 0))
        _set_surface_emission(tree, bc)
        _activate_image_node(bc, key)
        return "EMIT"

    if method == "ao":
        # AO nativo de Cycles (oclusión geométrica real) multiplicado por la
        # cavidad procedural que aporta el material.
        ao_socket = out_socket(group_node, "Ambient Occlusion")
        b = bc_builder(tree)
        ao_node = b.add("ShaderNodeAmbientOcclusion", name="PCM_BakeAO",
                        label="AO de Cycles")
        if ao_node is not None:
            try:
                ao_node.samples = 32
            except Exception:
                pass
            try:
                ao_node.only_local = False
            except Exception:
                pass
            compat.set_sock(ao_node, "Distance", 0.05)
            ao_out = out_socket(ao_node, "AO", "Color", 0)
            final = ao_out
            if ao_socket is not None:
                final = b.math("MULTIPLY", ao_out, ao_socket, label="AO × cavidad")
            if final is not None:
                sep = b.add("ShaderNodeSeparateColor", name="PCM_AOSep")
                if sep is not None:
                    b.link(final, in_socket(sep, "Color", 0))
                    b.link(out_socket(sep, "Red", 0), in_socket(emission, "Color", 0))
                else:
                    b.link(final, in_socket(emission, "Color", 0))
        _set_surface_emission(tree, bc)
        _activate_image_node(bc, key)
        return "EMIT"

    if method == "emit_color":
        col = out_socket(group_node, "Emission Color")
        strength = out_socket(group_node, "Emission Strength")
        b = bc_builder(tree)
        if col is None:
            bc.warnings.append("El material no tiene canal emisivo; se omite.")
            return None
        if strength is not None:
            mul = b.math("MULTIPLY", col, strength, label="Emisivo × fuerza")
            b.link(mul, in_socket(emission, "Color", 0))
        else:
            b.link(col, in_socket(emission, "Color", 0))
        _set_surface_emission(tree, bc)
        _activate_image_node(bc, key)
        return "EMIT"

    if method == "orm":
        src = bc.channel_nodes.get("orm")
        if src is None:
            bc.warnings.append("No hay enrutado ORM; se omite el mapa empaquetado.")
            return None
        b = bc_builder(tree)
        b.link(src, in_socket(emission, "Color", 0))
        _set_surface_emission(tree, bc)
        _activate_image_node(bc, key)
        return "EMIT"

    if method == "emit":
        chan = cfg["channel"]
        src = out_socket(group_node, chan) if chan else None
        b = bc_builder(tree)
        if src is None:
            if chan == "Alpha":
                # sin alfa explícito: todo opaco
                v = b.value(1.0, label="Alfa")
                b.link(v, in_socket(emission, "Color", 0))
            else:
                bc.warnings.append(f"El material no expone «{chan}»; se omite.")
                return None
        else:
            b.link(src, in_socket(emission, "Color", 0))
        _set_surface_emission(tree, bc)
        _activate_image_node(bc, key)
        return "EMIT"

    bc.errors.append(f"Método de bake desconocido para {key}")
    return None


_builders: Dict[int, Builder] = {}


def bc_builder(tree: Any) -> Builder:
    """Un Builder por árbol, reutilizado entre pasos."""
    key = id(tree)
    b = _builders.get(key)
    if b is None or b.tree is not tree:
        b = Builder(tree)
        _builders[key] = b
    return b


def _activate_image_node(bc: BakeContext, key: str) -> None:
    """Marca el nodo de imagen del mapa como activo y seleccionado."""
    node = bc.image_nodes.get(key)
    tree = getattr(bc.bake_material, "node_tree", None)
    if node is None or tree is None:
        return
    try:
        for n in tree.nodes:
            n.select = False
        node.select = True
        tree.nodes.active = node
    except Exception as exc:
        log.debug("No se pudo activar el nodo de imagen %s: %s", key, exc)


def _set_surface_emission(tree: Any, bc: BakeContext) -> None:
    """Conecta la emisión a la salida de superficie."""
    if bc.emission is None or bc.output is None:
        return
    b = bc_builder(tree)
    b.link(out_socket(bc.emission, "Emission", 0), in_socket(bc.output, "Surface"))
    _clear_displacement(tree, bc)


def _set_surface_to_holding(tree: Any, bc: BakeContext) -> None:
    """
    Para el bake ``NORMAL`` la superficie debe ser el shader real del modelo:
    se conecta el grupo maestro a la salida y el desplazamiento si procede.
    """
    if bc.output is None:
        return
    group_node = tree.nodes.get("PCM_Master")
    if group_node is None:
        return
    b = bc_builder(tree)
    b.link(out_socket(group_node, "Surface"), in_socket(bc.output, "Surface"))
    disp = out_socket(group_node, "Displacement")
    disp_in = in_socket(bc.output, "Displacement")
    if disp is not None and disp_in is not None:
        b.link(disp, disp_in)
    _apply_displacement_mode(bc, True)


def _clear_displacement(tree: Any, bc: BakeContext) -> None:
    """Desconecta el desplazamiento para los bakes por emisión."""
    if bc.output is None:
        return
    disp_in = in_socket(bc.output, "Displacement")
    if disp_in is None:
        return
    for l in list(getattr(disp_in, "links", ())):
        try:
            tree.links.remove(l)
        except Exception:
            pass


def _apply_displacement_mode(bc: BakeContext, enable: bool) -> None:
    """Activa/desactiva el desplazamiento del material y la subdivisión."""
    mat = bc.bake_material
    if mat is None:
        return
    try:
        mat.displacement_method = "BOTH" if enable else "BUMP"
    except Exception:
        pass
    try:
        obj = bc.obj
        if obj is None:
            return
        if enable:
            if bc.subdiv_mod is None:
                mod = obj.modifiers.new("PCM_BakeSubdiv", "SUBSURF")
                if mod is not None:
                    try:
                        mod.subdivision_type = "ADAPTIVE"
                    except Exception:
                        pass
                    try:
                        mod.render_levels = 2
                    except Exception:
                        pass
                    try:
                        mod.levels = 0
                    except Exception:
                        pass
                    bc.subdiv_mod = mod
        else:
            if bc.subdiv_mod is not None:
                try:
                    obj.modifiers.remove(bc.subdiv_mod)
                except Exception:
                    pass
                bc.subdiv_mod = None
    except Exception as exc:
        log.debug("No se pudo ajustar la subdivisión: %s", exc)


def _encode_normal(b: Builder, normal: Any) -> Any:
    """
    Codifica una normal tangente ``[-1, 1]`` a color ``[0, 1]``.

    ``color = normal * 0.5 + 0.5`` — la convención OpenGL estándar que esperan
    Unity, Godot y glTF.
    """
    out = b.vector_math("MULTIPLY_ADD", normal, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5),
                        label="Codificar normal")
    if out is None:
        mul = b.vector_math("MULTIPLY", normal, (0.5, 0.5, 0.5), label="×0.5")
        out = b.vector_math("ADD", mul, (0.5, 0.5, 0.5), label="+0.5")
    return out


# ---------------------------------------------------------------------------
# Ejecución de un paso
# ---------------------------------------------------------------------------

def bake_one(context: Any, bc: BakeContext, key: str) -> bool:
    """
    Bakea un mapa concreto.  Devuelve ``True`` si terminó sin errores.

    Es una llamada **bloqueante**: el operador modal la invoca una vez por paso
    y actualiza la barra de progreso entre medias.
    """
    if bpy is None or bc.obj is None:
        return False
    settings = bc.settings
    normal_mode = getattr(settings, "normal_mode", "displaced")

    bake_type = _route_channel(bc, key)
    if bake_type is None:
        return False

    scene = context.scene
    cscene = getattr(scene, "cycles", None)
    cbk = getattr(scene.render, "bake", None)
    if cscene is None or cbk is None:
        bc.errors.append("No se pudo acceder a los ajustes de Cycles")
        return False

    # --- ajustes específicos del paso -------------------------------------
    use_displacement = False
    if key == "normal":
        try:
            cbk.normal_space = "TANGENT"
            cbk.normal_r = "POS_X"
            cbk.normal_g = "POS_Y"
            cbk.normal_b = "POS_Z"
        except Exception:
            pass
        use_displacement = (normal_mode == "displaced")
        _apply_displacement_mode(bc, use_displacement)
        if use_displacement:
            _ensure_adaptive_subdiv(context, bc, settings)
    else:
        _apply_displacement_mode(bc, False)


    # --- seleccionar sólo el objeto a bakear ------------------------------
    prev_selected = _selected_objects(context)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        bc.obj.select_set(True)
        context.view_layer.objects.active = bc.obj
    except Exception as exc:
        log.debug("No se pudo aislar la selección para el bake: %s", exc)

    # --- ejecutar ----------------------------------------------------------
    ok = True
    try:
        bpy.ops.object.bake(type=bake_type, pass_index=0)
    except Exception as exc:
        ok = False
        bc.errors.append(f"El bake de {MAPS[key]['label']} falló: {exc}")
        log.error("object.bake falló para %s: %s", key, exc)

    # --- post-proceso ------------------------------------------------------
    if ok:
        img = bc.images.get(key)
        if img is not None:
            try:
                _post_process(context, bc, key, img)
            except Exception as exc:
                bc.warnings.append(f"Post-proceso de {MAPS[key]['label']}: {exc}")
            try:
                img.update()
            except Exception:
                pass

    # --- restaurar selección ----------------------------------------------
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            try:
                o.select_set(True)
            except Exception:
                pass
        context.view_layer.objects.active = bc.obj
    except Exception:
        pass

    if use_displacement:
        _apply_displacement_mode(bc, False)

    if ok:
        bc.done.append(key)
    return ok


def _selected_objects(context: Any) -> List[Any]:
    try:
        return [o for o in context.selected_objects]
    except Exception:
        return []


def _ensure_adaptive_subdiv(context: Any, bc: BakeContext, settings: Any) -> None:
    """Configura Cycles para subdivisión adaptativa real."""
    cscene = getattr(context.scene, "cycles", None)
    if cscene is None:
        return
    try:
        cscene.use_adaptive_subdivision = True
    except Exception:
        pass
    try:
        # dicing_rate está en unidades de escena por defecto; si el usuario usa
        # píxeles, se interpreta igual.
        cscene.dicing_rate = max(0.05, float(getattr(settings, "dicing_rate", 0.8)))
    except Exception:
        pass
    try:
        cscene.offline_dicing_rate = max(0.05, float(getattr(settings, "dicing_rate", 0.8)))
    except Exception:
        pass
    try:
        cscene.max_subdivisions = max(0, int(getattr(settings, "max_subdivisions", 6)))
    except Exception:
        pass
    if bc.subdiv_mod is not None:
        try:
            bc.subdiv_mod.subdivision_type = "ADAPTIVE"
        except Exception:
            pass
        try:
            bc.subdiv_mod.render_levels = max(1, int(getattr(settings, "max_subdivisions", 6)))
        except Exception:
            pass


def _post_process(context: Any, bc: BakeContext, key: str, img: Any) -> None:
    """Ajustes posteriores: convención de normales, alfa, guardado."""
    settings = bc.settings
    engine = getattr(settings, "engine", "unity")
    convention = getattr(settings, "normal_convention", None) or \
        normal_convention_for_engine(engine)

    if key in ("normal", "normal_overlay") and convention == "directx":
        # DirectX usa el verde invertido respecto a OpenGL.
        try:
            img.invert(invert_r=False, invert_g=True, invert_b=False,
                       invert_a=False)
        except TypeError:
            # firma antigua
            try:
                img.invert(invert_r=False, invert_g=True, invert_b=False)
            except Exception as exc:
                bc.warnings.append(
                    f"No se pudo invertir el verde de {MAPS[key]['label']}: {exc}")
        except Exception as exc:
            bc.warnings.append(
                f"No se pudo invertir el verde de {MAPS[key]['label']}: {exc}")

    # Unity espera "Smoothness" (1 - roughness) si se usa el Mask Map estándar;
    # dejamos la rugosidad tal cual porque es lo que pide el shader de HDRP/URP
    # configurable, y lo documentamos en el export.
    try:
        img.pack()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------

def finish_bake(context: Any, bc: Optional[BakeContext], *,
                restore: bool = True) -> None:
    """Restaura el estado original y retira el material temporal de bake."""
    if bpy is None or bc is None:
        return
    scene = context.scene
    obj = bc.obj

    # quitar el modificador temporal
    _apply_displacement_mode(bc, False)

    # quitar el slot temporal del material de bake
    try:
        if obj is not None and bc.prev_slot_index >= 0:
            mats = getattr(obj.data, "materials", None)
            if mats is not None and bc.prev_slot_index < len(mats):
                mats.pop(index=bc.prev_slot_index, update_data=True)
    except Exception as exc:
        log.debug("No se pudo retirar el material de bake: %s", exc)

    # restaurar el material activo
    try:
        if obj is not None:
            for i, slot in enumerate(getattr(obj, "material_slots", ())):
                m = getattr(slot, "material", None)
                if m is not None and m.name.startswith(assembler.MATERIAL_PREFIX) \
                        and not m.name.startswith(BAKE_MATERIAL_PREFIX):
                    obj.active_material_index = i
                    break
    except Exception:
        pass

    if not restore:
        return

    # restaurar ajustes de Cycles
    cscene = getattr(scene, "cycles", None)
    cbk = getattr(scene.render, "bake", None)
    if cscene is not None:
        if bc.prev_samples is not None:
            try:
                cscene.samples = bc.prev_samples
            except Exception:
                pass
        if bc.prev_denoise is not None:
            try:
                cscene.use_denoising = bc.prev_denoise
            except Exception:
                pass
        if bc.prev_adaptive is not None:
            try:
                cscene.use_adaptive_subdivision = bc.prev_adaptive
            except Exception:
                pass
        if bc.prev_dicing is not None:
            try:
                cscene.dicing_rate = bc.prev_dicing
            except Exception:
                pass
        if getattr(bc, "prev_offline_dicing", None) is not None:
            try:
                cscene.offline_dicing_rate = bc.prev_offline_dicing
            except Exception:
                pass
        if bc.prev_max_subdiv is not None:
            try:
                cscene.max_subdivisions = bc.prev_max_subdiv
            except Exception:
                pass
    if cbk is not None:
        for attr, value in (("margin", bc.prev_margin),
                            ("margin_type", bc.prev_margin_type),
                            ("use_clear", bc.prev_use_clear),
                            ("normal_space", bc.prev_normal_space)):
            if value is not None:
                try:
                    setattr(cbk, attr, value)
                except Exception:
                    pass
    if bc.prev_engine is not None:
        try:
            scene.render.engine = bc.prev_engine
        except Exception:
            pass
    if bc.prev_resolution is not None:
        try:
            scene.render.resolution_x, scene.render.resolution_y = bc.prev_resolution
        except Exception:
            pass

    # borrar el material de bake (las imágenes se conservan: son el resultado)
    try:
        mat = bc.bake_material
        if mat is not None:
            try:
                mat.user_clear()
            except Exception:
                pass
            bpy.data.materials.remove(mat)
    except Exception as exc:
        log.debug("No se pudo borrar el material de bake: %s", exc)


def bake_summary(bc: BakeContext) -> str:
    """Texto resumen para el reporte final."""
    ok = ", ".join(MAPS[k]["label"] for k in bc.done) or "—"
    msg = f"{T('Listo')}: {ok}"
    if bc.errors:
        msg += f" · {len(bc.errors)} {T('Errores').lower()}"
    if bc.warnings:
        msg += f" · {len(bc.warnings)} {T('Advertencias').lower()}"
    return msg
