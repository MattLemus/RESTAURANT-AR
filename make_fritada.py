# python3 make_fritada.py           (despues de make_pieces.py; bpy 5.2 de pip y usd-core para el USDZ)
# Arma la fritada como los pancakes de la galeria de Apple: una pieza por ingrediente, copias que comparten malla y
# textura (como sus 20 arandanos), plato modelado (make_plate.py, rugosidad 0,27 como el de Apple) con la sombra de
# la comida horneada en un mapa de oclusion (su plate_ao). Sale fritada-nueva.glb (web/Android) y fritada-nueva.usdz
# (iPhone), que usa la pagina de prueba fritada-nueva.html; la del QR (fritada.html) sigue con fritada.glb/usdz.
# Distribucion copiada del plato original (ar/fritada.glb). Coordenadas de Blender en cm: x derecha, y fondo, z arriba.
import math
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'piezas', 'build')
TMP = os.path.join(BUILD, 'tmp')
NAME = 'fritada-nueva'


def finish_usdz(usdc, usdz):
    """Parte que corre sin Blender (usd-core): la oclusion del plato y el empaquetado para Quick Look."""
    from pxr import Sdf, Usd, UsdShade, UsdUtils
    stage = Usd.Stage.Open(usdc)
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Shader):
            continue
        sh = UsdShade.Shader(prim)
        if sh.GetIdAttr().Get() != 'UsdPreviewSurface':
            continue
        n = sh.GetInput('normal')
        if n and n.HasConnectedSource():                  # mapa de normales: de 0..1 a -1..1 (como Apple)
            tex = UsdShade.Shader(n.GetConnectedSource()[0].GetPrim())
            tex.CreateInput('scale', Sdf.ValueTypeNames.Float4).Set((2, 2, 2, 1))
            tex.CreateInput('bias', Sdf.ValueTypeNames.Float4).Set((-1, -1, -1, 0))
            tex.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('raw')
        if 'porcelana' in str(prim.GetPath()):
            st = None
            for p in prim.GetParent().GetChildren():
                s2 = UsdShade.Shader(p)
                if s2 and s2.GetIdAttr().Get() == 'UsdPrimvarReader_float2':
                    st = s2
            mat_path = prim.GetParent().GetPath()
            if st is None:
                st = UsdShade.Shader.Define(stage, mat_path.AppendChild('uvmap'))
                st.CreateIdAttr('UsdPrimvarReader_float2')
                st.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
                st.CreateOutput('result', Sdf.ValueTypeNames.Float2)
            ao = UsdShade.Shader.Define(stage, mat_path.AppendChild('plato_ao'))
            ao.CreateIdAttr('UsdUVTexture')
            ao.CreateInput('file', Sdf.ValueTypeNames.Asset).Set('./textures/plato_ao.png')
            ao.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('raw')
            ao.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(st.ConnectableAPI(), 'result')
            ao.CreateOutput('r', Sdf.ValueTypeNames.Float)
            sh.CreateInput('occlusion', Sdf.ValueTypeNames.Float).ConnectToSource(ao.ConnectableAPI(), 'r')
    stage.GetRootLayer().Save()
    if not UsdUtils.CreateNewARKitUsdzPackage(usdc, usdz):
        raise SystemExit('no se pudo empaquetar ' + usdz)
    print('USDZ', usdz, os.path.getsize(usdz) // 1024, 'KB')


if len(sys.argv) > 2 and sys.argv[1] == '--usdz':
    finish_usdz(*sys.argv[2:4])
    sys.exit()

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix, Euler
from mathutils.bvhtree import BVHTree

random.seed(7)
CM = 0.01
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
placed = []


def load(name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(BUILD, name + '.glb'))
    ob = [o for o in bpy.data.objects if o not in before and o.type == 'MESH'][0]
    for o in list(bpy.data.objects):
        if o not in before and o is not ob:
            bpy.data.objects.remove(o)
    ob.parent = None
    ob.matrix_world = Matrix.Identity(4)
    scene.collection.objects.unlink(ob)                 # queda como molde, sin estar en la escena
    for m in ob.data.materials:
        # glTF trae metallicFactor 0 como textura x 0 (nodo MATH); el exportador USD ignora ese nodo y dejaria
        # la textura de brillo como metal (comida oscura y metalica en el iPhone): se deja fijo en 0
        bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        for link in list(bsdf.inputs['Metallic'].links):
            m.node_tree.links.remove(link)
        bsdf.inputs['Metallic'].default_value = 0.0
    return ob


def place(src, x, y, rot=(0, 0, 0), scale=1.0, lift=8.0):
    ob = src.copy()                                     # misma malla y material: se guarda una sola vez
    scene.collection.objects.link(ob)
    ob.rotation_mode = 'XYZ'
    ob.rotation_euler = Euler([math.radians(a) for a in rot], 'XYZ')
    ob.scale = (scale,) * 3
    ob.location = (x * CM, y * CM, lift * CM)
    bpy.context.view_layer.update()
    return ob


def tree_of(objs):
    verts, polys = [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        off = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        polys += [[off + i for i in p.vertices] for p in me.polygons]
        o.evaluated_get(dg).to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys)


def drop(ob, gap=0.4, keep=True, core=None):
    """Baja la pieza hasta que toque el plato o las piezas que ya estan (gap en mm). core: solo cuenta la parte
    central de la pieza (la lechuga baja hasta tocar el fondo y despues se acomoda a la subida del plato)."""
    tree = tree_of(placed)
    vs = ob.data.vertices
    if core:
        r = max(ob.dimensions) / max(ob.scale) * core
        vs = [v for v in vs if (v.co.x ** 2 + v.co.z ** 2) ** 0.5 < r]
    pts = [ob.matrix_world @ v.co for v in vs]
    best = None
    for p in pts[::max(1, len(pts) // 700)]:
        hit = tree.ray_cast(p, Vector((0, 0, -1)), 1.0)[0]
        if hit is not None:
            best = p.z - hit.z if best is None else min(best, p.z - hit.z)
    if best is not None:
        ob.location.z -= best - gap * 0.001
    bpy.context.view_layer.update()
    if keep:
        placed.append(ob)
    return ob


def settle(src, x, y, spread, rot, scale=1.0, lift=9.0, tries=8, gap=0.3, tilt=0.0):
    """Prueba varias posiciones cerca de (x, y) y deja la pieza donde queda mas baja: los montoncitos quedan
    bajos y parejos, sin torres."""
    best = None
    for _ in range(tries):
        ob = place(src, x + random.uniform(-spread, spread), y + random.uniform(-spread, spread), rot(), scale, lift)
        if tilt:
            tilt_to_surface(ob, tilt)
        drop(ob, gap=gap, keep=False)
        top = max((ob.matrix_world @ v.co).z for v in ob.data.vertices)
        if best is None or top < best[0]:
            if best is not None:
                bpy.data.objects.remove(best[1])
            best = (top, ob)
        else:
            bpy.data.objects.remove(ob)
    placed.append(best[1])
    return best[1]


def tilt_to_surface(ob, k=1.0):
    """Inclina una pieza rigida (maduro, llapingacho) segun la pendiente del plato debajo."""
    tree = tree_of(placed[:1])
    c = ob.matrix_world.translation.copy()
    r = max(ob.dimensions) * 0.35
    pts = [tree.ray_cast(Vector((c.x + dx, c.y + dy, 0.2)), Vector((0, 0, -1)), 1.0)[0]
           for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r))]
    if all(p is not None for p in pts):
        sx = (pts[0].z - pts[1].z) / (2 * r); sy = (pts[2].z - pts[3].z) / (2 * r)
        R = Matrix.Rotation(math.atan(sy) * k, 4, 'X') @ Matrix.Rotation(-math.atan(sx) * k, 4, 'Y')
        ob.matrix_world = Matrix.Translation(c) @ R @ Matrix.Translation(-c) @ ob.matrix_world
        bpy.context.view_layer.update()


def drape(ob, lift=0.08):
    """La lechuga se acomoda a la curva del plato (ningun vertice queda por debajo de lo que tiene abajo)."""
    tree = tree_of(placed)
    M = ob.matrix_world; Mi = M.inverted()
    for v in ob.data.vertices:
        p = M @ v.co
        hit = tree.ray_cast(Vector((p.x, p.y, 0.3)), Vector((0, 0, -1)), 1.0)[0]
        if hit is not None and p.z < hit.z + lift * CM:
            v.co = Mi @ Vector((p.x, p.y, hit.z + lift * CM))
    ob.data.update()
    placed.append(ob)


def onion_strip(R, L, name):
    """Tira de cebolla morada (no hubo foto): cinta curva delgada, mitad morada como la capa de afuera."""
    img = bpy.data.images.get('cebolla_color')
    if img is None:
        tex = np.ones((64, 256, 4), np.float32)
        v = np.linspace(0, 1, 64)[:, None]
        t = np.clip((v - 0.30) / 0.22, 0, 1)[..., None]
        tex[..., :3] = np.array([0.36, 0.04, 0.30]) * (1 - t) + np.array([0.93, 0.85, 0.91]) * t
        tex[..., :3] *= 1 + 0.04 * np.sin(np.linspace(0, 60, 256))[None, :, None]
        img = bpy.data.images.new('cebolla_color', 256, 64); img.pixels = tex.ravel(); img.pack()
    bm = bmesh.new()
    W, T, n = 0.0038, 0.0013, 24
    rows = []
    for i in range(n + 1):
        a = (i / n - 0.5) * L / R
        c = Vector((R * math.sin(a), R * (1 - math.cos(a)), 0)); nrm = Vector((-math.sin(a), math.cos(a), 0))
        rows.append([bm.verts.new(c + nrm * dw + Vector((0, 0, dt)))
                     for dw, dt in ((-W / 2, -T / 2), (W / 2, -T / 2), (W / 2, T / 2), (-W / 2, T / 2))])
    uvl = bm.loops.layers.uv.new('UVMap')
    for i in range(n):
        for k in range(4):
            f = bm.faces.new((rows[i][k], rows[i][(k + 1) % 4], rows[i + 1][(k + 1) % 4], rows[i + 1][k]))
            for loop, (du, dv) in zip(f.loops, ((0, 0), (0, 1), (1, 1), (1, 0))):
                loop[uvl].uv = ((i + du) / n, dv)
    bm.faces.new(rows[0][::-1]); bm.faces.new(rows[-1])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    mat = bpy.data.materials.get('cebolla')
    if mat is None:
        mat = bpy.data.materials.new('cebolla'); mat.use_nodes = True; mat.use_backface_culling = True
        nt = mat.node_tree; bsdf = next(x for x in nt.nodes if x.type == 'BSDF_PRINCIPLED')
        ti = nt.nodes.new('ShaderNodeTexImage'); ti.image = img
        nt.links.new(ti.outputs['Color'], bsdf.inputs['Base Color'])
        bsdf.inputs['Roughness'].default_value = 0.4
    me.materials.append(mat)
    return bpy.data.objects.new(name, me)


# ---------- plato ----------
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(HERE, 'piezas', 'plato.glb'))
plate = [o for o in bpy.data.objects if o not in before and o.type == 'MESH'][0]
plate.parent = None; plate.matrix_world = Matrix.Identity(4)
placed.append(plate)

