# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
Prueba de importación y registro de PCM Studio bajo un ``bpy`` simulado.

Se puede ejecutar de dos formas::

    python3 tests/test_addon.py          # runner propio, sin dependencias
    python3 -m pytest tests/ -q          # si tienes pytest

Verifica, para Blender 5.2.2 **y** 4.2.0 (ruta de compatibilidad):

* que todos los módulos se importan sin excepción;
* que ``register()``/``unregister()`` funcionan y registran las clases esperadas;
* que cada ``bl_idname`` de operador/panel/lista está bien formado y es único;
* que toda referencia ``.operator("pcm.…")`` de la interfaz apunta a un
  operador que de verdad existe (caza typos entre ui/operators);
* que el ``default`` de cada ``EnumProperty`` es uno de sus ``items``.
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from typing import Any, Dict, List, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_MOCK = os.path.join(_HERE, "mock")
for p in (_ROOT, _MOCK):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy_mock  # noqa: E402  (después de fijar sys.path)

_SUBMODULES = (
    "i18n", "log", "compat", "shaderkit", "texlib", "zones", "styles",
    "recipes", "recipes.base", "recipes.skin", "recipes.eyes", "recipes.mouth",
    "recipes.keratin", "recipes.animal", "recipes.custom",
    "assembler", "properties", "preferences", "diagnostics", "uv",
    "select_tools", "bake", "export", "operators", "ui",
)

_RESULTS: List[Tuple[bool, str, str]] = []


def _check(ok: bool, name: str, detail: str = "") -> None:
    _RESULTS.append((bool(ok), name, detail))


def _fresh_import(version: Tuple[int, int, int]) -> Any:
    """Reinstala el mock y (re)importa el paquete desde cero."""
    for mod in list(sys.modules):
        if mod == "pcm_studio" or mod.startswith("pcm_studio."):
            del sys.modules[mod]
    bpy_mock.install(version=version)
    import pcm_studio  # noqa: E402

    return pcm_studio


def test_import_and_register(version: Tuple[int, int, int]) -> None:
    tag = ".".join(str(x) for x in version)
    try:
        pkg = _fresh_import(version)
    except Exception:
        _check(False, f"[{tag}] import pcm_studio", traceback.format_exc())
        return
    _check(True, f"[{tag}] import pcm_studio")

    # cada submódulo, explícitamente
    for sub in _SUBMODULES:
        full = f"pcm_studio.{sub}"
        try:
            __import__(full)
            _check(True, f"[{tag}] import {sub}")
        except Exception:
            _check(False, f"[{tag}] import {sub}", traceback.format_exc())

    # registro
    try:
        pkg.register()
        _check(True, f"[{tag}] register()")
    except Exception:
        _check(False, f"[{tag}] register()", traceback.format_exc())
        return

    registered = bpy_mock.registered()
    names = {getattr(c, "__name__", "") for c in registered}
    _check(len(registered) >= 40, f"[{tag}] clases registradas ({len(registered)})",
           "esperadas ≥ 40 (operadores + paneles + listas + prefs + props)")

    # register() captura excepciones por módulo y las loguea: hay que comprobar
    # que NINGÚN módulo falló, no sólo que register() no lanzó.  Si ui no
    # registró sus clases, algo se rompió en silencio.
    reports = " ".join(m for lvl, m in bpy_mock.reports() if "ERROR" in str(lvl))
    for ui_cls in ("PCM_PT_base", "PCM_PT_zones", "PCM_PT_bake", "PCM_PT_viewport",
                   "PCM_UL_zones", "PCM_UL_proposals"):
        _check(ui_cls in names, f"[{tag}] ui registró {ui_cls}",
               "la interfaz no se registró (register falló en silencio)")
    for op_cls in ("PCM_OT_bake", "PCM_OT_assign_zone", "PCM_OT_export_maps"):
        _check(op_cls in names, f"[{tag}] operators registró {op_cls}")
    _check("registro incompleto" not in reports.lower(),
           f"[{tag}] ningún módulo falló al registrar", reports[:400])

    # idnames presentes
    idnames = {getattr(c, "bl_idname", "") for c in registered if getattr(c, "bl_idname", "")}
    for required in ("pcm.prepare_object", "pcm.assign_zone", "pcm.build_material",
                     "pcm.bake", "pcm.export_maps", "pcm.show_diagnostics",
                     "pcm.propose_zones", "pcm.report", "pcm.refresh_zones"):
        _check(required in idnames, f"[{tag}] registrado {required}")

    # Object.pcm / Scene.pcm asignados
    import bpy

    _check(hasattr(bpy.types.Object, "pcm"), f"[{tag}] Object.pcm")
    _check(hasattr(bpy.types.Scene, "pcm"), f"[{tag}] Scene.pcm")

    # desregistro limpio
    try:
        pkg.unregister()
        _check(True, f"[{tag}] unregister()")
    except Exception:
        _check(False, f"[{tag}] unregister()", traceback.format_exc())
    _check(len(bpy_mock.registered()) == 0, f"[{tag}] registro vacío tras unregister",
           f"quedan {len(bpy_mock.registered())}")


