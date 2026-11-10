# python cerrar.py entrada.ply salida.ply camaras.json
# Deja el plato SIN HUECOS antes de pintarlo (pedido del usuario, 9-nov):
#  1. quita la mesa o lo que se uso para girar el plato (una rejilla, una tabla): no es parte del plato;
#  2. visto desde arriba, en cada cuadrito toma la altura real de la comida o del borde del plato, y arma con eso un
#     solido cerrado: arriba la forma real, los costados bajan derecho hasta la mesa y abajo una base plana.
# Cerrado por construccion: no puede quedar un hueco ni salir una tapa encima de la comida. Lo que se pierde es lo que
# sobresale por debajo de otra cosa (un ala que cuelga del borde): un plato se ve desde arriba.
# Probado y descartado el 9-nov: tapar cada borde suelto (salio una tapa sobre la comida: la comida no esta unida a las
# paredes) y Poisson (estiro una lamina del tamano de toda la escena para cerrar la base).
# Despues OpenMVS pinta todo con las fotos reales; lo que ninguna foto ve (la base) queda gris claro.
# Entrada y salida: PLY binario como el de girar() en procesar_rs.py.
import json
import sys

import numpy as np
import scipy.ndimage as nd

src, dst, cj = sys.argv[1:4]
CELDAS = 600  # cuadritos en el lado largo del plato (~0.5 mm en un plato de 25 cm)

b = open(src, 'rb').read()
k = b.index(b'end_header\n') + len(b'end_header\n')
hdr = b[:k].decode('ascii', 'ignore').split('\n')
n = int([l for l in hdr if l.startswith('element vertex')][0].split()[2])
props = sum(1 for l in hdr if l.startswith('property float'))  # x y z (+ colores) en float
A = np.frombuffer(b[k:k + n * 4 * props], dtype='<f4').reshape(n, props)
V = A[:, :3].astype(np.float64)
Col = A[:, 3:6].astype(np.float64) / (255.0 if A[:, 3:6].max() > 1.5 else 1.0) if props >= 6 else None  # 0-1
F = np.frombuffer(b[k + n * 4 * props:], dtype=np.dtype([('n', 'u1'), ('i', '<i4', 3)]))['i'].astype(np.int64)

# vertical = eje del circulo de fotos, centro = el punto al que miran todas (igual que limpiar.py)
cams = json.load(open(cj))
C = np.array([c['centro'] for c in cams])
D = np.array([c['mira'] for c in cams])
up = np.linalg.svd(C - C.mean(0))[2][2]
if (D @ up).mean() > 0:  # las fotos miran hacia abajo, al plato
    up = -up
P = [np.eye(3) - np.outer(d, d) for d in D]
p = np.linalg.solve(sum(P), sum(q @ c for q, c in zip(P, C)))
x = np.cross(up, [1, 0, 0] if abs(up[0]) < 0.9 else [0, 1, 0])
x /= np.linalg.norm(x)
R = np.array([x, np.cross(up, x), up])  # filas: ejes del plato derecho (z = arriba)
Q = (V - p) @ R.T
h, rad = Q[:, 2], np.hypot(Q[:, 0], Q[:, 1])
dist = np.median(np.linalg.norm(C - p, axis=1))

# 1. la mesa o la base giratoria: la superficie plana horizontal mas baja que llega al borde del modelo (limpiar.py)
fn = np.cross(Q[F[:, 1]] - Q[F[:, 0]], Q[F[:, 2]] - Q[F[:, 0]])
vn = np.zeros_like(Q)
for j in range(3):
    np.add.at(vn, F[:, j], fn)
flat = np.abs(vn[:, 2]) > 0.9 * np.maximum(np.linalg.norm(vn, axis=1), 1e-12)
paso = 0.005 * dist
cuenta = np.bincount(np.floor((h[flat] - h[flat].min()) / paso).astype(int))
corte = None
for bn in np.where(cuenta >= 0.01 * flat.sum())[0]:
    h0 = h[flat].min() + (bn + 0.5) * paso
    mesa = flat & (np.abs(h - h0) < 1.5 * paso)
    h0 = np.median(h[mesa])
    r_mesa, r_todo = np.percentile(rad[mesa], 90), np.percentile(rad, 90)
    print(f'BASE plana a {h0 / dist:.3f}: radio {r_mesa / dist:.3f} vs modelo {r_todo / dist:.3f}', flush=True)
    # 0.8 y no 0.9 como limpiar.py: los flecos de la rejilla agrandan el radio del modelo (9-nov: 0.86). Si en cambio
    # toma el fondo plano del plato, solo le quita unos mm abajo y la base plana lo cierra igual
    if r_mesa > 0.8 * r_todo:
        corte = h0 + max(3 * np.std(h[mesa]), paso)
    break
