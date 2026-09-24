# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Capa de internacionalización.

El idioma **primario** del addon es el español: todas las cadenas que se
escriben en la UI son ya el texto en español.  Este módulo mantiene la tabla
inversa (español -> inglés) para quien prefiera la interfaz en inglés.

Uso::

    from .i18n import T
    layout.operator(PCM_OT_assign_zone.bl_idname, text=T("Asignar zona"))

La tabla se resuelve en tiempo de llamada y respeta la preferencia del usuario
(``pcm_prefs.language``), que puede ser ``es``, ``en`` o ``auto`` (sigue el
idioma configurado en Blender).
"""

from __future__ import annotations

__all__ = ("T", "set_language", "get_language", "EN", "is_english")


# ---------------------------------------------------------------------------
# Estado global
# ---------------------------------------------------------------------------

_LANG = "es"          # "es" | "en" | "auto"
_RESOLVED = "es"      # cache de la resolución de "auto"


def set_language(lang: str) -> None:
    global _LANG, _RESOLVED
    _LANG = lang if lang in ("es", "en", "auto") else "es"
    _RESOLVED = _resolve_auto() if _LANG == "auto" else _LANG


def _resolve_auto() -> str:
    """Detecta el idioma de la interfaz de Blender."""
    try:
        import bpy  # noqa: F401  (import tardío: el módulo puede no existir en tests)

        prefs = bpy.context.preferences.view
        lang = getattr(prefs, "language", "en_US") or "en_US"
        return "es" if lang.lower().startswith("es") else "en"
    except Exception:
        return "es"


def get_language() -> str:
    global _RESOLVED
    if _LANG == "auto":
        _RESOLVED = _resolve_auto()
    return _RESOLVED


def is_english() -> bool:
    return get_language() == "en"


# ---------------------------------------------------------------------------
# Tabla español -> inglés
# ---------------------------------------------------------------------------
#
# Regla: si una cadena no está en la tabla, se devuelve tal cual (español).
# Mantener las claves ordenadas por área ayuda a no duplicar entradas.

EN = {
    # -- Marca / cabeceras -------------------------------------------------
    "PCM Studio": "PCM Studio",
    "Materiales de personaje": "Character Materials",
    "Zonas": "Zones",
    "Zona": "Zone",
    "Estilo": "Style",
    "Estilos": "Styles",
    "Material": "Material",
    "Materiales": "Materials",
    "Recetas": "Recipes",
    "Herramientas": "Tools",
    "Mapas": "Maps",
    "Exportación": "Export",

    # -- Panel principal ---------------------------------------------------
    "Preparar objeto": "Prepare Object",
    "Objeto no preparado": "Object not prepared",
    "Objeto listo": "Object ready",
    "Estado del objeto": "Object state",
    "Motor de destino": "Target engine",
    "Resolución de bake": "Bake resolution",
    "Muestras": "Samples",
    "Reconstruir material": "Rebuild material",
    "El material se reconstruye al asignar zonas": "Material rebuilds when assigning zones",
    "Auto-reconstruir": "Auto-rebuild",

    # -- Asignación de zonas ----------------------------------------------
    "Asignar zona a la selección": "Assign zone to selection",
    "Asignar zona": "Assign zone",
    "Quitar zona de la selección": "Remove zone from selection",
    "Selecciona caras primero": "Select faces first",
    "Selecciona las caras en Modo Edición y pulsa «Asignar zona»":
        "Select faces in Edit Mode and press «Assign zone»",
    "Zonas asignadas": "Assigned zones",
    "Sin zonas asignadas": "No zones assigned",
    "Caras": "Faces",
    "caras": "faces",
    "Cara": "Face",
    "Seleccionar caras de esta zona": "Select faces of this zone",
    "Aislar zona en el viewport": "Isolate zone in viewport",
    "Detectar zonas automáticamente": "Auto-detect zones",
    "Detección automática": "Auto detection",
    "Seleccionar todo": "Select all",
    "Invertir selección": "Invert selection",
    "Crecer selección": "Grow selection",
    "Reducir selección": "Shrink selection",
    "Seleccionar por material": "Select by material",
    "Seleccionar por normal": "Select by normal",
    "Seleccionar por área": "Select by area",

    # -- Zonas (nombres) ---------------------------------------------------
    "Piel — Cara": "Skin — Face",
    "Piel — Cuerpo": "Skin — Body",
    "Piel — Manos y pies": "Skin — Hands and feet",
    "Piel — Párpados y orejas": "Skin — Eyelids and ears",
    "Labios": "Lips",
    "Esclerótica (blanco del ojo)": "Sclera (eye white)",
    "Iris": "Iris",
    "Córnea": "Cornea",
    "Cejas y pestañas": "Brows and lashes",
    "Dientes": "Teeth",
    "Encías": "Gums",
    "Lengua": "Tongue",
    "Uñas": "Nails",
    "Pelo y cuero cabelludo": "Hair and scalp",
    "Pelaje": "Fur coat",
    "Escamas": "Scales",
    "Plumas": "Feathers",
    "Pezuñas y cuernos": "Hooves and horns",
    "Hocico y trufa": "Snout and nose leather",
    "Caparazón": "Shell",
    "Ojo animal": "Animal eye",
    "Viscoso / anfibio": "Slime / amphibian",
    "Zona personalizada": "Custom zone",

    # -- Categorías --------------------------------------------------------
    "Humano": "Human",
    "Animal": "Animal",
    "Cabeza": "Head",
    "Cuerpo": "Body",
    "Boca": "Mouth",
    "Ojos": "Eyes",
    "Otros": "Others",

    # -- Estilos -----------------------------------------------------------
    "Realista": "Realistic",
    "Realista (foto)": "Realistic (photo)",
    "Estilo Sims 4": "Sims 4 style",
    "PBR estilizado": "Stylized PBR",
    "Arcilla / escaneo": "Clay / scan",
    "Pintado a mano": "Hand painted",

    # -- Bake --------------------------------------------------------------
    "Bakear mapas": "Bake maps",
    "Bakear todo": "Bake all",
    "Bakear mapa activo": "Bake active map",
    "Preparar bake": "Prepare bake",
    "Color base": "Base color",
    "Normal": "Normal",
    "Rugosidad": "Roughness",
    "Metálico": "Metallic",
    "Oclusión ambiental": "Ambient occlusion",
    "Altura": "Height",
    "Espesor": "Thickness",
    "Emisivo": "Emissive",
    "Altura de detalle": "Detail height",
    "Normal combinada": "Combined normal",
    "Mapas empaquetados": "Packed maps",
    "Directorio de salida": "Output folder",
    "Prefijo": "Prefix",
    "Exportar mapas": "Export maps",
    "Guardar y exportar": "Save and export",
    "Convención de normales": "Normal convention",
    "OpenGL (+Y)": "OpenGL (+Y)",
    "DirectX (-Y)": "DirectX (-Y)",
    "Rellenar bordes (padding)": "Margin (padding)",
    "Tamaño del borde": "Margin size",
    "El objeto necesita UVs": "The object needs UVs",
    "Crear UVs (Smart UV Project)": "Create UVs (Smart UV Project)",
    "Comprobar UVs": "Check UVs",
    "UVs correctas": "UVs OK",
    "Motor de render": "Render engine",
    "Se necesita Cycles para bakear": "Cycles is required for baking",
    "Cambiar a Cycles": "Switch to Cycles",
    "Dispositivo": "Device",
    "Progreso": "Progress",
    "Bakeando": "Baking",
    "Terminado": "Finished",
    "Cancelar": "Cancel",

    # -- Diagnóstico -------------------------------------------------------
    "Diagnóstico": "Diagnostics",
    "Validar instalación": "Validate installation",
    "Informe": "Report",
    "Todo correcto": "Everything OK",
    "Advertencias": "Warnings",
    "Errores": "Errors",
    "Nodos no disponibles en esta versión": "Nodes unavailable in this version",
    "Mostrar informe": "Show report",

    # -- Preferencias ------------------------------------------------------
    "Preferencias": "Preferences",
    "Idioma": "Language",
    "Español": "Spanish",
    "Inglés": "English",
    "Automático (idioma de Blender)": "Automatic (Blender language)",
    "Calidad por defecto": "Default quality",
    "Resolución por defecto": "Default resolution",
    "Ruta de exportación por defecto": "Default export path",
    "Unidades": "Units",
    "Métrico": "Metric",
    "Mostrar consejos": "Show tips",
    "Modo desarrollador": "Developer mode",

    # -- Mensajes ----------------------------------------------------------
    "Hecho": "Done",
    "Listo": "Ready",
    "Error": "Error",
    "Aviso": "Warning",
    "Información": "Info",
    "No hay objeto activo": "No active object",
    "El objeto debe ser una malla": "The object must be a mesh",
    "Entra en Modo Edición para asignar zonas": "Enter Edit Mode to assign zones",
    "Zona asignada a {n} caras": "Zone assigned to {n} faces",
    "Zona eliminada de {n} caras": "Zone removed from {n} faces",
    "Material generado": "Material generated",
    "Material reconstruido": "Material rebuilt",
    "Nada que hacer": "Nothing to do",
}


def T(text: str) -> str:
    """Traduce ``text`` (escrito en español) al idioma activo."""
    if not is_english():
        return text
    return EN.get(text, text)


def Tf(text: str, **kwargs) -> str:
    """Traduce y formatea con ``str.format``."""
    return T(text).format(**kwargs)
