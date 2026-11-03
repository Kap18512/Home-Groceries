'use strict';
/* ---------- dates ---------- */
let T = startOfToday();
function startOfToday(){const d=new Date();d.setHours(0,0,0,0);return d}
const addD=(d,n)=>{const x=new Date(d);x.setDate(x.getDate()+n);return x};
const diff=(a,b)=>Math.round((a-b)/86400000);
const iso=d=>{const x=new Date(d);return x.getFullYear()+'-'+String(x.getMonth()+1).padStart(2,'0')+'-'+String(x.getDate()).padStart(2,'0')};
const parseISO=s=>{const[a,b,c]=s.split('-').map(Number);return new Date(a,b-1,c)};
const fmtD=d=>d.toLocaleDateString('en-US',{month:'short',day:'numeric'});
const fmtMY=d=>d.toLocaleDateString('en-US',{month:'short',year:'numeric'});
const fmtTS=s=>{const d=new Date(s.replace(' ','T')+'Z');return isNaN(d)?'':fmtD(d)};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const reEsc=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
const plural=(n,w)=>n+' '+w+(n===1?'':'s');
const $=s=>document.querySelector(s);

/* ---------- server data ---------- */
let CFG=null, USER=null, items=[], shopping=[];
const LEVELS={full:'Full',half:'Half',low:'Almost out'};
const locKey=l=>l==='Pantry'?'pantry':l==='Fridge'?'fridge':'freezer';
const S={tab:'search',q:'',loc:'all',cat:'all',status:'all',sort:'soon',store:'all'};

