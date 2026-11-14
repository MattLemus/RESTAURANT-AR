# python procesar.py <carpeta_fotos | video> <trabajo> [ancho_cm]   (video: el de web/grabar.html)
# Fotos de un plato real -> modelo 3D limpio (trabajo/limpio.glb) y, con ancho_cm, el GLB de la web (trabajo/web.glb).
# Sirve con el celular quieto y el plato en una base giratoria, o caminando una vuelta alrededor del plato.
# Se conservan intermedios. Para comparar parámetros, usar un trabajo nuevo.
import re
import argparse
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageOps
import glob
import json
import os
import shutil
import subprocess
import sys

try:
    import cv2
except ImportError:
    cv2 = None  # Solo requerido para vídeo, máscaras y reconstrucción.
import numpy as np

COLMAP = r'C:\Mattech\tools\colmap\bin\colmap.exe'
MVS = r'C:\Mattech\tools\openmvs\vc17\x64\Release'
BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
COLMAP = os.environ.get('COLMAP_EXE', COLMAP)
MVS = os.environ.get('OPENMVS_DIR', MVS)
BLENDER = os.environ.get('BLENDER_EXE', BLENDER)
LOG_DIR = None
AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, '..')


def run(*cmd, cwd=None):
    command = [str(c) for c in cmd]
    print('>>', ' '.join(command), flush=True)
    folder = Path(LOG_DIR or cwd or AQUI)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f')
    log = folder / f'comando_{stamp}.log'
    with log.open('w', encoding='utf-8') as output:
        result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    with (folder / 'comandos.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps({'command': command, 'cwd': cwd, 'log': str(log),
                                 'returncode': result.returncode}) + '\n')
    if result.returncode:
        raise RuntimeError(f'Falló {command[0]} ({result.returncode}). Ver {log}')
    return log


def arguments(description, rs=False):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('src')
    parser.add_argument('job')
    parser.add_argument('cm', nargs='?', default='')
    parser.add_argument('--mode', choices=['walk', 'turntable'], default='walk')
    parser.add_argument('--approve-masks', action='store_true', help='Confirmar inspección visual de todas las máscaras')
    parser.add_argument('--mobile-tris', type=int, default=0, help='0 conserva detalle; la reducción solo afecta web.glb')
    if rs:
        parser.add_argument('--rs-config', required=True, help='Configuración exportada y revisada de RealityScan')
    return parser.parse_args()


def init_job(args):
    global LOG_DIR
    job = Path(args.job).resolve()
    marker = job / 'pipeline_v2.json'
    config = {'version': 2, 'source': str(Path(args.src).resolve()), 'mode': args.mode,
              'cm': getattr(args, 'cm', ''), 'mobile_tris': getattr(args, 'mobile_tris', 0)}
    if marker.exists():
        old = json.loads(marker.read_text(encoding='utf-8'))
        if any(old.get(key) != value for key, value in config.items()):
            raise ValueError('Usa una carpeta de trabajo nueva para otra fuente o modo')
    elif job.exists() and any(job.iterdir()):
        raise ValueError('Trabajo antiguo: usa una carpeta NUEVA. No se mezclarán resultados destructivos previos.')
    job.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(config, indent=2), encoding='utf-8')
    LOG_DIR = str(job / 'logs')
    Path(LOG_DIR).mkdir(exist_ok=True)
    return str(job)


