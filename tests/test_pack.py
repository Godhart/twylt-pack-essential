import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pydantic import ValidationError

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
import common as c

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302); self.send_header('Location','/text'); self.end_headers(); return
        if self.path == '/foreign':
            self.send_response(302); self.send_header('Location',self.server.foreign+'/headers'); self.end_headers(); return
        if self.path == '/file':
            self.send_response(302); self.send_header('Location','file:///etc/passwd'); self.end_headers(); return
        if self.path.startswith('/search?'):
            from urllib.parse import parse_qs,urlsplit
            self.server.query = parse_qs(urlsplit(self.path).query)
            payload = json.dumps({'results':[{'title':'Demo','url':'https://example.org','content':'Found','engines':['test']}],'suggestions':['demo'],'number_of_results':1}).encode()
        elif self.path == '/headers': payload = json.dumps(dict(self.headers.items())).encode()
        elif self.path == '/binary': payload = b'\xff\x00'
        else: payload = b'hello\n'
        self.send_response(404 if self.path == '/missing' else 200)
        self.send_header('Content-Type','text/plain; charset=utf-8'); self.end_headers(); self.wfile.write(payload)
    def do_POST(self):
        payload = self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.send_response(200); self.end_headers(); self.wfile.write(payload)

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.other = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.server.foreign = f'http://127.0.0.1:{cls.other.server_port}'
        for s in [cls.server,cls.other]: threading.Thread(target=s.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        for s in [cls.server,cls.other]: s.shutdown(); s.server_close()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ,{'TWYLT_WORKSPACE_ROOT':self.temp.name,'TWYLT_SEARXNG_URL':self.url,'TWYLT_ESSENTIAL_DISABLE_NETWORK':'0','TWYLT_INCIDENT_LOG':''})
        self.env.start()
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def test_echo_preserves_text(self):
        for text in ['', 'Привет, TWYLT! 😀', '  a\t\r\n b\n', '\x00']:
            self.assertEqual(c.echo(c.EchoInput(text=text)).text, text)
        for data in [{}, {'text':123}, {'text':'hello','extra':1}]:
            with self.assertRaises(ValidationError): c.EchoInput(**data)
    def test_echo_cli_and_network_disabled(self):
        text = '  Привет!\nSecond line\t'
        with patch.dict(os.environ, {'TWYLT_ESSENTIAL_DISABLE_NETWORK':'1'}):
            result = subprocess.run([sys.executable,str(BASE/'tools/echo/run.py'),json.dumps({'text':text})],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout), {'text':text})
    def test_sleep_real_time(self):
        start = time.monotonic(); out = c.sleep(c.SleepInput(seconds=.02))
        self.assertGreaterEqual(time.monotonic()-start,.02); self.assertGreaterEqual(out.elapsed_seconds,.02)
    def test_strict_validation(self):
        for data in [{'seconds':-1},{'seconds':float('nan')},{'seconds':1,'extra':1}]:
            with self.assertRaises(ValidationError): c.SleepInput(**data)
        with self.assertRaises(ValidationError): c.CurlInput(url=self.url,body='a',json_body={})
    def test_http_text_and_binary(self):
        out = c.http(c.CurlInput(url=self.url+'/text')); self.assertEqual(out.text,'hello\n'); self.assertEqual(out.bytes_received,6)
        self.assertEqual(c.http(c.CurlInput(url=self.url+'/binary')).body_base64,'/wA=')
    def test_post(self):
        out = c.http(c.CurlInput(url=self.url,method='POST',json_body={'x':1})); self.assertEqual(json.loads(out.text),{'x':1})
    def test_http_error(self):
        out = c.http(c.CurlInput(url=self.url+'/missing')); self.assertEqual(out.status,404); self.assertFalse(out.ok)
    def test_redirect(self):
        self.assertEqual(c.http(c.CurlInput(url=self.url+'/redirect')).status,200)
        self.assertEqual(c.http(c.CurlInput(url=self.url+'/redirect',follow_redirects=False)).status,302)
    def test_redirect_credentials(self):
        out = c.http(c.CurlInput(url=self.url+'/foreign',headers={'Authorization':'secret','Cookie':'secret','X-Api-Key':'secret'}))
        self.assertNotIn('secret',out.text)
    def test_protocol_restriction(self):
        for url in ['file:///etc/passwd','ftp://example.org','http://user:pass@example.org']:
            with self.assertRaises(ValueError): c.http(c.CurlInput(url=url))
        with self.assertRaises(ValueError): c.http(c.CurlInput(url=self.url+'/file'))
    def test_download_atomic(self):
        path = Path(self.temp.name)/'out'
        out = c.http(c.WgetInput(url=self.url+'/text',output_path='/out')); self.assertEqual(out.output_path,'/out'); self.assertEqual(path.read_bytes(),b'hello\n')
        with self.assertRaises(FileExistsError): c.http(c.WgetInput(url=self.url,output_path='out'))
        with self.assertRaises(ValueError): c.http(c.WgetInput(url=self.url,output_path='out',overwrite=True,max_bytes=2))
        self.assertEqual(path.read_bytes(),b'hello\n')
        c.http(c.WgetInput(url=self.url+'/missing',output_path='out',overwrite=True)); self.assertEqual(path.read_bytes(),b'hello\n')
        c.http(c.WgetInput(url=self.url+'/binary',output_path='out',overwrite=True)); self.assertEqual(path.read_bytes(),b'\xff\x00')
    def test_workspace_escape_and_symlink(self):
        with self.assertRaises(c.WorkspaceDenied): c.http(c.WgetInput(url=self.url,output_path='../escape'))
        (Path(self.temp.name)/'link').symlink_to('/tmp')
        with self.assertRaises(c.WorkspaceDenied): c.http(c.WgetInput(url=self.url,output_path='link/out'))
    def test_network_disabled(self):
        with patch.dict(os.environ,{'TWYLT_ESSENTIAL_DISABLE_NETWORK':'1'}):
            for fn,data in [(c.http,c.CurlInput(url=self.url)),(c.ping,c.PingInput(host='localhost')),(c.web_search,c.SearchInput(query='test'))]:
                with self.assertRaises(ValueError): fn(data)
            c.sleep(c.SleepInput(seconds=0))
    def test_search(self):
        out = c.web_search(c.SearchInput(query='a & b',limit=1,time_range='month'))
        self.assertEqual(out.results[0].snippet,'Found'); self.assertEqual(self.server.query['q'],['a & b']); self.assertEqual(self.server.query['format'],['json'])
        with patch.dict(os.environ,{'TWYLT_SEARXNG_URL':''}):
            with self.assertRaises(ValueError): c.web_search(c.SearchInput(query='test'))
    def test_ping(self):
        for code in [0,1]:
            with patch.object(c.shutil,'which',return_value='/usr/bin/ping'), patch.object(c.platform,'system',return_value='Linux'), patch.object(c.subprocess,'run',return_value=subprocess.CompletedProcess([],code,b'ping',b'')) as run:
                out = c.ping(c.PingInput(host='localhost')); self.assertEqual(out.reachable,code==0); self.assertEqual(run.call_args.args[0][-1],'localhost'); self.assertNotIn('shell',run.call_args.kwargs)
        with patch.object(c.shutil,'which',return_value='/usr/bin/ping'), patch.object(c.platform,'system',return_value='Linux'), patch.object(c.subprocess,'run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial')):
            self.assertTrue(c.ping(c.PingInput(host='localhost')).timed_out)
        with self.assertRaises(ValueError): c.ping(c.PingInput(host='-h'))
        with patch.object(c.shutil,'which',return_value=None):
            with self.assertRaises(RuntimeError): c.ping(c.PingInput(host='localhost'))
    def test_standalone_contracts(self):
        for name in ['echo','sleep','wget','curl','ping','web_search']:
            path = BASE/'tools'/name/'tool.py'
            spec = importlib.util.spec_from_file_location('essential_'+name,path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            tool = module.TOOL
            for example in tool.few_shots:
                tool.input_model.model_validate(example['input']); tool.output_model.model_validate(example['output'])
            result = subprocess.run([sys.executable,str(path.with_name('run.py')),json.dumps({'describe':'json_spec'})],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            metadata = json.loads(result.stdout); self.assertEqual(metadata['name'],name); self.assertTrue(metadata['inputSchema']); self.assertTrue(metadata['outputSchema'])
    def test_cli_stdin_and_errors(self):
        path = BASE/'tools/sleep/run.py'
        result = subprocess.run([sys.executable,str(path)],input='{"seconds":0}',capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['requested_seconds'],0)
        result = subprocess.run([sys.executable,str(path),'{"seconds":-1}'],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0); json.loads(result.stdout or result.stderr)

if __name__ == '__main__': unittest.main()
