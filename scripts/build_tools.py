from pathlib import Path
import json
BASE = Path(__file__).resolve().parents[1]
common = (BASE/'src/common.py').read_text().replace('from workspace import Workspace, WorkspaceTransport, WorkspaceDenied',(BASE/'src/workspace.py').read_text())
specs = {
'echo': ('EchoInput','EchoOutput','echo','Return the request text unchanged.',{'text':'Hello, TWYLT!'}, {'text':'Hello, TWYLT!'}),
'sleep': ('SleepInput','SleepOutput','sleep','Wait in real time.',{'seconds':1},{'requested_seconds':1,'elapsed_seconds':1.001}),
'wget': ('WgetInput','HttpOutput','http','Download an HTTP(S) resource to a workspace file.',{'url':'https://example.com/','output_path':'example.html'},{'status':200,'ok':True,'headers':{},'bytes_received':0,'sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','output_path':'/example.html','elapsed_seconds':0.1}),
'curl': ('CurlInput','HttpOutput','http','Perform an HTTP(S) request; return text/base64 or save a workspace file.',{'url':'https://example.com/'},{'status':200,'ok':True,'headers':{},'bytes_received':0,'sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','text':'','elapsed_seconds':0.1}),
'ping': ('PingInput','PingOutput','ping','Check ICMP reachability using the operating system ping utility.',{'host':'127.0.0.1','count':1},{'reachable':True,'timed_out':False,'returncode':0,'stdout':'','stderr':'','elapsed_seconds':0.01}),
'web_search': ('SearchInput','SearchOutput','web_search','Search the web through a configured SearXNG JSON API.',{'query':'TWYLT github'},{'query':'TWYLT github','page':1,'results':[],'suggestions':[],'number_of_results':0}),
}
manifest = {'name':'twylt-pack-essential','version':'0.1.1','protocol':'TWYLT 1','tools':[]}
for name,(inp,out,call,description,example,answer) in specs.items():
    folder = BASE/'tools'/name
    folder.mkdir(parents=True,exist_ok=True)
    code = common + f'''
class EssentialTool(WorkspaceTransport, Tool[{inp}, {out}]):
    input_model = {inp}
    output_model = {out}
    name = {name!r}
    version = '0.1.1'
    description = {description!r}
    requirements = Requirements(tool='pip', format='requirements.txt', content={(BASE/'requirements.txt').read_text()!r})
    few_shots = {[{'input':example,'output':answer}]!r}
    input_schema_name = '{name}.input'
    input_schema_version = '1.0.0'
    output_schema_name = '{name}.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return {call}(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
'''
    (folder/'tool.py').write_text(code)
    (folder/'run.py').write_text('from pathlib import Path\nfrom twylt.bootstrap import run_tool_file\nif __name__ == "__main__":\n    run_tool_file(Path(__file__).with_name("tool.py"))\n')
    (folder/'example.json').write_text(json.dumps(example,indent=2)+'\n')
    manifest['tools'].append(dict(name=name,entrypoint=f'tools/{name}/tool.py',bootstrap=f'tools/{name}/run.py',description=description))
(BASE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
