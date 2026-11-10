# python captura/servidor.py  ->  sirve web/ en http://localhost:8765 y guarda en captura/fotos/<sesion>/ las fotos
# que manda web/capturar.html. En el celular: adb reverse tcp:8765 tcp:8765 y abrir http://localhost:8765/capturar.html
# python captura/servidor.py publico  ->  puerto 8766 y SOLO capturar.html + subir: es el que se abre a internet
# (cloudflared tunnel --url http://localhost:8766) para que el dueno del restaurante escanee desde su celular.
import http.server
import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(RAIZ, '..')
FOTOS = os.path.join(RAIZ, 'fotos')
PUBLICO = 'publico' in sys.argv[1:]
SESION = r'plato_\d{8}_\d{6}'  # nombre fijo: nada de rutas raras


def revisar(carpeta):
    """Fotos recibidas y cuales salieron movidas, con la misma regla que procesar.preparar (nitidez < 0.4 de la mediana).
    shortcut: si TODAS salen movidas la mediana tambien baja y no avisa; hace falta un umbral fijo medido en varios
    celulares cuando haya escaneos de duenos para calibrarlo."""
    import cv2
    import numpy as np
    nit = {}
    for f in sorted(os.listdir(carpeta)) if os.path.isdir(carpeta) else []:
        im = cv2.imread(os.path.join(carpeta, f), cv2.IMREAD_REDUCED_GRAYSCALE_2)
        if im is not None:
            nit[int(f[-7:-4])] = cv2.Laplacian(im, cv2.CV_64F).var()
    med = np.median(list(nit.values())) if nit else 0
    return {'fotos': sorted(nit), 'movidas': sorted(n for n, v in nit.items() if v < 0.4 * med)}


class Pedido(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def do_GET(self):
        if self.path.startswith('/subir/ping'):
            return self._ok()
        m = re.fullmatch(rf'/subir/revisar\?s=({SESION})', self.path)
        if m:
            return self._ok(json.dumps(revisar(os.path.join(FOTOS, m[1]))).encode())
        # abierto a internet no se sirve la carpeta entera (.git, fotos y trabajos de otros platos)
        if PUBLICO and self.path.split('?')[0] != '/capturar.html':
            return self.send_error(404)
        super().do_GET()

    do_HEAD = do_GET

    def do_POST(self):
        m = re.fullmatch(rf'/subir\?s=({SESION})&n=(\d{{1,3}})', self.path)
        largo = int(self.headers.get('Content-Length') or 0)
        if not m or not 0 < largo <= 40_000_000:
            return self.send_error(400)
        datos = self.rfile.read(largo)
        carpeta = os.path.join(FOTOS, m[1])
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, f'{m[1]}_{int(m[2]):03d}.jpg'), 'wb') as f:
            f.write(datos)
        print('foto', m[1], m[2], len(datos) // 1024, 'KB', flush=True)
        self._ok()

    def _ok(self, cuerpo=b'ok'):
        self.send_response(200)
        self.send_header('Content-Length', str(len(cuerpo)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(cuerpo)


if __name__ == '__main__':
    puerto = 8766 if PUBLICO else 8765
    print('sirviendo', 'solo capturar.html' if PUBLICO else os.path.abspath(WEB), f'en http://localhost:{puerto}', flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1', puerto), Pedido).serve_forever()
