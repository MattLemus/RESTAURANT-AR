# Devuelve caras que se habian borrado por su color (la lamina beige del arroz del churrasco) y las pinta con el color de
# lo que tienen justo debajo (la loza o la comida). Borrarlas dejo a la vista lo que tapaban: el borde de la salsa
# flotando en sierra y el escalon de la loza (franja blanca). Las caras son las mismas de la entrada; la lamina toma
# tambien el material de lo que tiene debajo, y las demas imagenes quedan byte a byte iguales.
#   python recolorear_glb.py entrada.glb sin_lamina.glb salida.glb
# entrada: el plato completo; sin_lamina: el mismo plato con esas caras borradas. Las caras de entrada que faltan en
# sin_lamina son las que se pintan. La imagen de color sale en PNG (sin perdida): sombras_glb.py la pasa luego a JPEG.
# Blender corre este mismo archivo (blender -b -P recolorear_glb.py -- ...).
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sombras_glb import BLENDER, partes, reempacar, vista  # noqa: E402

LEVANTE = 0.006  # m: el rayo sale 6 mm por encima de la lamina y baja hasta la superficie de abajo
ALCANCE = 0.02  # m: mas lejos que esto no se busca color


def lineal_a_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def rellenar(color, ok, zona, px):
    """Extiende los pixeles ok hacia los de zona que faltan (promedio de 4 vecinos, px pasos)."""
    c, ok = color.astype(np.float32).copy(), ok.copy()
    for _ in range(px):
        s, n = np.zeros_like(c), np.zeros(ok.shape, np.float32)
        for eje, paso in ((0, 1), (0, -1), (1, 1), (1, -1)):
            s += np.roll(np.where(ok[..., None], c, 0), paso, eje)
            n += np.roll(ok, paso, eje)
        nuevo = zona & ~ok & (n > 0)
        if not nuevo.any():
            break
        c[nuevo] = s[nuevo] / n[nuevo][:, None]
        ok |= nuevo
    return c, ok


def main():
    from PIL import Image
    entrada, sin_lamina, salida = map(Path, sys.argv[1:4])
    if salida.exists() or salida.resolve() in (entrada.resolve(), sin_lamina.resolve()):
        raise ValueError('Usa una salida nueva')
    g, binc = partes(entrada.read_bytes())
    colores = {g['textures'][m['pbrMetallicRoughness']['baseColorTexture']['index']]['source'] for m in g['materials']
               if 'baseColorTexture' in m.get('pbrMetallicRoughness', {})}
    if len(colores) != 1:
        raise ValueError(f'Se esperaba una sola imagen de color, hay {len(colores)}')
    if any(m.get('pbrMetallicRoughness', {}).get('baseColorFactor', [1] * 4) != [1] * 4 for m in g['materials']):
        raise ValueError('Un material tiñe la textura (baseColorFactor): el color copiado no lo incluiria')
    im = g['images'][colores.pop()]
    color = np.asarray(Image.open(io.BytesIO(vista(g, binc, im['bufferView']))).convert('RGB'))
    alto, ancho = color.shape[:2]
    with tempfile.TemporaryDirectory() as t:
        npz, malla = Path(t) / 'r.npz', Path(t) / 'malla.glb'
        subprocess.run([BLENDER, '-b', '--factory-startup', '-P', __file__, '--', str(entrada), str(sin_lamina), str(npz),
                        str(ancho), str(alto), im['name'], str(malla)], check=True)
        with np.load(npz) as r:
            debajo, lamina, otros = r['debajo'], r['lamina'] > 0.5, r['otros'] > 0.5
        gm, bm = partes(malla.read_bytes())
    propia = lamina & ~otros  # texeles que solo usa la lamina (los compartidos con otras caras no se tocan)
    hallado = propia & (debajo[..., 3] > 0.5)
    nuevo = lineal_a_srgb(debajo[..., :3]) * 255
    # texeles de la lamina sin superficie debajo (al aire): el color de sus vecinos ya pintados
    nuevo, ok = rellenar(nuevo, hallado, propia, 64)
    falta = propia & ~ok
    # el borde de cada isla (8 px fuera, solo donde ninguna cara usa la imagen) tambien: si no, el beige asoma al alejarse
    nuevo, cambiar = rellenar(nuevo, ok, ~otros & ~lamina, 8)
    out = color.copy()
    out[cambiar] = np.round(nuevo[cambiar]).clip(0, 255).astype(np.uint8)
    f = io.BytesIO()
    Image.fromarray(out).save(f, 'PNG', optimize=False, compress_level=6)
    # la malla de Blender con las imagenes de la entrada tal cual (Blender las recomprime), salvo el color pintado
    orig = {x['name']: (x.get('mimeType'), vista(g, binc, x['bufferView'])) for x in g['images']}
    if {x.get('name') for x in gm['images']} != set(orig):
        raise ValueError('Las imagenes exportadas no coinciden con las de la entrada')
    nuevos = {}
    for x in gm['images']:
        x['mimeType'], nuevos[x['bufferView']] = ('image/png', f.getvalue()) if x['name'] == im['name'] else orig[x['name']]
    salida.write_bytes(reempacar(gm, bm, nuevos))
    assert (out[otros] == color[otros]).all(), 'toco texeles de otras caras'
    print(f'{salida}: lamina {lamina.sum()} texeles (compartidos con otras caras: {(lamina & otros).sum()}), '
          f'con superficie debajo {hallado.sum()}, sin color {falta.sum()}, {salida.stat().st_size / 1e6:.1f} MB')


