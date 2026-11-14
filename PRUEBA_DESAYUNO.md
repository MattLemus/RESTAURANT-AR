# Captura inteligente y reconstrucción conservadora

## Flujo actual en Android y Windows

1. Conecta el teléfono por USB y haz doble clic en `ABRIR_ESCANER.bat`. Si sigue abierta la consola del iniciador anterior, ciérrala con Ctrl+C una vez y abre el BAT de nuevo. El BAT prepara el enlace y abre Chrome en el teléfono.
2. Espera **Captura sin cable lista**. Desconecta el teléfono y usa el capturador en el mismo Chrome. Las fotos se guardan en ese navegador hasta que las envías.
3. Elige 15, 24 o 34 posiciones para repartir la vuelta. Marca que el plato está entero, toca **Empezar** y sigue la indicación sobre la imagen. Puedes pasar a diagonal o a ras del plato en cualquier momento. **Listo, terminar captura** abre el panel de envío.
4. Reconecta el teléfono, abre el BAT y pulsa **Enviar y generar 3D**. Espera el mensaje de originales recibidos. El envío compara el SHA-256 de cada archivo con el recibido en la PC.
5. Si el trabajo pide desconectar internet en la PC, apaga su Wi-Fi y desconecta Ethernet. El trabajo empieza automáticamente cuando Windows deja de mostrar una ruta por defecto. Puedes quitar el cable del teléfono una vez recibidos los originales.
6. El modelo se escribe en `captura/trabajos/<sesión>/<ejecución>/dense/prueba_3d.glb`. La pantalla muestra su ruta y un enlace de descarga al reconectar el teléfono. El GLB incluye el PNG de textura sin volver a comprimirlo.

El envío automático usa las fotos aceptadas a resolución completa y evita la reducción de la prueba inicial. Puede tardar más y consumir más RAM. La reconstrucción sigue dependiendo de la cobertura de las fotos y puede incluir la mesa. Las instrucciones históricas de abajo sirven para el proceso manual y los demás motores.

