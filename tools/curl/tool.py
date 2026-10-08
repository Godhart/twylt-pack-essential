from twylt import Tool, Requirements
from typing import Literal
from pydantic import Field, model_validator
# Shared code travels with the source pack; its location does not depend on cwd.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from essential_common.http import HttpInput, HttpOutput, http

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

class EssentialTool(Tool[CurlInput, HttpOutput]):
    input_model = CurlInput
    output_model = HttpOutput
    name = 'curl'
    version = '0.3.0'
    description = 'Perform an HTTP(S) request; return text/base64 or save a workspace file.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.0,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'url': 'https://example.com/'}, 'output': {'status': 200, 'ok': True, 'headers': {}, 'bytes_received': 0, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'text': '', 'elapsed_seconds': 0.1}}]
    input_schema_name = 'curl.input'
    input_schema_version = '1.0.0'
    output_schema_name = 'curl.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return http(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
