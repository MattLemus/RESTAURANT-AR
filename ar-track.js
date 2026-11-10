// Seguimiento de la mesa para ar.html (lo que Snapchat llama "Surface tracking"), en un hilo aparte para que dibujar
// el plato no se trabe. Puntos con textura de la mesa (veta, cables, bordes) se siguen cuadro a cuadro; cada punto tiene su lugar
// fijo en la mesa, y de donde se ven en el cuadro salen la posicion del celular y una correccion a la orientacion del sensor.
// Recibe: el cuadro reducido + la orientacion del sensor cuando se tomo. Devuelve: la pose de ESE cuadro, que la pagina dibuja
// junto con ese mismo cuadro (asi el plato no se desliza respecto a la mesa aunque el calculo tarde).
// Segun LOGICA_ANCLAJE_SUPERFICIES_SIN_ARCORE.md: pose validada antes de usarla, puntos nuevos solo desde una pose validada, y
// vistas guardadas de la mesa para volver al mismo lugar tras perderla. Segun LOGICA_FLUIDEZ_FILTROS_3D_SIN_ARCORE.md: cada
// cuadro tiene que costar poco (en celulares modestos el seguidor anterior tardaba ~170 ms; ver lk() y el presupuesto de puntos).
self.window = self // jsfeat se registra en "window"
importScripts('https://cdn.jsdelivr.net/npm/jsfeat@0.0.8/build/jsfeat-min.js')
const CELL = 16, LEVELS = 4 // un punto por cuadricula de 16 px, para que queden repartidos
let maxp = 60 // presupuesto de puntos: baja si el celular tarda, sube si le sobra tiempo (ver el final de onmessage)
let fov = 67, tw = 0, th = 0, focal = 1, ctx, prevPyr, currPyr, corners, blur, pts = [], lastT = 0, thr = 10, frameNo = 0, msAvg = 0
const c = [0, 0.45, 0] // posicion del celular (m); la mesa es el plano y = 0
let cOk = c.slice(), tOk = 0, bad = 0, kfs = [], relocFor = 0 // ultima pose validada, cuadros malos seguidos, vistas guardadas
let trasBrusco = false // buscando la mesa en las vistas guardadas despues de un tiron (el plato no se muestra)
// error del sensor de orientacion medido por la imagen. En celulares sin giroscopio (solo acelerometro + brujula) la brujula se
// desvia varios grados (mas cerca de metal) y casi no cambia de un cuadro al otro: se arrastra en vez de volver a cero
let qb = [0, 0, 0, 1], qvPrev = null, flowPrev = [0, 0]
// ...pero solo en el giro horizontal: la inclinacion (donde esta el piso) la da bien el acelerometro. Aprendiendo tambien la
// inclinacion, cada error chico de la imagen se sumaba sin volver nunca a cero: la mesa virtual se ladeaba de a poco (con
// teclado y plato sobresaliendo de la mesa, 2-4 grados en 90 s simulados) y el plato se veia como desde arriba (prueba 01-11)
const soloGiro = (q) => { const n = Math.hypot(q[1], q[3]); return [0, q[1] / n, 0, q[3] / n] }
// Y si la imagen sostiene una inclinacion distinta a la del acelerometro (mapa de puntos armado desde una pose ladeada: el ajuste
// lo defiende cuadro a cuadro), se la lleva al piso de a poco, como un estabilizador. Solo un error grande y sostenido: mediana de
// los ultimos 3 s (un empujon de la mano mueve el acelerometro menos de 1 s) y mas de 3 grados (menos no se nota; cada correccion
// corre un poco el plato, y el atraso del sensor al girar ya da ~1 grado). Se corrige en ~1 s girando alrededor de la mesa que se ve (donde suele estar el plato: asi
// no se corre en la imagen; girando alrededor del celular se corria ~30 px) y los puntos se rehacen desde la pose corregida
const desv = [] // [hora, giro en x, giro en z] que llevaria el piso de la imagen al del acelerometro (ejes del mundo, rad)
const aPlomo = (qv, q, t, dt) => {
  const s = qrot(qv, qrot(qinv(q), [0, -1, 0])) // el piso del acelerometro, en el mundo de la imagen
  desv.push([t, s[2], -s[0]]) // cruz(s, abajo)
  while (desv[0][0] < t - 3000) desv.shift()
  const ex = median(desv.map((d) => d[1])), ez = median(desv.map((d) => d[2]))
  if (desv.length < 30 || Math.hypot(ex, ez) < 0.052 || !dt) return qv
  const k = Math.min(1, dt), x = ex * k, z = ez * k, a = Math.hypot(x, z), sn = Math.sin(a / 2) / a, r = [x * sn, 0, z * sn, Math.cos(a / 2)]
  for (const d of desv) { d[1] -= x; d[2] -= z }
  const o = [median(pts.map((p) => p.P[0])), 0, median(pts.map((p) => p.P[2]))], v = qrot(r, [c[0] - o[0], c[1], c[2] - o[2]])
  c.splice(0, 3, o[0] + v[0], v[1], o[2] + v[2])
  qv = qmul(r, qv)
  for (const p of pts) { const d = qrot(qv, p.b); if (d[1] < -0.05) { const l = -c[1] / d[1]; p.P = [c[0] + d[0] * l, 0, c[2] + d[2] * l] } }
  return qv
}
const A = new Float64Array(42)

