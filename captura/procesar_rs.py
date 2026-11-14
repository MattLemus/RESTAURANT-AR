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

from pathlib import Path
from datetime import datetime, timezone
import hashlib
try:
    import cv2
except ImportError:
    cv2 = None
import numpy as np

import procesar as p

RS = r'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe'
RS = os.environ.get('REALITYSCAN_EXE', RS)
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
    # Un registro por ejecución; errores de proceso y del registro no se ignoran.
    args = [RS, '-headless', '-silent', os.path.join(job, 'crash'), '-stdConsole',
            '-set', 'appQuitOnError=true', *cmds, '-quit']
    log = p.run(*args, cwd=job)
    text = Path(log).read_text(encoding='utf-8', errors='replace')
    if 'Processing failed' in text:
        raise RuntimeError(f'RealityScan falló. Ver {log}')


def stage_inputs(img, md, destination):
    """RGB originales orientados + capas mask oficiales. Ningún RGB con fondo negro."""
    dest = Path(destination)
    dest.mkdir(exist_ok=True)
    for photo in sorted(Path(img).glob('*.png')):
        for source, target in [(photo, dest / photo.name),
                               (Path(md) / (photo.name + '.png'), dest / (photo.name + '.mask.png'))]:
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError('Entrada o máscara cambió: utiliza un trabajo nuevo')
            if not target.exists():
                shutil.copy2(source, target)
    return str(dest)


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
    from scipy.spatial import cKDTree
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
    print(f'CONSERVO {len(F)} caras, incluidas {(~v).sum()} sin cámara visible; no son ruido demostrado')
    open(dst, 'wb').write(b[:k] + V.tobytes() + F.tobytes())


def main():
    args = p.arguments(__doc__, rs=True)
    src, cm = args.src, args.cm
    p.preflight(RS, p.BLENDER, os.path.join(p.MVS, 'TextureMesh.exe'), os.path.join(p.MVS, 'InterfaceCOLMAP.exe'))
    config = Path(args.rs_config).resolve()
    if not config.is_file():
        raise FileNotFoundError('Exporta y revisa una configuración .rsconfig de RealityScan')
    job = p.init_job(args)
    config_copy = Path(job) / 'configuracion_realityscan.rsconfig'
    if config_copy.exists() and config_copy.read_bytes() != config.read_bytes():
        raise ValueError('La configuración cambió: usa un trabajo nuevo')
    if not config_copy.exists():
        shutil.copy2(config, config_copy)
    (Path(job) / 'configuracion_sha256.txt').write_text(hashlib.sha256(config_copy.read_bytes()).hexdigest(), encoding='ascii')
    img, md, mi, col = (os.path.join(job, x) for x in ('imagenes', 'mascaras', 'recortes', 'colmap'))
    if not os.path.isdir(img):
        p.preparar(src, img, os.path.join(job, 'borrosas'))
    p.reviewed_masks(img, md, args.approve_masks)
    mi = stage_inputs(img, md, os.path.join(job, 'rs_inputs'))

    malla = os.path.join(job, 'malla.ply')
    if not os.path.exists(malla):
        os.makedirs(col, exist_ok=True)
        xml = os.path.join(job, 'colmap_params.xml')
        open(xml, 'w', encoding='utf-8').write(PARAMS)  # sin BOM: con BOM RealityScan no lo lee (err:5617)
        # Comandos y claves comprobados en la documentación oficial. High Detail usa resolución completa.
        realityscan(job, '-importGlobalSettings', str(config_copy),
                    '-set', 'appQuitOnError=true', '-set', 'appIncSubdirs=false',
                    '-set', 'MvsGeometryMarginStyle=false', '-set', 'mvsMinSampleDistance=0.0',
                    '-set', 'mvsDecimationFactor=1.0', '-set', 'sfmImageDownscaleFactor=1',
                    '-set', 'sfmFeatureDetectionQuality=High',
                    '-newScene', '-addFolder', mi, '-selectAllImages', '-setDownscaleForDepthMaps', '1',
                    '-align', '-selectMaximalComponent', '-setReconstructionRegionAuto',
                    '-calculateHighModel', '-save', os.path.join(job, 'maestro.rsproj'),
                    '-exportGlobalSettings', os.path.join(job, 'configuracion_efectiva.rsconfig'),
                    '-exportRegistration', os.path.join(col, 'colmap.txt'), xml,
                    '-exportSelectedModel', malla + '.tmp.ply')
        cero = os.path.join(col, 'sparse', '0')
        for f in os.listdir(cero):  # InterfaceCOLMAP busca sparse/cameras.txt
            os.replace(os.path.join(cero, f), os.path.join(col, 'sparse', f))
        os.rmdir(cero)
        os.replace(malla + '.tmp.ply', malla)
    fotos = sum(1 for l in open(os.path.join(col, 'sparse', 'images.txt')) if l.strip() and not l.startswith('#')) // 2
    assert fotos >= .7 * len(list(Path(img).glob('*.png'))), 'Menos del 70% de fotos alineadas; revisar captura y máscaras'
    print(f"RealityScan ubico {fotos} de {len(list(Path(img).glob('*.png')))} fotos")

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
        # Conservar todos los triángulos originales; nunca sustituirlos por alturas XY.
        shutil.copy2(vista, os.path.join(col, 'malla.ply'))  # misma superficie; se permiten bordes abiertos
    mvs('InterfaceCOLMAP', 'scene.mvs', '-i', '.', '-o', 'scene.mvs')
    # caras sin foto en gris claro (por defecto salen naranjas); nivelado de costuras apagado como en procesar.py
    mvs('TextureMesh', 'modelo.glb', '-i', 'scene.mvs', '-m', 'malla.ply', '-o', 'modelo.glb', '--export-type', 'glb',
        '--resolution-level', 0, '--decimate', 1, '--close-holes', 0,
        '--global-seam-leveling', 0, '--local-seam-leveling', 0, '--empty-color', 0xDCDCDC)

    master = os.path.join(job, 'maestro_texturizado.glb')
    if not os.path.exists(master):
        shutil.copy2(os.path.join(col, 'modelo.glb'), master)
    limpio = os.path.join(job, 'limpio.glb')
    if not os.path.exists(limpio):
        p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.AQUI, 'limpiar.py'), '--',
              os.path.join(col, 'modelo.glb'), cj, limpio, 'conservar_geometria')  # conservar superficie y materiales
    if cm:
        web = os.path.join(job, 'web.glb')
        if not os.path.exists(web):
            p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.WEB, 'make_web_glb.py'), '--', limpio, web, cm,
                  args.mobile_tris, 'sin_nivelar', cwd=p.WEB)
        vista = os.path.join(job, 'vista.png')
        p.run(p.BLENDER, '-b', '--factory-startup', '-P', os.path.join(p.AQUI, 'ver.py'), '--', web, vista)
        if cv2 is not None:
            cv2.imwrite(vista, cv2.hconcat([cv2.imread(f'{vista}.{i}.png') for i in range(5)]))
        print('VISTA', vista)


if __name__ == '__main__':
    main()
