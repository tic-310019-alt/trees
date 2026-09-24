# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Exportación a motor de juego.

Guarda los mapas bakeados en disco con la nomenclatura y la configuración que
espera cada motor, y genera además un manifiesto con los ajustes exactos del
material (estilo, zonas, parámetros) para poder reproducirlo.

Nomenclatura por motor
----------------------
===================  ============================  ===========================
Mapa                 Unity                         Unreal
===================  ============================  ===========================
Color base           ``T_<obj>_Albedo``            ``T_<obj>_BaseColor``
Normal               ``T_<obj>_Normal``            ``T_<obj>_Normal``
Rugosidad            ``T_<obj>_Smoothness``        ``T_<obj>_Roughness``
Metálico             ``T_<obj>_Metallic``          ``T_<obj>_Metallic``
Oclusión             ``T_<obj>_AO``                ``T_<obj>_AO``
Altura               ``T_<obj>_Height``            ``T_<obj>_Height``
Empaquetado          ``T_<obj>_MaskMap``           ``T_<obj>_ORM``
===================  ============================  ===========================

Se genera también un ``.json`` con el estado del material y un ``.txt`` con las
instrucciones de importación específicas del motor (compresión, espacio de
color, sRGB) — que es donde se arruinan el 90 % de los materiales al exportar.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import assembler, bake
from .i18n import get_language
from .log import log

try:  # pragma: no cover
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]

__all__ = ("export_maps", "export_manifest", "import_instructions",
           "resolve_output_dir", "texture_file_name", "write_instructions",
           "ext_for_format", "FORMAT_EXT")


# ---------------------------------------------------------------------------
# Rutas y nombres
# ---------------------------------------------------------------------------

def resolve_output_dir(context: Any, settings: Any, obj: Any) -> str:
    """Resuelve el directorio de salida (admite ``//`` relativo al .blend)."""
    raw = getattr(settings, "output_dir", "") or "//PCM_Export/"
    try:
        path = bpy.path.abspath(raw) if bpy is not None else raw
    except Exception:
        path = raw
    if not os.path.isabs(path):
        base = os.path.dirname(getattr(bpy.data, "filepath", "") or "") if bpy else ""
        path = os.path.join(base or os.getcwd(), path)
    return os.path.normpath(path)


def texture_file_name(prefix: str, map_key: str, engine: str,
                      resolution: int, ext: str) -> str:
    """``T_<prefijo><sufijo>_<res>.<ext>``"""
    suffix = bake.suffix_for_engine(engine, map_key)
    return f"T_{prefix}{suffix}_{resolution}.{ext.lstrip('.')}"


FORMAT_EXT: Dict[str, str] = {
    "PNG": "png",
    "TARGA": "tga",
    "TIFF": "tif",
    "OPEN_EXR": "exr",
    "WEBP": "webp",
}


def ext_for_format(file_format: str) -> str:
    """Extensión de fichero para un ``file_format`` de Blender."""
    return FORMAT_EXT.get(file_format, "png")


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------

def export_maps(context: Any, obj: Any, settings: Any, *,
                map_keys: Optional[Sequence[str]] = None,
                only_existing: bool = True) -> Dict[str, Any]:
    """
    Guarda los mapas en disco.

    Devuelve ``{"files": [...], "dir": str, "errors": [...], "warnings": [...]}``.
    """
    result: Dict[str, Any] = {"files": [], "dir": "", "errors": [], "warnings": []}
    if bpy is None or obj is None:
        result["errors"].append("Blender no está disponible")
        return result

    out_dir = resolve_output_dir(context, settings, obj)
    result["dir"] = out_dir
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as exc:
        result["errors"].append(f"No se pudo crear el directorio {out_dir}: {exc}")
        return result

    engine = getattr(settings, "engine", "unity")
    try:
        resolution = int(getattr(settings, "resolution", "4096"))
    except Exception:
        resolution = 4096
    prefix = (getattr(settings, "prefix", "") or "").strip() or bake.clean_name(obj.name)
    file_format = getattr(settings, "file_format", "PNG")
    depth = getattr(settings, "color_depth", "8")
    ext = ext_for_format(file_format)

    keys = list(map_keys) if map_keys else [
        k for k in bake.MAPS.keys()
        if getattr(settings, f"bake_{k}", False) or k == "orm"
    ]

    # configuración de render de imagen temporal
    img_settings = bpy.context.scene.render.image_settings
    prev = (img_settings.file_format, img_settings.color_mode,
            img_settings.color_depth, img_settings.compression)
    exported_any = False

    for key in keys:
        if key not in bake.MAPS:
            continue
        cfg = bake.MAPS[key]
        name = bake.image_name(prefix, key, engine, resolution)
        img = bpy.data.images.get(name)
        if img is None:
            if only_existing:
                continue
            result["warnings"].append(f"No existe la imagen de {cfg['label']}")
            continue
        try:
            img_settings.file_format = file_format
        except Exception:
            try:
                img_settings.file_format = "PNG"
            except Exception:
                pass
        try:
            img_settings.color_mode = "RGBA" if key in ("basecolor", "alpha") else "RGB"
        except Exception:
            pass
        try:
            img_settings.color_depth = "16" if (depth == "16" or cfg.get("float")) else "8"
        except Exception:
            pass
        try:
            if file_format == "PNG":
                img_settings.compression = 15
        except Exception:
            pass

        filename = texture_file_name(prefix, key, engine, resolution, ext)
        filepath = os.path.join(out_dir, filename)
        try:
            img.filepath_raw = filepath
            img.save(filepath=filepath)
            result["files"].append({"map": key, "path": filepath, "name": filename})
            exported_any = True
        except Exception as exc:
            result["errors"].append(f"No se pudo guardar {filename}: {exc}")
            log.error("Export falló para %s: %s", filename, exc)

    # restaurar
    try:
        (img_settings.file_format, img_settings.color_mode,
         img_settings.color_depth, img_settings.compression) = prev
    except Exception:
        pass

    if not exported_any and not result["errors"]:
        result["warnings"].append(
            "No se exportó ningún mapa: haz el bake primero o revisa la selección "
            "de mapas.")
    return result


