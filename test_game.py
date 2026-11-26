import unittest, asyncio, json
from aiohttp.test_utils import TestServer, TestClient
from aiohttp import WSMsgType
from server import Game,Player,create_app,ROOMS
class Online:
    closed=False
class Logic(unittest.TestCase):
    def test_single_wolf_five_players_both_powers(self):
        ps=[Player(f'p{i}') for i in range(5)];g=Game('SOLO',ps[0]);g.players={p.id:p for p in ps}
        for p in ps:p.ws=Online()
        g.act(g.host,{'type':'settings','settings':{'single':True,'extra':True}})
        self.assertFalse(g.settings['extra'])
        g.start(g.host)
        self.assertEqual(len(g.wolves()),1)
        wolf=g.wolves()[0];self.assertEqual(g.powers(),{'kill':wolf,'silence':wolf})
        self.assertEqual(sorted(p.role for p in ps),['black','doctor','villager','villager','witch'])
        villagers=[p.id for p in ps if p.role=='villager']
        g.act(wolf,{'type':'kill','target':villagers[0]});self.assertEqual(g.phase,'wolves')
        g.act(wolf,{'type':'silence','target':villagers[1]});self.assertEqual(g.phase,'witch')
        g.act(g.role('witch'),{'type':'witch','save':False,'target':None})
        g.act(g.role('doctor'),{'type':'protect','target':g.role('doctor')})
        self.assertFalse(g.players[villagers[0]].alive);self.assertEqual(g.silenced,villagers[1]);self.assertIsNone(g.winner)
        g.eliminate(wolf,'vote');self.assertTrue(g.check_win());self.assertEqual(g.winner,'village')

    def make(self,extra=False):
        roles=['black','silent','witch','doctor','villager','villager','villager','villager']+(['wolf'] if extra else [])
        ps=[Player(r+str(i)) for i,r in enumerate(roles)]; g=Game('TEST',ps[0]); g.players={p.id:p for p in ps}
        for p,r in zip(ps,roles):p.role=r;p.ws=Online()
        g.night();return g,ps
    def test_secret_and_voice(self):
        g,p=self.make();b,s,w,d,v,*_=p
        self.assertEqual(g.voice_targets(b.id),[s.id]);self.assertEqual(g.voice_targets(v.id),[])
        view=g.view(v.id);self.assertIsNone(view['players'][0]['role']);self.assertEqual(view['private'],{})
        self.assertEqual(g.view(b.id)['private']['wolves'],[b.id,s.id]);self.assertNotIn(b.id,g.valid_targets(b.id,'kill'));self.assertIn(b.id,g.valid_targets(s.id,'silence'))
    def test_witch_doctor_and_silence(self):
        g,p=self.make();b,s,w,d,v,v2,*_=p
        g.act(b.id,{'type':'kill','target':v.id});g.act(s.id,{'type':'silence','target':v2.id});self.assertEqual(g.phase,'witch')
        self.assertEqual(g.view(w.id)['private']['witch']['victim'],v.id)
        g.act(w.id,{'type':'witch','save':True,'target':d.id});self.assertEqual(g.phase,'doctor');self.assertNotIn('witch',g.view(d.id)['private'])
        g.act(d.id,{'type':'protect','target':d.id});self.assertTrue(v.alive and d.alive);self.assertEqual(g.potions,{'life':False,'death':False});self.assertEqual(g.silenced,v2.id)
        self.assertNotIn(v2.id,[g.turn]+g.queue);g.night();self.assertNotIn(v2.id,g.valid_targets(s.id,'silence'));self.assertNotIn(d.id,g.valid_targets(d.id,'protect'))
    def test_dawn_precedes_speech_and_only_reports_effective_saves(self):
        for potion,poison,expected in [(False,False,True),(True,False,False),(True,True,True)]:
            g,players=self.make()
            black,silent,witch,doctor,victim,muted,*_=players
            g.actions={'kill':victim.id,'protect':victim.id,'silence':muted.id,'save':potion}
            if poison:g.actions['witchkill']=victim.id
            g.resolve_night()
            view=g.view(muted.id)
            self.assertEqual(view['phase'],'dawn')
            self.assertEqual(view['doctorSaved'],expected)
            self.assertIsNone(view['turn'])
            self.assertEqual(view['silenced'],muted.id)
            self.assertEqual(view['private'],{})
            self.assertFalse(any(g.can_talk(p.id) for p in players))
            g.deadline=0;g.tick()
            self.assertEqual(g.phase,'speech')
            self.assertNotIn(muted.id,[g.turn]+g.queue)

    def test_default_timers_and_vote_timeout(self):
        g,players=self.make()
        for key in ('speech','debate','vote','wolves','witch','doctor'):
            self.assertEqual(g.settings[key],60)
        g.begin_vote(False)
        first=g.turn
        self.assertAlmostEqual(g.view(first)['remaining'],60,delta=1)
        g.deadline=0;g.tick()
        self.assertNotEqual(g.turn,first)
        self.assertEqual(g.votes,{})
        self.assertAlmostEqual(g.view(g.turn)['remaining'],60,delta=1)
        while g.phase=='vote':
            g.deadline=0;g.tick()
        self.assertEqual(g.phase,'wolves')

    def test_secrets_only_revealed_at_end(self):
        g,players=self.make()
        black,silent,witch,doctor,victim,muted,*_=players
        g.act(black.id,{'type':'kill','target':victim.id})
        g.act(silent.id,{'type':'silence','target':muted.id})
        g.act(witch.id,{'type':'witch','save':False,'target':None})
        g.act(doctor.id,{'type':'protect','target':victim.id})
        g.night()
        for p in players:self.assertNotIn('history',g.view(p.id)['private'])
        for wolf in (black,silent):g.eliminate(wolf.id,'vote')
        self.assertTrue(g.check_win())
        for p in players:
            first,last=g.view(p.id)['private']['history']
            self.assertEqual(first['actions'],{'kill':victim.id,'silence':muted.id,'protect':victim.id})
            self.assertTrue(first['resolved'])
            self.assertEqual(first['out'],[])
            self.assertEqual([d['id'] for d in last['out']],[black.id,silent.id])

    def test_inheritance(self):
        g,p=self.make(True);b,s,*_=p;normal=p[-1];g.eliminate(b.id,'vote');self.assertEqual(g.powers(),{'kill':s.id,'silence':s.id});g.eliminate(s.id,'vote');self.assertEqual(g.powers(),{'kill':normal.id,'silence':normal.id})
    def test_vote_tie_and_debate(self):
        g,p=self.make();g.silenced=p[0].id;g.begin_speech(False)
        while g.phase=='speech':g.act(g.turn,{'type':'finish'})
        a,b=p[:2];i=0
        while g.phase=='vote':g.act(g.turn,{'type':'vote','target':[a.id,b.id][i%2]});i+=1
        self.assertEqual(g.phase,'debate');self.assertEqual(set(g.tied),{a.id,b.id});self.assertIn(a.id,[g.turn]+g.queue)
        while g.phase=='debate':g.act(g.turn,{'type':'finish'})
        self.assertNotIn(a.id,[g.turn]+g.queue);self.assertNotIn(b.id,[g.turn]+g.queue);self.assertIsNotNone(g.deadline)
        i=0
        while g.phase=='vote':g.act(g.turn,{'type':'vote','target':[a.id,b.id][i%2]});i+=1
        self.assertEqual(g.phase,'result');self.assertTrue(all(x.alive for x in p));g.deadline=0;g.tick();self.assertEqual(g.phase,'wolves');self.assertEqual(g.day,2)
    def test_witch_without_life(self):
        g,p=self.make();b,s,w,d,v,*_=p;g.potions['life']=False;g.act(b.id,{'type':'kill','target':v.id});g.act(s.id,{'type':'silence','target':v.id});self.assertIsNone(g.view(w.id)['private']['witch']['victim']);self.assertEqual(g.view(d.id)['private'],{})
    def test_pause_and_win(self):
        g,p=self.make();p[-1].ws=None;g.check_pause();self.assertTrue(g.paused_at);self.assertFalse(g.can_talk(p[0].id));g.act(g.host,{'type':'kick','target':p[-1].id});self.assertFalse(p[-1].alive);self.assertIsNone(g.paused_at)
        g.eliminate(p[0].id,'vote');g.eliminate(p[1].id,'vote');self.assertTrue(g.check_win());self.assertEqual(g.winner,'village')
