# blender -b --factory-startup -P make_web_glb.py -- ../ar/fritada.glb fritada.glb [ancho_cm] [triangulos]
# fritada.glb para la web a partir del original (ar/fritada.glb, 17 MB): apoyado en la mesa (base en y=0), centrado, 27 cm.
# La textura es un mosaico de trocitos: con la compresion por defecto (Draco 12 bits en UV, JPEG fuerte) se mezclaban
# trocitos vecinos y el queso/arroz se veia gris y "brilloso" como hielo. Por eso UV a 16 bits y JPEG 95.
# ancho_cm: ancho real del plato visto desde arriba (los modelos generados vienen de ~1 m). triangulos: maximo, para que
# cargue rapido (la hamburguesa de 977k tris tardaba 9 s en Quick Look).
import sys
import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

a = sys.argv[sys.argv.index('--') + 1:]
src, dst = a[:2]
CM = float(a[2]) if len(a) > 2 else 0
TRIS = int(a[3]) if len(a) > 3 else 0

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
# unir los vertices repetidos en las costuras de la textura: si no, cada isla de la textura cuenta como pieza suelta
bpy.ops.import_scene.gltf(filepath=src, merge_vertices=TRIS > 0)


def reducir(o, ancho):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    # piezas sueltas: caras unidas por vertices
    pieza, tam = [-1] * len(bm.faces), []
    for f in bm.faces:
        if pieza[f.index] >= 0:
            continue
        n, pila = len(tam), [f]
        pieza[f.index] = n
        tam.append(0)
        while pila:
            g = pila.pop()
            tam[n] += 1
            for v in g.verts:
                for h in v.link_faces:
                    if pieza[h.index] < 0:
                        pieza[h.index] = n
                        pila.append(h)
    grande = {i for i, c in enumerate(tam) if c >= 0.05 * len(bm.faces)} | {tam.index(max(tam))}
    pv = {v: pieza[v.link_faces[0].index] for v in bm.verts if v.link_faces}
    kd = KDTree(sum(1 for p in pv.values() if p in grande))
    for v, p in pv.items():
        if p in grande:
            kd.insert(v.co, v.index)
    kd.balance()
    # Las semillas y gotas de salsa estan a ~1 mm de la superficie y se quedan; lo que flota mas lejos (1% del ancho)
    # son restos del generador, como los trozos de borde junto al plato roto de la hamburguesa
    lejos = {p for v, p in pv.items() if p not in grande and kd.find(v.co)[2] > 0.01 * ancho}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if pieza[f.index] in lejos], context='FACES')
    # solo se reducen las piezas grandes (pan, carne, plato): las chicas (semillas, gotas) se apartan y se desharian
    chicas = sum(1 for f in bm.faces if pieza[f.index] not in grande)
    for f in bm.faces:
        f.select_set(pieza[f.index] not in grande)
    grandes = len(bm.faces) - chicas
    bm.to_mesh(o.data)
    bm.free()
    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    if chicas:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')
    sueltas = [x for x in bpy.context.selected_objects if x != o]
    mod = o.modifiers.new('decimate', 'DECIMATE')
    mod.ratio = max(0.02, min(1.0, (TRIS - chicas) / grandes))
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    print('REDUCIR', o.name, 'piezas', len(tam), 'borradas', len(lejos), 'chicas', chicas, 'tris', grandes, '->',
          len(o.data.polygons))
    if sueltas:
        bpy.ops.object.select_all(action='DESELECT')
        for x in sueltas + [o]:
            x.select_set(True)
        bpy.ops.object.join()
    # al reducir se pierden las normales del archivo y queda facetado: normales suaves calculadas de nuevo
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.shade_smooth()

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
for o in meshes:
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

pts = [v.co for o in meshes for v in o.data.vertices]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
# Blender es Z arriba: base en z=0 y centrado en x/y
shift = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
k = CM / 100 / max(hi.x - lo.x, hi.y - lo.y) if CM else 1
for o in meshes:
    o.data.transform(Matrix.Scale(k, 4) @ Matrix.Translation(shift))
    if TRIS and len(o.data.polygons) > TRIS:
        reducir(o, k * max(hi.x - lo.x, hi.y - lo.y))
    print('MESH', o.name, len(o.data.polygons), 'tris, size', tuple(round(c * k, 3) for c in hi - lo))
    for m in o.data.materials:
        bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        # metallicFactor 0 llega como textura x 0; se deja fijo en 0 (ver glb_to_usdz.py)
        s = bsdf.inputs['Metallic']
        if s.is_linked and s.links[0].from_node.type == 'MATH':
            m.node_tree.links.remove(s.links[0])
            s.default_value = 0.0

for img in bpy.data.images:
    print('IMG', img.name, tuple(img.size))

bpy.ops.export_scene.gltf(
    filepath=dst, export_format='GLB',
    export_image_format='JPEG', export_image_quality=95,  # export_jpeg_quality se ignora: salia en calidad 75
    export_draco_mesh_compression_enable=True,
    export_draco_position_quantization=14, export_draco_normal_quantization=10, export_draco_texcoord_quantization=16,
    export_cameras=False, export_lights=False,
)
print('EXPORTED', dst)
