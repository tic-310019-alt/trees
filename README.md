# Stylized Rock Forge

Addon para **Blender 5.2** que crea rocas estilizadas procedurales con una
silueta reproducible por semilla, material PBR editable y normales completas.
La interfaz está en español y no usa imágenes, librerías externas ni servicios
remotos.

> El paquete instalable es `stylized_rocks/`. El directorio `pcm_studio/` que
> acompaña a este checkout es un addon anterior del repositorio y no es
> necesario para usar Rock Forge.

## Qué crea

Cada roca contiene:

- **Geometría procedural reproducible**: icosfera triangulada subdividida,
  ruido fractal multi-escala, asimetría, conicidad y base plana. Regenerar con
  la misma semilla reconstruye la forma desde cero, sin acumular deformaciones.
- **Normales geométricas**: modo facetas planas, híbrido o suave; el modo
  híbrido conserva aristas según un ángulo y puede añadir un modificador
  `Weighted Normal`. Los datos de la malla se actualizan al terminar.
- **Material procedural editable**: dos `Noise Texture`, `Voronoi`, paleta por
  `ColorRamp`, rugosidad variable y una cadena explícita
  `SR_FINE_NOISE → SR_NORMAL_BUMP → Principled Normal`.
- **Normal tangente bakeable**: crea una imagen `Non-Color`, hornea la normal
  procedural con Cycles y la conecta mediante `Normal Map`. La ruta de salida
  es opcional; si queda vacía la imagen permanece en el `.blend`.
- **Cinco estilos**: Pizarra, Granito, Arenisca, Obsidiana y Roca con musgo.
- **Variaciones rápidas**: nueva semilla y duplicado de la roca activa con una
  semilla vecina.

## Instalación

1. Genera el zip desde la raíz del repositorio:

   ```bash
   python3 tools/package_rockforge.py --check
   python3 tools/package_rockforge.py
   ```

2. En Blender 5.2 abre **Edit → Preferences → Add-ons → Install from Disk**.
3. Selecciona `dist/stylized_rocks-1.0.0.zip` y activa **Stylized Rock Forge**.
4. Abre la Vista 3D, pulsa `N` y usa la pestaña **Roca Forge**. También se
   puede crear desde **Add → Roca estilizada procedural**.

El manifiesto de extensión y `__init__.py` están en la raíz del zip, por lo que
no hay que descomprimirlo dentro de otra carpeta.

## Flujo recomendado

1. Ajusta semilla, detalle y dimensiones en **Crear** y pulsa **Crear roca**.
2. En **Forma**, aumenta `Rugosidad de silueta` y `Asimetría` para separar
   variaciones; `Detalle geométrico = 2` suele ser suficiente para un asset
   estilizado. `3` o `4` sirve para primeros planos.
3. En **Normales geométricas**, elige **Facetas planas** para low-poly,
   **Híbrida** para facetas controladas o **Suave** para una roca redondeada.
   `Fuerza de normal procedural` controla el micro-relieve del shader, no la
   topología.
4. Cambia la paleta en **Material procedural**. El material se puede inspeccionar
   en el Shader Editor; sus nodos empiezan por `SR_`.
5. Si necesitas un mapa para un motor externo, conserva un UV `UVMap` generado
   automáticamente y pulsa **Hornear normal tangente**. Conecta luego la imagen
   exportada como **Non-Color** a un nodo `Normal Map` en el motor de destino.

## Estructura

```text
stylized_rocks/
├── __init__.py              # registro y bl_info
├── blender_manifest.toml    # extensión Blender 5.2
├── geometry.py              # icosfera, deformación y dimensiones
├── noise.py                 # hash/value noise/fBm determinista
├── material.py              # grafo PBR y normales Bump/Normal Map
├── mesh.py                  # malla, UV, shading y modificadores
├── properties.py            # ajustes persistentes
├── operators.py             # crear, regenerar, variar y bakear
└── ui.py                    # panel Roca Forge y menú Add
```

Comprobaciones rápidas sin Blender:

```bash
python3 tools/run_rock_checks.py
python3 -m py_compile stylized_rocks/*.py
python3 - <<'PY'
from stylized_rocks.geometry import generate_rock_geometry
v, f = generate_rock_geometry({'seed': 7, 'detail': 2})
print(len(v), len(f), 'vértices/caras')
PY
```

## Licencia

GPL-3.0-or-later. Copyright © 2026 Stylized Rock Forge.
