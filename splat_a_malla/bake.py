# Hornea el color del splat en la textura de la malla: cada texel (punto 3D de la superficie) toma el color de las vistas que lo
# ven (su profundidad coincide con la de la vista) pesadas por lo de frente que lo miran; lo que ninguna ve se rellena desde
# los vecinos. Salida: textura PNG (fila 0 = v = 1, convencion OpenGL) para exportar con trimesh.
import sys, glob, numpy as np, torch, torch.nn.functional as Fn
from PIL import Image

mesh, vdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
dev = 'cuda'
m = np.load(mesh); T = int(m['res'])
P, Nv, F, UV = (torch.tensor(m[k], device=dev) for k in ('pos', 'nrm', 'faces', 'uv'))

# 1) rasterizar los triangulos en el espacio UV: por texel, su punto 3D y su normal
pos = torch.zeros(T * T, 3, device=dev); nrm = torch.zeros(T * T, 3, device=dev); cov = torch.zeros(T * T, dtype=torch.bool, device=dev)
tu = UV[F] * torch.tensor([T, T], device=dev); tu[..., 1] = T - tu[..., 1]   # px del texel; fila 0 arriba = v 1
for c in range(0, len(F), 20000):
    q = tu[c:c + 20000]; f = F[c:c + 20000]
    lo = q.min(1).values.floor().clamp(0, T - 1).long(); hi = q.max(1).values.floor().clamp(0, T - 1).long()
    bw, bh = hi[:, 0] - lo[:, 0] + 1, hi[:, 1] - lo[:, 1] + 1
    cnt = bw * bh
    ti = torch.repeat_interleave(torch.arange(len(q), device=dev), cnt)
    k = torch.arange(len(ti), device=dev) - (torch.cumsum(cnt, 0) - cnt)[ti]
    x = lo[ti, 0] + k % bw[ti]; y = lo[ti, 1] + torch.div(k, bw[ti], rounding_mode='floor')
    px, py = x + 0.5, y + 0.5
    a, b, cc = q[ti, 0], q[ti, 1], q[ti, 2]
    d = (b[:, 0] - a[:, 0]) * (cc[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (cc[:, 0] - a[:, 0])
    w1 = ((px - a[:, 0]) * (cc[:, 1] - a[:, 1]) - (py - a[:, 1]) * (cc[:, 0] - a[:, 0])) / d
    w2 = ((b[:, 0] - a[:, 0]) * (py - a[:, 1]) - (b[:, 1] - a[:, 1]) * (px - a[:, 0])) / d
    w0 = 1 - w1 - w2
    e = -0.02  # un poco hacia afuera del borde: los texels del contorno tambien llevan color
    ok = (w0 >= e) & (w1 >= e) & (w2 >= e) & (d.abs() > 1e-12)
    ti, x, y, w = ti[ok], x[ok], y[ok], torch.stack([w0[ok], w1[ok], w2[ok]], 1)
    fi = f[ti]
    t = y * T + x
    pos[t] = (P[fi] * w[..., None]).sum(1); nrm[t] = (Nv[fi] * w[..., None]).sum(1); cov[t] = True
nrm = Fn.normalize(nrm, dim=1)
idx = torch.nonzero(cov)[:, 0]; Pt, Nt = pos[idx], nrm[idx]
print('texels', len(idx))

# 2) color desde las vistas
acc = torch.zeros(len(idx), 3, device=dev); wsum = torch.zeros(len(idx), device=dev)
for p in sorted(glob.glob(f'{vdir}/v*.npz')):
    v = np.load(p)
    W, H, f = int(v['W']), int(v['H']), float(v['f'])
    R, t = torch.tensor(v['R'], dtype=torch.float32, device=dev), torch.tensor(v['t'], dtype=torch.float32, device=dev)
    img = torch.tensor(v['rgb'], device=dev).permute(2, 0, 1)[None].float() / 255
    al = torch.tensor(v['a'], device=dev)[None, None].float() / 255
    dep = torch.tensor(v['d'], device=dev)[None, None]
    pc = Pt @ R.T + t; z = pc[:, 2]
    ix, iy = f * pc[:, 0] / z + W / 2, f * pc[:, 1] / z + H / 2
    g = torch.stack([ix / W * 2 - 1, iy / H * 2 - 1], 1)[None, None]
    col = Fn.grid_sample(img, g, align_corners=False)[0, :, 0].T
    a = Fn.grid_sample(al, g, align_corners=False)[0, 0, 0]
    dz = Fn.grid_sample(dep, g, mode='nearest', align_corners=False)[0, 0, 0]
    eye = -R.T @ t
    cos = (Nt * Fn.normalize(eye - Pt, dim=1)).sum(1)
    vis = (z > 0) & (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H) & (a > 0.7) & ((z - dz).abs() < 0.003) & (cos > 0.15)
    w = torch.where(vis, cos ** 4, torch.zeros_like(cos))
    acc += w[:, None] * col; wsum += w
seen = wsum > 0
print('vistos', round(seen.float().mean().item(), 4))
tex = torch.zeros(T * T, 3, device=dev); has = torch.zeros(T * T, dtype=torch.bool, device=dev)
tex[idx[seen]] = acc[seen] / wsum[seen, None]; has[idx[seen]] = True

# 3) relleno de lo que ninguna vista ve (el fondo tapado, lo de abajo de camarones y conchas) y del margen de cada pieza (evita
# costuras al reducir la textura): cada hueco toma el color de lo visto alrededor, a la escala que haga falta (push-pull)
def rellenar(img, msk):
    if img.shape[-1] <= 1 or msk.min() > 0: return img
    low = rellenar(Fn.avg_pool2d(img * msk, 2) / Fn.avg_pool2d(msk, 2).clamp(min=1e-8), (Fn.avg_pool2d(msk, 2) > 0).float())
    return torch.where(msk > 0, img, Fn.interpolate(low, scale_factor=2, mode='bilinear', align_corners=False))


img = rellenar(tex.view(T, T, 3).permute(2, 0, 1)[None], has.view(1, 1, T, T).float())
Image.fromarray((img[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255 + 0.5).astype(np.uint8)).save(out)
print('textura', out)
