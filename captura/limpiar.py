# blender -b --factory-startup -P limpiar.py -- modelo.glb camaras.json limpio.glb
# El modelo de OpenMVS sale torcido, con la mesa y restos del fondo. Lo pone derecho (las fotos rodean el plato en un
# circulo: su eje es la vertical), corta la mesa y deja solo el plato. make_web_glb.py despues lo centra y le da su
# ancho real. Tambien avisa si a algun lado del plato le faltan fotos.
import json
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

src, cj, dst = sys.argv[sys.argv.index('--') + 1:][:3]
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
# unir los vertices repetidos en las costuras de la textura: si no, cada isla de la textura es una pieza suelta
bpy.ops.import_scene.gltf(filepath=src, merge_vertices=True)
ms = [x for x in bpy.context.scene.objects if x.type == 'MESH']
for x in bpy.context.scene.objects:
    x.select_set(x.type == 'MESH')
bpy.context.view_layer.objects.active = ms[0]
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
if len(ms) > 1:
    bpy.ops.object.join()
o = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for x in [x for x in bpy.context.scene.objects if x != o]:
    bpy.data.objects.remove(x)

# glTF guarda Y arriba y Blender usa Z arriba: el importador cambia (x, y, z) -> (x, -z, y); a las fotos igual
cams = json.load(open(cj))
C = np.array([[c['centro'][0], -c['centro'][2], c['centro'][1]] for c in cams])
D = np.array([[c['mira'][0], -c['mira'][2], c['mira'][1]] for c in cams])
up = np.linalg.svd(C - C.mean(0))[2][2]
if (D @ up).mean() > 0:  # las fotos miran hacia abajo, al plato
    up = -up
# el punto al que miran todas las fotos = el plato
P = [np.eye(3) - np.outer(d, d) for d in D]
p = np.linalg.solve(sum(P), sum(q @ c for q, c in zip(P, C)))
x = np.cross(up, [1, 0, 0] if abs(up[0]) < 0.9 else [0, 1, 0])
x /= np.linalg.norm(x)
R = np.array([x, np.cross(up, x), up])
M = np.eye(4)
M[:3, :3], M[:3, 3] = R, -R @ p
o.data.transform(Matrix(M.tolist()))

Cp = (C - p) @ R.T
dist = np.median(np.linalg.norm(Cp, axis=1))
elev = np.degrees(np.arcsin(Cp[:, 2] / np.linalg.norm(Cp, axis=1)))
az = np.sort(np.degrees(np.arctan2(Cp[:, 1], Cp[:, 0])) % 360)
gaps = np.diff(np.append(az, az[0] + 360))
print(f'FOTOS {len(cams)}: altura {elev.mean():.0f} grados (de {elev.min():.0f} a {elev.max():.0f}), '
      f'hueco mas grande entre fotos {gaps.max():.0f} grados')
for i in np.where(gaps > 15)[0]:
    print(f'FALTAN FOTOS entre {az[i]:.0f} y {az[(i + 1) % len(az)]:.0f} grados ({gaps[i]:.0f} grados sin foto)')

me = o.data
n = len(me.vertices)
V = np.empty(n * 3)
me.vertices.foreach_get('co', V)
V = V.reshape(-1, 3)
Nz = np.empty(n * 3)
me.vertex_normals.foreach_get('vector', Nz)
Nz = Nz.reshape(-1, 3)[:, 2]
h, rad = V[:, 2], np.hypot(V[:, 0], V[:, 1])
print(f'MALLA {n} vertices, {len(me.polygons)} caras; distancia de las fotos {dist:.3f}')

# la mesa: la superficie plana horizontal mas baja que se extiende mas alla del plato
flat = np.abs(Nz) > 0.9
paso = 0.005 * dist
bins = np.floor((h[flat] - h[flat].min()) / paso).astype(int)
cuenta = np.bincount(bins)
corte = None
# 1%: la base giratoria asoma poco debajo del plato; con 5% se la saltaba y cortaba la bandeja
for b in np.where(cuenta >= 0.01 * flat.sum())[0]:
    h0 = h[flat].min() + (b + 0.5) * paso
    mesa = flat & (np.abs(h - h0) < 1.5 * paso)
    h0 = np.median(h[mesa])
    margen = max(3 * np.std(h[mesa]), paso)
    # la mesa (o la base giratoria) llega al borde del modelo; el fondo del plato, que tambien es plano, queda adentro
    r_mesa, r_todo = np.percentile(rad[mesa], 90), np.percentile(rad, 90)
    print(f'plano a {h0 / dist:.3f}: radio {r_mesa / dist:.3f} vs todo el modelo {r_todo / dist:.3f}')
    if r_mesa > 0.9 * r_todo:
        corte = h0 + margen
    break
