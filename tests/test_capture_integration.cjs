/* Ejecuta las funciones reales del controlador con DOM y almacenamiento en memoria;
 * no pretende simular óptica, cámara física ni IndexedDB de un fabricante. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const Q=require('../captura/calidad.js');
function harness(dark=false,failStorage=false){
  const elements=new Map(), saved=[];
  function el(){return {textContent:'',value:'walk',src:'',style:{},checked:true,setAttribute(){},replaceChildren(){},appendChild(){},addEventListener(){}};}
  const pixels=new Uint8ClampedArray(320*240*4);
  for(let y=0;y<240;y++)for(let x=0;x<320;x++){let i=(y*320+x)*4;const v=dark?5:80+((Math.floor(x/4)+Math.floor(y/4))%2)*100;pixels[i]=pixels[i+1]=pixels[i+2]=v;pixels[i+3]=255;}
  const document={getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id);},createElement(tag){const e=el();if(tag==='canvas')e.getContext=()=>({drawImage(){},getImageData:()=>({data:pixels})});return e;},createElementNS(){return el();}};
  const ctx=vm.createContext({ScanQuality:Q,document,window:{},addEventListener(){},URL:{createObjectURL:()=> 'blob:original',revokeObjectURL(){}},setTimeout(){},navigator:{},performance:{now:()=>0},createImageBitmap:async()=>({width:3000,height:2000,close(){}}),Blob,console});
  vm.runInContext(fs.readFileSync('captura/capturador.js','utf8').replace('init().then(loop);',''),ctx);
  ctx.saved=saved;ctx.failStorage=failStorage;
  vm.runInContext(`session='plato_20261111_090000';currentRing=0;request=async(store,mode,action)=>{if(failStorage)throw Error('QuotaExceededError');return action({add:record=>saved.push(record)});};`,ctx);
  return {ctx,saved,run:code=>vm.runInContext(code,ctx)};
}
test('controlador archiva foto rechazada y no avanza',async()=>{const h=harness(true);await h.run("storePhoto(new Blob(['original bytes'],{type:'image/jpeg'}),true)");assert.equal(h.saved.length,1);assert.equal(h.saved[0].valid,false);assert.equal(h.run('engine.accepted.size'),0);assert.equal(await h.saved[0].blob.text(),'original bytes');});
test('controlador acepta solo después de guardar el original intacto',async()=>{const h=harness();await h.run("storePhoto(new Blob(['original bytes'],{type:'image/jpeg'}),true)");assert.equal(h.saved[0].valid,true);assert.equal(h.run('engine.accepted.size'),1);assert.equal(await h.saved[0].blob.text(),'original bytes');});
test('fallo de almacenamiento no completa objetivo',async()=>{const h=harness(false,true);await assert.rejects(h.run("storePhoto(new Blob(['bytes']),true)"),/QuotaExceeded/);assert.equal(h.run('engine.accepted.size'),0);});
test('original repetido se archiva pero no rellena otra posición',async()=>{const h=harness();await h.run("storePhoto(new Blob(['first']),true)");await h.run("storePhoto(new Blob(['second']),true)");assert.equal(h.saved.length,2);assert.equal(h.saved[1].valid,false);assert.match(h.saved[1].reason,/idéntica/);assert.equal(h.run('engine.accepted.size'),1);});
test('fotografía menor a 5MP no avanza',async()=>{const h=harness();vm.runInContext('createImageBitmap=async()=>({width:1920,height:1080,close(){}})',h.ctx);await h.run("storePhoto(new Blob(['video-size']),true)");assert.equal(h.run('engine.accepted.size'),0);assert.match(h.saved[0].reason,/Resolución insuficiente/);});
function live(h,drift=false){h.ctx.clock=0;h.ctx.drift=drift;h.run(`initialized=true;engine.resume();track={readyState:'live',muted:false};camera={takePhoto:async()=>new Blob(['native-original'],{type:'image/jpeg'})};$('video').videoWidth=1920;$('video').readyState=4;$('video').paused=false;performance.now=()=>clock;metrics=()=>({mean:120,contrast:40,sharpness:300,edge:12,dark:0,bright:0,signature:Array.from({length:192},(_,i)=>(i%2?1:-1)*(drift?clock/120:10))});`);}
test('bucle real no dispara durante deriva lenta acumulada',async()=>{const h=harness();live(h,true);for(let t=120;t<=2400;t+=120){h.ctx.clock=t;await h.run('loop()');}assert.equal(h.saved.length,0);assert.equal(h.run('engine.accepted.size'),0);});
test('bucle captura automáticamente tras 1000ms de imagen estable',async()=>{const h=harness();live(h);for(let t=120;t<=1200;t+=120){h.ctx.clock=t;await h.run('loop()');}assert.equal(h.saved.length,0);h.ctx.clock=1240;await h.run('loop()');assert.equal(h.saved.length,1);assert.equal(h.run('engine.accepted.size'),1);assert.equal(await h.saved[0].blob.text(),'native-original');});
test('un cambio de imagen desde el mismo rumbo no habilita el punto siguiente',()=>{
  const h=harness();
  h.run("engine.ringPlans[0]=34;engine.accepted.set('0:0',{heading:4,previewSignature:[0,100]});heading=4;headingTime=0;confirmed=true;");
  assert.match(h.run('positionCheck(engine.target(),{signature:[100,0]},100).message'),/Avanza/);
  h.run('heading=353.4;');
  assert.equal(h.run('positionCheck(engine.target(),{signature:[100,0]},100).message'),null);
});
test('sin brújula cada punto requiere confirmación y una vista distinta',()=>{
  const h=harness();
  h.run("engine.accepted.set('0:0',{previewSignature:[0,100]});");
  assert.match(h.run('positionCheck(engine.target(),{signature:[100,0]},100).message'),/confírmalo/);
  h.run('confirmed=true;');
  assert.match(h.run('positionCheck(engine.target(),{signature:[0,100]},100).message'),/casi igual/);
  assert.equal(h.run('positionCheck(engine.target(),{signature:[100,0]},100).message'),null);
});
test('tras 15 fotos altas se puede pasar a diagonal, luego a baja y terminar',()=>{
  const h=harness();
  h.run(`db={}; const stages=new Map();
    globalThis.localStorage={setItem:(key,value)=>stages.set(key,value)};
    $('process').focus=()=>{};
    engine.activeRing=0;engine.ringPlans[0]=15;
    for(let i=0;i<15;i++) engine.accepted.set('0:'+i,{ring:0,position:i});
    $('next').onclick();`);
  assert.equal(h.run('engine.target().ring'),1);
  assert.equal(h.run('engine.accepted.size'),15);
  h.run("$('next').onclick(); $('finish').onclick();");
  assert.equal(h.run('engine.target().ring'),2);
  assert.equal(h.run('engine.state'),'PAUSED');
  assert.equal(h.run("$('delivery').hidden"),false);
  assert.equal(h.run("JSON.parse(stages.get('guided-stage:'+session)).finished"),true);
});
test('la foto automática de menor resolución queda fuera de la reconstrucción',async()=>{
  const h=harness();
  await h.run("cameraInfo.requestedPhotoSettings={imageWidth:4000,imageHeight:3000};storePhoto(new Blob(['native']),false)");
  assert.equal(h.saved[0].valid,false);
  assert.match(h.saved[0].reason,/menos resolución/);
});
