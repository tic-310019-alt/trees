# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Kit de construcción de árboles de nodos.

Toda la generación de materiales pasa por aquí.  El objetivo es doble:

1. **Robustez**: ningún ``node.inputs["Nombre"]`` a pelo.  Los sockets se
   resuelven por nombre lógico con alias y por ``identifier``, y si un socket
   no existe en la versión de Blender en uso la operación se ignora en vez de
   lanzar una excepción.  Así el addon sobrevive a renombrados futuros.

2. **Legibilidad del resultado**: los nodos se colocan en columnas, se agrupan
   en *frames* con título y se etiquetan en el idioma del usuario.  Un material
   generado por PCM Studio se puede abrir y entender.

Además construye los materiales como **grupos de nodos** (``NodeGroup``) con
sus parámetros expuestos como entradas de grupo: eso da al usuario una lista
limpia de sliders por zona en lugar de un bosque de 300 nodos.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from . import compat
from .log import log

try:  # pragma: no cover - fuera de Blender no existe
    import bpy
    from mathutils import Color, Vector
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

    class Vector(tuple):  # type: ignore[no-redef]
        def __new__(cls, seq=()):
            return super().__new__(cls, tuple(seq))

    class Color(tuple):  # type: ignore[no-redef]
        def __new__(cls, seq=(0.0, 0.0, 0.0)):
            return super().__new__(cls, tuple(seq))


__all__ = (
    "Builder",
    "GroupBuilder",
    "NodeOut",
    "in_socket",
    "out_socket",
    "link",
    "set_default",
    "SOCKET_TYPES",
)


# ---------------------------------------------------------------------------
# Tipos de socket conocidos (para entradas/salidas de grupos de nodos)
# ---------------------------------------------------------------------------

SOCKET_TYPES = {
    "FLOAT": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "BOOL": "NodeSocketBool",
    "VECTOR": "NodeSocketVector",
    "COLOR": "NodeSocketColor",
    "SHADER": "NodeSocketShader",
    "STRING": "NodeSocketString",
}


# ---------------------------------------------------------------------------
# Resolución de sockets
# ---------------------------------------------------------------------------

def _items(node: Any, direction: str):
    return getattr(node, direction, ()) or ()


def _sockets_matching(items: Any, name: str) -> List[Any]:
    """
    Sockets de ``items`` cuyo ``name``/``identifier`` coincide con ``name`` o con
    alguno de sus alias del Principled.

    Devuelve una **lista** (puede haber varios) porque algunos nodos —Math y
    VectorMath— tienen varias entradas con el *mismo* nombre ("Value", "Vector")
    que sólo se distinguen por índice.
    """
    out: List[Any] = []
    candidates = [name]
    candidates.extend(compat.PRINCIPLED_ALIASES.get(name, ()))
    idents = {str(c).replace(" ", "_") for c in candidates}
    idents.add(str(name).replace(" ", "_"))
    try:
        for s in items:
            sname = getattr(s, "name", None)
            sid = getattr(s, "identifier", "")
            if sname in candidates or sid in idents or sid == name:
                out.append(s)
    except Exception:
        pass
    return out


def in_socket(node: Any, *names: str) -> Optional[Any]:
    """
    Devuelve el socket de entrada que coincida con alguno de ``names``.

    Acepta nombres visibles ("Base Color"), identificadores ("Subsurface_Weight")
    e índices enteros.  **Regla de resolución** (crítica para la corrección):

    * Si un nombre coincide con **un único** socket, se usa ese socket y se
      ignora el índice.  Así ``("Height", 1)`` devuelve el socket *Height* del
      nodo Bump aunque esté en la posición 2: el índice que acompaña al nombre es
      sólo una pista y a veces no corresponde.
    * Si un nombre coincide con **varios** sockets (Math/VectorMath, donde todas
      las entradas se llaman igual), se usa el **índice** para desambiguar.  Sin
      esto, ``("Value", 1)`` devolvería ``Value[0]`` y el segundo operando de un
      ``MULTIPLY``/``ADD`` sobrescribiría al primero, dejando ``Value[1]`` en su
      valor por defecto y dando un resultado incorrecto.
    * Si ningún nombre coincide, se intenta el índice como respaldo.
    """
    if node is None:
        return None
    inputs = _items(node, "inputs")
    ints = [n for n in names if isinstance(n, int)]
    strs = [n for n in names if not isinstance(n, int)]

    for name in strs:
        matches = _sockets_matching(inputs, name)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # nombre ambiguo → desambiguar por el índice explícito
            if ints:
                try:
                    return inputs[ints[0]]
                except Exception:
                    pass
            return matches[0]

    # ningún nombre coincidió: usar el índice como respaldo
    for idx in ints:
        try:
            s = inputs[idx]
            if s is not None:
                return s
        except Exception:
            continue
    return None


