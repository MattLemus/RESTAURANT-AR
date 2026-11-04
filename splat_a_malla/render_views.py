# Dibuja el splat desde anillos de vistas alrededor (sobre todo por arriba; dos anillos por debajo para el fondo, que si no
# quedaba con manchones de otros colores) y guarda, por vista, el color,
# la opacidad, la profundidad mediana y la camara: de esto salen la forma (TSDF) y la textura (horneado).
import sys, os, time, numpy as np, torch
from splat_render import load_ply, look_at, render

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
g = load_ply(src, 'cuda')
W = H = 2048
f = W / 2 / np.tan(np.radians(22.5))
target = np.array([0, 0.04, 0.0])
rings = [(-60, 4), (-25, 8), (12, 16), (25, 16), (40, 12), (55, 10), (70, 6), (85, 4)]
i = 0; t0 = time.time()
for el, n in rings:
    for k in range(n):
        az = 2 * np.pi * (k + 0.5 * (el // 15 % 2)) / n
        e, a = np.radians(el), az
        eye = target + 0.55 * np.array([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)])
        R, t = look_at(eye, target)
        c, al, d = render(g, R, t, f, W, H)
        col = (c / al.clamp(min=1e-6)[..., None]).clamp(0, 1)  # sin premultiplicar
        np.savez_compressed(f'{out}/v{i:03d}.npz', rgb=(col.cpu().numpy() * 255 + 0.5).astype(np.uint8),
                            a=(al.cpu().numpy() * 255 + 0.5).astype(np.uint8), d=d.cpu().numpy().astype(np.float32),
                            R=R, t=t, f=f, W=W, H=H)
        i += 1
print('vistas', i, 'segundos', round(time.time() - t0))
