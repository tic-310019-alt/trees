# PCM Studio — guía de usuario

## 1. Preparar el modelo

PCM Studio trabaja con objetos Mesh. Aplica la escala antes de generar el
material, verifica las normales y crea una UV limpia llamada `UVMap` o activa
la UV que quieras usar. Para un personaje con varias piezas, puedes asignar el
material a cada pieza; el atributo de zonas se guarda en las caras de cada
malla.

El atributo técnico es `pcm_zone`, un valor FLOAT en dominio FACE. No es
necesario pintarlo a mano: los operadores de PCM Studio lo crean y escriben al
asignar zonas.

## 2. Crear el material maestro

En **Material Properties → PCM Studio**:

1. Selecciona el preset `Realista` para piel y superficies anatómicas
   físicamente plausibles, o `Sims 4` para colores más limpios, contraste
   controlado y microdetalle estilizado.
2. Pulsa **Crear material**.
3. PCM Studio genera grupos de nodos separados por zona y un grupo maestro que
   mezcla Surface, Base Color, Roughness, Metallic, Normal, Height, AO y los
   canales necesarios para el bake.

La miniatura del material es un nodo de grupo y un Output Material a propósito:
el grafo detallado vive dentro de `PCM_MASTER_<objeto>` y en los grupos
`PCM_Z_<zona>`. Esto mantiene limpio el material principal y permite inspeccionar
cada familia en el Shader Editor.

## 3. Asignar zonas

En Edit Mode:

- Selecciona caras.
- En la lista de zonas elige una zona.
- Pulsa **Asignar caras seleccionadas**.
- Para borrar/reasignar, repite con otra zona.

Zonas incluidas:

| Familia | Zonas |
| --- | --- |
| Humano | Piel corporal, piel facial, extremidades, piel fina |
| Ojos | Iris, esclerótica, córnea, pestañas |
| Boca | Labios, dientes, encías, lengua |
| Queratina | Uñas |
| Pelo | Pelo y pelaje |
| Reptil/ave | Escamas y plumas |
| Animal | Pezuñas/cuerno, hocico/rinario, caparazón, ojo animal, anfibio |
| Libre | Personalizada |

**Proponer zonas** analiza la geometría y devuelve sugerencias con caras,
razón y confianza. Revisa las propuestas antes de aplicarlas, especialmente en
modelos simétricos o con piezas superpuestas.

## 4. Ajustar una zona

Cada receta expone parámetros agrupados por intención: color base, variación,
poros o fibras, microdetalle, rugosidad, aceite/humedad, normal, cavidad y
propiedades específicas de la superficie. Los controles se guardan en las
propiedades del objeto y se resuelven en este orden:

1. Valor personalizado del usuario.
2. Parámetro de la zona.
3. Parámetro de la categoría del preset.
4. Parámetro común del preset.
5. Valor seguro de la zona.

Regenera después de cambios estructurales de zona. Los ajustes pequeños pueden
hacerse directamente en el grupo de nodos generado.

## 5. Diagnóstico antes del bake

Pulsa **Diagnóstico** para comprobar:

- Objeto Mesh y material activo.
- UV activa, cobertura y densidad de texel.
- Caras sin zona o con ids desconocidos.
- Resolución y formato de salida.
- Disponibilidad de nodos/sockets del Blender actual.
- Estado del grupo maestro y de los grupos por zona.

Corrige los errores antes de hornear. Las advertencias de densidad o cobertura
pueden ser intencionales, pero deben revisarse.

## 6. Bake

El motor usa Cycles y un material temporal de emisión para conseguir canales
limpios y repetibles. El material temporal se guarda con nombre
`PCM_BAKE_<prefijo>` y se restaura el material original al finalizar.

### Modos

- **Geometría**: bake con la malla actual.
- **Desplazado**: añade una subdivisión temporal adaptativa para capturar Height
  y relieve; después restaura modificadores y método de desplazamiento.
- **Overlay**: hornea el detalle procedural como normal adicional sin cambiar
  el volumen base.

### Canales

- Base Color — emisión del color, sRGB.
- Normal — Tangent Space, OpenGL o DirectX.
- Roughness — lineal/no color.
- Metallic — lineal/no color.
- AO — Cycles Ambient Occlusion multiplicado por cavidad.
- Height — escala de desplazamiento procedural.
- ORM — R AO, G Roughness, B Metallic.
- Mask — máscara de zona/cavidad cuando está habilitada.

El margen se configura en píxeles y se pasa a `scene.render.bake.margin`.
Asegura suficiente padding para el mipmapping del motor destino.

## 7. Exportación para motores

Selecciona el motor en el panel de exportación. El addon usa sufijos estables,
prefijo `T_`, extensión elegida y un `manifest.json` con:

- objeto y zona de origen;
- mapa y canal;
- resolución, formato y bit depth;
- espacio de color;
- orientación de normal;
- mapeo ORM/mask;
- destino sugerido (Unity, Unreal, Godot o glTF).

En Unreal importa ORM como una textura lineal y conecta R/G/B a AO,
Roughness/Specular y Metallic según el material del proyecto. En Unity usa
normal map como tipo Normal Map y marca sRGB sólo para Base Color y Emission.
Comprueba siempre la convención de normal del proyecto antes de publicar.

## 8. Cambiar el idioma

En **Edit → Preferences → Add-ons → PCM Studio**, selecciona:

- `Español (ES)` — opción predeterminada.
- `English (EN)`.

El cambio se aplica a las etiquetas de la interfaz. Los identificadores de
zonas, atributos de malla y nombres de archivos no se traducen para mantener
compatibilidad entre equipos.

## 9. Solución de problemas

### El material aparece uniforme

Comprueba que las caras tienen `pcm_zone`, que el grupo maestro está conectado
a Surface y que la UV activa tiene datos. Ejecuta Diagnóstico y regenera el
material.

### El bake queda negro o vacío

Asegura que Cycles está disponible, que existe una UV activa y que el objeto
correcto está seleccionado. Revisa la imagen destino y la carpeta de exportación.
El bake requiere permiso de escritura en la carpeta elegida.

### El detalle parece demasiado grande

Aumenta la resolución o la densidad de texel, revisa la escala aplicada del
objeto y ajusta `Escala de detalle` de la zona. En pelaje, fibras y escamas la
escala depende especialmente de la UV.

### El relieve tiene la orientación equivocada

Elige OpenGL o DirectX según el motor. PCM Studio invierte el canal verde como
postproceso para DirectX; no inviertas de nuevo el mapa en el importador.

### Quiero inspeccionar el grafo

Busca `PCM_MASTER_<objeto>` y `PCM_Z_<zona>` en el Shader Editor. Las etiquetas
de los nodos describen la operación y cada grupo expone los canales principales.

## 10. Verificación del paquete

Desde la raíz del repositorio:

```bash
python3 tools/run_checks.py
python3 tools/package.py --check
python3 tools/package.py
```

El paquete instalable queda en `dist/`. No se incluyen tests ni caches de
Python dentro del zip.
