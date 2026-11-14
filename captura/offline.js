'use strict';
const cacheName='restaurant-capture-v3';
const shell=['/capturar.html','/captura/capturador.css?v=3','/captura/calidad.js?v=3','/captura/capturador.js?v=3'];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(cacheName).then(cache=>cache.addAll(shell.map(url=>new Request(url,{cache:'reload'})))).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET') return;
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin) return;
  const resource=url.pathname==='/capturar.html'?url.pathname:url.pathname+url.search;
  if(!shell.includes(resource)) return;
  event.respondWith(caches.open(cacheName).then(async cache=>{
    if(url.pathname!=='/capturar.html') {
      const asset=await cache.match(resource);
      if(asset) return asset;
    }
    try {return await fetch(event.request);}
    catch(error) {const saved=await cache.match(resource);if(saved)return saved;throw error;}
  }));
});
