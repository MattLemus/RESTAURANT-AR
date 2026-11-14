import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageOps
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'captura'))
import procesar as pipeline
import procesar_rs as rs
import servidor
from cerrar import conservar


def photo(color=(90, 150, 60), fmt='JPEG'):
    out = io.BytesIO()
    Image.new('RGB', (96, 64), color).save(out, fmt)
    return out.getvalue()


def make_input(folder):
    folder.mkdir()
    for i in range(20):
        (folder / f'foto_{i:03d}.jpg').write_bytes(photo((i + 30, 150, 60)))


def test_original_bytes_and_lossless_rgb(tmp_path):
    source = tmp_path / 'source'
    make_input(source)
    dest = tmp_path / 'job' / 'imagenes'
    pipeline.preparar(str(source), str(dest), str(tmp_path / 'borrosas'))
    audit = json.loads((dest.parent / 'calidad_fotos.json').read_text())
    assert len(audit) == 20
    for item in audit:
        original = source / item['original']
        assert (dest.parent / 'originales' / original.name).read_bytes() == original.read_bytes()
        assert hashlib.sha256(original.read_bytes()).hexdigest() == item['sha256']
        with Image.open(original) as image, Image.open(dest / item['rgb']) as rgb:
            assert np.array_equal(np.asarray(ImageOps.exif_transpose(image).convert('RGB')), np.asarray(rgb))
    assert not (tmp_path / 'borrosas').exists()


def test_manifest_excludes_rejected_and_repeated(tmp_path):
    source = tmp_path / 'source'
    make_input(source)
    records = [{'sequence': i, 'valid': i != 3, 'superseded': i == 5} for i in range(20)]
    (source / 'manifest.json').write_text(json.dumps({'records': records}))
    with pytest.raises(ValueError, match='18'):
        pipeline.preparar(str(source), str(tmp_path / 'job' / 'imagenes'), '')
    assert len(list(source.glob('*.jpg'))) == 20


def test_upload_is_byte_preserving_and_retry_idempotent(tmp_path):
    data = photo()
    info = servidor.save_photo(tmp_path, 'plato_20261111_090000', 1, data)
    servidor.save_photo(tmp_path, 'plato_20261111_090000', 1, data)
    assert info['width'] == 96 and info['height'] == 64
    assert next(tmp_path.glob('*.jpg')).read_bytes() == data
    with pytest.raises(FileExistsError):
        servidor.save_photo(tmp_path, 'plato_20261111_090000', 1, photo((255, 0, 0)))
    assert next(tmp_path.glob('*.jpg')).read_bytes() == data


def test_upload_keeps_png_as_png(tmp_path):
    servidor.save_photo(tmp_path, 'plato_20261111_090000', 2, photo(fmt='PNG'))
    assert len(list(tmp_path.glob('*.png'))) == 1


def test_enqueue_only_uses_accepted_originals(tmp_path, monkeypatch):
    session = 'plato_20261111_090000'
    monkeypatch.setattr(servidor, 'RAIZ', tmp_path)
    monkeypatch.setattr(servidor, 'FOTOS', tmp_path / 'fotos')
    monkeypatch.setattr(servidor, 'JOBS', {})
    pending = []
    class Thread:
        def __init__(self, target, args, daemon):
            pending.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr(servidor.threading, 'Thread', Thread)
    source = servidor.FOTOS / session
    for sequence in range(1, 9):
        servidor.save_photo(source, session, sequence, photo())
    report = {'session': session, 'records': [dict(sequence=i, valid=i < 9) for i in range(1, 10)]}
    (source / 'manifest.json').write_text(json.dumps(report), encoding='utf-8')
    job = servidor.start_job(session)
    assert job['state'] == 'queued'
    assert job['sequences'] == list(range(1, 9))
    assert servidor.start_job(session) == job
    assert len(pending) == 1
    assert json.loads(pending[0][1][2].read_bytes()) == report


def test_portable_glb_preserves_mesh_and_png_bytes(tmp_path):
    import struct
    from prueba_3d_local import embed_texture

    texture = photo(fmt='PNG')
    (tmp_path / 'plate.png').write_bytes(texture)
    mesh = b'original mesh bytes '
    doc = {'buffers': [{'byteLength': len(mesh)}], 'bufferViews': [], 'images': [{'uri': 'plate.png'}]}
    metadata = json.dumps(doc).encode()
    metadata += b' ' * (-len(metadata) % 4)
    model = tmp_path / 'plate.glb'
    model.write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 28 + len(metadata) + len(mesh), len(metadata), b'JSON')
                      + metadata + struct.pack('<I4s', len(mesh), b'BIN\0') + mesh)
    embed_texture(model)
    data = model.read_bytes()
    size = struct.unpack_from('<I', data, 12)[0]
    new_doc = json.loads(data[20:20 + size])
    binary = data[28 + size:]
    view = new_doc['bufferViews'][new_doc['images'][0]['bufferView']]
    assert binary[:len(mesh)] == mesh
    assert binary[view['byteOffset']:view['byteOffset'] + view['byteLength']] == texture
    assert 'uri' not in new_doc['images'][0]


def test_corrupt_upload_not_saved(tmp_path):
    with pytest.raises((OSError, ValueError)):
        servidor.save_photo(tmp_path, 'plato_20261111_090000', 1, b'not a photo')
    assert not list(tmp_path.glob('*.jpg'))


def test_close_preserves_every_original_byte(tmp_path):
    source = tmp_path / 'overhang.ply'
    source.write_bytes(b'ply\nformat ascii 1.0\ncomment arbitrary overhang and disconnected ingredient\nend_header\n')
    target = tmp_path / 'preserved.ply'
    conservar(source, target)
    assert target.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        conservar(source, target)
    with pytest.raises(ValueError):
        conservar(source, source)


