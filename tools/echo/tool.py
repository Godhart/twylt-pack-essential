from twylt import Tool, Requirements
from pydantic import Field

from twylt import ContractModel as Model

class EchoInput(Model):
    text: str = Field(description='Text to return unchanged, including whitespace and line breaks.')

class EchoOutput(Model):
    text: str = Field(description='Exact text from the request.')

def echo(data):
    return EchoOutput(text=data.text)

class EssentialTool(Tool[EchoInput, EchoOutput]):
    input_model = EchoInput
    output_model = EchoOutput
    name = 'echo'
    version = '0.2.0'
    description = 'Return the request text unchanged.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.0,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'text': 'Hello, TWYLT!'}, 'output': {'text': 'Hello, TWYLT!'}}]
    input_schema_name = 'echo.input'
    input_schema_version = '1.0.0'
    output_schema_name = 'echo.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return echo(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
