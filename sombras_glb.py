# Oscurece el color del plato donde su propia forma tapa la luz (oclusion ambiental): entre los granos, bajo la carne,
# donde la comida toca el plato. Sin esto un plato horneado en Blender se ve "de plastico": color plano, sin sombras.
# Sale solo de la forma, no de la luz de un cuarto: sirve igual para cualquier plato y cualquier lugar.
# La comida recibe sombra de todo; la loza solo de la comida (sus capas de modelado no deben marcarse).
# Solo cambia la imagen de color; la malla y las demas texturas quedan byte a byte iguales (no suma triangulos).
#   python sombras_glb.py entrada.glb salida.glb [distancia_m] [fuerza]
# distancia_m: hasta donde tapa (0.02 = 2 cm, como el borde de la carne); fuerza: 0 = nada, 1 = sombra completa.
# Blender corre este mismo archivo para hornear (blender -b -P sombras_glb.py -- ...).
import io
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'


def partes(b):
    jl = struct.unpack_from('<I', b, 12)[0]
    bl = struct.unpack_from('<I', b, 20 + jl)[0]
    return json.loads(b[20:20 + jl]), b[28 + jl:28 + jl + bl]


def vista(g, binc, i):
    v = g['bufferViews'][i]
    o = v.get('byteOffset', 0)
    return binc[o:o + v['byteLength']]


def reempacar(g, binc, nuevos):
    """GLB con los bufferViews de `nuevos` ({indice: bytes}) cambiados; el resto se copia tal cual."""
    g = json.loads(json.dumps(g))
    if len(g['buffers']) != 1 or 'uri' in g['buffers'][0]:
        raise ValueError('Se esperaba un GLB con un solo buffer interno')
    datos = bytearray()
    for i, v in enumerate(g['bufferViews']):
        d = nuevos.get(i, vista(g, binc, i))
        datos += b'\0' * (-len(datos) % 4)
        v['byteOffset'], v['byteLength'] = len(datos), len(d)
        datos += d
    datos += b'\0' * (-len(datos) % 4)
    g['buffers'][0]['byteLength'] = len(datos)
    j = json.dumps(g, separators=(',', ':')).encode()
    j += b' ' * (-len(j) % 4)
    return (struct.pack('<III', 0x46546C67, 2, 28 + len(j) + len(datos)) + struct.pack('<II', len(j), 0x4E4F534A) + j
            + struct.pack('<II', len(datos), 0x004E4942) + bytes(datos))


def oscurecer(color, ao, fuerza, calidad=95):
    """JPEG del color (PIL RGB) multiplicado por la oclusion; la luz se multiplica en lineal, no en sRGB."""
    from PIL import Image
    c = np.asarray(color, np.float32) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    lin *= (1 - fuerza * (1 - np.clip(ao, 0, 1)))[..., None]
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    f = io.BytesIO()
    Image.fromarray(np.round(s * 255).astype(np.uint8)).save(f, 'JPEG', quality=calidad, progressive=True, optimize=True)
    return f.getvalue()


def margen(ao, px):
    """Extiende cada isla px pixeles hacia afuera (sin esto las islas chicas, como un grano, se aclaran al alejarse);
    lo que no es superficie queda sin sombra (1). En ao, -1 = pixel que no horneo ninguna cara."""
    ok = ao >= 0
    a = np.where(ok, ao, 0).astype(np.float32)
    for _ in range(px):
        s, n = np.zeros_like(a), np.zeros_like(a)
        for eje, paso in ((0, 1), (0, -1), (1, 1), (1, -1)):
            s += np.roll(np.where(ok, a, 0), paso, eje)
            n += np.roll(ok, paso, eje)
        nuevo = ~ok & (n > 0)
        a[nuevo] = s[nuevo] / n[nuevo]
        ok |= nuevo
    return np.where(ok, a, 1)


def hornear_con_blender(glb, ancho, alto, distancia):
    with tempfile.TemporaryDirectory() as t:
        npy = Path(t) / 'ao.npy'
        subprocess.run([BLENDER, '-b', '--factory-startup', '-P', __file__, '--', str(glb), str(npy), str(ancho), str(alto),
                        str(distancia)], check=True)
        return margen(np.load(npy), 8)


def main():
    from PIL import Image
    a = sys.argv[1:]
    entrada, salida = Path(a[0]), Path(a[1])
    distancia = float(a[2]) if len(a) > 2 else 0.02
    fuerza = float(a[3]) if len(a) > 3 else 1.0
    if salida.resolve() == entrada.resolve():
        raise ValueError('Usa una salida nueva, distinta de la entrada')
    if distancia <= 0 or not 0 <= fuerza <= 1:
        raise ValueError('distancia > 0 y fuerza entre 0 y 1')
    g, binc = partes(entrada.read_bytes())
    colores = {g['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source'] for m in g['materials']
               if 'baseColorTexture' in m.get('pbrMetallicRoughness', {})}
    # shortcut: un solo atlas de color para todo el plato (asi salen los platos horneados en Blender); con varias imagenes de color, hornear una por imagen
    if len(colores) != 1:
        raise ValueError(f'Se esperaba una sola imagen de color para todo el plato, hay {len(colores)}')
    iv = g['images'][colores.pop()]['bufferView']
    color = Image.open(io.BytesIO(vista(g, binc, iv))).convert('RGB')
    ao = hornear_con_blender(entrada, *color.size, distancia)
    salida.write_bytes(reempacar(g, binc, {iv: oscurecer(color, ao, fuerza)}))
    g2, b2 = partes(salida.read_bytes())
    assert all(vista(g2, b2, i) == vista(g, binc, i) for i in range(len(g['bufferViews'])) if i != iv), 'cambio algo mas que el color'
    print(f'{salida}: sombra media {1 - ao.mean():.3f}, {salida.stat().st_size / 1e6:.1f} MB')


