# blender -b --factory-startup -P make_lite_glb.py -- fritada.glb fritada-lite.glb
# Version liviana como la milanesa de Menuly (82k tris, solo textura de color, sin brillo): en iPhone model-viewer
# arma el USDZ al tocar AR y Quick Look la pone en la mesa en ~1 s en un iPhone 14; la nuestra de 11 MB tardaba.
import sys
import bpy

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]
TRIS = 80000

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)

for o in [o for o in bpy.context.scene.objects if o.type == 'MESH']:
    bpy.context.view_layer.objects.active = o
    n = len(o.data.polygons)
    if n > TRIS:
        mod = o.modifiers.new('decimate', 'DECIMATE')
        mod.ratio = TRIS / n
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
    print('MESH', o.name, n, '->', len(o.data.polygons), 'tris')
    for m in o.data.materials:
        bsdf = next(x for x in m.node_tree.nodes if x.type == 'BSDF_PRINCIPLED')
        # solo color: sin mapa de normales ni de rugosidad/metal, mate como el de Menuly
        for name, value in (('Normal', None), ('Roughness', 1.0), ('Metallic', 0.0)):
            s = bsdf.inputs[name]
            for link in list(s.links):
                m.node_tree.links.remove(link)
            if value is not None:
                s.default_value = value

bpy.ops.export_scene.gltf(
    filepath=dst, export_format='GLB',
    export_image_format='JPEG', export_jpeg_quality=90,
    export_draco_mesh_compression_enable=True,
    export_draco_position_quantization=14, export_draco_normal_quantization=10, export_draco_texcoord_quantization=16,
    export_cameras=False, export_lights=False,
)
print('EXPORTED', dst)
