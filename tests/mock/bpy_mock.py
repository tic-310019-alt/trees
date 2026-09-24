# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
``bpy`` simulado para probar PCM Studio fuera de Blender.

No es un reemplazo del motor: es lo mínimo necesario para **importar y
registrar** el addon bajo CPython normal (3.11), de modo que el cuerpo real de
las clases (``bpy.props.*`` en anotaciones, ``bpy.types.*`` como bases,
``register_class``) se ejecute y revele errores de nombre, de firma o de API
que de otra forma sólo aparecerían dentro de Blender.

Instalar con::

    import bpy_mock
    bpy_mock.install(version=(5, 2, 2))   # simula Blender 5.2
    import pcm_studio                      # ahora ve un ``bpy`` de verdad
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict, List, Optional, Tuple

import bpy_nodes  # noqa: E402  (mismo directorio en sys.path)


# Iconos "conocidos" — suficiente para que ``_icon_exists`` no devuelva siempre
# falso y el dibujado de paneles pueda ejercitarse.
_ICON_ENUM: Dict[str, Any] = {name: name for name in (
    "NONE", "ERROR", "CANCEL", "CHECKMARK", "X", "INFO", "QUESTION", "TEXT",
    "FILE_TEXT", "FILE_FOLDER", "FILE_REFRESH", "FILE_TICK", "FILEBLANK",
    "FILEBROWSER", "EXPORT", "ADD", "TRASH", "WORDWRAP_ON", "WORLD", "LANGUAGE",
    "RENDER_STILL", "RENDER_ANIMATION", "PLAY", "PAINTFACE", "BRUSH_DATA",
    "NODETREE", "NODE", "MATERIAL", "TEXTURE", "MESH_DATA", "OUTLINER_OB_MESH",
    "MOD_UVPROJECT", "UV_FACESEL", "UV_ISLANDSEL", "GROUP_UVS", "GROUP_VCOL",
    "SELECT_SUBTRACT", "SELECT_DIFFERENCE", "SELECT_EXTEND", "ZOOM_IN",
    "ZOOM_OUT", "ZOOM_ALL", "ZOOM_SELECTED", "ZOOM_PREV", "VIEWZOOM", "SPHERE",
    "MESH_UVSPHERE", "ORIENT_NORMAL", "NORMALS_FACE", "MOD_SMOOTH",
    "MOD_SUBSURF", "MOD_DISPLACE", "MOD_MESHDEFORM", "LIGHTPROBE_GRID", "AUTO",
    "RESTRICT_SELECT_OFF", "PENCIL_ACTIVE", "EDITMODE_HLT", "GHOST_ENABLED",
    "GHOST_DISABLED", "SEQUENCE_COLOR", "IMAGE_DATA", "IMAGE_REFERENCE",
    "EMPTY_ARROWS", "SORTTIME", "TIME", "FUND", "RECOVER_LAST", "PREFERENCES",
    "OUTLINER_OB_VOLUME",
)}


# ---------------------------------------------------------------------------
# bpy.props — fábricas de propiedades
# ---------------------------------------------------------------------------

class _PropDef:
    """Representa la definición de una propiedad (lo que devuelve ``IntProperty``)."""

    def __init__(self, kind: str, **kwargs: Any) -> None:
        self.kind = kind
        self.kwargs = kwargs

    def __repr__(self) -> str:  # pragma: no cover - depuración
        return f"<{self.kind} {self.kwargs!r}>"


def _prop_factory(kind: str):
    def factory(**kwargs: Any) -> _PropDef:
        # validación ligera de los argumentos más usados, para cazar typos
        allowed = {
            "name", "description", "default", "min", "max", "soft_min", "soft_max",
            "step", "precision", "subtype", "unit", "size", "items", "options",
            "update", "get", "set", "type", "maxlen", "search", "search_items",
            "override", "attr", "domain", "translate", "id", "password",
        }
        unknown = set(kwargs) - allowed
        if unknown:
            raise TypeError(f"{kind}() got unexpected keyword(s): {unknown}")
        return _PropDef(kind, **kwargs)

    factory.__name__ = kind
    return factory


def _build_props_module() -> types.ModuleType:
    mod = types.ModuleType("bpy.props")
    for kind in ("BoolProperty", "BoolVectorProperty", "IntProperty",
                 "IntVectorProperty", "FloatProperty", "FloatVectorProperty",
                 "StringProperty", "EnumProperty", "PointerProperty",
                 "CollectionProperty"):
        setattr(mod, kind, _prop_factory(kind))
    return mod