def test_unknown_old_job_not_reused(tmp_path):
    job = tmp_path / 'old'
    job.mkdir()
    (job / 'malla.ply').write_text('old model')
    args = argparse.Namespace(job=str(job), src=str(tmp_path), mode='walk')
    with pytest.raises(ValueError, match='NUEVA'):
        pipeline.init_job(args)
    assert (job / 'malla.ply').read_text() == 'old model'


def test_rs_masks_are_separate_layers_without_rgb_edit(tmp_path):
    images, masks = tmp_path / 'images', tmp_path / 'masks'
    images.mkdir(); masks.mkdir()
    rgb = photo(fmt='PNG')
    (images / 'dish.png').write_bytes(rgb)
    Image.new('L', (96, 64), 255).save(masks / 'dish.png.png')
    staged = Path(rs.stage_inputs(images, masks, tmp_path / 'rs_inputs'))
    assert (staged / 'dish.png').read_bytes() == rgb
    assert (staged / 'dish.png.mask.png').exists()
    (masks / 'dish.png.png').write_bytes(photo(fmt='PNG'))
    with pytest.raises(ValueError, match='cambió'):
        rs.stage_inputs(images, masks, staged)


def test_missing_tools_stop_with_actionable_error():
    with pytest.raises(FileNotFoundError, match='COLMAP_EXE'):
        pipeline.preflight('this-tool-does-not-exist-restaurant.exe')


def test_capture_source_requires_synchronized_manifest(tmp_path):
    make_input(tmp_path / 'source')
    (tmp_path / 'source' / 'foto_000.jpg.json').write_text('{}')
    with pytest.raises(ValueError, match='manifest.json'):
        pipeline.preparar(str(tmp_path / 'source'), str(tmp_path / 'rgb'), '')


def test_exif_orientation_does_not_change_archived_original(tmp_path):
    source = tmp_path / 'source'
    make_input(source)
    path = source / 'foto_000.jpg'
    image = Image.new('RGB', (120, 80), 'orange')
    exif = Image.Exif(); exif[274] = 6
    image.save(path, exif=exif)
    data = path.read_bytes()
    pipeline.preparar(str(source), str(tmp_path / 'job' / 'imagenes'), '')
    assert (tmp_path / 'job' / 'originales' / path.name).read_bytes() == data
    with Image.open(tmp_path / 'job' / 'imagenes' / '0001_foto_000.png') as rgb:
        assert rgb.size == (80, 120)


def test_rs_orchestration_keeps_master_and_uses_high_detail(tmp_path, monkeypatch):
    source, job = tmp_path / 'source', tmp_path / 'job'
    make_input(source)
    config = tmp_path / 'reviewed.rsconfig'; config.write_text('<reviewed-settings/>')
    args = argparse.Namespace(src=str(source), job=str(job), cm='', mode='walk',
                              mobile_tris=0, approve_masks=True, rs_config=str(config))
    monkeypatch.setattr(pipeline, 'arguments', lambda *a, **k: args)
    monkeypatch.setattr(pipeline, 'preflight', lambda *a: None)
    def masks(img, md, approved):
        Path(md).mkdir()
        for path in Path(img).glob('*.png'):
            with Image.open(path) as rgb:
                Image.new('L', rgb.size, 255).save(Path(md) / (path.name + '.png'))
    monkeypatch.setattr(pipeline, 'reviewed_masks', masks)
    commands = []
    def reconstruct(folder, *cmd):
        commands.extend(cmd)
        col = Path(folder) / 'colmap' / 'sparse' / '0'; col.mkdir(parents=True)
        photos = sorted((Path(folder) / 'imagenes').glob('*.png'))
        (col / 'images.txt').write_text(''.join(f'{i} 1 0 0 0 0 0 0 1 {p.name}\n0 0 -1\n' for i,p in enumerate(photos,1)))
        (col / 'points3D.txt').write_text('# synthetic orchestration fixture')
        (Path(folder) / 'malla.ply.tmp.ply').write_bytes(b'ply\nORIGINAL_GEOMETRY')
    monkeypatch.setattr(rs, 'realityscan', reconstruct)
    monkeypatch.setattr(rs, 'girar', lambda src, dst, *a: Path(dst).write_bytes(Path(src).read_bytes()))
    invoked = []
    def run(*cmd, cwd=None):
        invoked.append(cmd)
        if '-o' in cmd:
            (Path(cwd) / cmd[cmd.index('-o')+1]).write_bytes(b'textured-master')
        if '--' in cmd:
            Path(cmd[cmd.index('--')+3]).write_bytes(b'aligned-master')
    monkeypatch.setattr(pipeline, 'run', run)
    rs.main()
    assert '-calculateHighModel' in commands and '-calculateNormalModel' not in commands
    assert '-simplify' not in commands and '-removeSelectedTriangles' not in commands
    assert (job / 'maestro_texturizado.glb').read_bytes() == b'textured-master'
    assert (job / 'malla.ply').read_bytes() == (job / 'colmap' / 'malla.ply').read_bytes()
    assert not any('cerrar.py' in str(c) for cmd in invoked for c in cmd)
    texture = next(cmd for cmd in invoked if '--export-type' in cmd)
    assert texture[texture.index('--close-holes')+1] == 0
    assert texture[texture.index('--global-seam-leveling')+1] == 0


def test_frontend_references_existing_controls():
    import re
    html = (ROOT / 'capturar.html').read_text(encoding='utf-8')
    js = (ROOT / 'captura' / 'capturador.js').read_text(encoding='utf-8')
    ids = set(re.findall(r'id="([^"]+)"', html))
    references = set(re.findall(r"\$\('([^']+)'\)", js))
    assert references <= ids
