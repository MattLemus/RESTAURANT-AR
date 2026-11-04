# python -I preparar.py idol.ply splat.ply [ancho_cm]
# Primer paso de splat_a_malla.sh: el splat de Idol (Speridlabs) con Y arriba, en metros, centrado, apoyado en la mesa (base en
# y=0) y con su lado largo de ancho_cm. Solo se gira, mueve y escala cada gaussiana (posicion, rotacion y tamano): colores,
# opacidades y formas quedan iguales.
import sys, numpy as np

src, dst = sys.argv[1], sys.argv[2]
ancho = (float(sys.argv[3]) if len(sys.argv) > 3 else 40) / 100

raw = open(src, 'rb').read()
end = raw.index(b'end_header\n') + len(b'end_header\n')
head = raw[:end].decode().splitlines()
assert 'format binary_little_endian 1.0' in head, 'solo .ply binario little endian'
n = next(int(l.split()[2]) for l in head if l.startswith('element vertex'))
props = [l.split()[2] for l in head if l.startswith('property')]
assert all(l.split()[1] == 'float' for l in head if l.startswith('property')), 'solo propiedades float'
v = np.frombuffer(raw, dtype=[(p, '<f4') for p in props], count=n, offset=end).copy()

# Idol entrega Y hacia abajo (convencion de camara OpenCV): media vuelta en X -> (x, -y, -z)
# shortcut: el giro es el de Idol; un splat de otro generador que ya venga con Y arriba quedaria de cabeza (agregar una opcion entonces)
v['y'], v['z'] = -v['y'], -v['z']
w, x, y, z = v['rot_0'].copy(), v['rot_1'].copy(), v['rot_2'].copy(), v['rot_3'].copy()
v['rot_0'], v['rot_1'], v['rot_2'], v['rot_3'] = -x, w, -z, y  # (0,1,0,0) * q: la misma media vuelta para la orientacion

# medidas sin las gaussianas sueltas: solo las bien opacas, del 0.5 al 99.5 por ciento de cada eje
ok = 1 / (1 + np.exp(-v['opacity'])) > 0.5
P = np.stack([v['x'][ok], v['y'][ok], v['z'][ok]], 1)
lo, hi = np.percentile(P, 0.5, 0), np.percentile(P, 99.5, 0)
k = ancho / max(hi[0] - lo[0], hi[2] - lo[2])
v['x'] = (v['x'] - (lo[0] + hi[0]) / 2) * k
v['y'] = (v['y'] - lo[1]) * k
v['z'] = (v['z'] - (lo[2] + hi[2]) / 2) * k
for s in ('scale_0', 'scale_1', 'scale_2'): v[s] += np.log(k)  # el tamano se guarda como logaritmo

# las normales de un .ply de splats van siempre en cero (ningun visor las usa): fuera, el archivo baja ~3 MB
keep = [p for p in props if not (p in ('nx', 'ny', 'nz') and not v[p].any())]
out = np.empty(n, dtype=[(p, '<f4') for p in keep])
for p in keep: out[p] = v[p]
hdr = ['ply', 'format binary_little_endian 1.0', f'element vertex {n}'] + [f'property float {p}' for p in keep] + ['end_header']
open(dst, 'wb').write(('\n'.join(hdr) + '\n').encode() + out.tobytes())

# autocomprobacion: la orientacion nueva de cada gaussiana es la vieja girada media vuelta en X
def mat(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
for i in range(0, n, max(1, n // 50)):
    a = np.array([w[i], x[i], y[i], z[i]]); b = np.array([v[f'rot_{j}'][i] for j in range(4)])
    assert np.allclose(mat(b), np.diag([1, -1, -1]) @ mat(a), atol=1e-5)
print(f'{n} gaussianas, {k * (hi[0] - lo[0]) * 100:.1f} x {k * (hi[2] - lo[2]) * 100:.1f} cm, alto {k * (hi[1] - lo[1]) * 100:.1f} cm, '
      f'{len(keep)} propiedades -> {dst} ({len(out.tobytes()) / 1e6:.1f} MB)')