# ---------------------------------------------------------------------------
# bpy.types — clases base
# ---------------------------------------------------------------------------

class _RNAParameter:
    def __init__(self, enum_items: Optional[Dict[str, Any]] = None) -> None:
        self.enum_items = enum_items or {}


class _RNAFunction:
    def __init__(self, params: Dict[str, _RNAParameter]) -> None:
        self.parameters = params


class _RNAStruct:
    """Simula ``bl_rna`` con ``functions`` consultables."""

    def __init__(self) -> None:
        self.functions: Dict[str, _RNAFunction] = {
            "prop": _RNAFunction({
                "icon": _RNAParameter(_ICON_ENUM),
            }),
        }


class _BlenderType:
    bl_rna = _RNAStruct()


class Struct(_BlenderType):
    pass


class Operator(_BlenderType):
    bl_idname = ""
    bl_label = ""
    bl_description = ""
    bl_options: Any = set()

    def report(self, level: Any, message: str) -> None:
        _REPORTS.append((tuple(level), message))

    def poll(cls, context: Any) -> bool:  # noqa: N805
        return True

    def execute(self, context: Any) -> Any:
        return {"FINISHED"}


class Panel(_BlenderType):
    bl_idname = ""
    bl_label = ""
    bl_space_type = ""
    bl_region_type = ""
    bl_context = ""
    bl_parent_id = ""
    bl_category = ""
    bl_options: Any = set()


class UIList(_BlenderType):
    bl_idname = ""
    bitflag_visible_item = 1
    layout_type = "DEFAULT"
    filter_name = ""

    def draw_item(self, *args: Any, **kwargs: Any) -> None:
        return None


class Menu(_BlenderType):
    bl_idname = ""

    _appended: List[Any] = []

    @classmethod
    def append(cls, fn: Any) -> None:
        cls._appended.append(fn)

    @classmethod
    def remove(cls, fn: Any) -> None:
        try:
            cls._appended.remove(fn)
        except ValueError:
            pass

    @classmethod
    def draw(cls, context: Any) -> None:
        return None


class PropertyGroup(_BlenderType):
    pass


class AddonPreferences(_BlenderType):
    bl_idname = ""


class Object(Struct):
    def __init__(self, name: str = "Object") -> None:
        self.name = name
        self.type = "MESH"


class Scene(Struct):
    def __init__(self, name: str = "Scene") -> None:
        self.name = name


class UILayout(_BlenderType):
    """Base para los layouts; sólo se usa su ``bl_rna`` para validar iconos."""


class WindowManager(Struct):
    pass


# ---------------------------------------------------------------------------
# Registro de clases
# ---------------------------------------------------------------------------

_REGISTERED: List[Any] = []
_REPORTS: List[Tuple[Tuple[str, ...], str]] = []
_IDNAME_RE = None


def _valid_idname(idname: str) -> bool:
    global _IDNAME_RE
    if _IDNAME_RE is None:
        import re

        _IDNAME_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
    return bool(_IDNAME_RE.match(idname or ""))


def register_class(cls: Any) -> None:
    if cls in _REGISTERED:
        raise ValueError(f"already registered: {getattr(cls, '__name__', cls)}")
    name = getattr(cls, "__name__", repr(cls))
    if issubclass(cls, Operator):
        idname = getattr(cls, "bl_idname", "")
        if not _valid_idname(idname):
            raise ValueError(f"{name}: bl_idname inválido {idname!r}")
        if not getattr(cls, "bl_label", ""):
            raise ValueError(f"{name}: falta bl_label")
    elif issubclass(cls, Panel):
        if not getattr(cls, "bl_label", ""):
            raise ValueError(f"{name}: falta bl_label")
        for attr in ("bl_space_type", "bl_region_type"):
            if not getattr(cls, attr, ""):
                raise ValueError(f"{name}: falta {attr}")
    elif issubclass(cls, (UIList, Menu)):
        # Blender deriva bl_idname del nombre de clase si no se especifica.
        if not getattr(cls, "bl_idname", ""):
            cls.bl_idname = name
    _REGISTERED.append(cls)


def unregister_class(cls: Any) -> None:
    if cls not in _REGISTERED:
        raise ValueError(f"not registered: {getattr(cls, '__name__', cls)}")
    _REGISTERED.remove(cls)


def user_resource(kind: str = "CONFIG", **kwargs: Any) -> str:
    import os

    return os.path.join(os.path.expanduser("~"), ".config", "blender", kind.lower())


def register_classes_factories() -> None:  # pragma: no cover - compatibilidad
    return None


