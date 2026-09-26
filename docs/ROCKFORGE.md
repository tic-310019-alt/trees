# Guía de Stylized Rock Forge

## Parámetros de forma

- **Semilla**: usa un entero estable. La forma no depende del orden de creación
  de objetos ni del generador aleatorio global.
- **Detalle geométrico**: cada nivel multiplica por cuatro las caras de la
  icosfera. Como referencia: nivel 1 = 80 caras, nivel 2 = 320, nivel 3 =
  1.280 y nivel 4 = 5.120.
- **Rugosidad de silueta**: combina cuatro escalas de ruido en el radio de cada
  vértice. En 0 se obtiene una forma limpia, útil para un ítem gráfico.
- **Asimetría**: evita que cambios de semilla parezcan una misma esfera
  escalada.
- **Base plana**: eleva los vértices inferiores a un plano antes de normalizar
  la altura final. El origen local queda en la base de la roca.
- **Conicidad**: valores positivos ensanchan la parte inferior; valores
  negativos dan una roca más pesada arriba.

La malla se reconstruye desde la icosfera original en cada regeneración. Esto
es intencional: pulsar varias veces **Regenerar** no aumenta el desplazamiento.

## Normales

Rock Forge conserva dos niveles de normal:

### Normal de geometría

`mesh.update(calc_edges=True)` calcula las normales de las caras después de
construir la topología. Después se aplica el modo elegido:

- **Facetas planas**: `polygon.use_smooth = False` para conservar la lectura
  triangular low-poly.
- **Suave**: todas las caras se suavizan y el modificador `SR Weighted Normals`
  estabiliza el gradiente.
- **Híbrida**: las caras se suavizan, pero las aristas cuyo ángulo supera
  `Ángulo de arista` se marcan como sharp y el weighted normal las conserva.

El modificador de bisel, si se activa, se coloca antes del weighted normal y es
no destructivo. Blender 5.2 ya no necesita que el addon escriba
`use_auto_smooth`; se usan las propiedades de arista compatibles con la API
actual.

### Normal procedural de material

El material contiene esta cadena visible en el Shader Editor:

```text
Generated
  ├─ SR_MACRO_NOISE ──────────────── SR_ROCK_PALETTE ── color ── Principled
  └─ SR_FINE_NOISE + SR_FRACTURE_VORONOI
                   └─ SR_DETAIL_MIX ── SR_NORMAL_BUMP.Height
                                      SR_NORMAL_BUMP.Normal ── Principled.Normal
```

`Normal Strength` y `Normal Distance` controlan el relieve sin cambiar la
silueta. Es la normal que se ve tanto en Eevee como en Cycles.

### Bake de mapa normal

El operador prepara un `UVMap`, crea una imagen cuadrada en la resolución
indicada, la marca como `Non-Color`, cambia temporalmente el motor a Cycles y
llama a `bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")`. El motor,
la selección y el objeto activo se restauran aunque el bake falle. Tras un bake
correcto la cadena queda:

```text
SR_BAKED_NORMAL_IMAGE → SR_BAKED_NORMAL_MAP → Principled.Normal
```

**Usar normal procedural** vuelve a conectar el Bump. La imagen queda en
`bpy.data.images` para que el usuario pueda guardarla, empacarla o reemplazarla.

## Rendimiento

- Nivel 2 y material procedural: recomendado para scattering y viewport.
- Nivel 3: recomendado para un asset de juego cercano a cámara.
- Nivel 4: reservado para primeros planos o para hornear un mapa y usar después
  una malla más ligera.
- La semilla es un hash local; no se crea ni se serializa una textura de ruido.
