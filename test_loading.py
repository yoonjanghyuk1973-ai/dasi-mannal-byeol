import json, os, socket, tempfile, threading, time, unittest, urllib.error, urllib.request

fd, DB = tempfile.mkstemp(prefix='memorial-test-', suffix='.db')
os.close(fd)
os.environ['MEMORIAL_DB'] = DB
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_KEY', None)
os.environ['ADMIN_TOKEN'] = 'test-admin-token'

import server


def start():
    global httpd
    httpd = server.http.server.ThreadingHTTPServer(('127.0.0.1', 0), server.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


PORT = start()


def call(path, headers=None, timeout=3, method='GET', payload=None):
    req = urllib.request.Request(
        'http://127.0.0.1:%d%s' % (PORT, path),
        data=payload,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def js(path, headers=None, timeout=3, method='GET', payload=None):
    status, raw = call(path, headers, timeout, method, payload)
    return status, json.loads(raw.decode())


class LoadingBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        started = time.perf_counter()
        status, body = js('/api/health', timeout=2)
        cls.health_dt = time.perf_counter() - started
        cls.health = (status, body)
        status, raw = call('/', timeout=2)
        cls.root = (status, raw)
        status, body = js('/api/pets', timeout=2)
        cls.pets_before_boot = (status, body)
        cls.summary_forbidden = js('/api/admin/summary', timeout=2)
        cls.summary_waiting = js('/api/admin/summary', {'X-Admin-Token': os.environ['ADMIN_TOKEN']}, timeout=2)

    def test_listener_answers_before_database_boot(self):
        status, body = self.health
        self.assertLess(self.health_dt, 1.0)
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertFalse(body['db'])
        status, raw = self.root
        self.assertEqual(status, 200)
        self.assertIn('불러오는 중이에요'.encode(), raw)
        self.assertIn(b'#/admin', raw)
        self.assertIn('다시 시도'.encode(), raw)
        status, body = self.pets_before_boot
        self.assertEqual(status, 503)
        self.assertFalse(body['db'])
        self.assertNotIn('letter', body)
        forbidden, denied = self.summary_forbidden
        self.assertEqual(forbidden, 403)
        self.assertNotIn('real_total', denied)
        authed, waiting = self.summary_waiting
        self.assertEqual(authed, 503)
        self.assertFalse(waiting['db'])
        self.assertNotIn('real_total', waiting)

    def test_summary_counts_hidden_memorials_without_personal_fields(self):
        server.boot()
        status, pets = js('/api/pets', timeout=3)
        self.assertEqual(status, 200)
        self.assertTrue(any(p.get('example') for p in pets))
        self.assertTrue(all(set(p) <= {'id', 'name', 'species', 'birth', 'passed', 'photo', 'candles', 'example'} for p in pets))
        before = js('/api/admin/summary', {'X-Admin-Token': os.environ['ADMIN_TOKEN']})[1]
        created = []
        for visibility, name in (('private', '로컬확인-비공개'), ('link', '로컬확인-링크')):
            code, row = js('/api/pets', method='POST', payload=json.dumps({
                'name': name, 'visibility': visibility, 'species': '고양이', 'letter': '비밀편지', 'owner': '보호자표시금지',
            }).encode(), headers={'Content-Type': 'application/json'})
            self.assertEqual(code, 200)
            self.assertIn('id', row)
            created.append(name)
        status, pets = js('/api/pets')
        listed = json.dumps(pets, ensure_ascii=False)
        for name in created:
            self.assertNotIn(name, listed)
        status, summary = js('/api/admin/summary', {'X-Admin-Token': os.environ['ADMIN_TOKEN']})
        self.assertEqual(status, 200)
        blob = json.dumps(summary, ensure_ascii=False)
        for secret in created + ['비밀편지', '보호자표시금지', 'ekey', 'letter', 'owner', 'photo', 'name']:
            self.assertNotIn(secret, blob)
        self.assertEqual(summary['real_total'], before['real_total'] + 2)
        self.assertEqual(summary['real_private'], before['real_private'] + 1)
        self.assertEqual(summary['real_link'], before['real_link'] + 1)
        self.assertEqual(summary['real_new_24h'], before['real_new_24h'] + 2)
        self.assertEqual(summary['real_new_7d'], before['real_new_7d'] + 2)
        self.assertEqual(summary['example_total'], before['example_total'])
        self.assertGreater(summary['example_total'], 0)
        self.assertIsInstance(summary['newest_real_created'], float)
        self.assertEqual(summary['public_list_includes'], 'public')
        wrong, denied = js('/api/admin/summary', {'X-Admin-Token': 'nope'})
        self.assertEqual(wrong, 403)
        self.assertNotIn('real_total', denied)

    def test_walk_reuses_one_job_and_keeps_memorial_fields(self):
        os.environ['DEMO_DELAY'] = '0'
        os.environ.pop('XAI_API_KEY', None)
        os.environ.pop('XAI_MOCK', None)
        server.boot()
        with server.db() as c:
            c.execute('delete from gen_log')
        code, made = js('/api/pets', method='POST', payload=json.dumps({
            'name': '로컬산책', 'visibility': 'public', 'species': '강아지', 'letter': '로컬편지', 'owner': '로컬보호',
        }).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        pid = made['id']
        with server.db() as c:
            c.execute('update pets set photo=? where id=?', ('/static/samples/pet_kongi.jpg', pid))
            before = dict(c.execute('select photo,letter,owner,visibility,ekey from pets where id=?', (pid,)).fetchone())
        code, job = js('/api/pets/%s/videos' % pid, method='POST', payload=json.dumps({'style': 'walk', 'cid': 'walk-test'}).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        self.assertEqual(job.get('provider'), 'demo')
        self.assertEqual(job.get('sample'), 1)
        self.assertEqual(job.get('style'), 'walk')
        self.assertEqual(job.get('status'), 'running')
        again_code, again = js('/api/pets/%s/videos' % pid, method='POST', payload=json.dumps({'style': 'walk', 'cid': 'walk-test'}).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(again_code, 200)
        self.assertEqual(again.get('id'), job['id'])
        self.assertEqual(again.get('reused'), 1)
        deadline = time.time() + 20
        status = 'running'
        video = {}
        while time.time() < deadline and status == 'running':
            time.sleep(0.2)
            st, video = js('/api/videos/%s' % job['id'])
            self.assertEqual(st, 200)
            status = video.get('status')
        self.assertEqual(status, 'done', video.get('error'))
        self.assertTrue(str(video.get('url') or '').endswith('.mp4'))
        self.assertEqual(video.get('sample'), 1)
        with server.db() as c:
            after = dict(c.execute('select photo,letter,owner,visibility,ekey from pets where id=?', (pid,)).fetchone())
            rows = c.execute("select id from videos where pet_id=? and style='walk' and status!='error'", (pid,)).fetchall()
        self.assertEqual(after, before)
        self.assertEqual(len(rows), 1)
        ex_code, ex = js('/api/pets/1/videos', method='POST', payload=json.dumps({'style': 'walk'}).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(ex_code, 403)

    def test_failed_walk_can_retry_without_a_second_running_job(self):
        os.environ['DEMO_DELAY'] = '0'
        server.boot()
        with server.db() as c:
            c.execute('delete from gen_log')
        code, made = js('/api/pets', method='POST', payload=json.dumps({
            'name': '로컬재시도', 'visibility': 'public', 'species': '고양이', 'letter': '유지편지', 'owner': '유지보호',
        }).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        pid = made['id']
        with server.db() as c:
            c.execute('update pets set photo=? where id=?', ('/static/samples/pet_nabi.jpg', pid))
            before = dict(c.execute('select photo,letter,owner,visibility,ekey from pets where id=?', (pid,)).fetchone())
        def boom(photo_path, prompt):
            raise RuntimeError('forced')
        old = server.DemoProvider.generate
        server.DemoProvider.generate = boom
        try:
            code, job = js('/api/pets/%s/videos' % pid, method='POST', payload=json.dumps({'style': 'walk', 'cid': 'retry-test'}).encode(), headers={'Content-Type': 'application/json'})
            self.assertEqual(code, 200)
            deadline = time.time() + 10
            status = 'running'
            while time.time() < deadline and status == 'running':
                time.sleep(0.15)
                status = js('/api/videos/%s' % job['id'])[1].get('status')
        finally:
            server.DemoProvider.generate = old
        self.assertEqual(status, 'error')
        with server.db() as c:
            logs = c.execute('select count(*) from gen_log where pet_id=?', (pid,)).fetchone()[0]
        self.assertEqual(logs, 0)
        code, retry = js('/api/pets/%s/videos' % pid, method='POST', payload=json.dumps({'style': 'walk', 'cid': 'retry-b'}).encode(), headers={'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        self.assertNotEqual(retry.get('id'), job['id'])
        self.assertEqual(retry.get('reused'), None)
        with server.db() as c:
            after = dict(c.execute('select photo,letter,owner,visibility,ekey from pets where id=?', (pid,)).fetchone())
            running = c.execute("select count(*) from videos where pet_id=? and status='running'", (pid,)).fetchone()[0]
        self.assertEqual(after, before)
        self.assertEqual(running, 1)

    def test_seeded_examples_remain_stored_after_public_reads(self):
        server.boot()
        with server.db() as c:
            before = [dict(r) for r in c.execute('select id,name,photo,letter,owner,ekey,visibility,example from pets where coalesce(example,0)!=0 order by id')]
        self.assertGreaterEqual(len(before), 6)
        js('/api/pets')
        with server.db() as c:
            after = [dict(r) for r in c.execute('select id,name,photo,letter,owner,ekey,visibility,example from pets where coalesce(example,0)!=0 order by id')]
        self.assertEqual(after, before)
        for row in after:
            self.assertTrue(str(row['name']).startswith('[예시]'))
            self.assertTrue(str(row['photo']).startswith('/static/samples/pet_'))
            self.assertTrue(row['letter'])
            self.assertTrue(row['owner'])
            self.assertTrue(row['ekey'])
            self.assertEqual(row['visibility'] or 'public', 'public')

    def test_slow_database_returns_json_instead_of_hanging(self):
        server.boot()
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        def hold():
            try:
                while True:
                    conn, _ = sock.accept()
                    time.sleep(3)
                    conn.close()
            except OSError:
                return

        threading.Thread(target=hold, daemon=True).start()
        old = (server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT)
        server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT = True, 'http://127.0.0.1:%d' % port, 'k', 0.4
        try:
            started = time.perf_counter()
            status, body = js('/api/pets', timeout=3)
            elapsed = time.perf_counter() - started
        finally:
            server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT = old
            sock.close()
        self.assertLess(elapsed, 2.0)
        self.assertEqual(status, 503)
        self.assertIn('불러오지 못했어요', body['error'])
        self.assertNotIn('exec_sql', json.dumps(body))
        self.assertNotIn('db unavailable', json.dumps(body))

    def test_health_stays_fast_when_database_is_slow(self):
        server.boot()
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        old = (server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT)
        server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT = True, 'http://127.0.0.1:%d' % sock.getsockname()[1], 'k', 5
        try:
            started = time.perf_counter()
            status, body = js('/api/health', timeout=1)
            elapsed = time.perf_counter() - started
        finally:
            server.PGURL, server.SB, server.SBK, server.RPC_TIMEOUT = old
            sock.close()
        self.assertLess(elapsed, 0.5)
        self.assertEqual(status, 200)
        self.assertTrue(body['db'])


if __name__ == '__main__':
    unittest.main()
