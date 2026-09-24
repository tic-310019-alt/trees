# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
Mock de árboles de nodos de Blender para ejecutar las recetas de PCM Studio
fuera de Blender.

El objetivo es **correr de verdad** cada receta procedural (piel, ojos, pelaje,
escamas…) y detectar dos clases de fallo que un simple ``import`` no ve:

1. Errores de Python (``NameError``, ``AttributeError``, dereferenciar ``None``).
2. **Cadenas de enumeración inválidas** — p. ej. ``node.operation = "ARCTAN"``
   (lo correcto es ``ARCTANGENT``).  En Blender eso lanza, ``shaderkit`` lo
   captura y lo deja pasar, y el nodo se queda en su valor por defecto: el
   material sale *mal* pero *sin error visible*.  Aquí esas asignaciones se
   validan contra los conjuntos reales de Blender 5.2 y se anotan como aviso.

Los sockets se crean de forma dinámica y permisiva (Blender tiene cientos de
tipos de nodo con decenas de sockets cada uno; replicarlos exactos no compensa).
Lo que se valida con precisión son los **enums**, que es donde se esconden los
bugs silenciosos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Conjuntos de enumeración autorizados (Blender 5.2)
# ---------------------------------------------------------------------------

MATH_OPS = {
    "ADD", "SUBTRACT", "MULTIPLY", "MULTIPLY_ADD", "DIVIDE", "POWER",
    "LOGARITHM", "SQRT", "INVERSE_SQRT", "ABSOLUTE", "EXPONENT", "MINIMUM",
    "MAXIMUM", "LESS_THAN", "GREATER_THAN", "SIGN", "COMPARE", "SMOOTH_MIN",
    "SMOOTH_MAX", "ROUND", "FLOOR", "CEIL", "TRUNC", "FRACT", "MODULO",
    "TRUNCATED_MODULO", "FLOORED_MODULO", "WRAP", "SNAP", "PINGPONG", "SINE",
    "COSINE", "TANGENT", "ARCSINE", "ARCCOSINE", "ARCTANGENT", "ARCTAN2",
    "HYPOTENUSE", "RADIANS", "DEGREES", "SINH", "COSH", "TANH", "NEGATE",
}

VECTOR_OPS = {
    "ADD", "SUBTRACT", "MULTIPLY", "MULTIPLY_ADD", "DIVIDE", "CROSS_PRODUCT",
    "DOT_PRODUCT", "PROJECT", "REFLECT", "REFRACT", "FACEFORWARD", "LENGTH",
    "DISTANCE", "NORMALIZE", "ABSOLUTE", "POWER", "SIGN", "MINIMUM", "MAXIMUM",
    "FLOOR", "CEIL", "FRACT", "MODULO", "WRAP", "SNAP", "SINE", "COSINE",
    "TANGENT", "ARCSINE", "ARCCOSINE", "ARCTANGENT", "ARCTAN2", "TO_RADIANS",
    "TO_DEGREES", "MULTIPLY_BY_SCALE", "SMOOTH_MIN", "SMOOTH_MAX",
}

MIXRGB_BLEND = {
    "MIX", "DARKEN", "MULTIPLY", "BURN", "LIGHTEN", "SCREEN", "DODGE", "ADD",
    "OVERLAY", "SOFT_LIGHT", "LINEAR_LIGHT", "DIFFERENCE", "SUBTRACT",
    "DIVIDE", "HUE", "SATURATION", "COLOR", "VALUE",
}

MIX_BLEND = MIXRGB_BLEND | {"REPLACE"}

MIX_DATA_TYPE = {"FLOAT", "INT", "VECTOR", "COLOR", "RGBA", "SHADER"}

MAPRANGE_INTERP = {"LINEAR", "STEPPED_LINEAR", "SMOOTHSTEP", "SMOOTHERSTEP"}

COLOR_MODE = {"RGB", "HSV", "HSL", "XYZ"}

NORMALMAP_SPACE = {"TANGENT", "OBJECT", "WORLD"}

MAPPING_VECTOR_TYPE = {"TEXTURE", "POINT", "VECTOR", "NORMAL"}

SSS_METHOD = {"RANDOM_WALK", "RANDOM_WALK_SKIN", "BURLEY", "CUBIC", "GAUSSIAN",
              "PRINCIPLED", "PRINCIPLED_RANDOM_WALK"}

