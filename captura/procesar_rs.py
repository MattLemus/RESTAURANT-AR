# python procesar_rs.py <carpeta_fotos | video> <trabajo> [ancho_cm]
# Lo mismo que procesar.py, pero RealityScan (tarjeta de video) ubica las fotos y arma la forma: ~10 min en total en vez
# de ~1.5 h con COLMAP + OpenMVS en el procesador. El color lo sigue poniendo OpenMVS, porque el texturizado de
# RealityScan 2.2 falla en esta PC ("Texturing stage 01 sanity check", probado 8 formas, tambien con driver 621.14).
# Cada paso se salta si su resultado ya existe.
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np
from scipy.spatial import cKDTree

import procesar as p

RS = r'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe'
# exportRegistration en formato COLMAP con fotos sin distorsion (lo que lee InterfaceCOLMAP de OpenMVS)
PARAMS = '''<Configuration id="{2D5793BC-A65D-4318-A1B9-A05044608385}">
  <entry key="calexFileFormat" value="COLMAP"/>
  <entry key="calexFileFormatId" value="{280B11A4-F9A3-47D1-AE58-C0DEA33487D8}"/>
  <entry key="calexHasUndistort" value="0x1"/>
  <entry key="calexHasImageExport" value="0x1"/>
  <entry key="calexHasDisabled" value="0x0"/>
  <entry key="MvsExportIsModelCoordinates" value="1"/>
</Configuration>
'''


def realityscan(job, *cmds):
    log = os.path.join(job, 'realityscan.log')
    a = [RS, '-headless', '-silent', os.path.join(job, 'crash'), '-stdConsole', '-set', 'appQuitOnError=true', *cmds,
         '-quit']
    print('>> RealityScan', ' '.join(cmds), flush=True)
    with open(log, 'w') as f:
        subprocess.run(a, stdout=f, stderr=subprocess.STDOUT)
    texto = open(log, errors='ignore').read()
    assert 'Processing failed' not in texto, 'RealityScan fallo, ver ' + log


def leer_ply(ruta):
    b = open(ruta, 'rb').read()
    k = b.index(b'end_header\n') + len(b'end_header\n')
    n = int([l for l in b[:k].split(b'\n') if l.startswith(b'element vertex')][0].split()[2])
    return b, k, n


def girar(src, dst, puntos, centros):
    """La malla que exporta RealityScan viene con Z arriba y sus camaras COLMAP con -Y arriba: (x, y, z) -> (x, -z, y).
    Se comprueba contra los puntos de COLMAP para no texturizar con la malla corrida (sale todo naranja y torcido).
    Algunas corridas la entregan al reves (caras mirando hacia abajo): OpenMVS la cree invisible y deja la comida sin
    color. Si la mayoria de las caras no mira hacia las camaras, se dan vuelta todas."""
    b, k, n = leer_ply(src)
    assert b[:k].count(b'property float') == 6, 'se esperaba x y z red green blue en float'
    assert b'property list uchar int vertex_indices' in b[:k], 'se esperaban caras con indices int'
    V = np.frombuffer(b[k:k + n * 24], dtype='<f4').reshape(n, 6).copy()
    y, z = V[:, 1].copy(), V[:, 2].copy()
    V[:, 1], V[:, 2] = -z, y
    P = np.array([[float(v) for v in l.split()[1:4]] for l in open(puntos) if not l.startswith('#')])
    P = P[((P > np.percentile(P, 5, 0)) & (P < np.percentile(P, 95, 0))).all(1)]
    d = np.median(cKDTree(V[:, :3]).query(P[::5])[0])
    tam = np.linalg.norm(np.ptp(V[:, :3], 0))
    print(f'MALLA vs puntos: {d / tam:.4f} del tamano (alineada si < 0.01)')
    assert d < 0.01 * tam, 'la malla no calza con las camaras exportadas'

    F = np.frombuffer(b[k + n * 24:], dtype=np.dtype([('n', 'u1'), ('i', '<i4', 3)])).copy()
    assert (F['n'] == 3).all(), 'se esperaban solo triangulos'
    T = V[:, :3][F['i']]
    nor = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    cen, C = T.mean(1), np.asarray(centros)

    def vista():  # la cara mira hacia al menos una de las fotos
        return np.concatenate([(np.einsum('fk,fck->fc', nor[s], C[None] - cen[s, None]) > 0).any(1)
                               for s in np.array_split(np.arange(len(F)), 50)])
    v = vista()
    print(f'CARAS que mira alguna foto: {v.mean():.0%}')
    if v.mean() < 0.5:
        F['i'], nor = F['i'][:, ::-1], -nor
        v = vista()
        print('MALLA dada vuelta (venia al reves)')
    # una 'tapa' de triangulos mirando hacia abajo sobre la comida la tapaba en OpenMVS y la dejaba sin color
    print(f'QUITO {(~v).sum()} caras que ninguna foto pudo ver')
    hdr = b[:k].replace(b'element face %d' % len(F), b'element face %d' % v.sum())
    open(dst, 'wb').write(hdr + V.tobytes() + F[v].tobytes())


