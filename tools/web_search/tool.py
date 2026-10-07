from twylt import Tool, Requirements
import json
import os
import urllib.parse
from typing import Literal
from pydantic import Field
from twylt.guardrails import check_network
from twylt_pack_essential.http import HttpInput, http, check_url

from twylt import ContractModel as Model

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
    check_network('web_search')
    endpoint = os.environ.get('TWYLT_SEARXNG_URL','').rstrip('/')
    if not endpoint: raise ValueError('Configure TWYLT_SEARXNG_URL with your SearXNG base URL')
    parsed = check_url(endpoint)
    if parsed.query or parsed.fragment: raise ValueError('SearXNG base URL must not contain query or fragment')
    params = dict(q=data.query,format='json',pageno=data.page,language=data.language,categories=data.categories,safesearch=data.safe_search)
    if data.time_range: params['time_range'] = data.time_range
    result = http(HttpInput(url=endpoint+'/search?'+urllib.parse.urlencode(params),timeout=data.timeout,max_bytes=5_000_000,headers={'Accept':'application/json'}))
    if not result.ok: raise RuntimeError(f'SearXNG HTTP {result.status}; enable JSON format on the server')
    raw = json.loads(result.text or '')
    entries = [SearchEntry(title=x.get('title',''),url=x['url'],snippet=x.get('content',''),engines=x.get('engines',[])) for x in raw.get('results',[])[:data.limit]]
    return SearchOutput(query=data.query,page=data.page,results=entries,suggestions=raw.get('suggestions',[]),number_of_results=raw.get('number_of_results'))

class EssentialTool(Tool[SearchInput, SearchOutput]):
    input_model = SearchInput
    output_model = SearchOutput
    name = 'web_search'
    version = '0.2.0'
    description = 'Search the web through a configured SearXNG JSON API.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.0,<2\npydantic>=2,<3\ntwylt-pack-essential==0.2.0\n')
    few_shots = [{'input': {'query': 'TWYLT github'}, 'output': {'query': 'TWYLT github', 'page': 1, 'results': [], 'suggestions': [], 'number_of_results': 0}}]
    input_schema_name = 'web_search.input'
    input_schema_version = '1.0.0'
    output_schema_name = 'web_search.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return web_search(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
