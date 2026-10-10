import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cat_cafe_sim.cafe_new_game import create_game
from cat_cafe_sim.unity_state_server import make_server


class UnitySaveSlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = create_game(self.root / 'source')
        self.start_server()

    def start_server(self):
        self.server = make_server(self.session, 0, self.root / 'saves')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def get(self, route):
        with urlopen(self.base + route) as reply:
            return json.load(reply)

    def command(self, kind='save_game', **fields):
        state = self.get('/state')
        return dict(request_id=uuid.uuid4().hex, instance_id=state['instance_id'],
                    expected_revision=state['revision'], working_cats=[], kind=kind, **fields)

    def post(self, command):
        request = Request(self.base + '/commands', data=json.dumps(command).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request) as reply:
                return reply.status, json.load(reply)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_slot_replacement_retry_old_saves_and_restart(self):
        self.assertEqual(self.post(self.command())[0], 200)
        legacy = self.get('/saves')['saves'][0]
        command = self.command(save_slot=3)
        first_reply = self.post(command)
        self.assertEqual(first_reply[0], 200)
        first = self.get('/saves')['saves'][0]
        self.assertEqual(first['slot'], 3)
        old_files = {p.name: p.read_bytes() for p in (self.root / 'saves' / first['save_id']).iterdir()}
        self.assertEqual(self.post(command), first_reply)
        self.assertEqual(len(self.get('/saves')['saves']), 2)
        self.assertEqual(self.post(self.command(save_slot=3))[0], 200)
        rows = self.get('/saves')['saves']
        replacement = next(r for r in rows if r['slot'] == 3)
        self.assertNotEqual(replacement['save_id'], first['save_id'])
        self.assertEqual(len(rows), 2)
        self.assertIn(legacy['save_id'], [r['save_id'] for r in rows])
        self.assertEqual(old_files, {p.name: p.read_bytes() for p in (self.root / 'saves' / first['save_id']).iterdir()})
        self.assertEqual(self.post(self.command('load_game', save_id=replacement['save_id']))[0], 200)
        self.stop_server()
        self.start_server()
        self.assertEqual(next(r for r in self.get('/saves')['saves'] if r['slot'] == 3)['save_id'], replacement['save_id'])

    def test_failed_replacement_keeps_published_slot_and_game_state(self):
        self.assertEqual(self.post(self.command(save_slot=1))[0], 200)
        before = self.get('/state')
        rows = self.get('/saves')
        with patch('cat_cafe_sim.storage.cafe_saves.save_game', side_effect=OSError('disk full')):
            self.assertEqual(self.post(self.command(save_slot=1))[0], 422)
        self.assertEqual(self.get('/saves'), rows)
        self.assertEqual(self.get('/state'), before)
        self.assertEqual(self.post(self.command('load_game', save_id=rows['saves'][0]['save_id']))[0], 200)

    def test_invalid_slot_and_slot_on_other_command_rejected(self):
        before = self.get('/state')
        for slot in (-1, 11, True, '1', None):
            with self.subTest(slot=slot):
                self.assertEqual(self.post(self.command(save_slot=slot))[0], 400)
        self.assertEqual(self.post(self.command('new_game', choice='popularity', save_slot=1))[0], 400)
        self.assertEqual(self.get('/state'), before)
        self.assertEqual(self.get('/saves')['saves'], [])


if __name__ == '__main__':
    unittest.main()