if corte is not None:
    quedan = (h[F] >= corte).all(1)
    print(f'QUITO LA BASE: {(~quedan).sum()} caras debajo de {corte / dist:.3f}', flush=True)
    F = F[quedan]
else:
    print('BASE no encontrada: no quito nada', flush=True)
    corte = h.min()
usa = np.unique(F)
Q, nz = Q[usa], np.abs(vn[usa, 2]) / np.maximum(np.linalg.norm(vn[usa], axis=1), 1e-12)
Col = Col[usa] if Col is not None else None

# 2. alturas vistas desde arriba: la mas alta en cada cuadrito (la comida, el borde del plato)
lado = max(np.ptp(Q[:, 0]), np.ptp(Q[:, 1])) / CELDAS
x0, y0 = Q[:, 0].min() - 3 * lado, Q[:, 1].min() - 3 * lado
ix = ((Q[:, 0] - x0) / lado).astype(int)
iy = ((Q[:, 1] - y0) / lado).astype(int)
alto = np.full((iy.max() + 4, ix.max() + 4), -np.inf)
np.maximum.at(alto, (iy, ix), Q[:, 2])
dato = np.isfinite(alto)
# la huella del plato: los cuadritos con altura de verdad (los restos de la rejilla quedan pegados a la base y hacian un
# reborde plano alrededor, 9-nov), juntos, sin agujeros, y la pieza mas grande
alto_ok = dato & (alto > corte + 0.15 * (np.percentile(alto[dato], 95) - corte))
huella = nd.binary_fill_holes(nd.binary_closing(alto_ok, structure=np.ones((5, 5)), iterations=2))
lab, nlab = nd.label(huella)
if nlab > 1:
    huella = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
huella = nd.binary_opening(huella, structure=np.ones((3, 3)))  # sin puntas de un cuadrito (aristas raras en el costado)
# cuadritos sin datos dentro de la huella: la altura del vecino con datos mas cercano
cerca = nd.distance_transform_edt(~dato, return_distances=False, return_indices=True)
alto = nd.median_filter(alto[cerca[0], cerca[1]], size=5)  # sin agujas sueltas
alto = np.maximum(alto, corte + lado)
print(f'ARRIBA {huella.sum()} cuadritos de {lado / dist * 1000:.2f} milesimas de la distancia de las fotos '
      f'({(~dato & huella).sum()} sin datos, rellenados)', flush=True)

# solido cerrado: arriba la forma, abajo la base plana (los mismos triangulos al reves) y los costados entre ambos
ids = np.full(huella.shape, -1)
celdas = np.argwhere(huella)
ids[huella] = np.arange(len(celdas))
cx, cy = x0 + (celdas[:, 1] + .5) * lado, y0 + (celdas[:, 0] + .5) * lado
m = len(celdas)
arriba = np.column_stack([cx, cy, alto[huella]])
# el plato se angosta hacia abajo (un envase, un bowl): con paredes derechas desde el borde de arriba, las paredes quedan
# por fuera del plato y se pintan con lo que hay detras en las fotos (la rejilla, 9-nov). Se mide que tan ancho es cerca
# de la base con las paredes que si salieron (empinadas, bajas y dentro de la huella) y la base se achica a esa medida
eje = np.linalg.svd(np.column_stack([cx, cy]) - [cx.mean(), cy.mean()], full_matrices=False)[2]  # largo y ancho
centro = np.array([cx.mean(), cy.mean()])
dentro = huella[np.clip(iy, 0, huella.shape[0] - 1), np.clip(ix, 0, huella.shape[1] - 1)]
alto_tot = np.percentile(alto[huella], 95) - corte
ancho = [np.ptp((np.column_stack([cx, cy]) - centro) @ e) for e in eje]
al_borde = nd.distance_transform_edt(huella) * lado < 0.2 * min(ancho)  # pared de afuera, no los lados de la comida
al_borde = al_borde[np.clip(iy, 0, huella.shape[0] - 1), np.clip(ix, 0, huella.shape[1] - 1)]
# donde termina de verdad la pared: la base de la rejilla quedaba mas abajo y las paredes salian altas y pintadas con la
# rejilla (9-nov). Es la parte mas baja de la pared que tiene el color del borde del plato (lo de abajo es de otro color)
base = corte
if Col is not None:
    borde_alto = dentro & al_borde & (Q[:, 2] > corte + 0.7 * alto_tot)
    pared = dentro & al_borde & (nz < 0.6)
    if borde_alto.sum() > 50:
        pw = pared & (np.linalg.norm(Col - np.median(Col[borde_alto], 0), axis=1) < 0.2)
        if pw.sum() > 100:
            base = max(corte, np.percentile(Q[pw, 2], 3))
