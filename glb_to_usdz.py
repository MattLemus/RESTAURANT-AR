# blender -b --factory-startup -P glb_to_usdz.py -- in.glb out.usdz
import os
import sys
import bpy

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]

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
        nodes = m.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
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

# Mismo USDZ, mas liviano y sin cambiar un solo valor (-35/-41%): Blender escribe normales y UV por esquina de triangulo
# (600k veces). Si todas las esquinas de cada punto valen lo mismo bit a bit, se guardan una vez por punto ('vertex').
# Texturas: jpegtran con Huffman optimizado, mismos pixeles; JPEG normal (no progresivo): no se confirmo que Quick Look lo lea.
import os, subprocess, tempfile, zipfile
import numpy as np
from pxr import Usd, UsdGeom, Sdf, Vt
JPEGTRAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'jpegtran.exe')
tmp = tempfile.mkdtemp()
with zipfile.ZipFile(dst) as z:
    names = z.namelist()
    z.extractall(tmp)
root = os.path.join(tmp, names[0])  # el primer archivo del usdz es la escena
st = Usd.Stage.Open(root)
for prim in st.Traverse():
    if prim.GetTypeName() != 'Mesh':
        continue
    mesh = UsdGeom.Mesh(prim)
    fvi = np.array(mesh.GetFaceVertexIndicesAttr().Get())
    first = np.full(len(mesh.GetPointsAttr().Get()), -1)
    first[fvi[::-1]] = np.arange(len(fvi))[::-1]  # primera esquina de cada punto

    def por_punto(vals):
        vals = np.asarray(vals, dtype=np.float32)
        if len(vals) != len(fvi) or (first < 0).any():
            return None
        ref = vals[first[fvi]]
        return ref[first] if np.array_equal(ref.view(np.uint32), vals.view(np.uint32)) else None

    if mesh.GetNormalsInterpolation() == UsdGeom.Tokens.faceVarying:
        v = por_punto(mesh.GetNormalsAttr().Get())
        if v is not None:
            mesh.GetNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(v))
            mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars():
        if pv.GetInterpolation() != UsdGeom.Tokens.faceVarying or pv.GetTypeName() != Sdf.ValueTypeNames.TexCoord2fArray:
            continue
        v = por_punto(pv.ComputeFlattened())
        if v is not None:
            pv.Set(Vt.Vec2fArray.FromNumpy(v))
            pv.SetInterpolation(UsdGeom.Tokens.vertex)
            if pv.GetIndicesAttr():
                prim.RemoveProperty(pv.GetIndicesAttr().GetName())
    print('COMPACTAR', prim.GetPath(), 'normales', mesh.GetNormalsInterpolation())
# Save() en un .usdc agrega al final y deja los datos viejos dentro: se escribe un archivo nuevo
st.GetRootLayer().Export(root + '.nuevo.usdc')
del st
os.replace(root + '.nuevo.usdc', root)
w = Sdf.ZipFileWriter.CreateNew(dst + '.tmp')  # sin comprimir y alineado a 64 bytes, como pide USDZ
for name in names:
    f = os.path.join(tmp, name)
    if name.lower().endswith(('.jpg', '.jpeg')):
        subprocess.run([JPEGTRAN, '-copy', 'none', '-optimize', '-outfile', f + '.opt', f], check=True)
        os.replace(f + '.opt', f)
    w.AddFile(f, name)
w.Save()
del w
size = os.path.getsize(dst)
os.replace(dst + '.tmp', dst)
print('EXPORTED', dst, size, '->', os.path.getsize(dst))
