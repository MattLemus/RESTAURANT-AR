# python procesar.py <carpeta_fotos | video> <trabajo> [ancho_cm]   (video: el de web/grabar.html)
# Fotos de un plato real -> modelo 3D limpio (trabajo/limpio.glb) y, con ancho_cm, el GLB de la web (trabajo/web.glb).
# Sirve con el celular quieto y el plato en una base giratoria, o caminando una vuelta alrededor del plato.
# Cada paso se salta si su resultado ya existe: para repetir uno, borrar su carpeta/archivo en el trabajo.
import glob
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

COLMAP = r'C:\Mattech\tools\colmap\bin\colmap.exe'
MVS = r'C:\Mattech\tools\openmvs\vc17\x64\Release'
BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, '..')


def run(*cmd, cwd=None):
    print('>>', ' '.join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def cuadros(video, dst, n=90):
    """Video de grabar.html (3 vueltas) -> n imagenes: el video se parte en n tramos iguales y de cada uno queda el
    cuadro mas nitido. Las pausas fuera de altura ya no estan en el video, asi que los tramos siguen la vuelta."""
    cap = cv2.VideoCapture(video)
    nit = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(im, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        nit.append(cv2.Laplacian(g, cv2.CV_64F).var())
    assert len(nit) >= n, f'el video tiene solo {len(nit)} cuadros'
    tramos = np.array_split(np.arange(len(nit)), n)
    elegidos = {int(t[np.argmax([nit[i] for i in t])]) for t in tramos}
    os.makedirs(dst, exist_ok=True)
    cap = cv2.VideoCapture(video)
    i, ancho = 0, 0
    while True:
        ok, im = cap.read()
        if not ok:
            break
        if i in elegidos:
            cv2.imwrite(os.path.join(dst, f'cuadro_{i:05d}.png'), im)
            ancho = im.shape[1]
        i += 1
    print(f'VIDEO {len(nit)} cuadros -> {len(elegidos)} elegidos ({ancho} px de ancho)')


def preparar(src, img, borrosas):
    """Copia las fotos derechas (EXIF), a lo mas 4032 px, y aparta las movidas."""
    if os.path.isfile(src):  # un video: primero se sacan los cuadros
        carpeta = img + '_video'
        if not os.path.isdir(carpeta):
            cuadros(src, carpeta + '.tmp')
            os.replace(carpeta + '.tmp', carpeta)
        src = carpeta
    fotos = sorted(f for f in glob.glob(os.path.join(src, '*')) if f.lower().endswith(('.jpg', '.jpeg', '.png')))
    assert len(fotos) >= 20, f'solo {len(fotos)} fotos en {src}'
    os.makedirs(img)
    os.makedirs(borrosas, exist_ok=True)
    nitidez = {}
    for f in fotos:
        im = cv2.imread(f)  # aplica la rotacion EXIF del celular
        s = 4032 / max(im.shape[:2])
        if s < 1:
            im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        n = os.path.splitext(os.path.basename(f))[0] + '.jpg'
        cv2.imwrite(os.path.join(img, n), im, [cv2.IMWRITE_JPEG_QUALITY, 97])
        g = cv2.cvtColor(cv2.resize(im, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        nitidez[n] = cv2.Laplacian(g, cv2.CV_64F).var()  # detalle fino: una foto movida tiene mucho menos
    med = np.median(list(nitidez.values()))
    for n, v in sorted(nitidez.items()):
        if v < 0.4 * med:
            shutil.move(os.path.join(img, n), os.path.join(borrosas, n))
            print(f'BORROSA {n}: nitidez {v / med:.2f} de la mediana')
    print(f'{len(os.listdir(img))} fotos nitidas, {len(os.listdir(borrosas))} borrosas')


def objeto(img, md, mi):
    """Recorta el plato con la comida en cada foto (rembg, isnet-general-use). COLMAP solo busca puntos ahi (md) y
    OpenMVS arma la forma con el fondo en negro (mi). Asi da igual caminar alrededor, girar el plato o mezclar las dos:
    si el plato gira, el fondo quieto haria creer a COLMAP que la camara no se movio."""
    from rembg import new_session, remove
    se = new_session('isnet-general-use')
    os.makedirs(md, exist_ok=True)
    os.makedirs(mi, exist_ok=True)
    nombres = sorted(os.listdir(img))
    for k, n in enumerate(nombres):
        if os.path.exists(os.path.join(mi, n)):
            continue
        im = cv2.imread(os.path.join(img, n))
        m = (np.array(remove(im, session=se, only_mask=True)) > 127).astype(np.uint8)
        # solo la mancha mas grande: el plato (la botella o la mano de al lado quedan fuera)
        nl, lab, st, _ = cv2.connectedComponentsWithStats(m)
        m = (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8) * 255 if nl > 1 else m * 255
        cv2.imwrite(os.path.join(md, n + '.png'), cv2.erode(m, np.ones((9, 9), np.uint8)))  # sin la mesa del borde
        ancho = cv2.dilate(m, np.ones((15, 15), np.uint8))  # un poco de margen para que el borde del plato se texture
        cv2.imwrite(os.path.join(mi, n), im * (ancho[:, :, None] > 0), [cv2.IMWRITE_JPEG_QUALITY, 97])
        print(f'recorte {k + 1}/{len(nombres)} {n}: plato {m.mean() / 2.55:.0f}% de la foto', flush=True)


def camaras(sparse, txt):
    """Centro y direccion de mirada de cada foto (coordenadas de COLMAP), para que limpiar.py sepa donde es arriba."""
    os.makedirs(txt, exist_ok=True)
    run(COLMAP, 'model_converter', '--input_path', sparse, '--output_path', txt, '--output_type', 'TXT')
    lineas = [l for l in open(os.path.join(txt, 'images.txt')) if not l.startswith('#')]
    cams = []
    for l in lineas[::2]:
        p = l.split()
        qw, qx, qy, qz, tx, ty, tz = map(float, p[1:8])
        r = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                      [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                      [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
        cams.append({'foto': p[9], 'centro': (-r.T @ [tx, ty, tz]).tolist(), 'mira': r[2].tolist()})
    return cams


def main():
    src, job = sys.argv[1], os.path.abspath(sys.argv[2])
    cm = sys.argv[3] if len(sys.argv) > 3 else ''
    os.makedirs(job, exist_ok=True)
    img, db, dense, md, mi = (os.path.join(job, x) for x in ('imagenes', 'colmap.db', 'dense', 'mascaras', 'recortes'))
    if not os.path.isdir(img):
        preparar(src, img, os.path.join(job, 'borrosas'))

    if not os.path.exists(db):
        objeto(img, md, mi)
        mask = ['--ImageReader.mask_path', md]  # COLMAP: negro = no buscar puntos ahi
        # GPU apagada: COLMAP con CUDA se cae (0xC0000409) en la RTX 5060 (probado de nuevo 2026-11-05).
        # 4096 puntos por foto en vez de 8192: comparar cuesta ~4 veces menos (con 8192 eran 25 min por 60 fotos)
        run(COLMAP, 'feature_extractor', '--database_path', db + '.tmp', '--image_path', img,
            '--ImageReader.single_camera', 1, '--FeatureExtraction.use_gpu', 0,
            '--SiftExtraction.max_num_features', 4096, *mask)
        run(COLMAP, 'exhaustive_matcher', '--database_path', db + '.tmp', '--FeatureMatching.use_gpu', 0)
        os.replace(db + '.tmp', db)

    sp = os.path.join(job, 'sparse')
    if not os.path.isdir(sp):
        os.makedirs(sp + '.tmp', exist_ok=True)
        run(COLMAP, 'mapper', '--database_path', db, '--image_path', img, '--output_path', sp + '.tmp')
        os.replace(sp + '.tmp', sp)
    # si quedaron varios pedazos, el que tiene mas fotos
    modelo = max(glob.glob(os.path.join(sp, '*')), key=lambda d: os.path.getsize(os.path.join(d, 'images.bin')))
    cj = os.path.join(job, 'camaras.json')
    if not os.path.exists(cj):
        cams = camaras(modelo, os.path.join(job, 'sparse_txt'))
        json.dump(cams, open(cj, 'w'))
    cams = json.load(open(cj))
    fuera = sorted(set(os.listdir(img)) - {c['foto'] for c in cams})
    print(f'COLMAP ubico {len(cams)} de {len(os.listdir(img))} fotos', ('; sin ubicar: ' + ', '.join(fuera)) if fuera else '')
    # con pocas fotos ubicadas el modelo sale a pedazos: mejor parar aqui y repetir esas fotos
    assert len(cams) >= 0.7 * len(os.listdir(img)), 'muy pocas fotos ubicadas: no sigo'

    if not os.path.isdir(dense):
        run(COLMAP, 'image_undistorter', '--image_path', mi, '--input_path', modelo, '--output_path', dense + '.tmp',
            '--output_type', 'COLMAP')
        os.replace(dense + '.tmp', dense)
    def mvs(exe, sale, *a):
        if not os.path.exists(os.path.join(dense, sale)):
            run(os.path.join(MVS, exe + '.exe'), '-w', dense, *a, cwd=dense)

    mvs('InterfaceCOLMAP', 'scene.mvs', '-i', '.', '-o', 'scene.mvs')
    mvs('DensifyPointCloud', 'denso.mvs', '-i', 'scene.mvs', '-o', 'denso.mvs')
    mvs('ReconstructMesh', 'malla.ply', '-i', 'denso.mvs', '-o', 'malla.ply')
    # nivelado de costuras apagado: en este OpenMVS de Windows deja negra casi toda la textura
    mvs('TextureMesh', 'modelo.glb', '-i', 'denso.mvs', '-m', 'malla.ply', '-o', 'modelo.glb', '--export-type', 'glb',
        '--global-seam-leveling', 0, '--local-seam-leveling', 0)
    tex = os.path.join(dense, 'modelo.glb')

    limpio = os.path.join(job, 'limpio.glb')
    run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(AQUI, 'limpiar.py'), '--', tex, cj, limpio,
        'sin_corte')  # con el fondo recortado no hay mesa: el 'plano' que encontraba era parte del plato
    if cm:
        web = os.path.join(job, 'web.glb')
        run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(WEB, 'make_web_glb.py'), '--', limpio, web, cm,
            200000, 'sin_nivelar', cwd=WEB)
        vista = os.path.join(job, 'vista.png')
        run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(AQUI, 'ver.py'), '--', web, vista)
        cv2.imwrite(vista, cv2.hconcat([cv2.imread(f'{vista}.{i}.png') for i in range(5)]))
        print('VISTA', vista)


if __name__ == '__main__':
    main()