Para una copia nueva, prepara Python con `PREPARAR_ESCANER.ps1` si trabajas en la copia que ya incluye ese script, o crea `.venv` con `python -m venv .venv` e instala `requirements-captura-local.txt` con `.venv\Scripts\python.exe -m pip install -r requirements-captura-local.txt`. Para reconstruir con el botón, extrae [OpenMVS para Windows x64](https://github.com/cdcseacave/openMVS/releases/tag/v2.4.0) en `captura/trabajos/_runtime/openmvs/` de forma que exista `vc17/x64/Release/TextureMesh.exe` dentro de esa carpeta. El BAT busca `adb.exe` en el proyecto, Descargas o PATH.

El flujo local USB permite enviar y reconstruir. Si abres el capturador desde GitHub Pages, podrás capturar e inspeccionar los originales en ese navegador. El origen de almacenamiento de GitHub Pages es diferente al de `localhost`, así que para usar el flujo del BAT empieza la sesión desde la página que abre el iniciador.

## Arrancar en la computadora

En PowerShell, desde la carpeta del proyecto:

```powershell
.\INICIAR_CAPTURADOR.ps1
```

Alternativa sin script PowerShell:

```powershell
.\.venv\Scripts\python.exe captura/servidor.py
```

Abrir [http://localhost:8765/capturar.html](http://localhost:8765/capturar.html). No se abre ningún túnel ni se publica nada. Mantener la consola abierta; Ctrl+C detiene el servidor. Solo se sirven el capturador y sus dos scripts, junto con las rutas de subida.

### Android por USB, opción sencilla sin certificado

1. Instalar Android SDK Platform Tools desde su fuente oficial y habilitar depuración USB en el teléfono.
2. Conectar por USB y aceptar en el teléfono la autorización de esta computadora.
3. En otra consola ejecutar, usando la ruta real de `adb.exe`:

```powershell
& 'C:\ruta\platform-tools\adb.exe' devices
& 'C:\ruta\platform-tools\adb.exe' reverse tcp:8765 tcp:8765
```

4. En Chrome del teléfono abrir **http://localhost:8765/capturar.html** y permitir la cámara. `localhost` aquí funciona gracias al enlace USB.

También puedes indicar `-Adb 'C:\ruta\platform-tools\adb.exe'` al iniciador. No se encontró adb en PATH durante esta implementación.

### Android/iPhone por Wi-Fi

La cámara del navegador necesita un origen seguro. Abrir `http://IP-DE-LA-PC:8765` normalmente no basta. Usa un certificado HTTPS válido y confiable para el teléfono, correspondiente al nombre o IP de acceso:

```powershell
.\INICIAR_CAPTURADOR.ps1 -BindAddress 0.0.0.0 -Certificate 'C:\certs\local.pem' -PrivateKey 'C:\certs\local-key.pem'
```

Abre `https://NOMBRE-O-IP-DEL-CERTIFICADO:8765/capturar.html` en la misma red. La configuración de confianza del certificado y, si hace falta, el permiso del firewall requieren preparación en tus dispositivos. No se modificaron aquí. No hace falta ARCore.

Si ImageCapture no funciona en ese navegador, la página lo informa y ofrece **Importar foto original** con cámara nativa. No promete automatización de alta resolución donde no existe la API. No sustituye fotografías por capturas de video.

## Prueba del desayuno

1. Limpia la lente. Usa luz natural abundante y difusa, cerca de una ventana, evitando sol directo, sombras móviles y reflejos. No uses flash, zoom digital ni filtros. Deja enfriar vapor intenso.
2. Elige un plato con alimentos de textura visible. Mantén la comida inmóvil durante todo el escaneo. Evita empezar con líquidos brillantes, cristal o ingredientes que se muevan.
3. Mide el ancho del plato en centímetros y anótalo. Deja espacio para caminar alrededor sin cambiar la iluminación. Si usas una base, elige ese modo explícitamente y mantén la cámara fija.
4. Selecciona **Caminar alrededor · plato fijo**. Encaja el plato completo dentro del óvalo verde, sin cortar el borde ni ingredientes. El encuadre depende de tu confirmación; no existe un detector semántico de platos.
5. Confirma el encuadre y pulsa Empezar. Completa **34 posiciones altas, 34 medias y 34 bajas**. Desde cada posición: detente, mantén quieto el teléfono durante al menos un segundo y espera la foto automática.
6. Después de una foto válida avanza aproximadamente **11 grados** alrededor del plato y vuelve a detenerte. No gires solamente la muñeca desde el mismo lugar. En una base: gira unos 11 grados, retira la mano y detén la base.
7. Los puntos verdes corresponden a objetivos con fotografía validada y guardada. No miden tu posición espacial. Si no hay suficiente cambio visual, ajusta el ángulo. **Confirmar posición aproximada** sirve para corregir la guía cuando la apariencia cambia poco; no evita el rechazo de duplicados ni los controles de imagen.
8. Cada zona nueva se pausa para confirmar otra vez el encuadre y ajustar la altura. Sin sensor útil, sigue la guía visual; con acelerómetro, el ángulo es aproximado y puede necesitar calibración según el teléfono. Si la inclinación indicada no corresponde a lo que ves, abre Corregir guía de altura, desactiva el sensor y sigue la guía visual; documenta el dispositivo para calibrarlo.
9. Ante rechazo, el objetivo sigue pendiente. Corrige luz/enfoque/ángulo y pulsa Reintentar. Una foto rechazada queda archivada, pero no cuenta para la reconstrucción. Puedes pausar, revisar originales y reabrir cualquier posición aceptada desde la galería.
10. Al terminar, pulsa **Reenviar pendientes** y **Descargar informe**. Confirma que los originales estén en la PC antes de cerrar o borrar datos del navegador. Si trabajaste sin servidor, descarga cada original desde la galería y el informe; ponlos juntos en una carpeta por sesión. El procesador reconoce `manifest.json` y también un único archivo `*_informe.json`.

Las fotos reales deben tener al menos 5 MP y un lado largo de 2400 px. Se muestran resolución solicitada, resolución recibida y tamaño. Las capacidades máximas de ancho/alto no siempre forman una combinación admitida; si falla la solicitud se reintenta `takePhoto()` sin ajustes, se registra el caso y se comprueba la foto real. Si llega por debajo del mínimo se rechaza. Si llega con menos píxeles de los solicitados, se informa para compararla con la cámara nativa.

## Qué se guarda y qué significa la validación

- `captura/fotos/<sesion>/`: originales recibidos sin recodificar, metadatos de dimensiones/hash y `manifest.json` con los objetivos, rechazos, repeticiones y métricas. Reenviar un mismo archivo es idempotente; un archivo distinto no sobrescribe el original.
- IndexedDB del teléfono: todos los blobs recibidos, también los rechazados o sustituidos por repetición. El progreso se acepta después de completar esa escritura. La misma sesión se recupera al recargar en el mismo navegador/origen. Cambiar de navegador o URL no comparte esos datos.
- No hay garantía de retención si el sistema borra almacenamiento del navegador o se llena el dispositivo. Un error de almacenamiento no hace avanzar el objetivo. Prioriza envío a la PC y revisa espacio libre; 102 fotos pueden superar 1 GB.
- Se evalúan luminancia, saturación extrema, contraste, gradientes, detalle de bordes y diferencias visuales, además del movimiento angular cuando está disponible. La estabilidad compara muestras consecutivas y la apariencia al inicio de la espera para evitar disparar durante una deriva lenta.
- Estas métricas no garantizan enfoque óptico perfecto, velocidad de obturación, exposición del sensor ni ausencia de ruido. El navegador no entrega confirmación universal de enfoque. Los modos automáticos se solicitan cuando existen y se registran; no se marcan como confirmados por haber solicitado una restricción.
- El encuadre usa una confirmación humana y señales de contraste; no hay detección fiable de la silueta ni seguimiento espacial 3D. Tampoco se certifica solapamiento o un ángulo exacto. Revisa los detalles al 100% antes de retirar el plato.

## Preparar las herramientas de reconstrucción

```powershell
.\.venv\Scripts\python.exe captura/diagnostico.py
python -m pip --python .venv/Scripts/python.exe install -r requirements-captura.txt
```

La descarga inicial del modelo de rembg también necesita conexión a internet. Instala las aplicaciones desde sus distribuidores oficiales y configura sus rutas reales en esta misma consola; no son URLs ni rutas de ejemplo que deban copiarse literalmente:

```powershell
$env:REALITYSCAN_EXE = 'C:\ruta\RealityScan.exe'
$env:OPENMVS_DIR = 'C:\ruta\OpenMVS'
$env:BLENDER_EXE = 'C:\ruta\blender.exe'
$env:COLMAP_EXE = 'C:\ruta\colmap.exe'
```

RealityScan necesita GPU compatible y su configuración/licencia correspondiente. El modo High Detail puede necesitar considerable memoria, disco y tiempo; no se promete un tiempo de finalización. Se detiene con un mensaje útil si faltan ejecutables.

### Ruta RealityScan, preferida para la prueba de geometría

Revisa en RealityScan la configuración de reconstrucción y exportación: máscaras activas para alineación/malla, resolución completa, sin simplificación y exportación PLY binaria triangular con XYZ y RGB float, como espera el adaptador existente. Exporta la configuración global a `captura/config_desayuno.rsconfig`. Una forma de exportar los ajustes que hayas revisado en la aplicación es:

```powershell
& $env:REALITYSCAN_EXE -exportGlobalSettings "$PWD\captura\config_desayuno.rsconfig" -quit
```

Cerrar primero otra instancia si la aplicación lo requiere. No uses un archivo de configuración desconocido. El script requiere esta entrada explícita, guarda su copia/hash y exporta los ajustes efectivos de la ejecución. High Detail usa resolución completa; además se establece downscale por imagen a 1 y se fijan claves críticas. Los restantes ajustes provienen de ese archivo revisado, no de preferencias persistentes ocultas.

Sustituye la sesión por el nombre real que muestra el capturador y 26 por tu medida:

```powershell
.\.venv\Scripts\python.exe captura/procesar_rs.py captura/fotos/SESION_REAL captura/trabajos/desayuno_v2 26 --mode walk --rs-config captura/config_desayuno.rsconfig
```

El primer intento prepara RGB y máscaras y **se detiene antes de reconstruir** para que las revises. Comprueba cada máscara en `captura/trabajos/desayuno_v2/mascaras/`: blanco debe incluir todo el plato y la comida; negro excluye fondo y manos. Corrige los PNG sin cambiar dimensiones. El script no erosiona contornos ni descarta componentes pequeños. La segmentación automática puede equivocarse: aprobarla a ciegas compromete el resultado.

Después de revisar, repite:

```powershell
.\.venv\Scripts\python.exe captura/procesar_rs.py captura/fotos/SESION_REAL captura/trabajos/desayuno_v2 26 --mode walk --rs-config captura/config_desayuno.rsconfig --approve-masks
```

`--mode turntable` identifica una captura de base giratoria. No mezcles captura caminando y giratoria en una misma sesión. Las máscaras importadas siguen el esquema oficial `foto.png.mask.png`, separadas del RGB intacto. OpenMVS textura las fotografías exportadas sin distorsión; no se reactiva el texturizado de RealityScan que anteriormente falló.

### Ruta COLMAP + OpenMVS

```powershell
.\.venv\Scripts\python.exe captura/procesar.py captura/fotos/SESION_REAL captura/trabajos/desayuno_colmap_v2 26 --mode walk
# Revisar máscaras y repetir con --approve-masks.
```

Esta alternativa conserva RGB completos y máscaras para extraer puntos de COLMAP. La propagación de máscaras hacia la densificación de OpenMVS aún no está implementada: puede reconstruir parte de la mesa y **no es la opción recomendada para una base giratoria en esta versión**. No se sustituye esa limitación pintando negro el RGB. La densificación solicita resolución completa y puede exigir mucha memoria. Comprueba la compatibilidad de las opciones con el OpenMVS instalado a través de sus registros/ayuda si usas otra versión.

### Salidas y reanudación

En la carpeta de trabajo elegida:

| Archivo/carpeta | Uso |
| --- | --- |
| `originales/` | Copias exactas de las fotos seleccionadas, con EXIF intacto |
| `imagenes/` | RGB orientados, PNG sin pérdida, sin reducir dimensiones |
| `calidad_fotos.json` | Correspondencia original/RGB, dimensiones, métricas y SHA-256 |
| `mascaras/` y `rs_inputs/` | Máscaras independientes y capas importadas a RealityScan |
| `maestro.rsproj` y `malla.ply` | Proyecto y geometría de alta calidad antes de texturizar, ruta RS |
| `colmap/malla.ply` | Malla transformada para OpenMVS, sin sustitución XY ni eliminación de caras |
| `maestro_texturizado.glb` | Copia del primer GLB texturizado, antes de limpieza/exportación móvil |
| `limpio.glb` | Modelo orientado mediante cámaras, conservando superficie y materiales |
| `web.glb` | Modelo centrado y escalado a centímetros, si se proporcionó el ancho |
| `vista.png` y `vista.png.0.png` a `.4.png` | Vistas de control generadas por Blender |
| `logs/` | Registro separado por comando, argumentos y códigos de salida |

No se cierran agujeros automáticamente ni se inventa la base. AR puede mostrar una superficie abierta. Si hay mesa o base no deseada, recorta localmente una copia en un editor 3D y conserva el maestro; esta versión no inventa un recorte automático preciso.

Por defecto `web.glb` conserva detalle y no activa Draco. Para experimentar con una versión móvil reducida, usa **otro trabajo** con `--mobile-tris 200000`; no sobrescribas el maestro. `sin_nivelar` ahora evita realmente volver a orientar el plato. No se fuerzan texturas a JPEG de menor calidad. Los visores y el menú AR no se modificaron: prueba primero el GLB de trabajo antes de sustituir manualmente un modelo del menú.

El trabajo lleva una marca de versión. No se reutilizan automáticamente carpetas antiguas que puedan contener mallas cerradas como relieve. Para otros ajustes, fuente de fotos o máscaras ya utilizadas, crea otra carpeta. No borres etapas para comparar.

## Identificar dónde se pierde calidad

1. **Captura:** abre varios originales al 100%. Busca bordes dobles, arroz/pan sin detalle, reflejos quemados y fondos movidos. Compara foto real con preview: el preview no valida el archivo nativo. Mira dimensiones, rechazos y métricas del informe; una mediana buena no garantiza que una imagen concreta esté bien.
2. **Máscaras:** compara cada PNG con su RGB. Un ingrediente negro en la máscara quedará excluido aunque esté perfectamente fotografiado. Las copias RGB deben seguir mostrando el fondo original, nunca un relleno negro artificial.
3. **Alineación/geometría:** abre `maestro.rsproj` o `malla.ply` sin texturas. Si el volumen ya está deformado, el problema está antes del GLB/texturizado. Revisa cámaras no alineadas, huecos de cobertura y registro de reconstrucción. El proceso se detiene si menos del 70% de fotos se alinean; aun superar ese porcentaje no garantiza cobertura completa.
4. **Texturizado:** si la malla se ve correcta sin textura pero `maestro_texturizado.glb` tiene parches, negro o borrosidad, revisa proyecciones de cámara, máscaras, iluminación entre fotos y atlas. El fondo negro artificial se eliminó como fuente potencial de contaminación, pero no se ha demostrado que fuera la única causa. Hay antecedentes documentados de errores de máscaras y resolución en OpenMVS; verificar la versión instalada forma parte de la prueba.
5. **Exportación móvil:** compara maestro, `limpio.glb` y `web.glb` con iluminación semejante. Si solo el último pierde detalle, revisa reducción, UV y materiales. Una diferencia de iluminación entre visores puede cambiar la apariencia incluso sin cambios en la textura. No se atribuye el problema a Draco/GLB sin esa comparación.

El nivelado global/local de costuras sigue apagado por el fallo negro documentado en esta PC. Todavía pueden verse costuras. Falta una comparación controlada con fotografías reales y el binario instalado para diagnosticar su causa y decidir si es seguro reactivarlo; no se activó ninguna opción experimental.

## Archivos intervenidos

Modificados: `capturar.html`, `captura/servidor.py`, `captura/procesar.py`, `captura/procesar_rs.py`, `captura/cerrar.py`, `captura/limpiar.py`, `make_web_glb.py`, `glb_to_usdz.py`.

Añadidos: `captura/calidad.js`, `captura/capturador.js`, `captura/diagnostico.py`, `INICIAR_CAPTURADOR.ps1`, `requirements-captura.txt`, esta guía y las pruebas `tests/test_capture_quality.cjs`, `tests/test_capture_integration.cjs`, `tests/test_capture_pipeline.py`. El respaldo mantiene las versiones anteriores de los ocho archivos modificados.

El menú, las páginas AR, sus scripts y los GLB/USDZ existentes no fueron editados. La comprobación de archivos HTML/JS/modelos de la raíz modificados desde el inicio solo identificó `capturar.html`.

## Verificación reproducible

```powershell
node --check captura/calidad.js
node --check captura/capturador.js
node --test tests/test_capture_quality.cjs tests/test_capture_integration.cjs
python -m compileall -q captura make_web_glb.py glb_to_usdz.py
$env:SCAN_SOCKETLESS_TESTS = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest tests -q
```

**Resultado: 29 pruebas Python y 18 pruebas JavaScript aprobadas.** Sintaxis Python/JavaScript/PowerShell comprobada. Informe Python: `test-results/quality-tests.xml`. La prueba del bucle de captura ejecuta el controlador con imágenes/almacenamiento simulados: dispara después de 1000 ms estables y no dispara durante una deriva visual lenta.

Las pruebas nuevas cubren temporización, movimiento, rechazo sin avance, almacenamiento antes de aceptación, errores de almacenamiento, duplicados, resolución mínima, conservación de originales/EXIF/RGB, no sobrescritura, capas de máscara y orquestación RS con ejecutables simulados. Las pruebas existentes del estudio COLMAP también se ejecutan. Ninguna prueba simulada acredita calidad fotogramétrica física.

Pendiente en celular: permisos y cámara trasera correcta, resolución/foco reales, orientación del acelerómetro, estabilidad y temperatura durante 102 fotos, almacenamiento, reenvío tras desconexión y revisión visual de reconstrucción/textura. Probar primero 3–5 fotos antes del recorrido completo.

## Fuentes oficiales consultadas

- [RealityScan: comandos de reconstrucción](https://rshelp.capturingreality.com/en-US/tutorials/commandline_2.htm)
- [RealityScan: ajustes y High Detail](https://rshelp.capturingreality.com/en-US/appbasics/modelsettings.htm)
- [RealityScan: claves de configuración](https://rshelp.capturingreality.com/en-US/tutorials/setkeyvaluetable.htm)
- [RealityScan: máscaras](https://rshelp.capturingreality.com/en-US/tools/mask.htm) y [capas de imagen](https://rshelp.capturingreality.com/en-US/tools/imglayers.htm)
- [ImageCapture, especificación W3C](https://www.w3.org/TR/image-capture/)
- [OpenMVS: controles de limpieza de malla](https://github.com/cdcseacave/openMVS/blob/master/apps/ReconstructMesh/ReconstructMesh.cpp)
- [OpenMVS: incidencia de máscaras/resolución en textura](https://github.com/cdcseacave/openMVS/issues/1094)
