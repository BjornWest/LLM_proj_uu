"""Independent saved-state replay of the versioned strict-draft repair; no runs."""
import argparse
import json
from pathlib import Path
from data.curation.expansion import review_authored03_native as prior
from data.curation.expansion.tricky.authored03 import grader, grader_v2


def review(suite):
    result=prior.review(suite)
    ids={r['task_id'] for r in result['records']}
    assert ids=={'AU46','AU47','AU51','AU52'} and len(result['records'])==8
    tasks={t['id']:t for t in json.loads((prior.AUTHORED/'contracts.json').read_text())['tasks']}
    boundary=[]
    for tid in sorted(ids):
        t=tasks[tid];expected=t['grader_input']['expected']
        field='message_draft' if tid in {'AU46','AU47'} else 'alert_email';value=expected[field]
        state={'form_fields':dict(expected),'path':t['grader_input']['required_final_path']}
        assert grader_v2.grade(t,None,state,[])['task_completed']
        values=[value.swapcase(),value+' ',value.replace(' ','  ') if ' ' in value else value+'.',value.rstrip('.') if value.endswith('.') else value+'.',None,123]
        for v in values:
            if v==value:continue
            s={**state,'form_fields':{**state['form_fields'],field:v}}
            old=grader.grade(t,None,s,[])['task_completed'];new=grader_v2.grade(t,None,s,[])['task_completed']
            assert new is False
            boundary.append({'task_id':tid,'field':field,'candidate_value':v,'old_completed':old,'new_completed':new})
    assert any(b['old_completed'] for b in boundary)
    result.update(schema='tricky-authored03-drafts-v2-independent-review',instances=4,accepted_instances=4,held_ids=[],hold_reason=None,templates=2,sites=['health','news'],
                  reviewed_ids=sorted(ids),newly_accepted_ids=['AU46','AU47'],boundary_checks=boundary,
                  reviewer_sha256=prior.sha(Path(__file__)),saved_state_reviewer_sha256=prior.sha(Path(prior.__file__)),
                  exact_grader_sha256=prior.sha(Path(grader_v2.__file__)),prior_grader_sha256=prior.sha(Path(grader.__file__)))
    result['limitations'].append('News alert submission remains ungraded; accepted scope is exact visible draft plus final page, with broader authorization unknown.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();r=review(a.suite.resolve())
    with a.output.open('x') as out:json.dump(r,out,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in r.items() if k not in ['records','boundary_checks']},indent=2))
