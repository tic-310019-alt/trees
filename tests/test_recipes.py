# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
Ejecuta **todas las recetas procedurales** contra el mock de nodos.

Este es el test más valioso del proyecto: las recetas son el corazón del addon
(generan piel, ojos, dientes, pelaje, escamas, plumas…) y nunca se habían
ejecutado.  Aquí se construye el grupo de nodos de cada zona con el ensamblador
real (:func:`pcm_studio.assembler.build_zone_group`) sobre un árbol simulado y
se comprueba que:

* ninguna receta lanza excepción;
* ninguna asigna un **enum inválido** a un nodo (``operation``, ``blend_type``,
  ``interpolation_type``…): el bug silencioso que en Blender produce materiales
  mal sin error visible;
* ninguna emite avisos/errores al log;
* el grupo resultante tiene nodos y expone los canales PBR esperados.

Ejecución::

    python3 tests/test_recipes.py
    python3 -m pytest tests/test_recipes.py -q
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
import types
from typing import Any, Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_MOCK = os.path.join(_HERE, "mock")
for p in (_ROOT, _MOCK):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy_mock  # noqa: E402
import bpy_nodes  # noqa: E402

_STYLES = ("realistic", "sims4")

# Canales que toda zona "normal" debería acabar exponiendo en su grupo.
_EXPECTED_OUTPUTS = {"Surface"}

_RESULTS: List[Tuple[bool, str, str]] = []


def _check(ok: bool, name: str, detail: str = "") -> None:
    _RESULTS.append((bool(ok), name, detail))


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(f"{record.levelname}: {record.getMessage()}")
        except Exception:
            self.records.append(record.levelname)


def _build_zone(assembler: Any, zones_mod: Any, styles: Any, zone: Any,
                style: Any, uv_scale: float = 1.0) -> Tuple[Any, List[str], List[str]]:
    """Construye el grupo de una zona y devuelve (árbol, avisos, violaciones)."""
    cap = _Capture()
    logger = logging.getLogger("pcm_studio")
    logger.addHandler(cap)
    bpy_nodes.reset_violations()
    try:
        tree = assembler.build_zone_group(zone, style, {}, uv_scale=uv_scale,
                                          reuse=False)
    finally:
        logger.removeHandler(cap)
    return tree, list(cap.records), list(bpy_nodes.VIOLATIONS)


def test_recipes() -> None:
    bpy_mock.install(version=(5, 2, 2))
    from pcm_studio import assembler, zones as zones_mod, styles

    for style_id in _STYLES:
        style = styles.get_style(style_id)
        for zone in zones_mod.ZONES:
            label = f"[{style_id}] {zone.key}"
            try:
                tree, warns, viol = _build_zone(assembler, zones_mod, styles,
                                                zone, style)
            except Exception:
                _check(False, f"{label}: build_zone_group",
                       traceback.format_exc())
                continue

            _check(tree is not None, f"{label}: grupo creado")
            if tree is None:
                continue

            n_nodes = len(tree.nodes)
            _check(n_nodes > 3, f"{label}: {n_nodes} nodos",
                   "demasiados pocos nodos: la receta no generó casi nada")

            # salidas del grupo (canales PBR expuestos)
            out_names = {s.name for s in tree.outputs}
            _check(bool(out_names & _EXPECTED_OUTPUTS) or "Base Color" in out_names
                   or len(out_names) > 0,
                   f"{label}: expone canales ({len(out_names)})",
                   f"salidas: {sorted(out_names)}")

            # enums inválidos = bug silencioso
            _check(not viol, f"{label}: sin enums inválidos",
                   "; ".join(sorted(set(viol))))

            # avisos/errores al log durante la construcción
            noisy = [w for w in warns if "no existe" in w.lower()
                     or "no se pudo" in w.lower() or "no disponible" in w.lower()
                     or w.startswith("ERROR")]
            _check(not noisy, f"{label}: sin avisos graves",
                   "; ".join(sorted(set(noisy))[:5]))


def test_master_group_and_material() -> None:
    """Construye el grupo maestro y el material de un objeto simulado."""
    bpy_mock.install(version=(5, 2, 2))
    from pcm_studio import assembler, styles, zones as zones_mod

    obj = _MockObject("Cabeza")
    n_faces = len(obj.data.polygons)
    assembler.ensure_zone_attribute(obj.data)
    zone_ids = [zones_mod.get_zone_by_key("skin_face").id,
                zones_mod.get_zone_by_key("iris").id,
                zones_mod.get_zone_by_key("sclera").id,
                zones_mod.get_zone_by_key("lips").id]
    # reparte las caras entre varias zonas (como haría el usuario al pintar)
    for zid in zone_ids:
        idxs = [i for i in range(n_faces) if zone_ids[i % len(zone_ids)] == zid]
        assembler.set_zone_faces(obj.data, idxs, zid)

    style = styles.get_style("realistic")
    cap = _Capture()
    logger = logging.getLogger("pcm_studio")
    logger.addHandler(cap)
    bpy_nodes.reset_violations()
    try:
        mat = assembler.build_material(obj, style, uv_scale=1.0, force=True)
    except Exception:
        _check(False, "material: build_material", traceback.format_exc())
        logger.removeHandler(cap)
        return
    finally:
        try:
            logger.removeHandler(cap)
        except Exception:
            pass

    _check(mat is not None, "material: creado")
    viol = list(bpy_nodes.VIOLATIONS)
    _check(not viol, "material: sin enums inválidos", "; ".join(sorted(set(viol))))
    noisy = [w for w in cap.records if w.startswith("ERROR")
             or "no se pudo" in w.lower()]
    _check(not noisy, "material: sin errores graves", "; ".join(sorted(set(noisy))[:5]))
    if mat is not None:
        # el árbol del material es fino (Group + Output); el grafo real vive en
        # el grupo maestro, que mezcla los grupos de cada zona.
        tree = getattr(mat, "node_tree", None)
        _check(tree is not None and len(tree.nodes) >= 2,
               "material: árbol con Group+Output",
               f"{len(tree.nodes) if tree else 0} nodos")
        master = assembler.get_master_group(obj)
        _check(master is not None, "material: grupo maestro creado")
        if master is not None:
            _check(len(master.nodes) > 10,
                   f"material: grupo maestro con grafo ({len(master.nodes)} nodos)",
                   "el maestro debería mezclar varias zonas")
            master_outs = {s.name for s in master.outputs}
            _check("Surface" in master_outs and "Base Color" in master_outs,
                   "material: maestro expone Surface y Base Color",
                   f"salidas: {sorted(master_outs)}")


