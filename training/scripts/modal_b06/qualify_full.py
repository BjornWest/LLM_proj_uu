"""Once-only ordered-wire qualification; full episode lifecycle is caller-owned."""
from hashlib import sha256
from pathlib import Path
import base64
import io
import json

from pilot_relay import canonical, tokenize_payload
from producer_transport import http as request, wire_bytes, projection_binding


def qualify(origin, binding, qualification, output, request_pin, counter_source):
    fingerprint=projection_binding(Path(__file__).with_name("pilot_relay.py"), counter_source)
    fingerprint_sha=sha256(canonical(fingerprint)).hexdigest()
    if fingerprint_sha!=qualification["counter_projection_sha256"]:
        raise ValueError("Pre-dispatch counter projection differs")
    # This uses the actual accepted source for the local estimator. The paid
    # factory will independently count every exact request with server /tokenize.
    import importlib.util
    path = Path(binding['first_case']['source_root'])/'intent_browser/input_budget.py'
    module_spec = importlib.util.spec_from_file_location('pilot_accepted_input_budget',path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    counter = module.QwenInputCounter(binding['tokenizer']['tokenizer.json']['path'])
    from PIL import Image
    model = binding['model']['repository']
    live = request(origin,'/qualification')
    if not (live == qualification):
        raise ValueError('Qualification failed: live == qualification')
    if not (qualification['hardware']['capability'] == [12, 0]):
        raise ValueError("Qualification failed: qualification['hardware']['capability'] == [12, 0]")
    models = request(origin,'/v1/models')
    if not (any((m['id'] == model and m['max_model_len'] == 131072 for m in models['data']))):
        raise ValueError(models)
    info = request(origin,'/tokenizer_info')
    template = Path(binding['tokenizer']['chat_template.jinja']['path']).read_text()
    if not (info['chat_template'] == template):
        raise ValueError("Qualification failed: info['chat_template'] == template")
    # Use the actual22-tool schema, including order-sensitive nested unions.
    tools=json.loads(request_pin.read_text())['tools']
    def png(width,height):
        stream=io.BytesIO();Image.new('RGB',(width,height),'white').save(stream,format='PNG')
        return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()}}
    probes=[]
    for w,h in ((64,64),(1280,720),(2048,1024)):
        probes.append((f'image-{w}x{h}',[{'role':'user','content':[{'type':'text','text':'Inspect this page.'},png(w,h)]}],tools))
    history=[{'role':'user','content':[{'type':'text','text':'Inspect the page.'},png(1280,720)]},
        {'role':'assistant','content':None,'reasoning_content':'First inspect the target, then compare its price.',
         'tool_calls':[{'id':'parity-1','type':'function','function':{'name':'ax_search','arguments':'{"limit":5,"query":"42"}'}}]},
        {'role':'tool','tool_call_id':'parity-1','content':'The page is now visible.'},
        {'role':'user','content':[{'type':'text','text':'Continue.'},png(2048,1024)]}]
    probes.append(('retained-history',history,tools))
    # Exact near-ISL probe with tools; count only first, then a two-token GPU
    # forward. No arbitrary shortening of actual episode context/tool budgets.
    boundary=[{'role':'user','content':' x'*99000}]
    for _ in range(4):
        n=counter(boundary,tools)['input_tokens']
        if n==100000: break
        boundary[0]['content']=' x'*(boundary[0]['content'].count(' x')+100000-n)
    if not (counter(boundary, tools)['input_tokens'] == 100000):
        raise ValueError("Qualification failed: counter(boundary, tools)['input_tokens'] == 100000")
    probes.append(('100000-input-boundary',boundary,tools))
    rows=[]
    def progress():
        # Keep partial qualification evidence even when a later assertion stops
        # the pilot; this is not a passing readiness/dispatch receipt.
        (output/'qualification-progress.json').write_bytes(canonical(
            dict(passed=False,parity_probes=rows,serving_session_id=qualification['serving_session_id'])))
    independent_controls=False
    for label,messages,selected_tools in probes:
        body=dict(model=model,messages=messages,tools=selected_tools,tool_choice='auto',parallel_tool_calls=False,
                  temperature=0,max_tokens=2,stream=False)
        measured=request(origin,'/tokenize',tokenize_payload(body))
        expected=counter(messages,selected_tools)['input_tokens']
        rows.append(dict(probe=label,input_tokens=expected,server=measured,
                         wire_bytes=len(wire_bytes(body)),generation=None))
        progress()
        if not (measured['count'] == expected and measured['max_model_len'] == 131072):
            raise ValueError((label, measured, expected))
        if label in {'retained-history','100000-input-boundary'}:
            done=request(origin,'/v1/chat/completions',{**body,'return_token_ids':True})
            (output/(label+'-generation.json')).write_bytes(canonical(done))
            if not (done['usage']['prompt_tokens'] == expected):
                raise ValueError((label, done['usage'], expected))
            if not (done['usage']['completion_tokens'] <= 2):
                raise ValueError("Qualification failed: done['usage']['completion_tokens'] <= 2")
            if not (sha256(canonical(done['prompt_token_ids'])).hexdigest() == measured['token_ids_sha256']):
                raise ValueError("Qualification failed: sha256(canonical(done['prompt_token_ids'])).hexdigest() == measured['token_ids_sha256']")
            rows[-1]['generation']=done['usage']
            progress()
            if label=='retained-history':
                alternate={**body,'parallel_tool_calls':True,'max_tokens':1}
                changed=request(origin,'/v1/chat/completions',{**alternate,'return_token_ids':True})
                (output/(label+'-alternate-controls.json')).write_bytes(canonical(changed))
                if not (changed['usage']['prompt_tokens'] == expected):
                    raise ValueError("Qualification failed: changed['usage']['prompt_tokens'] == expected")
                if not (changed['usage']['completion_tokens'] <= 1):
                    raise ValueError("Qualification failed: changed['usage']['completion_tokens'] <= 1")
                if not (changed['prompt_token_ids'] == done['prompt_token_ids']):
                    raise ValueError("Qualification failed: changed['prompt_token_ids'] == done['prompt_token_ids']")
                rows[-1]['alternate_controls_generation']=changed['usage']
                progress()
                independent_controls=True
    if not (independent_controls):
        raise ValueError('Qualification failed: independent_controls')
    return dict(parser_patch_sha256=qualification['parser_patch_sha256'],runtime_projection=fingerprint,counter_projection_sha256=fingerprint_sha,
        wire_serialization='json-insertion-order-v1',counter_wire_function_sha256=fingerprint['counter_wire_function_sha256'],
        counter_projection_digest_format='sha256-compact-sorted-utf8-json-of-runtime-projection-v1',
        passed=True,ready=True,identity=qualification['identity'],server_context=131072,isl=100000,
        serving_session_id=qualification['serving_session_id'],deadline=qualification['deadline'],platform_lifetime=qualification['platform_lifetime'],
        vision=True,native_tools=True,exact_complete_request_counter=True,
        parity_probes=rows,output_controls_prompt_independent=True,parallel_tool_calls_prompt_independent=True,
        tokenize_projection_source_sha256=fingerprint['tokenize_projection_source_sha256'],
        qualification='Actual /tokenize and tiny GPU prompt-usage parity, including changed output/parallel controls; configured native tool parser. B06 verifies actual tool behavior.',
        per_request_counter='Exact server /tokenize; retain actual counts and compare generation usage')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--origin',required=True);p.add_argument('--binding',type=Path,required=True);p.add_argument('--identity',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--request',type=Path,required=True);p.add_argument('--counter-source',type=Path,required=True)
    args=p.parse_args()
    gates=qualify(args.origin,json.loads(args.binding.read_text()),json.loads(args.identity.read_text()),args.output,args.request,args.counter_source)
    (args.output/'readiness.json').write_text(json.dumps(gates,indent=2)+'\n')
