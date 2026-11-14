"""Genera una primera malla texturizada de una sesión, sin conexión a internet."""

import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess

from PIL import Image, ImageOps

import procesar


def has_default_route(table, destination):
    active = re.search(rb'(?im)^[ \t]*(?:Active Routes|Rutas activas):[^\r\n]*\r?$', table)
    if active is None:
        raise ValueError('Windows no mostró la tabla de rutas activas.')
    rows = re.split(rb'(?im)^[ \t]*(?:Persistent Routes|Rutas persistentes):', table[active.end():], maxsplit=1)[0]
    return re.search(destination, rows, re.MULTILINE) is not None


def require_offline():
    # route.exe funciona sin el acceso a CIM que Get-NetRoute requiere.
    route = Path(os.environ['SystemRoot']) / 'System32' / 'route.exe'
    try:
        for family, destination in [('-4', rb'^[ \t]*0\.0\.0\.0[ \t]+0\.0\.0\.0[ \t]+'),
                                    ('-6', rb'^[ \t]*\d+[ \t]+\d+[ \t]+::/0[ \t]+')]:
            table = subprocess.check_output([str(route), 'print', family], stderr=subprocess.STDOUT, timeout=10)
            if has_default_route(table, destination):
                raise SystemExit('Windows todavía tiene una ruta de red activa. Apaga el Wi-Fi y desconecta Ethernet. '
                                 'Si usas anclaje USB, apágalo en el teléfono. Luego repite el comando.')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'No se pudo comprobar el estado de la red. El procesamiento no empezó. {error}') from error


