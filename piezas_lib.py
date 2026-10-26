# Piezas 3D a partir de una sola foto (piezas/fotos): forma simple + la foto proyectada encima, asi la textura es
# la foto misma. La usan make_pieces.py y make_fritada.py.
import math
import cv2
import numpy as np
import triangle as tr
from scipy import ndimage, optimize, spatial


def load(path, trim_shadow=True):
    """Foto con fondo blanco -> (imagen RGB, mascara de la pieza)."""
    bgr = cv2.imread(path); h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    dist = 255 - bgr.min(2).astype(int)          # que tan lejos del blanco
    sat = hsv[..., 1].astype(int)
    # GrabCut con semillas: blanco puro = fondo, color fuerte = pieza
    m = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    m[(dist < 6) & (sat < 8)] = cv2.GC_BGD
    m[(dist > 40) | (sat > 40)] = cv2.GC_PR_FGD
    core = cv2.erode(((dist > 60) | (sat > 60)).astype(np.uint8), np.ones((9, 9), np.uint8))
    m[core > 0] = cv2.GC_FGD
    cv2.grabCut(bgr, m, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    mask = np.isin(m, (cv2.GC_FGD, cv2.GC_PR_FGD))
    img = bgr[..., ::-1].copy()
    if trim_shadow:
        # quitar la sombra gris clara que queda pegada abajo de la pieza (no en el mote, que es blanco)
        hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
        d = ndimage.distance_transform_edt(mask)
        mask &= ~((hsv[..., 1] < 45) & (hsv[..., 2] > 170) & (d < 30))
    mask = ndimage.binary_opening(mask, np.ones((5, 5)))
    lab, n = ndimage.label(mask)
    mask = lab == (1 + np.argmax(ndimage.sum(mask, lab, range(1, n + 1))))
    mask = ndimage.binary_fill_holes(ndimage.binary_closing(mask, np.ones((7, 7))))
    mask = ndimage.binary_erosion(mask, np.ones((3, 3)), iterations=2)   # sin el borde mezclado con el fondo
    return img, mask


def texture(img, mask, size=1024, pad=12):
    """Recorta la pieza en un cuadrado y rellena afuera con el color del borde (sin halo blanco al alejarse)."""
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min() - pad, xs.max() + pad, ys.min() - pad, ys.max() + pad
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    x0, y0 = cx - side // 2, cy - side // 2
    H, W = mask.shape
    big = np.zeros((side, side, 3), np.uint8); m = np.zeros((side, side), bool)
    sx0, sy0 = max(0, x0), max(0, y0); sx1, sy1 = min(W, x0 + side), min(H, y0 + side)
    big[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
    m[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = mask[sy0:sy1, sx0:sx1]
    _, (iy, ix) = ndimage.distance_transform_edt(~m, return_indices=True)
    big = big[iy, ix]
    tex = cv2.resize(big, (size, size), interpolation=cv2.INTER_AREA)
    # (col, row) de la foto -> uv de Blender (v hacia arriba)
    to_uv = lambda col, row: np.stack([(col - x0) / side, 1 - (row - y0) / side], -1)
    return tex, to_uv


def normal_map(tex, strength=2.0, fine=1.2, coarse=6.0):
    L = cv2.cvtColor(tex, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    h = cv2.GaussianBlur(L, (0, 0), fine) - cv2.GaussianBlur(L, (0, 0), coarse)
    gx = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3)
    n = np.dstack([-gx * strength, gy * strength, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


def _resample(c, step):
    seg = np.linalg.norm(np.diff(np.vstack([c, c[:1]]), axis=0), axis=1)
    acc = np.concatenate([[0], np.cumsum(seg)])
    n = max(16, int(acc[-1] / step))
    t = np.linspace(0, acc[-1], n, endpoint=False)
    cc = np.vstack([c, c[:1]])
    return np.stack([np.interp(t, acc, cc[:, 0]), np.interp(t, acc, cc[:, 1])], -1)


def _contours(mask_u8):
    cs, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return [c[:, 0, :].astype(float) for c in cs if len(c) > 20]


def inflate(img, mask, px_per_m, half_depth, bevel, relief=0.0, back=1.0, step=10, rings=(2, 5, 10, 18, 30, 45)):
    """Pieza "inflada" desde su silueta: frente hacia la camara (-Y), atras espejo (back=0 la deja plana).
    half_depth y bevel en fraccion de la distancia maxima al borde. Devuelve verts (m), caras, (col,row) por vertice."""
    D = ndimage.distance_transform_edt(mask)
    c = max(_contours(mask.astype(np.uint8)), key=len)
    c = ndimage.gaussian_filter1d(c, 2.0, axis=0, mode='wrap')
    boundary = _resample(c, step * 0.6)
    pts = [boundary]
    for r in rings:                                  # anillos cerca del borde, donde la forma curva fuerte
        for cc in _contours((D >= r).astype(np.uint8)):
            pts.append(_resample(cc, step * (0.7 + r / 40)))
    gy, gx = np.mgrid[0:mask.shape[0]:step * 1.6, 0:mask.shape[1]:step * 1.6]
    g = np.stack([gx.ravel(), gy.ravel()], -1).astype(float)
    g = g[D[g[:, 1].astype(int), g[:, 0].astype(int)] > max(rings) + step]
    pts.append(g)
    nb = len(boundary)
    V = np.vstack(pts)
    seg = np.stack([np.arange(nb), (np.arange(nb) + 1) % nb], -1)
    t = tr.triangulate({'vertices': V, 'segments': seg}, 'pq25Y')
    V2, T = t['vertices'], t['triangles']
    on_b = np.zeros(len(V2), bool); on_b[:nb] = True
    on_b |= ndimage.map_coordinates(D, [V2[:, 1], V2[:, 0]], order=1) < 0.5
    Dmax = D.max()
    d = ndimage.map_coordinates(D, [V2[:, 1], V2[:, 0]], order=1)
    u = np.clip(d / (bevel * Dmax), 0, 1)
    f = half_depth * Dmax * np.sqrt(1 - (1 - u) ** 2)
    if relief:
        L = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        hp = L - cv2.GaussianBlur(L, (0, 0), 14)
        f += relief * Dmax * ndimage.map_coordinates(hp, [V2[:, 1], V2[:, 0]], order=1) * u
    f[on_b] = 0
    # Costados: con la proyeccion plana todo el costado toma la ultima linea de pixeles del borde (se ve estirado).
    # Desde donde la superficie se inclina mas de 55 grados, el costado sigue el contorno y recorre la franja de la
    # foto pegada al borde: baja hasta la silueta y vuelve hacia adentro (un solo reflejo), casi a la escala real.
    xd = np.linspace(0, bevel * Dmax, 600)
    fd = half_depth * Dmax * np.sqrt(1 - (1 - xd / (bevel * Dmax)) ** 2)
    slope = np.gradient(fd, xd)
    j = max(1, np.argmax(slope <= math.tan(math.radians(55))))
    dj = xd[j]
    seglen = np.sqrt(1 + slope ** 2) * np.gradient(xd)
    arc = np.zeros_like(xd)
    arc[:j] = np.cumsum(seglen[:j][::-1])[::-1]
    A = arc[0]                                    # largo del costado, de la union al borde
    W = min(A - dj, 0.45 * Dmax) if A > dj else 0
    k = (dj + W) / A if A > 0 else 1
    a = np.interp(d, xd, arc)
    d_uv = np.where(d < dj, np.abs(dj - a * k), d)
    C = _resample(c, 1.0)
    nC = np.roll(C, -3, 0) - np.roll(C, 3, 0)
    nC = np.stack([nC[:, 1], -nC[:, 0]], -1); nC /= np.maximum(np.linalg.norm(nC, axis=1, keepdims=True), 1e-6)
    probe = C + nC * 3
    inward = ndimage.map_coordinates(D, [probe[:, 1], probe[:, 0]], order=1) > 1
    nC[~inward] *= -1
    nC = ndimage.gaussian_filter1d(nC, 6, axis=0, mode='wrap'); nC /= np.maximum(np.linalg.norm(nC, axis=1, keepdims=True), 1e-6)
    _, kk = spatial.cKDTree(C).query(V2)
    UVP = np.where((d < dj)[:, None], C[kk] + nC[kk] * d_uv[:, None], V2)
    ys, xs = np.nonzero(mask)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    X = (V2[:, 0] - cx) / px_per_m; Z = (cy - V2[:, 1]) / px_per_m
    # frente
    verts = [np.stack([X, -f / px_per_m, Z], -1)]
    colrow = [UVP]
    inner = np.nonzero(~on_b)[0]
    idx_back = np.arange(len(V2)); idx_back[inner] = len(V2) + np.arange(len(inner))
    verts.append(np.stack([X[inner], back * f[inner] / px_per_m, Z[inner]], -1))
    colrow.append(UVP[inner] if back else V2[inner])
    # triangle da caras en sentido antihorario en la imagen (fila hacia abajo) -> mirar desde -Y
    front = T[:, [0, 2, 1]]
    backf = idx_back[T]
    return np.vstack(verts), np.vstack([front, backf]), np.vstack(colrow), np.nonzero(on_b)[0]


# ---------- forma ajustada a la silueta (cubo de tomate, disco de llapingacho) ----------

def project(P, cam):
    """Camara ortografica: yaw alrededor de Z, luego elevacion. Devuelve (col, row)."""
    cx, cy, s, yaw, elev = cam
    cyw, syw = math.cos(yaw), math.sin(yaw)
    x = P[:, 0] * cyw - P[:, 1] * syw
    y = P[:, 0] * syw + P[:, 1] * cyw
    up = P[:, 2] * math.cos(elev) + y * math.sin(elev)
    return np.stack([cx + s * x, cy - s * up], -1)


def superquadric(a, b, c, k_h=10.0, k_v=10.0, n=24):
    """Caja (k altos) o disco (k_h=2) redondeado, como esfera-cubo para que los vertices queden parejos."""
    g = np.linspace(-1, 1, n + 1)
    faces, verts, index = [], [], {}
    def vid(p):
        key = tuple(np.round(p, 6))
        if key not in index:
            index[key] = len(verts); verts.append(p)
        return index[key]
    for axis in range(3):
        for sign in (-1, 1):
            for i in range(n):
                for j in range(n):
                    quad = []
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        p = np.zeros(3); p[axis] = sign
                        o = [k for k in range(3) if k != axis]
                        p[o[0]], p[o[1]] = g[i + di], g[j + dj]
                        quad.append(vid(p))
                    if (sign > 0) != (axis == 1):
                        quad = quad[::-1]
                    faces.append(quad)
    V = np.array(verts); d = V / np.linalg.norm(V, axis=1, keepdims=True)
    h = (np.abs(d[:, 0]) ** k_h + np.abs(d[:, 1]) ** k_h) ** (k_v / k_h) + np.abs(d[:, 2]) ** k_v
    V = d * h[:, None] ** (-1 / k_v) * [a, b, c]
    # todas las caras mirando hacia afuera
    out = []
    for q in faces:
        P = V[q]
        n = np.cross(P[1] - P[0], P[2] - P[0])
        out.append(q if n @ P.mean(0) >= 0 else q[::-1])
    return V, out


def fit_silhouette(mask, shape_fn, x0, bounds=None):
    """Ajusta camara + medidas para que la silueta de la forma coincida con la mascara (IoU)."""
    small = cv2.resize(mask.astype(np.uint8), (256, 256), interpolation=cv2.INTER_NEAREST).astype(bool)
    k = 256 / mask.shape[1]
    def loss(p):
        P, cam = shape_fn(p)
        q = project(P, cam) * k
        hull = cv2.convexHull(q.astype(np.float32)).astype(np.int32)
        sil = np.zeros_like(small, np.uint8); cv2.fillConvexPoly(sil, hull, 1)
        sil = sil.astype(bool)
        return 1 - (sil & small).sum() / max(1, (sil | small).sum())
    best = None
    for start in x0:
        r = optimize.minimize(loss, start, method='Nelder-Mead', options={'maxiter': 3000, 'xatol': 1e-3, 'fatol': 1e-5})
        if best is None or r.fun < best.fun:
            best = r
    return best.x, 1 - best.fun


def rough_map(tex, base, gloss=0.3):
    """Brillo segun la foto: donde la foto tiene reflejos (claro y poco saturado) la superficie es mas lisa."""
    hsv = cv2.cvtColor(tex, cv2.COLOR_RGB2HSV).astype(np.float32) / 255
    hi = np.clip((hsv[..., 2] - 0.78) / 0.15, 0, 1) * np.clip((0.45 - hsv[..., 1]) / 0.25, 0, 1)
    hi = cv2.GaussianBlur(hi, (0, 0), 3)
    return (np.clip(base - gloss * hi, 0.05, 1) * 255).astype(np.uint8)


def delight(tex, knee=0.78, keep=0.5, gain=0.97, gamma=1.0):
    """Quita parte de la luz del estudio que trae la foto (los modelos de Apple tienen texturas de luz pareja):
    baja los reflejos blancos y aclara menos; la luz la pone el visor o el AR."""
    t = tex.astype(np.float32) / 255
    L = t @ np.array([0.299, 0.587, 0.114], np.float32)
    L2 = np.where(L > knee, knee + (L - knee) * keep, L)
    t = t * (L2 / np.maximum(L, 1e-4))[..., None]
    t = np.clip(t * gain, 0, 1) ** gamma
    return (t * 255).astype(np.uint8)


def hidden_face_uv(V, faces, cam, to_uv):
    """UV por esquina: cada cara toma la foto desde la camara; la que no se ve en la foto copia la cara opuesta
    que si se ve (atras <- frente, abajo <- arriba), como si la pieza fuera igual por los dos lados."""
    cx, cy, s, yaw, elev = cam
    c = np.array([-math.sin(yaw) * math.cos(elev), -math.cos(yaw) * math.cos(elev), math.sin(elev)])
    flips = [np.array(f) for f in ((1, 1, 1), (-1, -1, 1), (1, 1, -1), (-1, -1, -1))]
    out = []
    for f in faces:
        P = V[list(f)]
        n = np.cross(P[1] - P[0], P[2] - P[0])
        n = n if n @ P.mean(0) >= 0 else -n
        n /= max(np.linalg.norm(n), 1e-12)
        # la primera que se vea (de frente gana siempre); si ninguna, la que mas se vea
        best = next((fl for fl in flips if (n * fl) @ c > 0.12), max(flips, key=lambda fl: (n * fl) @ c))
        q = project(P * best, cam)
        out.append(to_uv(q[:, 0], q[:, 1]))
    return np.vstack(out)


def lumpy(V, amp, seed=3):
    """Deforma suave hacia afuera/adentro con ondas al azar (la misma deformacion para la malla alta y la baja)."""
    rng = np.random.default_rng(seed)
    n = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
    size = np.ptp(V, 0).max()
    d = np.zeros(len(V))
    for _ in range(6):
        k = rng.normal(size=3) * (2.5 / size); ph = rng.uniform(0, 2 * np.pi)
        d += np.sin(V @ k * 2 * np.pi + ph) / 6
    return V + n * (amp * d)[:, None]
