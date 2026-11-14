# blender -b --factory-startup -P glb_to_usdz.py -- in.glb out.usdz
from pathlib import Path
import os
import sys
import bpy

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]
if Path(src).resolve() == Path(dst).resolve() or Path(dst).exists():
    raise ValueError('Usa una salida USDZ nueva para conservar archivos existentes')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.gltf(filepath=src)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
for o in meshes:
    xs = [(o.matrix_world @ v.co) for v in o.data.vertices]
    print('MESH', o.name, len(o.data.polygons), 'tris',
          'size', [round(max(c[i] for c in xs) - min(c[i] for c in xs), 4) for i in range(3)],
          'minZ', round(min(c[2] for c in xs), 4))
    for m in o.data.materials:
        if not m or not m.use_nodes:
            continue
        nodes = m.node_tree.nodes
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            print('Material sin Principled: revisar apariencia en Quick Look', m.name)
            continue
        # glTF metallicFactor 0 llega como textura x 0 (nodo MATH); el exportador USD
        # ignora ese nodo y usaria la textura sola, asi que se fija metalico = 0
        s = bsdf.inputs['Metallic']
        if s.is_linked and s.links[0].from_node.type == 'MATH':
            mn = s.links[0].from_node
            consts = [i.default_value for i in mn.inputs[:2] if not i.is_linked]
            if mn.operation == 'MULTIPLY' and 0.0 in consts:
                m.node_tree.links.remove(s.links[0])
                s.default_value = 0.0
        for name in ('Base Color', 'Roughness', 'Metallic', 'Normal'):
            s = bsdf.inputs[name]
            print('  INPUT', name, 'linked' if s.is_linked else s.default_value,
                  s.links[0].from_node.type if s.is_linked else '')

bpy.ops.wm.usd_export(
    filepath=dst,
    export_materials=True,
    generate_preview_surface=True,
    export_textures_mode='NEW',
    convert_orientation=True,
    export_global_forward_selection='NEGATIVE_Z',
    export_global_up_selection='Y',
    export_cameras=False,
    export_lights=False,
    convert_world_material=False,
    triangulate_meshes=True,
    accessibility_label=os.path.splitext(os.path.basename(dst))[0].capitalize(),  # lo que lee VoiceOver: Ribeye
)

# La malla queda como la escribe Blender (normales por esquina, igual que los modelos de ejemplo de Apple): pasarla a una
# vez por punto bajaba 35-41% con los mismos valores, pero no se pudo probar en un iPhone y el usuario prefiere calidad a peso.
# Texturas: el GLB las trae en JPEG progresivo (Android) y Blender las copia tal cual; no se confirmo que Quick Look lea
# progresivo, asi que jpegtran las pasa a JPEG normal (baseline), mismos pixeles.
import os, subprocess, tempfile, zipfile
from pxr import Sdf
JPEGTRAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'jpegtran.exe')
tmp = tempfile.mkdtemp()
with zipfile.ZipFile(dst) as z:
    names = z.namelist()
    z.extractall(tmp)
w = Sdf.ZipFileWriter.CreateNew(dst + '.tmp')  # sin comprimir y alineado a 64 bytes, como pide USDZ
for name in names:
    f = os.path.join(tmp, name)
    if name.lower().endswith(('.jpg', '.jpeg')) and os.path.isfile(JPEGTRAN):
        subprocess.run([JPEGTRAN, '-copy', 'none', '-optimize', '-outfile', f + '.opt', f], check=True)
        os.replace(f + '.opt', f)
    w.AddFile(f, name)
w.Save()
del w
size = os.path.getsize(dst)
os.replace(dst + '.tmp', dst)
print('EXPORTED', dst, size, '->', os.path.getsize(dst))