// cuaterniones [x, y, z, w] y vectores [x, y, z], con las mismas formulas que three.js
const qmul = (a, b) => [a[0] * b[3] + a[3] * b[0] + a[1] * b[2] - a[2] * b[1], a[1] * b[3] + a[3] * b[1] + a[2] * b[0] - a[0] * b[2],
  a[2] * b[3] + a[3] * b[2] + a[0] * b[1] - a[1] * b[0], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]]
const qrot = (q, v) => {
  const tx = 2 * (q[1] * v[2] - q[2] * v[1]), ty = 2 * (q[2] * v[0] - q[0] * v[2]), tz = 2 * (q[0] * v[1] - q[1] * v[0])
  return [v[0] + q[3] * tx + q[1] * tz - q[2] * ty, v[1] + q[3] * ty + q[2] * tx - q[0] * tz, v[2] + q[3] * tz + q[0] * ty - q[1] * tx]
}
const qinv = (q) => [-q[0], -q[1], -q[2], q[3]]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const camRay = (x, y) => { const v = [(x - tw / 2) / focal, -(y - th / 2) / focal, -1], n = Math.hypot(...v); return v.map((a) => a / n) }
const cellOf = (p) => ((p.y / CELL) | 0) * 64 + ((p.x / CELL) | 0)
const median = (a) => a.sort((x, y) => x - y)[a.length >> 1]

