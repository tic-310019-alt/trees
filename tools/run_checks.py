# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
Pasarela de comprobaciones de PCM Studio (equivalente a ``make test``).

Ejecuta, en orden:

1. ``py_compile`` de todos los módulos del paquete (sintaxis).
2. Validación del manifiesto de extensión.
3. ``tests/test_addon.py``  — importación y registro (Blender 5.2 y 4.2).
4. ``tests/test_recipes.py``— ejecución real de todas las recetas procedurales.

Todo corre bajo un ``bpy`` simulado (no hace falta tener Blender instalado).
Devuelve código 0 si todo pasa.

Uso::

    python3 tools/run_checks.py
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
from typing import List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_PKG = os.path.join(_ROOT, "pcm_studio")


def _compile_all() -> int:
    failures: List[str] = []
    count = 0
    for base, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            count += 1
            path = os.path.join(base, fn)
            try:
                # cfile=None usa __pycache__ de forma estándar; está ignorado
                # por git y se elimina al final de la pasada.
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as exc:
                failures.append(f"{path}: {exc}")
    if failures:
        print(f"✗ Sintaxis: {len(failures)} ficheros con errores")
        for f in failures:
            print(f"   {f}")
        return 1
    print(f"✓ Sintaxis: {count} módulos compilan")
    return 0


def _run(script: str) -> int:
    path = os.path.join(_ROOT, "tests", script)
    proc = subprocess.run([sys.executable, path], cwd=_ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)
    out = proc.stdout or ""
    # mostrar sólo el resumen (últimas líneas) salvo que falle
    lines = [ln for ln in out.splitlines()
             if not ln.startswith("[PCM]") or "ERROR" in ln]
    tail = "\n".join(lines[-6:])
    if proc.returncode != 0:
        print(f"✗ {script} falló:\n{tail}")
        return 1
    summary = [ln for ln in lines if "OK," in ln or "FALLOS" in ln]
    print(f"✓ {script}: {summary[-1] if summary else 'OK'}")
    return 0


def main() -> int:
    print("=" * 68)
    print("PCM Studio — comprobaciones")
    print("=" * 68)
    rc = 0
    rc |= _compile_all()
    proc = subprocess.run([sys.executable, os.path.join(_HERE, "package.py"),
                           "--check"], cwd=_ROOT, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print("✗ Manifiesto:\n" + (proc.stdout or ""))
        rc |= 1
    else:
        print("✓ Manifiesto: " + (proc.stdout or "").strip().splitlines()[-1])
    rc |= _run("test_addon.py")
    rc |= _run("test_recipes.py")
    print("=" * 68)
    print("RESULTADO:", "TODO CORRECTO ✓" if rc == 0 else "HAY FALLOS ✗")
    print("=" * 68)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
