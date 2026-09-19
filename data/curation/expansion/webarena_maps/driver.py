"""Source-derived scripted-control scaffold; never fabricates an answer or success.

The injected binding must provide page, act(locator,operation,value), record,
and current AX text using the actual native BrowserGym driver. No browser is
created here. Selectors are source-supported hypotheses until live preflight.
"""
import re
from .staging import contract,policy_projection
ENGINE_LABELS={'driving':'Car (OSRM)','walking':'Foot (OSRM)','cycling':'Bicycle (OSRM)'}
class RuntimeProofRequired(RuntimeError):pass

def visible_time_to_hms(text):
    match=re.fullmatch(r'(\d+):([0-5]\d)',text.strip())
    if not match:raise ValueError('Expected original visible H:MM format')
    return f'{int(match[1]):02}:{match[2]}:00'

def one_hour_from_rounded_minutes(text):
    h,m,s=map(int,visible_time_to_hms(text).split(':'));minutes=h*60+m
    return None if minutes==60 else minutes<60

def effective_mode(request_url):
    from urllib.parse import urlsplit
    match=re.search(r'/(routed-(car|bike|foot))/route/v1/driving/',urlsplit(request_url).path)
    return {'car':'driving','bike':'cycling','foot':'walking'}[match[2]]if match else None

def source_plan(task_id):
    task=contract(task_id);slots=task['driver_public_slots']
    actions=[]
    if 'query'in slots:
        actions=[{'op':'fill','selector':'#query','value':slots['query']},{'op':'press','selector':'#query','value':'Enter'}, {'op':'capture_visible_only','selector':'#sidebar_content'}]
    else:
        actions=[{'op':'click','selector':'.search_form a.switch_link'}, {'op':'fill','selector':'#route_from','value':slots['from']},{'op':'fill','selector':'#route_to','value':slots['to']}]
        for mode in slots['modes']:
            actions += [{'op':'select_visible_label','selector':'select.routing_engines','value':ENGINE_LABELS[mode]}, {'op':'click','selector':'.directions_form .routing_go'},{'op':'capture_visible_only','selector':'#sidebar_content','requested_mode':mode}]
    return {'source_task_id':task_id,'policy_input':policy_projection(task),'actions':actions,'ends_with':'RuntimeProofRequired: answer/grading bindings intentionally not implemented','source_only':True,'browser_executed':False}

class MapsScriptedScaffold:
    def __init__(self,task_id,binding):self.task=contract(task_id);self.binding=binding
    def steps(self):
        b=self.binding;p=b.page
        for item in source_plan(self.task['source_task_id'])['actions']:
            loc=p.locator(item['selector'])
            if item['op']=='capture_visible_only':
                b.record('maps_unverified_visible_result',{'sidebar':loc.inner_text(),'url':p.url,'requested_mode':item.get('requested_mode'),'driver_observation_only':True})
            elif item['op']=='select_visible_label':
                options=loc.locator('option').evaluate_all('es=>es.map(e=>({value:e.value,label:e.textContent}))')
                matches=[o for o in options if o['label'].strip()==item['value']]
                if len(matches)!=1 or item['value']not in b.text:raise RuntimeProofRequired('Original selected engine label not established in delivered AX')
                yield b.act(loc,'select_option',matches[0]['value'])
            elif item['op']=='click':yield b.act(loc)
            else:yield b.act(loc,item['op'],item['value'])
        raise RuntimeProofRequired('Scaffold stopped before answer/success: actual endpoint identity, visible answer and independent grading need browser validation')
