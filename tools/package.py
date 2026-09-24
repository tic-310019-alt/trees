# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
Empaqueta PCM Studio como una **extensión de Blender** (``.zip`` instalable).

Uso::

    python3 tools/package.py            # genera dist/pcm_studio-<versión>.zip
    python3 tools/package.py --check    # sólo valida, no escribe

Formato de extensión (Blender 4.2+ / 5.x): el ``blender_manifest.toml`` y el
``__init__.py`` van en la **raíz del zip**, no dentro de una subcarpeta.  Por
eso se empaqueta el *contenido* de ``pcm_studio/``, no la carpeta en sí.

Se excluyen ``__pycache__``, ``*.pyc`` y cualquier carpeta ``tests``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from typing import Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_PKG = os.path.join(_ROOT, "pcm_studio")
_DIST = os.path.join(_ROOT, "dist")

_EXCLUDE_DIRS = {"__pycache__", "tests", ".git", ".pytest_cache", ".mypy_cache"}
_EXCLUDE_EXT = {".pyc", ".pyo", ".zip"}

# Campos obligatorios del manifiesto según la plataforma de extensiones.
_REQUIRED_MANIFEST = (
    "schema_version", "id", "version", "name", "tagline", "maintainer",
    "type", "blender_version_min", "license",
)


def _read_manifest() -> Dict[str, str]:
    """Lectura mínima de ``blender_manifest.toml`` (sin depender de tomllib)."""
    path = os.path.join(_PKG, "blender_manifest.toml")
    values: Dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$', line)
            if not m:
                continue
            key, raw = m.group(1), m.group(2).strip()
            if raw.startswith('"') and raw.endswith('"'):
                values[key] = raw[1:-1]
            elif raw.startswith("["):
                values[key] = raw  # listas (tags, license) se guardan tal cual
            else:
                values[key] = raw
    return values


def _validate(manifest: Dict[str, str]) -> List[str]:
    problems: List[str] = []
    for field in _REQUIRED_MANIFEST:
        if field not in manifest:
            problems.append(f"falta el campo obligatorio «{field}»")
    if manifest.get("schema_version") != "1.0.0":
        problems.append(f"schema_version debería ser 1.0.0 (es "
                        f"{manifest.get('schema_version')!r})")
    if manifest.get("type") != "add-on":
        problems.append("type debe ser «add-on»")
    if not re.match(r"^\d+\.\d+\.\d+$", manifest.get("version", "")):
        problems.append(f"version no tiene formato X.Y.Z: {manifest.get('version')!r}")
    if not re.match(r"^[a-z0-9_]+$", manifest.get("id", "")):
        problems.append(f"id inválido: {manifest.get('id')!r}")
    # coherencia con bl_info del __init__
    init_path = os.path.join(_PKG, "__init__.py")
    if os.path.exists(init_path):
        text = open(init_path, encoding="utf-8").read()
        m = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', text)
        if m:
            init_ver = ".".join(m.groups())
            if init_ver != manifest.get("version"):
                problems.append(
                    f"bl_info.version ({init_ver}) != manifest.version "
                    f"({manifest.get('version')})")
        else:
            problems.append("no se encontró bl_info[\"version\"] en __init__.py")
    else:
        problems.append("falta __init__.py en la raíz del paquete")
    return problems


def _collect_files() -> List[str]:
    """Rutas absolutas a incluir, relativas al paquete."""
    out: List[str] = []
    for base, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext in _EXCLUDE_EXT:
                continue
            out.append(os.path.join(base, fn))
    return sorted(out)


def build(dest: str) -> int:
    manifest = _read_manifest()
    problems = _validate(manifest)
    if problems:
        print("Manifiesto inválido:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    files = _collect_files()
    if not any(os.path.basename(f) == "blender_manifest.toml" for f in files):
        print("✗ blender_manifest.toml no está en el paquete")
        return 1
    if not any(os.path.basename(f) == "__init__.py" and
               os.path.dirname(f) == _PKG for f in files):
        print("✗ __init__.py no está en la raíz del paquete")
        return 1

    version = manifest["version"]
    ext_id = manifest["id"]
    zip_name = f"{ext_id}-{version}.zip"
    zip_path = os.path.join(dest, zip_name)
    os.makedirs(dest, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for abs_path in files:
            # arcname relativo a la RAÍZ del paquete (manifest en la raíz del zip)
            arc = os.path.relpath(abs_path, _PKG)
            zf.write(abs_path, arc)

    size = os.path.getsize(zip_path)
    print(f"✓ {zip_path}")
    print(f"  {len(files)} ficheros · {size / 1024:.1f} KiB · v{version}")
    print("  Instala en Blender: Edit › Preferences › Add-ons › Install from Disk")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Empaqueta la extensión PCM Studio")
    ap.add_argument("--check", action="store_true",
                    help="sólo valida el manifiesto, no genera el zip")
    ap.add_argument("--dest", default=_DIST, help="carpeta de salida")
    args = ap.parse_args(argv)

    manifest = _read_manifest()
    problems = _validate(manifest)
    if args.check:
        if problems:
            print("✗ Manifiesto inválido:")
            for p in problems:
                print(f"   - {p}")
            return 1
        print(f"✓ Manifiesto correcto: {manifest.get('id')} v{manifest.get('version')}")
        return 0
    return build(args.dest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
