// Seguimiento de la mesa para fritada-ar.html (lo que Snapchat llama "Surface tracking"), en un hilo aparte para que dibujar
// el plato no se trabe en celulares modestos. Puntos con textura de la mesa (veta, cables, bordes) se siguen cuadro a cuadro
// (flujo optico de jsfeat). Cada punto tiene su lugar fijo en la mesa; de donde se ven en el cuadro salen la posicion del celular
// y una pequena correccion a la orientacion del giroscopio, que llega algo desfasado del video (sin corregirla, girar el celular
// pareceria moverlo). Recibe: el cuadro reducido + la orientacion del giroscopio cuando se tomo. Devuelve: posicion y correccion.
// Segun LOGICA_ANCLAJE_SUPERFICIES_SIN_ARCORE.md: seguimiento ida y vuelta, pose validada antes de usarla, puntos nuevos solo
// desde una pose validada, y vistas guardadas de la mesa para volver al mismo lugar tras perderla.
self.window = self // jsfeat se registra en "window"
importScripts('https://cdn.jsdelivr.net/npm/jsfeat@0.0.8/build/jsfeat-min.js')
const MAXP = 80, CELL = 16 // como mucho 80 puntos, uno por cuadricula de 16 px para que queden repartidos
let fov = 67, tw = 0, th = 0, focal = 1, ctx, prevPyr, currPyr, corners, blur, pts = [], lastT = 0, thr = 10, frameNo = 0
const c = [0, 0.45, 0] // posicion del celular (m); la mesa es el plano y = 0
let cOk = c.slice(), tOk = 0, bad = 0, kfs = [], relocFor = 0 // ultima pose validada, cuadros malos seguidos, vistas guardadas
const pxy = new Float32Array(MAXP * 2), cxy = new Float32Array(MAXP * 2), bxy = new Float32Array(MAXP * 2), ok = new Uint8Array(MAXP), ok2 = new Uint8Array(MAXP), A = new Float64Array(42)

// cuaterniones [x, y, z, w] y vectores [x, y, z], con las mismas formulas que three.js
const qmul = (a, b) => [a[0] * b[3] + a[3] * b[0] + a[1] * b[2] - a[2] * b[1], a[1] * b[3] + a[3] * b[1] + a[2] * b[0] - a[0] * b[2],
  a[2] * b[3] + a[3] * b[2] + a[0] * b[1] - a[1] * b[0], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]]
const qrot = (q, v) => {
  const tx = 2 * (q[1] * v[2] - q[2] * v[1]), ty = 2 * (q[2] * v[0] - q[0] * v[2]), tz = 2 * (q[0] * v[1] - q[1] * v[0])
  return [v[0] + q[3] * tx + q[1] * tz - q[2] * ty, v[1] + q[3] * ty + q[2] * tx - q[0] * tz, v[2] + q[3] * tz + q[0] * ty - q[1] * tx]
}
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const camRay = (x, y) => { const v = [(x - tw / 2) / focal, -(y - th / 2) / focal, -1], n = Math.hypot(...v); return v.map((a) => a / n) }
const cellOf = (p) => ((p.y / CELL) | 0) * 64 + ((p.x / CELL) | 0)
const median = (a) => a.sort((x, y) => x - y)[a.length >> 1]