src = {n: load(n) for n in ('carneA', 'carneB', 'carneC', 'moteA', 'moteB', 'maduro', 'aguacate', 'lechuga',
                            'tomate1', 'tomate2', 'llapingacho')}
FLAT = -90    # piezas fotografiadas desde arriba (maduro, aguacate, lechuga): la foto queda mirando hacia arriba

# lechuga (fondo izquierda): hoja curvada con los bordes hacia arriba, acomodada al plato
leaf_me = src['lechuga'].data.copy()
for v in leaf_me.vertices:
    x = v.co.x
    v.co.y -= 0.012 * (x / 0.07) ** 2 + 0.004 * math.sin(x * 140) * (abs(x) / 0.07)   # -y local = arriba
leaf = src['lechuga'].copy(); leaf.data = leaf_me
for x, y, yaw, s in ((-7.6, 4.6, 200, 0.72), (-4.4, 6.6, 160, 0.65)):   # sin salirse del plato
    ob = place(leaf, x, y, (FLAT, 0, yaw), s, lift=6)
    ob.data = ob.data.copy()
    drop(ob, keep=False, core=0.25); drape(ob)

# aguacate sobre la lechuga: tajadas en abanico, cada una apenas montada sobre la anterior
for x, y in ((-10.0, 2.8), (-7.4, 5.0), (-4.8, 7.2)):      # lado a lado: el largo cruzado a la fila
    settle(src['aguacate'], x, y, 0.5, lambda: (FLAT, 0, 130), 0.72, lift=7, tries=4)