class Network(unittest.IsolatedAsyncioTestCase):
    async def test_lobby_voice_is_bidirectional_and_room_isolated(self):
        ROOMS.clear();client=TestClient(TestServer(create_app()));await client.start_server();socks=[]
        async def read_state(ws):
            while True:
                msg=await ws.receive(timeout=2)
                if msg.type==WSMsgType.TEXT:
                    d=json.loads(msg.data)
                    if d['type']=='state':return d
        try:
            for i in range(3):
                ws=await client.ws_connect('/ws');socks.append(ws)
                await ws.send_json({'type':'join' if i==1 else 'create','name':f'lobby{i}','code':code if i==1 else ''})
                d=await read_state(ws)
                self.assertTrue(d['talk']);self.assertEqual(d['phase'],'lobby')
                if i==0:code=d['code']
            await read_state(socks[0])  # First player sees the second join.
            for sender,receiver in [(0,1),(1,0)]:
                await socks[sender].send_bytes(bytes(640))
                msg=await socks[receiver].receive(timeout=2)
                self.assertEqual(msg.type,WSMsgType.BINARY);self.assertEqual(len(msg.data),648)
                with self.assertRaises(asyncio.TimeoutError):await socks[2].receive(timeout=.15)
        finally:
            for ws in socks:await ws.close()
            await client.close();ROOMS.clear()

    async def test_actual_websocket_audio_isolation(self):
        ROOMS.clear();client=TestClient(TestServer(create_app()));await client.start_server();socks=[]
        async def read_state(ws):
            while True:
                msg=await ws.receive(timeout=2)
                if msg.type==WSMsgType.TEXT:
                    d=json.loads(msg.data)
                    if d['type']=='state':return d
        try:
            for i in range(5):
                ws=await client.ws_connect('/ws');socks.append(ws);await ws.send_json({'type':'create' if i==0 else 'join','name':f'p{i}','code':code if i else ''});d=await read_state(ws);code=d['code']
            await socks[0].send_json({'type':'start'});states=[]
            for ws in socks:
                while True:
                    d=await read_state(ws)
                    if d['phase']=='wolves':states.append(d);break
            wolves=[i for i,d in enumerate(states) if d['role'] in ('black','silent')];v=next(i for i in range(5) if i not in wolves)
            await socks[wolves[0]].send_bytes(bytes(640));msg=await socks[wolves[1]].receive(timeout=2);self.assertEqual(msg.type,WSMsgType.BINARY);self.assertEqual(len(msg.data),648)
            with self.assertRaises(asyncio.TimeoutError):await socks[v].receive(timeout=.15)
            await socks[v].send_bytes(bytes(640))
            with self.assertRaises(asyncio.TimeoutError):await socks[wolves[0]].receive(timeout=.15)
            ghosts=[i for i in range(5) if i not in wolves][:2]
            game=ROOMS[code]
            for i in ghosts:game.eliminate(states[i]['me'],'night')
            frame=bytes([7])*640
            for sender,receiver in [ghosts,ghosts[::-1]]:
                self.assertTrue(game.view(states[sender]['me'])['talk'])
                await socks[sender].send_bytes(frame)
                packet=await socks[receiver].receive_bytes(timeout=2)
                self.assertEqual(packet,bytes.fromhex(states[sender]['me'])+frame)
                with self.assertRaises(asyncio.TimeoutError):await socks[wolves[0]].receive(timeout=.1)
            await socks[wolves[0]].send_bytes(frame)
            await socks[wolves[1]].receive_bytes(timeout=2)
            with self.assertRaises(asyncio.TimeoutError):await socks[ghosts[0]].receive(timeout=.1)
            for phase in ('speech','debate'):
                game.setphase(phase);game.turn=states[wolves[0]]['me']
                await socks[wolves[0]].send_bytes(frame)
                for i in ghosts:
                    self.assertEqual((await socks[i].receive_bytes(timeout=2))[8:],frame)
        finally:
            for ws in socks:await ws.close()
            await client.close();ROOMS.clear()
if __name__=='__main__':unittest.main(verbosity=2)
