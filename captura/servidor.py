"""Servidor local de captura. USB: adb reverse tcp:8765 tcp:8765.
HTTPS LAN: --host 0.0.0.0 --cert certificado.pem --key clave.pem.
No publica ni abre túneles automáticamente.
"""
import argparse
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import threading
import time
import shutil
from urllib.parse import urlsplit
from datetime import datetime, timezone

from PIL import Image, UnidentifiedImageError

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ.parent
FOTOS = RAIZ / 'fotos'
SESION = r'plato_\d{8}_\d{6}(?:_[a-f0-9]{1,8})?'
PUBLICO = False
LOCK = threading.Lock()
ASSETS = {'/capturar.html', '/captura/calidad.js', '/captura/capturador.js', '/captura/capturador.css'}
JOBS = {}
JOB_LOCK = threading.Lock()


def accepted_sequences(report):
    sequences = []
    for record in report['records']:
        if not isinstance(record, dict):
            raise ValueError('Informe inválido')
        if record.get('valid') is not True or record.get('superseded'):
            continue
        sequence = record.get('sequence')
        if type(sequence) is not int or not 1 <= sequence <= 99999:
            raise ValueError('Número de foto inválido')
        sequences.append(sequence)
    if len(sequences) != len(set(sequences)):
        raise ValueError('Hay fotos repetidas en el informe')
    return sequences


def start_job(session):
    source = FOTOS / session
    with JOB_LOCK:
        existing = JOBS.get(session)
        with LOCK:
            manifest = (source / 'manifest.json').read_bytes()
        report = json.loads(manifest)
        if report.get('session') != session:
            raise ValueError('El informe no corresponde a esta sesión')
        sequences = accepted_sequences(report)
        if existing and existing['state'] in ('queued', 'running'):
            if existing['sequences'] == sequences:
                return existing.copy()
            raise ValueError('La PC ya está procesando una selección anterior. Espera a que termine para enviar las nuevas fotos')
        if len(sequences) < 8:
            raise ValueError('Toma al menos 8 fotos desde ángulos distintos para generar el 3D')
        for sequence in sequences:
            stem = f'{session}_{sequence:03d}'
            if not any((source / (stem + suffix)).is_file() for suffix in ('.jpg', '.png')):
                raise ValueError(f'Falta el original de la foto {sequence}')
        if existing and existing['state'] == 'done' and existing['sequences'] == sequences:
            return existing.copy()
        if any(item['state'] in ('queued', 'running') for item in JOBS.values()):
            raise ValueError('La PC ya está reconstruyendo otro plato. Intenta cuando termine')
        parent = RAIZ / 'trabajos' / session
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        parent.mkdir(parents=True, exist_ok=True)
        snapshot = parent / f'{stamp}_fotos.json'
        snapshot.write_bytes(manifest)
        work = parent / stamp
        job = {'state': 'queued', 'message': 'Originales recibidos. Preparando el modelo en la PC.',
               'sequences': sequences}
        JOBS[session] = job
        threading.Thread(target=run_job, args=(source, work, snapshot, job), daemon=True).start()
        return job.copy()


def run_job(source, work, snapshot, job):
    log = work.with_suffix('.log')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    command = [sys.executable, '-u', str(RAIZ / 'prueba_3d_local.py'), str(source), str(work),
               '--manifest', str(snapshot), '--alta-calidad']
    try:
        from prueba_3d_local import require_offline

        while True:
            try:
                require_offline()
                break
            except SystemExit as error:
                if not str(error).startswith('Windows todavía tiene una ruta'):
                    raise RuntimeError(str(error)) from error
                message = 'Originales en la PC. Apaga el Wi-Fi y desconecta Ethernet de la PC para empezar. El celular ya se puede desconectar.'
                with JOB_LOCK:
                    if job['message'] != message:
                        print(message, flush=True)
                    job['message'] = message
                time.sleep(3)
        with JOB_LOCK:
            job.update(state='running', message='Alineando fotos a resolución completa. Puedes desconectar el celular.')
        last_message = ''
        with log.open('w', encoding='utf-8') as output, subprocess.Popen(
            command, cwd=WEB, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        ) as process:
            for line in process.stdout:
                output.write(line)
                output.flush()
                if line.strip():
                    last_message = line.strip()
                if line.startswith(('Preparando ', 'Alineadas ', 'Corrigiendo ', 'Reconstruyendo ', 'Proyectando ')):
                    with JOB_LOCK:
                        job['message'] = line.strip()
                    print(line.strip(), flush=True)
            if process.wait() != 0:
                raise RuntimeError(last_message or 'El proceso se detuvo.')
        result = work / 'dense' / 'prueba_3d.glb'
        if not result.is_file():
            raise RuntimeError('El proceso terminó sin crear el archivo 3D.')
        print(f'Modelo 3D listo: {result}', flush=True)
        with JOB_LOCK:
            job.update(state='done', message=f'Modelo 3D listo en la PC: {result.relative_to(WEB)}', path=str(result))
    except (OSError, RuntimeError) as error:
        print(f'No se generó el modelo: {error}\nRegistro: {log}', flush=True)
        with JOB_LOCK:
            job.update(state='error', message=str(error))


