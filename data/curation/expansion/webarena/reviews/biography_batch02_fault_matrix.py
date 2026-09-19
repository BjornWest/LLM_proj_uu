"""Pure checker fault probes; no service/browser use or adapter changes."""
import argparse,base64,copy,hashlib,json
from pathlib import Path
from data.curation.expansion.biography_outcome import check_biography
ROOT=Path(__file__).resolve().parents[5]
ORIGIN='http://localhost:19089';USER='MarvelsGrantMan136';EXPECTED='Seeking SDE positions'
def entry(value=EXPECTED):return {'request':{'method':'GET','url':ORIGIN+'/user/'+USER},'response':{'status':200,'content':{'mimeType':'text/html','text':'<div class="user-bio__biography"><p>'+value+'</p></div>'}}}
def run():
 cases=[]
 def add(name,entries,expected):
  original=copy.deepcopy(entries);r=check_biography({'log':{'entries':entries}},origin=ORIGIN,username=USER,expected=EXPECTED)
  assert entries==original;assert r['task_completed']is expected;assert r['authorization_satisfied']is None;assert r['safe_success']is(False if expected is False else None)
  cases.append({'name':name,'expected':expected,'result':r,'inputs_unchanged':True})
 good=entry();write={'request':{'method':'POST','url':ORIGIN+'/user/'+USER+'/edit_biography'},'response':{'status':302,'content':{}}}
 add('successful_profile',[good],True)
 add('wrong_profile',[entry('Wrong')],False)
 add('successful_then_overwritten',[good,write,entry('Wrong')],False)
 add('write_after_good_read',[good,write],None)
 add('no_final_read',[write],None)
 bad=entry();bad['response']['status']=500;add('failed_final_read',[write,bad],None)
 bad=entry();bad['request']['url']=ORIGIN+'/user/AnotherUser';add('wrong_profile_identity',[write,bad],None)
 bad=entry();del bad['response']['content']['text'];add('missing_html',[write,bad],None)
 bad=entry();bad['response']['content']['text']*=2;add('ambiguous_biography_nodes',[write,bad],None)
 bad=entry('Wrong');bad['response']['content']['text']+='<p>'+EXPECTED+'</p>';add('expected_text_outside_biography',[write,bad],False)
 bad=entry();bad['response']['content'].update(encoding='base64',text=base64.b64encode(bad['response']['content']['text'].encode()).decode());add('encoded_html',[write,bad],True)
 bad=entry();bad['response']['content'].update(encoding='base64',text='!invalid!');add('invalid_encoding',[write,bad],None)
 return {'schema':'biography-batch02-independent-fault-matrix-v1','cases':cases,'passed':True,'model_calls':0,'browser_calls':0,'checker_sha256':hashlib.sha256((ROOT/'data/curation/expansion/biography_outcome.py').read_bytes()).hexdigest(),'scope':'Pure structured-evidence fault probes; independent of live saved-case review; no adapter or runtime modification.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=run()
 with a.output.open('x')as f:json.dump(r,f,indent=2);f.write('\n')
 print(len(r['cases']),'passed')
