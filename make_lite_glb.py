# blender -b --factory-startup -P make_lite_glb.py -- fritada.glb fritada-lite.glb 15000 1024
# Version liviana para celulares sin ARCore (fritada-mesa.html): menos triangulos y texturas.
import sys
import bpy

src, dst, tris, tex = sys.argv[sys.argv.index('--') + 1:][:4]
tris, tex = int(tris), int(tex)

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)

for o in [o for o in bpy.context.scene.objects if o.type == 'MESH']:
    n = len(o.data.polygons)
    if n > tris:
        mod = o.modifiers.new('dec', 'DECIMATE')
        mod.ratio = tris / n
        mod.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=mod.name)
    print('MESH', o.name, n, '->', len(o.data.polygons), 'tris')
    for m in o.data.materials:
        bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        # metallicFactor 0 llega como textura x 0; se deja fijo en 0 (ver glb_to_usdz.py)
        s = bsdf.inputs['Metallic']
        if s.is_linked and s.links[0].from_node.type == 'MATH':
            m.node_tree.links.remove(s.links[0])
            s.default_value = 0.0

for img in bpy.data.images:
    if img.size[0] > tex or img.size[1] > tex:
        print('IMG', img.name, tuple(img.size), '->', tex)
        img.scale(tex, tex)

bpy.ops.export_scene.gltf(
    filepath=dst, export_format='GLB',
    export_image_format='JPEG', export_jpeg_quality=85,
    export_draco_mesh_compression_enable=True,
    export_cameras=False, export_lights=False,
)
print('EXPORTED', dst)