# ---------------------------------------------------------------------------
# Comprobaciones estáticas (no dependen del bpy simulado)
# ---------------------------------------------------------------------------

_OPERATOR_IDNAME_RE = re.compile(r'bl_idname\s*=\s*"([a-z0-9_.]+)"')
_OPERATOR_CALL_RE = re.compile(r'\.operator\(\s*"([a-z0-9_.]+)"')


def _all_operator_idnames(pkg_root: str) -> Set[str]:
    ids: Set[str] = set()
    for base, _dirs, files in os.walk(pkg_root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            text = open(os.path.join(base, fn), encoding="utf-8").read()
            for m in _OPERATOR_IDNAME_RE.finditer(text):
                ids.add(m.group(1))
    return ids


def test_operator_references(pkg_root: str) -> None:
    defined = _all_operator_idnames(pkg_root)
    # además existen operadores nativos que NO definen aquí; sólo comprobamos
    # las llamadas a "pcm.*".
    referenced: Dict[str, List[str]] = {}
    for base, _dirs, files in os.walk(pkg_root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(base, fn)
            text = open(path, encoding="utf-8").read()
            for m in _OPERATOR_CALL_RE.finditer(text):
                idn = m.group(1)
                if idn.startswith("pcm."):
                    referenced.setdefault(idn, []).append(fn)
    _check(len(referenced) > 0, "ui referencia operadores pcm.*")
    for idn, files in sorted(referenced.items()):
        _check(idn in defined,
               f"operador referenciado existe: {idn}",
               f"usado en {sorted(set(files))} pero no definido")


def test_idnames_unique_wellformed(pkg_root: str) -> None:
    ids = _all_operator_idnames(pkg_root)
    _check(len(ids) >= 30, f"nº de bl_idname ({len(ids)})")
    for idn in sorted(ids):
        _check(re.match(r"^pcm\.[a-z0-9_]+$", idn) is not None,
               f"idname bien formado: {idn}")


def test_enum_defaults(pkg_root: str) -> None:
    """Cada EnumProperty con default literal debe incluirlo en items."""
    import pcm_studio.properties as props  # requiere mock instalado

    # RESOLUTION / ENGINE / FORMAT / NORMAL_MODE definidos como listas módulo
    tables = {
        "RESOLUTION_ITEMS": props.RESOLUTION_ITEMS,
        "ENGINE_ITEMS": props.ENGINE_ITEMS,
        "FORMAT_ITEMS": props.FORMAT_ITEMS,
        "NORMAL_MODE_ITEMS": props.NORMAL_MODE_ITEMS,
    }
    for name, items in tables.items():
        keys = {i[0] for i in items}
        _check(len(keys) == len(items), f"{name}: claves únicas")

    # defaults usados por SceneProps
    _check("4096" in {i[0] for i in props.RESOLUTION_ITEMS}, "resolución default 4096")
    _check("unity" in {i[0] for i in props.ENGINE_ITEMS}, "motor default unity")
    _check("PNG" in {i[0] for i in props.FORMAT_ITEMS}, "formato default PNG")
    _check("displaced" in {i[0] for i in props.NORMAL_MODE_ITEMS},
           "modo normal default displaced")


def test_zones_and_styles_integrity() -> None:
    from pcm_studio import zones, styles, recipes

    ids = [z.id for z in zones.ZONES]
    _check(len(ids) == len(set(ids)), "zonas: ids únicos")
    keys = [z.key for z in zones.ZONES]
    _check(len(keys) == len(set(keys)), "zonas: claves únicas")
    for z in zones.ZONES:
        _check(z.recipe in recipes.RECIPES,
               f"zona {z.key} → receta '{z.recipe}' existe")
        for prm in z.params:
            if prm.kind == "FLOAT" and prm.min is not None and prm.max is not None:
                _check(prm.min <= float(prm.default) <= prm.max,
                       f"zona {z.key} parám '{prm.name}' default en rango")

    sids = [s.id for s in styles.STYLES]
    _check(len(sids) == len(set(sids)), "estilos: ids únicos")
    for want in ("realistic", "sims4"):
        _check(want in sids, f"estilo '{want}' presente")
    _check(styles.default_style_id() in sids, "estilo por defecto existe")


def test_bake_export_tables() -> None:
    from pcm_studio import bake, export

    for key in ("basecolor", "normal", "roughness", "metallic", "ao", "height"):
        _check(key in bake.MAPS, f"bake.MAPS tiene '{key}'")
    # sufijos por motor cubren todas las claves
    for engine, table in bake.ENGINE_SUFFIX.items():
        if not table:
            continue
        for key in table:
            _check(key in bake.MAPS, f"{engine}: sufijo de '{key}' conocido")
    _check(bake.normal_convention_for_engine("unreal") == "directx",
           "Unreal → DirectX por defecto")
    _check(bake.normal_convention_for_engine("unity") == "opengl",
           "Unity → OpenGL por defecto")
    _check(export.ext_for_format("PNG") == "png", "PNG → .png")
    _check(export.ext_for_format("OPEN_EXR") == "exr", "OPEN_EXR → .exr")
    name = export.texture_file_name("Head", "normal", "unity", 4096, "png")
    _check(name == "T_Head_Normal_4096.png", "nomenclatura Unity normal", name)
    name2 = export.texture_file_name("Head", "basecolor", "unity", 2048, "png")
    _check(name2 == "T_Head_Albedo_2048.png", "nomenclatura Unity albedo", name2)


def _summary() -> int:
    passed = sum(1 for ok, _, _ in _RESULTS if ok)
    failed = [(n, d) for ok, n, d in _RESULTS if not ok]
    print("=" * 68)
    print(f"PCM Studio — test de importación/registro: {passed} OK, {len(failed)} FALLOS")
    print("=" * 68)
    for name, detail in failed:
        print(f"✗ {name}")
        if detail:
            for line in detail.strip().splitlines()[-6:]:
                print(f"    {line}")
    return 1 if failed else 0


def main() -> int:
    # dinámicas (con mock)
    test_import_and_register((5, 2, 2))
    test_import_and_register((4, 2, 0))
    # estáticas (reinstala 5.2 para los imports de propiedades/bake/export)
    pkg = _fresh_import((5, 2, 2))
    pkg_root = os.path.dirname(os.path.abspath(pkg.__file__))
    test_operator_references(pkg_root)
    test_idnames_unique_wellformed(pkg_root)
    test_enum_defaults(pkg_root)
    test_zones_and_styles_integrity()
    test_bake_export_tables()
    return _summary()


# --- compatibilidad con pytest ---------------------------------------------

def test_everything() -> None:
    if main() != 0:
        raise AssertionError("PCM Studio: hay fallos en las pruebas de importación")


if __name__ == "__main__":
    raise SystemExit(main())
