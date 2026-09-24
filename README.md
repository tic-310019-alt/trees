# PCM Studio

**Materiales de personaje procedurales, profesionales y game-ready para Blender**

PCM Studio crea un único material PBR procedural para personajes humanos y
animales. El flujo está diseñado para ser directo: **selecciona caras → asigna
una zona → genera el material → bakea y exporta**.

- Blender **5.2 LTS** (compatible desde 4.2).
- Interfaz en **español por defecto**, con selector español/inglés.
- Presets **Realista** y **Sims 4** (también Estilizado y ClayScan para look-dev).
- Un material maestro que mezcla zonas por atributo de cara `pcm_zone`.
- Bake completo: Base Color, Normal OpenGL/DirectX, Roughness, Metallic, AO,
  Height y ORM/Mask.
- Exportación preparada para Unity, Unreal, Godot y glTF, con nombres,
  espacios de color, padding y manifiesto.
- Zonas humanas y animales: piel, iris, esclerótica, córnea, labios, pestañas,
  dientes, encías, lengua, uñas, pelo, pelaje, escamas, plumas, pezuñas,
  cuernos, hocico/rinario, caparazón, ojos animales, anfibios y personalizada.

> El addon es procedural: no depende de imágenes generadas ni de servicios
> externos. El resultado se construye con nodos nativos de Blender y puede
> editarse después en el Shader Editor.

## Instalación

1. Descarga `pcm_studio-1.0.0.zip` desde **Releases** o genera el paquete con
   `python3 tools/package.py`.
2. En Blender abre **Edit → Preferences → Add-ons → Install from Disk**.
3. Selecciona el `.zip`, activa **PCM Studio** y conserva el idioma español o
   cámbialo a English en las preferencias.

El zip de una extensión de Blender contiene `blender_manifest.toml` y
`__init__.py` directamente en su raíz. No descomprimas el paquete dentro de
otra carpeta del addon.

## Flujo rápido

1. Selecciona un objeto de tipo Mesh y crea/activa una UV.
2. En **Material Properties → PCM Studio**, pulsa **Crear material**.
3. En modo Edit selecciona las caras y usa **Asignar zona**. Para acelerar el
   proceso, usa **Proponer zonas**: el addon analiza posición, normales,
   curvatura y grupos suaves para sugerir asignaciones con confianza.
4. Elige **Realista** o **Sims 4**, ajusta los parámetros de la zona y pulsa
   **Regenerar material**.
5. Ejecuta el diagnóstico antes del bake para revisar UVs, caras sin zona,
   nodos y resolución.
6. En **Bake / Export**, elige modo de bake, resolución, padding, formato,
   motor destino y carpeta. El bake crea mapas con prefijos `T_<objeto>_...` y
   un `manifest.json`/`LEEME.txt` de importación.

También está disponible un panel compacto en **View3D → N → PCM Studio** y
menús contextuales para asignar zonas a las caras seleccionadas.

## Bake y exportación

PCM Studio ofrece tres modos de geometría:

- **Geometría**: bake directo con la malla actual.
- **Desplazado** (predeterminado): subdivisión adaptativa temporal para capturar
  Height y micro-relieve; restaura la escena y `displacement_method` al terminar.
- **Overlay**: conserva la geometría y hornea el detalle como normal adicional.

La normal puede exportarse como **OpenGL** o **DirectX**. DirectX se obtiene
como postproceso del mapa bakeado, invirtiendo el canal verde. El ORM se empaqueta
como **R = AO, G = Roughness, B = Metallic** y el manifiesto documenta el
mapeo. Los mapas de color van en sRGB; roughness, metallic, AO, height, mask,
ORM y normal van en espacio lineal/no color según corresponda.

## Desarrollo y comprobaciones

El repositorio incluye un `bpy` simulado con validación estricta de enums y
sockets, por lo que las recetas pueden ejecutarse sin una instalación local de
Blender:

```bash
python3 tools/run_checks.py
# 26 módulos compilan
# test_addon.py: 535 OK, 0 FALLOS
# test_recipes.py: 237 OK, 0 FALLOS

python3 tools/package.py --check
python3 tools/package.py
```

`tools/package.py` genera `dist/pcm_studio-1.0.0.zip` y excluye caches de
Python y tests. El código usa la licencia **GPL-3.0-or-later**; consulta
`pcm_studio/blender_manifest.toml`.

## Idioma

El texto se centraliza en `pcm_studio/i18n.py`. Español (`es`) es el idioma
inicial y English (`en`) está disponible desde las preferencias. Los nombres
internos de nodos y los nombres de mapas exportados permanecen estables para
que los materiales y proyectos sean reproducibles entre idiomas.

## Estado de compatibilidad

El objetivo de producción es **Blender 5.2 LTS**. La capa `compat.py` mantiene
fallbacks para Blender 4.2–5.x (nodos nuevos, sockets del Principled y cambios
de bake). El conjunto de comprobaciones valida importación/registro en los
perfiles simulados 5.2.2 y 4.2.0, y ejecuta todas las recetas humanas y
animales con ambos estilos principales.

## Licencia

Copyright © 2026 PCM Studio. GPL-3.0-or-later.