def embed_texture(glb):
    """Make the OpenMVS export portable without changing pixels or mesh data."""
    raw = glb.read_bytes()
    magic, version, total, json_size, kind = struct.unpack_from('<4sIII4s', raw)
    if (magic, version, total, kind) != (b'glTF', 2, len(raw), b'JSON'):
        raise ValueError('OpenMVS no produjo un GLB válido.')
    document = json.loads(raw[20:20 + json_size])
    start = 28 + json_size
    bin_size, bin_kind = struct.unpack_from('<I4s', raw, start - 8)
    if bin_kind != b'BIN\0' or start + bin_size != len(raw) or len(document['buffers']) != 1:
        raise ValueError('La malla no tiene el búfer binario esperado.')
    binary = bytearray(raw[start:])
    for image in document.get('images', []):
        uri = image.get('uri')
        if not uri:
            continue
        if Path(uri).name != uri or not uri.lower().endswith('.png'):
            raise ValueError('La textura exportada no es un PNG local.')
        texture = (glb.parent / uri).read_bytes()
        image.update(bufferView=len(document['bufferViews']), mimeType='image/png')
        del image['uri']
        document['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(texture)})
        binary.extend(texture)
        binary.extend(b'\0' * (-len(binary) % 4))
    document['buffers'][0]['byteLength'] = len(binary)
    metadata = json.dumps(document, separators=(',', ':')).encode()
    metadata += b' ' * (-len(metadata) % 4)
    temp = glb.with_suffix('.tmp')
    with temp.open('wb') as output:
        output.write(struct.pack('<4sIII4s', b'glTF', 2, 28 + len(metadata) + len(binary), len(metadata), b'JSON'))
        output.write(metadata)
        output.write(struct.pack('<I4s', len(binary), b'BIN\0'))
        output.write(binary)
    os.replace(temp, glb)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sesion', type=Path, help='Carpeta de originales y manifest.json')
    parser.add_argument('trabajo', type=Path, help='Carpeta nueva para esta reconstrucción')
    parser.add_argument('--manifest', type=Path, help='Copia del informe seleccionado al enviar')
    parser.add_argument('--alta-calidad', action='store_true', help='Usar los píxeles a resolución completa')
    args = parser.parse_args()
    require_offline()
    import pycolmap

    source = args.sesion.resolve()
    work = args.trabajo.resolve()
    if work == source or work.is_relative_to(source):
        parser.error('La carpeta de trabajo debe estar fuera de la carpeta de originales.')
    mvs_bin = Path(procesar.AQUI) / 'trabajos/_runtime/openmvs/vc17/x64/Release'
    stages = ('InterfaceCOLMAP', 'DensifyPointCloud', 'ReconstructMesh', 'TextureMesh')
    procesar.preflight(*(mvs_bin / f'{stage}.exe' for stage in stages))
    report = json.loads((args.manifest or source / 'manifest.json').read_text(encoding='utf-8'))
    photos = []
    for record in report['records']:
        if record['valid'] and not record.get('superseded'):
            stem = f"{source.name}_{int(record['sequence']):03d}"
            path = next((item for item in source.glob(stem + '.*') if item.suffix.lower() in {'.jpg', '.png'}), None)
            if path is None:
                raise SystemExit(f'Falta el original {stem}. Reenvía la sesión desde el teléfono.')
            photos.append(path)
    if len(photos) < 8:
        raise SystemExit('Faltan fotografías aceptadas para una primera reconstrucción.')

    work.mkdir(parents=True, exist_ok=False)
    procesar.LOG_DIR = str(work / 'logs')
    images, sparse, dense = (work / name for name in ('imagenes', 'sparse', 'dense'))
    images.mkdir()
    sparse.mkdir()
    dense.mkdir()
    print(f'Preparando {len(photos)} copias de trabajo. Los originales se quedan intactos.', flush=True)
    for original in photos:
        with Image.open(original) as image:
            preview = ImageOps.exif_transpose(image).convert('RGB')
            if not args.alta_calidad:
                preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            preview.save(images / f'{original.stem}.png')

    database = work / 'colmap.db'
    extraction = pycolmap.FeatureExtractionOptions(max_image_size=-1 if args.alta_calidad else 1600, num_threads=2)
    extraction.sift.first_octave = 0
    extraction.sift.max_num_features = 12000 if args.alta_calidad else 4500
    pycolmap.extract_features(database, images, extraction_options=extraction, device=pycolmap.Device.cpu)
    pycolmap.match_exhaustive(database, matching_options=pycolmap.FeatureMatchingOptions(num_threads=4),
                             device=pycolmap.Device.cpu)
    models = pycolmap.incremental_mapping(database, images, sparse,
                                          pycolmap.IncrementalPipelineOptions(num_threads=4, min_model_size=6))
    if not models:
        raise SystemExit('COLMAP no pudo alinear suficientes vistas. Se conservaron los archivos de diagnóstico.')
    key, model = max(models.items(), key=lambda item: item[1].num_reg_images())
    print(f'Alineadas {model.num_reg_images()} de {len(photos)} fotos.', flush=True)
    model.export_PLY(work / 'nube.ply')
    print('Corrigiendo la distorsión de la cámara', flush=True)
    pycolmap.undistort_images(dense, sparse / str(key), images, num_threads=2,
                              jpeg_quality=100 if args.alta_calidad else -1)

    def mvs(stage, *options):
        require_offline()
        procesar.run(mvs_bin / f'{stage}.exe', '-w', str(dense), *options, cwd=str(dense))

    mvs('InterfaceCOLMAP', '-i', '.', '-o', 'scene.mvs')
    longest_edge = 1200
    if args.alta_calidad:
        undistorted = [path for path in (dense / 'images').rglob('*')
                       if path.suffix.lower() in ('.png', '.jpg', '.jpeg')]
        if not undistorted:
            raise SystemExit('COLMAP no exportó las imágenes corregidas.')
        for path in undistorted:
            with Image.open(path) as image:
                longest_edge = max(longest_edge, *image.size)
    print('Reconstruyendo el volumen del plato', flush=True)
    mvs('DensifyPointCloud', '-i', 'scene.mvs', '-o', 'denso.mvs',
        '--resolution-level', 0 if args.alta_calidad else 1, '--max-resolution', longest_edge, '--max-threads', 4)
    mvs('ReconstructMesh', '-i', 'denso.mvs', '-o', 'malla.ply', '--decimate', 1, '--remove-spurious', 0,
        '--remove-spikes', 0, '--close-holes', 0, '--smooth', 0)
    print('Proyectando la textura de las fotos', flush=True)
    mvs('TextureMesh', '-i', 'denso.mvs', '-m', 'malla.ply', '-o', 'prueba_3d.glb', '--export-type', 'glb',
        '--resolution-level', 0, '--decimate', 1, '--close-holes', 0,
        '--global-seam-leveling', 0, '--local-seam-leveling', 0)
    glb = dense / 'prueba_3d.glb'
    with glb.open('rb') as file:
        if file.read(4) != b'glTF':
            raise SystemExit(f'El archivo generado no tiene una cabecera GLB válida: {glb}')
    if args.alta_calidad:
        embed_texture(glb)
    print(f'Vista previa sin recorte ni escala AR: {glb}', flush=True)


if __name__ == '__main__':
    main()
