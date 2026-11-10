# blender -b --factory-startup -P ver.py -- web.glb vista.png
# Foto de control del plato terminado: 4 lados a 45 grados y uno de costado (vista.png.0..4.png; procesar.py los junta
# en vista.png), para revisarlo antes de entregarlo.
import math
import sys

import bpy
from mathutils import Vector

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
pts = [o.matrix_world @ Vector(c) for o in sc.objects if o.type == 'MESH' for c in o.bound_box]
r = max(max(abs(p.x), abs(p.y)) for p in pts)
z = max(p.z for p in pts) / 2
bpy.ops.object.camera_add()
cam = bpy.context.object
sc.camera = cam
cam.data.lens = 50
sc.world = bpy.data.worlds.new('w')
sc.world.use_nodes = True
sc.world.node_tree.nodes['Background'].inputs[1].default_value = 2.5
sc.view_settings.view_transform = 'Standard'
sc.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys() else 'BLENDER_EEVEE_NEXT'
sc.render.resolution_x = sc.render.resolution_y = 700
vistas = [(a, 45) for a in (0, 90, 180, 270)] + [(0, 8)]
for i, (az, el) in enumerate(vistas):
    a, e, d = math.radians(az), math.radians(el), 4.2 * r
    cam.location = (d * math.cos(e) * math.sin(a), -d * math.cos(e) * math.cos(a), z + d * math.sin(e))
    cam.rotation_euler = (Vector((0, 0, z)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.render.filepath = f'{dst}.{i}.png'
    bpy.ops.render.render(write_still=True)
print('VISTA', dst)
