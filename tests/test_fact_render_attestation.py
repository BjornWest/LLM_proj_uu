"""Source-only normalization checks; actual BrowserGym acceptance stays pending."""
from copy import deepcopy
import json
import subprocess

import pytest

from training.browser_training.fact_render_capture import attest, _render_attestation_function


def test_bookkeeping_is_ignored_but_content_and_control_mutations_are_not():
    script=_render_attestation_function()+r'''
      const text={nodeType:3,nodeName:'#text',nodeValue:'49 kr',childNodes:[]};
      const input={nodeType:1,nodeName:'INPUT',nodeValue:null,attributes:[
        {name:'type',value:'checkbox'},{name:'value',value:'default'}],
        value:'current',checked:false,indeterminate:false,childNodes:[]};
      const root={nodeType:1,nodeName:'DIV',nodeValue:null,
        attributes:[{name:'id',value:'app'},{name:'aria-label',value:'Shipping'}],childNodes:[text,input]};
      const baseline=JSON.stringify(renderAttestation(root));
      const equal=()=>JSON.stringify(renderAttestation(root))===baseline;
      root.attributes.push({name:'bid',value:'7'},
        {name:'browsergym_visibility_ratio',value:'0.3'},
        {name:'browsergym_set_of_marks',value:'1'});
      input.attributes.find(a=>a.name==='value').value='current';
      root.attributes.reverse();
      const results={bookkeeping:equal()};
      text.nodeValue='59 kr';results.text=equal();text.nodeValue='49 kr';
      input.value='other';results.value=equal();input.value='current';
      input.checked=true;results.checked=equal();input.checked=false;
      input.indeterminate=true;results.indeterminate=equal();input.indeterminate=false;
      root.attributes.find(a=>a.name==='aria-label').value='Changed';
      results.aria=equal();root.attributes.find(a=>a.name==='aria-label').value='Shipping';
      root.attributes.push({name:'hidden',value:''});results.hidden=equal();root.attributes.pop();
      root.childNodes.reverse();results.order=equal();root.childNodes.reverse();
      input.nodeName='SELECT';results.element=equal();input.nodeName='INPUT';
      const select={nodeType:1,nodeName:'OPTION',nodeValue:null,attributes:[],
        value:'42',selected:false,childNodes:[]};
      const selectedBefore=JSON.stringify(renderAttestation(select));
      select.selected=true;results.selected=JSON.stringify(renderAttestation(select))===selectedBefore;
      input.shadowRoot={};try{renderAttestation(root);results.shadow=false;}catch{results.shadow=true;}
      console.log(JSON.stringify(results));
    '''
    result=subprocess.run(['node','--input-type=module','-'],input=script,text=True,
                          capture_output=True,check=True,timeout=10)
    assert json.loads(result.stdout)=={
        'bookkeeping':True,'text':False,'value':False,'checked':False,
        'indeterminate':False,'aria':False,'hidden':False,'order':False,
        'element':False,'selected':False,'shadow':True}


class Page:
    def __init__(self, actual):self.actual=actual;self.calls=[]
    def evaluate(self, script, key):
        self.calls.append((script,key));return deepcopy(self.actual)


@pytest.mark.parametrize('kind',['html','render_state'])
def test_exports_choose_strict_legacy_or_structural_attestation(kind):
    value='<div>49 kr</div>' if kind=='html' else {
        'schema':'fact-render-state-browsergym-v1','tree':['exact structure']}
    actual={'url':'https://shop.test/','draft':{'variant':'42'},kind:value}
    page=Page(actual);commit={'meta':{'state_key':'private',**actual}}
    assert attest(page,commit)==actual
    assert page.calls[0][1]=={'selector':'#app','key':'private','static':False}
    if kind=='render_state':
        assert 'renderAttestation(' in page.calls[0][0]
        commit['meta']['html']='old unmarked HTML' # remains archival, not a second check
        assert attest(page,commit)==actual
    for field in ['url','draft',kind]:
        changed=deepcopy(actual);changed[field]='changed';page.actual=changed
        with pytest.raises(ValueError,match='stale'):attest(page,commit)


def test_unknown_attestation_version_is_rejected_before_reading_page():
    page=Page({});commit={'meta':{'render_state':{'schema':'unqualified'}}}
    with pytest.raises(ValueError,match='Unqualified'):attest(page,commit)
    assert page.calls==[]
