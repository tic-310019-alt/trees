# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""Material procedural de roca y flujo de normales."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

try:  # pragma: no cover - se ejecuta dentro de Blender
    import bpy
except Exception:  # pragma: no cover
    bpy = None  # type: ignore[assignment]


RGBA = Tuple[float, float, float, float]

# Colores deliberadamente con contraste suficiente para leer facetas en el
# viewport. Blender los interpreta como valores lineales del shader.
STYLE_PALETTES: Dict[str, Tuple[RGBA, RGBA, RGBA, RGBA, RGBA]] = {
    "SLATE": (
        (0.035, 0.045, 0.060, 1.0),
        (0.085, 0.105, 0.135, 1.0),
        (0.18, 0.205, 0.23, 1.0),
        (0.31, 0.34, 0.36, 1.0),
        (0.48, 0.50, 0.49, 1.0),
    ),
    "GRANITE": (
        (0.055, 0.050, 0.045, 1.0),
        (0.13, 0.125, 0.115, 1.0),
        (0.26, 0.25, 0.22, 1.0),
        (0.43, 0.40, 0.34, 1.0),
        (0.62, 0.57, 0.48, 1.0),
    ),
    "SANDSTONE": (
        (0.19, 0.085, 0.035, 1.0),
        (0.36, 0.18, 0.07, 1.0),
        (0.58, 0.32, 0.12, 1.0),
        (0.76, 0.49, 0.22, 1.0),
        (0.90, 0.68, 0.36, 1.0),
    ),
    "OBSIDIAN": (
        (0.008, 0.006, 0.014, 1.0),
        (0.025, 0.020, 0.045, 1.0),
        (0.075, 0.045, 0.12, 1.0),
        (0.16, 0.09, 0.20, 1.0),
        (0.30, 0.18, 0.34, 1.0),
    ),
    "MOSS": (
        (0.025, 0.045, 0.025, 1.0),
        (0.07, 0.12, 0.055, 1.0),
        (0.16, 0.22, 0.09, 1.0),
        (0.31, 0.35, 0.14, 1.0),
        (0.52, 0.49, 0.22, 1.0),
    ),
}


def _get(settings: Any, name: str, default: Any) -> Any:
    if settings is None:
        return default
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _input(node: Any, name: str) -> Optional[Any]:
    try:
        return node.inputs.get(name)
    except AttributeError:
        try:
            return node.inputs[name] if name in node.inputs else None
        except Exception:
            return None


def _set(node: Any, name: str, value: Any) -> None:
    socket = _input(node, name)
    if socket is None:
        return
    try:
        socket.default_value = value
    except (AttributeError, TypeError, ValueError):
        pass


def _set_index(node: Any, index: int, value: Any) -> None:
    try:
        node.inputs[index].default_value = value
    except (AttributeError, IndexError, TypeError, ValueError):
        pass


def _output(node: Any, name: str) -> Optional[Any]:
    outputs = getattr(node, "outputs", ())
    try:
        return outputs.get(name)
    except AttributeError:
        try:
            return outputs[name] if name in outputs else None
        except (KeyError, IndexError, TypeError):
            return None


def _link(tree: Any, output: Any, node: Any, input_name: str) -> None:
    target = _input(node, input_name)
    if output is None or target is None:
        return
    try:
        tree.links.new(output, target)
    except (RuntimeError, TypeError):
        # Un socket opcional puede cambiar entre versiones; el resto del
        # material sigue siendo válido y el diagnóstico de Blender lo mostrará.
        pass


def _color_tint(color: Sequence[float]) -> RGBA:
    values = list(color) + [1.0, 1.0, 1.0, 1.0]
    return (
        max(0.0, min(2.0, float(values[0]))),
        max(0.0, min(2.0, float(values[1]))),
        max(0.0, min(2.0, float(values[2]))),
        max(0.0, min(2.0, float(values[3]))),
    )


def _tinted_palette(style: str, tint: Sequence[float]) -> Tuple[RGBA, ...]:
    palette = STYLE_PALETTES.get(style, STYLE_PALETTES["GRANITE"])
    tr, tg, tb, _ta = _color_tint(tint)
    return tuple((
        min(1.0, color[0] * tr),
        min(1.0, color[1] * tg),
        min(1.0, color[2] * tb),
        color[3],
    ) for color in palette)


def _configure_ramp(ramp: Any, colors: Sequence[RGBA]) -> None:
    elements = ramp.elements
    # Conservamos los dos elementos que crea Blender y añadimos tres bandas.
    while len(elements) > 2:
        try:
            elements.remove(elements[-1])
        except Exception:
            break
    positions = (0.08, 0.28, 0.50, 0.72, 0.94)
    first = elements[0]
    last = elements[1]
    for index, color in enumerate(colors):
        if index == 0:
            element = first
        elif index == len(colors) - 1:
            element = last
        else:
            element = elements.new(positions[index])
        element.position = positions[index]
        element.color = color
    try:
        ramp.interpolation = "EASE"
    except (AttributeError, ValueError):
        pass


