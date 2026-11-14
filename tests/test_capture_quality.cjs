const {test}=require('node:test');
const assert=require('node:assert/strict');
const {analyze,assess,difference,CaptureState}=require('../captura/calidad.js');
function frame(value,pattern=false){const a=new Uint8ClampedArray(320*240*4);for(let y=0;y<240;y++)for(let x=0;x<320;x++){const i=(y*320+x)*4,v=pattern?80+((Math.floor(x/4)+Math.floor(y/4))%2)*100:value;a[i]=a[i+1]=a[i+2]=v;a[i+3]=255;}return analyze(a,320,240);}
test('requiere al menos 1000ms continuos antes de disparar',()=>{const s=new CaptureState();s.resume();for(let t=0;t<1000;t+=100)assert.equal(s.tick(t,true),false);assert.equal(s.tick(1000,true),true);assert.equal(s.state,'CAPTURING');assert.equal(s.tick(1100,true),false);});
test('movimiento reinicia el segundo completo',()=>{const s=new CaptureState();s.resume();for(let t=0;t<=800;t+=100)s.tick(t,true);s.tick(900,false);for(let t=1000;t<2000;t+=100)assert.equal(s.tick(t,true),false);assert.equal(s.tick(2000,true),true);});
test('salto de muestras no cuenta como estabilidad',()=>{const s=new CaptureState();s.resume();s.tick(0,true);s.tick(200,true);assert.equal(s.tick(1500,true),false);assert.equal(s.progress,0);});
test('foto rechazada no completa un objetivo',()=>{const s=new CaptureState();s.resume();s.state='VALIDATING';const t=s.target();s.result(false,{id:'bad'});assert.equal(s.accepted.size,0);assert.deepEqual(s.target(),t);});
test('solo validación aceptada cambia recorrido y repetición lo reabre',()=>{const s=new CaptureState(2,3);s.state='VALIDATING';s.result(true,{id:1});s.state='VALIDATING';s.result(true,{id:2});assert.deepEqual(s.target(),{ring:1,position:0});s.repeat();assert.equal(s.accepted.size,1);assert.deepEqual(s.target(),{ring:0,position:1});});
test('pausa y continuación reinician estabilidad',()=>{const s=new CaptureState();s.resume();s.tick(0,true);s.tick(200,true);s.pause();assert.equal(s.tick(1500,true),false);s.resume();assert.equal(s.tick(2000,true),false);});
test('completa exactamente todos los objetivos aceptados',()=>{const s=new CaptureState(2,3);for(let i=0;i<6;i++){s.state='VALIDATING';s.result(true,{id:i});}assert.equal(s.target(),null);assert.equal(s.state,'COMPLETE');});
test('rechaza escenas negras, quemadas y lisas',()=>{assert.match(assess(frame(5)),/luz/);assert.match(assess(frame(253)),/luz/);assert.match(assess(frame(125)),/encuadre/);});
test('textura expuesta produce varias métricas útiles',()=>{const m=frame(0,true);assert.equal(assess(m),null);assert.ok(m.sharpness>100);assert.ok(m.contrast>20);assert.ok(m.edge>3);});
test('duplicado tolera cambios globales de brillo',()=>{const a=[30,80,120,60];assert.equal(difference(a,a.map(v=>v+20)),0);assert.ok(difference(a,[120,30,60,80])>20);});
test('no acepta fotografías fuera del estado de captura',()=>{const s=new CaptureState();assert.throws(()=>s.result(true,{}),/estado/);assert.equal(s.accepted.size,0);});