print(f'BASE del plato a {(base - corte) / alto_tot:.0%} de la altura sobre el corte', flush=True)
arriba[:, 2] = np.maximum(arriba[:, 2], base + lado)
pie = dentro & al_borde & (nz < 0.6) & (Q[:, 2] >= base) & (Q[:, 2] < base + 0.25 * (alto_tot - (base - corte)))
escala = np.ones(2)
if pie.sum() > 200:
    for j in range(2):
        t_arr = (np.column_stack([cx, cy]) - centro) @ eje[j]
        t_pie = (Q[pie, :2] - centro) @ eje[j]
        escala[j] = np.clip(np.ptp(np.percentile(t_pie, [2, 98])) / np.ptp(t_arr), 0.6, 1.0)
print(f'PAREDES: la base mide {escala[0]:.2f} x {escala[1]:.2f} del borde de arriba ({pie.sum()} puntos de pared)',
      flush=True)
xy_abajo = centro + ((np.column_stack([cx, cy]) - centro) @ eje.T * escala) @ eje
abajo = np.column_stack([xy_abajo, np.full(m, base)])
a, bb, c, d = ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]
ok = (a >= 0) & (bb >= 0) & (c >= 0) & (d >= 0)
a, bb, c, d = a[ok], bb[ok], c[ok], d[ok]
Ft = np.concatenate([np.column_stack([a, bb, c]), np.column_stack([a, c, d])])  # normales hacia arriba
E = np.concatenate([Ft[:, [0, 1]], Ft[:, [1, 2]], Ft[:, [2, 0]]])
borde = E[~np.isin(E[:, 0] * m + E[:, 1], E[:, 1] * m + E[:, 0])]  # aristas sin pareja: el contorno
u, v = borde[:, 0], borde[:, 1]
Fc = np.concatenate([np.column_stack([v, u, u + m]), np.column_stack([v, u + m, v + m])])  # costados, hacia afuera
F2 = np.concatenate([Ft, Ft[:, ::-1] + m, Fc])
V2 = np.vstack([arriba, abajo])
usa = np.unique(F2)
nuevo = np.full(len(V2), -1)
nuevo[usa] = np.arange(len(usa))
V2, F2 = V2[usa] @ R + p, nuevo[F2]  # de vuelta a las coordenadas de las fotos

E = np.sort(np.concatenate([F2[:, [0, 1]], F2[:, [1, 2]], F2[:, [2, 0]]]), 1)
_, cnt = np.unique(E, axis=0, return_counts=True)
print(f'SOLIDO {len(V2)} vertices, {len(F2)} caras | BORDES ABIERTOS {int((cnt == 1).sum())} | '
      f'aristas con mas de 2 caras {int((cnt > 2).sum())}', flush=True)
assert (cnt == 1).sum() == 0, 'quedaron huecos'

cab = ('ply\nformat binary_little_endian 1.0\n'
       f'element vertex {len(V2)}\nproperty float x\nproperty float y\nproperty float z\n'
       f'element face {len(F2)}\nproperty list uchar int vertex_indices\nend_header\n').encode('ascii')
caras = np.empty(len(F2), dtype=np.dtype([('n', 'u1'), ('i', '<i4', 3)]))
caras['n'], caras['i'] = 3, F2
open(dst, 'wb').write(cab + V2.astype('<f4').tobytes() + caras.tobytes())
print('CERRADA', dst, flush=True)
