# python captura/servidor.py  ->  sirve web/ en http://localhost:8765 y guarda en captura/fotos/<sesion>/ las fotos
# que manda web/capturar.html. En el celular: adb reverse tcp:8765 tcp:8765 y abrir http://localhost:8765/capturar.html
import http.server
import os
import re

RAIZ = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(RAIZ, '..')
FOTOS = os.path.join(RAIZ, 'fotos')


class Pedido(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def do_GET(self):
        if self.path.startswith('/subir/ping'):
            return self._ok()
        super().do_GET()

    def do_POST(self):
        m = re.fullmatch(r'/subir\?s=(plato_\d{8}_\d{6})&n=(\d{1,3})', self.path)  # nombre fijo: nada de rutas raras
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

    def _ok(self):
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b'ok')


if __name__ == '__main__':
    print('sirviendo', os.path.abspath(WEB), 'en http://localhost:8765', flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1', 8765), Pedido).serve_forever()
