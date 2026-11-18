# Quita los triangulos que nunca se ven en el AR (bajo la comida, debajo del plato) mirando el plato desde todos los lados
# y alturas con que alguien lo rodea en la mesa, desde 6 grados sobre la mesa. Un recorte mirando solo desde arriba dejo
# el borde de la salsa en sierra y una franja blanca en la orilla del plato (se ven al mirar de lado).
#   blender -b --factory-startup -P visibles_glb.py -- entrada.glb salida.glb [conservar.glb]
# conservar.glb: un recorte anterior del mismo plato; sus caras se quedan y solo se agregan las que se ven y faltaban.
# Las imagenes de la salida son los mismos bytes de la entrada; la malla sale con la misma compresion que make_web_glb.py.
import math
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sombras_glb import partes, reempacar, vista  # noqa: E402

LADO = 2048  # pixeles por vista
ALTURAS = (6, 12, 20, 30, 45, 60, 75, 90)  # grados sobre la mesa
GIROS = 18  # vistas alrededor del plato (cada 20 grados)
DISTANCIAS = (0.25, 0.5)  # m al centro del plato: de cerca y a un brazo

a = sys.argv[sys.argv.index('--') + 1:]
src, dst = a[0], a[1]
conservar = a[2] if len(a) > 2 else None
if Path(dst).exists() or Path(src).resolve() == Path(dst).resolve():
    raise ValueError('Usa una salida nueva, distinta de la entrada')


def importar(p):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    piezas = [o for o in bpy.data.objects if o not in antes and o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in piezas:
        o.select_set(True)
    bpy.context.view_layer.objects.active = piezas[0]
    if len(piezas) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def centros(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    c = [f.calc_center_median() for f in bm.faces]
    bm.free()
    return c


bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
plato = importar(src)
me = plato.data
nf = len(me.polygons)
visto = np.zeros(nf, bool)

# cada cara pinta su numero (3 bytes) sin luz: el pixel dice que cara se ve ahi
ids = np.arange(nf, dtype=np.int64)
rgb = np.stack([(ids >> s) & 255 for s in (0, 8, 16)], 1).astype(np.float32) / 255
me.attributes.new('fid', 'FLOAT_VECTOR', 'FACE').data.foreach_set('vector', rgb.ravel())
originales = [s.material for s in plato.material_slots]
m = bpy.data.materials.new('fid')
if m.node_tree is None:
    m.use_nodes = True
n, ln = m.node_tree.nodes, m.node_tree.links
n.clear()
at = n.new('ShaderNodeAttribute')
at.attribute_name = 'fid'
em = n.new('ShaderNodeEmission')
ln.new(at.outputs['Vector'], em.inputs['Color'])
ln.new(em.outputs[0], n.new('ShaderNodeOutputMaterial').inputs['Surface'])
for s in plato.material_slots:
    s.material = m

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.samples = 1
sc.cycles.use_denoising = False
sc.cycles.pixel_filter_type = 'BOX'
sc.cycles.filter_width = 0.01  # un rayo por pixel: nunca mezcla dos caras
sc.render.use_persistent_data = True  # la escena no cambia entre vistas, solo la camara
sc.render.film_transparent = True  # alfa 0 = fondo
sc.render.resolution_x = sc.render.resolution_y = LADO
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = 'Raw'
sc.render.image_settings.file_format = 'OPEN_EXR'
sc.render.image_settings.color_depth = '16'
sc.render.image_settings.color_mode = 'RGBA'
pr = bpy.context.preferences.addons['cycles'].preferences
for tipo in ('OPTIX', 'CUDA'):
    try:
        pr.compute_device_type = tipo
    except TypeError:
        continue
    pr.get_devices()
    if any(d.type == tipo for d in pr.devices):
        for d in pr.devices:
            d.use = d.type == tipo
        sc.cycles.device = 'GPU'
        break
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.angle = math.radians(70)
cam.data.clip_start, cam.data.clip_end = 0.005, 5
caja = [plato.matrix_world @ Vector(c) for c in plato.bound_box]
centro = Vector((sum(v.x for v in caja) / 8, sum(v.y for v in caja) / 8, min(v.z for v in caja) + 0.02))

vistas = [(d, alt, 2 * math.pi * k / GIROS) for d in DISTANCIAS for alt in ALTURAS for k in range(1 if alt == 90 else GIROS)]
print(f'{nf} caras, {len(vistas)} vistas, render en', sc.cycles.device)
with tempfile.TemporaryDirectory() as t:
    sc.render.filepath = str(Path(t) / 'v.exr')
    for i, (d, alt, az) in enumerate(vistas):
        e = math.radians(alt)
        cam.location = centro + Vector((d * math.cos(e) * math.cos(az), d * math.cos(e) * math.sin(az), d * math.sin(e)))
        cam.rotation_euler = (centro - cam.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(sc.render.filepath, check_existing=False)
        px = np.empty(LADO * LADO * 4, np.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        px = px.reshape(-1, 4)
        b = np.round(px[px[:, 3] > 0.5, :3] * 255).astype(np.int64)
        visto[b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16] = True
        if i % 40 == 0:
            print(f'vista {i}/{len(vistas)}: {visto.sum()} caras vistas')

for s, mat in zip(plato.material_slots, originales):
    s.material = mat
me.attributes.remove(me.attributes['fid'])
bpy.data.objects.remove(cam)
vistas_solas = int(visto.sum())

if conservar:  # el recorte anterior: se emparejan caras por su centro (misma malla, distinta compresion)
    arbol = KDTree(nf)
    for i, c in enumerate(centros(plato)):
        arbol.insert(c, i)
    arbol.balance()
    k = importar(conservar)
    ck = centros(k)
    pares = [arbol.find(c) for c in ck]
    iguales = [i for _, i, dist in pares if dist < 5e-5]
    print(f'conservar: {len(iguales)} de {len(ck)} caras emparejadas')
    if len(iguales) < 0.999 * len(ck):
        raise ValueError('conservar.glb no es un recorte de la entrada')
    visto[iguales] = True
    bpy.data.objects.remove(k)

bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[f for f in bm.faces if not visto[f.index]], context='FACES')
bm.to_mesh(me)
bm.free()
print(f'RESULTADO: {nf} -> {len(me.polygons)} caras (vistas desde algun angulo: {vistas_solas})')

bpy.ops.object.select_all(action='DESELECT')
plato.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=dst, export_format='GLB', use_selection=True,
    export_image_format='AUTO', export_image_quality=100,
    export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=10,
    export_draco_position_quantization=14, export_draco_normal_quantization=10, export_draco_texcoord_quantization=16,
    export_cameras=False, export_lights=False,
)
# las imagenes vuelven a ser los bytes exactos de la entrada (el exportador de Blender las recomprime)
gs, bs = partes(Path(src).read_bytes())
gd, bd = partes(Path(dst).read_bytes())
orig = {im['name']: (im.get('mimeType'), vista(gs, bs, im['bufferView'])) for im in gs['images']}
if {im.get('name') for im in gd['images']} != set(orig):
    raise ValueError('Las imagenes exportadas no coinciden con las de la entrada')
for im in gd['images']:
    im['mimeType'] = orig[im['name']][0]
Path(dst).write_bytes(reempacar(gd, bd, {im['bufferView']: orig[im['name']][1] for im in gd['images']}))