def _principled(tree: Any) -> Any:
    nodes = tree.nodes
    node = nodes.new("ShaderNodeBsdfPrincipled")
    node.name = "SR_PRINCIPLED"
    node.label = "ROCA · Principled PBR"
    node.location = (680, 80)
    return node


def build_rock_material(obj: Any, settings: Any) -> Optional[Any]:
    """Crea o reconstruye el material procedural de ``obj``.

    La conexión importante para las normales es explícita y estable:
    ``SR_FINE_NOISE`` → ``SR_NORMAL_BUMP.Height`` →
    ``SR_NORMAL_BUMP.Normal`` → ``SR_PRINCIPLED.Normal``.
    """
    if bpy is None or obj is None or getattr(obj, "type", "") != "MESH":
        return None
    mesh = getattr(obj, "data", None)
    if mesh is None:
        return None

    material_name = f"SR_MAT_{obj.name}"
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        mat = bpy.data.materials.new(material_name)
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()

    style = str(_get(settings, "style", "GRANITE"))
    tint = _get(settings, "color_tint", (1.0, 1.0, 1.0, 1.0))
    palette = _tinted_palette(style, tint)

    nodes = tree.nodes
    output = nodes.new("ShaderNodeOutputMaterial")
    output.name = "SR_MATERIAL_OUTPUT"
    output.label = "SALIDA · roca estilizada"
    output.location = (980, 80)

    principled = _principled(tree)
    _set(principled, "Metallic", 0.0)
    _set(principled, "Roughness", 0.72)
    _set(principled, "Specular IOR Level", 0.30)
    _set(principled, "Coat Weight", 0.04 if style == "OBSIDIAN" else 0.0)
    _set(principled, "Coat Roughness", 0.22)

    coordinates = nodes.new("ShaderNodeTexCoord")
    coordinates.name = "SR_COORDINATES"
    coordinates.label = "Coordenadas generadas"
    coordinates.location = (-1000, 80)

    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "SR_MAPPING"
    mapping.label = "Escala de detalle"
    mapping.location = (-800, 80)
    _set(mapping, "Scale", (1.0, 1.0, 1.0))
    _link(tree, _output(coordinates, "Generated"), mapping, "Vector")

    macro = nodes.new("ShaderNodeTexNoise")
    macro.name = "SR_MACRO_NOISE"
    macro.label = "MACRO · variación de estratos"
    macro.location = (-580, 240)
    _set(macro, "Scale", 2.65)
    _set(macro, "Detail", 4.0)
    _set(macro, "Roughness", 0.68)
    _set(macro, "Distortion", 0.18)
    _link(tree, _output(mapping, "Vector"), macro, "Vector")

    fine = nodes.new("ShaderNodeTexNoise")
    fine.name = "SR_FINE_NOISE"
    fine.label = "FINE · fuente de normal"
    fine.location = (-580, -60)
    _set(fine, "Scale", 18.0)
    _set(fine, "Detail", 5.0)
    _set(fine, "Roughness", 0.74)
    _set(fine, "Distortion", 0.10)
    _link(tree, _output(mapping, "Vector"), fine, "Vector")

    fracture = nodes.new("ShaderNodeTexVoronoi")
    fracture.name = "SR_FRACTURE_VORONOI"
    fracture.label = "VORONOI · fracturas gráficas"
    fracture.location = (-580, -330)
    _set(fracture, "Distance", 0.0)
    _set(fracture, "Scale", 6.5)
    _set(fracture, "Randomness", 0.42)
    _link(tree, _output(mapping, "Vector"), fracture, "Vector")

    detail_mix = nodes.new("ShaderNodeMixRGB")
    detail_mix.name = "SR_DETAIL_MIX"
    detail_mix.label = "Mezcla de grano y fractura"
    detail_mix.blend_type = "MULTIPLY"
    detail_mix.location = (-260, 20)
    _set(detail_mix, "Fac", 0.30)
    _link(tree, _output(fine, "Fac"), detail_mix, "Color1")
    _link(tree, _output(fracture, "Distance"), detail_mix, "Color2")

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "SR_ROCK_PALETTE"
    ramp.label = f"PALETA · {style.title()}"
    ramp.location = (0, 250)
    _configure_ramp(ramp.color_ramp, palette)
    _link(tree, _output(macro, "Fac"), ramp, "Fac")

    color_variation = nodes.new("ShaderNodeMixRGB")
    color_variation.name = "SR_COLOR_VARIATION"
    color_variation.label = "Color × detalle"
    color_variation.blend_type = "MULTIPLY"
    color_variation.location = (280, 260)
    _set(color_variation, "Fac", 0.18)
    _link(tree, _output(ramp, "Color"), color_variation, "Color1")
    _link(tree, _output(detail_mix, "Color"), color_variation, "Color2")
    _link(tree, _output(color_variation, "Color"), principled, "Base Color")

    rough_math = nodes.new("ShaderNodeMath")
    rough_math.name = "SR_ROUGHNESS_VARIATION"
    rough_math.label = "Rugosidad por grano"
    rough_math.operation = "MULTIPLY_ADD"
    rough_math.location = (260, -100)
    _set_index(rough_math, 1, 0.23)
    _set_index(rough_math, 2, 0.58)
    _link(tree, _output(detail_mix, "Color"), rough_math, "Value")
    _link(tree, _output(rough_math, "Value"), principled, "Roughness")

    bump = nodes.new("ShaderNodeBump")
    bump.name = "SR_NORMAL_BUMP"
    bump.label = "NORMAL · micro-relieve procedural"
    bump.location = (360, -300)
    _set(bump, "Strength", float(_get(settings, "normal_strength", 0.34)))
    _set(bump, "Distance", float(_get(settings, "normal_distance", 0.075)))
    _set(bump, "Invert", False)
    _link(tree, _output(detail_mix, "Color"), bump, "Height")
    _link(tree, _output(bump, "Normal"), principled, "Normal")

    _link(tree, _output(principled, "BSDF"), output, "Surface")

    # El material sigue siendo editable: nombres y etiquetas actúan como una
    # pequeña documentación del grafo para quien lo abra en el Shader Editor.
    mat.diffuse_color = palette[2]
    mat["sr_addon"] = "Stylized Rock Forge"
    mat["sr_material_version"] = "1.0"
    mat["sr_style"] = style
    mat["sr_normal_source"] = "PROCEDURAL_BUMP"
    mat["sr_normal_chain"] = "SR_FINE_NOISE > SR_DETAIL_MIX > SR_NORMAL_BUMP > Principled Normal"
    mat["sr_generated_for"] = obj.name

    # Un único slot evita que una regeneración deje materiales antiguos en la
    # malla. No se tocan slots ajenos si el material no pudo asignarse.
    try:
        if len(mesh.materials) == 0:
            mesh.materials.append(mat)
        else:
            mesh.materials[0] = mat
            while len(mesh.materials) > 1:
                mesh.materials.pop(index=len(mesh.materials) - 1)
    except (AttributeError, RuntimeError):
        pass
    return mat


