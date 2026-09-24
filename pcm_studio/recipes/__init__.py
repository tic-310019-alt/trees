# SPDX-License-Identifier: GPL-3.0-or-later
# -*- coding: utf-8 -*-
"""
PCM Studio — Paquete de recetas procedurales.

Cada receta construye los canales PBR de una zona (color base, altura de
detalle, rugosidad, normales, SSS…) dentro de un grupo de nodos.  Las recetas
no crean el *Principled BSDF*: devuelven un diccionario de canales y
:mod:`pcm_studio.assembler` los cablea, de modo que el manejo de sockets,
versiones de Blender y capacidades del estilo se hace **una sola vez**.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from .base import RecipeContext, RecipeResult
from .skin import skin, skin_face, skin_extremity, skin_thin, lips
from .eyes import sclera, iris, cornea, animal_eye, lashes
from .mouth import teeth, gums, tongue
from .keratin import nails, hair, hooves, shell
from .animal import fur, scales, feathers, snout, amphibian
from .custom import custom

__all__ = ("RECIPES", "get_recipe", "RecipeContext", "RecipeResult")


RECIPES: Dict[str, Callable[[RecipeContext], RecipeResult]] = {
    "skin": skin,
    "skin_face": skin_face,
    "skin_extremity": skin_extremity,
    "skin_thin": skin_thin,
    "lips": lips,
    "sclera": sclera,
    "iris": iris,
    "cornea": cornea,
    "animal_eye": animal_eye,
    "lashes": lashes,
    "teeth": teeth,
    "gums": gums,
    "tongue": tongue,
    "nails": nails,
    "hair": hair,
    "hooves": hooves,
    "shell": shell,
    "fur": fur,
    "scales": scales,
    "feathers": feathers,
    "snout": snout,
    "amphibian": amphibian,
    "custom": custom,
}


def get_recipe(name: str) -> Callable[[RecipeContext], RecipeResult]:
    """Devuelve la receta por nombre; cae en ``custom`` si no existe."""
    return RECIPES.get(name, custom)