// --- Lucas-Kanade piramidal propio (seccion 7 de LOGICA_ANCLAJE) ---
// El de jsfeat recalculaba las derivadas de toda la imagen en cada llamada y se usaba dos veces (ida y vuelta): era casi todo
// el tiempo del cuadro. Este calcula solo la ventana de cada punto (9x9), una vez por nivel, y empieza a buscar donde la pose
// prevista dice que deberia estar el punto, asi converge en pocas vueltas. En vez de la vuelta, cada punto se valida
// comparando su parche con el del cuadro anterior (correlacion): un reflejo, algo que tapa la mesa o un desenfoque fuerte no
// se parecen y se descartan; los que se corren de a poco los descarta despues el ajuste de la pose (no encajan en el plano).
// Calculo: ~60 puntos x 4 niveles x pocas vueltas de 81 px, contra las derivadas de las 4 imagenes enteras dos veces de antes.
const R = 5, WS = 2 * R + 1, WN = WS * WS, SW = WS + 2
const T = new Float32Array(WN), GX = new Float32Array(WN), GY = new Float32Array(WN), S = new Float32Array(SW * SW), I = new Float32Array(WN)
let cw = 0, ch = 0 // limites para bil en los niveles chicos: ahi la ventana puede salirse (se repite el borde)
const bil = (d, w, x, y) => { // x, y >= 0 (se comprueba antes, salvo en los niveles chicos, que pasan por el recorte)
  if (cw) { x = x < 0 ? 0 : x > cw ? cw : x; y = y < 0 ? 0 : y > ch ? ch : y }
  const x0 = x | 0, y0 = y | 0, ax = x - x0, ay = y - y0, i = y0 * w + x0, a = d[i] + (d[i + 1] - d[i]) * ax
  return a + (d[i + w] + (d[i + w + 1] - d[i + w]) * ax - a) * ay
}
// (x, y): el punto en el cuadro anterior; (gx, gy): donde se lo espera en este. Devuelve [x, y, correlacion] o null
const lk = (x, y, gx, gy) => {
  let dx = gx - x, dy = gy - y
  for (let l = LEVELS - 1; l >= 0; l--) {
    const s = 1 / (1 << l), a = prevPyr.data[l], w = a.cols, h = a.rows, ia = a.data, ib = currPyr.data[l].data
    const px = x * s, py = y * s
    let ex = dx * s, ey = dy * s
    // en los niveles chicos un punto cerca del borde igual busca (repitiendo el borde): sin ellos los saltos grandes se pierden
    cw = l ? w - 1.001 : 0; ch = h - 1.001
    if (!l && (px < R + 2 || py < R + 2 || px > w - R - 3 || py > h - R - 3)) return null // cerca del borde de la imagen
    for (let j = 0, k = 0; j < SW; j++) for (let i = 0; i < SW; i++, k++) S[k] = bil(ia, w, px - R - 1 + i, py - R - 1 + j)
    let hxx = 0, hxy = 0, hyy = 0, sgx = 0, sgy = 0, st = 0, stt = 0, sgtx = 0, sgty = 0
    for (let j = 0, k = 0; j < WS; j++) for (let i = 0; i < WS; i++, k++) {
      const o = (j + 1) * SW + i + 1, gxv = (S[o + 1] - S[o - 1]) * 0.5, gyv = (S[o + SW] - S[o - SW]) * 0.5, tv = S[o]
      T[k] = tv; GX[k] = gxv; GY[k] = gyv; hxx += gxv * gxv; hxy += gxv * gyv; hyy += gyv * gyv
      sgx += gxv; sgy += gyv; st += tv; stt += tv * tv; sgtx += gxv * tv; sgty += gyv * tv
    }
    const det = hxx * hyy - hxy * hxy, mt = st / WN, sdt = Math.sqrt(Math.max(1e-6, stt / WN - mt * mt))
    // poca textura en esta ventana: con el menor autovalor bajo, el desplazamiento queda mal definido (borde liso o mancha).
    // En los niveles chicos la imagen esta suavizada y el umbral es menor: ahi solo se busca el desplazamiento grueso
    const lmin = (hxx + hyy) / 2 - Math.sqrt(((hxx - hyy) / 2) ** 2 + hxy * hxy)
    if (lmin < (l ? 0.05 : 0.25) * WN) { if (!l) return null; continue }
    for (let it = 0; it < 12; it++) {
      const qx = px + ex - R, qy = py + ey - R
      if (!l && (qx < 0 || qy < 0 || qx > w - WS - 1 || qy > h - WS - 1)) return null // la ventana se sale de la imagen
      if (l && (qx < -WS || qy < -WS || qx > w || qy > h)) break // en un nivel chico, fuera del todo: se sigue con el siguiente
      let si = 0, sii = 0, sgix = 0, sgiy = 0
      for (let j = 0, k = 0; j < WS; j++) for (let i = 0; i < WS; i++, k++) { const v = bil(ib, w, qx + i, qy + j); si += v; sii += v * v; sgix += GX[k] * v; sgiy += GY[k] * v }
      // la camara aclara u oscurece sola (exposicion automatica): la ventana nueva se lleva al brillo y contraste de la vieja
      // (I*g + o) antes de comparar, si no un cambio de exposicion empuja el punto
      const mi = si / WN, g = sdt / Math.sqrt(Math.max(1e-6, sii / WN - mi * mi)), o = mt - g * mi
      const bx = g * sgix + o * sgx - sgtx, by = g * sgiy + o * sgy - sgty
      const ux = (hyy * bx - hxy * by) / det, uy = (hxx * by - hxy * bx) / det
      ex -= ux; ey -= uy
      if (ux * ux + uy * uy < 0.001) break // menos de 0.03 px
    }
    dx = ex / s; dy = ey / s
    if (!l) { // correlacion del parche en su lugar final (1 = identico)
      const qx = px + ex - R, qy = py + ey - R
      if (!(qx >= 0 && qy >= 0 && qx <= w - WS - 1 && qy <= h - WS - 1)) return null // tambien descarta NaN
      let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0
      for (let j = 0, k = 0; j < WS; j++) for (let i = 0; i < WS; i++, k++) {
        const va = T[k], vb = I[k] = bil(ib, w, qx + i, qy + j); sa += va; sb += vb; saa += va * va; sbb += vb * vb; sab += va * vb
      }
      const cv = sab - sa * sb / WN, va = saa - sa * sa / WN, vb = sbb - sb * sb / WN
      return [x + dx, y + dy, cv / Math.sqrt(va * vb + 1e-6)]
    }
  }
  return null
}