BSDF_DISTRIBUTION = {"GGX", "MULTI_GGX", "ASHIKHMIN_SHIRLEY"}

RAMP_INTERP = {"B_SPLINE", "LINEAR", "CARDINAL", "EASE", "CONSTANT"}

#: (bl_idname, attr) -> conjunto válido.  ``None`` como bl_idname = cualquiera.
_ENUM_RULES: List[Tuple[Optional[str], str, Any]] = [
    ("ShaderNodeMath", "operation", MATH_OPS),
    ("ShaderNodeVectorMath", "operation", VECTOR_OPS),
    ("ShaderNodeMixRGB", "blend_type", MIXRGB_BLEND),
    ("ShaderNodeMix", "blend_type", MIX_BLEND),
    ("ShaderNodeMix", "data_type", MIX_DATA_TYPE),
    ("ShaderNodeMapRange", "interpolation_type", MAPRANGE_INTERP),
    ("ShaderNodeSeparateColor", "mode", COLOR_MODE),
    ("ShaderNodeCombineColor", "mode", COLOR_MODE),
    ("ShaderNodeNormalMap", "space", NORMALMAP_SPACE),
    ("ShaderNodeMapping", "vector_type", MAPPING_VECTOR_TYPE),
    ("ShaderNodeBsdfPrincipled", "subsurface_method", SSS_METHOD),
    ("ShaderNodeBsdfPrincipled", "distribution", BSDF_DISTRIBUTION),
]

# Avisos detectados (enums inválidos).  El test los inspecciona al final.
VIOLATIONS: List[str] = []


def _note(msg: str) -> None:
    VIOLATIONS.append(msg)


def reset_violations() -> None:
    VIOLATIONS.clear()


# ---------------------------------------------------------------------------
# mathutils mínimo y mutable
# ---------------------------------------------------------------------------

class Vector:
    """Vector mutable (Blender lo es; el fallback de shaderkit no)."""

    __slots__ = ("_v",)

    def __init__(self, seq: Any = (0.0, 0.0, 0.0)) -> None:
        if isinstance(seq, (int, float)):
            seq = (seq, seq, seq)
        self._v = [float(x) for x in seq]

    def __len__(self) -> int:
        return len(self._v)

    def __getitem__(self, i: Any) -> Any:
        return self._v[i]

    def __setitem__(self, i: Any, v: Any) -> None:
        self._v[i] = float(v)

    def __iter__(self):
        return iter(self._v)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Vector({self._v})"

    @property
    def x(self) -> float:
        return self._v[0]

    @property
    def y(self) -> float:
        return self._v[1] if len(self._v) > 1 else 0.0

    @property
    def z(self) -> float:
        return self._v[2] if len(self._v) > 2 else 0.0

    @property
    def length(self) -> float:
        return sum(c * c for c in self._v) ** 0.5

    def normalized(self) -> "Vector":
        L = self.length or 1.0
        return Vector([c / L for c in self._v])

    def dot(self, other: "Vector") -> float:
        return sum(a * b for a, b in zip(self._v, other._v))

    def __sub__(self, other: "Vector") -> "Vector":
        return Vector([a - b for a, b in zip(self._v, other._v)])

    def __add__(self, other: "Vector") -> "Vector":
        return Vector([a + b for a, b in zip(self._v, other._v)])

    def __mul__(self, s: float) -> "Vector":
        return Vector([a * s for a in self._v])


class Color(Vector):
    """Color mutable RGBA."""

    def __init__(self, seq: Any = (0.0, 0.0, 0.0, 1.0)) -> None:
        super().__init__(seq)
        while len(self._v) < 4:
            self._v.append(1.0)

    @property
    def r(self) -> float:
        return self._v[0]

    @property
    def g(self) -> float:
        return self._v[1]

    @property
    def b(self) -> float:
        return self._v[2]


# ---------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------

def _infer_socket_type(name: str) -> str:
    n = (name or "").lower()
    if n in {"color", "base color", "tint", "emission color", "sheen tint",
             "specular tint", "coat tint", "subsurface color", "color1",
             "color2", "a_color", "b_color", "result_color"}:
        return "NodeSocketColor"
    if n in {"vector", "normal", "position", "location", "rotation", "scale",
             "tangent", "direction", "center", "coordinates", "reflection"}:
        return "NodeSocketVector"
    if n in {"shader", "bsdf", "surface", "volume", "displacement"}:
        return "NodeSocketShader"
    return "NodeSocketFloat"