def hornear(glb, sin_lamina, npz, ancho, alto, nombre_color, exportar):
    import bmesh
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree

    def importar(p):
        antes = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=p)
        ps = [o for o in bpy.data.objects if o not in antes and o.type == 'MESH']
        bpy.ops.object.select_all(action='DESELECT')
        for o in ps:
            o.select_set(True)
        bpy.context.view_layer.objects.active = ps[0]
        if len(ps) > 1:
            bpy.ops.object.join()
        return bpy.context.view_layer.objects.active

    def centros(o):
        n = len(o.data.polygons)
        c = np.zeros(n * 3)
        o.data.polygons.foreach_get('center', c)
        M = np.array(o.matrix_world)
        return (np.c_[c.reshape(-1, 3), np.ones(n)] @ M.T)[:, :3]

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    plato = importar(glb)
    ref = importar(sin_lamina)
    arbol = KDTree(len(ref.data.polygons))
    for i, c in enumerate(centros(ref)):
        arbol.insert(c, i)
    arbol.balance()
    cp = centros(plato)

    def materiales(o):
        mi = np.zeros(len(o.data.polygons), int)
        o.data.polygons.foreach_get('material_index', mi)
        return np.array([re.sub(r'\.\d{3}$', '', o.data.materials[i].name) for i in mi])  # el 2do import agrega .001
    mp, mr = materiales(plato), materiales(ref)
    # misma cara = mismo centro (la compresion mueve < 50 um) y mismo material: donde la lamina cruza la loza hay
    # centros casi iguales de caras distintas
    quedan = np.array([any(d < 5e-5 and mr[j] == mp[i] for _, j, d in arbol.find_n(c, 4)) for i, c in enumerate(cp)])
    faltan = int((~quedan).sum())
    print(f'caras: {len(cp)}, en sin_lamina: {len(ref.data.polygons)}, a pintar: {faltan}')
    if quedan.sum() < 0.999 * len(ref.data.polygons) or not faltan:
        raise ValueError('sin_lamina no es la entrada con caras borradas')
    bpy.data.objects.remove(ref)

    bpy.ops.object.select_all(action='DESELECT')
    plato.select_set(True)
    bpy.context.view_layer.objects.active = plato
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bm = bmesh.from_edit_mesh(plato.data)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select_set(not quedan[f.index])
    bmesh.update_edit_mesh(plato.data)
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    lamina = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o is not plato)
    # la lamina esta acostada sobre la loza: todas sus caras miran hacia arriba, asi el rayo baja desde encima
    # (sin las normales del archivo, que no se dan vuelta con las caras)
    bpy.ops.object.select_all(action='DESELECT')
    lamina.select_set(True)
    bpy.context.view_layer.objects.active = lamina
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bpy.ops.object.mode_set(mode='OBJECT')
    bm = bmesh.new()
    bm.from_mesh(lamina.data)
    bmesh.ops.reverse_faces(bm, faces=[f for f in bm.faces if (lamina.matrix_world.to_3x3() @ f.normal).z < 0])
    bm.to_mesh(lamina.data)
    bm.free()
    bpy.ops.object.shade_smooth()

    def imagen(nombre):
        im = bpy.data.images.new(nombre, ancho, alto, alpha=True, float_buffer=True)
        im.pixels.foreach_set(np.zeros(ancho * alto * 4, np.float32))
        return im

    def material_con(im, emision):
        m = bpy.data.materials.new(im.name)
        if m.node_tree is None:
            m.use_nodes = True
        n, ln = m.node_tree.nodes, m.node_tree.links
        n.clear()
        salida = n.new('ShaderNodeOutputMaterial')
        if emision:
            em = n.new('ShaderNodeEmission')
            em.inputs['Color'].default_value = (1, 1, 1, 1)
            ln.new(em.outputs[0], salida.inputs['Surface'])
        t = n.new('ShaderNodeTexImage')
        t.image = im
        n.active = t
        return m

    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 4
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

    def hornear_en(objs, activo, **kw):
        bpy.ops.object.select_all(action='DESELECT')
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = activo
        bpy.ops.object.bake(margin=0, use_clear=False, **kw)

    def leer(im):
        px = np.empty(ancho * alto * 4, np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(alto, ancho, 4)[::-1]  # Blender guarda de abajo hacia arriba

    # 1) el color de lo que hay debajo de cada texel de la lamina (rayo desde 6 mm encima, hasta 2 cm). Se copia la
    # textura tal cual (emision), no el color difuso: el barniz de la loza lo oscurecia un 4%.
    originales = {o: [s.material for s in o.material_slots] for o in (plato, lamina)}
    usadas = {nd.image for s in plato.material_slots for nd in s.material.node_tree.nodes if nd.type == 'TEX_IMAGE'}
    fuente = material_con(next(i for i in usadas if i and i.name.split('.')[0] == nombre_color), True)
    n, ln = fuente.node_tree.nodes, fuente.node_tree.links
    ln.new(n.active.outputs['Color'], n['Emission'].inputs['Color'])
    for s in plato.material_slots:
        s.material = fuente
    debajo = imagen('debajo')
    for s in lamina.material_slots:
        s.material = material_con(debajo, False)
    hornear_en([plato, lamina], lamina, type='EMIT', use_selected_to_active=True, cage_extrusion=LEVANTE,
               max_ray_distance=ALCANCE)
    # 2) que texeles son de la lamina y 3) cuales usan las demas caras (esos no se tocan)
    lam, otros = imagen('lamina'), imagen('otros')
    for s in lamina.material_slots:
        s.material = material_con(lam, True)
    hornear_en([lamina], lamina, type='EMIT')
    for s in plato.material_slots:
        s.material = material_con(otros, True)
    hornear_en([plato], plato, type='EMIT')
    np.savez(npz, debajo=leer(debajo), lamina=leer(lam)[..., 0], otros=leer(otros)[..., 0])

    # 4) la lamina toma tambien el material de lo que tiene debajo (casi siempre la loza), con el mismo rayo del color:
    # asi sombras_glb.py la trata como loza (como arroz tapaba la luz de la pared del plato desde adentro) y en el visor
    # 3D brilla igual que lo que imita
    for o, mats in originales.items():
        for s, m in zip(o.material_slots, mats):
            s.material = m
    bp = bmesh.new()
    bp.from_mesh(plato.data)
    bp.transform(plato.matrix_world)
    arbol_p, mat_p = BVHTree.FromBMesh(bp), [f.material_index for f in bp.faces]
    bp.free()
    nombres = [s.material.name for s in lamina.material_slots]
    cambiadas = 0
    for p in lamina.data.polygons:
        _, _, i, _ = arbol_p.ray_cast(lamina.matrix_world @ p.center + Vector((0, 0, LEVANTE)), Vector((0, 0, -1)), ALCANCE)
        if i is not None:
            k = nombres.index(plato.material_slots[mat_p[i]].material.name)
            cambiadas += p.material_index != k
            p.material_index = k
    print(f'lamina: {cambiadas} de {len(lamina.data.polygons)} caras cambiaron al material de lo que tienen debajo')
    bpy.ops.object.select_all(action='DESELECT')
    lamina.select_set(True)
    plato.select_set(True)
    bpy.context.view_layer.objects.active = plato
    bpy.ops.object.join()
    bpy.ops.export_scene.gltf(  # misma compresion que make_web_glb.py
        filepath=exportar, export_format='GLB', use_selection=True,
        export_image_format='AUTO', export_image_quality=100,
        export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=10,
        export_draco_position_quantization=14, export_draco_normal_quantization=10, export_draco_texcoord_quantization=16,
        export_cameras=False, export_lights=False,
    )


if __name__ == '__main__':
    if '--' in sys.argv:
        a = sys.argv[sys.argv.index('--') + 1:]
        hornear(a[0], a[1], a[2], int(a[3]), int(a[4]), a[5], a[6])
    else:
        main()
