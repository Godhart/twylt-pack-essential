from twylt import Tool, Requirements
import time
from pydantic import Field

from twylt import ContractModel as Model

class SleepInput(Model):
    seconds: float = Field(ge=0, le=86400, description='Real elapsed seconds to wait (maximum one day).')

class SleepOutput(Model):
    requested_seconds: float
    elapsed_seconds: float

def sleep(data):
    start = time.monotonic()
    time.sleep(data.seconds)
    return SleepOutput(requested_seconds=data.seconds, elapsed_seconds=time.monotonic()-start)

class EssentialTool(Tool[SleepInput, SleepOutput]):
    input_model = SleepInput
    output_model = SleepOutput
    name = 'sleep'
    version = '0.2.0'
    description = 'Wait in real time.'
    requirements = Requirements(tool='pip', format='requirements.txt', content='twylt>=1.1.0,<2\npydantic>=2,<3\n')
    few_shots = [{'input': {'seconds': 1}, 'output': {'requested_seconds': 1, 'elapsed_seconds': 1.001}}]
    input_schema_name = 'sleep.input'
    input_schema_version = '1.0.0'
    output_schema_name = 'sleep.output'
    output_schema_version = '1.0.0'
    def biz(self, data):
        return sleep(data)

TOOL = EssentialTool
if __name__ == '__main__':
    EssentialTool.run()
