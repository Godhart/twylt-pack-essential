import base64
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from pydantic import Field
from twylt.guardrails import Workspace, check_network


from twylt import ContractModel as Model

class HttpInput(Model):
    url: str = Field(description='HTTP or HTTPS URL.')
    headers: dict[str, str] = Field(default_factory=dict, description='Request headers.')
    timeout: float = Field(default=30, gt=0, le=600, description='Socket timeout and checked total deadline, seconds.')
    max_bytes: int = Field(default=10_000_000, ge=1, le=1_000_000_000, description='Maximum downloaded response bytes.')
    follow_redirects: bool = Field(default=True, description='Follow at most ten HTTP(S) redirects.')
    output_path: str | None = Field(default=None, description='Virtual workspace path; otherwise return response body.')
    overwrite: bool = Field(default=False, description='Explicitly permit replacement of destination.')

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
    check_network('http')
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