def decode_photo(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ('JPEG', 'PNG'):
            raise ValueError('Importa JPEG o PNG original')
        if image.width * image.height > 100_000_000:
            raise ValueError('Imagen demasiado grande')
        info = {'width': image.width, 'height': image.height,
                'extension': '.png' if image.format == 'PNG' else '.jpg',
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        image.verify()
    return info


def save_photo(folder, session, sequence, data):
    info = decode_photo(data)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{session}_{sequence:03d}{info["extension"]}'
    with LOCK:
        other = path.with_suffix('.jpg' if info['extension'] == '.png' else '.png')
        if other.exists():
            raise FileExistsError('Este número de foto ya pertenece a otro original')
        if path.exists():
            if path.read_bytes() != data:
                raise FileExistsError('Este original ya existe con otros bytes')
        else:
            temp = path.with_suffix(path.suffix + '.part')
            temp.write_bytes(data)
            os.replace(temp, path)
        sidecar = path.with_suffix(path.suffix + '.json')
        if not sidecar.exists():
            sidecar.write_text(json.dumps(info, indent=2), encoding='utf-8')
    return info


def revisar(folder):
    photos = []
    folder = Path(folder)
    for path in sorted(folder.glob('*')) if folder.is_dir() else []:
        if path.suffix.lower() not in ('.jpg', '.png', '.jpeg'):
            continue
        try:
            info = decode_photo(path.read_bytes())
            photos.append({'file': path.name, **info})
        except (ValueError, OSError):
            photos.append({'file': path.name, 'error': 'No decodificable'})
    return {'fotos': photos, 'aviso': 'Las métricas son heurísticas. Revisión visual obligatoria.'}


class Pedido(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        if self.path == '/subir/ping':
            return self._ok(b'ok')
        if self.path == '/subir/estado':
            return self._json({'version': 3})
        if self.path == '/captura-offline.js':
            return self._ok((RAIZ / 'offline.js').read_bytes(), 'text/javascript')
        job = re.fullmatch(rf'/procesar\?s=({SESION})', self.path)
        if job and not PUBLICO:
            with JOB_LOCK:
                status = JOBS.get(job[1], {'state': 'error', 'message': 'Aún no hay un modelo en proceso.'}).copy()
            return self._json(status)
        model = re.fullmatch(rf'/modelo\?s=({SESION})', self.path)
        if model and not PUBLICO:
            with JOB_LOCK:
                job = JOBS.get(model[1], {})
                result = job.get('path') if job.get('state') == 'done' else None
            if not result or not Path(result).is_file():
                return self.send_error(404)
            with Path(result).open('rb') as file:
                self.send_response(200)
                self.send_header('Content-Type', 'model/gltf-binary')
                self.send_header('Content-Disposition', 'attachment; filename="plato_3d.glb"')
                self.send_header('Content-Length', str(os.fstat(file.fileno()).st_size))
                self.end_headers()
                if self.command != 'HEAD':
                    shutil.copyfileobj(file, self.wfile)
            return
        match = re.fullmatch(rf'/subir/revisar\?s=({SESION})', self.path)
        if match:
            return self._ok(json.dumps(revisar(FOTOS / match[1])).encode(), 'application/json')
        # No exponer modelos, fotos de otros escaneos ni archivos internos.
        if urlsplit(self.path).path not in ASSETS:
            return self.send_error(404)
        return super().do_HEAD() if self.command == 'HEAD' else super().do_GET()

    do_HEAD = do_GET

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send_error(403, 'Origen no permitido')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_error(400)
        if not 0 < length <= 60_000_000:
            return self.send_error(413)
        photo = re.fullmatch(rf'/subir\?s=({SESION})&n=(\d{{1,5}})', self.path)
        manifest = re.fullmatch(rf'/subir/manifest\?s=({SESION})', self.path)
        job = re.fullmatch(rf'/procesar\?s=({SESION})', self.path)
        if not photo and not manifest and (not job or PUBLICO):
            return self.send_error(404)
        if (manifest and length > 2_000_000) or (job and length > 1024):
            return self.send_error(413)
        data = self.rfile.read(length)
        if len(data) != length:
            return self.send_error(400)
        try:
            if job:
                return self._json(start_job(job[1]))
            if photo:
                info = save_photo(FOTOS / photo[1], photo[1], int(photo[2]), data)
                return self._ok(json.dumps(info).encode(), 'application/json')
            body = json.loads(data)
            if not isinstance(body, dict) or body.get('session') != manifest[1] or not isinstance(body.get('records'), list):
                raise ValueError('Informe inválido')
            accepted_sequences(body)
            folder = FOTOS / manifest[1]
            folder.mkdir(parents=True, exist_ok=True)
            with LOCK:
                tmp = folder / 'manifest.tmp'
                tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
                os.replace(tmp, folder / 'manifest.json')
            return self._json({'ok': True})
        except FileExistsError as error:
            return self.send_error(409, str(error))
        except (ValueError, OSError, UnidentifiedImageError) as error:
            return self._json({'error': str(error)}, 400)

    def _json(self, value, status=200):
        return self._ok(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json', status)

    def _ok(self, body=b'ok', content_type='text/plain', status=200):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', content_type)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=['publico'])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int)
    parser.add_argument('--cert')
    parser.add_argument('--key')
    args = parser.parse_args()
    PUBLICO = args.mode == 'publico' or args.host not in ('127.0.0.1', 'localhost', '::1')
    if bool(args.cert) != bool(args.key):
        parser.error('--cert y --key deben indicarse juntos')
    port = args.port or (8766 if args.mode == 'publico' else 8765)
    server = http.server.ThreadingHTTPServer((args.host, port), Pedido)
    if args.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    scheme = 'https' if args.cert else 'http'
    print(f'Capturador: {scheme}://localhost:{port}/capturar.html', flush=True)
    print(f'Originales: {FOTOS}', flush=True)
    server.serve_forever()