async function api(method,url,body){
  const r=await fetch(url,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  if(r.status===401&&url!=='/api/login'){showLogin();throw new Error('Please sign in again.')}
  if(!r.ok){
    let m='Something went wrong. Try again.';
    try{const j=await r.json();if(typeof j.detail==='string')m=j.detail;else if(Array.isArray(j.detail))m='Check the form: '+j.detail.map(d=>d.loc.slice(-1)[0]).join(', ')}catch(e){}
    throw new Error(m);
  }
  return r.status===204?null:r.json();
}
const hydrate=i=>({...i,bought:parseISO(i.bought),exp:parseISO(i.exp),opened:i.opened?parseISO(i.opened):null});
async function loadItems(){items=(await api('GET','/api/items')).map(hydrate)}
async function loadShopping(){shopping=await api('GET','/api/shopping')}
async function loadAll(){T=startOfToday();await Promise.all([loadItems(),loadShopping()])}

/* ---------- rules (from the server) ---------- */
function suggest(cat,loc,bought){const days=CFG.rules[cat][locKey(loc)];return{days,date:addD(bought,days)}}
function suggestNote(cat,loc,bought){
  const s=suggest(cat,loc,bought);
  if(!s.days)return{ok:false,date:bought,txt:cat+' is not recommended in '+loc+'. Pick another location.'};
  const span=s.days>=60?'about '+Math.round(s.days/30)+' months':plural(s.days,'day');
  return{ok:true,date:s.date,txt:'Suggested: '+span+' in '+loc.toLowerCase()+' (USDA-style rule), counted from the purchase date.'};
}

/* ---------- thumbnails (drawn stand-ins until product photos are added) ---------- */
function thumb(type,c){
  const w='rgba(255,255,255,.88)';
  const S={
    can:`<rect x="9" y="7" width="22" height="27" rx="3" fill="${c}"/><rect x="9" y="16" width="22" height="9" fill="${w}"/><rect x="9" y="5" width="22" height="3" rx="1.5" fill="rgba(0,0,0,.28)"/>`,
    tub:`<path d="M7 14h26l-3 20H10z" fill="${c}"/><rect x="6" y="10" width="28" height="5" rx="2" fill="rgba(0,0,0,.28)"/><rect x="12" y="21" width="16" height="7" rx="1" fill="${w}"/>`,
    bag:`<path d="M9 8h22l2 26H7z" fill="${c}"/><path d="M9 8l2 3 3-3 3 3 3-3 3 3 3-3 3 3" fill="none" stroke="rgba(0,0,0,.28)" stroke-width="1.5"/><rect x="12" y="17" width="16" height="9" rx="1" fill="${w}"/>`,
    block:`<rect x="5" y="14" width="30" height="16" rx="2" fill="${c}"/><rect x="10" y="18" width="20" height="8" rx="1" fill="${w}"/>`,
    carton:`<path d="M10 14l5-7h10l5 7v21H10z" fill="${c}"/><rect x="14" y="20" width="12" height="9" rx="1" fill="${w}"/>`,
    box:`<rect x="7" y="7" width="26" height="28" rx="2" fill="${c}"/><circle cx="20" cy="21" r="8" fill="${w}"/>`,
    loaf:`<path d="M5 24c0-9 6-14 15-14s15 5 15 14v7H5z" fill="${c}"/><path d="M12 15l3 6M20 13l3 7M28 15l2 6" stroke="rgba(255,255,255,.7)" stroke-width="2" stroke-linecap="round"/>`,
    jar:`<rect x="11" y="5" width="18" height="5" rx="1.5" fill="rgba(0,0,0,.3)"/><rect x="9" y="10" width="22" height="25" rx="5" fill="${c}"/><rect x="12" y="18" width="16" height="9" rx="1" fill="${w}"/>`,
    tray:`<rect x="4" y="16" width="32" height="16" rx="3" fill="${c}"/><rect x="7" y="19" width="26" height="10" rx="2" fill="${w}"/>`
  };
  return `<svg viewBox="0 0 40 40" aria-hidden="true">${S[type]||S.box}</svg>`;
}

/* ---------- helpers ---------- */
const useBy=i=>i.opened&&i.ol?new Date(Math.min(i.exp,addD(i.opened,i.ol))):i.exp;
function status(date){
  const d=diff(date,T);
  if(d<0)return{d,cls:'bad',txt:'Expired '+(-d)+'d ago'};
  if(d===0)return{d,cls:'bad',txt:'Use today'};
  if(d===1)return{d,cls:'warn',txt:'Tomorrow'};
  if(d<=3)return{d,cls:'warn',txt:d+' days'};
  if(d<=14)return{d,cls:'ok',txt:d+' days'};
  if(d<=60)return{d,cls:'ok',txt:Math.round(d/7)+' weeks'};
  return{d,cls:'calm',txt:fmtMY(date)};
}
const ago=d=>{const n=diff(T,d);return n<=0?'today':n+'d ago'};
function hl(text,q){
  const w=q.split(/\s+/).filter(Boolean);
  if(!w.length)return esc(text);
  const re=new RegExp('('+w.map(reEsc).join('|')+')','ig');
  return text.split(re).map((p,i)=>i%2?'<mark>'+esc(p)+'</mark>':esc(p)).join('');
}
function qtyBadge(i){
  if(i.mode==='count')return `<span class="qty num">×${i.qty}</span>`;
  const n={full:3,half:2,low:1}[i.level];
  return `<span class="meter ${i.level==='low'?'low':''}" title="${LEVELS[i.level]}" aria-label="${LEVELS[i.level]}">${[1,2,3].map(k=>`<i class="${k<=n?'on':''}"></i>`).join('')}</span>`;
}
function row(i,q){
  const st=status(useBy(i));
  return `<button class="row" data-act="open" data-id="${i.id}">
    <span class="thumb">${thumb(i.type,i.col)}</span>
    <span class="rmain"><span class="rname">${hl(i.name,q||'')}</span>
      <span class="rsub">${i.brand?hl(i.brand,q||'')+' · ':''}${esc(i.pkg||'')}</span>
      <span class="rtags"><span class="tag">${esc(i.loc)}</span>${i.opened?`<span class="tag open">Opened ${ago(i.opened)}</span>`:''}</span></span>
    <span class="rside">${qtyBadge(i)}<span class="pill ${st.cls}">${st.txt}</span></span></button>`;
}
function toast(msg,label,fn){
  const t=$('#toast');t.innerHTML=`<span>${esc(msg)}</span>${label?`<button id="toastBtn">${esc(label)}</button>`:''}`;t.hidden=false;
  if(label)$('#toastBtn').onclick=()=>{t.hidden=true;fn()};
  clearTimeout(toast.h);toast.h=setTimeout(()=>t.hidden=true,5000);
}
const fail=e=>{if(e.message!=='Please sign in again.')toast(e.message)};

/* ---------- views ---------- */
function filtered(){
  const q=S.q.trim().toLowerCase();
  let r=items.filter(i=>{
    if(S.loc!=='all'&&i.loc!==S.loc)return false;
    if(S.cat!=='all'&&i.cat!==S.cat)return false;
    if(S.status==='soon'&&diff(useBy(i),T)>3)return false;
    if(S.status==='opened'&&!i.opened)return false;
    if(S.status==='low'&&!(i.mode==='level'?i.level==='low':i.qty<=1&&i.loc==='Pantry'))return false;
    if(q){const hay=(i.name+' '+i.brand+' '+i.cat+' '+i.loc).toLowerCase();return q.split(/\s+/).every(w=>hay.includes(w))}
    return true;
  });
  if(S.sort==='soon')r.sort((a,b)=>useBy(a)-useBy(b));
  if(S.sort==='name')r.sort((a,b)=>a.name.localeCompare(b.name));
  if(S.sort==='new')r.sort((a,b)=>b.id-a.id);
  return r;
}
function summaryLine(){
  const ex=items.filter(i=>diff(useBy(i),T)<0).length;
  const soon=items.filter(i=>{const d=diff(useBy(i),T);return d>=0&&d<=3}).length;
  return `<b>${items.length}</b> items on hand${soon?` · <b class="warn">${soon} expiring within 3 days</b>`:''}${ex?` · <b class="bad">${ex} expired</b>`:''}`;
}
function renderSearch(){
  const chip=(k,v,label)=>`<button class="chip" data-act="filter" data-k="${k}" data-v="${esc(v)}" aria-pressed="${S[k]===v}">${esc(label)}</button>`;
  $('#view').innerHTML=`
    <div class="search"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      <input id="q" type="search" inputmode="search" autocomplete="off" placeholder="Do we have…  try “ricot” or “freezer”" value="${esc(S.q)}" aria-label="Search inventory"></div>
    <p class="hint" id="summary">${summaryLine()}</p>
    <div class="chiplabel">Status</div>
    <div class="chips">${chip('status','all','All')}${chip('status','soon','Expiring ≤ 3 days')}${chip('status','opened','Opened')}${chip('status','low','Running low')}</div>
    <div class="chiplabel">Location</div>
    <div class="chips">${chip('loc','all','Anywhere')}${CFG.locs.map(l=>chip('loc',l,l)).join('')}</div>
    <div class="chiplabel">Category</div>
    <div class="chips">${chip('cat','all','All categories')}${CFG.cats.map(c=>chip('cat',c,c)).join('')}</div>
    <div class="sortline"><span id="count"></span>
      <select id="sort" aria-label="Sort"><option value="soon">Use first</option><option value="name">Name A–Z</option><option value="new">Newest</option></select></div>
    <div class="list" id="results"></div>`;
  $('#sort').value=S.sort;renderResults();
}
function renderResults(){
  const r=filtered();const q=S.q.trim();
  const units=r.reduce((n,i)=>n+(i.mode==='count'?i.qty:0),0);
  $('#count').textContent=r.length+(r.length===1?' match':' matches')+(units?' · '+units+' counted units':'');
  if(!r.length){
    const filt=S.loc!=='all'||S.cat!=='all'||S.status!=='all';
    $('#results').innerHTML=`<div class="empty"><h3>${q?'None at home':(items.length?'Nothing matches':'Nothing here yet')}</h3>
      <p>${q?`No item matches “${esc(q)}”${filt?' with the current filters':''}. Safe to buy.`:(items.length?'Try clearing a filter.':'Tap the + button to add your first item.')}</p>
      <div class="btns">${q?`<button class="btn primary" data-act="list-add-q">Add to shopping list</button>`:''}${filt||q?`<button class="btn" data-act="clear">Clear filters</button>`:''}</div></div>`;
    return;
  }
  $('#results').innerHTML=r.map(i=>row(i,q)).join('');
}
function renderSoon(){
  const rows=items.slice().sort((a,b)=>useBy(a)-useBy(b));
  const G=[['Expired or use today',x=>x<=0],['Next 3 days',x=>x>0&&x<=3],['This week',x=>x>3&&x<=7],['Next two weeks',x=>x>7&&x<=14]];
  const first=rows.filter(i=>diff(useBy(i),T)<=3);
  const names=[...new Set(first.map(i=>i.name))];
  const dig=names.slice(0,4).join(', ')+(names.length>4?` and ${names.length-4} more`:'');
  $('#view').innerHTML=`
    <div class="alertprev"><div class="lbl">Daily alert preview · 8:00 AM</div>
      <p>${first.length?`<b>${plural(first.length,'item')} need${first.length===1?'s':''} attention.</b> ${esc(dig)}.`:'Nothing needs attention in the next 3 days.'}</p>
      <p class="note" style="margin:6px 0 0">Push notifications are not turned on yet. This shows what they will say.</p></div>
    ${G.map(([t,f])=>{const g=rows.filter(i=>f(diff(useBy(i),T)));return g.length?`<h2 class="sec">${t}<span>${g.length}</span></h2><div class="list">${g.map(i=>row(i,'')).join('')}</div>`:''}).join('')}`;
}
function renderLocs(){
  $('#view').innerHTML=`<h2 class="sec" style="margin-top:6px">Where things are</h2>
    <div class="locs">${CFG.locs.map(l=>{
      const g=items.filter(i=>i.loc===l);const soon=g.filter(i=>diff(useBy(i),T)<=3).length;
      return `<button class="loc" data-act="goloc" data-v="${esc(l)}"><b>${l}</b><span class="big num">${g.length}</span><small>${g.length===1?'item':'items'}${soon?` · <span style="color:var(--warn);font-weight:600">${soon} soon</span>`:''}</small></button>`}).join('')}</div>
    <h2 class="sec">By category</h2>
    <div class="chips" style="flex-wrap:wrap;overflow:visible">${CFG.cats.map(c=>{const n=items.filter(i=>i.cat===c).length;return n?`<button class="chip" data-act="gocat" data-v="${esc(c)}">${c} · ${n}</button>`:''}).join('')}</div>`;
}
const ANY='Any store';
function shopRow(s){
  const have=items.filter(i=>i.name.toLowerCase().includes(s.name.toLowerCase()));
  const sub=[s.note?esc(s.note):'',have.length?'<span style="color:var(--warn);font-weight:600">You already have '+esc(have[0].name)+' ('+esc(have[0].loc)+')</span>':''].filter(Boolean).join(' · ');
  return `<div class="row" style="grid-template-columns:minmax(0,1fr) auto"><span class="rmain"><span class="rname">${esc(s.name)}</span>
    ${sub?`<span class="rsub">${sub}</span>`:''}
    <span class="rtags"><button class="tag storetag" data-act="shop-edit" data-id="${s.id}" aria-label="Edit ${esc(s.name)}, store: ${esc(s.store||ANY)}">${esc(s.store||ANY)}</button></span></span>
    <button class="chip" data-act="list-del" data-id="${s.id}">Got it</button></div>`;
}
function renderList(){
  const stores=CFG.stores;
  const count=st=>shopping.filter(x=>x.store===st).length;
  const chip=(v,label)=>`<button class="chip" data-act="shop-filter" data-v="${esc(v)}" aria-pressed="${S.store===v}">${esc(label)}</button>`;
  const active=stores.filter(st=>count(st)>0||S.store===st);
  let body='';
  if(!shopping.length){
    body='<div class="empty"><h3>List is empty</h3><p>Add what you need and pick the store. Items you use up can be added here too.</p></div>';
  }else if(S.store==='all'){
    const groups=[...stores.filter(st=>count(st)),...(count('')?['']:[])];
    body=groups.map(st=>`<h2 class="sec">${esc(st||ANY)}<span>${count(st)}</span></h2><div class="list">${shopping.filter(x=>x.store===st).map(shopRow).join('')}</div>`).join('');
  }else{
    const mine=shopping.filter(x=>x.store===S.store),any=shopping.filter(x=>x.store==='');
    body=(mine.length?`<h2 class="sec">${esc(S.store)}<span>${mine.length}</span></h2><div class="list">${mine.map(shopRow).join('')}</div>`
      :`<div class="empty"><h3>Nothing for ${esc(S.store)}</h3><p>Pick that store when you add an item.</p></div>`)
      +(any.length?`<h2 class="sec">${ANY}<span>${any.length}</span></h2><div class="list">${any.map(shopRow).join('')}</div>`:'');
  }
  const addStore=S.store==='all'?'':S.store;
  $('#view').innerHTML=`<h2 class="sec" style="margin-top:6px">Shopping list<span>${plural(shopping.length,'item')}</span></h2>
    <form id="lform" style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px">
      <input id="litem" class="inp" style="margin:0" placeholder="Add an item" autocomplete="off" maxlength="120" aria-label="Item to add">
      <button class="btn primary" type="submit">Add</button>
      <select id="lstore" class="inp" style="margin:0;grid-column:1/-1" aria-label="Store">
        <option value="">${ANY}</option>${stores.map(st=>`<option ${st===addStore?'selected':''}>${esc(st)}</option>`).join('')}</select>
    </form>
    <div class="chips" style="margin-top:6px">${chip('all','All stores · '+shopping.length)}${active.map(st=>chip(st,st+' · '+count(st))).join('')}</div>
    <div style="margin-top:6px">${body}</div>`;
  $('#lform').onsubmit=async e=>{e.preventDefault();const v=$('#litem').value.trim();if(!v)return;
    try{await api('POST','/api/shopping',{name:v,store:$('#lstore').value});await loadShopping();renderList();badge()}catch(x){fail(x)}};
}
let SE=null;
function shopEdit(id){
  const x=shopping.find(i=>i.id===id);if(!x)return;
  SE={id,name:x.name,store:x.store,note:x.note};
  const stores=['',...CFG.stores];
  sheet(`<h3 style="font:700 21px var(--display);margin:0">Shopping item</h3>
    <label class="f">Name<input id="sh-name" maxlength="120" autocomplete="off" value="${esc(SE.name)}"></label>
    <div class="chiplabel">Buy at</div>
    <div class="locpick">${stores.map(st=>`<button class="chip" data-act="shop-store" data-v="${esc(st)}" aria-pressed="${SE.store===st}">${esc(st||ANY)}</button>`).join('')}</div>
    <label class="f">Note (optional)<input id="sh-note" maxlength="80" autocomplete="off" placeholder="e.g. BOGO this week" value="${esc(SE.note)}"></label>
    <p class="err" id="sherr" role="alert" style="color:var(--bad);margin:10px 2px 0;min-height:18px"></p>
    <div class="btns" style="margin-top:8px"><button class="btn" data-act="close">Cancel</button><button class="btn primary" data-act="shop-save">Save</button></div>
    <button class="btn block" data-act="list-del-sheet" style="margin-top:8px">Got it, remove from list</button>`);
}
async function removeShop(id){
  const x=shopping.find(i=>i.id===id);if(!x)return;
  try{
    await api('DELETE','/api/shopping/'+id);await loadShopping();
    if(S.tab==='list')renderList();badge();
    toast('Removed '+x.name,'Undo',async()=>{
      try{await api('POST','/api/shopping',{name:x.name,store:x.store,note:x.note});await loadShopping();if(S.tab==='list')renderList();badge()}catch(e){fail(e)}
    });
  }catch(e){fail(e)}
}
function badge(){const b=$('#listBadge');b.hidden=!shopping.length;b.textContent=shopping.length}
function render(){
  document.querySelectorAll('.tab[data-tab]').forEach(b=>{if(b.dataset.tab===S.tab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  ({search:renderSearch,soon:renderSoon,locs:renderLocs,list:renderList})[S.tab]();badge();
}

/* ---------- sheet ---------- */
function sheet(html){$('#sheetbody').innerHTML=html;$('#sheet').hidden=false;$('.panel').scrollTop=0}
function closeSheet(){$('#sheet').hidden=true;$('#sheetbody').innerHTML='';M=null;SE=null;render()}
const sheetOpen=()=>!$('#sheet').hidden;

function openItem(id){
  const i=items.find(x=>x.id===id);if(!i)return closeSheet();
  const ub=useBy(i),st=status(ub);
  const earlier=i.opened&&i.ol&&ub<i.exp;
  sheet(`
    <div class="shead"><span class="thumb">${thumb(i.type,i.col)}</span><div><h3>${esc(i.name)}</h3><p>${[i.brand,i.pkg,i.cat].filter(Boolean).map(esc).join(' · ')}</p></div></div>
    <div class="dates">
      <div><small>Purchased</small><b>${fmtD(i.bought)}</b></div>
      <div><small>Package date</small><b>${fmtD(i.exp)}</b></div>
      <div><small>Opened</small><b>${i.opened?fmtD(i.opened):'Not opened'}</b></div>
      <div><small>Location</small><b>${esc(i.loc)}</b></div>
      <div class="useby"><span><small>Use by</small><b>${fmtD(ub)}</b></span><span class="pill ${st.cls}">${st.txt}</span></div>
    </div>
    ${earlier?`<p class="note">Opened ${ago(i.opened)}: this item keeps ${plural(i.ol,'day')} after opening, which is sooner than the package date.</p>`:''}
    <div class="qrow"><span>${i.mode==='count'?'How many':'How much is left'}</span>
      ${i.mode==='count'?`<div class="stepper"><button data-act="dec" data-id="${i.id}" aria-label="One less">−</button><output class="num">${i.qty}</output><button data-act="inc" data-id="${i.id}" aria-label="One more">+</button></div>`
      :`<div class="seg" style="min-width:230px">${['full','half','low'].map(l=>`<button data-act="level" data-id="${i.id}" data-v="${l}" aria-pressed="${i.level===l}">${LEVELS[l]}</button>`).join('')}</div>`}</div>
    ${!i.opened?`<button class="btn block" data-act="opentoday" data-id="${i.id}" style="margin-bottom:8px">Mark opened today</button>`:''}
    <div class="chiplabel">Move to</div>
    <div class="locpick">${CFG.locs.map(l=>`<button class="chip" data-act="move" data-id="${i.id}" data-v="${esc(l)}" aria-pressed="${i.loc===l}">${l}</button>`).join('')}</div>
    <p class="note">Moving to a freezer resets the use-by date to the frozen shelf life. Moving back to the fridge starts a short thaw clock.</p>
    <div class="btns" style="margin-top:10px"><button class="btn" data-act="used" data-id="${i.id}">Used up</button><button class="btn danger" data-act="toss" data-id="${i.id}">Tossed</button></div>
    <div class="btns" style="margin-top:8px"><button class="btn" data-act="buyagain" data-id="${i.id}">Add to shopping list</button><button class="btn" data-act="edit" data-id="${i.id}">Edit details</button></div>
    <div class="chiplabel" style="margin-top:20px">History</div>
    <ul class="hist" id="hist"><li><span>Loading…</span></li></ul>`);
  api('GET',`/api/items/${id}/events`).then(ev=>{
    const h=$('#hist');if(!h||!sheetOpen())return;
    h.innerHTML=ev.slice(0,8).map(e=>`<li><time>${fmtTS(e.ts)}</time><span><b style="color:var(--ink)">${esc(e.action)}</b> ${esc(e.note)}<span class="who">· ${esc(e.who)}</span></span></li>`).join('');
  }).catch(()=>{});
}
async function itemAct(id,action,value){
  try{
    const res=await api('POST',`/api/items/${id}/action`,{action,value:value||null,today:iso(T)});
    await loadItems();
    return res;
  }catch(e){fail(e)}
}
async function removeItem(id,action){
  const it=items.find(x=>x.id===id);const res=await itemAct(id,action);
  if(!res)return;
  closeSheet();
  toast(it.name+(res.removed==='Used up'?' marked used up':' marked tossed'),'Undo',async()=>{
    try{await api('POST',`/api/items/${id}/action`,{action:'restore',today:iso(T)});await loadItems();render()}catch(e){fail(e)}
  });
}

/* ---------- add / edit ---------- */
let M=null;
function addMenu(){
  sheet(`<h3 style="font:700 21px var(--display);margin:0 0 4px">Add items</h3>
    <div class="menu">
      <button class="mbtn" data-act="manual"><span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg></span><span><b>Type it in</b><span>Name, dates, location</span></span></button>
    </div>
    <p class="note">Barcode and receipt scanning are planned for the next phase.</p>
    <div class="chiplabel">Buy again</div>
    <div class="again" id="again" style="margin-top:8px"><span class="note">Loading…</span></div>`);
  api('GET','/api/recent').then(r=>{
    const a=$('#again');if(!a)return;
    window._recent=r;
    a.innerHTML=r.length?r.map((p,k)=>`<button class="chip" data-act="again" data-k="${k}">${esc(p.name)}</button>`).join(''):'<span class="note">Items you add will show up here.</span>';
  }).catch(()=>{});
}
function newM(p){
  p=p||{};const cat=p.cat||CFG.cats[0];
  M={editId:null,name:p.name||'',brand:p.brand||'',cat,loc:p.loc||CFG.rules[cat].loc,mode:p.mode||'count',qty:1,level:'full',pkg:p.pkg||'',bought:T,exp:null,expEdited:false,opened:null};
  M.exp=suggest(M.cat,M.loc,M.bought).date;
}
function manual(){
  const edit=M.editId!=null;
  sheet(`<h3 style="font:700 21px var(--display);margin:0">${edit?'Edit details':'Type it in'}</h3>
    <label class="f">Name<input id="f-name" autocomplete="off" maxlength="120" placeholder="e.g. Sour cream" value="${esc(M.name)}"></label>
    <label class="f">Brand (optional)<input id="f-brand" autocomplete="off" maxlength="80" value="${esc(M.brand)}"></label>
    <div class="two"><label class="f">Category<select id="f-cat">${CFG.cats.map(c=>`<option ${c===M.cat?'selected':''}>${c}</option>`).join('')}</select></label>
    <label class="f">Location<select id="f-loc">${CFG.locs.map(c=>`<option ${c===M.loc?'selected':''}>${c}</option>`).join('')}</select></label></div>
    <label class="f">Package size<input id="f-pkg" autocomplete="off" maxlength="60" placeholder="8 oz, 1 lb, package" value="${esc(M.pkg)}"></label>
    <div class="chiplabel">Quantity</div>
    <div class="seg" style="margin-top:6px"><button data-act="mode" data-v="count" aria-pressed="${M.mode==='count'}">Count</button><button data-act="mode" data-v="level" aria-pressed="${M.mode==='level'}">Level (loaf, bag)</button></div>
    <div id="qtyblock">${qtyBlock()}</div>
    <div class="two"><label class="f">Purchased<input id="f-bought" type="date" max="${iso(T)}" value="${iso(M.bought)}"></label>
    <label class="f">Package date<input id="f-exp" type="date" value="${iso(M.exp)}"></label></div>
    <p class="note" id="sugg"></p>
    <label class="f">Opened (optional)<input id="f-opened" type="date" max="${iso(T)}" value="${M.opened?iso(M.opened):''}"></label>
    <p class="err" id="ferr" role="alert" style="color:var(--bad);margin:10px 2px 0;min-height:18px"></p>
    <div class="btns" style="margin-top:8px"><button class="btn" data-act="${edit?'reopen':'add'}" data-id="${M.editId||''}">Back</button><button class="btn primary" data-act="save-manual" id="savebtn">${edit?'Save changes':'Save item'}</button></div>`);
  updSugg();
}
function qtyBlock(){
  return M.mode==='count'
    ?`<div class="qrow"><span>How many</span><div class="stepper"><button data-act="m-dec" aria-label="One less">−</button><output class="num">${M.qty}</output><button data-act="m-inc" aria-label="One more">+</button></div></div>`
    :`<div class="qrow"><span>Level</span><div class="seg" style="min-width:230px">${['full','half','low'].map(l=>`<button data-act="m-level" data-v="${l}" aria-pressed="${M.level===l}">${LEVELS[l]}</button>`).join('')}</div></div>`;
}
function updSugg(){
  const s=suggestNote(M.cat,M.loc,M.bought);
  if(!M.expEdited&&s.ok){M.exp=s.date;const e=$('#f-exp');if(e)e.value=iso(M.exp)}
  const n=$('#sugg');if(n){n.textContent=s.txt+(M.expEdited?' You set the date yourself.':'');n.className='note'+(s.ok?' good':'')}
}
async function saveManual(){
  const err=$('#ferr');
  if(!M.name.trim()){err.textContent='Give the item a name.';$('#f-name').focus();return}
  if(!M.exp){err.textContent='Pick a package date.';return}
  const body={name:M.name.trim(),brand:M.brand.trim(),cat:M.cat,loc:M.loc,mode:M.mode,qty:M.qty,level:M.level,pkg:M.pkg.trim(),
    bought:iso(M.bought),exp:iso(M.exp),opened:M.opened?iso(M.opened):null};
  const btn=$('#savebtn');btn.disabled=true;
  try{
    const editing=M.editId;
    if(editing)await api('PUT','/api/items/'+editing,body);else await api('POST','/api/items',body);
    await loadItems();
    if(editing){M=null;openItem(editing);toast('Saved changes')}
    else{closeSheet();toast('Added '+body.name)}
  }catch(e){err.textContent=e.message;btn.disabled=false}
}

/* ---------- login ---------- */
async function showLogin(){
  $('#login').hidden=false;$('#who').innerHTML='';$('#qerr').textContent='';
  let names=[];
  try{const r=await fetch('/api/login-users');if(r.ok)names=await r.json()}catch(e){}
  $('#quick').innerHTML=names.map(u=>`<button class="btn primary block" data-act="quick-login" data-u="${esc(u.username)}">${esc(u.display)}</button>`).join('');
  $('#quickwrap').hidden=!names.length;$('#loginForm').hidden=names.length>0;
  if(!names.length)setTimeout(()=>$('#lu').focus(),50);
}
function showWho(){$('#who').innerHTML=`<span>${esc(USER.display)}</span><button data-act="logout">Sign out</button>`}
async function boot(){
  try{
    USER=await api('GET','/api/me');
  }catch(e){return showLogin()}
  $('#login').hidden=true;showWho();
  try{
    CFG=await api('GET','/api/config');
    await loadAll();
    render();
  }catch(e){$('#view').innerHTML=`<div class="empty"><h3>Could not load</h3><p>${esc(e.message)}</p><button class="btn primary" data-act="retry">Try again</button></div>`}
}
$('#loginForm').addEventListener('submit',async e=>{
  e.preventDefault();$('#lerr').textContent='';
  try{
    await api('POST','/api/login',{username:$('#lu').value.trim(),password:$('#lp').value});
    $('#lp').value='';boot();
  }catch(x){$('#lerr').textContent=x.message}
});

/* ---------- events ---------- */
const byId=b=>+b.dataset.id;
const H={
  tab:b=>{S.tab=b.dataset.tab;render();window.scrollTo(0,0)},
  filter:b=>{S[b.dataset.k]=b.dataset.v;document.querySelectorAll(`[data-act=filter][data-k=${b.dataset.k}]`).forEach(x=>x.setAttribute('aria-pressed',x===b));renderResults()},
  clear:()=>{S.q='';S.loc='all';S.cat='all';S.status='all';renderSearch()},
  goloc:b=>{S.tab='search';S.loc=b.dataset.v;S.cat='all';S.status='all';S.q='';render();window.scrollTo(0,0)},
  gocat:b=>{S.tab='search';S.cat=b.dataset.v;S.loc='all';S.status='all';S.q='';render();window.scrollTo(0,0)},
  open:b=>openItem(byId(b)),reopen:b=>{M=null;openItem(byId(b))},
  close:closeSheet,
  inc:async b=>{if(await itemAct(byId(b),'inc'))openItem(byId(b))},
  dec:async b=>{const id=byId(b),it=items.find(x=>x.id===id);if(it.qty<=1)return removeItem(id,'used');if(await itemAct(id,'dec'))openItem(id)},
  level:async b=>{const id=byId(b);if(await itemAct(id,'level',b.dataset.v)){openItem(id);
    if(b.dataset.v==='low'){const it=items.find(x=>x.id===id);toast(it.name+' is almost out. Add to the list?','Add',addShop(it.name))}}},
  opentoday:async b=>{if(await itemAct(byId(b),'open'))openItem(byId(b))},
  move:async b=>{if(await itemAct(byId(b),'move',b.dataset.v))openItem(byId(b))},
  used:b=>removeItem(byId(b),'used'),
  toss:b=>removeItem(byId(b),'tossed'),
  buyagain:async b=>{const it=items.find(x=>x.id===byId(b));await addShop(it.name)()},
  'list-del':b=>removeShop(byId(b)),
  'list-del-sheet':async()=>{const id=SE.id;closeSheet();await removeShop(id)},
  'shop-filter':b=>{S.store=b.dataset.v;renderList()},
  'shop-edit':b=>shopEdit(byId(b)),
  'shop-store':b=>{SE.store=b.dataset.v;document.querySelectorAll('[data-act=shop-store]').forEach(x=>x.setAttribute('aria-pressed',x===b))},
  'shop-save':async()=>{
    if(!SE.name.trim()){$('#sherr').textContent='Give the item a name.';return}
    try{await api('PATCH','/api/shopping/'+SE.id,{name:SE.name.trim(),store:SE.store,note:SE.note.trim()});await loadShopping();closeSheet()}
    catch(e){$('#sherr').textContent=e.message}
  },
  'list-add-q':async()=>{const v=S.q.trim();if(v)await addShop(v)()},
  add:addMenu,
  manual:()=>{newM();manual()},
  again:b=>{const p=window._recent[+b.dataset.k];newM({name:p.name,brand:p.brand,cat:p.cat,pkg:p.pkg,mode:p.mode});manual()},
  edit:b=>{const i=items.find(x=>x.id===byId(b));
    M={editId:i.id,name:i.name,brand:i.brand,cat:i.cat,loc:i.loc,mode:i.mode,qty:i.qty,level:i.level,pkg:i.pkg,bought:i.bought,exp:i.exp,expEdited:true,opened:i.opened};manual()},
  mode:b=>{M.mode=b.dataset.v;manual()},
  'm-inc':()=>{M.qty=Math.min(999,M.qty+1);$('#qtyblock').innerHTML=qtyBlock()},
  'm-dec':()=>{M.qty=Math.max(1,M.qty-1);$('#qtyblock').innerHTML=qtyBlock()},
  'm-level':b=>{M.level=b.dataset.v;$('#qtyblock').innerHTML=qtyBlock()},
  'save-manual':saveManual,
  logout:async()=>{try{await api('POST','/api/logout')}catch(e){}items=[];shopping=[];$('#view').innerHTML='';showLogin()},
  retry:boot,
  'quick-login':async b=>{
    try{await api('POST','/api/login',{username:b.dataset.u,password:''});boot()}
    catch(e){$('#qerr').textContent=e.message}
  },
  'show-pw':()=>{$('#quickwrap').hidden=true;$('#loginForm').hidden=false;$('#lu').focus()}
};
function addShop(name,store){return async()=>{
  try{await api('POST','/api/shopping',{name,store:store||''});await loadShopping();badge();toast('“'+name+'” is on the shopping list');if(S.tab==='list')renderList()}catch(e){fail(e)}
}}
document.addEventListener('click',e=>{const b=e.target.closest('[data-act]');if(b&&H[b.dataset.act])H[b.dataset.act](b,e)});
function onInput(e){
  const t=e.target,id=t.id;
  // Ignore the blur-time "change" for the search box: input already handled every keystroke, and
  // redrawing the results on blur would swallow the tap on a button inside them.
  if(id==='q'){if(e.type==='input'){S.q=t.value;renderResults()}return}
  if(id==='sort'){S.sort=t.value;renderResults();return}
  if(SE){if(id==='sh-name')SE.name=t.value;else if(id==='sh-note')SE.note=t.value;return}
  if(!M)return;
  if(id==='f-name')M.name=t.value;
  else if(id==='f-brand')M.brand=t.value;
  else if(id==='f-pkg')M.pkg=t.value;
  else if(id==='f-cat'){M.cat=t.value;if(M.editId==null){M.loc=CFG.rules[M.cat].loc;$('#f-loc').value=M.loc}updSugg()}
  else if(id==='f-loc'){M.loc=t.value;updSugg()}
  else if(id==='f-bought'&&t.value){M.bought=parseISO(t.value);updSugg()}
  else if(id==='f-exp'&&t.value){M.exp=parseISO(t.value);M.expEdited=true;updSugg()}
  else if(id==='f-opened')M.opened=t.value?parseISO(t.value):null;
}
document.addEventListener('input',onInput);document.addEventListener('change',onInput);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&sheetOpen())closeSheet()});

/* Refresh when the app comes back to the foreground, so the other person's changes show up. */
async function refresh(){
  if(!USER||!$('#login').hidden||sheetOpen())return;
  try{await loadAll();const q=$('#q');if(S.tab==='search'&&q&&document.activeElement===q){renderResults();$('#summary').innerHTML=summaryLine()}else render()}catch(e){}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
setInterval(()=>{if(!document.hidden)refresh()},60000);
boot();
