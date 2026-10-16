'use strict';
const $ = id => document.getElementById(id);
const state = {view:'recommended', category:'', q:'', source:'', sort:'recommended', page:1, version:null, item:null, request:0};
const views = {recommended:['值得关注的校园动态','科研、实习与竞赛机会，不错过，也不必一条条找。','为你推荐'], latest:['新收录与更新','按本地收录时间浏览；发布时间另行标注，旧公告不会变成新公告。','最新收录'], unread:['还没读过的信息','看过的内容会留在历史中；正文有变化时会重新标为未读。','未读信息'], favorites:['留给以后的好机会','先收藏，等有时间再认真看看。','我的收藏'], all:['校园信息，完整保留','不依赖推荐判断，在这里发现算法可能漏掉的信息。','全部历史'], hidden:['暂时不感兴趣','内容没有被删除，随时可以恢复。重要教务事项仍受保护。','不感兴趣']};
const icons = {research:'⌁',competition:'♧',internship:'▣',event:'✧',mandatory_academic:'▤',general:'◫',electronics:'⚡'};
function el(tag,cls,text){const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;}
function dateText(value,withTime=false){if(!value)return '暂无成功记录';const d=new Date(value);if(Number.isNaN(d.getTime()))return value;return d.toLocaleString('zh-CN',withTime?{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}:{year:'numeric',month:'2-digit',day:'2-digit'});}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,3000);}
async function api(path,body){const options=body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(body)}:{};const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw new Error(data.message||'暂时无法读取，请稍后重试。');return data;}
async function mutate(item,action,value){await api('/api/state',{id:item.id,hash:item.hash,action,value});}
function renderCard(item){
 const card=el('article','card'+(item.unread?'':' read'));card.dataset.id=item.id;
 card.append(el('div','category-icon '+item.category,icons[item.category]||'◫'));
 const main=el('div','card-main'),meta=el('div','card-meta');
 meta.append(el('span','tag',item.category_label),el('span','',item.source==='portal'?'信息门户':'北邮人论坛'),el('span','','·'),el('span','',item.origin||'来源待核实'),el('span','','·'),el('time','',item.published||'发布时间未知'));
 if(item.unread&&item.revision>1)meta.append(el('span','tag new','正文有更新'));
 if(item.historical)meta.append(el('span','tag','较早历史 · 留意有效期'));
 if(item.importance==='high')meta.append(el('span','tag priority','重要事项'));
 if(item.hidden)meta.append(el('span','tag','已标不感兴趣'));
 main.append(meta);const h=el('h2'),title=el('button','title-button');
 if(item.unread)title.append(el('span','unread-dot'));title.append(document.createTextNode(item.title));title.addEventListener('click',()=>openReader(item.id));h.append(title);main.append(h);
 main.append(el('p','excerpt',item.summary));
 if(item.deadline.value)main.append(el('div','deadline','原文截止日期：'+item.deadline.value+' · 具体时刻请核对原文'));
 const bottom=el('div','card-bottom');const reason=item.reasons.length?item.reasons[0].text:'正文摘录 · 适用条件与有效期请查看原文';
 bottom.append(el('div','recommend-reason',(item.relevance==='high'?'✦ ':'')+reason));const actions=el('div','card-actions');
 const save=el('button','card-action'+(item.favorite?' saved':''),item.favorite?'★':'☆');save.title=item.favorite?'取消收藏':'收藏';save.setAttribute('aria-label',save.title);save.addEventListener('click',async()=>{try{await mutate(item,'favorite',!item.favorite);await loadFeed();toast(item.favorite?'已取消收藏':'已收藏，稍后再看');}catch(e){toast(e.message);}});
 const hide=el('button','card-action',item.hidden?'↶':'⊖');hide.title=item.hidden?'恢复到信息流':'不感兴趣';hide.setAttribute('aria-label',hide.title);hide.disabled=item.importance==='high';hide.addEventListener('click',async()=>{try{await mutate(item,'hidden',!item.hidden);await loadFeed();toast(item.hidden?'已恢复，内容仍保留在历史中':'已收起，可在“不感兴趣”中恢复');}catch(e){toast(e.message);}});
 actions.append(save,hide);bottom.append(actions);main.append(bottom);card.append(main);return card;
}
async function loadFeed(){
 const seq=++state.request;$('error-banner').hidden=true;
 const params=new URLSearchParams({view:state.view,category:state.category,q:state.q,source:state.source,sort:state.sort,page:state.page});
 try{const data=await api('/api/feed?'+params);if(seq!==state.request)return;
  state.version=data.version;$('new-banner').hidden=true;$('feed').replaceChildren();
  if(data.items.length)data.items.forEach(i=>$('feed').append(renderCard(i)));else{const empty=el('div','empty');empty.append(el('strong','',state.view==='favorites'?'还没有收藏':'这里暂时没有信息'),el('p','',state.q?'换个关键词或清除筛选试试。':state.view==='recommended'?'推荐不代表全部。可以打开“最新收录”或“全部历史”继续浏览。':'采集完成后，新内容会自动出现在这里。'));if(state.view==='recommended'){const b=el('button','secondary-button','浏览全部历史');b.onclick=()=>switchView('all');empty.append(b);}$('feed').append(empty);}
  $('result-count').textContent=data.total;$('nav-unread').textContent=data.counts.unread;$('nav-favorites').textContent=data.counts.favorites||'';
  const pages=Math.max(1,Math.ceil(data.total/data.page_size));$('pagination-label').textContent=`第 ${data.page} / ${pages} 页`;$('prev-page').disabled=data.page<=1;$('next-page').disabled=data.page>=pages;
 }catch(e){if(seq!==state.request)return;$('error-banner').textContent=e.message;$('error-banner').hidden=false;$('feed').replaceChildren(el('div','empty','暂时无法打开本地数据。采集和历史文件不会因此被清空。'));}
}
function switchView(view){state.view=view;state.page=1;state.sort=view==='recommended'?'recommended':view==='latest'?'collected':'published';$('sort').value=state.sort;const copy=views[view];$('view-title').replaceChildren(document.createTextNode(copy[0]),el('span','','✦'));$('view-subtitle').textContent=copy[1];$('breadcrumb-view').textContent=copy[2];$('list-context').textContent=view==='recommended'?'· 未读优先，基于你的本地兴趣':'· 按所选顺序浏览，历史完整保留';document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));loadFeed();}
async function openReader(id){
 try{const item=await api('/api/detail?'+new URLSearchParams({id}));state.item=item;$('reader-content').replaceChildren();const box=$('reader-content');
  box.append(el('span','tag',item.category_label),el('h2','detail-title',item.title),el('div','detail-meta',`${item.source==='portal'?'信息门户':'北邮人论坛'} · ${item.origin} · 发布于 ${item.published||'未知'}`));
  const controls=el('div','detail-controls');if(item.url){const a=el('a','original-link','打开原文 ↗');a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';controls.append(a);}
  const favorite=el('button','secondary-button',item.favorite?'★ 已收藏':'☆ 收藏');favorite.onclick=async()=>{try{await mutate(item,'favorite',!item.favorite);item.favorite=!item.favorite;favorite.textContent=item.favorite?'★ 已收藏':'☆ 收藏';loadFeed();}catch(e){toast(e.message);}};
  const unread=el('button','secondary-button','标为未读');unread.onclick=async()=>{try{await mutate(item,'read',false);toast('已标为未读');closeReader();loadFeed();}catch(e){toast(e.message);}};controls.append(favorite,unread);box.append(controls);
  const insight=el('section','insight-box');insight.append(el('strong','','为什么值得看 · 本地规则判断'));
  if(!item.reasons.length)insight.append(el('p','','目前没有足够信息判断个人相关性。保留原文供你自行发现机会。'));
  item.reasons.forEach(r=>{insight.append(el('p','','推断：'+r.text));if(r.evidence)insight.append(el('div','evidence','原文证据：'+r.evidence));});
  if(item.deadline.value){insight.append(el('p','','原文明确的截止日期：'+item.deadline.value),el('div','evidence',item.deadline.evidence));}else insight.append(el('p','','截止时间：无法确认。没有完整年份或存在多处截止时，不推测日期。'));
  insight.append(el('p','','行动建议：核对适用对象、报名方式与当前有效期；这里不代表你已经满足资格。'));box.append(insight);
  if(item.body_status!=='ok')box.append(el('div','error-banner',item.body_status==='image_only'?'本通知正文为图片，文字尚未提取，请打开原文查看。':item.body_status==='attachment_only'?'本通知以附件提供正文，附件内容尚未提取。':'正文采集不完整，请以原文为准。'));
  box.append(el('div','body-label','收录正文 · 以原通知为准'),el('div','detail-body',item.body));
  item.attachments.forEach(a=>{if(a.url){const link=el('a','original-link',a.name+' ↗');link.href=a.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);}});
  box.append(el('div','detail-foot',`本地首次收录：${dateText(item.first_seen,true)} · 当前版本 ${item.revision}。发布时间与收录时间不同。`));
  const feedback=el('div','feedback-buttons');[['relevant','与我相关'],['important','很重要'],['irrelevant','不感兴趣'],['unsure','暂不确定']].forEach(([value,label])=>{const b=el('button',item.feedback===value?'active':'',label);b.onclick=async()=>{try{await mutate(item,'feedback',value);feedback.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');toast('反馈已本地保存；采集忙时会稍后同步');loadFeed();}catch(e){toast(e.message);}};feedback.append(b);});box.append(feedback);
  $('reader-drawer').hidden=false;$('drawer-backdrop').hidden=false;document.body.style.overflow='hidden';$('close-reader').focus();
  await mutate(item,'read',true);loadFeed();
 }catch(e){toast(e.message);}
}
function closeReader(){$('reader-drawer').hidden=true;$('drawer-backdrop').hidden=true;document.body.style.overflow='';state.item=null;}
let latestStatus=null;
async function checkStatus(poll=false){try{const data=await api('/api/status');latestStatus=data;const labels={ok:'已更新',no_new:'无新增',running:'正在采集',stuck:'采集未完成',stale:'较久未成功',never:'尚未采集',login_expired:'需要重新登录',failed:'采集失败',partial_failed:'部分采集失败',interrupted:'上次采集中断'};for(const [key,name] of [['portal','信息门户'],['byr','北邮人论坛']]){const s=data.sources[key];$(key+'-status').textContent=`${name} · ${labels[s.status]||'需要检查'} · ${s.last_success?'成功于 '+dateText(s.last_success,true):'暂无成功记录'}`;$(key+'-status').classList.toggle('failed',!['ok','no_new','running'].includes(s.status));}
 if(poll&&state.version){const feed=await api('/api/feed?view=all');if(feed.version!==state.version)$('new-banner').hidden=false;}
 }catch(e){$('portal-status').textContent='状态暂不可用 · '+e.message;$('portal-status').classList.add('failed');}}
function info(title,paragraphs){$('info-title').textContent=title;$('info-content').replaceChildren(...paragraphs.map(x=>el('p','',x)));$('info-dialog').showModal();}
$('navigation').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b)switchView(b.dataset.view);});
$('topics').addEventListener('click',e=>{const b=e.target.closest('[data-category]');if(!b)return;state.category=b.dataset.category;state.page=1;document.querySelectorAll('[data-category]').forEach(x=>x.classList.toggle('active',x===b));loadFeed();});
$('search').addEventListener('input',()=>{clearTimeout(state.searchTimer);state.searchTimer=setTimeout(()=>{state.q=$('search').value;state.page=1;loadFeed();},220);});
$('source-filter').onchange=()=>{state.source=$('source-filter').value;state.page=1;loadFeed();};$('sort').onchange=()=>{state.sort=$('sort').value;state.page=1;loadFeed();};
$('refresh').onclick=()=>{loadFeed();checkStatus();};$('load-new').onclick=()=>{state.page=1;loadFeed();checkStatus();};$('prev-page').onclick=()=>{state.page--;loadFeed();window.scrollTo({top:150,behavior:'smooth'});};$('next-page').onclick=()=>{state.page++;loadFeed();window.scrollTo({top:150,behavior:'smooth'});};
$('close-reader').onclick=closeReader;$('drawer-backdrop').onclick=closeReader;$('close-info').onclick=()=>$('info-dialog').close();
$('help-button').onclick=()=>info('每天看五分钟，就够了',['先看“为你推荐”和“最新收录”，再用主题和搜索缩小范围。收藏会保存到本机；关闭网页也不会丢失。','读过的信息留在完整历史中。正文发生变化会重新标为未读。不感兴趣的内容可以随时恢复，重要教务事项受保护。','采集由现有Windows计划任务独立执行。电脑关机、休眠、未登录或校园网/VPN断开时可能无法更新，请留意上方的最后成功时间。','学校原文按纯文本展示，不加载外部图片、脚本或字体。网页只在本机开放，不调用云端模型。关闭浏览器不会停止采集；用“关闭 BUPT Insight”快捷方式停止阅读服务。']);
$('status-details').onclick=()=>info('信息从哪里来',latestStatus?['最近成功时间代表实际业务采集成功，不是网页刷新时间。无新增仍属于一次成功检查。',...Object.entries(latestStatus.sources).map(([k,s])=>`${k==='portal'?'信息门户':'北邮人论坛'}：${s.status}；最后成功 ${dateText(s.last_success,true)}；最近一轮读取 ${s.total} 条。`),latestStatus.feedback_pending?`还有 ${latestStatus.feedback_pending} 条反馈等待采集结束后同步，已经安全保存在本机。`:'反馈同步正常。']:['暂时无法取得运行状态，请稍后刷新。']);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeReader();if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();$('search').focus();}});
$('today-label').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});loadFeed();checkStatus();setInterval(()=>checkStatus(true),30000);
