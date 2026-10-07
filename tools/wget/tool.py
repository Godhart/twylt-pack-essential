from twylt import Tool, Requirements
from pydantic import Field
from twylt_pack_essential.http import HttpInput, HttpOutput, http

class WgetInput(HttpInput):
    output_path: str = Field(description='Required destination inside TWYLT_WORKSPACE_ROOT.')

class EssentialTool(Tool[WgetInput, HttpOutput]):
    input_model = WgetInput
    output_model = HttpOutput
    name = 'wget'
    version = '0.2.0'
    description = 'Download an HTTP(S) resource to a workspace file.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.0,<2\npydantic>=2,<3\ntwylt-pack-essential==0.2.0\n')
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
