'use strict';
const $=id=>document.getElementById(id), Q=ScanQuality;
const zones=[{name:'Arriba',min:58,max:90,text:'Desde arriba, dejando ver todo el borde.'},{name:'Diagonal',min:34,max:57,text:'En diagonal, mostrando también los lados de la comida.'},{name:'A ras',min:10,max:33,text:'Cerca de la mesa, mostrando la pared del plato.'}];
const engine=new Q.CaptureState();
engine.ringPlans=[24,24,24];
let db, session, track, camera, photoSettings, cameraInfo={}, records=[], previous=null;
let sensorTime=0, tilt=null, rotation=0, busy=false, initialized=false, reference=0, stableBaseline=0;
let lastFrameTime=0, confirmed=false, currentRing=-1, wake, pauseAfterCapture=false, holdSignature=null;
let heading=null, headingTime=-Infinity, shotHeading=null;
let finished=false, sending=false, jobTimer;
function saveStage() {
  localStorage.setItem('guided-stage:'+session, JSON.stringify({ring:engine.activeRing, finished, plans:engine.ringPlans}));
}
function selectStage(ring) {
  engine.activeRing=ring;
  engine.pause();
  confirmed=false;
  holdSignature=null;
  stableBaseline=0;
  saveStage();
  render();
}
const canvas=document.createElement('canvas'); canvas.width=320; canvas.height=240;
const context=canvas.getContext('2d',{willReadFrequently:true});
const say=t=>$('msg').textContent=t;
function request(store,mode,action) { return new Promise((resolve,reject)=>{const tx=db.transaction(store,mode), r=action(tx.objectStore(store));tx.oncomplete=()=>resolve(r.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('No se pudo guardar'));}); }
async function openDB() {
  db=await new Promise((resolve,reject)=>{const r=indexedDB.open('restaurant-guided-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('photos',{keyPath:'id'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
  session=localStorage.getItem('guided-session');
  if(!session) {session='plato_'+new Date().toISOString().replace(/[-:]/g,'').replace('T','_').slice(0,15)+'_'+crypto.getRandomValues(new Uint32Array(1))[0].toString(16);localStorage.setItem('guided-session',session);}
  $('mode').value=localStorage.getItem('guided-mode:'+session)||'walk';
  // Un cursor evita cargar simultáneamente cientos de originales de varios MP.
  records=await new Promise((resolve,reject)=>{const rows=[],tx=db.transaction('photos','readonly'),r=tx.objectStore('photos').openCursor();r.onsuccess=()=>{const cursor=r.result;if(!cursor)return;const {blob,...record}=cursor.value;if(record.session===session)rows.push(record);cursor.continue();};tx.oncomplete=()=>resolve(rows.sort((a,b)=>a.sequence-b.sequence));tx.onerror=()=>reject(tx.error);});
  for(const r of records) if(r.valid && !r.superseded) engine.accepted.set(`${r.ring}:${r.position}`,r);
  let savedStage;
  try { savedStage=JSON.parse(localStorage.getItem('guided-stage:'+session)); } catch (_) {}
  engine.ringPlans=zones.map((_,ring)=>[15,24,34].includes(savedStage?.plans?.[ring])
    ? savedStage.plans[ring] : records.some(record=>record.ring===ring)?34:24);
  engine.activeRing=Number.isInteger(savedStage?.ring) && savedStage.ring>=0 && savedStage.ring<zones.length
    ? savedStage.ring : engine.target()?.ring ?? 2;
  finished=savedStage?.finished===true;
  saveStage();
  $('session').textContent=session;
  render();
}
function metrics(source) {context.drawImage(source,0,0,320,240);return Q.analyze(context.getImageData(0,0,320,240).data,320,240);}
function updateAngle(ring, now=performance.now()) {
  const zone=zones[ring];
  const sensed=$('useTilt').checked && tilt!==null && now-sensorTime<1500;
  const visual=['Casi desde arriba','Desde la diagonal','Casi a la altura de la mesa'][ring];
  const direction=sensed && tilt<zone.min ? 'Sube e inclina' : sensed && tilt>zone.max ? 'Baja el celular' : null;
  $('angleTitle').textContent=sensed ? direction || 'Buen ángulo' : visual;
  $('height').textContent=sensed ? `${Math.round(tilt)}° · objetivo ${zone.min}–${zone.max}°` : 'Guía visual';
  $('angle').setAttribute('data-ready',String(sensed && !direction));
  $('angleNeedle').setAttribute('transform',`rotate(-${sensed ? tilt : (zone.min+zone.max)/2},5,26)`);
  return direction;
}
function render() {
  const target=engine.target();
  const ring=engine.activeRing ?? target?.ring ?? 2;
  const zone=zones[ring];
  if(ring!==currentRing) {
    currentRing=ring;
    $('framing').checked=false;
    confirmed=false;
    engine.pause();
    say('Encuadra el plato y toca Empezar.');
  }
  const counts=zones.map((_,i)=>[...engine.accepted.values()].filter(r=>r.ring===i).length);
  $('zone').textContent=`${zone.name} · ${counts[ring]} fotos`;
  $('counter').textContent=`${engine.accepted.size} fotos aceptadas en esta sesión`;
  $('zones').replaceChildren(...zones.map((item,i)=>{
    const label=document.createElement('button');
    label.type='button';
    label.textContent=`${item.name} · ${counts[i]}`;
    label.className=i===ring?'active':'';
    label.setAttribute('aria-pressed',String(i===ring));
    label.disabled=finished || !db;
    label.onclick=()=>{
      if(!busy && !sending && !finished && i!==currentRing) selectStage(i);
    };
    return label;
  }));
  const radius=[113,87,58][ring];
  $('oval').setAttribute('ry',radius);
  $('dots').replaceChildren();
  const plan=engine.ringPlans[ring];
  for(let i=0;i<plan;i++) {
    const angle=i*2*Math.PI/plan-Math.PI/2;
    const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.setAttribute('cx',150+128*Math.cos(angle));
    dot.setAttribute('cy',200+(radius+12)*Math.sin(angle));
    dot.setAttribute('r',i===target?.position?'7':'2.5');
    dot.setAttribute('fill',engine.accepted.has(`${ring}:${i}`)?'#71f5ad':i===target?.position?'#fbbf24':'#93a69a');
    $('dots').appendChild(dot);
  }
  updateAngle(ring);
  $('hint').textContent=zone.text;
  $('confirm').hidden=true;
  $('orbitHint').textContent='';
  $('start').textContent=engine.state==='PAUSED'?(counts[ring]?'Continuar':'Empezar'):'Pausar';
  $('start').disabled=!initialized || !target || finished || sending;
  $('repeat').disabled=!engine.accepted.size || busy || finished;
  $('next').hidden=ring===zones.length-1;
  $('next').disabled=busy || finished || !db;
  $('next').textContent=ring===0?'Pasar a diagonal':'Pasar a ras del plato';
  $('plan').value=String(plan);
  $('plan').disabled=busy || sending || counts[ring]>0 || engine.state!=='PAUSED';
  $('finish').disabled=busy || !engine.accepted.size;
  $('captureControls').hidden=finished;
  $('delivery').hidden=!finished;
  $('coverage').textContent=counts.map((count,i)=>`${zones[i].name}: ${count}`).join(' · ')
    +(counts.some(count=>count===0)?' Faltan vistas en alguna altura y puede quedar incompleto de lado.':'');
  if(!target && !finished) say('Vuelta completa. Pasa a la siguiente altura o toca Listo.');
  if(finished) say('Captura terminada. Originales guardados en el teléfono.');
}
async function sensors() {
  const requests=[];
  if(typeof DeviceMotionEvent!=='undefined' && DeviceMotionEvent.requestPermission) requests.push(DeviceMotionEvent.requestPermission());
  if(typeof DeviceOrientationEvent!=='undefined' && DeviceOrientationEvent.requestPermission) requests.push(DeviceOrientationEvent.requestPermission(true));
  await Promise.allSettled(requests);
}
function updateHeading(event) {
  if (!event.absolute && event.type!=='deviceorientationabsolute') return;
  heading=Q.cameraHeading(event.alpha,event.beta,event.gamma);
  headingTime=performance.now();
}
addEventListener('deviceorientationabsolute',updateHeading);
addEventListener('deviceorientation',updateHeading);
function currentHeading(now) {
  return $('useCompass').checked && $('mode').value==='walk' && now-headingTime<1500 ? heading : null;
}
function positionCheck(target, preview, now) {
  if (!target.position) return {message:null, hint:'Encuadra el plato para empezar esta vuelta.', confirm:false};
  const origin=engine.accepted.get(`${target.ring}:0`);
  const prior=engine.accepted.get(`${target.ring}:${target.position-1}`);
  const angle=currentHeading(now);
  const hasCompass=Number.isFinite(angle) && Number.isFinite(origin?.heading);
  const hint=$('mode').value==='walk'?'↻ Da un paso en sentido horario.':'↻ Gira la base y retira la mano.';
  if (hasCompass) {
    const result=Q.orbitTarget(angle,origin.heading,target.position,engine.ringPlans[target.ring],prior?.heading);
    if (!result.ready) {
      const direction=result.offset < -3.5 ? 'Retrocede un poco.' : '↻ Avanza alrededor del plato.';
      return {message:direction,hint:direction,confirm:false};
    }
  } else if (!confirmed) {
    return {message:'Cambia de posición y confírmalo en la cámara.',hint,confirm:true};
  }
  // Compara vistas previas con el mismo encuadre de cámara, no un JPEG con el video.
  if (prior?.previewSignature && Q.difference(preview.signature,prior.previewSignature)<4) {
    return {message:'La vista sigue casi igual. Cambia de ángulo.',hint,confirm:!hasCompass};
  }
  return {message:null,hint:'En el objetivo. Mantén quieto el celular.',confirm:!hasCompass};
}
addEventListener('devicemotion',e=>{const g=e.accelerationIncludingGravity;if(!g || g.z==null)return;const angle=Math.asin(Math.min(1,Math.abs(g.z)/(Math.hypot(g.x,g.y,g.z)||1)))*180/Math.PI;tilt=tilt===null?angle:tilt*.7+angle*.3;sensorTime=performance.now();const r=e.rotationRate;rotation=r?Math.hypot(r.alpha||0,r.beta||0,r.gamma||0):0;});
async function init() {
  try {await openDB();$('destination').textContent='Los originales se guardan aquí hasta que los envíes.';
    if(!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw Error('La cámara necesita HTTPS o localhost. Usa USB con adb reverse, o importa fotos de la cámara nativa.');
    const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1440}}});
    track=stream.getVideoTracks()[0];$('video').srcObject=stream;await $('video').play();
    const fit=()=>{$('view').style.setProperty('--r',$('video').videoWidth/$('video').videoHeight);};fit();$('video').addEventListener('resize',fit);
    const caps=track.getCapabilities?.()||{}; const applied={};
    for(const key of ['focusMode','exposureMode','whiteBalanceMode']) if(caps[key]?.includes('continuous')) {try{await track.applyConstraints({advanced:[{[key]:'continuous'}]});applied[key]='continuous solicitado';}catch(e){applied[key]=e.message;}}
    cameraInfo={capabilities:caps,settings:track.getSettings(),applied};
    if(!window.ImageCapture) throw Error('Este navegador no permite fotos automáticas de alta resolución. Usa la cámara nativa y el botón Importar foto original.');
    camera=new ImageCapture(track);
    try {const caps=await camera.getPhotoCapabilities();cameraInfo.photoCapabilities=JSON.parse(JSON.stringify(caps));photoSettings={};if(caps.imageWidth?.max)photoSettings.imageWidth=caps.imageWidth.max;if(caps.imageHeight?.max)photoSettings.imageHeight=caps.imageHeight.max;cameraInfo.requestedPhotoSettings={...photoSettings};} catch(e){cameraInfo.photoCapabilitiesError=e.message;}
    initialized=true;$('camera').textContent=`Vista previa ${$('video').videoWidth}×${$('video').videoHeight}; resolución fotográfica pendiente de verificar`;
    if(finished) api(`/procesar?s=${session}`).then(watchJob).catch(()=>{});
    else say('Centra el plato en el óvalo y toca Empezar.');
  } catch(e) {$('camera').textContent=e.message;say('Modo manual con archivos originales. No se usarán cuadros de video.');} finally {$('start').disabled=!initialized || !engine.target();$('import').disabled=!db;}
}
function report() {return {version:1,session,mode:$('mode').value,camera:cameraInfo,limits:'Guía angular aproximada; no hay posición 3D ni detección semántica del plato. Enfoque y exposición evaluados por imagen, sin confirmación óptica del sensor.',accepted:engine.accepted.size,records};}
async function api(path, options={}) {
  let response;
  try {response=await fetch(path,{...options,cache:'no-store',signal:AbortSignal.timeout(25000)});}
  catch (_) {throw Error('No se pudo conectar con la PC');}
  if(!response.ok) {
    const error=await response.json().catch(()=>null);
    throw Error(error?.error || `La PC respondió con error ${response.status}`);
  }
  return response.json();
}
async function sendOriginals(processModel) {
  if(busy || sending || !engine.accepted.size) return;
  sending=true;
  engine.pause();
  $('process').disabled=true;
  $('resumeCapture').disabled=true;
  $('downloadModel').hidden=true;
  const status=$('jobStatus');
  try {
    await api('/subir/estado');
    const originals=records.filter(record=>record.valid && !record.superseded);
    for (const [index,record] of originals.entries()) {
      status.textContent=`Copiando originales a la PC · ${index+1}/${originals.length}`;
      $('destination').textContent=status.textContent;
      const saved=await request('photos','readonly',store=>store.get(record.id));
      if(!saved?.blob) throw Error(`Falta el original de la foto ${record.sequence}`);
      const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',await saved.blob.arrayBuffer()));
      const sha256=Array.from(digest,value=>value.toString(16).padStart(2,'0')).join('');
      const received=await api(`/subir?s=${session}&n=${record.sequence}`,{method:'POST',body:saved.blob});
      if(received.bytes!==saved.blob.size || received.sha256!==sha256) {
        throw Error(`La copia de la foto ${record.sequence} no coincide con el original`);
      }
      record.uploaded=true;
      await request('photos','readwrite',store=>store.put({...record,blob:saved.blob}));
    }
    await api(`/subir/manifest?s=${session}`,{method:'POST',body:JSON.stringify(report())});
    $('destination').textContent=`${originals.length} originales copiados a la PC.`;
    status.textContent=$('destination').textContent;
    if(processModel) {
      const job=await api(`/procesar?s=${session}`,{method:'POST',body:'{}'});
      await watchJob(job);
    }
  } catch(error) {
    status.textContent=`${error.message}. Comprueba el cable y ABRIR_ESCANER.bat. Puedes volver a enviar.`;
    $('destination').textContent=status.textContent;
  } finally {
    sending=false;
    $('process').disabled=false;
    $('resumeCapture').disabled=false;
    render();
  }
}
async function watchJob(job) {
  clearTimeout(jobTimer);
  $('jobStatus').textContent=job.message;
  $('downloadModel').hidden=job.state!=='done';
  if(job.state==='done') $('downloadModel').href=`/modelo?s=${session}`;
  if(job.state==='done' || job.state==='error') return;
  jobTimer=setTimeout(async()=>{
    try { await watchJob(await api(`/procesar?s=${session}`)); }
    catch (_) { $('jobStatus').textContent='La PC sigue trabajando. Conecta el cable y recarga para ver el estado.'; }
  },3000);
}
async function storePhoto(blob,fromManual=false) {
  const target=engine.target();if(!target) return;
  engine.state='VALIDATING';
  let image;try{image=await createImageBitmap(blob,{imageOrientation:'from-image'});}catch(e){throw Error('Archivo no decodificable. Importa JPEG o PNG original, sin HEIC.');}
  const m=metrics(image), width=image.width,height=image.height;image.close();
  let reason=Q.assess(m,reference);
  if(Math.max(width,height)<2400 || width*height<5_000_000)reason='Resolución insuficiente para este escaneo: usa fotografía nativa de al menos 5 MP y lado largo de 2400 px';
  if(records.some(r=>r.valid && !r.superseded && Q.difference(m.signature,r.metrics.signature)<1.8))reason='Fotografía casi idéntica: avanza a otro ángulo y repite esta posición';
  const preview=previous;
  if(!fromManual && preview && m.sharpness<preview.sharpness*.35)reason='La fotografía real perdió nitidez respecto a la vista previa';
  const requested=cameraInfo.requestedPhotoSettings;
  if(!fromManual && requested?.imageWidth && requested?.imageHeight && width*height<requested.imageWidth*requested.imageHeight) {
    reason='La cámara entregó menos resolución de la solicitada. Repite o importa una foto original en resolución máxima';
  }
  const sequence=Math.max(0,...records.map(r=>r.sequence))+1;
  const record={id:session+':'+sequence,session,sequence,ring:target.ring,position:target.position,valid:!reason,reason,width,height,bytes:blob.size,mime:blob.type,metrics:m,manual:fromManual,approximatePosition:true,positionConfirmed:confirmed,heading:fromManual?null:shotHeading,previewSignature:fromManual?null:preview?.signature,time:new Date().toISOString(),uploaded:false};
  // La transacción debe completar ANTES de aceptar el objetivo. El blob se guarda sin recodificar.
  await request('photos','readwrite',s=>s.add({...record,blob}));records.push(record);
  engine.result(!reason,record);
  if(!reason) {reference=reference?reference*.75+m.sharpness*.25:m.sharpness;confirmed=false;}
  const req=cameraInfo.requestedPhotoSettings;
  $('camera').textContent=`Foto real ${width}×${height} · ${(blob.size/1048576).toFixed(1)} MB · ${fromManual?'archivo original':'takePhoto'}${req?` · solicitado ${req.imageWidth||'?'}×${req.imageHeight||'?'}`:''}. Enfoque/exposición ópticos no confirmables por esta API.`;
  if(!fromManual && req?.imageWidth && req?.imageHeight && width*height<req.imageWidth*req.imageHeight*.8)$('camera').textContent+=' El navegador entregó menos píxeles de los solicitados. Compara con la cámara nativa; puedes pausar e importar el original.';
  const old=$('last').src;if(old.startsWith('blob:'))URL.revokeObjectURL(old);$('last').src=URL.createObjectURL(blob);$('last').hidden=false;
  say(reason?`Repite esta posición: ${reason}`:'Fotografía guardada. Avanza al próximo objetivo y detente.');
  render();
  if(reason) {engine.pause();$('start').textContent='Reintentar posición';say(`Repite esta posición: ${reason}. Corrige y pulsa Reintentar.`);}
}
async function capture() {
  busy=true;shotHeading=currentHeading(performance.now());say('Capturando automáticamente');
  try {let blob;try{blob=await camera.takePhoto(photoSettings);}catch(e){if(!photoSettings)throw e;photoSettings=undefined;cameraInfo.requestRetry=e.message;blob=await camera.takePhoto();}await storePhoto(blob);}
  catch(e){engine.pause();say(`No se avanzó: ${e.message}. Puedes reintentar o importar una foto nativa.`);}
  finally {busy=false;previous=null;stableBaseline=0;holdSignature=null;engine.reset();if(pauseAfterCapture){engine.pause();pauseAfterCapture=false;}render();}
}
async function loop() {
  try {
    if(initialized && engine.activeRing!=null && !document.hidden) updateAngle(engine.activeRing);
    if(!initialized || busy || document.hidden || !['GUIDING','STABILIZING'].includes(engine.state))return;
    const now=performance.now();if(!$('video').videoWidth)return;
    if($('video').paused || $('video').readyState<2 || track.readyState!=='live' || track.muted){engine.tick(now,false);say('Cámara detenida: vuelve a abrirla antes de continuar.');return;}
    const m=metrics($('video')), gap=now-lastFrameTime;lastFrameTime=now;
    const delta=Q.difference(m.signature,previous?.signature);previous=m;
    const t=engine.target();if(!t)return;const sensor=tilt!==null && now-sensorTime<1500;
    const anglePrompt=updateAngle(t.ring,now);
    let reason=Q.assess(m,reference);
    if(!reason && !$('framing').checked)reason='Confirma que el plato completo ocupa el óvalo';
    if(!reason && anglePrompt)reason=anglePrompt;
    const position=positionCheck(t,m,now);
    $('confirm').hidden=!position.confirm || Boolean(reason);
    $('orbitHint').textContent=reason ? '' : position.hint;
    if(!reason)reason=position.message;
    if(!reason && (delta>4 || (sensor && rotation>8) || gap>350))reason='Mantén el celular quieto';
    if(!reason && holdSignature && Q.difference(m.signature,holdSignature)>5)reason='Mantén el celular quieto';
    if(!reason && !holdSignature)holdSignature=m.signature;
    if(!reason && !stableBaseline)stableBaseline=m.sharpness;
    if(!reason && m.sharpness<stableBaseline*.65)reason='Buscando enfoque';
    if(reason){stableBaseline=0;holdSignature=null;}
    const fire=engine.tick(now,!reason);
    $('stability').value=engine.progress;$('quality').textContent=`Luz ${Math.round(m.mean)}/255 · detalle ${Math.round(m.sharpness)} · ${reason||'Posición lista'}`;
    say(reason||'Posición lista. Mantén el celular quieto un segundo.');
    if(fire)await capture();
  } catch(e){engine.pause();say('Análisis detenido: '+e.message);} finally {setTimeout(loop,120);}
}
$('start').onclick=async()=>{if(sending || finished)return;if(busy){pauseAfterCapture=true;say('Se pausará al terminar de guardar la fotografía en curso.');return;}await sensors();holdSignature=null;stableBaseline=0;if(engine.state==='PAUSED'){engine.resume();previous=null;lastFrameTime=0;try{wake=await navigator.wakeLock?.request('screen');}catch(e){/* opcional */}}else engine.pause();render();};
$('confirm').onclick=()=>{if(busy)return;confirmed=true;engine.reset();say('Posición confirmada. Mantén el celular quieto.');};
$('mode').onchange=()=>{if(busy || engine.accepted.size){$('mode').value=localStorage.getItem('guided-mode:'+session)||'walk';say('Para cambiar entre caminar y base giratoria, crea una sesión nueva.');return;}localStorage.setItem('guided-mode:'+session,$('mode').value);engine.pause();render();};
async function reopen(r){if(busy || sending || finished || !r || r.superseded)return;busy=true;engine.pause();try{const saved=await request('photos','readonly',s=>s.get(r.id));saved.superseded=true;await request('photos','readwrite',s=>s.put(saved));r.superseded=true;engine.accepted.delete(`${r.ring}:${r.position}`);selectStage(r.ring);say('Objetivo reabierto. El original anterior se conserva. Regresa a esa posición y continúa.');}catch(e){say('No se pudo reabrir o sincronizar: '+e.message);}finally{busy=false;render();}}
$('repeat').onclick=()=>reopen([...engine.accepted.values()].at(-1));
$('import').onclick=()=>{if(busy)return;engine.pause();$('file').click();};
$('file').onchange=async e=>{const file=e.target.files[0];if(!file||busy||sending||finished)return;busy=true;try{await storePhoto(file,true);engine.pause();}catch(e){engine.pause();say(e.message);}finally{busy=false;e.target.value='';render();}};
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
$('manifest').onclick=()=>download(new Blob([JSON.stringify(report(),null,2)],{type:'application/json'}),session+'_informe.json');
$('resend').onclick=()=>sendOriginals(false);
$('process').onclick=()=>sendOriginals(true);
$('plan').onchange=()=>{
  const plan=Number($('plan').value);
  if(![15,24,34].includes(plan) || $('plan').disabled) return;
  engine.ringPlans[engine.activeRing]=plan;
  saveStage();
  render();
};
$('next').onclick=()=>{
  if(busy || sending || finished || engine.activeRing>=zones.length-1) return;
  selectStage(engine.activeRing+1);
};
$('finish').onclick=()=>{
  if(busy || sending || !engine.accepted.size) return;
  finished=true;
  engine.pause();
  saveStage();
  render();
  $('process').focus();
};
$('resumeCapture').onclick=()=>{
  if(sending) return;
  finished=false;
  selectStage(engine.activeRing);
  if(engine.target()) say('Encuadra el plato y toca Continuar para tomar más fotos.');
};
$('review').onclick=async()=>{if(busy)return;engine.pause();$('gallery').replaceChildren();for(const r of records){const row=document.createElement('div'),label=document.createElement('p');label.textContent=`${r.sequence}: ${zones[r.ring].name} ${r.position+1} · ${r.superseded?'repetida':r.valid?'válida':'rechazada'} · ${r.width}×${r.height}`;row.appendChild(label);const view=document.createElement('button');view.textContent='Ver original';view.onclick=async()=>{const saved=await request('photos','readonly',s=>s.get(r.id)),img=$('reviewImage');if(img.src.startsWith('blob:'))URL.revokeObjectURL(img.src);img.src=URL.createObjectURL(saved.blob);img.hidden=false;say(r.reason||'Revisa el borde y los detalles de la comida.');};row.appendChild(view);const b=document.createElement('button');b.textContent='Descargar';b.onclick=async()=>{const saved=await request('photos','readonly',s=>s.get(r.id));download(saved.blob,`${session}_${String(r.sequence).padStart(3,'0')}.${saved.blob.type==='image/png'?'png':'jpg'}`);};row.appendChild(b);if(r.valid&&!r.superseded){const repeat=document.createElement('button');repeat.textContent='Repetir posición';repeat.onclick=()=>reopen(r);row.appendChild(repeat);}$('gallery').appendChild(row);}render();};
$('new').onclick=()=>{if(busy||sending)return;if(confirm('¿Crear otra sesión? La anterior seguirá en el navegador y en la PC. Descarga su informe antes de continuar.')){localStorage.removeItem('guided-session');location.reload();}};
addEventListener('visibilitychange',()=>{if(document.hidden){if(busy)pauseAfterCapture=true;else engine.pause();}render();});
addEventListener('beforeunload',()=>{track?.stop();wake?.release();});
async function prepareOffline() {
  const badge=$('offline');
  try {
    if(!navigator.serviceWorker) throw Error();
    await navigator.serviceWorker.register('captura-offline.js');
    await navigator.serviceWorker.ready;
    const update=()=>{
      if(!navigator.serviceWorker.controller) return;
      badge.textContent='Captura sin cable lista';
      badge.className='ready';
    };
    navigator.serviceWorker.addEventListener('controllerchange',update);
    update();
    navigator.storage?.persist?.().catch(()=>{});
  } catch (_) {badge.textContent='Mantén esta pestaña abierta para capturar sin cable';}
}
init().then(loop);
prepareOffline();
if(window.addEventListener) window.addEventListener('online',()=>{
  if(finished && session) api(`/procesar?s=${session}`).then(watchJob).catch(()=>{});
});
