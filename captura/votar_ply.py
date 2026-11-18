"""blender -b --factory-startup -P votar_ply.py -- malla.ply camaras_mascaras.npz salida.ply [umbral] [triangulos]
Version para la malla de OpenMVS ANTES de texturizar: vota, deja la pieza mayor, reduce y exporta PLY para TextureMesh.
Cada vertice se proyecta en todas las fotos; queda si cae dentro de la mascara del plato en al menos `umbral` de las
fotos que lo ven. Una mascara mala no basta para borrar ni para conservar nada."""
import sys

import bmesh
import bpy
import numpy as np

a = sys.argv[sys.argv.index('--') + 1:]
src, npz, dst = a[:3]
umbral = float(a[3]) if len(a) > 3 else 0.5
tris = int(a[4]) if len(a) > 4 else 200000
C = np.load(npz)
K, R, T, M, WH = C['K'], C['R'], C['T'], C['M'], C['WH']

bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
bpy.ops.wm.ply_import(filepath=src)
o = [x for x in bpy.context.scene.objects if x.type == 'MESH'][0]
bpy.context.view_layer.objects.active = o; o.select_set(True)
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = o.data
Vb = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', Vb); Vb = Vb.reshape(-1, 3)


def votos(X):
    dentro = np.zeros(len(X)); vista = np.zeros(len(X))
    for k in range(len(K)):
        Xc = X @ R[k].T + T[k]
        z = Xc[:, 2]
        uv = (Xc @ K[k].T)[:, :2] / np.maximum(z, 1e-9)[:, None] / 4
        u, v = np.floor(uv[:, 0]).astype(int), np.floor(uv[:, 1]).astype(int)
        ok = (z > 0) & (u >= 0) & (v >= 0) & (u < WH[k][0]) & (v < WH[k][1])
        vista += ok
        dentro[ok] += M[k][v[ok], u[ok]]
    return dentro / np.maximum(vista, 1), vista


# glTF Y arriba -> Blender Z arriba: (x, y, z) -> (x, -z, y). Se prueban ambas y gana la que cuadra con las fotos.
muestra = Vb[np.random.default_rng(0).choice(len(Vb), min(20000, len(Vb)), replace=False)]
opciones = {'gltf': lambda V: np.stack([V[:, 0], V[:, 2], -V[:, 1]], 1), 'directo': lambda V: V}
puntaje = {n: float(np.mean(np.prod(votos(f(muestra)), 0))) for n, f in opciones.items()}  # fotos que lo ven dentro del plato
mejor = max(puntaje, key=puntaje.get)
print('COORDENADAS', puntaje, '->', mejor)
f, vista = votos(opciones[mejor](Vb))
print('VISTO por', np.percentile(vista, [10, 50, 90]), 'fotos; VOTO percentiles 10/25/50/75/90:',
      np.round(np.percentile(f, [10, 25, 50, 75, 90]), 2))
fuera = (f < umbral) | (vista < 3)

bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.verts[i] for i in np.where(fuera)[0]], context='VERTS')
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
print(f'BORRADOS {fuera.sum()} de {len(fuera)} vertices; QUEDAN {len(me.polygons)} caras')
if len(me.polygons) > tris:
    d = o.modifiers.new('d', 'DECIMATE'); d.ratio = tris / len(me.polygons)
    bpy.ops.object.modifier_apply(modifier='d')
print('REDUCIDA a', len(o.data.polygons), 'caras')
bpy.ops.wm.ply_export(filepath=dst, export_selected_objects=False, apply_modifiers=True, export_normals=False,
                      export_uv=False, export_colors='NONE', export_triangulated_mesh=True, ascii_format=False)
