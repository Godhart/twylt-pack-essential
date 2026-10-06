"""Shared implementation embedded in every standalone tool."""
import base64
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from twylt import Tool, Requirements
"""Shared workspace policy 1.0.0. Embedded verbatim in standalone tools.
Explicit path confinement, not an OS sandbox. Environment is trusted configuration.
"""
import contextvars
import datetime as _datetime
import json as _json
import os as _os
from pathlib import Path as _Path
import stat as _stat
import sys as _sys
import uuid as _uuid

_POLICY = contextvars.ContextVar('twylt_workspace', default=None)

class WorkspaceDenied(ValueError):
    """A policy denial, already recorded in the incident sink."""
    def __init__(self, code, incident_id):
        self.code = code
        self.incident_id = incident_id
        super().__init__(f'{code}: access denied (incident {incident_id})')

class Workspace:
    def __init__(self, tool='unknown'):
        self.tool = tool
        self.log_path = None
        self.root = None
        value = _os.environ.get('TWYLT_WORKSPACE_ROOT', '')
        if not value or not _Path(value).is_absolute():
            self.deny('workspace_not_configured')
        candidate = _Path(_os.path.abspath(value))
        # The root and all of its ancestors must be real directories.
        try:
            for part in [*reversed(candidate.parents), candidate]:
                st = part.lstat()
                if self._link(st) or not _stat.S_ISDIR(st.st_mode):
                    self.deny('invalid_workspace_root')
            if candidate.parent == candidate:
                self.deny('filesystem_root_forbidden')
        except OSError:
            self.deny('invalid_workspace_root')
        self.root = candidate
        configured_log = _os.environ.get('TWYLT_INCIDENT_LOG', '')
        if configured_log:
            p = _Path(configured_log)
            if not p.is_absolute(): self.deny('invalid_incident_log')
            p = _Path(_os.path.abspath(p))
            if self.contains(p): self.deny('incident_log_inside_workspace')
            try:
                for parent in [*reversed(p.parent.parents), p.parent]:
                    st = parent.lstat()
                    if self._link(st) or not _stat.S_ISDIR(st.st_mode):
                        self.deny('invalid_incident_log')
                self.log_path = p
                fd = self._open_log()
                _os.close(fd)
            except WorkspaceDenied:
                raise
            except (OSError, ValueError):
                self.log_path = None
                self.deny('incident_log_unavailable')

    @staticmethod
    def _link(st):
        # Includes Windows junctions/reparse points even on Python without is_junction().
        return _stat.S_ISLNK(st.st_mode) or bool(getattr(st, 'st_file_attributes', 0) & 0x400)

    def contains(self, path):
        return self.root is not None and (path == self.root or self.root in path.parents)

    def _open_log(self):
        p = self.log_path
        if p.exists() or p.is_symlink():
            st = p.lstat()
            if self._link(st) or not _stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError('unsafe audit sink')
        flags = _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT | getattr(_os, 'O_NOFOLLOW', 0) | getattr(_os, 'O_CLOEXEC', 0) | getattr(_os, 'O_NONBLOCK', 0)
        fd = _os.open(p, flags, 0o600)
        try:
            st = _os.fstat(fd)
            if not _stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError('unsafe audit sink')
        except BaseException:
            _os.close(fd)
            raise
        return fd

    def deny(self, code, requested=None):
        identifier = str(_uuid.uuid4())
        event = {'event': 'workspace_incident', 'schema_version': '1.0',
                 'timestamp': _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
                 'incident_id': identifier, 'tool': self.tool, 'pid': _os.getpid(),
                 'action': 'deny', 'code': code}
        if requested is not None:
            # Only explicit path values, never file contents or remote URLs/credentials.
            event['requested_path'] = str(requested)[:1024]
        payload = (_json.dumps(event, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
        try:
            if self.log_path is None:
                _sys.stderr.write(payload.decode('utf-8')); _sys.stderr.flush()
            else:
                fd = self._open_log()
                try:
                    if _os.write(fd, payload) != len(payload): raise OSError('short audit write')
                    _os.fsync(fd)
                finally: _os.close(fd)
        except (OSError, ValueError):
            event['original_code'] = code
            event['code'] = code = 'incident_log_unavailable'
            _sys.stderr.write(_json.dumps(event, ensure_ascii=True) + '\n'); _sys.stderr.flush()
        raise WorkspaceDenied(code, identifier)

    def inspect(self, path, allow_leaf_link=False):
        """Check physical path components without following any link."""
        path = _Path(path)
        if not self.contains(path): self.deny('path_outside_workspace')
        current = self.root
        parts = path.relative_to(self.root).parts
        for i, part in enumerate(parts):
            current = current / part
            try: st = current.lstat()
            except FileNotFoundError: break
            if self._link(st):
                if allow_leaf_link and i == len(parts)-1: return path
                self.deny('symlink_forbidden', self.virtual_unchecked(path))
            if _stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                self.deny('hardlink_forbidden', self.virtual_unchecked(path))
            if not (_stat.S_ISREG(st.st_mode) or _stat.S_ISDIR(st.st_mode)):
                self.deny('special_file_forbidden', self.virtual_unchecked(path))
            if st.st_dev != self.root.stat().st_dev:
                self.deny('mount_boundary_forbidden', self.virtual_unchecked(path))
        return path

    def resolve(self, value, base=None):
        """POSIX virtual / is root; relative paths are root-based unless base is explicit."""
        if not isinstance(value, str) or not value or '\x00' in value:
            self.deny('invalid_path')
        if '\\' in value or ':' in value or value.startswith('//') or value.startswith('~'):
            self.deny('invalid_path_syntax', value)
        parts = value.split('/')
        if '..' in parts: self.deny('path_outside_workspace', value)
        if _os.name == 'nt':
            reserved = {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}
            if any(p.endswith((' ', '.')) or p.split('.')[0].upper() in reserved for p in parts if p not in {'', '.'}):
                self.deny('invalid_path_syntax', value)
        start = self.root if value.startswith('/') or base is None else base
        path = start.joinpath(*(p for p in parts if p not in {'', '.'}))
        return self.inspect(path)

    def virtual_unchecked(self, path):
        relative = _Path(path).relative_to(self.root).as_posix()
        return '/' if relative == '.' else '/' + relative

    def virtual(self, path):
        if not self.contains(_Path(path)): self.deny('path_outside_workspace')
        return self.virtual_unchecked(path)

    def protect_root(self, path):
        if path == self.root: self.deny('workspace_root_mutation_forbidden', '/')

    def tree(self, path):
        """Preflight every descendant before a recursive mutation."""
        self.inspect(path)
        if not path.is_dir(): return
        stack = [path]
        while stack:
            parent = stack.pop()
            with _os.scandir(parent) as children:
                for child in children:
                    p = self.inspect(_Path(child.path))
                    if p.is_dir(): stack.append(p)

    def redact(self, value):
        if self.root is None: return str(value)
        return str(value).replace(str(self.root) + _os.sep, '/').replace(str(self.root), '/')

    def __enter__(self):
        self._token = _POLICY.set(self)
        return self

    def __exit__(self, typ, exc, tb):
        _POLICY.reset(self._token)
        # Remove host workspace prefixes from errors returned by business code.
        if exc is not None and not isinstance(exc, WorkspaceDenied):
            if isinstance(exc, OSError):
                if exc.filename: exc.filename = self.redact(exc.filename)
                if exc.filename2: exc.filename2 = self.redact(exc.filename2)
            exc.args = tuple(self.redact(a) if isinstance(a, str) else a for a in exc.args)
        return False

def workspace():
    active = _POLICY.get()
    return active if active is not None else Workspace()

class WorkspaceTransport:
    """Guard TWYLT 1.0.0's implicit input.json/output.json before its file I/O."""
    @classmethod
    def _transport_payload(cls):
        payload, source = super()._transport_payload()
        if source is None and not _os.environ.get('INPUT_DESCRIBE', ''):
            with Workspace(cls.name) as ws:
                cwd = _Path.cwd()
                if not ws.contains(cwd): ws.deny('transport_cwd_outside_workspace')
                ws.inspect(cwd)
                for attribute in ['input_path', 'output_path']:
                    path = _Path(getattr(cls, attribute))
                    full = path if path.is_absolute() else cwd/path
                    setattr(cls, attribute, ws.inspect(full))
        return payload, source

    @classmethod
    def _write_output(cls, value):
        with Workspace(cls.name) as ws:
            ws.inspect(_Path(cls.output_path))
            return super()._write_output(value)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class EchoInput(Model):
    text: str = Field(description='Text to return unchanged, including whitespace and line breaks.')

class EchoOutput(Model):
    text: str = Field(description='Exact text from the request.')


def echo(data):
    return EchoOutput(text=data.text)

class SleepInput(Model):
    seconds: float = Field(ge=0, le=86400, description='Real elapsed seconds to wait (maximum one day).')

class SleepOutput(Model):
    requested_seconds: float
    elapsed_seconds: float


def sleep(data):
    start = time.monotonic()
    time.sleep(data.seconds)
    return SleepOutput(requested_seconds=data.seconds, elapsed_seconds=time.monotonic()-start)

class HttpInput(Model):
    url: str = Field(description='HTTP or HTTPS URL.')
    headers: dict[str, str] = Field(default_factory=dict, description='Request headers.')
    timeout: float = Field(default=30, gt=0, le=600, description='Socket timeout and checked total deadline, seconds.')
    max_bytes: int = Field(default=10_000_000, ge=1, le=1_000_000_000, description='Maximum downloaded response bytes.')
    follow_redirects: bool = Field(default=True, description='Follow at most ten HTTP(S) redirects.')
    output_path: str | None = Field(default=None, description='Virtual workspace path; otherwise return response body.')
    overwrite: bool = Field(default=False, description='Explicitly permit replacement of destination.')

class WgetInput(HttpInput):
    output_path: str = Field(description='Required destination inside TWYLT_WORKSPACE_ROOT.')

class CurlInput(HttpInput):
    method: Literal['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'] = Field(default='GET', description='HTTP method.')
    body: str | None = Field(default=None, description='UTF-8 request body.')
    json_body: dict | list | str | int | float | bool | None = Field(default=None, description='JSON request body; exclusive with body.')
    encoding: str | None = Field(default=None, description='Decode returned body with this encoding, otherwise Content-Type or UTF-8.')
    @model_validator(mode='after')
    def check_body(self):
        if self.body is not None and self.json_body is not None:
            raise ValueError('body and json_body are mutually exclusive')
        return self

class HttpOutput(Model):
    status: int
    ok: bool
    headers: dict[str, str]
    bytes_received: int
    sha256: str
    output_path: str | None = None
    text: str | None = None
    body_base64: str | None = None
    elapsed_seconds: float


def network_allowed():
    if os.environ.get('TWYLT_ESSENTIAL_DISABLE_NETWORK','').lower() in {'1','true','yes','on'}:
        raise ValueError('Network disabled by TWYLT_ESSENTIAL_DISABLE_NETWORK')


def check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {'http','https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Expected HTTP(S) URL without embedded credentials')
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError('Control characters in URL')
    return parsed

class Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 10
    def __init__(self, enabled):
        self.enabled = enabled
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        if not self.enabled:
            return None
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result and urllib.parse.urlsplit(req.full_url)[:2] != urllib.parse.urlsplit(newurl)[:2]:
            # Never forward caller-provided secrets to another origin.
            result.headers = {k:v for k,v in result.headers.items() if k.lower() in {'accept','user-agent','content-type','content-length'}}
            result.unredirected_hdrs = {}
        return result


def http(data):
    network_allowed()
    check_url(data.url)
    method = getattr(data,'method','GET')
    headers = dict(data.headers)
    for k,v in headers.items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",k) or '\r' in v or '\n' in v:
            raise ValueError('Invalid HTTP header')
    body = getattr(data,'body',None)
    if getattr(data,'json_body',None) is not None:
        body = json.dumps(data.json_body,allow_nan=False)
        if not any(k.lower() == 'content-type' for k in headers): headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(data.url,data=body.encode('utf-8') if body is not None else None,headers=headers,method=method)
    opener = urllib.request.build_opener(Redirect(data.follow_redirects))
    start = time.monotonic()
    try:
        response = opener.open(request,timeout=data.timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in {301,302,303,307,308} and exc.headers.get('Location'):
            check_url(urllib.parse.urljoin(data.url,exc.headers['Location']))
        response = exc  # HTTP failure is a structured result, transport failure is a TWYLT business error.
    with response:
        chunks = []
        size = 0
        while True:
            if time.monotonic()-start > data.timeout: raise TimeoutError('HTTP total deadline exceeded')
            chunk = response.read1(min(65536,data.max_bytes-size+1))
            if not chunk: break
            size += len(chunk)
            if size > data.max_bytes: raise ValueError('Response exceeds max_bytes')
            chunks.append(chunk)
        payload = b''.join(chunks)
        result = HttpOutput(status=response.code,ok=200 <= response.code < 300,headers=dict(response.headers.items()),bytes_received=size,sha256=hashlib.sha256(payload).hexdigest(),elapsed_seconds=time.monotonic()-start)
        if data.output_path is not None:
            if not result.ok: return result  # preserve destination on unsuccessful HTTP status
            with Workspace('http_download') as ws:
                path = ws.resolve(data.output_path)
                ws.protect_root(path)
                if path.exists() and not data.overwrite: raise FileExistsError('Destination already exists')
                if not path.parent.is_dir(): raise FileNotFoundError('Destination parent does not exist')
                fd, temp = tempfile.mkstemp(prefix='.essential-',dir=path.parent)
                try:
                    with os.fdopen(fd,'wb') as stream: stream.write(payload)
                    ws.inspect(path)
                    if data.overwrite: os.replace(temp,path)
                    else: os.link(temp,path)  # atomic no-clobber
                    result.output_path = ws.virtual(path)
                finally:
                    Path(temp).unlink(missing_ok=True)
        else:
            encoding = getattr(data,'encoding',None) or response.headers.get_content_charset() or 'utf-8'
            try: result.text = payload.decode(encoding)
            except UnicodeError: result.body_base64 = base64.b64encode(payload).decode('ascii')
        result.elapsed_seconds = time.monotonic()-start
        return result

class PingInput(Model):
    host: str = Field(min_length=1,max_length=253,description='Hostname or IP address; no command-line arguments.')
    count: int = Field(default=4,ge=1,le=100,description='Number of ICMP echo requests.')
    timeout: float = Field(default=10,gt=0,le=300,description='Whole process deadline, seconds.')
    family: Literal['auto','ipv4','ipv6'] = Field(default='auto',description='IP address family.')

class PingOutput(Model):
    reachable: bool
    timed_out: bool
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float


def ping(data):
    network_allowed()
    if data.host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.:%-]+',data.host):
        raise ValueError('Invalid host')
    executable = shutil.which('ping')
    if not executable: raise RuntimeError('ping executable is missing; install iputils-ping (Linux)')
    family = [] if data.family == 'auto' else ['-4' if data.family == 'ipv4' else '-6']
    system = platform.system()
    if system == 'Windows': args = [executable,*family,'-n',str(data.count),'-w','1000',data.host]
    elif system == 'Linux': args = [executable,*family,'-n','-c',str(data.count),'-W','1',data.host]
    else: raise RuntimeError('ping currently supports Linux and Windows')
    start = time.monotonic()
    try:
        result = subprocess.run(args,capture_output=True,timeout=data.timeout,check=False,env={**os.environ,'LC_ALL':'C'},stdin=subprocess.DEVNULL)
        return PingOutput(reachable=result.returncode==0,timed_out=False,returncode=result.returncode,stdout=result.stdout.decode(errors='replace'),stderr=result.stderr.decode(errors='replace'),elapsed_seconds=time.monotonic()-start)
    except subprocess.TimeoutExpired as exc:
        return PingOutput(reachable=False,timed_out=True,returncode=None,stdout=(exc.stdout or b'').decode(errors='replace'),stderr=(exc.stderr or b'').decode(errors='replace'),elapsed_seconds=time.monotonic()-start)

class SearchInput(Model):
    query: str = Field(min_length=1,max_length=4096,description='Search query.')
    limit: int = Field(default=10,ge=1,le=100,description='Maximum returned results from the requested page.')
    page: int = Field(default=1,ge=1,le=100,description='SearXNG page number.')
    language: str = Field(default='all',description='SearXNG language code.')
    categories: str = Field(default='general',description='Comma-separated SearXNG categories.')
    time_range: Literal['day','month','year'] | None = Field(default=None,description='Optional time filter.')
    safe_search: int = Field(default=1,ge=0,le=2,description='SearXNG safe search level.')
    timeout: float = Field(default=30,gt=0,le=600,description='HTTP timeout, seconds.')

class SearchEntry(Model):
    title: str
    url: str
    snippet: str
    engines: list[str]

class SearchOutput(Model):
    query: str
    page: int
    results: list[SearchEntry]
    suggestions: list[str]
    number_of_results: int | None


def web_search(data):
    network_allowed()
    endpoint = os.environ.get('TWYLT_SEARXNG_URL','').rstrip('/')
    if not endpoint: raise ValueError('Configure TWYLT_SEARXNG_URL with your SearXNG base URL')
    parsed = check_url(endpoint)
    if parsed.query or parsed.fragment: raise ValueError('SearXNG base URL must not contain query or fragment')
    params = dict(q=data.query,format='json',pageno=data.page,language=data.language,categories=data.categories,safesearch=data.safe_search)
    if data.time_range: params['time_range'] = data.time_range
    result = http(CurlInput(url=endpoint+'/search?'+urllib.parse.urlencode(params),timeout=data.timeout,max_bytes=5_000_000,headers={'Accept':'application/json'}))
    if not result.ok: raise RuntimeError(f'SearXNG HTTP {result.status}; enable JSON format on the server')
    raw = json.loads(result.text or '')
    entries = [SearchEntry(title=x.get('title',''),url=x['url'],snippet=x.get('content',''),engines=x.get('engines',[])) for x in raw.get('results',[])[:data.limit]]
    return SearchOutput(query=data.query,page=data.page,results=entries,suggestions=raw.get('suggestions',[]),number_of_results=raw.get('number_of_results'))

class EssentialTool(WorkspaceTransport, Tool[WgetInput, HttpOutput]):
    input_model = WgetInput
    output_model = HttpOutput
    name = 'wget'
    version = '0.1.1'
    description = 'Download an HTTP(S) resource to a workspace file.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt==1.0.0\npydantic>=2,<3\n')
    few_shots = [{'input': {'url': 'https://example.com/', 'output_path': 'example.html'}, 'output': {'status': 200, 'ok': True, 'headers': {}, 'bytes_received': 0, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'output_path': '/example.html', 'elapsed_seconds': 0.1}}]
    input_schema_name = 'wget.input'
    input_schema_version = '1.0.0'
    output_schema_name = 'wget.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return http(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