def preflight(*executables):
    missing = [str(e) for e in executables if not Path(e).is_file() and not shutil.which(str(e))]
    if missing:
        raise FileNotFoundError('Faltan herramientas: ' + ', '.join(missing) +
                                '. Configura COLMAP_EXE, OPENMVS_DIR, BLENDER_EXE o REALITYSCAN_EXE.')


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
    """Archiva originales byte a byte; RGB orientado en PNG sin pérdida ni reducción.
    Los rechazos heurísticos se informan, nunca se apartan automáticamente.
    Un manifiesto del capturador selecciona solo objetivos aceptados vigentes.
    """
    if os.path.isfile(src):
        if cv2 is None:
            raise RuntimeError('Vídeo requiere opencv-python; para máxima calidad utiliza fotos originales')
        folder = img + '_video'
        if not os.path.isdir(folder):
            cuadros(src, folder + '.tmp')
            os.replace(folder + '.tmp', folder)
        src = folder
    source = Path(src)
    photos = sorted(f for f in source.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png'))
    manifest_path = source / 'manifest.json'
    if not manifest_path.exists():
        downloaded = list(source.glob('*_informe.json'))
        if len(downloaded) == 1:
            manifest_path = downloaded[0]
    if not manifest_path.exists() and any(re.fullmatch(r'plato_\d{8}_\d{6}_[a-f0-9]{1,8}_\d{3,5}', f.stem) for f in photos):
        raise ValueError('Falta informe del capturador; descárgalo o pulsa Reenviar pendientes')
    if not manifest_path.exists() and (list(source.glob('*.jpg.json')) or list(source.glob('*.png.json'))):
        raise ValueError('Falta manifest.json: vuelve al capturador y pulsa Reenviar pendientes antes de procesar')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        accepted = {int(r['sequence']) for r in manifest['records'] if r.get('valid') and not r.get('superseded')}
        photos = [f for f in photos if int(f.stem.rsplit('_', 1)[-1]) in accepted]
        present = {int(f.stem.rsplit('_', 1)[-1]) for f in photos}
        if accepted - present:
            raise ValueError('Faltan originales aceptados en la PC; pulsa Reenviar pendientes')
    if len(photos) < 20:
        raise ValueError(f'Solo {len(photos)} fotos válidas en {src}; se requieren al menos 20')
    final = Path(img)
    if final.exists():
        raise FileExistsError(f'No sobrescribir RGB existentes: {final}')
    dest = Path(img + '.preparando')
    originals = dest.parent / 'originales'
    dest.mkdir(parents=True, exist_ok=True)
    originals.mkdir(exist_ok=True)
    audit = []
    for index, photo in enumerate(photos, 1):
        data = photo.read_bytes()
        archive = originals / photo.name
        if archive.exists() and archive.read_bytes() != data:
            raise FileExistsError(f'Original distinto ya archivado: {archive}')
        if not archive.exists():
            archive.write_bytes(data)
        with Image.open(photo) as image:
            rgb = ImageOps.exif_transpose(image).convert('RGB')
            name = f'{index:04d}_{photo.stem}.png'
            rgb.save(dest / name, 'PNG')
            small = np.asarray(rgb.resize((320, 240)).convert('L'), dtype=float)
            lap = small[1:-1, :-2] + small[1:-1, 2:] + small[:-2, 1:-1] + small[2:, 1:-1] - 4 * small[1:-1, 1:-1]
            audit.append({'original': photo.name, 'rgb': name, 'sha256': hashlib.sha256(data).hexdigest(),
                          'width': rgb.width, 'height': rgb.height, 'sharpness': float(lap.var()),
                          'mean': float(small.mean()), 'warning': bool(small.mean() < 48 or small.mean() > 218)})
    (dest.parent / 'calidad_fotos.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    if manifest_path.exists():
        shutil.copy2(manifest_path, originals / 'manifest.json')
    dest.rename(final)  # una preparación parcial nunca se confunde con una completada
    print(f'{len(audit)} originales intactos y RGB PNG de resolución completa; revisar calidad_fotos.json')


def objeto(img, md, mi=None):
    """Solo máscaras. No pintar fondo negro, erosionar bordes ni quitar ingredientes aislados."""
    if cv2 is None:
        raise RuntimeError('Instala opencv-python y rembg para generar máscaras')
    from rembg import new_session, remove
    session = None
    os.makedirs(md, exist_ok=True)
    for photo in sorted(Path(img).glob('*.png')):
        mask_path = Path(md) / (photo.name + '.png')  # convención COLMAP: nombre completo + .png
        if mask_path.exists():
            continue
        if session is None:
            session = new_session('isnet-general-use')
        with Image.open(photo) as im:
            mask = np.asarray(remove(im.convert('RGB'), session=session, only_mask=True))
        mask = (mask > 96).astype(np.uint8) * 255
        # Margen conservador, conservando TODOS los componentes de la segmentación.
        mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))
        coverage = float((mask > 0).mean())
        if not .03 < coverage < .98:
            raise ValueError(f'Máscara dudosa en {photo.name}: {coverage:.0%}. Corregir a mano.')
        Image.fromarray(mask).save(mask_path)
        print(f'Máscara {photo.name}: {coverage:.0%}. Revisar borde e ingredientes.', flush=True)