def principled_node(material: Any) -> Optional[Any]:
    if material is None or not getattr(material, "use_nodes", False):
        return None
    try:
        return material.node_tree.nodes.get("SR_PRINCIPLED")
    except AttributeError:
        return None


def connect_baked_normal(material: Any, image: Any) -> bool:
    """Conecta una imagen normal tangente bakeada al Principled del material."""
    if material is None or image is None or not getattr(material, "use_nodes", False):
        return False
    tree = material.node_tree
    nodes = tree.nodes
    principled = nodes.get("SR_PRINCIPLED")
    if principled is None:
        return False
    target = nodes.get("SR_BAKED_NORMAL_IMAGE")
    if target is None:
        target = nodes.new("ShaderNodeTexImage")
        target.name = "SR_BAKED_NORMAL_IMAGE"
        target.label = "NORMAL BAKEADA · Non-Color"
        target.location = (0, -520)
    target.image = image
    try:
        image.colorspace_settings.name = "Non-Color"
    except (AttributeError, TypeError, ValueError):
        pass

    normal_map = nodes.get("SR_BAKED_NORMAL_MAP")
    if normal_map is None:
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "SR_BAKED_NORMAL_MAP"
        normal_map.label = "NORMAL MAP · Tangente"
        normal_map.location = (390, -520)
    _set(normal_map, "Strength", 1.0)

    normal_socket = _input(principled, "Normal")
    if normal_socket is None:
        return False
    for link in list(tree.links):
        if getattr(link, "to_node", None) is principled and getattr(link, "to_socket", None) is normal_socket:
            tree.links.remove(link)
    _link(tree, _output(target, "Color"), normal_map, "Color")
    _link(tree, _output(normal_map, "Normal"), principled, "Normal")
    material["sr_normal_source"] = "BAKED_TANGENT_IMAGE"
    material["sr_normal_image"] = image.name
    return True


def restore_procedural_normal(material: Any) -> bool:
    """Restaura la conexión Bump → Principled sin reconstruir todo el material."""
    if material is None or not getattr(material, "use_nodes", False):
        return False
    tree = material.node_tree
    principled = tree.nodes.get("SR_PRINCIPLED")
    bump = tree.nodes.get("SR_NORMAL_BUMP")
    if principled is None or bump is None:
        return False
    normal_socket = _input(principled, "Normal")
    if normal_socket is None:
        return False
    for link in list(tree.links):
        if getattr(link, "to_node", None) is principled and getattr(link, "to_socket", None) is normal_socket:
            tree.links.remove(link)
    _link(tree, _output(bump, "Normal"), principled, "Normal")
    material["sr_normal_source"] = "PROCEDURAL_BUMP"
    return True