def out_socket(node: Any, *names: str) -> Optional[Any]:
    """Equivalente a :func:`in_socket` para salidas (misma regla de resolución)."""
    if node is None:
        return None
    outputs = _items(node, "outputs")
    ints = [n for n in names if isinstance(n, int)]
    strs = [n for n in names if not isinstance(n, int)]

    for name in strs:
        matches = _sockets_matching(outputs, name)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            if ints:
                try:
                    return outputs[ints[0]]
                except Exception:
                    pass
            return matches[0]

    for idx in ints:
        try:
            s = outputs[idx]
            if s is not None:
                return s
        except Exception:
            continue
    # última opción: primera salida
    try:
        if len(outputs):
            return outputs[0]
    except Exception:
        pass
    return None


def set_default(node: Any, socket_names: Union[str, Sequence[str]], value: Any) -> bool:
    """Fija ``default_value``; acepta nombre o tupla de alias. Devuelve éxito."""
    if isinstance(socket_names, str):
        socket_names = (socket_names,)
    s = in_socket(node, *socket_names)
    if s is None:
        return False
    try:
        if isinstance(value, (tuple, list)) and hasattr(s.default_value, "__len__"):
            n = min(len(s.default_value), len(value))
            for i in range(n):
                s.default_value[i] = value[i]
        else:
            s.default_value = value
        return True
    except Exception:
        log.debug("No se pudo fijar %s en %s", socket_names, getattr(node, "name", "?"))
        return False


def link(tree: Any, from_: Any, to: Any) -> bool:
    """Enlaza dos sockets tolerando ``None`` y tipos incompatibles."""
    if from_ is None or to is None:
        return False
    try:
        tree.links.new(from_, to)
        return True
    except Exception as exc:
        log.debug("Link fallido %s -> %s (%s)", from_, to, exc)
        return False


