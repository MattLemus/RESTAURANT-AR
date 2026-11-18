"""python camaras_npz.py <dense> <mascaras> <salida.npz> <camaras.json>: camaras (K,R,T) del modelo sin distorsion +
mascaras a 1/4 para votar_ply.py, y centro/mirada de cada foto para limpiar.py.

Orden para dejar SOLO el plato (sin mesa ni tapa), probado en prueba-5060 (17-11-2026), <t> = carpeta del trabajo,
despues de ReconstructMesh (prueba_3d_local.py o procesar.py). No hace falta texturizar la malla completa antes.
  1. python -c "import procesar; procesar.objeto(r'<t>/dense/images', r'<t>/mascaras')"            rembg, 9.6 min CPU
  2. python camaras_npz.py <t>/dense <t>/mascaras <t>/camaras_mascaras.npz <t>/camaras.json
  3. blender -b --factory-startup -P votar_ply.py -- <t>/dense/malla.ply <t>/camaras_mascaras.npz <t>/dense/malla_plato.ply
  4. TextureMesh -w <t>/dense -i denso.mvs -m malla_plato.ply -o plato.glb --export-type glb                    44 s
  5. blender -b --factory-startup -P limpiar.py -- <t>/dense/plato.glb <t>/camaras.json <t>/limpio.glb
  6. blender -b --factory-startup -P cortar_base.py -- <t>/limpio.glb <t>/base.glb
  7. blender -b --factory-startup -P ../make_web_glb.py -- <t>/base.glb <t>/web_plato.glb 20 200000 sin_nivelar --draco
     (20 = ancho real en cm; sin sin_nivelar se inclina 11 grados; sin --draco pesa 26 MB en vez de 8.5)"""
import json, sys
from pathlib import Path
import numpy as np
import pycolmap
from PIL import Image

dense, md, npz, cj = sys.argv[1:5]
rec = pycolmap.Reconstruction(str(Path(dense) / 'sparse'))
K, R, T, M, WH, cams = [], [], [], [], [], []
for im in sorted(rec.images.values(), key=lambda i: i.name):
    pose = im.cam_from_world() if callable(im.cam_from_world) else im.cam_from_world
    r, t = pose.rotation.matrix(), np.asarray(pose.translation)
    with Image.open(Path(md) / (im.name + '.png')) as m:
        w, h = m.size
        assert (w, h) == (rec.cameras[im.camera_id].width, rec.cameras[im.camera_id].height), im.name
        M.append((np.asarray(m.convert('L').resize((w // 4, h // 4))) > 127).astype(np.uint8))
    K.append(rec.cameras[im.camera_id].calibration_matrix()); R.append(r); T.append(t); WH.append((w // 4, h // 4))
    cams.append({'foto': im.name, 'centro': (-r.T @ t).tolist(), 'mira': r[2].tolist()})
# las fotos sin distorsion salen de tamanos distintos: se rellenan con 0; votar_ply usa WH para no salirse
H, W = max(x.shape[0] for x in M), max(x.shape[1] for x in M)
M = [np.pad(x, ((0, H - x.shape[0]), (0, W - x.shape[1]))) for x in M]
np.savez(npz, K=np.array(K), R=np.array(R), T=np.array(T), M=np.array(M), WH=np.array(WH))
json.dump(cams, open(cj, 'w'))
print('CAMARAS', len(K), 'mascara', M[0].shape, 'cubre', round(float(np.mean(M)), 2))