// Gauss-Newton: c = posicion, qc = giro pequeno sobre el giroscopio. Cada punto pesa menos cuanto peor encaja (reflejos, cosas
// que no estan en la mesa), y ambas incognitas se atan un poco a su valor previo para no temblar.
// Probado con video sintetico: atar mas el giro al giroscopio hace que girar parezca moverse; atar mas la posicion, al reves.
const solvePose = (qF) => {
  const c0 = c.slice(), wv = [0, 0, 0], lc = 0.05 * pts.length, lw = 0.001 * pts.length
  let qc = [0, 0, 0, 1]
  for (let it = 0, sig = 1e9; it < 4; it++) {
    const qv = qmul(qc, qF)
    A.fill(0)
    for (const p of pts) {
      const d = p.d = qrot(qv, p.b), u = [p.P[0] - c[0], p.P[1] - c[1], p.P[2] - c[2]], n = Math.hypot(...u), ud = dot(u, d)
      const r = cross(u, d).map((a) => a / n) // ~ angulo entre donde se ve el punto y donde deberia verse
      p.e = Math.hypot(...r) * focal // en px
      const k = 1 / (1 + (p.e / sig) ** 2)
      const J = [[0, -d[2] / n, d[1] / n, (ud - d[0] * u[0]) / n, -d[0] * u[1] / n, -d[0] * u[2] / n],
        [d[2] / n, 0, -d[0] / n, -d[1] * u[0] / n, (ud - d[1] * u[1]) / n, -d[1] * u[2] / n],
        [-d[1] / n, d[0] / n, 0, -d[2] * u[0] / n, -d[2] * u[1] / n, (ud - d[2] * u[2]) / n]]
      for (let j = 0; j < 3; j++) for (let a = 0; a < 6; a++) {
        for (let b = 0; b < 6; b++) A[a * 7 + b] += k * J[j][a] * J[j][b]
        A[a * 7 + 6] -= k * J[j][a] * r[j]
      }
    }
    for (let a = 0; a < 3; a++) {
      A[a * 8] += lc; A[a * 7 + 6] -= lc * (c[a] - c0[a])
      A[(a + 3) * 8] += lw; A[(a + 3) * 7 + 6] -= lw * wv[a]
    }
    for (let i = 0; i < 6; i++) for (let j = i + 1; j < 6; j++) { const f = A[j * 7 + i] / A[i * 8]; for (let k = i; k < 7; k++) A[j * 7 + k] -= f * A[i * 7 + k] }
    for (let i = 5; i >= 0; i--) { let s = A[i * 7 + 6]; for (let k = i + 1; k < 6; k++) s -= A[i * 7 + k] * A[k * 7 + 6]; A[i * 7 + 6] = s / A[i * 8] }
    for (let a = 0; a < 3; a++) { c[a] += A[a * 7 + 6]; wv[a] += A[(a + 3) * 7 + 6] }
    const w = [A[27], A[34], A[41]], ang = Math.hypot(...w)
    if (ang > 1e-9) { const s = Math.sin(ang / 2) / ang; qc = qmul([w[0] * s, w[1] * s, w[2] * s, Math.cos(ang / 2)], qc) }
    // escala de los pesos = error tipico de esta vuelta: si todos estan corridos (giroscopio desfasado) ninguno se descarta
    sig = Math.max(2, median(pts.map((p) => p.e)))
  }
  return qc
}

// Antes de usar una pose: bastantes puntos, repartidos, que encajen, y un movimiento posible para una mano. Si no, se descarta;
// una pose mala aceptada (p. ej. un tiron borroso) dejaba el plato gigante o atravesado para siempre.
const plausible = (qc, t) => {
  if (pts.length < 10) return false
  let x0 = tw, x1 = 0, y0 = th, y1 = 0
  for (const p of pts) { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y) }
  const jump = Math.hypot(c[0] - cOk[0], c[1] - cOk[1], c[2] - cOk[2])
  return median(pts.map((p) => p.e)) < 2 && (x1 - x0) * (y1 - y0) > 0.06 * tw * th && // px; area de la imagen que cubren
    jump < 0.04 + 1.5 * (t - tOk) / 1000 && c[1] > 0.08 && c[1] < 2 && // m, m/s: una mano no teletransporta el celular
    2 * Math.acos(Math.min(1, Math.abs(qc[3]))) < 0.15 // rad: el giroscopio no se equivoca tanto
}
const lose = () => { pts = []; bad = 0; c.splice(0, 3, ...cOk) }