def export_manifest(context: Any, obj: Any, settings: Any, out_dir: str,
                    style: Any) -> Optional[str]:
    """Escribe un JSON con el estado completo del material."""
    if bpy is None or obj is None:
        return None
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        return None
    info = assembler.material_report(obj)
    values = assembler.load_user_params(assembler._existing_pcm_material(obj))

    data: Dict[str, Any] = {
        "addon": "PCM Studio",
        "version": _addon_version(),
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "blender": getattr(bpy.app, "version_string", "?"),
        "object": obj.name,
        "engine": getattr(settings, "engine", "unity"),
        "normal_convention": getattr(settings, "normal_convention",
                                     bake.normal_convention_for_engine(
                                         getattr(settings, "engine", "unity"))),
        "resolution": getattr(settings, "resolution", "4096"),
        "style": {
            "id": style.id,
            "name": style.name(lang),
            "globals": dict(style.globals),
        },
        "faces": {
            "total": info["faces_total"],
            "unassigned": info["faces_unassigned"],
        },
        "zones": [
            {"id": z["id"], "key": z["key"], "name": z["name"], "faces": z["faces"]}
            for z in info["zones"]
        ],
        "parameters": values,
        "maps": [
            {"key": k, "label": bake.MAPS[k]["label"],
             "suffix": bake.suffix_for_engine(getattr(settings, "engine", "unity"), k),
             "colorspace": bake.MAPS[k]["colorspace"],
             "enabled": bool(getattr(settings, f"bake_{k}", False))}
            for k in bake.MAPS if k != "orm"
        ],
    }
    path = os.path.join(out_dir, f"T_{bake.clean_name(obj.name)}_PCM.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
    except Exception as exc:
        log.error("No se pudo escribir el manifiesto: %s", exc)
        return None
    return path


def _addon_version() -> str:
    try:
        from . import bl_info  # type: ignore[attr-defined]

        return ".".join(str(x) for x in bl_info.get("version", (1, 0, 0)))
    except Exception:
        return "1.0.0"


# ---------------------------------------------------------------------------
# Instrucciones de importación
# ---------------------------------------------------------------------------

_IMPORT_NOTES: Dict[str, List[str]] = {
    "unity": [
        "UNITY — IMPORTACIÓN",
        "",
        "1. Copia las texturas a Assets/ (por ejemplo Assets/Characters/<nombre>/).",
        "2. _Albedo:  Texture Type = Default · sRGB = ON · Compression = Normal Quality.",
        "3. _Normal:   Texture Type = Normal map · sRGB = OFF. Unity preguntará si",
        "              quieres arreglarla: di que NO, ya viene en OpenGL (+Y).",
        "4. _Roughness, _Metallic, _AO, _Height, _MaskMap:",
        "              Texture Type = Default · sRGB = OFF · Compression = Normal.",
        "5. En el shader Standard/Lit conecta:",
        "              Base Map        <- _Albedo (A <- _Alpha si existe)",
        "              Normal Map      <- _Normal",
        "              Metallic Map    <- _Metallic (R), Smoothness = 1 - _Roughness",
        "              Occlusion Map   <- _AO",
        "              Height Map      <- _Height (activa Parallax Mapping si lo usas)",
        "6. Si generaste _MaskMap (R=AO, G=Smoothness, B=Metal, A=Normal Y),",
        "   conéctalo a la ranura Mask Map del shader HDRP y no uses los sueltos.",
        "7. IMPORTANT: Unity usa SMOOTHNESS = 1 - ROUGHNESS. Si conectas el mapa",
        "   de rugosidad directamente, invierte el valor en el shader o exporta",
        "   la copia invertida desde PCM Studio.",
        "",
    ],
    "unreal": [
        "UNREAL ENGINE — IMPORTACIÓN",
        "",
        "1. Arrastra las texturas al Content Browser (Content/Characters/<nombre>).",
        "2. _BaseColor:      Compression Settings = Default (DXT1/BC1) · sRGB = ON.",
        "3. _Normal:         Compression Settings = Normalmap · sRGB = OFF.",
        "                    Si exportaste con convención DirectX el verde ya viene",
        "                    invertido; Unreal espera DirectX (-Y), que es lo que",
        "                    produce PCM Studio al elegir Unreal como motor.",
        "4. _Roughness/_Metallic/_AO/_Height: Compression = Grayscale o Masks,",
        "                    sRGB = OFF, Mip Gen Settings = NoMipmaps si es UI.",
        "5. _ORM: R = Ambient Occlusion, G = Roughness, B = Metallic.",
        "   Conéctalo tal cual al material (Unreal usa ese orden por convención).",
        "6. Material: crea un Material y enchufa",
        "              Base Color  <- _BaseColor",
        "              Normal      <- _Normal",
        "              Roughness   <- _ORM.G",
        "              Metallic    <- _ORM.B",
        "              AmbientOcclusion <- _ORM.R",
        "7. Si el personaje usa Subsurface en Blender, en Unreal pon",
        "   Shading Model = Subsurface y conecta un Subsurface Color aproximado",
        "   (los mapas de PCM no incluyen el perfil de SSS: es un dato del shader).",
        "8. _NormalDetail se usa como Detail Normal: en el material, multiplícalo",
        "   con la normal base tras desempaquetar (Unreal no tiene Detail Normal",
        "   nativo; usa el nodo BlendAngleCorrectedNormals).",
        "",
    ],
    "godot": [
        "GODOT — IMPORTACIÓN",
        "",
        "1. Copia las texturas a res:// (por ejemplo res://characters/<nombre>/).",
        "2. En el panel Import, para _Normal marca 'Normal Map' en Detect As.",
        "3. Para _Roughness/_Metallic/_AO/_Height desactiva sRGB (Compress > Lossless",
        "   y 'Detect As: Data' si está disponible en tu versión).",
        "4. Godot usa OpenGL (+Y), que es la convención por defecto de PCM Studio.",
        "5. En StandardMaterial3D: Albedo <- _Albedo, Normal Map <- _Normal",
        "   (activa el flag), Roughness <- _Roughness (canal R), Metallic <- _Metallic,",
        "   AO <- _AO, Height/Parallax <- _Height si lo necesitas.",
        "",
    ],
    "generic": [
        "glTF / GENÉRICO — IMPORTACIÓN",
        "",
        "1. Nomenclatura glTF: _BaseColor (sRGB), _Normal (lineal, OpenGL +Y),",
        "   _Roughness y _Metallic empaquetados en G y B de una sola textura",
        "   (metallicRoughnessTexture), _Emissive (sRGB).",
        "2. Si usas el exportador glTF de Blender, exporta el material tal cual:",
        "   PCM conecta los canales al Principled BSDF y el exportador los",
        "   empaqueta solo.  Revisa que 'Images > Format' sea PNG o JPEG.",
        "3. Para otros motores: color base en sRGB, el resto en lineal, normales en",
        "   OpenGL salvo que el motor documente lo contrario.",
        "",
    ],
}


def import_instructions(engine: str) -> str:
    """Texto de ayuda de importación para el motor elegido."""
    lines = list(_IMPORT_NOTES.get(engine, _IMPORT_NOTES["generic"]))
    lines += [
        "NOTAS GENERALES",
        "",
        "· Los mapas de color (BaseColor, Emissive) van en sRGB; todos los demás",
        "  (Normal, Roughness, Metallic, AO, Height, ORM) van en lineal / Non-Color.",
        "· La normal se exporta en OpenGL (+Y) salvo que elijas DirectX en el panel.",
        "· El margen (padding) por defecto es 16 px: suficiente para 2K-4K con",
        "  mipmaps.  Si ves costuras en el motor, súbelo a 32.",
        "· La altura es lineal en 0..1 y corresponde al relieve en metros del",
        "  material; multiplícala por la escala que necesite tu shader de parallax.",
        "· El perfil de Subsurface Scattering NO se puede bakear: es un dato del",
        "  shader.  El JSON de manifiesto incluye el radio y el color usados en",
        "  Blender para que los reproduzcas en el motor.",
        "",
    ]
    return "\n".join(lines)


def write_instructions(out_dir: str, engine: str, obj_name: str) -> Optional[str]:
    """Guarda las instrucciones de importación en un .txt junto a los mapas."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"LEEME_{bake.clean_name(obj_name)}_importacion.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"PCM Studio — {datetime.date.today().isoformat()}\n")
            fh.write("=" * 60 + "\n\n")
            fh.write(import_instructions(engine))
        return path
    except Exception as exc:
        log.error("No se pudieron escribir las instrucciones: %s", exc)
        return None