# mote (fondo centro): montoncito de granos
any_rot = lambda: (random.uniform(-180, 180), random.uniform(-60, 60), random.uniform(-180, 180))
for i in range(24):
    settle(src['moteA' if i % 2 else 'moteB'], 2.8, 6.6, 2.3, any_rot, random.uniform(0.9, 1.1), gap=0.2)

# maduros (fondo derecha), sobre la subida del plato
for x, y, yaw in ((9.4, 6.6, -15), (9.6, 1.0, 15)):
    ob = place(src['maduro'], x, y, (FLAT, 0, yaw), 0.85, lift=5); tilt_to_surface(ob); drop(ob)

# llapingachos (centro)
for x, y, yaw in ((0.0, -2.2, 10), (-0.4, -8.0, -20)):
    settle(src['llapingacho'], x, y, 0.8, lambda: (0, 0, yaw), 0.9, lift=5, tries=5, tilt=0.8)

# carne (adelante derecha), apilada: trozos apoyados en una cara, algo ladeados
meat = [('carneB', 4.8, -3.6, 20), ('carneA', 9.0, -4.0, 150), ('carneC', 5.0, -7.8, -100), ('carneA', 9.4, -8.0, -40),
        ('carneB', 7.0, -6.0, 200), ('carneC', 3.8, -0.8, 80), ('carneC', 7.4, -1.8, -150)]
