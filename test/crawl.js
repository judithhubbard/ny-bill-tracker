<script>
(function(){
const R=[], errs=[]; let n=0;
window.addEventListener('error',e=>errs.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>errs.push('rej '+e.reason));
const sig=()=>document.body.innerHTML.length+'|'+location.hash+'|'+[...document.querySelectorAll('[id^=view-]')].filter(e=>!e.hidden).map(e=>e.id)+'|'+[...document.querySelectorAll('details[open]')].length;
const label=(el)=>(el.tagName+'.'+(el.className||'')+' '+JSON.stringify(el.dataset||{})+' "'+(el.textContent||'').trim().slice(0,40)+'"').replace(/\s+/g,' ');
function sweep(name, getRoot, reset){
  reset(); const root=getRoot(); if(!root){R.push(name+': no root');return;}
  const els=[...root.querySelectorAll('button, summary, a[href]:not([target=_blank]), select, input[type=checkbox]')].filter(e=>e.offsetParent!==null);
  R.push(name+': '+els.length+' controls');
  const keys=els.map(label);
  for(let i=0;i<keys.length;i++){
    reset(); const r=getRoot(); if(!r) continue;
    const el=[...r.querySelectorAll('button, summary, a[href]:not([target=_blank]), select, input[type=checkbox]')].filter(e=>e.offsetParent!==null).find(e=>label(e)===keys[i]);
    if(!el) continue;
    if(el.tagName==='A'){R.push('  LINK '+keys[i]+' -> '+el.getAttribute('href')); continue;}
    if(el.dataset.copylink!==undefined||/Copy/.test(el.textContent)) continue;
    const b=sig(), e0=errs.length; n++;
    try{ if(el.tagName==='SELECT'){ if(el.options.length>1){el.selectedIndex=(el.selectedIndex+1)%el.options.length; el.dispatchEvent(new Event('change',{bubbles:true}));} } else el.click(); }catch(x){errs.push('throw '+x)}
    if(errs.length>e0) R.push('  ERROR '+keys[i]+' '+errs.slice(e0).join(';'));
    else if(sig()===b) R.push('  NO CHANGE '+keys[i]);
  }
}
const tab=(v)=>document.querySelector('.view-tab[data-view='+v+']').click();
setTimeout(()=>{
  // bill panels
  sweep('bill panel', ()=>{const d=document.querySelector('#list .bill');return d;}, ()=>{tab('bills');const d=document.querySelector('#list .bill'); if(d&&!d.open){d.querySelector('summary').click();}});
  // star three bills then watchlist
  tab('bills'); [...document.querySelectorAll('#list .bill')].slice(0,3).forEach(d=>{const s=d.querySelector('[data-watch], .watch, button[aria-label*=atch]'); s&&s.click();});
  sweep('watchlist', ()=>document.getElementById('view-watch'), ()=>tab('watch'));
  sweep('weigh in', ()=>document.getElementById('view-act'), ()=>tab('act'));
  sweep('filters', ()=>document.getElementById('side')||document.getElementById('filtered'), ()=>tab('bills'));
  const o=document.createElement('pre');o.id='RESULT';o.textContent='clicked '+n+'\n'+R.join('\n')+'\nERRORS: '+errs.join(' || ');document.body.prepend(o);
},3500);
})();
</script>
