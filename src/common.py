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
from workspace import Workspace, WorkspaceTransport, WorkspaceDenied

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
