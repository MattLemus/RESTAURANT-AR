// Seguimiento de la mesa para fritada-ar.html (lo que Snapchat llama "Surface tracking"), en un hilo aparte para que dibujar
// el plato no se trabe en celulares modestos. Puntos con textura de la mesa (veta, cables, bordes) se siguen cuadro a cuadro
// (flujo optico de jsfeat). Cada punto tiene su lugar fijo en la mesa; de donde se ven en el cuadro salen la posicion del celular
// y una pequena correccion a la orientacion del giroscopio, que llega algo desfasado del video (sin corregirla, girar el celular
// pareceria moverlo). Recibe: el cuadro reducido + la orientacion del giroscopio cuando se tomo. Devuelve: posicion y correccion.
self.window = self // jsfeat se registra en "window"
importScripts('https://cdn.jsdelivr.net/npm/jsfeat@0.0.8/build/jsfeat-min.js')
const MAXP = 80, CELL = 16 // como mucho 80 puntos, uno por cuadricula de 16 px para que queden repartidos
let fov = 67, tw = 0, th = 0, focal = 1, ctx, prevPyr, currPyr, corners, pts = [], lastT = 0, thr = 10, frameNo = 0
const c = [0, 0.45, 0] // posicion del celular (m); la mesa es el plano y = 0
const pxy = new Float32Array(MAXP * 2), cxy = new Float32Array(MAXP * 2), ok = new Uint8Array(MAXP), A = new Float64Array(42)

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
    sig = Math.max(2, pts.map((p) => p.e).sort((a, b) => a - b)[pts.length >> 1])
  }
  return qc
}

onmessage = ({data: m}) => {
  if (m.h) { c[1] = m.h; fov = m.fov; return } // configuracion inicial
  const t1 = performance.now(), {bmp, q: qF, t} = m, w = bmp.width, h = bmp.height
  if (w !== tw || h !== th) { // primer cuadro o el celular cambio de orientacion: se empieza de cero
    tw = w; th = h; pts = []
    focal = (Math.max(w, h) / 2) / Math.tan(fov * Math.PI / 360)
    ctx = new OffscreenCanvas(w, h).getContext('2d', {willReadFrequently: true})
    prevPyr = new jsfeat.pyramid_t(4); currPyr = new jsfeat.pyramid_t(4)
    prevPyr.allocate(w, h, jsfeat.U8C1_t); currPyr.allocate(w, h, jsfeat.U8C1_t)
    corners = Array.from({length: (w * h) >> 2}, () => new jsfeat.keypoint_t())
  }
  ctx.drawImage(bmp, 0, 0); bmp.close()
  jsfeat.imgproc.grayscale(ctx.getImageData(0, 0, w, h).data, w, h, currPyr.data[0])
  currPyr.build(currPyr.data[0], true)
  // tras un tiron (el celular trabado, p. ej. al cargar el plato) los puntos ya no se pueden seguir: mejor volver a sembrarlos
  // desde la pose actual que arrastrar puntos mal seguidos, que dejarian el plato corrido para siempre
  if (t - lastT > 250) pts = []
  lastT = t
  let qc = [0, 0, 0, 1], tracking = false
  if (pts.length) {
    const before = pts.length
    pts.forEach((p, i) => { pxy[2 * i] = p.x; pxy[2 * i + 1] = p.y })
    jsfeat.optical_flow_lk.track(prevPyr, currPyr, pxy, cxy, pts.length, 15, 20, ok, 0.01, 0.001)
    pts = pts.filter((p, i) => ok[i] && (p.b = camRay(p.x = cxy[2 * i], p.y = cxy[2 * i + 1])))
    if (pts.length < before / 2) pts = []
    tracking = pts.length >= 8
    if (tracking) { qc = solvePose(qF); pts = pts.filter((p) => p.e < 4) }
  }
  const qv = qmul(qc, qF) // orientacion corregida de este cuadro
  // puntos nuevos en las zonas de la imagen que se quedaron sin puntos; buscar esquinas recorre toda la imagen (caro), por eso
  // solo cada 3 cuadros salvo que queden muy pocos
  if (pts.length < 40 && (pts.length < 15 || ++frameNo % 3 === 0)) {
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
  postMessage({tracking, c, qc, qv, n: pts.length, ms: performance.now() - t1,
    // ?debug: los puntos para dibujarlos, y el inicio de la fila 3 del cuadro (las pruebas automaticas leen ahi el numero de cuadro)
    ...(m.debug && {xy: pts.flatMap((p) => [p.x, p.y]), strip: Array.from(prevPyr.data[0].data.subarray(3 * w, 3 * w + 60))})})
}