def _default_for(socket_type: str) -> Any:
    if socket_type == "NodeSocketColor":
        return Color((0.8, 0.8, 0.8, 1.0))
    if socket_type == "NodeSocketVector":
        return Vector((0.0, 0.0, 0.0))
    if socket_type == "NodeSocketBool":
        return False
    if socket_type == "NodeSocketInt":
        return 0
    if socket_type == "NodeSocketString":
        return ""
    if socket_type == "NodeSocketShader":
        return None
    return 0.0


class MockSocket:
    def __init__(self, name: str, socket_type: str, in_out: str = "INPUT") -> None:
        self.name = name
        self.type = socket_type
        self.bl_idname = socket_type
        self.identifier = name.replace(" ", "_")
        self.in_out = in_out
        self.links: List[Any] = []
        self.is_linked = False
        self.description = ""
        self.min_value: Any = None
        self.max_value: Any = None
        self.hide = False
        self.enabled = True
        self._default = _default_for(socket_type)

    @property
    def default_value(self) -> Any:
        return self._default

    @default_value.setter
    def default_value(self, value: Any) -> None:
        cur = self._default
        if isinstance(cur, Vector):
            if isinstance(value, (int, float)):
                for i in range(len(cur)):
                    cur[i] = value
            else:
                seq = list(value)
                for i in range(min(len(cur), len(seq))):
                    cur[i] = float(seq[i])
            return
        if self.type == "NodeSocketBool":
            self._default = bool(value)
        elif self.type == "NodeSocketInt":
            self._default = int(value)
        elif self.type == "NodeSocketString":
            self._default = str(value)
        elif self.type == "NodeSocketShader":
            self._default = value
        else:
            try:
                self._default = float(value)
            except Exception:
                self._default = value

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MockSocket {self.in_out} {self.name}:{self.type}>"


class MockSocketList:
    """Lista de sockets que crea dinámicamente los que se pidan por nombre."""

    def __init__(self, in_out: str) -> None:
        self._items: List[MockSocket] = []
        self._in_out = in_out

    def _find(self, key: Any) -> Optional[MockSocket]:
        if isinstance(key, int):
            return self._items[key] if 0 <= key < len(self._items) else None
        for s in self._items:
            if s.name == key or s.identifier == key:
                return s
        return None

    def __contains__(self, key: Any) -> bool:
        # Blender "completo": un nodo tiene todos sus sockets.  Si se pregunta
        # por un nombre que aún no existe, se crea (permisivo) y se responde
        # True, igual que ``out_socket``/``principal_socket`` esperan.  Para
        # índices enteros se respeta el tamaño real.
        if isinstance(key, int):
            return 0 <= key < len(self._items)
        self._ensure(str(key))
        return True

    def _ensure(self, name: str) -> MockSocket:
        s = self._find(name)
        if s is None:
            s = MockSocket(name, _infer_socket_type(name), self._in_out)
            self._items.append(s)
        return s

    def __getitem__(self, key: Any) -> MockSocket:
        if isinstance(key, int):
            found = self._find(key)
            if found is None:
                raise IndexError(key)
            return found
        return self._ensure(str(key))

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        # Una colección de sockets es un objeto válido aunque esté vacía (los
        # sockets se crean al pedirlos).  Sin esto, ``getattr(n,"outputs") or ()``
        # de shaderkit la convertiría en una tupla vacía y fallaría todo.
        return True

    def new(self, socket_type: str, name: str) -> MockSocket:
        s = MockSocket(name, socket_type, self._in_out)
        self._items.append(s)
        return s

    def remove(self, s: MockSocket) -> None:
        try:
            self._items.remove(s)
        except ValueError:
            pass

    def clear(self) -> None:
        self._items.clear()


# ---------------------------------------------------------------------------
# ColorRamp / Curves
# ---------------------------------------------------------------------------

class MockRampElement:
    def __init__(self, position: float = 0.5) -> None:
        self.position = position
        self.color = Color((0.5, 0.5, 0.5, 1.0))
        self.alpha = 1.0