// --- vistas guardadas para reencontrar la mesa (seccion 10) ---
// Descriptores ORB de los puntos seguidos + su lugar en la mesa. El angulo de cada descriptor es la direccion en la imagen del
// eje x de la mesa (sale del giroscopio, no depende de donde este el celular), asi el mismo punto da el mismo descriptor aunque
// el celular este girado.
const qinv = (q) => [-q[0], -q[1], -q[2], q[3]]
const angleAt = (x, y, qv) => {
  const v = qrot(qinv(qv), [0.01, 0, 0]), b = camRay(x, y), p = b.map((a) => a / -b[2]), z = -(p[2] + v[2])
  return Math.atan2(th / 2 - focal * (p[1] + v[1]) / z - y, tw / 2 + focal * (p[0] + v[0]) / z - x)
}
const describe = (xy, qv) => { // xy: [[x, y], ...] -> descriptores (8 enteros de 32 bits por punto)
  const ks = xy.map(([x, y]) => new jsfeat.keypoint_t(x, y, 0, 0, angleAt(x, y, qv))), d = new jsfeat.matrix_t(32, ks.length, jsfeat.U8C1_t)
  jsfeat.imgproc.gaussian_blur(currPyr.data[0], blur, 5)
  jsfeat.orb.describe(blur, ks, ks.length, d)
  return new Uint32Array(d.data.buffer, 0, ks.length * 8)
}
const pop = (v) => { v -= (v >>> 1) & 0x55555555; v = (v & 0x33333333) + ((v >>> 2) & 0x33333333); return (((v + (v >>> 4)) & 0xf0f0f0f) * 0x1010101) >>> 24 }
const inside = (p) => p.x > 16 && p.y > 16 && p.x < tw - 16 && p.y < th - 16 // ORB mira 32x32 px alrededor
const addKeyframe = (qv) => {
  const f = qrot(qv, [0, 0, -1]), use = pts.filter(inside)
  if (use.length < 25 || kfs.some((k) => Math.hypot(c[0] - k.c[0], c[1] - k.c[1], c[2] - k.c[2]) < 0.15 * c[1] && dot(f, k.f) > 0.98)) return
  kfs.push({c: c.slice(), f, P: use.map((p) => p.P), d: describe(use.map((p) => [p.x, p.y]), qv)})
  if (kfs.length > 10) kfs.splice(1, 1) // la primera vista (donde se puso el plato) se queda siempre
}
// punto mas cercano a todas las rectas P + s*d: la posicion del celular si se conoce su orientacion (el giroscopio)
const closest = (ms) => {
  const M = [0, 0, 0, 0, 0, 0, 0, 0, 0], r = [0, 0, 0]
  for (const {d, P} of ms) for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) { const v = (a === b) - d[a] * d[b]; M[a * 3 + b] += v; r[a] += v * P[b] }
  const det = (m) => m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6]), D = det(M)
  if (Math.abs(D) < 1e-9) return null
  return [0, 1, 2].map((i) => det(M.map((v, k) => (k % 3 === i ? r[(k / 3) | 0] : v))) / D) // Cramer
}
const errPx = (m, cc) => { const u = [m.P[0] - cc[0], m.P[1] - cc[1], m.P[2] - cc[2]]; return dot(u, m.d) > 0 ? Math.hypot(...cross(u, m.d)) / Math.hypot(...u) * focal : 1e9 }
// Esquinas del cuadro actual comparadas con las vistas guardadas; con 2 coincidencias al azar sale una posicion (RANSAC) y gana
// la que mas coincidencias explica. Se acepta solo si pasa la misma validacion que el seguimiento normal.
const relocalize = (qF, t) => {
  const f = qrot(qF, [0, 0, -1]), cand = kfs.filter((k) => dot(k.f, f) > 0.75)
  if (!cand.length) return false
  jsfeat.fast_corners.set_threshold(thr)
  const n = jsfeat.fast_corners.detect(currPyr.data[0], corners, 16)
  const qs = corners.slice(0, n).sort((a, b) => b.score - a.score).slice(0, 150)
  if (qs.length < 15) return false
  const qd = describe(qs.map((k) => [k.x, k.y]), qF)
  let best = []
  for (const k of cand) {
    const ms = [], m = k.P.length
    for (let i = 0; i < qs.length; i++) {
      let b1 = 999, b2 = 999, bj = 0
      for (let j = 0; j < m; j++) {
        let h = 0
        for (let w = 0; w < 8 && h < b2; w++) h += pop(qd[i * 8 + w] ^ k.d[j * 8 + w])
        if (h < b1) { b2 = b1; b1 = h; bj = j } else if (h < b2) b2 = h
      }
      if (b1 < 50 && b1 < 0.8 * b2) { const b = camRay(qs[i].x, qs[i].y); ms.push({x: qs[i].x, y: qs[i].y, b, d: qrot(qF, b), P: k.P[bj]}) }
    }
    if (ms.length > best.length) best = ms
  }
  if (best.length < 15) return false
  let inl = []
  for (let it = 0; it < 150; it++) {
    const a = best[(Math.random() * best.length) | 0], b = best[(Math.random() * best.length) | 0], cc = a !== b && closest([a, b])
    if (!cc || cc[1] < 0.08) continue
    const s = best.filter((m) => errPx(m, cc) < 8)
    if (s.length > inl.length) inl = s
  }
  const cc = inl.length >= Math.max(12, 0.3 * best.length) && closest(inl)
  if (!cc || Math.hypot(cc[0] - cOk[0], cc[1] - cOk[1], cc[2] - cOk[2]) > 1) return false
  const keep = pts, c0 = c.slice(), t0 = tOk
  c.splice(0, 3, ...cc); pts = inl.map(({x, y, b, P}) => ({x, y, b, P}))
  const qc = solvePose(qF)
  pts = pts.filter((p) => p.e < 4)
  tOk = -1e9 // el salto respecto a la pose de antes es justamente la correccion
  if (plausible(qc, t)) return qc
  pts = keep; c.splice(0, 3, ...c0); tOk = t0
  return false
}

