# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Comprobaciones de Stylized Rock Forge sin una instalación local de Blender."""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.join(ROOT, "stylized_rocks")


def compile_package() -> int:
    failures: List[str] = []
    count = 0
    for filename in sorted(os.listdir(PACKAGE)):
        if not filename.endswith(".py"):
            continue
        count += 1
        path = os.path.join(PACKAGE, filename)
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{filename}: {exc}")
    if failures:
        for failure in failures:
            print("✗", failure)
        return 1
    print(f"✓ Sintaxis: {count} módulos")
    return 0


def run(script: str) -> int:
    process = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", script)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(process.stdout.rstrip())
    return process.returncode


def main() -> int:
    result = compile_package()
    result |= run("test_rockforge.py")
    package_check = subprocess.run(
        [sys.executable, os.path.join(HERE, "package_rockforge.py"), "--check"],
        cwd=ROOT,
        text=True,
    )
    result |= package_check.returncode
    print("RESULTADO:", "TODO CORRECTO ✓" if result == 0 else "HAY FALLOS ✗")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