# ---------------------------------------------------------------------------
# bpy.ops / bpy.data / bpy.context — mínimos (no se usan en el registro)
# ---------------------------------------------------------------------------

class _OpsNamespace:
    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            _REPORTS.append((("OPS",), f"{name}({kwargs})"))
            return {"FINISHED"}

        return call


class _DataCollection(dict):
    def get(self, key: Any, default: Any = None) -> Any:
        return dict.get(self, key, default)


class _NodeGroups(dict):
    """``bpy.data.node_groups`` con ``.new(nombre, tipo)`` real."""

    def new(self, name: str, idtype: str = "ShaderNodeTree") -> Any:
        tree = bpy_nodes.new_tree(name)
        self[name] = tree
        return tree

    def get(self, key: Any, default: Any = None) -> Any:
        return dict.get(self, key, default)

    def remove(self, tree: Any, **kw: Any) -> None:
        self.pop(getattr(tree, "name", None), None)


class _Material:
    """Material simulado con ``node_tree`` perezoso y props personalizadas."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.use_nodes = False
        self.blend_method = "OPAQUE"
        self.shadow_method = "OPAQUE"
        self.use_backface_culling = False
        self.show_transparent_back = True
        self.displacement_method = "BUMP"
        self.use_fake_user = False
        self.users = 1
        self._node_tree: Any = None
        self._custom: Dict[str, Any] = {}

    @property
    def node_tree(self) -> Any:
        if self._node_tree is None:
            self._node_tree = bpy_nodes.new_tree(self.name)
        return self._node_tree

    @node_tree.setter
    def node_tree(self, value: Any) -> None:
        self._node_tree = value

    def __setitem__(self, k: str, v: Any) -> None:
        self._custom[k] = v

    def __getitem__(self, k: str) -> Any:
        return self._custom[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self._custom.get(k, default)

    def __contains__(self, k: str) -> bool:
        return k in self._custom

    def user_clear(self) -> None:
        self.users = 0


class _Materials(dict):
    def new(self, name: str) -> Any:
        m = _Material(name)
        self[name] = m
        return m

    def get(self, key: Any, default: Any = None) -> Any:
        return dict.get(self, key, default)

    def remove(self, m: Any, **kw: Any) -> None:
        self.pop(getattr(m, "name", None), None)


class _Data:
    def __init__(self) -> None:
        self.images = _DataCollection()
        self.materials = _Materials()
        self.node_groups = _NodeGroups()
        self.texts = _DataCollection()
        self.filepath = ""


class _Context:
    def __init__(self) -> None:
        self.scene = None
        self.active_object = None
        self.selected_objects = []
        self.mode = "OBJECT"
        self.preferences = None
        self.window_manager = None
        self.view_layer = None
        self.screen = None


# ---------------------------------------------------------------------------
# Ensamblaje del módulo ``bpy``
# ---------------------------------------------------------------------------

# Clases de nodo Shader presentes en Blender 5.2 (para que compat.has_node las
# encuentre y no salte el aviso de "nodos esenciales faltantes").
_SHADER_NODE_TYPES = (
    "ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial", "ShaderNodeTexNoise",
    "ShaderNodeTexVoronoi", "ShaderNodeBump", "ShaderNodeNormalMap",
    "ShaderNodeMixRGB", "ShaderNodeMath", "ShaderNodeVectorMath",
    "ShaderNodeValToRGB", "ShaderNodeRGBCurve", "ShaderNodeTexCoord",
    "ShaderNodeUVMap", "ShaderNodeMapping", "ShaderNodeGroup",
    "ShaderNodeMixShader", "ShaderNodeTexImage", "ShaderNodeEmission",
    "ShaderNodeAttribute", "ShaderNodeNewGeometry", "ShaderNodeBevel",
    "ShaderNodeAmbientOcclusion", "ShaderNodeVertexColor",
    "ShaderNodeSeparateColor", "ShaderNodeCombineColor", "ShaderNodeMapRange",
    "ShaderNodeClamp", "ShaderNodeValue", "ShaderNodeRGB", "ShaderNodeMix",
    "ShaderNodeVectorRotate", "ShaderNodeSqueeze", "ShaderNodeTexWave",
    "ShaderNodeTexGabor", "ShaderNodeTexWhiteNoise", "ShaderNodeBsdfVelvet",
    "ShaderNodeBsdfSheen", "ShaderNodeBsdfGlossy", "ShaderNodeBsdfMetallic",
    "ShaderNodeRadialTiling", "ShaderNodeBsdfHairPrincipled",
    "ShaderNodeSeparateRGB", "ShaderNodeCombineRGB", "ShaderNodeGroupInput",
    "ShaderNodeGroupOutput", "ShaderNodeSubsurfScattering", "ShaderNodeBsdfGlass",
    "ShaderNodeBsdfTransparent", "ShaderNodeBsdfDiffuse", "ShaderNodeInvert",
    "ShaderNodeBrightContrast", "ShaderNodeHueSaturation", "ShaderNodeLightFalloff",
    "ShaderNodeAmbientOcclusion", "ShaderNodeDisplacement",
    "ShaderNodeVectorDisplacement", "ShaderNodeVectorCurve", "ShaderNodeCombineXYZ",
    "ShaderNodeSeparateXYZ", "ShaderNodeCurveFloat", "ShaderNodeCurveVec",
)

def build(version: Tuple[int, int, int] = (5, 2, 2)) -> types.ModuleType:
    """Construye y devuelve (sin instalar) un módulo ``bpy`` simulado."""
    bpy = types.ModuleType("bpy")

    props = _build_props_module()

    btypes = types.ModuleType("bpy.types")
    for cls in (Struct, Operator, Panel, UIList, Menu, PropertyGroup,
                AddonPreferences, Object, Scene, UILayout, WindowManager):
        setattr(btypes, cls.__name__, cls)
    # nodos Shader conocidos
    for node_name in _SHADER_NODE_TYPES:
        setattr(btypes, node_name, type(node_name, (Struct,), {}))

    # Blender "completo": cualquier clase de nodo (ShaderNode*/Node*/Compositor*)
    # existe.  Así compat.has_node devuelve True y las recetas ejercitan todos
    # sus caminos en vez de degradarse por nodos "ausentes".
    _NODE_PREFIXES = ("ShaderNode", "Node", "Compositor", "Texture")

    def _types_getattr(name: str) -> Any:
        if name.startswith(_NODE_PREFIXES):
            cls = type(name, (Struct,), {})
            setattr(btypes, name, cls)   # caché
            return cls
        raise AttributeError(name)

    btypes.__getattr__ = _types_getattr  # PEP 562
    # menús a los que ui.py hace append
    for menu_name in ("VIEW_3D_MT_object_context_menu",
                      "VIEW_3D_MT_select_mesh_context_menu",
                      "NODE_EDITOR_MT_editor_menus"):
        m = type(menu_name, (Menu,), {"bl_idname": menu_name.lower()})
        setattr(btypes, menu_name, m)

    utils = types.ModuleType("bpy.utils")
    utils.register_class = register_class
    utils.unregister_class = unregister_class
    utils.user_resource = user_resource
    utils.register_classes_factories = register_classes_factories

    app = types.ModuleType("bpy.app")
    app.version = version
    app.version_string = ".".join(str(x) for x in version)
    app.build_branch = "main"
    # bpy.app.handlers / timers / online_access
    handlers = types.SimpleNamespace(depsgraph_update_post=[], load_post=[])
    app.handlers = handlers
    app.timers = types.SimpleNamespace(register=lambda *a, **k: None)
    app.online_access = False

    path_mod = types.ModuleType("bpy.path")
    path_mod.abspath = lambda p: p

    bpy.props = props
    bpy.types = btypes
    bpy.utils = utils
    bpy.app = app
    bpy.path = path_mod
    bpy.ops = _OpsNamespace()
    bpy.data = _Data()
    bpy.context = _Context()

    # mathutils mutable (Vector/Color) para que shaderkit use los reales
    mu = types.ModuleType("mathutils")
    mu.Vector = bpy_nodes.Vector
    mu.Color = bpy_nodes.Color
    mu.Quaternion = type("Quaternion", (), {})
    mu.Matrix = type("Matrix", (), {})
    sys.modules["mathutils"] = mu
    bpy.mathutils = mu

    # submódulos importables: ``import bpy.props`` / ``from bpy.types import X``
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = props
    sys.modules["bpy.types"] = btypes
    sys.modules["bpy.utils"] = utils
    sys.modules["bpy.app"] = app
    sys.modules["bpy.path"] = path_mod
    return bpy


def install(version: Tuple[int, int, int] = (5, 2, 2)) -> types.ModuleType:
    """Construye e instala ``bpy`` en ``sys.modules``."""
    reset()
    return build(version)


def reset() -> None:
    """Limpia el estado entre pruebas."""
    _REGISTERED.clear()
    _REPORTS.clear()


def registered() -> List[Any]:
    return list(_REGISTERED)


def reports() -> List[Tuple[Tuple[str, ...], str]]:
    return list(_REPORTS)
