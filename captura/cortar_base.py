"""blender -b --factory-startup -P cortar_base.py -- limpio.glb salida.glb
Despues de limpiar.py (Z arriba): borra lo que cuelga DEBAJO del fondo del envase (restos de mesa que la votacion no
quita porque desde las fotos quedan detras del plato) y guarda la textura en JPEG como el resto de platos de la web.
Fondo = altura del 5% mas bajo del borde exterior (vertices mas alejados del centro en cada uno de 36 sectores)."""
import sys

import bmesh
import bpy
import numpy as np

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)
o = [x for x in bpy.context.scene.objects if x.type == 'MESH'][0]
bpy.context.view_layer.objects.active = o; o.select_set(True)
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = o.data
V = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', V); V = V.reshape(-1, 3)

c = np.median(V[:, :2], 0)
d = V[:, :2] - c
r, ang = np.hypot(d[:, 0], d[:, 1]), np.arctan2(d[:, 1], d[:, 0])
sector = ((ang + np.pi) / (2 * np.pi) * 36).astype(int) % 36
borde = np.zeros(len(V), bool)
for s in range(36):
    i = sector == s
    if i.any():
        borde |= i & (r >= np.percentile(r[i], 85))
fondo = np.percentile(V[borde, 2], 5)
alto = np.ptp(V[:, 2])
debajo = V[:, 2] < fondo - 0.01 * alto
print(f'FONDO z={fondo:.4f} (alto {alto:.4f}); BORRAR {debajo.sum()} de {len(V)} vertices debajo del fondo')
assert debajo.mean() < 0.2, 'se iba a borrar demasiado: revisar orientacion'

bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.verts[i] for i in np.where(debajo)[0]], context='VERTS')
# piezas sueltas que quedaron colgando: fuera todo lo que no sea parte de la pieza mayor (por posicion, no por UV)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
bm.faces.ensure_lookup_table()
seen, piezas = set(), []
for f0 in bm.faces:
    if f0.index in seen:
        continue
    pila, pieza = [f0], []
    seen.add(f0.index)
    while pila:
        g0 = pila.pop(); pieza.append(g0)
        for e in g0.edges:
            for g in e.link_faces:
                if g.index not in seen:
                    seen.add(g.index); pila.append(g)
    piezas.append(pieza)
piezas.sort(key=len, reverse=True)
print('PIEZAS', len(piezas), [len(p) for p in piezas[:5]])
bmesh.ops.delete(bm, geom=[g for p in piezas[1:] for g in p], context='FACES')
bm.to_mesh(me); bm.free()
print('QUEDAN', len(me.polygons), 'caras')
for img in bpy.data.images:
    img.file_format = 'JPEG'
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_image_format='JPEG', export_image_quality=95)
