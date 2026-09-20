"""Current-policy scripted acceptance of the original Prislyktan task adapter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
from intent_browser.prislyktan import PrislyktanTask
from intent_browser.standard_profile import standard_profile
from intent_browser.runner import run_episode
from intent_browser.actions import make_action_set
from scripts.harness_suite_tasks import scripted_backend
from data.curation.aggregator_trial.verify import Driver


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',required=True)
    parser.add_argument('--negative',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    task=PrislyktanTask('prislyktan:'+args.task)
    holder={}
    backend=scripted_backend(Driver(task,holder,negative=args.negative))
    backend.requires_browser_thread=True
    backend.supports_images=True
    def factory(video):
        holder['env']=task.make_env(video,action_mapping=make_action_set().to_python_code)
        return holder['env']
    try:
        directory,result=run_episode(factory,backend,{'task':'prislyktan:'+args.task,'driver':'scripted-validation','training_eligible':False},
            output=args.output/'traces',episode_task=task,harness_profile=standard_profile(),max_steps=20,
            terminal_response_instruction='Return the answer requested by the goal using send_msg_to_user.')
        evaluation=result['evaluation']
        metadata=json.loads((directory/'metadata.json').read_text())
        checks={'expected_grade':evaluation['safe_success'] is (not args.negative),'no_action_errors':result['action_error_count']==0,
                'no_technical_error':result['error'] is None,'four_origins':len(metadata['harness_profile']['navigation']['allowed_origins'])==4}
        files={str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}
        report={'passed':all(checks.values()),'checks':checks,'trace':str(directory),'evaluation':evaluation,'artifact_sha256':files,'model_calls':0}
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if not report['passed']:raise SystemExit(1)
    finally:task.close()

if __name__=='__main__':main()
