# python3 make_pieces.py            (bpy 5.2 de pip, opencv-python-headless, scipy, triangle)
# python3 make_pieces.py carneA     (solo esa pieza)
# Una pieza 3D por ingrediente desde su foto (piezas/fotos), como arma Apple los pancakes de su galeria: cada
# ingrediente es un objeto aparte con su propio juego de texturas (color, relieve, brillo), 1024 o 2048, y pocas
# caras (el detalle va en las texturas). Salen en piezas/build/<pieza>.glb; make_fritada.py las arma en el plato.
#
# Dos formas de pasar de foto a 3D:
#  - caja/disco: se ajusta una caja o disco redondeado a la silueta (camara y medidas) y la foto se proyecta desde esa
#    camara; las caras que no salen en la foto copian la opuesta (carne, tomate, llapingacho).
#  - inflada: la silueta se "infla" en frente y espalda (mote, maduro, aguacate, lechuga).
# La pieza detallada se hornea a una malla liviana con islas de UV grandes (piezas_bake.py).
import math
import os
import sys
import cv2
import numpy as np
from scipy import ndimage
import bpy
import piezas_lib as pc
import piezas_bake as bk

HERE = os.path.dirname(os.path.abspath(__file__))
FOTOS = os.path.join(HERE, 'piezas', 'fotos')
BUILD = os.path.join(HERE, 'piezas', 'build')
TMP = os.path.join(BUILD, 'tmp')

# medidas reales (m), brillo (rugosidad base y cuanto baja donde la foto tiene reflejos), tamano de textura
BOX = dict(rough=0.72, gloss=0.3, tex=2048, k=5.0, lump=0.07, n_low=14)
PIECES = {
    'carneA': ('01_Carne_A_cubo', 'box', dict(size=0.042, **BOX)),
    'carneB': ('02_Carne_B_alargada', 'box', dict(size=0.055, **BOX)),
    'carneC': ('03_Carne_C_oscura', 'box', dict(size=0.036, **BOX)),
    'tomate1': ('08_Tomate_1', 'box', dict(size=0.015, rough=0.45, gloss=0.25, tex=1024, k=8.0, lump=0, n_low=8)),
    'tomate2': ('09_Tomate_2', 'box', dict(size=0.015, rough=0.45, gloss=0.25, tex=1024, k=8.0, lump=0, n_low=8)),
    'llapingacho': ('04_Llapingacho', 'disc', dict(size=0.07, rough=0.7, gloss=0.2, tex=2048, k=8.0, lump=0, n_low=12)),
    # el mote es blanco: sin bajar los claros (perderia el detalle) y sin recortar sombra gris
    'moteA': ('06_Mote_A', 'inflate', dict(width=0.017, half=0.85, bevel=1.0, relief=0.10, rough=0.55, gloss=0.3,
                                           tris=110, tex=1024, trim=False, delight=False)),
    'moteB': ('07_Mote_B', 'inflate', dict(width=0.016, half=0.85, bevel=1.0, relief=0.10, rough=0.55, gloss=0.3,
                                           tris=110, tex=1024, trim=False, delight=False)),
    'maduro': ('05_Maduro', 'inflate', dict(width=0.08, half_m=0.005, bevel=0.45, relief=0.04, rough=0.55, gloss=0.3,
                                            tris=1800, tex=2048)),
    'aguacate': ('10_Aguacate', 'inflate', dict(width=0.09, half_m=0.006, bevel=0.6, relief=0.02, rough=0.4, gloss=0.25,
                                                tris=1500, tex=1024)),
    'lechuga': ('11_Lechuga', 'inflate', dict(width=0.14, half_m=0.0012, bevel=0.2, relief=0.04, rough=0.5, gloss=0.2,
                                              tris=3000, tex=2048)),
}


def source_maps(out, tex, rough, gloss):
    paths = [os.path.join(TMP, f'{out}_{k}.png') for k in 'cnr']
    cv2.imwrite(paths[0], tex[..., ::-1])
    cv2.imwrite(paths[1], pc.normal_map(tex)[..., ::-1])
    cv2.imwrite(paths[2], pc.rough_map(tex, rough, gloss))
    return paths


