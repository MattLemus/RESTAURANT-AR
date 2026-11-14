/* Métricas heurísticas, sin prometer detección de platos ni enfoque óptico. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ScanQuality = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function analyze(rgba, width, height) {
    const gray = new Float32Array(width * height);
    for (let i = 0; i < gray.length; i++) gray[i] = .299 * rgba[i*4] + .587 * rgba[i*4+1] + .114 * rgba[i*4+2];
    let sum=0, square=0, lap=0, lap2=0, edges=0, dark=0, bright=0, count=0;
    const signature=[];
    for (let y=1; y<height-1; y++) for (let x=1; x<width-1; x++) {
      if (((x-width/2)/(.43*width))**2 + ((y-height/2)/(.35*height))**2 > 1) continue;
      const i=y*width+x, v=gray[i], l=gray[i-1]+gray[i+1]+gray[i-width]+gray[i+width]-4*v;
      sum+=v; square+=v*v; lap+=l; lap2+=l*l; edges+=Math.abs(gray[i+1]-gray[i-1])+Math.abs(gray[i+width]-gray[i-width]);
      dark+=v<18; bright+=v>246; count++;
    }
    for(let y=0;y<12;y++) for(let x=0;x<16;x++) signature.push(gray[Math.floor((y+.5)*height/12)*width+Math.floor((x+.5)*width/16)]);
    const mean=sum/count;
    return {mean, contrast:Math.sqrt(Math.max(0,square/count-mean*mean)), sharpness:lap2/count-(lap/count)**2,
      edge:edges/count, dark:dark/count, bright:bright/count, signature};
  }
  function difference(a,b) {
    if (!a || !b || a.length!==b.length) return Infinity;
    const ma=a.reduce((s,v)=>s+v,0)/a.length, mb=b.reduce((s,v)=>s+v,0)/b.length;
    return a.reduce((s,v,i)=>s+Math.abs((v-ma)-(b[i]-mb)),0)/a.length;
  }
  function assess(m, reference=0) {
    if (m.mean<48 || m.dark>.48) return 'Necesitamos más luz';
    if (m.mean>218 || m.bright>.38) return 'Demasiada luz: evita reflejos y sol directo';
    if (m.contrast<10 || m.edge<2) return 'Acerca un poco el plato o corrige el encuadre';
    if (m.sharpness<Math.max(20,Math.min(100,reference*.48)) || m.edge<3) return 'Buscando enfoque';
    return null;
  }
  function cameraHeading(alpha, beta, gamma) {
    if (![alpha, beta, gamma].every(Number.isFinite)) return null;
    const [a, b, g] = [alpha, beta, gamma].map(value => value * Math.PI / 180);
    // Proyección horizontal del eje óptico. Cerca de la vertical el rumbo es ambiguo.
    const x = -Math.cos(a) * Math.sin(g) - Math.sin(a) * Math.sin(b) * Math.cos(g);
    const y = -Math.sin(a) * Math.sin(g) + Math.cos(a) * Math.sin(b) * Math.cos(g);
    if (Math.hypot(x, y) < .12) return null;
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }
  function angleDifference(a, b) { return ((a - b + 540) % 360) - 180; }
  function orbitTarget(heading, origin, position, total, previousHeading) {
    const expected = (origin - position * 360 / total + 360) % 360;
    const offset = angleDifference(heading, expected);
    const advanced = !Number.isFinite(previousHeading) || angleDifference(previousHeading, heading) >= 6;
    return { offset, ready: Math.abs(offset) <= 3.5 && advanced };
  }
  class CaptureState {
    constructor(total=34, rings=3) { this.total=total; this.rings=rings; this.accepted=new Map(); this.state='PAUSED'; this.reset(); }
    reset() { this.since=null; this.last=null; this.progress=0; }
    pause() { this.state='PAUSED'; this.reset(); }
    resume() { this.state='GUIDING'; this.reset(); }
    target() {
      const first = this.activeRing ?? 0;
      const end = this.activeRing == null ? this.rings : first + 1;
      for (let ring = first; ring < end; ring++) {
        for (let position = 0; position < (this.ringPlans?.[ring] ?? this.total); position++) {
          if (!this.accepted.has(`${ring}:${position}`)) return {ring, position};
        }
      }
      return null;
    }
    tick(now, ready) {
      if(!['GUIDING','STABILIZING'].includes(this.state)) return false;
      if(!ready || (this.last!==null && now-this.last>350)) { this.reset(); this.state='GUIDING'; if(!ready) return false; }
      this.last=now; if(this.since===null) this.since=now;
      this.state='STABILIZING'; this.progress=Math.min(1,(now-this.since)/1000);
      if(this.progress>=1) { this.state='CAPTURING'; return true; } return false;
    }
    result(valid, record) {
      if(!['CAPTURING','VALIDATING'].includes(this.state)) throw Error('Captura fuera de estado');
      if(valid) { const t=this.target(); if(!t) throw Error('Recorrido completo'); this.accepted.set(`${t.ring}:${t.position}`,record); }
      this.reset(); this.state=this.target() ? 'GUIDING':'COMPLETE';
    }
    repeat() { const keys=[...this.accepted.keys()]; if(keys.length) this.accepted.delete(keys[keys.length-1]); this.pause(); }
  }
  return {analyze,difference,assess,cameraHeading,orbitTarget,CaptureState};
});
