import asyncio, json, random, secrets, time, os, re
from pathlib import Path
from aiohttp import web, WSMsgType

ROOT=Path(__file__).parent
ROLES={'black':'الذئب الأسود','silent':'الذئب المُسكِت','wolf':'الذئب العادي','doctor':'الطبيب','witch':'الساحر','villager':'القروي البسيط'}
WOLVES={'black','silent','wolf'}
ROOMS={}
RNG=random.SystemRandom()

def now(): return time.monotonic()
def require(ok,msg):
    if not ok: raise ValueError(msg)
def choice(v, values, default): return v if v in values else default

class Player:
    def __init__(self,name,bot=False):
        self.id=secrets.token_hex(8); self.token=secrets.token_urlsafe(32); self.name=name
        self.bot=bot; self.role=None; self.alive=True; self.ws=None; self.last_audio=0; self.audio_budget=10; self.audio_at=now()
    @property
    def online(self): return self.bot or (self.ws is not None and not self.ws.closed)

class Game:
    def __init__(self,code,owner):
        self.test=False; self.test_role=None; self.bot_due=0; self.code=code; self.players={owner.id:owner}; self.host=owner.id; self.phase='lobby'; self.day=0
        self.settings={'speech':60,'debate':120,'wolves':120,'witch':30,'doctor':30,'single':False,'extra':False}
        self.deadline=None; self.paused_at=None; self.turn=None; self.queue=[]; self.votes={}; self.round=1; self.tied=[]; self.rotation=0
        self.actions={}; self.potions={'life':True,'death':True}; self.last_silenced=None; self.silenced=None; self.last_doctor=None
        self.deaths=[]; self.winner=None; self.note=''; self.caps={}; self.created=now(); self.activity=now()
    def alive(self): return [p.id for p in self.players.values() if p.alive]
    def wolves(self): return [i for i in self.alive() if self.players[i].role in WOLVES]
    def role(self,r): return next((i for i in self.alive() if self.players[i].role==r),None)
    def order(self, ids):
        allids=list(self.players); n=len(allids); start=(self.rotation-1)%n
        return [i for i in allids[start:]+allids[:start] if i in ids]
    def setphase(self,phase,seconds=None):
        self.phase=phase; self.deadline=now()+seconds if seconds else None; self.turn=None; self.queue=[]; self.paused_at=None
        self.check_pause()
    def check_pause(self):
        blocked= self.phase not in ('lobby','end') and any(not self.players[i].online for i in self.alive())
        if blocked and self.paused_at is None: self.paused_at=now()
        if not blocked and self.paused_at is not None:
            if self.deadline is not None: self.deadline+=now()-self.paused_at
            self.paused_at=None
    def start(self,actor):
        require(actor==self.host and self.phase=='lobby','صاحب الغرفة فقط يمكنه بدء اللعبة')
        n=len(self.players); require(n>=5,'تحتاج إلى خمسة لاعبين على الأقل'); require(all(p.online for p in self.players.values()),'انتظر اتصال جميع اللاعبين')
        wolf_roles=['black'] if self.settings['single'] else ['black','silent']+(['wolf'] if self.settings['extra'] else [])
        roles=wolf_roles+['doctor','witch']
        require(n>2*len(wolf_roles),'الذئاب يجب أن يكونوا أقل من نصف اللاعبين')
        roles+=['villager']*(n-len(roles)); RNG.shuffle(roles)
        if self.test and self.test_role:
            require(self.test_role in roles,'الدور المختار غير موجود ضمن الإعدادات')
            idx=roles.index(self.test_role); roles[0],roles[idx]=roles[idx],roles[0]
        for p,r in zip(self.players.values(),roles): p.role=r
        self.night()
    def powers(self):
        w=self.wolves(); b=self.role('black'); s=self.role('silent'); normal=self.role('wolf')
        return {'kill':b or s or normal,'silence':s or b or normal} if w else {}
    def night(self):
        if self.check_win(): return
        self.day+=1; self.rotation+=1; self.actions={}; self.deaths=[]; self.note=''; self.votes={}; self.tied=[]; self.round=1; self.silenced=None
        self.caps=self.powers(); self.setphase('wolves',self.settings['wolves'])
    def witch_phase(self):
        self.setphase('witch',self.settings['witch'])
        if not self.role('witch') or not any(self.potions.values()): self.doctor_phase()
    def doctor_phase(self):
        self.setphase('doctor',self.settings['doctor'])
        if not self.role('doctor'): self.resolve_night()
    def check_win(self):
        if self.phase=='lobby': return False
        w=len(self.wolves()); v=len(self.alive())-w
        if w==0 or w>=v:
            self.winner='village' if w==0 else 'wolves'; self.setphase('end'); return True
        return False
    def eliminate(self,i,cause):
        if i in self.players and self.players[i].alive:
            self.players[i].alive=False; self.deaths.append({'id':i,'name':self.players[i].name,'role':self.players[i].role,'cause':cause})
    def resolve_night(self):
        a=self.actions; protect=a.get('protect'); victim=a.get('kill'); saved=a.get('save')
        if victim and victim!=protect and not saved: self.eliminate(victim,'night')
        victim2=a.get('witchkill')
        if victim2 and victim2!=protect: self.eliminate(victim2,'night')
        self.last_doctor=protect; self.last_silenced=a.get('silence'); self.silenced=self.last_silenced if self.last_silenced in self.alive() else None
        self.note='انتهت الليلة. لم يمت أحد.' if not self.deaths else 'انتهت الليلة.'
        if not self.check_win(): self.begin_speech(False)
    def begin_speech(self,debate):
        self.setphase('debate' if debate else 'speech'); self.queue=self.order([i for i in (self.tied if debate else self.alive()) if i in self.alive() and (debate or i!=self.silenced)])
        self.next_speech()
    def next_speech(self):
        if self.queue:
            self.turn=self.queue.pop(0); self.deadline=(self.paused_at or now())+self.settings['debate' if self.phase=='debate' else 'speech']
        else: self.begin_vote(self.phase=='debate')
    def begin_vote(self,second):
        self.round=2 if second else 1; self.votes={}; self.setphase('vote')
        self.queue=self.order([i for i in self.alive() if not second or i not in self.tied]); self.next_vote()
    def next_vote(self):
        if self.queue: self.turn=self.queue.pop(0)
        else: self.finish_vote()
    def finish_vote(self):
        counts={i:0 for i in self.alive() if self.round==1 or i in self.tied}
        for v in self.votes.values():
            if v in counts: counts[v]+=1
        if not counts or not self.votes: self.night(); return
        top=max(counts.values()); tied=[i for i,v in counts.items() if v==top]
        if len(tied)==1:
            self.eliminate(tied[0],'vote'); self.note='تم إقصاء '+self.players[tied[0]].name
            if not self.check_win(): self.setphase('result',5)
        elif self.round==1:
            self.tied=tied; self.note='تعادل في التصويت — المناظرة'; self.begin_speech(True)
        else:
            self.note='تعادل للمرة الثانية، لا إقصاء'; self.setphase('result',5)
    def valid_targets(self,actor,kind):
        a=self.alive()
        if kind=='kill': return [i for i in a if i not in self.wolves()]
        if kind=='silence': return [i for i in a if i!=self.last_silenced and i!=actor]
        if kind=='protect': return [i for i in a if not(i==actor and self.last_doctor==actor)]
        if kind=='witchkill': return [i for i in a if i!=actor]
        if kind=='vote': return [i for i in a if self.round==1 or i in self.tied]
        return []
    def act(self,i,d):
        p=self.players[i]; k=d.get('type'); self.activity=now()
        if k=='settings':
            require(i==self.host and self.phase=='lobby','الإعدادات لصاحب الغرفة فقط')
            s=d.get('settings',{}); require(isinstance(s,dict),'إعدادات غير صالحة')
            for key,vals in {'speech':[30,60,90,120],'debate':[60,120,180],'wolves':[60,120,180],'witch':[15,30,60],'doctor':[15,30,60]}.items(): self.settings[key]=choice(s.get(key),vals,self.settings[key])
            single=s.get('single') is True; extra=s.get('extra') is True and not single
            if self.test:
                require(not extra or len(self.players)>=7,'ثلاثة ذئاب تحتاج سبعة لاعبين')
                require(not single or self.test_role not in ('silent','wolf'),'عدد الذئاب لا يناسب دورك')
                require(self.test_role!='wolf' or extra,'الذئب العادي يحتاج ثلاثة ذئاب')
            self.settings['single']=single
            self.settings['extra']=extra; return
        if k=='start': self.start(i); return
        if k=='kick':
            target=d.get('target'); require(i==self.host and target in self.players and target!=i and not self.players[target].online,'يمكن إقصاء لاعب غير متصل فقط')
            if self.phase=='lobby': del self.players[target]; return
            require(self.phase!='end' and self.players[target].alive,'اللاعب غير متاح')
            self.eliminate(target,'disconnect'); self.queue=[x for x in self.queue if x!=target]
            self.tied=[x for x in self.tied if x!=target]; self.votes={a:b for a,b in self.votes.items() if a!=target}
            if self.check_win(): return
            self.check_pause()
            if self.phase in ('speech','debate') and self.turn==target: self.next_speech()
            elif self.phase=='vote' and self.turn==target: self.next_vote()
            elif self.phase=='wolves':
                self.caps=self.powers()
                if all(x in self.actions for x in self.caps): self.witch_phase()
            elif self.phase=='witch' and self.role('witch') is None: self.doctor_phase()
            elif self.phase=='doctor' and self.role('doctor') is None: self.resolve_night()
            return
        require(p.alive and self.phase not in ('lobby','end') and self.paused_at is None,'لا يمكنك تنفيذ إجراء الآن')
        if k in ('kill','silence'):
            require(self.phase=='wolves' and self.caps.get(k)==i and k not in self.actions,'ليس دورك أو تم تأكيد الاختيار')
            t=d.get('target'); require(t in self.valid_targets(i,k) or (k=='silence' and t is None),'اختيار غير مسموح')
            self.actions[k]=t
            if all(x in self.actions for x in self.caps): self.witch_phase()
        elif k=='witch':
            require(self.phase=='witch' and p.role=='witch','ليس دور الساحر')
            save=d.get('save') is True; target=d.get('target')
            require(not save or (self.potions['life'] and self.actions.get('kill') in self.alive()),'جرعة الحياة غير متاحة')
            require(target is None or (self.potions['death'] and target in self.valid_targets(i,'witchkill')),'جرعة الموت غير متاحة')
            if save: self.potions['life']=False; self.actions['save']=True
            if target is not None: self.potions['death']=False; self.actions['witchkill']=target
            self.doctor_phase()
        elif k=='protect':
            require(self.phase=='doctor' and p.role=='doctor','ليس دور الطبيب'); t=d.get('target'); require(t in self.valid_targets(i,k),'لا يمكن حماية هذا اللاعب')
            self.actions[k]=t; self.resolve_night()
        elif k=='finish':
            require(self.phase in ('speech','debate') and self.turn==i,'ليس دورك في الكلام'); self.next_speech()
        elif k=='vote':
            require(self.phase=='vote' and self.turn==i and i not in self.votes,'ليس دورك في التصويت'); t=d.get('target'); require(t in self.valid_targets(i,k),'اختيار غير مسموح'); self.votes[i]=t; self.next_vote()
        else: raise ValueError('إجراء غير معروف')
    def bot_step(self):
        if not self.test or self.paused_at is not None or now()<self.bot_due: return False
        move=None; actor=None
        if self.phase=='wolves':
            for k,i in self.caps.items():
                if self.players[i].bot and k not in self.actions:
                    targets=self.valid_targets(i,k)
                    if targets or k=='silence': actor=i; move={'type':k,'target':RNG.choice(targets) if targets else None}; break
        elif self.phase=='witch':
            i=self.role('witch')
            if i and self.players[i].bot:
                actor=i; move={'type':'witch','save':bool(self.potions['life'] and self.actions.get('kill') in self.alive() and RNG.random()<.65),'target':None}
                targets=self.valid_targets(i,'witchkill')
                if self.potions['death'] and targets and RNG.random()<.25: move['target']=RNG.choice(targets)
        elif self.phase=='doctor':
            i=self.role('doctor')
            if i and self.players[i].bot:
                targets=self.valid_targets(i,'protect')
                if targets: actor=i; move={'type':'protect','target':RNG.choice(targets)}
        elif self.phase in ('speech','debate','vote') and self.turn and self.players[self.turn].bot:
            actor=self.turn
            if self.phase=='vote':
                targets=self.valid_targets(actor,'vote')
                if targets:
                    other=[i for i in targets if i!=actor and (self.players[actor].role not in WOLVES or i not in self.wolves())]
                    move={'type':'vote','target':RNG.choice(other or targets)}
            else: move={'type':'finish'}
        if move:
            self.bot_due=now()+1.2; self.act(actor,move); return True
        return False
    def tick(self):
        if self.bot_step(): return True
        if self.paused_at is not None or self.deadline is None or now()<self.deadline: return False
        if self.phase=='wolves': self.witch_phase()
        elif self.phase=='witch': self.doctor_phase()
        elif self.phase=='doctor': self.resolve_night()
        elif self.phase in ('speech','debate'): self.next_speech()
        elif self.phase=='result': self.night()
        return True
    def voice_targets(self,i):
        if self.paused_at is not None or i not in self.alive(): return []
        if self.phase=='lobby': return [j for j in self.alive() if j!=i]
        if self.phase=='wolves' and i in self.wolves(): return [j for j in self.wolves() if j!=i]
        if self.phase in ('speech','debate') and self.turn==i: return [j for j in self.alive() if j!=i]
        return []
    def can_talk(self,i):
        return self.paused_at is None and i in self.alive() and (self.phase=='lobby' or (self.phase=='wolves' and i in self.wolves()) or (self.phase in ('speech','debate') and i==self.turn))
    def view(self,i):
        p=self.players[i]; private={}; reveal=self.phase=='end'; w=p.role in WOLVES and p.alive
        if w: private['wolves']=self.wolves()
        if self.phase=='wolves' and w:
            private['wolfActions']={k:{'targets':self.valid_targets(i,k),'chosen':self.actions.get(k),'done':k in self.actions} for k in self.caps if self.caps[k]==i}; private['wolfChoices']=self.actions.copy()
        if p.role=='witch' and p.alive:
            private['potions']=self.potions.copy()
            if self.phase=='witch':
                private['witch']={'victim':self.actions.get('kill') if self.potions['life'] else None,'targets':self.valid_targets(i,'witchkill') if self.potions['death'] else []}
        if self.phase=='doctor' and p.alive and p.role=='doctor': private['protect']=self.valid_targets(i,'protect')
        if self.phase=='vote' and self.turn==i and p.alive: private['vote']=self.valid_targets(i,'vote')
        return {'type':'state','test':self.test,'testRole':self.test_role,'code':self.code,'me':i,'host':self.host,'phase':self.phase,'day':self.day,'settings':self.settings,'turn':self.turn,'round':self.round,'tied':self.tied,'votes':self.votes,'silenced':self.silenced,'deaths':self.deaths,'note':self.note,'winner':self.winner,'paused':self.paused_at is not None,'remaining':max(0,self.deadline-(self.paused_at or now())) if self.deadline is not None else None,'role':p.role,'talk':self.can_talk(i),'private':private,'players':[{'id':q.id,'name':q.name,'bot':q.bot,'online':q.online,'alive':q.alive,'role':q.role if not q.alive or reveal or q.id==i or (w and q.id in self.wolves()) else None} for q in self.players.values()]}
    async def broadcast(self):
        await asyncio.gather(*(safe_send(p.ws,self.view(p.id)) for p in self.players.values() if p.online and not p.bot))

