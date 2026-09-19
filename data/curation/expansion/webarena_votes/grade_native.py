import json,sys
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
har,response,output,tid=sys.argv[1:]
a=WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__REDDIT__':{'urls':['http://localhost:19099']}}))
r=a.evaluate_task(task_id=int(tid),agent_response=json.loads(Path(response).read_text()),network_trace=Path(har)).model_dump(mode='json')
Path(output).write_text(json.dumps(r,indent=2)+'\n')