def hornear(glb, npy, ancho, alto, distancia):
    import bpy
    from mathutils import Vector
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    bpy.ops.import_scene.gltf(filepath=glb)
    piezas = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in piezas:
        o.select_set(True)
    bpy.context.view_layer.objects.active = piezas[0]
    if len(piezas) > 1:
        bpy.ops.object.join()
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.separate(type='MATERIAL')
    bpy.ops.object.mode_set(mode='OBJECT')
    piezas = [o for o in bpy.context.scene.objects if o.type == 'MESH']

    def huella(o):
        p = [o.matrix_world @ Vector(c) for c in o.bound_box]
        return (max(v.x for v in p) - min(v.x for v in p)) * (max(v.y for v in p) - min(v.y for v in p))
    # shortcut: la loza = el material que mas ocupa visto desde arriba; un modelo de un solo material (escaneo) queda sin sombra
    loza = max(piezas, key=huella)
    nombre_loza = loza.material_slots[loza.data.polygons[0].material_index].material.name
    comida = [o for o in piezas if o is not loza]
    # caras de comida pegadas a la loza (a menos de 0.5 mm y paralelas, restos del modelado): se hornean como loza.
    # Si no, la loza las tapa y salen puntitos negros en la pared del plato.
    import bmesh
    from mathutils.bvhtree import BVHTree
    bl = bmesh.new()
    bl.from_mesh(loza.data)
    bl.transform(loza.matrix_world)
    arbol = BVHTree.FromBMesh(bl)
    bl.free()
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    for o in comida:
        bpy.ops.object.select_all(action='DESELECT')
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(o.data)
        mw, giro = o.matrix_world, o.matrix_world.to_3x3()
        pegadas = 0
        for f in bm.faces:
            loc, nn, _, _ = arbol.find_nearest(mw @ f.calc_center_median(), 5e-4)
            if loc is not None and abs(nn.dot((giro @ f.normal).normalized())) > 0.8:
                f.select_set(True)
                pegadas += 1
        bmesh.update_edit_mesh(o.data)
        if pegadas:
            bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')
        print('pegadas a la loza:', o.name, pegadas)
    sueltas = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o is not loza and o not in comida]
    if sueltas:
        bpy.ops.object.select_all(action='DESELECT')
        for o in sueltas + [loza]:
            o.select_set(True)
        bpy.context.view_layer.objects.active = loza
        bpy.ops.object.join()
    comida = [o for o in comida if o.data.polygons]
    piezas = [loza] + comida
    zmin = min((o.matrix_world @ Vector(c)).z for o in piezas for c in o.bound_box)
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, zmin - 1e-4))  # la mesa tambien tapa la luz bajo el plato
    img = bpy.data.images.new('ao', ancho, alto, alpha=False, float_buffer=True)
    img.pixels.foreach_set(np.full(ancho * alto * 4, -1, np.float32))  # -1 = no lo horneo ninguna cara (margen() lo llena)
    m = bpy.data.materials.new('ao')
    if m.node_tree is None:
        m.use_nodes = True
    n, ln = m.node_tree.nodes, m.node_tree.links
    n.clear()
    geo = n.new('ShaderNodeNewGeometry')
    neg = n.new('ShaderNodeVectorMath')
    neg.operation = 'SCALE'
    neg.inputs['Scale'].default_value = -1
    ln.new(geo.outputs['Normal'], neg.inputs[0])
    mx = n.new('ShaderNodeMath')
    mx.operation = 'MAXIMUM'
    # no todas las caras apuntan hacia afuera (winding mezclado): se mira por los dos lados y vale el lado abierto
    for k, normal in enumerate((geo.outputs['Normal'], neg.outputs['Vector'])):
        ao = n.new('ShaderNodeAmbientOcclusion')
        ao.samples = 16
        ao.inputs['Distance'].default_value = distancia
        ln.new(normal, ao.inputs['Normal'])
        ln.new(ao.outputs['AO'], mx.inputs[k])
    em = n.new('ShaderNodeEmission')
    ln.new(mx.outputs[0], em.inputs['Color'])
    ln.new(em.outputs[0], n.new('ShaderNodeOutputMaterial').inputs['Surface'])
    t = n.new('ShaderNodeTexImage')
    t.image = img
    n.active = t
    for o in piezas:
        for s in o.material_slots:
            s.material = m
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 32
    pr = bpy.context.preferences.addons['cycles'].preferences
    for tipo in ('OPTIX', 'CUDA'):  # GPU si hay; si no, CPU (mas lento, mismo resultado)
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
    print('hornear con', sc.cycles.device, pr.compute_device_type, '| loza:', nombre_loza)

    def pasada(objetivos):  # sin margen: una pasada no pisa las islas de la otra
        bpy.ops.object.select_all(action='DESELECT')
        for o in objetivos:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objetivos[0]
        bpy.ops.object.bake(type='EMIT', margin=0, use_clear=False)
    if comida:
        pasada(comida)  # la comida: sombra de todo (otra comida y la loza)
    # la loza solo recibe sombra de la comida: sus capas y escalones de modelado (2 mm) salian como una lamina gris
    loza.visible_shadow = False
    pasada([loza])
    px = np.empty(ancho * alto * 4, np.float32)
    img.pixels.foreach_get(px)
    np.save(npy, px.reshape(alto, ancho, 4)[::-1, :, 0])  # Blender guarda de abajo hacia arriba; la imagen del GLB, al reves


if __name__ == '__main__':
    if '--' in sys.argv:
        a = sys.argv[sys.argv.index('--') + 1:]
        hornear(a[0], a[1], int(a[2]), int(a[3]), float(a[4]))
    else:
        main()
