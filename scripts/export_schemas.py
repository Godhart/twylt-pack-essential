from pathlib import Path
import importlib.util
import json
BASE = Path(__file__).resolve().parents[1]
(BASE/'schemas').mkdir(exist_ok=True)
for path in sorted((BASE/'tools').glob('*/tool.py')):
    spec = importlib.util.spec_from_file_location('essential_'+path.parent.name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (BASE/'schemas'/f'{path.parent.name}.json').write_text(json.dumps(module.TOOL.json_spec(),ensure_ascii=False,indent=2)+'\n')
