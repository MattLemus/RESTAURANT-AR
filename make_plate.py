# blender -b --factory-startup -P make_plate.py -- piezas/plato.glb
# (o: python3 make_plate.py -- piezas/plato.glb, con el modulo bpy de pip)
# Plato modelado, sin foto, como el plato de los pancakes de la galeria de Apple: forma limpia y porcelana lisa con
# brillo, asi los bordes se ven nitidos a cualquier distancia. Medidas tomadas del plato de ar/fritada.glb:
# 26,2 x 23,5 cm, cuadrado de esquinas redondeadas (superelipse n=5,4), fondo plano y borde que sube hasta 2,2 cm.
import math
import sys
import bpy

dst = sys.argv[sys.argv.index('--') + 1]

A, B, N = 0.1302, 0.1165, 5.4   # semiejes (m) y redondez de las esquinas; el labio sale 0,8% mas
SEGMENTS = 160

# Perfil del plato: (s, altura en cm). s = 0 en el centro y 1 en el borde, en cualquier direccion.
# Va por arriba del centro al borde, redondea el labio y vuelve por abajo; el pie es un anillo que toca la mesa.
PROFILE = [
    (0.10, 0.50), (0.30, 0.50), (0.50, 0.50), (0.56, 0.51), (0.60, 0.54), (0.65, 0.62), (0.70, 0.75),
    (0.75, 0.91), (0.80, 1.10), (0.85, 1.31), (0.90, 1.54), (0.94, 1.76), (0.97, 1.96), (0.99, 2.10),
    (0.998, 2.18), (1.004, 2.17), (1.008, 2.08), (1.008, 1.92), (1.003, 1.80),   # labio redondeado
    (0.99, 1.68), (0.96, 1.48), (0.92, 1.24), (0.87, 0.98), (0.82, 0.76), (0.76, 0.54), (0.70, 0.36),
    (0.64, 0.22), (0.58, 0.11), (0.54, 0.05), (0.525, 0.01), (0.51, 0.0), (0.49, 0.0), (0.475, 0.02),
    (0.465, 0.08), (0.45, 0.12), (0.30, 0.12), (0.10, 0.12),
]
TOP_CENTER, BOTTOM_CENTER = 0.50, 0.12


def outline():
    # superelipse remuestreada por largo de arco, para que los segmentos queden parejos
    dense = []
    for i in range(4096):
        t = 2 * math.pi * i / 4096
        c, s = math.cos(t), math.sin(t)
        dense.append((A * math.copysign(abs(c) ** (2 / N), c), B * math.copysign(abs(s) ** (2 / N), s)))
    acc = [0.0]
    for i in range(1, len(dense) + 1):
        (x0, y0), (x1, y1) = dense[i - 1], dense[i % len(dense)]
        acc.append(acc[-1] + math.hypot(x1 - x0, y1 - y0))
    out, k = [], 0
    for j in range(SEGMENTS):
        target = acc[-1] * j / SEGMENTS
        while acc[k + 1] < target:
            k += 1
        f = (target - acc[k]) / (acc[k + 1] - acc[k])
        (x0, y0), (x1, y1) = dense[k], dense[(k + 1) % len(dense)]
        out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return out


edge = outline()
verts, faces, uvs = [], [], []
for s, h in PROFILE:
    for ex, ey in edge:
        verts.append((ex * s, ey * s, h / 100))
top_c = len(verts); verts.append((0, 0, TOP_CENTER / 100))
bot_c = len(verts); verts.append((0, 0, BOTTOM_CENTER / 100))
ring = lambda i, j: i * SEGMENTS + j % SEGMENTS
for i in range(len(PROFILE) - 1):
    for j in range(SEGMENTS):
        faces.append((ring(i, j), ring(i + 1, j), ring(i + 1, j + 1), ring(i, j + 1)))
last = len(PROFILE) - 1
for j in range(SEGMENTS):
    faces.append((top_c, ring(0, j), ring(0, j + 1)))
    faces.append((bot_c, ring(last, j + 1), ring(last, j)))

mesh = bpy.data.meshes.new('plato')
mesh.from_pydata(verts, [], faces)
mesh.update()
for p in mesh.polygons:
    p.use_smooth = True

# UV vista desde arriba para la cara de arriba (ahi va la sombra de la comida, que se hornea al armar el plato);
# la cara de abajo no se ve y va toda a una esquina vacia de la textura
uv = mesh.uv_layers.new(name='UVMap')
underside_from = PROFILE.index((1.003, 1.80)) + 1   # despues del labio empieza la cara de abajo
for poly in mesh.polygons:
    for li in poly.loop_indices:
        vi = mesh.loops[li].vertex_index
        x, y, z = verts[vi]
        below = vi == bot_c or (vi < top_c and vi // SEGMENTS >= underside_from)
        uv.data[li].uv = (0.995, 0.995) if below else (0.5 + x / 0.27, 0.5 + y / 0.27)

mat = bpy.data.materials.new('porcelana')
mat.use_nodes = True
mat.use_backface_culling = True   # plato cerrado: una sola cara
bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
bsdf.inputs['Base Color'].default_value = (0.855, 0.838, 0.807, 1)   # blanco calido (#EEECE8)
bsdf.inputs['Roughness'].default_value = 0.18
bsdf.inputs['Metallic'].default_value = 0.0
mesh.materials.append(mat)

for o in list(bpy.context.scene.objects):   # la escena de inicio trae cubo, camara y luz
    bpy.data.objects.remove(o)
obj = bpy.data.objects.new('plato', mesh)
bpy.context.scene.collection.objects.link(obj)
print('PLATO', len(mesh.vertices), 'verts', sum(len(p.vertices) - 2 for p in mesh.polygons), 'tris',
      'size cm', [round(d * 100, 2) for d in obj.dimensions])

bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_cameras=False, export_lights=False)
print('EXPORTED', dst)
