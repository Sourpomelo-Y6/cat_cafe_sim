import copy
import json
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cat_cafe_sim.cafe_interaction import CafeInteractionSession
from cat_cafe_sim.core.config import Config
from cat_cafe_sim.core.human_cat_relationship import RelationshipConfig
from cat_cafe_sim.core.human_cat_types import Personality
from cat_cafe_sim.storage.relationships import RelationshipStore
from cat_cafe_sim.storage.cafe_saves import save_game
from cat_cafe_sim.unity_state_server import make_server,state_view


def adoption_game(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    store=RelationshipStore(directory/'relationships.json')
    for key,name in [('cat-mike','ミケ'),('cat-sora','ソラ'),('cat-tama','タマ')]:
        store.register_cat(key,name,Personality())
        interaction=store.begin(replace(RelationshipConfig(),ticks=1,affinity_favorable=85,affinity_enthusiastic=85),key,'guest-1')
        interaction.step('direct');store.apply(interaction)
    session=CafeInteractionSession(store=store,seat_count=1,cafe_config=replace(Config.load(),initial_funds=1000,opening_ticks=6,arrival_ticks=(0,)),interaction_config=replace(RelationshipConfig(),ticks=1))
    save_game(session,directory/'cafe.json')
    return session


class UnityAdoptionTests(unittest.TestCase):
    def test_default_off_and_projection_do_not_change_saved_state(self):
        with tempfile.TemporaryDirectory() as directory:
            session=adoption_game(directory);before=session.core.snapshot();view=state_view(session)['adoption']
            self.assertEqual(session.core.snapshot(),before);self.assertIsNone(session.core.adoption)
            self.assertFalse(view['enabled']);self.assertTrue(view['can_configure']);self.assertEqual(view['events'],[])
            session.configure_adoption(True);session.automatic_step();session.automatic_step()
            before=session.core.snapshot();view=state_view(session)['adoption'];self.assertEqual(session.core.snapshot(),before)
            self.assertFalse(view['can_configure']);self.assertTrue(view['events'][0]['can_accept']);self.assertTrue(view['events'][0]['can_decline'])
            self.assertGreaterEqual(view['events'][0]['guest_affinity'],80)

    def test_http_choices_retries_history_and_save_restore(self):
        for choice in ('accept','decline'):
            with self.subTest(choice=choice),tempfile.TemporaryDirectory() as directory:
                session=adoption_game(Path(directory)/'source');originals={p:p.read_bytes() for p in session.checkpoint_path.parent.iterdir()}
                with make_server(session,0,Path(directory)/'saves') as server:
                    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
                    def read():
                        with urlopen(base+'/state') as response:return json.load(response)
                    def post(kind,command=None,**extra):
                        state=read();command=command or dict(kind=kind,request_id=uuid.uuid4().hex,instance_id=state['instance_id'],expected_revision=state['revision'],working_cats=[],**extra)
                        try:
                            with urlopen(Request(base+'/commands',json.dumps(command).encode(),{'Content-Type':'application/json'})) as response:return response.status,json.load(response),command
                        except HTTPError as ex:return ex.code,json.load(ex),command
                    try:
                        self.assertEqual(post('configure_adoption',choice='invalid')[0],400)
                        off=post('save_game')[1]['save_id'];code,result,command=post('configure_adoption',choice='on');self.assertEqual(code,200,result)
                        self.assertEqual(post('configure_adoption',command)[:2],(code,result));self.assertTrue(read()['adoption']['enabled'])
                        enabled=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=off)[0],200);self.assertFalse(read()['adoption']['enabled'])
                        self.assertEqual(post('load_game',save_id=enabled)[0],200);self.assertTrue(read()['adoption']['enabled'])
                        self.assertEqual(post('start_business')[0],200);self.assertEqual(post('advance_business')[0],200)
                        row=read()['adoption']['events'][0];waiting=post('save_game')[1]['save_id'];before=session.core.snapshot()
                        for kind,extra in [('configure_adoption',dict(choice='off')),('advance_business',{}),('resolve_adoption',dict(choice=choice,event_id='invalid',cat_id=row['cat_id'])),('resolve_adoption',dict(choice=choice,event_id=row['event_id'],cat_id='invalid'))]:
                            self.assertEqual(post(kind,**extra)[0],422);self.assertEqual(session.core.snapshot(),before)
                        self.assertEqual(post('resolve_adoption',choice=choice,cat_id=row['cat_id'])[0],400)
                        reference=copy.deepcopy(session);reference.resolve_adoption(row['event_id'],choice)
                        code,result,command=post('resolve_adoption',choice=choice,event_id=row['event_id'],cat_id=row['cat_id']);self.assertEqual(code,200,result)
                        self.assertEqual(session.core.snapshot(),reference.core.snapshot());self.assertEqual(post('resolve_adoption',command)[:2],(code,result))
                        self.assertEqual(session.core.activity(row['cat_id']),'adopted' if choice=='accept' else 'cafe')
                        self.assertEqual(post('resolve_adoption',choice='decline' if choice=='accept' else 'accept',event_id=row['event_id'],cat_id=row['cat_id'])[0],422)
                        final=read()['adoption']['events'][0];self.assertFalse(final['can_accept']);self.assertFalse(final['can_decline'])
                        resolved=post('save_game')[1]['save_id'];self.assertEqual(post('load_game',save_id=waiting)[0],200);self.assertEqual(read()['adoption']['events'][0],row)
                        self.assertEqual(post('load_game',save_id=resolved)[0],200);self.assertEqual(read()['adoption']['events'][0],final)
                        while not session.core.closed:session.automatic_step(auto_assign=True)
                        session.next_day();self.assertEqual(post('configure_adoption',choice='off')[0],200);self.assertEqual(read()['adoption']['events'][0],final)
                        if choice=='accept':
                            cat=next(r for r in read()['cats'] if r['cat_id']==row['cat_id']);self.assertFalse(cat['working']);self.assertFalse(cat['can_player_start']);self.assertIn('growth_details',cat)
                        self.assertEqual(originals,{p:p.read_bytes() for p in originals})
                    finally:server.shutdown();thread.join()