if len(sys.argv) > sys.argv.index('--') + 4 and sys.argv[-1] == 'sin_corte':  # si el corte se comio el plato
    corte = None
if corte is None:
    print('MESA no encontrada: no corto nada')
    corte = h.min() - 1

bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < corte], context='VERTS')
# piezas sueltas: queda la mas grande (el plato) y lo que este dentro de su radio
bm.faces.ensure_lookup_table()
pieza, tam = {}, []
for f in bm.faces:
    if f in pieza:
        continue
    k, pila = len(tam), [f]
    pieza[f] = k
    tam.append([])
    while pila:
        g = pila.pop()
        tam[k].append(g)
        for v in g.verts:
            for e in v.link_faces:
                if e not in pieza:
                    pieza[e] = k
                    pila.append(e)
big = max(range(len(tam)), key=lambda k: len(tam[k]))
rv = np.array([math.hypot(v.co.x, v.co.y) for f in tam[big] for v in f.verts])
r_max = np.percentile(rv, 99.5)
h_max = np.percentile([v.co.z for f in tam[big] for v in f.verts], 99.5)
fuera = []
for k, fs in enumerate(tam):
    co = [v.co for f in fs for v in f.verts]
    # ruido: fuera del radio del plato o flotando por encima de todo
    if k != big and (np.mean([math.hypot(c.x, c.y) for c in co]) > r_max or min(c.z for c in co) > h_max):
        fuera += fs
bmesh.ops.delete(bm, geom=fuera, context='FACES')
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
print(f'LIMPIO: {len(tam)} piezas, plato {len(tam[big])} caras, borradas {len(fuera)} caras de afuera, '
      f'quedan {len(bm.faces)}; radio del plato {r_max / dist:.3f}')
# nivelar por el borde del plato: el aro de afuera es plano. El eje del circulo de fotos falla si el plato se giro a
# mano (las fotos no forman un circulo) y quedaba ~8 grados torcido.
for _ in range(3):
    V = np.array([v.co[:] for v in bm.verts])
    r = np.hypot(V[:, 0] - np.median(V[:, 0]), V[:, 1] - np.median(V[:, 1]))
    aro = V[r > np.percentile(r, 92)]
    n = np.linalg.svd(aro - aro.mean(0))[2][2]
    n = n if n[2] > 0 else -n
    ang = np.degrees(np.arccos(min(1.0, n[2])))
    if ang < 0.2 or ang > 30:  # mas de 30: el aro no es plano (no es un plato), no se toca
        break
    bm.transform(Matrix(np.vstack([np.hstack([np.array(Vector(n).rotation_difference(Vector((0, 0, 1))).to_matrix()), [[0], [0], [0]]]), [0, 0, 0, 1]]).tolist()))
    print(f'NIVELAR por el borde del plato: {ang:.1f} grados')
bm.to_mesh(me)
bm.free()
# OpenMVS guarda la textura como material sin luz; make_web_glb.py y glb_to_usdz.py esperan uno normal (Principled)
for i, m in enumerate(me.materials):
    tex = next(n.image for n in m.node_tree.nodes if n.type == 'TEX_IMAGE')
    nuevo = bpy.data.materials.new(m.name)
    nuevo.use_nodes = True
    nt = nuevo.node_tree
    b = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = tex
    nt.links.new(t.outputs['Color'], b.inputs['Base Color'])
    b.inputs['Metallic'].default_value = 0  # la comida no es metal
    b.inputs['Roughness'].default_value = 0.8
    me.materials[i] = nuevo
# sin normales: con normales por cara make_web_glb.py no puede volver a unir los vertices (quedaba en 464k pedazos)
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_normals=False)
print('GUARDADO', dst)
