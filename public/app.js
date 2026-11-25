import {GameAudio} from './audio.js';
const app=document.querySelector('#app'), toast=document.querySelector('#toast');
const roles={black:'الذئب الأسود',silent:'الذئب المُسكِت',wolf:'الذئب العادي',doctor:'الطبيب',witch:'الساحر',villager:'القروي البسيط'};
const emojis={black:'🐺',silent:'🤫',wolf:'🐺',doctor:'🩺',witch:'🧙',villager:'🌾'};
const phases={dawn:'طلع النهار',lobby:'غرفة الانتظار',wolves:'تستيقظ الذئاب',witch:'دور الساحر',doctor:'دور الطبيب',speech:'النقاش اليومي',debate:'مناظرة المتعادلين',vote:'التصويت العلني',result:'نتيجة التصويت',end:'انتهت اللعبة'};
let state=null, socket=null, reconnect=null, timerEnd=null, currentAction='', connected=false, toastTimer, draft={save:false,target:'',kill:'',silence:''}, session=null;
try{session=JSON.parse(sessionStorage.getItem('wolf-session')||'null')}catch{}
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const speakingUntil=new Map();
function markSpeech(id,samples){
  if(!id)return;
  let energy=0;
  for(const sample of samples)energy+=sample*sample;
  if(energy/samples.length<320*320)return;
  if(!speakingUntil.has(id))document.getElementById('person-'+id)?.classList.add('speaking');
  speakingUntil.set(id,performance.now()+540);
}
function expireSpeech(){
  for(const [id,until] of speakingUntil){
    if(until>performance.now())continue;
    speakingUntil.delete(id);
    document.getElementById('person-'+id)?.classList.remove('speaking');
  }
}
const audio=new GameAudio(b=>{if(socket?.readyState===1&&socket.bufferedAmount<6400){socket.send(b);markSpeech(state?.me,new Int16Array(b))}});
const name=id=>state?.players.find(p=>p.id===id)?.name||'—';
function error(msg){toast.textContent=msg;toast.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('show'),4000)}
function send(d){if(socket?.readyState!==1){error('الاتصال مقطوع');return}socket.send(JSON.stringify(d))}
let effectsContext;
let effectsOn=localStorage.getItem('wolf-effects')!=='off';
function unlockEffects(){
  const Context=window.AudioContext||window.webkitAudioContext;
  if(!effectsOn||!Context)return;
  effectsContext??=new Context();
  if(effectsContext.state!=='running')effectsContext.resume().catch(()=>{});
}
document.addEventListener('click',unlockEffects,true);
const melodies={wolves:[294,220],dawn:[392,494,587],vote:[294,392,523],incoming:[740,554,740],yourTurn:[523,659,880],end:[392,494,587,784]};
function playCue(phase){
  const tones=melodies[phase],ctx=effectsContext;
  if(!effectsOn||!tones||ctx?.state!=='running')return;
  tones.forEach((frequency,index)=>{
    const tone=ctx.createOscillator(),gain=ctx.createGain(),at=ctx.currentTime+index*.18;
    tone.frequency.value=frequency;
    gain.gain.setValueAtTime(.0001,at);
    gain.gain.exponentialRampToValueAtTime(.07,at+.025);
    gain.gain.exponentialRampToValueAtTime(.0001,at+.27);
    tone.connect(gain).connect(ctx.destination);
    tone.start(at);tone.stop(at+.29);
  });
}
let dismissedDawn='';
function showDawn(){
  if(state?.phase!=='dawn')return;
  const key=state.code+'-'+state.day;
  if(dismissedDawn===key)return;
  const deaths=state.deaths.filter(d=>d.cause==='night').map(d=>`<li><strong>${escape(d.name)}</strong><span>${emojis[d.role]} ${roles[d.role]}</span></li>`);
  const dialog=document.createElement('dialog');
  dialog.className='dawn';dialog.setAttribute('aria-labelledby','dawn-title');
  dialog.innerHTML=`<h2 id="dawn-title">🌅 طلع النهار</h2>${deaths.length?`<h3>اللي ماتوا هاذ الليلة</h3><ul class="fallen">${deaths.join('')}</ul>`:'<p>ما مات حتى واحد هاذ الليلة.</p>'}<p>${state.silenced?'🤫 تسكّت اليوم: '+escape(name(state.silenced)):'ما تسكّت حتى واحد.'}</p>${state.doctorSaved?'<p>🩺 الطبيب قدر ينقذ لاعب هاذ الليلة.</p>':''}<button>فهمت</button>`;
  app.append(dialog);dialog.showModal();
  dialog.onclose=()=>{dismissedDawn=key};
  dialog.querySelector('button').onclick=()=>dialog.close();
}
const phaseIntros={
  wolves:['night','هبط الليل','القرية ترقد والذئاب تفيق'],
  dawn:['day','طلع النهار','حان وقت كشف أحداث الليلة'],
  vote:['vote','وقت التصويت','كل لاعب يصوّت كي يجي دوره']
};
let introTimer,noticeTimer;
function showPhaseIntro(phase){
  const intro=document.getElementById('phase-intro');
  clearTimeout(introTimer);
  intro.hidePopover?.();intro.hidden=true;
  const scene=phaseIntros[phase];
  if(!scene)return;
  intro.dataset.kind=scene[0];
  intro.querySelector('strong').textContent=scene[1];
  intro.querySelector('small').textContent=scene[2];
  intro.hidden=false;
  if(intro.showPopover)intro.showPopover();
  else intro.removeAttribute('popover');
  introTimer=setTimeout(()=>{intro.hidePopover?.();intro.hidden=true},1700);
}
let turnTimer;
function speakTurn(s){
  return s && !s.paused && (s.phase==='speech'||s.phase==='debate') && s.turn===s.me;
}
function announceState(previous,next){
  const noticeTurn=document.getElementById('turn-notice');
  if(!speakTurn(next)){noticeTurn.hidden=true;clearTimeout(turnTimer)}
  else if(!speakTurn(previous)||previous.phase!==next.phase||previous.day!==next.day){
    noticeTurn.textContent=next.phase==='debate'?'🎙 جا دورك في المناظرة':'🎙 جا دورك تهدر';
    noticeTurn.hidden=false;playCue('yourTurn');clearTimeout(turnTimer);
    turnTimer=setTimeout(()=>{noticeTurn.hidden=true},3200);
  }
  if(!previous||previous.code!==next.code)return;
  if(previous.phase!==next.phase||previous.day!==next.day){
    showPhaseIntro(next.phase);
    playCue(next.phase);
  }
  if(previous.phase!=='vote'||previous.day!==next.day||previous.round!==next.round)return;
  const voters=Object.entries(next.votes).filter(([id,target])=>
    target===next.me && id!==next.me && previous.votes[id]!==target);
  if(!voters.length)return;
  const notice=document.getElementById('vote-notice');
  clearTimeout(noticeTimer);
  if(notice.hidden)notice.replaceChildren();
  for(const [id] of voters){
    const line=document.createElement('div');
    line.textContent='🗳️ '+name(id)+' صوّت عليك';
    notice.append(line);
  }
  notice.hidden=false;
  playCue('incoming');
  noticeTimer=setTimeout(()=>{notice.hidden=true;notice.replaceChildren()},3800);
}
function connect(){socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.binaryType='arraybuffer';socket.onopen=()=>{connected=true;if(session)send({type:'resume',...session});else render()};socket.onmessage=e=>{if(typeof e.data!=='string'){if(e.data.byteLength===648){const id=Array.from(new Uint8Array(e.data,0,8),x=>x.toString(16).padStart(2,'0')).join('');markSpeech(id,new Int16Array(e.data,8))}audio.play(e.data);return}const d=JSON.parse(e.data);if(d.type==='session'){session={code:d.code,token:d.token};sessionStorage.setItem('wolf-session',JSON.stringify(session))}else if(d.type==='error'){error(d.message);if(d.message==='انتهت جلسة الغرفة'){session=null;state=null;sessionStorage.removeItem('wolf-session');render()}}else if(d.type==='state'){const old=state;state=d;const a=`${d.day}:${d.phase}:${d.turn}:${d.paused}`;if(a!==currentAction){draft={save:false,target:'',kill:'',silence:''};audio.clear();currentAction=a}timerEnd=d.remaining==null?null:performance.now()+d.remaining*1000;audio.setAllowed(d.talk);render();announceState(old,d)}};socket.onclose=e=>{connected=false;audio.setAllowed(false);audio.clear();if(e.code===4000){session=null;state=null;sessionStorage.removeItem('wolf-session');render();return}if(state)render();else if(!document.querySelector('#player-name'))render();clearTimeout(reconnect);reconnect=setTimeout(connect,1200)};socket.onerror=()=>{}}
function header(){return `<header class="brand"><b>◐ ليلة الذئاب</b><button id="effects" class="effects" aria-label="المؤثرات الصوتية" aria-pressed="${effectsOn}">${effectsOn?'🔔':'🔕'}</button><span class="pill">${connected?'● متصل':'○ إعادة الاتصال…'}</span></header>`}
function soloOptions(){return `<div class="divider"></div><h3>🧪 تجربة فردية</h3><small>اختبر القواعد وحدك مع لاعبين آليين.</small><label>عدد اللاعبين (بما فيهم أنت)<select id="test-count">${Array.from({length:26},(_,i)=>i+5).map(n=>`<option value="${n}" ${n===8?'selected':''}>${n}</option>`).join('')}</select></label><label>دورك في التجربة<select id="test-role"><option value="random">عشوائي</option>${Object.entries(roles).map(([r,label])=>`<option value="${r}">${label}</option>`).join('')}</select></label><button class="secondary" id="test-create">بدء تجربة فردية</button>`}
function home(){const invite=new URLSearchParams(location.search).get('room')||'';return `${header()}<section class="hero"><div class="moon">🌙</div><h1>ليلة الذئاب</h1><p class="gold">من بينكم الذئب؟</p><p class="muted">لعبة جماعية صوتية مع الأصدقاء • 5 لاعبين على الأقل</p></section><section class="panel"><label for="player-name">اسم اللاعب</label><input id="player-name" maxlength="24" autocomplete="nickname" placeholder="اكتب اسمك"><button id="create">إنشاء غرفة جديدة</button>${new URLSearchParams(location.search).get('solo')==='1'?soloOptions():''}<div class="divider"></div><label for="room-code">رمز الغرفة</label><input id="room-code" maxlength="6" value="${escape(invite)}" placeholder="ABC123" dir="ltr" autocapitalize="characters"><button class="secondary" id="join">انضم إلى أصدقائك</button></section><p class="muted center">استعمل سماعات الأذن لتجربة صوتية أفضل.</p>`}
function packChannel(){
  return state.phase==='wolves' && Boolean(state.private.wolves);
}
function packHint(){
  const others=state.players.filter(p=>p.id!==state.me && state.private.wolves.includes(p.id));
  if(!others.length)return 'راك الذئب الوحيد الحي.';
  if(others.every(p=>p.bot))return 'راك مع ذئب آلي. البوتات يختارو الهدف بصح ما يهدروش بالميكرو.';
  return 'يسمعوك غير الذئاب الأحياء كي يفعّلو الصوت. فعّل الميكرو باش تتشاورو.';
}
function audioPanel(){const dead=state.players.some(p=>p.id===state.me&&!p.alive);const open=audio.enabled&&state.talk&&!audio.muted;return `<section class="panel audio">${dead?'<h3>👻 قناة الموتى</h3>':''}${packChannel()?'<h3>🐺 قناة الذئاب الخاصة</h3>':''}<div class="row"><div><h3>${open?'🎙️ الميكروفون مفتوح':'🔇 الميكروفون مغلق'}</h3><small>${dead?'تسمع نقاش الأحياء والمناظرة. كي تهدر، يسمعوك غير الموتى اللي معاك في الغرفة.':packChannel()?packHint():state.phase==='lobby'?'محادثة غرفة الانتظار — يسمعك جميع الموجودين عند فتح الميكروفون':'أثناء اللعب يُفتح الكلام حسب الدور فقط'}</small></div><button id="audio" class="small secondary">${audio.enabled?'استئناف الصوت':'تفعيل الصوت والميكروفون'}</button></div>${audio.enabled?`<button id="mic-toggle" class="secondary" aria-pressed="${audio.muted}">${audio.muted?'فتح الميكروفون':'غلق الميكروفون'}</button>`:''}</section>`}
function players(){return `<section class="panel"><div class="row"><h3>اللاعبون</h3><small>${state.players.filter(p=>p.alive).length} أحياء / ${state.players.length}</small></div><div class="grid">${state.players.map(p=>{let label=!p.alive?'☠ '+(roles[p.role]||'مقصى'):!p.online?'غير متصل':p.id===state.turn?'دوره الآن':p.id===state.silenced?'مسكوت':p.id===state.host?'صاحب الغرفة':'في اللعبة';if(p.alive&&p.role&&p.id!==state.me)label=roles[p.role];return `<div id="person-${p.id}" class="person ${speakingUntil.has(p.id)?'speaking':''} ${!p.alive?'dead':p.id===state.turn?'active':p.id===state.silenced?'silent':''}"><div class="avatar">${!p.alive?'☠':p.role?emojis[p.role]:escape(p.name.slice(0,1))}</div><strong>${escape(p.name)}${p.id===state.me?' (أنت)':p.bot?' 🤖':''}</strong><small>${escape(label)}</small><span class="voice-live">🎙 راه يهدر</span>${state.host===state.me&&!p.online&&p.alive&&state.phase!=='end'?`<button class="small danger kick" data-id="${p.id}">إقصاء</button>`:''}</div>`}).join('')}</div></section>`}
function selectSetting(key,label,values){return `<label>${label}<select data-setting="${key}">${values.map(v=>`<option value="${v}" ${state.settings[key]===v?'selected':''}>${v} ثانية</option>`).join('')}</select></label>`}
function lobby(){return `${state.test?'<section class="panel center"><h3>🧪 وضع الاختبار الفردي</h3><small>اللاعبون الآليون يتحركون تلقائياً ولا يرسلون صوتاً.</small></section>':`<section class="panel center"><small>رمز الغرفة — شاركه مع أصدقائك</small><div class="code">${state.code}</div><button id="share" class="secondary">مشاركة رابط الدعوة</button></section>`}${players()}${state.host===state.me?`<section class="panel"><h3>إعدادات اللعبة</h3><div class="settings">${selectSetting('speech','الكلام العادي',[30,60,90,120])}${selectSetting('debate','المناظرة',[60,120,180])}${selectSetting('vote','التصويت لكل لاعب',[30,60,90,120])}${selectSetting('wolves','تشاور الذئاب',[60,120,180])}${selectSetting('witch','الساحر',[15,30,60])}${selectSetting('doctor','الطبيب',[15,30,60])}<label class="wide">عدد الذئاب<select id="wolf-count"><option value="1" ${state.test&&['silent','wolf'].includes(state.testRole)?'disabled':''} ${state.settings.single?'selected':''}>ذئب واحد يقتل ويسكت — مناسب لـ5 لاعبين</option><option value="2" ${state.test&&state.testRole==='wolf'?'disabled':''} ${!state.settings.single&&!state.settings.extra?'selected':''}>ذئبان: الأسود والمُسكِت</option><option value="3" ${state.test&&state.players.length<7?'disabled':''} ${state.settings.extra?'selected':''}>3 ذئاب — 7 لاعبين على الأقل</option></select></label></div><small>كل لاعب عنده وقت محدّد باش يصوّت. تبدأ اللعبة مباشرة في الليل.</small><button id="start" ${state.players.length<(state.settings.extra?7:5)||state.players.some(p=>!p.online)?'disabled':''}>بدء اللعبة</button></section>`:'<section class="panel center">بانتظار صاحب الغرفة لبدء اللعبة…</section>'}${audioPanel()}<button id="leave" class="secondary">مغادرة الغرفة</button>`}
function targetList(ids,selected=''){return `<select id="target"><option value="">اختر لاعباً</option>${ids.map(i=>`<option value="${i}" ${selected===i?'selected':''}>${escape(name(i))}</option>`).join('')}</select>`}
function action(){const p=state.private;let html='';if(state.paused||!state.players.find(x=>x.id===state.me)?.alive)return '';
if(p.wolfActions){html+=`<section class="panel"><h3>قرارات الذئاب السرية</h3><small>تحدثوا مع بعضكم — لا يسمعكم القرويون.</small>${Object.entries(p.wolfActions).map(([k,v])=>`<div class="stack"><b>${k==='kill'?'☠️ اختيار ضحية القتل':'🤫 اختيار من يتم إسكاته'}</b>${v.done?`<p class="green">تم التأكيد: ${escape(v.chosen?name(v.chosen):'لا أحد')}</p>`:`<select id="${k}"><option value="">اختر لاعباً</option>${v.targets.map(i=>`<option value="${i}" ${draft[k]===i?'selected':''}>${escape(name(i))}</option>`).join('')}</select><button data-wolf="${k}">تأكيد الاختيار</button>${k==='silence'?'<button class="secondary" id="skip-silence">عدم إسكات أحد</button>':''}`}</div>`).join('')}${p.wolfChoices?.kill?`<small>ضحية القتل المختارة: ${escape(name(p.wolfChoices.kill))}</small>`:''}${p.wolfChoices?.silence?`<small>المسكوت المختار: ${escape(name(p.wolfChoices.silence))}</small>`:''}</section>`}
if(p.witch){html+=`<section class="panel role"><h3>جرعات الساحر</h3>${p.potions.life?`<p>${p.witch.victim?'ضحية الذئاب: <b class="red">'+escape(name(p.witch.victim))+'</b>':'لم يتم اختيار ضحية'}</p>${p.witch.victim?`<label class="choice"><input id="save" type="checkbox" ${draft.save?'checked':''}> استعمال جرعة الحياة</label>`:''}`:'<small>جرعة الحياة مستعملة — ضحية الذئاب سرية.</small>'}${p.potions.death?`<label>جرعة الموت (اختيار اختياري)</label>${targetList(p.witch.targets,draft.target)}`:'<small>جرعة الموت مستعملة.</small>'}<button id="witch">تأكيد القرارات / تخطي</button></section>`}
if(p.protect)html+=`<section class="panel"><h3>من تريد حمايته الليلة؟</h3>${targetList(p.protect,draft.target)}<button id="protect">تأكيد الحماية</button></section>`;
if(p.vote)html+=`<section class="panel"><h3>حان دورك في التصويت</h3><small>أكّد صوتك قبل ما يوفى الوقت. كي يوفى دورك، يمرّ التصويت للاعب التالي.</small>${targetList(p.vote,draft.target)}<button id="vote">تأكيد صوتي</button></section>`;
if(['speech','debate'].includes(state.phase)&&state.turn===state.me)html+='<button id="finish">إنهاء دوري في الكلام</button>';return html;}
function ballot(){
  if(state.phase!=='vote')return '';
  const entries=Object.entries(state.votes);
  const total=state.players.filter(p=>p.alive && (state.round===1 || !state.tied.includes(p.id))).length;
  const last=entries.at(-1);
  return `<div class="ballot" aria-live="polite"><small>🗳️ الأصوات المسجّلة: ${entries.length} من ${total}</small><progress value="${entries.length}" max="${Math.max(total,1)}"></progress>${last?`<p><b>${escape(name(last[0]))}</b> صوّت على <b>${escape(name(last[1]))}</b></p>`:'<p>نستناو أول صوت…</p>'}</div>`;
}
let lastScene='', lastBallot='';
function animateScene(){
  const phase=state?.phase||'home';
  app.dataset.scene=phase;
  document.body.dataset.sky=['wolves','witch','doctor'].includes(phase)?'night':
    phase==='vote'?'vote':['dawn','speech','debate','result'].includes(phase)?'day':'home';
  const scene=[state?.code,state?.day,phase,state?.round].join('/');
  const vote=phase==='vote'?[scene,Object.keys(state.votes).length,state.turn].join('/'):'';
  if(scene!==lastScene)app.querySelector('.phase')?.classList.add('arrive');
  if(vote && vote!==lastBallot)app.querySelector('.ballot')?.classList.add('cast');
  lastScene=scene;lastBallot=vote;
}
function game(){let night=['wolves','witch','doctor'].includes(state.phase);let speaker=state.turn?name(state.turn):null;return `<section class="panel phase"><small>${night?'🌙 الليلة':'☀️ اليوم'} ${state.day} • ${state.phase==='vote'?'جولة '+state.round:'مرحلة اللعب'}</small><h2>${phases[state.phase]}</h2>${ballot()}${state.paused?'<p class="red">اللعبة متوقفة — بانتظار لاعب غير متصل</p>':state.winner?`<h1 class="gold">${state.winner==='wolves'?'🐺 فازت الذئاب':'🌾 فازت القرية'}</h1>`:speaker?`<p class="green">${state.phase==='vote'?'يصوّت الآن':'يتحدث الآن'}: ${escape(speaker)}</p>`:night?'<p class="muted">القرية نائمة… انتظر دورك</p>':''}${state.remaining!==null?'<div class="clock" id="clock">--:--</div>':''}${state.note&&!night?`<p>${escape(state.note)}</p>`:''}${state.tied.length&&['debate','vote'].includes(state.phase)?`<p class="gold">المتعادلون: ${state.tied.map(i=>escape(name(i))).join('، ')}</p>`:''}</section>${state.deaths.length?`<section class="panel notice"><h3>الإقصاءات المعلنة</h3>${state.deaths.map(d=>`<p>☠️ ${escape(d.name)} — ${roles[d.role]}</p>`).join('')}</section>`:''}${packChannel()?audioPanel():''}${action()}${players()}${state.role?`<section class="panel role"><small>🔒 دورك السري</small><h2>${emojis[state.role]} ${roles[state.role]}</h2>${state.private.potions?`<small>جرعة الحياة: ${+state.private.potions.life} • جرعة الموت: ${+state.private.potions.death}</small>`:''}${state.private.wolves?`<small>فريقك: ${state.private.wolves.map(i=>escape(name(i))).join('، ')}</small>`:''}</section>`:''}${Object.keys(state.votes).length&&!night?`<section class="panel"><h3>الأصوات العلنية</h3>${Object.entries(state.votes).map(([a,b])=>`<div class="vote-row">${escape(name(a))} ← صوّت لـ <b>${escape(name(b))}</b></div>`).join('')}</section>`:''}${packChannel()?'':audioPanel()}${state.test?'<button class="secondary" id="leave">إنهاء التجربة / تجربة جديدة</button>':state.phase==='end'?'<button id="leave">العودة إلى البداية</button>':''}`}
function bind(id,fn){const el=document.getElementById(id);if(el)el.onclick=fn;}
function render(){const oldName=document.querySelector('#player-name')?.value||'',oldCode=document.querySelector('#room-code')?.value,oldTestCount=document.querySelector('#test-count')?.value,oldTestRole=document.querySelector('#test-role')?.value;app.innerHTML=state?header()+`<div class="row"><small>الغرفة <b dir="ltr">${state.code}</b></small><small>${state.test?'🧪 اختبار فردي':state.host===state.me?'أنت صاحب الغرفة':''}</small></div>`+(state.phase==='lobby'?lobby():game()):home();animateScene();showDawn();bind('effects',()=>{effectsOn=!effectsOn;localStorage.setItem('wolf-effects',effectsOn?'on':'off');if(effectsOn){unlockEffects();playCue('dawn')}render()});if(!state){document.querySelector('#player-name').value=oldName;if(oldCode!=null)document.querySelector('#room-code').value=oldCode;if(oldTestCount)document.querySelector('#test-count').value=oldTestCount;if(oldTestRole)document.querySelector('#test-role').value=oldTestRole;bind('create',()=>send({type:'create',name:document.querySelector('#player-name').value}));bind('test-create',()=>{const count=Number(document.querySelector('#test-count').value),role=document.querySelector('#test-role').value;if(role==='wolf'&&count<7){error('الذئب العادي يحتاج 7 لاعبين على الأقل');return}send({type:'create_test',name:document.querySelector('#player-name').value||'أنا',count,role})});bind('join',()=>send({type:'join',name:document.querySelector('#player-name').value,code:document.querySelector('#room-code').value.trim().toUpperCase()}));return}
  bind('audio',async()=>{try{await audio.setup();render()}catch(e){error('تعذر تفعيل الصوت: '+e.message)}});
  bind('mic-toggle',async()=>{try{if(audio.muted)await audio.setup();audio.setMuted(!audio.muted);render()}catch(e){error('تعذر تفعيل الصوت: '+e.message)}});
  bind('share',async()=>{const url=location.origin+'/?room='+state.code;try{if(navigator.share)await navigator.share({title:'ليلة الذئاب',url});else{await navigator.clipboard.writeText(url);error('تم نسخ الرابط')}}catch{}});
  bind('start',()=>send({type:'start'}));bind('leave',()=>{sessionStorage.removeItem('wolf-session');session=null;location.href=state?.test?'/?solo=1':'/'});
  document.querySelectorAll('[data-setting],#wolf-count').forEach(el=>el.onchange=()=>{const s={...state.settings};document.querySelectorAll('[data-setting]').forEach(e=>s[e.dataset.setting]=Number(e.value));const count=Number(document.querySelector('#wolf-count').value);s.single=count===1;s.extra=count===3;send({type:'settings',settings:s})});
  document.querySelectorAll('.kick').forEach(el=>el.onclick=()=>{if(confirm('هل تريد إقصاء '+name(el.dataset.id)+'؟'))send({type:'kick',target:el.dataset.id})});
  for(const k of ['kill','silence']){const e=document.getElementById(k);if(e)e.onchange=()=>draft[k]=e.value}document.querySelectorAll('[data-wolf]').forEach(el=>el.onclick=()=>{const k=el.dataset.wolf,t=document.getElementById(k).value;if(t)send({type:k,target:t});else error('اختر لاعباً أولاً')});bind('skip-silence',()=>send({type:'silence',target:null}));
  const sel=document.querySelector('#target');if(sel)sel.onchange=()=>draft.target=sel.value;const save=document.querySelector('#save');if(save)save.onchange=()=>draft.save=save.checked;
  bind('witch',()=>send({type:'witch',save:draft.save,target:draft.target||null}));for(const k of ['protect','vote'])bind(k,()=>{if(draft.target)send({type:k,target:draft.target});else error('اختر لاعباً أولاً')});bind('finish',()=>send({type:'finish'}));updateClock();}
function updateClock(){expireSpeech();const e=document.querySelector('#clock');if(e&&timerEnd!==null){const s=Math.ceil(state.paused?state.remaining:Math.max(0,(timerEnd-performance.now())/1000));e.textContent=String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}setInterval(updateClock,150);render();connect();