for name, x, y, yaw in meat:
    settle(src[name], x, y, 1.2, lambda: (random.uniform(-14, 14), random.uniform(-14, 14), yaw + random.uniform(-20, 20)),
           tries=8, gap=0.4)

# curtido (izquierda): tomate y cebolla
cube_rot = lambda: (random.choice((0, 90, 180, 270)) + random.uniform(-15, 15), random.uniform(-15, 15), random.uniform(0, 360))
for i in range(11):
    settle(src['tomate1' if i % 2 else 'tomate2'], -7.4, -3.0, 2.6, cube_rot, random.uniform(0.85, 1.05), gap=0.2)
onions = [onion_strip(0.022, 0.042, 'cebolla_a'), onion_strip(0.034, 0.05, 'cebolla_b')]
flat_rot = lambda: (random.uniform(-10, 10), random.uniform(-10, 10), random.uniform(0, 360))
for i in range(9):
    settle(onions[i % 2], -7.2, -6.2, 2.6, flat_rot, random.uniform(0.85, 1.1), tries=5, gap=0.1)

# ---------- sombra de la comida en el plato (como plate_ao de Apple) ----------
scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 64
scene.world = scene.world or bpy.data.worlds.new('mundo')
scene.world.light_settings.distance = 0.025
nt = plate.data.materials[0].node_tree
bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
bsdf.inputs['Roughness'].default_value = 0.27            # el valor del plato de Apple
ao = bpy.data.images.new('plato_ao', 2048, 2048, alpha=False); ao.colorspace_settings.name = 'Non-Color'
tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = ao; nt.nodes.active = tn
bpy.ops.object.select_all(action='DESELECT'); plate.select_set(True); bpy.context.view_layer.objects.active = plate
scene.render.bake.use_selected_to_active = False; scene.render.bake.margin = 16
bpy.ops.object.bake(type='AO')
px = np.array(ao.pixels[:]).reshape(2048, 2048, 4)
px[..., :3] = 0.35 + 0.65 * px[..., :3]                  # sombra suave, solo donde la comida toca el plato
ao.pixels = px.ravel()
os.makedirs(TMP, exist_ok=True)
ao_path = os.path.join(TMP, 'plato_ao.png')
ao.filepath_raw = ao_path; ao.file_format = 'PNG'; ao.save()
tn.image = bpy.data.images.load(ao_path); tn.image.colorspace_settings.name = 'Non-Color'
# glTF: oclusion en el canal R de un mapa aparte (el USD la recibe en finish_usdz)
sep = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(tn.outputs['Color'], sep.inputs['Color'])
group = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
group.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
gnode = nt.nodes.new('ShaderNodeGroup'); gnode.node_tree = group
nt.links.new(sep.outputs['Red'], gnode.inputs['Occlusion'])

meshes = [o for o in scene.objects if o.type == 'MESH']
for o in meshes:
    xs = [(o.matrix_world @ v.co) for v in o.data.vertices]
    out = max(max(abs(p.x) - 0.1312, abs(p.y) - 0.1175) for p in xs)
    if out > 0.002 and o is not plate:
        print('FUERA', o.name, round(out * 100, 1), 'cm')
print('ESCENA', len(meshes), 'objetos', sum(len(p.vertices) - 2 for o in meshes for p in o.data.polygons), 'triangulos')

bpy.ops.export_scene.gltf(filepath=os.path.join(HERE, NAME + '.glb'), export_format='GLB', export_image_format='JPEG',
                          export_jpeg_quality=90, export_cameras=False, export_lights=False)
usdc = os.path.join(TMP, 'usd', 'fritada.usdc')
bpy.ops.wm.usd_export(filepath=usdc, export_materials=True, generate_preview_surface=True, export_textures_mode='NEW',
                      convert_orientation=True, export_global_forward_selection='NEGATIVE_Z',
                      export_global_up_selection='Y', export_cameras=False, export_lights=False,
                      convert_world_material=False, triangulate_meshes=True, accessibility_label='Fritada')
shutil.copy(ao_path, os.path.join(TMP, 'usd', 'textures', 'plato_ao.png'))   # Blender no la exporta (no va al BSDF)
subprocess.run([sys.executable, '-I', os.path.abspath(__file__), '--usdz', usdc, os.path.join(HERE, NAME + '.usdz')],
               check=True)
