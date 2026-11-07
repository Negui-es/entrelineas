const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../../static/app.js'),'utf8');
function setup(reduced=false){
  const handlers={}; const timers=new Map(); let id=0; const animations=[];
  const element=()=>({hidden:false,attrs:{},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]}});
  const message={textContent:'',animate(frames,options){const animation={cancelled:false,cancel(){this.cancelled=true}};animations.push(animation);return animation}};
  const button={disabled:false,textContent:'Buscar'}; const results=element(); const status=element();status.hidden=true;status.querySelector=()=>message;
  const form=element();form.querySelector=()=>button;form.addEventListener=(name,fn)=>{handlers[name]=fn};
  const document={querySelectorAll:()=>[],querySelector:s=>s==='[data-search-form]'?form:null,getElementById:id=>id==='catalog-search-status'?status:results,addEventListener:(name,fn)=>{handlers[name]=fn}};
  vm.runInNewContext(source,{document,window:{addEventListener:(name,fn)=>{handlers[name]=fn},matchMedia:()=>({matches:reduced})},WeakMap,gettext:s=>s,setInterval(fn,delay){assert.equal(delay,3000);timers.set(++id,fn);return id},clearInterval(id){timers.delete(id)}});
  return {handlers,timers,message,button,status,results,animations,tick(){for(const fn of timers.values()) fn()}};
}
test('30 random messages per cycle without repetitions, including cycle boundary',()=>{
  const s=setup();s.handlers.submit({});const seen=[];
  for(let i=0;i<90;i++){seen.push(s.message.textContent);s.tick()}
  for(let i=0;i<90;i+=30)assert.equal(new Set(seen.slice(i,i+30)).size,30);
  for(let i=1;i<seen.length;i++)assert.notEqual(seen[i],seen[i-1]);
  assert.equal(s.button.textContent,'Buscar');assert.equal(s.button.disabled,true);assert.equal(s.results.hidden,true);
});
test('invalid and duplicate submissions do not start extra timers',()=>{
  const s=setup();s.handlers.submit({defaultPrevented:true});assert.equal(s.timers.size,0);
  s.handlers.submit({});let prevented=false;s.handlers.submit({preventDefault(){prevented=true}});assert.equal(s.timers.size,1);assert.ok(prevented);
});
test('cancel, departure and history restore clean up timers and animations',()=>{
  for(const event of ['Escape','pagehide','pageshow']){
    const s=setup();s.handlers.submit({});const animation=s.animations[0];
    if(event==='Escape')s.handlers.keydown({key:'Escape'});else s.handlers[event]();
    assert.equal(s.timers.size,0);assert.equal(s.message.textContent,'');assert.equal(s.button.disabled,false);assert.equal(s.results.hidden,false);assert.ok(animation.cancelled);
    s.handlers.submit({});assert.equal(s.timers.size,1);
  }
});
test('reduced motion keeps rotating messages without animation',()=>{
  const s=setup(true);s.handlers.submit({});const before=s.message.textContent;s.tick();assert.notEqual(s.message.textContent,before);assert.equal(s.animations.length,0);
});