def main():
    src, job = sys.argv[1], os.path.abspath(sys.argv[2])
    cm = sys.argv[3] if len(sys.argv) > 3 else ''
    os.makedirs(job, exist_ok=True)
    img, md, mi, col = (os.path.join(job, x) for x in ('imagenes', 'mascaras', 'recortes', 'colmap'))
    if not os.path.isdir(img):
        p.preparar(src, img, os.path.join(job, 'borrosas'))
    p.objeto(img, md, mi)  # plato recortado, fondo negro: RealityScan arma solo el plato

    malla = os.path.join(job, 'malla.ply')
    if not os.path.exists(malla):
        shutil.rmtree(col, ignore_errors=True)
        os.makedirs(col)
        xml = os.path.join(job, 'colmap_params.xml')
        open(xml, 'w', encoding='utf-8').write(PARAMS)  # sin BOM: con BOM RealityScan no lo lee (err:5617)
        realityscan(job, '-newScene', '-addFolder', mi, '-align', '-selectMaximalComponent',
                    '-setReconstructionRegionAuto', '-calculateNormalModel', '-save', os.path.join(job, 'plato.rsproj'),
                    # fuera los triangulos gigantes del fondo negro y los pedazos sueltos
                    '-selectMarginalTriangles', '-removeSelectedTriangles', '-selectLargeTrianglesRel', '8',
                    '-removeSelectedTriangles', '-selectLargestModelComponent', '-invertTrianglesSelection',
                    '-removeSelectedTriangles', '-cleanModel', '-simplify', '1000000',
                    '-save', os.path.join(job, 'plato.rsproj'),
                    '-exportRegistration', os.path.join(col, 'colmap.txt'), xml,
                    '-exportSelectedModel', malla + '.tmp.ply')
        cero = os.path.join(col, 'sparse', '0')
        for f in os.listdir(cero):  # InterfaceCOLMAP busca sparse/cameras.txt
            os.replace(os.path.join(cero, f), os.path.join(col, 'sparse', f))
        os.rmdir(cero)
        os.replace(malla + '.tmp.ply', malla)
    fotos = sum(1 for l in open(os.path.join(col, 'sparse', 'images.txt')) if l.strip() and not l.startswith('#')) // 2
    print(f'RealityScan ubico {fotos} de {len(os.listdir(mi))} fotos')

    def mvs(exe, sale, *a):
        if not os.path.exists(os.path.join(col, sale)):
            p.run(os.path.join(p.MVS, exe + '.exe'), '-w', col, *a, cwd=col)
    cj = os.path.join(job, 'camaras.json')
    if not os.path.exists(cj):
        lineas = [l for l in open(os.path.join(col, 'sparse', 'images.txt')) if not l.startswith('#')]
        cams = []
        for l in lineas[::2]:
            q = l.split()
            qw, qx, qy, qz, tx, ty, tz = map(float, q[1:8])
            r = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                          [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                          [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
            cams.append({'foto': q[9], 'centro': (-r.T @ [tx, ty, tz]).tolist(), 'mira': r[2].tolist()})
        json.dump(cams, open(cj, 'w'))

    if not os.path.exists(os.path.join(col, 'malla.ply')):
        vista = os.path.join(col, 'malla_vista.ply')
        girar(malla, vista, os.path.join(col, 'sparse', 'points3D.txt'), [c['centro'] for c in json.load(open(cj))])
        # sin la base giratoria y sin huecos (pedidos del usuario): se hace ANTES de pintar, asi cada parche lleva la foto
        p.run(sys.executable, os.path.join(p.AQUI, 'cerrar.py'), vista, os.path.join(col, 'malla.ply'), cj)
    mvs('InterfaceCOLMAP', 'scene.mvs', '-i', '.', '-o', 'scene.mvs')
    # caras sin foto en gris claro (por defecto salen naranjas); nivelado de costuras apagado como en procesar.py
    mvs('TextureMesh', 'modelo.glb', '-i', 'scene.mvs', '-m', 'malla.ply', '-o', 'modelo.glb', '--export-type', 'glb',
        '--global-seam-leveling', 0, '--local-seam-leveling', 0, '--empty-color', 0xDCDCDC)

    limpio = os.path.join(job, 'limpio.glb')
    p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.AQUI, 'limpiar.py'), '--',
          os.path.join(col, 'modelo.glb'), cj, limpio, 'sin_corte')  # fondo recortado: no hay mesa que cortar
    if cm:
        web = os.path.join(job, 'web.glb')
        p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.WEB, 'make_web_glb.py'), '--', limpio, web, cm,
              200000, 'sin_nivelar', cwd=p.WEB)
        vista = os.path.join(job, 'vista.png')
        p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.AQUI, 'ver.py'), '--', web, vista)
        cv2.imwrite(vista, cv2.hconcat([cv2.imread(f'{vista}.{i}.png') for i in range(5)]))
        print('VISTA', vista)


if __name__ == '__main__':
    main()