class NodeOut:
    """
    Par ``(nodo, socket)`` cómodo de devolver desde los helpers.

    Se puede usar directamente donde se espera un socket gracias a
    ``__getattr__`` delegando al socket, y como nodo en ``link``.
    """

    __slots__ = ("node", "socket")

    def __init__(self, node: Any, socket_: Any = None):
        self.node = node
        self.socket = socket_ if socket_ is not None else out_socket(node, 0)

    def __getattr__(self, item):
        return getattr(self.socket, item)

    def __repr__(self):  # pragma: no cover - depuración
        name = getattr(self.node, "name", "?")
        sname = getattr(self.socket, "name", "?")
        return f"<NodeOut {name}.{sname}>"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class Builder:
    """Constructor de nodos con placement automático y helpers PBR."""

    #: separación horizontal entre columnas
    COL_STEP = 260
    ROW_STEP = 200

    def __init__(self, tree: Any, label_prefix: str = ""):
        self.tree = tree
        self.label_prefix = label_prefix
        self._x = 0.0
        self._y = 0.0
        self._col_nodes: List[Any] = []
        self.frames: Dict[str, Any] = {}
        self.missing: List[str] = []

    # -- colocación ------------------------------------------------------
    def at(self, x: float, y: float) -> "Builder":
        self._x, self._y = float(x), float(y)
        return self

    def col(self, index: int, row: int = 0) -> "Builder":
        self._x = index * self.COL_STEP
        self._y = -row * self.ROW_STEP
        return self

    def move(self, dx: float, dy: float = 0.0) -> "Builder":
        self._x += dx
        self._y += dy
        return self

    # -- creación --------------------------------------------------------
    def add(self, class_name: str, name: str = "", *, x: Optional[float] = None,
            y: Optional[float] = None, label: str = "", allow_fallback: bool = True,
            hide: bool = False) -> Optional[Any]:
        """
        Crea un nodo.  ``class_name`` es el nombre de la clase Python
        (``"ShaderNodeTexNoise"``).  Si no existe en este Blender se prueba el
        fallback declarado en :data:`compat.NODE_FALLBACKS`.
        """
        target = class_name
        if allow_fallback and not compat.has_node(class_name):
            target = compat.node_class(class_name)
            if target == class_name or not compat.has_node(target):
                if class_name not in self.missing:
                    self.missing.append(class_name)
                    log.warning("PCM Studio: el nodo %s no existe en Blender %s",
                                class_name, compat.BLENDER_VERSION_STR)
                return None
        try:
            node = self.tree.nodes.new(target)
        except Exception as exc:
            if class_name not in self.missing:
                self.missing.append(class_name)
            log.warning("PCM Studio: no se pudo crear %s (%s)", target, exc)
            return None
        node.location = (self._x if x is None else x, self._y if y is None else y)
        if name:
            node.name = name
        if label:
            node.label = label
        if hide:
            node.hide = True
            node.width_hidden = 140
        self._col_nodes.append(node)
        return node

    def frame(self, title: str, *, key: Optional[str] = None) -> Any:
        """Crea (o reutiliza) un frame con título."""
        key = key or title
        existing = self.frames.get(key)
        if existing is not None:
            return existing
        f = self.add("NodeFrame", name=f"PCM_F_{key}")
        if f is None:
            return None
        f.label = title
        f.use_custom_color = True
        f.color = (0.10, 0.12, 0.16)
        f.shrink = True
        f.text_size = 18
        self.frames[key] = f
        return f

    def parent(self, nodes: Iterable[Any], title: str, *, key: Optional[str] = None) -> Any:
        f = self.frame(title, key=key)
        if f is None:
            return None
        for n in nodes:
            if n is not None:
                try:
                    n.parent = f
                except Exception:
                    pass
        return f

    # -- enlaces ---------------------------------------------------------
    def link(self, from_: Any, to: Any) -> bool:
        f = from_.socket if isinstance(from_, NodeOut) else from_
        t = to.socket if isinstance(to, NodeOut) else to
        return link(self.tree, f, t)

    def link_into(self, src: Any, dst_node: Any, *names: str) -> bool:
        return self.link(src, in_socket(dst_node, *names))

    # -- helpers de alto nivel -------------------------------------------
    def math(self, op: str, a: Any = 0.5, b: Any = 0.5, c: Any = 0.0, *,
             label: str = "", use_clamp: bool = False) -> Optional[NodeOut]:
        """
        Nodo *Math*.  ``c`` alimenta la tercera entrada (``Value[2]``), usada por
        ``MULTIPLY_ADD`` (A·B+C) y ``SMOOTH_MIN``/``SMOOTH_MAX``.  Para el resto
        de operaciones la tercera entrada se ignora en Blender, así que fijarla a
        0 no afecta.
        """
        n = self.add("ShaderNodeMath", label=label)
        if n is None:
            return None
        try:
            n.operation = op
        except Exception:
            log.warning("Operación matemática no disponible: %s", op)
        n.use_clamp = bool(use_clamp)
        self._feed(n, ("Value", 0), a)
        self._feed(n, ("Value", 1), b)
        self._feed(n, ("Value", 2), c)
        return NodeOut(n, out_socket(n, "Value", 0))

    def vector_math(self, op: str, a: Any = (0, 0, 0), b: Any = (0, 0, 0),
                    c: Any = (0, 0, 0), *, label: str = "") -> Optional[NodeOut]:
        """
        Nodo *Vector Math*.

        El nodo vectorial sólo tiene **dos** entradas de vector, así que no
        existe un ``MULTIPLY_ADD`` nativo de tres operandos como en el Math
        escalar.  Cuando se pide ``MULTIPLY_ADD`` se descompone en
        ``MULTIPLY(a, b)`` seguido de ``ADD(resultado, c)``, que es exactamente
        A·B+C y funciona en todas las versiones.
        """
        if str(op).upper() == "MULTIPLY_ADD":
            mul = self.vector_math("MULTIPLY", a, b, label=(label + " ·A×B")
                                   if label else "A×B")
            if mul is None:
                return None
            return self.vector_math("ADD", mul, c, label=(label + " ·+C")
                                    if label else "+C")
        n = self.add("ShaderNodeVectorMath", label=label)
        if n is None:
            return None
        try:
            n.operation = op
        except Exception:
            log.warning("Operación vectorial no disponible: %s", op)
        self._feed(n, ("Vector", 0), a)
        self._feed(n, ("Vector", 1), b)
        return NodeOut(n, out_socket(n, "Vector", 0))

    def mix_rgb(self, blend: str, fac: Any = 0.5, a: Any = (0, 0, 0, 1),
                b: Any = (1, 1, 1, 1), *, label: str = "", use_clamp: bool = False
                ) -> Optional[NodeOut]:
        n = self.add("ShaderNodeMixRGB", label=label)
        if n is None:
            return None
        try:
            n.blend_type = blend
        except Exception:
            log.warning("Modo de mezcla no disponible: %s", blend)
        try:
            n.use_clamp = bool(use_clamp)
        except Exception:
            pass
        self._feed(n, ("Fac", "Factor", 0), fac)
        self._feed(n, ("Color1", 1), a)
        self._feed(n, ("Color2", 2), b)
        return NodeOut(n, out_socket(n, "Color", 0))

    def mix(self, data_type: str, blend: str, fac: Any = 0.5, a: Any = 0.0,
            b: Any = 1.0, *, label: str = "", use_clamp: bool = False
            ) -> Optional[NodeOut]:
        """Nodo *Mix* unificado (Blender 3.4+)."""
        n = self.add("ShaderNodeMix", label=label)
        if n is None:
            return None
        try:
            n.data_type = data_type
        except Exception:
            log.warning("data_type no disponible en Mix: %s", data_type)
        try:
            n.blend_type = blend
        except Exception:
            pass
        try:
            n.use_clamp = bool(use_clamp)
        except Exception:
            pass
        self._feed(n, ("Factor", "Fac", 0), fac)
        a_names = ("A", 1) if data_type == "FLOAT" else ("A_Color", "A", 1)
        b_names = ("B", 2) if data_type == "FLOAT" else ("B_Color", "B", 2)
        self._feed(n, a_names, a)
        self._feed(n, b_names, b)
        out_names = ("Result", 0) if data_type == "FLOAT" else ("Result_Color", "Result", 0)
        return NodeOut(n, out_socket(n, *out_names))

    def clamp(self, value: Any, lo: float = 0.0, hi: float = 1.0, *,
              label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeClamp", label=label)
        if n is None:
            # fallback: MapRange lineal con clamp
            return self.map_range(value, 0.0, 1.0, lo, hi, clamp=True, label=label)
        self._feed(n, ("Value", 0), value)
        self._feed(n, ("Min", 1), lo)
        self._feed(n, ("Max", 2), hi)
        return NodeOut(n, out_socket(n, "Result", "Value", 0))

    def map_range(self, value: Any, from_min: Any = 0.0, from_max: Any = 1.0,
                  to_min: Any = 0.0, to_max: Any = 1.0, *,
                  interpolation: str = "LINEAR", clamp: bool = False,
                  label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeMapRange", label=label)
        if n is None:
            return None
        try:
            n.interpolation_type = interpolation
        except Exception:
            pass
        try:
            n.use_clamp = bool(clamp)
        except Exception:
            pass
        self._feed(n, ("Value", 0), value)
        self._feed(n, ("From Min", 1), from_min)
        self._feed(n, ("From Max", 2), from_max)
        self._feed(n, ("To Min", 3), to_min)
        self._feed(n, ("To Max", 4), to_max)
        return NodeOut(n, out_socket(n, "Result", 0))

    def invert(self, fac: Any = 1.0, color: Any = (0, 0, 0, 1), *,
               label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeInvert", label=label)
        if n is None:
            return self.map_range(color, 0.0, 1.0, 1.0, 0.0, clamp=True, label=label)
        self._feed(n, ("Fac", 0), fac)
        self._feed(n, ("Color", 1), color)
        return NodeOut(n, out_socket(n, "Color", 0))

    def color_ramp(self, stops: Sequence[Tuple[float, Sequence[float]]], *,
                   interpolation: str = "LINEAR", label: str = "",
                   extrapolate: bool = False) -> Optional[NodeOut]:
        """
        ``stops`` = secuencia de ``(posición, (r, g, b, a))``.

        Se redimensiona la rampa al número de paradas pedido.
        """
        n = self.add("ShaderNodeValToRGB", label=label)
        if n is None:
            return None
        try:
            ramp = n.color_ramp
            ramp.interpolation = interpolation
            try:
                ramp.interpolation = "B_SPLINE" if interpolation == "B_SPLINE" else interpolation
            except Exception:
                pass
            while len(ramp.elements) < len(stops):
                ramp.elements.new(0.5)
            while len(ramp.elements) > len(stops):
                ramp.elements.remove(ramp.elements[-1])
            for i, (pos, col) in enumerate(stops):
                el = ramp.elements[i]
                el.position = max(0.0, min(1.0, float(pos)))
                for c in range(min(4, len(col))):
                    try:
                        el.color[c] = float(col[c])
                    except Exception:
                        pass
        except Exception as exc:
            log.warning("No se pudo configurar ColorRamp: %s", exc)
        return NodeOut(n, out_socket(n, "Color", 0))

    def rgb_curve(self, points: Sequence[Tuple[float, float]], *,
                  channel: str = "RGB", label: str = "") -> Optional[NodeOut]:
        """Curva de un canal (``RGB``, ``R``, ``G``, ``B`` o ``HUE``)."""
        n = self.add("ShaderNodeRGBCurve", label=label)
        if n is None:
            return None
        try:
            curves = n.mapping.curves
            idx = {"RGB": 0, "R": 1, "G": 2, "B": 3}.get(channel.upper(), 0)
            curve = curves[idx] if idx < len(curves) else curves[0]
            # limpiar puntos intermedios y colocar los nuestros
            while len(curve.points) > 2:
                curve.points.remove(curve.points[1])
            for i, (x, y) in enumerate(points):
                if i == 0:
                    curve.points[0].location = (x, y)
                elif i == 1 and len(curve.points) > 1:
                    curve.points[1].location = (x, y)
                else:
                    curve.points.new(x, y)
            n.mapping.update()
        except Exception as exc:
            log.warning("No se pudo configurar Curves (%s): %s", channel, exc)
        return NodeOut(n, out_socket(n, "Color", 0))

    def _feed(self, node: Any, names: Sequence[Union[str, int]], value: Any) -> None:
        """Si ``value`` es un socket/NodeOut, enlaza; si no, fija default_value."""
        s = in_socket(node, *names)
        if s is None:
            return
        if value is None:
            return
        if isinstance(value, NodeOut):
            link(self.tree, value.socket, s)
            return
        if hasattr(value, "links") and hasattr(value, "name"):  # es un socket
            link(self.tree, value, s)
            return
        if isinstance(value, (tuple, list)) and hasattr(s.default_value, "__len__"):
            n = min(len(s.default_value), len(value))
            for i in range(n):
                try:
                    s.default_value[i] = float(value[i])
                except Exception:
                    try:
                        s.default_value[i] = value[i]
                    except Exception:
                        pass
            return
        try:
            s.default_value = value
        except Exception:
            pass

    # -- utilidades varias ------------------------------------------------
    def reroute(self, src: Any, *, label: str = "") -> Any:
        n = self.add("NodeReroute", label=label)
        if n is None:
            return src
        self.link(src, in_socket(n, "Input", 0))
        return out_socket(n, "Output", 0)

    def value(self, v: float, *, label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeValue", label=label)
        if n is None:
            return None
        self._feed(n, ("Value", 0), float(v))
        return NodeOut(n, out_socket(n, "Value", 0))

    def rgb(self, color: Sequence[float], *, label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeRGB", label=label)
        if n is None:
            return None
        self._feed(n, ("Color", 0), tuple(color))
        return NodeOut(n, out_socket(n, "Color", 0))

    def separate_color(self, src: Any, *, mode: str = "RGB"
                       ) -> Tuple[Optional[NodeOut], Optional[NodeOut], Optional[NodeOut]]:
        n = self.add("ShaderNodeSeparateColor")
        if n is None:
            n = self.add("ShaderNodeSeparateRGB")
        if n is None:
            return None, None, None
        try:
            n.mode = mode
        except Exception:
            pass
        self.link(src, in_socket(n, "Color", 0))
        return (NodeOut(n, out_socket(n, "Red", 0)),
                NodeOut(n, out_socket(n, "Green", 1)),
                NodeOut(n, out_socket(n, "Blue", 2)))

    def combine_color(self, r: Any, g: Any, b: Any, *, mode: str = "RGB"
                      ) -> Optional[NodeOut]:
        n = self.add("ShaderNodeCombineColor")
        if n is None:
            n = self.add("ShaderNodeCombineRGB")
        if n is None:
            return None
        try:
            n.mode = mode
        except Exception:
            pass
        self._feed(n, ("Red", 0), r)
        self._feed(n, ("Green", 1), g)
        self._feed(n, ("Blue", 2), b)
        return NodeOut(n, out_socket(n, "Color", 0))

    def bump(self, height: Any, strength: Any = 0.1, *, distance: Any = 1.0,
             normal: Any = None, invert: bool = False, label: str = ""
             ) -> Optional[NodeOut]:
        n = self.add("ShaderNodeBump", label=label)
        if n is None:
            return None
        n.invert = bool(invert)
        self._feed(n, ("Strength", "Distance", 0), strength)
        self._feed(n, ("Height", 1), height)
        if normal is not None:
            self._feed(n, ("Normal", 2), normal)
        return NodeOut(n, out_socket(n, "Normal", 0))

    def normal_map(self, color: Any, strength: Any = 1.0, *, space: str = "TANGENT",
                   label: str = "") -> Optional[NodeOut]:
        n = self.add("ShaderNodeNormalMap", label=label)
        if n is None:
            return None
        try:
            n.space = space
        except Exception:
            pass
        self._feed(n, ("Strength", 0), strength)
        self._feed(n, ("Color", 1), color)
        return NodeOut(n, out_socket(n, "Normal", 0))

    def output_material(self) -> Optional[Any]:
        for n in self.tree.nodes:
            if getattr(n, "bl_idname", "") == "ShaderNodeOutputMaterial":
                return n
        n = self.add("ShaderNodeOutputMaterial", name="PCM_Output")
        if n is not None:
            try:
                n.is_active_output = True
            except Exception:
                pass
        return n

    def arrange(self, *, x_start: float = 0.0, y_start: float = 0.0) -> None:
        """Coloca en columnas los nodos creados sin posición explícita."""
        col = 0
        row = 0
        for n in self._col_nodes:
            if n is None:
                continue
            n.location = (x_start + col * self.COL_STEP, y_start - row * self.ROW_STEP)
            row += 1
            if row > 8:
                row = 0
                col += 1

    def tidy(self) -> None:
        try:
            if bpy is not None:
                for n in self.tree.nodes:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Constructor de grupos de nodos con parámetros expuestos
# ---------------------------------------------------------------------------

class GroupBuilder(Builder):
    """
    Construye un ``ShaderNodeTree`` usado como grupo, exponiendo parámetros.

    Los parámetros se crean como entradas de grupo y se pueden consultar con
    :meth:`param` para enlazarlos donde haga falta.  Al reconstruir la receta
    los valores por defecto se conservan (se copian del grupo anterior).
    """

    def __init__(self, tree: Any, label_prefix: str = ""):
        super().__init__(tree, label_prefix)
        self._params: Dict[str, Any] = {}
        self._order: List[Tuple[str, str]] = []   # (nombre, tipo)
        self._outputs: Dict[str, Any] = {}

    # -- entradas ---------------------------------------------------------
    def param(self, name: str, kind: str = "FLOAT", default: Any = 0.5, *,
              min_value: Optional[float] = None, max_value: Optional[float] = None,
              description: str = "") -> Any:
        """
        Crea (o recupera) una entrada de grupo y devuelve su socket.

        ``kind`` ∈ FLOAT | INT | BOOL | VECTOR | COLOR | SHADER
        """
        existing = self._params.get(name)
        if existing is not None:
            return existing
        sock_type = SOCKET_TYPES.get(kind.upper())
        if sock_type is None:
            log.warning("Tipo de parámetro desconocido: %s", kind)
            return None
        socket_ = None
        try:
            socket_ = self.tree.interface.new_socket(
                name=name, in_out="INPUT", socket_type=sock_type)
        except Exception:
            # Blender < 4.0
            try:
                socket_ = self.tree.inputs.new(sock_type, name)
            except Exception as exc:
                log.warning("No se pudo crear la entrada %s: %s", name, exc)
                return None
        if socket_ is None:
            return None
        try:
            if description:
                socket_.description = description
        except Exception:
            pass
        try:
            if kind.upper() == "FLOAT":
                if min_value is not None:
                    socket_.min_value = float(min_value)
                if max_value is not None:
                    socket_.max_value = float(max_value)
                if default is not None:
                    socket_.default_value = float(default)
            elif kind.upper() == "INT":
                if min_value is not None:
                    socket_.min_value = int(min_value)
                if max_value is not None:
                    socket_.max_value = int(max_value)
                if default is not None:
                    socket_.default_value = int(default)
            elif kind.upper() == "BOOL":
                socket_.default_value = bool(default)
            elif kind.upper() == "VECTOR":
                socket_.default_value = Vector(default if default is not None else (0, 0, 0))
            elif kind.upper() == "COLOR":
                socket_.default_value = Color(
                    list(default) if default is not None else [0.8, 0.8, 0.8, 1.0])
        except Exception as exc:
            log.debug("default_value de %s no ajustable: %s", name, exc)
        self._params[name] = socket_
        self._order.append((name, kind.upper()))
        return socket_

    def param_default(self, name: str) -> Any:
        s = self._params.get(name)
        if s is None:
            return None
        try:
            return s.default_value
        except Exception:
            return None

    def set_param_default(self, name: str, value: Any) -> bool:
        s = self._params.get(name)
        if s is None:
            return False
        try:
            if isinstance(value, (tuple, list)) and hasattr(s.default_value, "__len__"):
                for i, v in enumerate(value):
                    if i < len(s.default_value):
                        s.default_value[i] = v
            else:
                s.default_value = value
            return True
        except Exception:
            return False

    @property
    def params(self) -> Dict[str, Any]:
        return dict(self._params)

    @property
    def param_names(self) -> List[str]:
        return [n for n, _ in self._order]

    # -- salidas ----------------------------------------------------------
    def output(self, name: str, kind: str = "SHADER") -> Optional[Any]:
        existing = self._outputs.get(name)
        if existing is not None:
            return existing
        sock_type = SOCKET_TYPES.get(kind.upper())
        if sock_type is None:
            return None
        socket_ = None
        try:
            socket_ = self.tree.interface.new_socket(
                name=name, in_out="OUTPUT", socket_type=sock_type)
        except Exception:
            try:
                socket_ = self.tree.outputs.new(sock_type, name)
            except Exception as exc:
                log.warning("No se pudo crear la salida %s: %s", name, exc)
                return None
        if socket_ is not None:
            self._outputs[name] = socket_
        return socket_

    def group_input(self) -> Optional[Any]:
        """Nodo *Group Input* del grupo (crea uno si no existe)."""
        for n in self.tree.nodes:
            if getattr(n, "bl_idname", "") == "NodeGroupInput":
                return n
        return self.add("NodeGroupInput", name="PCM_GroupInput")

    def group_output(self) -> Optional[Any]:
        for n in self.tree.nodes:
            if getattr(n, "bl_idname", "") == "NodeGroupOutput":
                return n
        return self.add("NodeGroupOutput", name="PCM_GroupOutput")

    def feed_param(self, name: str) -> Optional[Any]:
        """Socket de salida del *Group Input* correspondiente al parámetro."""
        gi = self.group_input()
        if gi is None or name not in self._params:
            return None
        return out_socket(gi, name)