def inflated(out, photo, width, bevel, relief, rough, gloss, tris, tex, half=None, half_m=None, back=1.0, step=10,
             trim=True, delight=True):
    img, mask = pc.load(photo, trim)
    ys, xs = np.nonzero(mask)
    s = (np.ptp(xs) + 1) / width                         # pixeles por metro
    if half_m is not None:                              # grosor fijo (piezas planas)
        half = half_m * s / ndimage.distance_transform_edt(mask).max()
    V, F, CR, _ = pc.inflate(img, mask, s, half, bevel, relief, back=back, step=step)
    lowstep = step * (len(F) / tris) ** 0.5
    VL, FL, _, rim = pc.inflate(img, mask, s, half, bevel, relief * 0.5, back=back, step=lowstep, rings=(3, 10, 22))
    t, to_uv = pc.texture(img, mask)
    if delight:
        t = pc.delight(t)
    maps = source_maps(out, t, rough, gloss)
    bk.reset()
    high = bk.mesh_object(out + '_high', V, F, to_uv(CR[:, 0], CR[:, 1]))
    src = bk.source_material(high, *maps, 0.5)
    low = bk.make_low(out, VL, FL, rim)
    return high, low, src, tex


def box_shape(p):
    cx, cy, s, a, b, c, yaw, elev = p
    return np.array([[x, y, z] for x in (-a, a) for y in (-b, b) for z in (-c, c)]), (cx, cy, s, yaw, elev)


def disc_shape(p):
    cx, cy, s, h, elev = p
    t = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    ring = np.stack([np.cos(t), np.sin(t)], -1)
    return np.vstack([np.c_[ring, np.full(72, h)], np.c_[ring, np.full(72, -h)]]), (cx, cy, s, 0.0, elev)


def fitted(out, photo, kind, size, rough, gloss, tex, k, lump, n_low):
    img, mask = pc.load(photo)
    ys, xs = np.nonzero(mask); cx, cy, w = xs.mean(), ys.mean(), np.ptp(xs)
    if kind == 'box':
        starts = [[cx, cy, w / 2.6, 1, 1, 1, yaw, el] for yaw in (0.4, 0.8, 1.2) for el in (0.35, 0.6)]
        (cx, cy, s, a, b, c, yaw, elev), iou = pc.fit_silhouette(mask, box_shape, starts)
        dims, kh, kv = np.abs([a, b, c]), k, k
    else:
        starts = [[cx, cy, w / 2.05, h, el] for h in (0.2, 0.3) for el in (0.4, 0.6, 0.8)]
        (cx, cy, s, h, elev), iou = pc.fit_silhouette(mask, disc_shape, starts)
        dims, yaw, kh, kv = np.abs([1, 1, h]), 0.0, 2.0, k
    print('AJUSTE', out, kind, 'silueta %.0f%%' % (iou * 100), 'yaw %.0f elev %.0f' % (math.degrees(yaw), math.degrees(elev)))
    cam = (cx, cy, s, yaw, elev)
    scale = size / (2 * max(dims))                      # unidades del ajuste -> metros (lado mas largo)
    t, to_uv = pc.texture(img, mask)
    maps = source_maps(out, pc.delight(t), rough, gloss)
    bk.reset()
    Vh, Fh = pc.superquadric(*dims, k_h=kh, k_v=kv, n=40)
    uvh = pc.hidden_face_uv(Vh, Fh, cam, to_uv)         # la foto se proyecta antes de deformar
    Vl, Fl = pc.superquadric(*dims, k_h=kh, k_v=kv, n=n_low)
    if lump:                                            # trozo irregular, no caja perfecta (carne)
        Vh, Vl = pc.lumpy(Vh, lump * max(dims)), pc.lumpy(Vl, lump * max(dims))
    high = bk.mesh_object(out + '_high', Vh * scale, Fh, uvh)
    src = bk.source_material(high, *maps, 0.5)
    low = bk.mesh_object(out, Vl * scale, Fl)
    low.data.uv_layers.new(name='UVMap')
    bpy.ops.object.select_all(action='DESELECT'); low.select_set(True); bpy.context.view_layer.objects.active = low
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(50), island_margin=0.01)
    bpy.ops.object.mode_set(mode='OBJECT')
    return high, low, src, tex


def build(out):
    photo, kind, p = PIECES[out]
    photo = os.path.join(FOTOS, photo + '.jpg')
    if kind == 'inflate':
        high, low, src, tex = inflated(out, photo, **p)
    else:
        high, low, src, tex = fitted(out, photo, kind, **p)
    bk.bake_maps(high, low, src, tex, os.path.join(TMP, out))
    bk.export_glb(low, os.path.join(BUILD, out + '.glb'))
    n = sum(len(f.vertices) - 2 for f in low.data.polygons)
    print('PIEZA', out, n, 'triangulos, textura', tex, 'medidas cm', [round(d * 100, 1) for d in low.dimensions])


if __name__ == '__main__':
    os.makedirs(TMP, exist_ok=True)
    for out in (sys.argv[1:] or PIECES):
        build(out)