onmessage = ({data: m}) => {
  if (m.h) { c[1] = m.h; cOk = c.slice(); fov = m.fov; return } // configuracion inicial
  const t1 = performance.now(), {bmp, q: qF, t} = m, w = bmp.width, h = bmp.height
  if (w !== tw || h !== th) { // primer cuadro o el celular cambio de orientacion: se empieza de cero
    tw = w; th = h; pts = []; kfs = []
    focal = (Math.max(w, h) / 2) / Math.tan(fov * Math.PI / 360)
    ctx = new OffscreenCanvas(w, h).getContext('2d', {willReadFrequently: true})
    prevPyr = new jsfeat.pyramid_t(4); currPyr = new jsfeat.pyramid_t(4)
    prevPyr.allocate(w, h, jsfeat.U8C1_t); currPyr.allocate(w, h, jsfeat.U8C1_t)
    blur = new jsfeat.matrix_t(w, h, jsfeat.U8C1_t)
    corners = Array.from({length: (w * h) >> 2}, () => new jsfeat.keypoint_t())
  }
  ctx.drawImage(bmp, 0, 0); bmp.close()
  jsfeat.imgproc.grayscale(ctx.getImageData(0, 0, w, h).data, w, h, currPyr.data[0])
  currPyr.build(currPyr.data[0], true)
  // tras un tiron (el celular trabado, p. ej. al cargar el plato) los puntos ya no se pueden seguir: mejor volver a sembrarlos
  // desde la ultima pose buena que arrastrar puntos mal seguidos, que dejarian el plato corrido para siempre
  if (t - lastT > 250) lose()
  lastT = t
  let qc = [0, 0, 0, 1], valid = false, reloc = false
  if (pts.length) {
    const before = pts.length
    pts.forEach((p, i) => { pxy[2 * i] = p.x; pxy[2 * i + 1] = p.y })
    jsfeat.optical_flow_lk.track(prevPyr, currPyr, pxy, cxy, pts.length, 15, 20, ok, 0.01, 0.001)
    // y de vuelta: un punto bien seguido regresa a donde estaba; si no (borroso, reflejo, algo que se movio) se descarta
    jsfeat.optical_flow_lk.track(currPyr, prevPyr, cxy, bxy, pts.length, 15, 20, ok2, 0.01, 0.001)
    pts = pts.filter((p, i) => ok[i] && ok2[i] && Math.hypot(bxy[2 * i] - p.x, bxy[2 * i + 1] - p.y) < 1 && (p.b = camRay(p.x = cxy[2 * i], p.y = cxy[2 * i + 1])))
    if (pts.length < before / 2 || pts.length < 8) lose()
    else {
      qc = solvePose(qF)
      valid = plausible(qc, t)
      if (valid) { pts = pts.filter((p) => p.e < 4); bad = 0 }
      else { c.splice(0, 3, ...cOk); qc = [0, 0, 0, 1]; if (++bad >= 3) lose() } // seguimiento degradado: se mantiene la pose buena
    }
  }
  // recien vuelta la mesa: se busca en las vistas guardadas, por si el celular se movio mientras no se la veia
  if (relocFor > 0 && relocFor-- % 3 === 0) { const r = relocalize(qF, t); if (r) { qc = r; valid = reloc = true; relocFor = 0 } }
  if (valid) { cOk = c.slice(); tOk = t }
  const qv = qmul(qc, qF) // orientacion corregida de este cuadro
  // mientras se busca la mesa en las vistas guardadas no se guardan vistas nuevas: podrian estar corridas respecto al plato
  if (valid && ++frameNo % 5 === 0 && relocFor <= 0) addKeyframe(qv)
  // puntos nuevos en las zonas de la imagen que se quedaron sin puntos, solo desde una pose validada (o la ultima buena si no
  // queda ninguno); buscar esquinas recorre toda la imagen (caro), por eso solo cada 3 cuadros salvo que queden muy pocos
  if ((valid || !pts.length) && pts.length < 40 && (pts.length < 15 || frameNo % 3 === 0)) {
    if (!pts.length && kfs.length) relocFor = 45
    thr = pts.length < 30 ? Math.max(4, thr - 1) : Math.min(20, thr + 1) // mesa lisa: se aceptan esquinas mas suaves
    jsfeat.fast_corners.set_threshold(thr)
    const n = jsfeat.fast_corners.detect(currPyr.data[0], corners, 8), used = new Set(pts.map(cellOf)), best = new Map()
    for (let i = 0; i < n; i++) { const k = corners[i], key = cellOf(k); if (!used.has(key) && !(best.get(key)?.score >= k.score)) best.set(key, k) }
    for (const k of [...best.values()].sort((a, b) => b.score - a.score)) {
      if (pts.length >= MAXP) break
      const b = camRay(k.x, k.y), d = qrot(qv, b)
      if (d[1] > -0.2) continue // en el horizonte o arriba: no es la mesa
      const s = -c[1] / d[1], P = [c[0] + d[0] * s, 0, c[2] + d[2] * s]
      if (s < 2) pts.push({x: k.x, y: k.y, b, d, P}) // mas lejos suele ser el piso o la pared
    }
  }
  ;[prevPyr, currPyr] = [currPyr, prevPyr]
  const state = valid ? 'seguimiento' : bad ? 'degradado' : relocFor > 0 ? 'relocalizando' : 'perdido'
  postMessage({tracking: valid, reloc, state, c, qc, qv, n: pts.length, kf: kfs.length, ms: performance.now() - t1,
    // ?debug: los puntos para dibujarlos, y el inicio de la fila 3 del cuadro (las pruebas automaticas leen ahi el numero de cuadro)
    ...(m.debug && {xy: pts.flatMap((p) => [p.x, p.y]), strip: Array.from(prevPyr.data[0].data.subarray(3 * w, 3 * w + 60))})})
}