async def safe_send(ws,data):
    try: await ws.send_json(data)
    except (ConnectionError,RuntimeError): pass

def configure_test(g,d):
    count=d.get('count',8)
    require(type(count) is int and 5<=count<=30,'اختر بين 5 و30 لاعباً')
    role=choice(d.get('role'),list(ROLES)+['random'],'random')
    if role=='wolf' and count<7: raise ValueError('الذئب العادي يحتاج سبعة لاعبين على الأقل')
    g.settings['single']=count==5 and role not in ('silent','wolf')
    g.settings['extra']=role=='wolf'
    g.test_role=None if role=='random' else role
    for n in range(1,count):
        label=f'لاعب آلي {n}'
        if label==g.players[g.host].name: label+=' (آلي)'
        bot=Player(label,bot=True);g.players[bot.id]=bot
    g.bot_due=now()+1.2

def namecheck(n):
    require(isinstance(n,str) and 1<=len(n.strip())<=24,'اكتب اسماً من 1 إلى 24 حرفاً'); return n.strip()

async def socket(request):
    ws=web.WebSocketResponse(heartbeat=15,max_msg_size=8192); await ws.prepare(request); game=None; player=None
    try:
        async for msg in ws:
            if msg.type==WSMsgType.TEXT:
                try:
                    d=json.loads(msg.data); require(isinstance(d,dict),'طلب غير صالح'); typ=d.get('type')
                    if not player:
                        if typ in ('create','create_test'):
                            code=''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(6))
                            while code in ROOMS: code=''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(6))
                            new_player=Player(namecheck(d.get('name'))); new_game=Game(code,new_player)
                            if typ=='create_test': new_game.test=True; configure_test(new_game,d)
                            player=new_player; game=new_game; ROOMS[code]=game
                        elif typ=='join':
                            code=str(d.get('code','')).upper(); g=ROOMS.get(code); require(g is not None and g.phase=='lobby' and not g.test,'الغرفة غير موجودة أو بدأت اللعبة'); require(len(g.players)<30,'الغرفة ممتلئة'); name=namecheck(d.get('name')); require(all(p.name!=name for p in g.players.values()),'الاسم مستخدم'); player=Player(name); game=g; game.players[player.id]=player
                        elif typ=='resume':
                            g=ROOMS.get(str(d.get('code','')).upper()); p=next((p for p in g.players.values() if secrets.compare_digest(p.token,str(d.get('token','')))),None) if g else None; require(p is not None,'انتهت جلسة الغرفة'); game=g; player=p
                        else: raise ValueError('انضم إلى غرفة أولاً')
                        old=player.ws; player.ws=ws
                        if old and old is not ws: await old.close(code=4000,message=b'replaced')
                        game.activity=now(); game.check_pause(); await safe_send(ws,{'type':'session','code':game.code,'token':player.token}); await game.broadcast()
                    else:
                        require(player.ws is ws,'الجلسة غير نشطة'); game.act(player.id,d); await game.broadcast()
                except (ValueError,TypeError,KeyError) as e: await safe_send(ws,{'type':'error','message':str(e) if isinstance(e,ValueError) and not isinstance(e,json.JSONDecodeError) else 'طلب غير صالح'})
            elif msg.type==WSMsgType.BINARY and player and player.ws is ws:
                data=msg.data
                if len(data)!=640 or not game.can_talk(player.id): continue
                t=now(); player.audio_budget=min(10,player.audio_budget+(t-player.audio_at)*55); player.audio_at=t
                if player.audio_budget<1: continue
                player.audio_budget-=1
                async def relay(q):
                    try:
                        if q.online and not q.bot: await asyncio.wait_for(q.ws.send_bytes(bytes.fromhex(player.id)+data),.25)
                    except (ConnectionError,RuntimeError,asyncio.TimeoutError): pass
                await asyncio.gather(*(relay(game.players[j]) for j in game.voice_targets(player.id)))
    finally:
        if player and player.ws is ws:
            player.ws=None
            if game.host==player.id:
                nxt=next((q.id for q in game.players.values() if q.online and q.alive and not q.bot),None)
                if nxt: game.host=nxt
            game.check_pause(); await game.broadcast()
    return ws

async def ticker(app):
    while True:
        await asyncio.sleep(.15)
        for code,g in list(ROOMS.items()):
            if not any(p.online and not p.bot for p in g.players.values()) and now()-g.activity>(600 if g.test else 7200): ROOMS.pop(code,None); continue
            if g.tick(): await g.broadcast()
async def lifecycle(app):
    task=asyncio.create_task(ticker(app)); yield; task.cancel()
    try: await task
    except asyncio.CancelledError: pass
async def home(request): return web.FileResponse(ROOT/'public/index.html')
def create_app():
    app=web.Application(); app.router.add_get('/',home); app.router.add_get('/ws',socket); app.router.add_static('/static/',ROOT/'public'); app.cleanup_ctx.append(lifecycle); return app
if __name__=='__main__': web.run_app(create_app(),host='0.0.0.0',port=int(os.getenv('PORT','8080')))
