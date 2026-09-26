# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Empaqueta Stylized Rock Forge como extensión instalable de Blender 5.2.

Uso desde la raíz del repositorio::

    python3 tools/package_rockforge.py --check
    python3 tools/package_rockforge.py

El manifiesto y ``__init__.py`` quedan en la raíz del zip, como exige el
formato de extensiones de Blender 4.2+.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PACKAGE = os.path.join(ROOT, "stylized_rocks")
DEFAULT_DEST = os.path.join(ROOT, "dist")
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache"}
EXCLUDE_EXT = {".pyc", ".pyo", ".zip"}
REQUIRED = (
    "schema_version", "id", "version", "name", "tagline", "maintainer",
    "type", "blender_version_min", "license",
)


def read_manifest() -> Dict[str, str]:
    values: Dict[str, str] = {}
    with open(os.path.join(PACKAGE, "blender_manifest.toml"), encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$', line)
            if not match:
                continue
            key, value = match.groups()
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                values[key] = value[1:-1]
            else:
                values[key] = value
    return values


def validate(manifest: Dict[str, str]) -> List[str]:
    problems: List[str] = []
    for field in REQUIRED:
        if field not in manifest:
            problems.append(f"falta «{field}»")
    if manifest.get("schema_version") != "1.0.0":
        problems.append("schema_version debe ser 1.0.0")
    if manifest.get("type") != "add-on":
        problems.append("type debe ser add-on")
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", "")):
        problems.append("version debe tener formato X.Y.Z")
    if not re.fullmatch(r"[a-z0-9_]+", manifest.get("id", "")):
        problems.append("id debe usar minúsculas, números y guiones bajos")

    init_path = os.path.join(PACKAGE, "__init__.py")
    text = open(init_path, encoding="utf-8").read() if os.path.exists(init_path) else ""
    match = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', text)
    if not match:
        problems.append("no se encontró bl_info.version")
    elif ".".join(match.groups()) != manifest.get("version"):
        problems.append("bl_info.version y manifest.version no coinciden")
    return problems


def collect() -> List[str]:
    paths: List[str] = []
    for base, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for filename in sorted(files):
            if os.path.splitext(filename)[1].lower() not in EXCLUDE_EXT:
                paths.append(os.path.join(base, filename))
    return sorted(paths)


def build(destination: str) -> int:
    manifest = read_manifest()
    problems = validate(manifest)
    if problems:
        print("✗ Manifiesto inválido:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    files = collect()
    os.makedirs(destination, exist_ok=True)
    output = os.path.join(destination, f"{manifest['id']}-{manifest['version']}.zip")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, os.path.relpath(path, PACKAGE))
    print(f"✓ {output}")
    print(f"  {len(files)} ficheros · {os.path.getsize(output) / 1024:.1f} KiB")
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="valida sin crear el zip")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="carpeta de salida")
    args = parser.parse_args(argv)
    manifest = read_manifest()
    problems = validate(manifest)
    if args.check:
        if problems:
            for problem in problems:
                print(f"✗ {problem}")
            return 1
        print(f"✓ Manifiesto correcto: {manifest['id']} v{manifest['version']} · Blender >= {manifest['blender_version_min']}")
        return 0
    return build(args.dest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