// Gauss-Newton: c = posicion, qc = giro pequeno sobre el sensor. Cada punto pesa menos cuanto peor encaja (reflejos, cosas
// que no estan en la mesa), y ambas incognitas se atan un poco a su valor previo para no temblar.
// Probado con video sintetico: atar mas el giro al sensor hace que girar parezca moverse; atar mas la posicion, al reves.
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
    // escala de los pesos = error tipico de esta vuelta: si todos estan corridos (sensor desfasado) ninguno se descarta
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
    2 * Math.acos(Math.min(1, Math.abs(qc[3]))) < 0.25 // rad: el error del sensor no cambia tanto de un cuadro al otro
}
// seguimiento perdido de verdad (no por un cuadro atrasado): se vuelve a la ultima pose buena y se busca la mesa en las vistas
// guardadas, ya mismo (tiron con la mesa a la vista) y otra vez cuando la mesa vuelve a verse (se miro a otro lado un rato)
let lost = false
const lose = () => { pts = []; desv.length = 0; bad = 0; c.splice(0, 3, ...cOk); lost = true; if (kfs.length) relocFor = 30 }

// --- vistas guardadas para reencontrar la mesa (seccion 10) ---
// Descriptores ORB de los puntos seguidos + su lugar en la mesa. El angulo de cada descriptor es la direccion en la imagen del
// eje x de la mesa (sale del sensor, no depende de donde este el celular), asi el mismo punto da el mismo descriptor aunque
// el celular este girado.
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
// punto mas cercano a todas las rectas P + s*d: la posicion del celular si se conoce su orientacion (el sensor)
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
  const t0 = performance.now(), {bmp, t, id} = m, w = m.gray ? m.gw : bmp.width, h = m.gray ? m.gh : bmp.height, st = {}
  const qF = qmul(qb, m.q) // orientacion del sensor con su error ya conocido descontado
  if (w !== tw || h !== th) { // primer cuadro o el celular cambio de orientacion: se empieza de cero
    tw = w; th = h; pts = []; kfs = []; desv.length = 0
    focal = (Math.max(w, h) / 2) / Math.tan(fov * Math.PI / 360)
    ctx = new OffscreenCanvas(w, h).getContext('2d', {willReadFrequently: true})
    prevPyr = new jsfeat.pyramid_t(LEVELS); currPyr = new jsfeat.pyramid_t(LEVELS)
    prevPyr.allocate(w, h, jsfeat.U8C1_t); currPyr.allocate(w, h, jsfeat.U8C1_t)
    blur = new jsfeat.matrix_t(w, h, jsfeat.U8C1_t)
    corners = Array.from({length: (w * h) >> 2}, () => new jsfeat.keypoint_t())
  }
  const ta = performance.now()
  if (m.gray) currPyr.data[0].data.set(m.gray) // ya viene en gris desde ar.html (VideoFrame)
  else { ctx.drawImage(bmp, 0, 0); bmp.close(); jsfeat.imgproc.grayscale(ctx.getImageData(0, 0, w, h).data, w, h, currPyr.data[0]) }
  const tb = performance.now()
  const tc = performance.now()
  currPyr.build(currPyr.data[0], true)
  const t1 = performance.now(); st.img = t1 - t0; st.gd = tb - ta; st.gr = 0; st.py = t1 - tc
  // un cuadro atrasado (el celular ocupado) no es motivo para tirar los puntos: se buscan mas lejos (la piramide y la pose
  // prevista lo cubren). Solo una pausa larga (la pagina en segundo plano) invalida lo que se sabia de la imagen anterior
  const dt = lastT ? (t - lastT) / 1000 : 0
  if (dt > 1.5) lose()
  // tras un tiron (ar.html, bruscoHasta) los puntos viejos ya no estan donde se los dejo, y un mapa nuevo armado desde el
  // sensor sacudido quedaba ladeado o corrido para siempre: se busca la mesa en las vistas guardadas y el plato no se muestra hasta
  // encontrarla (o hasta rendirse, ~60 cuadros, y quedarse con el mapa nuevo)
  if (m.brusco) { lose(); flowPrev = [0, 0]; if (kfs.length) { relocFor = 60; trasBrusco = true } }
  lastT = t
  let qc = [0, 0, 0, 1], valid = false, reloc = false, flow = 0
  if (pts.length) {
    // donde deberia verse cada punto: con giroscopio, la orientacion nueva del sensor y la ultima posicion; sin giroscopio (su
    // orientacion llega tarde y temblando), el mismo desplazamiento en la imagen que en el cuadro anterior
    const qp = m.gyro || !qvPrev ? qF : null, before = pts.length, fl = [], keep = []
    for (const p of pts) {
      let gx = p.x + flowPrev[0], gy = p.y + flowPrev[1]
      if (qp) {
        const v = qrot(qinv(qp), [p.P[0] - c[0], p.P[1] - c[1], p.P[2] - c[2]])
        if (v[2] < -0.01) { gx = tw / 2 + focal * v[0] / -v[2]; gy = th / 2 - focal * v[1] / -v[2] }
      }
      const r = lk(p.x, p.y, gx, gy)
      if (!r || r[2] < 0.65) continue // en una mesa oscura y lisa el ruido de la camara ya baja la correlacion a ~0.8
      fl.push([r[0] - p.x, r[1] - p.y]); p.x = r[0]; p.y = r[1]; p.b = camRay(p.x, p.y); keep.push(p)
    }
    pts = keep
    if (fl.length) { // px que se movio la mesa en la imagen (la prueba de que el celular se movio) y hacia donde
      // el tamano se mide punto a punto: al acercarse los puntos se separan en todas direcciones y el promedio daria cero
      flow = median(fl.map((f) => Math.hypot(f[0], f[1]))); flowPrev = [median(fl.map((f) => f[0])), median(fl.map((f) => f[1]))]
    }
    st.lk = performance.now() - t1
    if (pts.length < before / 3 || pts.length < 8) { lose(); flowPrev = [0, 0] } else {
      qc = solvePose(qF)
      valid = plausible(qc, t)
      if (valid) { pts = pts.filter((p) => p.e < 4); bad = 0 }
      else { c.splice(0, 3, ...cOk); qc = [0, 0, 0, 1]; if (++bad >= 3) lose() } // seguimiento degradado: se mantiene la pose buena
    }
  }
  const t2 = performance.now(); st.pose = t2 - t1 - (st.lk || 0)
  // recien perdida la mesa: se busca en las vistas guardadas, por si el celular se movio mientras no se la veia
  if (relocFor > 0 && relocFor-- % 3 === 0) { const r = relocalize(qF, t); if (r) { qc = r; valid = reloc = true; relocFor = 0 } }
  if (relocFor <= 0) trasBrusco = false
  const t3 = performance.now(); st.reloc = t3 - t2
  let qv = qmul(qc, qF) // orientacion corregida de este cuadro
  if (valid) { qv = aPlomo(qv, m.q, t, dt); cOk = c.slice(); tOk = t; qb = soloGiro(qmul(qv, qinv(m.q))); qvPrev = qv }
  // mientras se busca la mesa en las vistas guardadas no se guardan vistas nuevas: podrian estar corridas respecto al plato
  if (valid && ++frameNo % 5 === 0 && relocFor <= 0) addKeyframe(qv)
  const t4 = performance.now(); st.kf = t4 - t3
  // puntos nuevos en las zonas de la imagen que se quedaron sin puntos, solo desde una pose validada (o la ultima buena si no
  // queda ninguno); buscar esquinas recorre toda la imagen, por eso solo cada 3 cuadros salvo que queden muy pocos
  // sin puntos, el mapa nuevo sale de la orientacion del sensor: no mientras la mano lo sacude (m.calma), saldria ladeado
  if ((valid || (!pts.length && m.calma !== false)) && pts.length < maxp * 0.6 && (pts.length < 15 || frameNo % 3 === 0)) {
    const fromEmpty = !pts.length
    thr = pts.length < maxp * 0.4 ? Math.max(4, thr - 1) : Math.min(20, thr + 1) // mesa lisa: se aceptan esquinas mas suaves
    jsfeat.fast_corners.set_threshold(thr)
    const n = jsfeat.fast_corners.detect(currPyr.data[0], corners, 8), used = new Set(pts.map(cellOf)), best = new Map()
    for (let i = 0; i < n; i++) { const k = corners[i], key = cellOf(k); if (!used.has(key) && !(best.get(key)?.score >= k.score)) best.set(key, k) }
    for (const k of [...best.values()].sort((a, b) => b.score - a.score)) {
      if (pts.length >= maxp) break
      const b = camRay(k.x, k.y), d = qrot(qv, b)
      if (d[1] > -0.2) continue // en el horizonte o arriba: no es la mesa
      const s = -c[1] / d[1], P = [c[0] + d[0] * s, 0, c[2] + d[2] * s]
      if (s < 2) pts.push({x: k.x, y: k.y, b, d, P}) // mas lejos suele ser el piso o la pared
    }
    if (fromEmpty && pts.length && lost && kfs.length) { relocFor = Math.max(relocFor, 30); lost = false } // la mesa volvio a verse tras perderla
  }
  st.seed = performance.now() - t4
  ;[prevPyr, currPyr] = [currPyr, prevPyr]
  const ms = performance.now() - t0
  // presupuesto: ~20 ms por cuadro deja seguir a 30 cuadros/s aunque el celular haga otras cosas; mas puntos solo si sobra
  msAvg = msAvg ? msAvg * 0.9 + ms * 0.1 : ms
  if (frameNo % 10 === 0) maxp = msAvg > 20 ? Math.max(30, maxp - 5) : msAvg < 10 ? Math.min(80, maxp + 5) : maxp
  const state = valid ? 'seguimiento' : bad ? 'degradado' : relocFor > 0 ? 'relocalizando' : 'perdido'
  postMessage({id, tracking: valid, reloc, state, t, dt, flow, c, qc: qb, qv, n: pts.length, kf: kfs.length, ms, st, maxp, buscando: trasBrusco,
    // ?debug: el inicio de la fila 3 del cuadro (las pruebas automaticas leen ahi el numero de cuadro)
    ...(m.debug && {strip: Array.from(prevPyr.data[0].data.subarray(3 * w, 3 * w + 60))})})
}
