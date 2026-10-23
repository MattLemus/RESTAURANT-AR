# blender -b --factory-startup -P make_web_glb.py -- ../ar/fritada.glb fritada.glb
# fritada.glb para la web a partir del original (ar/fritada.glb, 17 MB): apoyado en la mesa (base en y=0), centrado, 27 cm.
# La textura es un mosaico de trocitos: con la compresion por defecto (Draco 12 bits en UV, JPEG fuerte) se mezclaban
# trocitos vecinos y el queso/arroz se veia gris y "brilloso" como hielo. Por eso UV a 16 bits y JPEG 95.
import sys
import bpy
from mathutils import Matrix, Vector

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)

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
for o in meshes:
    o.data.transform(Matrix.Translation(shift))
    print('MESH', o.name, len(o.data.polygons), 'tris, size', tuple(round(c, 3) for c in hi - lo))
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
    export_image_format='JPEG', export_jpeg_quality=95,
    export_draco_mesh_compression_enable=True,
    export_draco_position_quantization=14, export_draco_normal_quantization=10, export_draco_texcoord_quantization=16,
    export_cameras=False, export_lights=False,
)
print('EXPORTED', dst)
