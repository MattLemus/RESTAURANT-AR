# Renderizador de splats (3D Gaussian Splatting, grado 0) en torch, sin kernels propios: proyecta cada gaussiana (EWA), arma los
# fragmentos de su huella por bloques de la imagen, los ordena por pixel y profundidad y los compone de adelante hacia atras.
# Devuelve color (premultiplicado), opacidad acumulada y profundidad mediana (donde la transmitancia cruza 0.5) por pixel.
import numpy as np, torch

C0 = 0.28209479177387814


def load_ply(path, dev):
    raw = open(path, 'rb').read()
    end = raw.index(b'end_header\n') + 11
    head = raw[:end].decode().splitlines()
    n = next(int(l.split()[2]) for l in head if l.startswith('element vertex'))
    props = [l.split()[2] for l in head if l.startswith('property')]
    v = np.frombuffer(raw, dtype=[(p, '<f4') for p in props], count=n, offset=end)
    f = lambda *k: torch.tensor(np.stack([v[x] for x in k], 1), device=dev)
    q = f('rot_0', 'rot_1', 'rot_2', 'rot_3'); q = q / q.norm(dim=1, keepdim=True)  # w, x, y, z
    return dict(xyz=f('x', 'y', 'z'), rgb=(0.5 + C0 * f('f_dc_0', 'f_dc_1', 'f_dc_2')).clamp(0, 1),
                op=torch.sigmoid(f('opacity'))[:, 0], scale=torch.exp(f('scale_0', 'scale_1', 'scale_2')), q=q)


def quat_mat(q):
    w, x, y, z = q.unbind(1)
    return torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
                        2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                        2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], 1).view(-1, 3, 3)


def look_at(eye, target, up=(0, 1, 0)):
    # mundo -> camara con la convencion de OpenCV (x derecha, y abajo, z hacia adelante)
    eye, target, up = map(lambda a: np.asarray(a, float), (eye, target, up))
    z = target - eye; z /= np.linalg.norm(z)
    x = np.cross(z, up); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z]); t = -R @ eye
    return R, t


@torch.no_grad()
def render(g, R, t, f, W, H, tile=128, near=0.05):
    dev = g['xyz'].device
    R = torch.tensor(R, dtype=torch.float32, device=dev); t = torch.tensor(t, dtype=torch.float32, device=dev)
    pc = g['xyz'] @ R.T + t
    z = pc[:, 2]
    ok = z > near
    x, y = pc[:, 0] / z, pc[:, 1] / z
    u, v = f * x + W / 2, f * y + H / 2
    M = quat_mat(g['q']) * g['scale'][:, None, :]
    S = M @ M.transpose(1, 2)                       # covarianza 3D
    Sc = R @ S @ R.T                                # en camara
    J = torch.zeros(len(z), 2, 3, device=dev)
    J[:, 0, 0] = f / z; J[:, 0, 2] = -f * x / z
    J[:, 1, 1] = f / z; J[:, 1, 2] = -f * y / z
    S2 = J @ Sc @ J.transpose(1, 2)
    S2[:, 0, 0] += 0.3; S2[:, 1, 1] += 0.3          # filtro de 3DGS contra el aliasing
    a, b, c = S2[:, 0, 0], S2[:, 0, 1], S2[:, 1, 1]
    det = a * c - b * b
    ca, cb, cc = c / det, -b / det, a / det         # conica (inversa)
    lam = 0.5 * (a + c) + torch.sqrt(torch.clamp(0.25 * (a - c) ** 2 + b * b, min=0))
    r = torch.ceil(3 * torch.sqrt(lam)).clamp(max=256)
    ok &= (det > 0) & (u + r >= 0) & (u - r < W) & (v + r >= 0) & (v - r < H) & (g['op'] > 1 / 255)
    idx = torch.nonzero(ok)[:, 0]
    u, v, r, z, ca, cb, cc = u[idx], v[idx], r[idx], z[idx], ca[idx], cb[idx], cc[idx]
    op, rgb = g['op'][idx], g['rgb'][idx]
    out_c = torch.zeros(H * W, 3, device=dev); out_a = torch.zeros(H * W, device=dev)
    out_d = torch.zeros(H * W, device=dev)
    x0a, x1a = (u - r).floor().clamp(0, W - 1), (u + r).floor().clamp(0, W - 1)
    y0a, y1a = (v - r).floor().clamp(0, H - 1), (v + r).floor().clamp(0, H - 1)
    for ty in range(0, H, tile):
        for tx in range(0, W, tile):
            sel = torch.nonzero((x1a >= tx) & (x0a < tx + tile) & (y1a >= ty) & (y0a < ty + tile))[:, 0]
            if not len(sel): continue
            x0, x1 = x0a[sel].clamp(min=tx), x1a[sel].clamp(max=tx + tile - 1)
            y0, y1 = y0a[sel].clamp(min=ty), y1a[sel].clamp(max=ty + tile - 1)
            bw, bh = (x1 - x0 + 1).long(), (y1 - y0 + 1).long()
            cnt = bw * bh
            gi = torch.repeat_interleave(torch.arange(len(sel), device=dev), cnt)
            start = torch.cumsum(cnt, 0) - cnt
            k = torch.arange(len(gi), device=dev) - start[gi]
            px = x0[gi] + (k % bw[gi]); py = y0[gi] + torch.div(k, bw[gi], rounding_mode='floor')
            s = sel[gi]
            dx, dy = px + 0.5 - u[s], py + 0.5 - v[s]
            al = (op[s] * torch.exp(-0.5 * (ca[s] * dx * dx + 2 * cb[s] * dx * dy + cc[s] * dy * dy))).clamp(max=0.99)
            keep = al >= 1 / 255
            al, s, pix = al[keep], s[keep], (py[keep] * W + px[keep]).long()
            # orden: pixel, y dentro de cada pixel de adelante hacia atras
            o = torch.argsort(z[s], stable=True); pix, al, s = pix[o], al[o], s[o]
            o = torch.argsort(pix, stable=True); pix, al, s = pix[o], al[o], s[o]
            l1 = torch.log1p(-al).double()
            cs = torch.cumsum(l1, 0); excl = cs - l1
            first = torch.ones_like(pix, dtype=torch.bool); first[1:] = pix[1:] != pix[:-1]
            seg = torch.cumsum(first.long(), 0) - 1
            base = excl[first][seg]
            T = torch.exp(excl - base).float()          # transmitancia antes de este fragmento
            w = al * T
            out_c.index_add_(0, pix, w[:, None] * rgb[s])
            out_a.index_add_(0, pix, w)
            cross = (T > 0.5) & (T * (1 - al) <= 0.5)   # donde se cruza la mitad: profundidad mediana
            out_d[pix[cross]] = z[s[cross]]
    return out_c.view(H, W, 3), out_a.view(H, W), out_d.view(H, W)


if __name__ == '__main__':
    # prueba: una vista en angulo de la bandeja, guarda png
    import sys
    from PIL import Image
    dev = 'cuda'
    g = load_ply(sys.argv[1], dev)
    W = H = 1024
    R, t = look_at((0, 0.42, 0.42), (0, 0.03, 0))
    import time; t0 = time.time()
    c, a, d = render(g, R, t, f=W / 2 / np.tan(np.radians(22.5)), W=W, H=H)
    torch.cuda.synchronize(); print('ms', (time.time() - t0) * 1000, 'cobertura', (a > 0.5).float().mean().item())
    img = (c + (1 - a)[..., None] * 0.15).clamp(0, 1)
    Image.fromarray((img.cpu().numpy() * 255).astype(np.uint8)).save(sys.argv[2])