class MockRampElements:
    def __init__(self) -> None:
        self._items = [MockRampElement(0.0), MockRampElement(1.0)]

    def new(self, position: float) -> MockRampElement:
        el = MockRampElement(position)
        self._items.append(el)
        self._items.sort(key=lambda e: e.position)
        return el

    def remove(self, el: MockRampElement) -> None:
        try:
            self._items.remove(el)
        except ValueError:
            pass

    def __getitem__(self, i: Any) -> MockRampElement:
        return self._items[i]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class MockColorRamp:
    def __init__(self) -> None:
        self.elements = MockRampElements()
        self._interpolation = "LINEAR"
        self.color_mode = "RGB"
        self.hue_interpolation = "NEAR"

    @property
    def interpolation(self) -> str:
        return self._interpolation

    @interpolation.setter
    def interpolation(self, value: str) -> None:
        if value not in RAMP_INTERP:
            _note(f"ColorRamp.interpolation inválido: {value!r}")
            raise ValueError(f"ColorRamp.interpolation inválido: {value!r}")
        self._interpolation = value


class MockCurvePoint:
    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self._loc = (x, y)

    @property
    def location(self) -> Tuple[float, float]:
        return self._loc

    @location.setter
    def location(self, value: Tuple[float, float]) -> None:
        self._loc = (float(value[0]), float(value[1]))

    @property
    def handle_type(self) -> str:
        return "AUTO"


class MockCurvePoints:
    def __init__(self) -> None:
        self._items = [MockCurvePoint(0.0, 0.0), MockCurvePoint(1.0, 1.0)]

    def new(self, x: float, y: float) -> MockCurvePoint:
        p = MockCurvePoint(x, y)
        self._items.append(p)
        self._items.sort(key=lambda p: p.location[0])
        return p

    def remove(self, p: MockCurvePoint) -> None:
        try:
            self._items.remove(p)
        except ValueError:
            pass

    def __getitem__(self, i: Any) -> MockCurvePoint:
        return self._items[i]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class MockCurve:
    def __init__(self) -> None:
        self.points = MockCurvePoints()