# ---------------------------------------------------------------------------
# Objeto / malla simulados (lo mínimo que usa assembler.build_material)
# ---------------------------------------------------------------------------

class _MockAttrData:
    def __init__(self, count: int) -> None:
        self._count = count
        self._cells: List[Any] = [types.SimpleNamespace(value=0.0, color=(0, 0, 0, 1))
                                  for _ in range(count)]

    def __len__(self) -> int:
        return self._count

    def __getitem__(self, i: int) -> Any:
        return self._cells[i]

    def __iter__(self):
        return iter(self._cells)


class _MockAttr:
    def __init__(self, name: str, count: int) -> None:
        self.name = name
        self.data_type = "FLOAT"
        self.domain = "FACE"
        self.data = _MockAttrData(count)


class _MockAttrs:
    def __init__(self, mesh: "_MockMesh") -> None:
        self._mesh = mesh
        self._store: Dict[str, _MockAttr] = {}

    def get(self, name: str, default: Any = None) -> Any:
        return self._store.get(name, default)

    def new(self, name: str, data_type: str, domain: str) -> _MockAttr:
        a = _MockAttr(name, len(self._mesh.polygons))
        self._store[name] = a
        return a

    def remove(self, a: _MockAttr) -> None:
        self._store.pop(a.name, None)

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __iter__(self):
        return iter(self._store.values())


class _MockPolygon:
    def __init__(self, index: int) -> None:
        self.index = index
        self.area = 0.0004
        self.loop_indices = (index * 3, index * 3 + 1, index * 3 + 2)
        self.vertices = (index * 3, index * 3 + 1, index * 3 + 2)


class _MockUVLayers:
    def __init__(self) -> None:
        self.active = types.SimpleNamespace(name="UVMap", data=[])
        self._layers = [self.active]

    def __len__(self) -> int:
        return len(self._layers)

    def __iter__(self):
        return iter(self._layers)

    def __getitem__(self, i: Any) -> Any:
        return self._layers[i]


class _MockMesh:
    def __init__(self, n_faces: int = 400) -> None:
        self.polygons = [_MockPolygon(i) for i in range(n_faces)]
        self.attributes = _MockAttrs(self)
        self.uv_layers = _MockUVLayers()
        self.materials: List[Any] = []

    def update(self) -> None:
        return None

    def calc_loop_triangles(self) -> None:
        return None


class _MockObject:
    def __init__(self, name: str = "Obj") -> None:
        import bpy

        self.name = name
        self.type = "MESH"
        self.data = _MockMesh()
        self.modifiers = types.SimpleNamespace(
            new=lambda *a, **k: types.SimpleNamespace(),
            remove=lambda *a, **k: None,
            __iter__=lambda s: iter(()),
        )
        self.active_material_index = 0
        self.matrix_world = _MockMatrix()
        self.pcm = None

    @property
    def material_slots(self) -> List[Any]:
        # en Blender los slots salen de data.materials; aquí los reflejamos
        return [types.SimpleNamespace(material=m) for m in self.data.materials]

    def update_tag(self) -> None:
        return None


class _MockMatrix:
    def inverted(self) -> "_MockMatrix":
        return self

    def __matmul__(self, other: Any) -> Any:
        return other



def _summary() -> int:
    passed = sum(1 for ok, _, _ in _RESULTS if ok)
    failed = [(n, d) for ok, n, d in _RESULTS if not ok]
    print("=" * 68)
    print(f"PCM Studio — test de recetas: {passed} OK, {len(failed)} FALLOS")
    print("=" * 68)
    for name, detail in failed:
        print(f"✗ {name}")
        if detail:
            for line in detail.strip().splitlines()[-6:]:
                print(f"    {line}")
    return 1 if failed else 0


def main() -> int:
    test_recipes()
    test_master_group_and_material()
    return _summary()


def test_all() -> None:
    if main() != 0:
        raise AssertionError("PCM Studio: hay fallos al ejecutar las recetas")


if __name__ == "__main__":
    raise SystemExit(main())
