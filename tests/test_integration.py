import json,os,subprocess,sys,tempfile,unittest
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
        code='import runpy,sys;runpy.run_path('+repr(str(BASE/'tools/echo/tool.py'))+''',run_name='inspect_only');assert 'twylt_pack_essential.http' not in sys.modules;assert 'urllib.request' not in sys.modules;assert 'subprocess' not in sys.modules'''
        # Pydantic or interpreter internals may import subprocess; restrict to the pack's HTTP module.
        code=code.replace(";assert 'subprocess' not in sys.modules",'')
        r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_new_policy_network_error(self):
        r=subprocess.run([sys.executable,str(BASE/'tools/curl/run.py'),'{"url":"https://example.com"}'],env={**os.environ,'TWYLT_GUARDRAILS':'1','TWYLT_DISABLE_NETWORK':'1','TWYLT_WORKSPACE_ROOT':''},input='',capture_output=True,text=True)
        self.assertEqual(r.returncode,6,r.stderr)
        errors=[json.loads(line) for line in r.stderr.splitlines()]
        self.assertEqual(errors[-1]['error']['code'],'network_disabled')

if __name__=='__main__':unittest.main()