class MockCurves:
    def __init__(self) -> None:
        self._items = [MockCurve() for _ in range(4)]  # RGB, R, G, B

    def __getitem__(self, i: Any) -> MockCurve:
        return self._items[i]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class MockMapping:
    def __init__(self) -> None:
        self.curves = MockCurves()

    def update(self) -> None:
        return None

    def initialize(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Sockets reales por tipo de nodo (Blender 5.2)
# ---------------------------------------------------------------------------
#
# Se siembran para que la resolución de sockets de ``shaderkit`` (único vs.
# ambiguo por índice) se ejercite de verdad.  Lo crítico son Math y VectorMath,
# cuyas entradas comparten nombre y sólo se distinguen por posición.

NODE_SOCKETS: Dict[str, Tuple[List[str], List[str]]] = {
    "ShaderNodeMath": (["Value", "Value", "Value"], ["Value"]),
    "ShaderNodeVectorMath": (["Vector", "Vector"], ["Vector"]),
    "ShaderNodeMixRGB": (["Fac", "Color1", "Color2"], ["Color"]),
    "ShaderNodeMix": (["Factor", "A", "B", "A_Color", "B_Color"],
                      ["Result", "Result_Color"]),
    "ShaderNodeMapRange": (["Value", "From Min", "From Max", "To Min", "To Max",
                            "Steps"], ["Result"]),
    "ShaderNodeClamp": (["Value", "Min", "Max"], ["Result"]),
    "ShaderNodeBump": (["Strength", "Midlevel", "Height", "Normal"], ["Normal"]),
    "ShaderNodeNormalMap": (["Strength", "Color"], ["Normal"]),
    "ShaderNodeValToRGB": (["Fac"], ["Color"]),
    "ShaderNodeRGBCurve": (["Fac", "Color"], ["Color"]),
    "ShaderNodeSeparateColor": (["Color"], ["Red", "Green", "Blue"]),
    "ShaderNodeCombineColor": (["Red", "Green", "Blue"], ["Color"]),
    "ShaderNodeSeparateRGB": (["Color"], ["R", "G", "B"]),
    "ShaderNodeCombineRGB": (["R", "G", "B"], ["Color"]),
    "ShaderNodeSeparateXYZ": (["Vector"], ["X", "Y", "Z"]),
    "ShaderNodeCombineXYZ": (["X", "Y", "Z"], ["Vector"]),
    "ShaderNodeTexCoord": ([], ["Generated", "Normal", "Object", "Camera",
                                "Window", "Reflection", "UV"]),
    "ShaderNodeMapping": (["Vector", "Location", "Rotation", "Scale"], ["Vector"]),
    "ShaderNodeUVMap": ([], ["UV"]),
    "ShaderNodeValue": ([], ["Value"]),
    "ShaderNodeRGB": ([], ["Color"]),
    "ShaderNodeTexImage": (["Vector"], ["Color", "Alpha"]),
    "ShaderNodeEmission": (["Color", "Strength"], ["Emission"]),
    "ShaderNodeBsdfPrincipled": (
        ["Base Color", "Subsurface Weight", "Subsurface Radius",
         "Subsurface Scale", "Subsurface IOR", "Subsurface Anisotropy",
         "Metallic", "Specular IOR Level", "Specular Tint", "Roughness",
         "Anisotropic", "Anisotropic Rotation", "Tangent", "Transmission Weight",
         "IOR", "Diffuse Roughness", "Thin Wall", "Thin Film Thickness",
         "Thin Film IOR", "Coat Weight", "Coat Roughness", "Coat IOR",
         "Coat Tint", "Coat Normal", "Sheen Weight", "Sheen Roughness",
         "Sheen Tint", "Emission Color", "Emission Strength", "Alpha", "Normal"],
        ["BSDF"]),
    "ShaderNodeOutputMaterial": (["Surface", "Displacement", "Volume"], []),
    "ShaderNodeAmbientOcclusion": (["Color", "Distance", "Normal"],
                                   ["AO", "Normal"]),
    "ShaderNodeBevel": (["Strength", "Vector", "Normal"], ["Normal"]),
    "ShaderNodeNewGeometry": ([], ["Position", "Normal", "Tangent", "True Normal",
                                   "Incoming", "Parametric", "Backfacing",
                                   "Pointiness"]),
    "ShaderNodeAttribute": ([], ["Color", "Fac", "Vector", "Alpha"]),
    "ShaderNodeBrightContrast": (["Color", "Bright", "Contrast"], ["Color"]),
    "ShaderNodeHueSaturation": (["Hue", "Saturation", "Value", "Fac", "Color"],
                                ["Color"]),
    "ShaderNodeInvert": (["Fac", "Color"], ["Color"]),
    "ShaderNodeVectorRotate": (["Vector", "Center", "Axis", "Angle"], ["Vector"]),
    "ShaderNodeLightFalloff": (["Strength"], ["Linear", "Constant", "Quadratic"]),
    "ShaderNodeTexNoise": (["Vector", "W", "Scale", "Detail", "Roughness",
                            "Lacunarity", "Distortion"], ["Fac", "Color"]),
    "ShaderNodeTexVoronoi": (["Vector", "W", "Scale", "Detail", "Roughness",
                               "Lacunarity", "Randomness"],
                             ["Color", "Distance", "Fac", "Position", "Normal",
                              "Radius"]),
    "ShaderNodeTexWave": (["Vector", "Scale", "Distortion", "Detail",
                           "Detail Scale", "Detail Roughness", "Phase Offset"],
                          ["Fac", "Color"]),
}


# ---------------------------------------------------------------------------
# Nodo
# ---------------------------------------------------------------------------

class MockNode:
    def __init__(self, bl_idname: str, name: str = "") -> None:
        object.__setattr__(self, "bl_idname", bl_idname)
        object.__setattr__(self, "_name", name or bl_idname)
        self.label = ""
        self.location = (0.0, 0.0)
        self.hide = False
        self.width_hidden = 140
        self.parent = None
        self.use_custom_color = False
        self.color = (0.6, 0.6, 0.6)
        self.shrink = False
        self.text_size = 12
        self.inputs = MockSocketList("INPUT")
        self.outputs = MockSocketList("OUTPUT")
        # sembrar sockets reales del tipo de nodo (si se conocen)
        seed = NODE_SOCKETS.get(bl_idname)
        if seed:
            for nm in seed[0]:
                self.inputs.new(_infer_socket_type(nm), nm)
            for nm in seed[1]:
                self.outputs.new(_infer_socket_type(nm), nm)
        self.select = False
        self.is_active_output = False
        # attrs de nodo que shaderkit/bake tocan directamente
        self.use_clamp = False
        self.invert = False
        self.samples = 16
        self.only_local = False
        self.operation = "ADD"
        self.blend_type = "MIX"
        self.data_type = "FLOAT"
        self.interpolation_type = "LINEAR"
        self.mode = "RGB"
        self.space = "TANGENT"
        self.vector_type = "TEXTURE"
        self.subsurface_method = "RANDOM_WALK"
        self.distribution = "GGX"
        self._color_ramp = MockColorRamp()
        self._mapping = MockMapping()

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        object.__setattr__(self, "_name", value)

    @property
    def color_ramp(self) -> MockColorRamp:
        return self._color_ramp

    @property
    def mapping(self) -> MockMapping:
        return self._mapping

    def __setattr__(self, key: str, value: Any) -> None:
        if isinstance(value, str) and key in {
                "operation", "blend_type", "data_type", "interpolation_type",
                "mode", "space", "vector_type", "subsurface_method",
                "distribution"}:
            for bl, attr, allowed in _ENUM_RULES:
                if attr == key and (bl is None or bl == self.bl_idname):
                    if value not in allowed:
                        _note(f"{self.bl_idname}.{key} = {value!r} NO es un "
                              f"valor válido (esperado uno de {sorted(allowed)[:4]}…)")
                        raise ValueError(f"{self.bl_idname}.{key} inválido: {value!r}")
        object.__setattr__(self, key, value)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MockNode {self.bl_idname} {self._name!r}>"


class MockNodeList:
    def __init__(self, tree: "MockNodeTree") -> None:
        self._tree = tree
        self._items: List[MockNode] = []

    def new(self, bl_idname: str) -> MockNode:
        n = MockNode(bl_idname, name=f"{bl_idname}_{len(self._items):03d}")
        self._items.append(n)
        return n

    def remove(self, n: MockNode) -> None:
        try:
            self._items.remove(n)
        except ValueError:
            pass

    def get(self, name: str, default: Any = None) -> Any:
        for n in self._items:
            if n.name == name:
                return n
        return default

    def clear(self) -> None:
        self._items.clear()

    def __getitem__(self, key: Any) -> MockNode:
        if isinstance(key, int):
            return self._items[key]
        for n in self._items:
            if n.name == key:
                return n
        raise KeyError(key)

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class MockLink:
    def __init__(self, from_socket: MockSocket, to_socket: MockSocket) -> None:
        self.from_socket = from_socket
        self.to_socket = to_socket


class MockLinkList:
    def __init__(self) -> None:
        self._items: List[MockLink] = []

    def new(self, from_socket: Any, to_socket: Any) -> MockLink:
        lk = MockLink(from_socket, to_socket)
        self._items.append(lk)
        try:
            from_socket.links.append(lk)
            to_socket.links.append(lk)
            to_socket.is_linked = True
        except Exception:
            pass
        return lk

    def remove(self, lk: MockLink) -> None:
        try:
            self._items.remove(lk)
        except ValueError:
            pass

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class MockInterface:
    def __init__(self, tree: "MockNodeTree") -> None:
        self._tree = tree

    def new_socket(self, name: str, in_out: str = "INPUT",
                   socket_type: str = "NodeSocketFloat", **kw: Any) -> MockSocket:
        coll = self._tree.inputs if in_out == "INPUT" else self._tree.outputs
        return coll.new(socket_type, name)


class MockNodeTree:
    """Árbol de nodos simulado (vale para material y para grupo)."""

    def __init__(self, name: str = "MockTree") -> None:
        self.name = name
        self.bl_idname = "ShaderNodeTree"
        self.nodes = MockNodeList(self)
        self.links = MockLinkList()
        self.inputs = MockSocketList("INPUT")
        self.outputs = MockSocketList("OUTPUT")
        self.interface = MockInterface(self)
        self.use_fake_user = False
        self.is_animation = False

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MockNodeTree {self.name} {len(self.nodes)} nodos>"


def new_tree(name: str = "MockTree") -> MockNodeTree:
    return MockNodeTree(name)