def reviewed_masks(img, md, approved):
    objeto(img, md)
    for photo in Path(img).glob('*.png'):
        with Image.open(photo) as rgb, Image.open(Path(md) / (photo.name + '.png')) as mask:
            if rgb.size != mask.size:
                raise ValueError(f'Máscara con dimensiones incorrectas: {photo.name}')
    if not approved:
        raise RuntimeError(f'Máscaras generadas en {md}. Revisa y corrige TODAS; repite con --approve-masks. RGB intacto.')


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
    args = arguments(__doc__)
    src, cm = args.src, args.cm
    preflight(COLMAP, BLENDER, os.path.join(MVS, 'TextureMesh.exe'), os.path.join(MVS, 'DensifyPointCloud.exe'))
    job = init_job(args)
    img, db, dense, md, mi = (os.path.join(job, x) for x in ('imagenes', 'colmap.db', 'dense', 'mascaras', 'recortes'))
    if not os.path.isdir(img):
        preparar(src, img, os.path.join(job, 'borrosas'))

    reviewed_masks(img, md, args.approve_masks)
    if not os.path.exists(db):
        mask = ['--ImageReader.mask_path', md]  # COLMAP: negro = no buscar puntos ahi
        # GPU apagada: COLMAP con CUDA se cae (0xC0000409) en la RTX 5060 (probado de nuevo 2026-11-05).
        # Prioridad de detalle: hasta 16384 puntos por foto, conservando la opción CPU existente.
        run(COLMAP, 'feature_extractor', '--database_path', db + '.tmp', '--image_path', img,
            '--ImageReader.single_camera', 1, '--FeatureExtraction.use_gpu', 0,
            '--SiftExtraction.max_num_features', 16384, *mask)
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
        run(COLMAP, 'image_undistorter', '--image_path', img, '--input_path', modelo, '--output_path', dense + '.tmp',
            '--output_type', 'COLMAP')
        os.replace(dense + '.tmp', dense)
    def mvs(exe, sale, *a):
        if not os.path.exists(os.path.join(dense, sale)):
            run(os.path.join(MVS, exe + '.exe'), '-w', dense, *a, cwd=dense)

    mvs('InterfaceCOLMAP', 'scene.mvs', '-i', '.', '-o', 'scene.mvs')
    max_resolution = max(max(Image.open(f).size) for f in Path(img).glob('*.png'))
    mvs('DensifyPointCloud', 'denso.mvs', '-i', 'scene.mvs', '-o', 'denso.mvs',
        '--resolution-level', 0, '--max-resolution', max_resolution)
    mvs('ReconstructMesh', 'malla.ply', '-i', 'denso.mvs', '-o', 'malla.ply',
        '--decimate', 1, '--remove-spurious', 0, '--remove-spikes', 0, '--close-holes', 0, '--smooth', 0)
    # nivelado de costuras apagado: en este OpenMVS de Windows deja negra casi toda la textura
    mvs('TextureMesh', 'modelo.glb', '-i', 'denso.mvs', '-m', 'malla.ply', '-o', 'modelo.glb', '--export-type', 'glb',
        '--resolution-level', 0, '--decimate', 1, '--close-holes', 0,
        '--global-seam-leveling', 0, '--local-seam-leveling', 0)
    tex = os.path.join(dense, 'modelo.glb')

    master = os.path.join(job, 'maestro_texturizado.glb')
    if not os.path.exists(master):
        shutil.copy2(tex, master)
    limpio = os.path.join(job, 'limpio.glb')
    if not os.path.exists(limpio):
        run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(AQUI, 'limpiar.py'), '--', tex, cj, limpio,
            'conservar_geometria')  # no aplicar recortes heurísticos al maestro
    if cm:
        web = os.path.join(job, 'web.glb')
        if not os.path.exists(web):
            run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(WEB, 'make_web_glb.py'), '--', limpio, web, cm,
                args.mobile_tris, 'sin_nivelar', cwd=WEB)
        vista = os.path.join(job, 'vista.png')
        run(BLENDER, '-b', '--factory-startup', '-P', os.path.join(AQUI, 'ver.py'), '--', web, vista)
        if cv2 is not None:
            cv2.imwrite(vista, cv2.hconcat([cv2.imread(f'{vista}.{i}.png') for i in range(5)]))
        print('VISTA', vista)


if __name__ == '__main__':
    main()
