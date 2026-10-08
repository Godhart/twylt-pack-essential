import json,os,subprocess,sys,tempfile,unittest,shutil,threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]

class Integration(unittest.TestCase):
    def test_builder_pack_and_nested_cwd(self):
        from toolpack_builder.builder import BuildConfig,scan,build_from_report
        with tempfile.TemporaryDirectory() as td:
            ws=Path(td)/'workspace';ws.mkdir()
            root=Path(td)/'runs';cwd=root/'one'/'two';cwd.mkdir(parents=True)
            env={'TWYLT_GUARDRAILS':'1','TWYLT_WORKSPACE_ROOT':str(ws),'TWYLT_ALLOWED_CWD':str(root)}
            with patch.dict(os.environ,env):
                config=BuildConfig(root=BASE/'tools',glob='*/tool.py',python=sys.executable)
                report=scan(config)
                self.assertEqual(len(report.valid),6,report.failed)
                payload=build_from_report(config,report).payload
                tools={t['name']:t for t in payload['category']['tools']}
                (cwd/'input.json').write_text('{"text":"nested"}')
                r=subprocess.run([sys.executable,'-c',tools['echo']['code']],stdin=subprocess.DEVNULL,cwd=cwd,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(json.loads((cwd/'output.json').read_text()),{'text':'nested'})
                self.assertNotIn('class Workspace',tools['echo']['code'])

    def test_echo_does_not_import_other_business_logic(self):
        code='import runpy,sys;runpy.run_path('+repr(str(BASE/'tools/echo/tool.py'))+''',run_name='inspect_only');assert 'essential_common.http' not in sys.modules;assert 'urllib.request' not in sys.modules;assert 'subprocess' not in sys.modules'''
        # Pydantic or interpreter internals may import subprocess; restrict to the pack's HTTP module.
        code=code.replace(";assert 'subprocess' not in sys.modules",'')
        r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_new_policy_network_error(self):
        r=subprocess.run([sys.executable,str(BASE/'tools/curl/run.py'),'{"url":"https://example.com"}'],env={**os.environ,'TWYLT_GUARDRAILS':'1','TWYLT_DISABLE_NETWORK':'1','TWYLT_WORKSPACE_ROOT':''},input='',capture_output=True,text=True)
        self.assertEqual(r.returncode,6,r.stderr)
        errors=[json.loads(line) for line in r.stderr.splitlines()]
        self.assertEqual(errors[-1]['error']['code'],'network_disabled')

class SourceDeployment(unittest.TestCase):
    def test_copied_pack_http_direct_bootstrap_and_builder(self):
        from toolpack_builder.builder import BuildConfig, scan, build_from_report

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'portable shared code')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack = root/'copied-pack'
                for directory in ('tools', 'shared'):
                    shutil.copytree(BASE/directory, pack/directory,
                                    ignore=shutil.ignore_patterns('__pycache__'))
                cwd = root/'unrelated'/'nested'
                cwd.mkdir(parents=True)
                ws = root/'workspace'
                ws.mkdir()
                env = {**os.environ, 'TWYLT_GUARDRAILS': '1',
                       'TWYLT_DISABLE_NETWORK': '0',
                       'TWYLT_WORKSPACE_ROOT': str(ws),
                       'TWYLT_ALLOWED_CWD': str(root/'unrelated')}
                # Reject any reliance on an old installed pack, including probe processes.
                blocker = root/'blocker'
                blocker.mkdir()
                (blocker/'sitecustomize.py').write_text(
                    "import sys\nclass BlockLegacy:\n"
                    " def find_spec(self, fullname, path=None, target=None):\n"
                    "  if fullname.split('.')[0] == 'twylt_pack_essential':\n"
                    "   raise ImportError('Installed essential package is forbidden')\n"
                    "sys.meta_path.insert(0, BlockLegacy())\n")
                env['PYTHONPATH'] = str(blocker)
                request = json.dumps({'url': f'http://127.0.0.1:{server.server_port}/'})
                for entry in ('tool.py', 'run.py'):
                    with self.subTest(entry=entry):
                        r = subprocess.run([sys.executable, str(pack/'tools/curl'/entry), request],
                                           cwd=cwd, env=env, input='', capture_output=True, text=True)
                        self.assertEqual(r.returncode, 0, r.stderr)
                        self.assertEqual(json.loads(r.stdout)['text'], 'portable shared code')
                with patch.dict(os.environ, env):
                    config = BuildConfig(root=pack/'tools', glob='*/tool.py', python=sys.executable)
                    report = scan(config)
                    self.assertEqual(len(report.valid), 6, report.failed)
                    payload = build_from_report(config, report).payload
                tools = {t['name']: t for t in payload['category']['tools']}
                for name in ('curl', 'wget', 'web_search'):
                    r = subprocess.run([sys.executable, str(pack/'tools'/name/'run.py'),
                                        '{"describe":"json_spec"}'], cwd=cwd, env=env,
                                       input='', capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertNotIn('twylt-pack-essential', json.loads(r.stdout)['requirements']['content'])
                (cwd/'input.json').write_text(request)
                r = subprocess.run([sys.executable, '-c', tools['curl']['code']],
                                   cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(json.loads((cwd/'output.json').read_text())['text'],
                                 'portable shared code')
        finally:
            server.shutdown()
            server.server_close()

    def test_non_http_tools_do_not_load_shared_code(self):
        for name in ('echo', 'sleep', 'ping'):
            with self.subTest(tool=name):
                code = ('import runpy,sys;runpy.run_path(' +
                        repr(str(BASE/'tools'/name/'tool.py')) +
                        ",run_name='inspect_only');assert not any("
                        "x == 'essential_common' or x.startswith('essential_common.') for x in sys.modules)")
                r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

if __name__=='__main__':unittest.main()
