import json
import sys
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

har, response, output, task_id = sys.argv[1:]
api = WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__REDDIT__': {'urls': ['http://localhost:19079']}}))
result = api.evaluate_task(task_id=int(task_id), agent_response=json.loads(Path(response).read_text()), network_trace=Path(har)).model_dump(mode='json')
Path(output).write_text(json.dumps(result, indent=2) + '\n')
