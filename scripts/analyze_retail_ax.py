"""Offline measurements and proper native-tool examples from retained AX captures."""
from collections import Counter
import argparse,hashlib,json
from pathlib import Path
from intent_browser.ax_context import AXContext
from intent_browser.standard_profile import standard_profile

BASE=Path('.local/retail-ax-study/20260925-v1')
CASES={
 'elgiganten':BASE/'capture-v2/elgiganten/scrolled',
 'elgiganten-specs':BASE/'disclosures/elgiganten/specifications',
 'amazon':BASE/'capture-v2/amazon/scrolled',
 **{d:BASE/('capture-v2/local-'+d+'/initial') for d in ('department-market','editorial-boutique','technical-catalog')},
}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--cases',type=Path);parser.add_argument('--output',type=Path,default=BASE/'analysis-v1');args=parser.parse_args()
 cases={k:Path(v) for k,v in json.loads(args.cases.read_text()).items()} if args.cases else CASES
 out=args.output;out.mkdir(exist_ok=False);results={}
 for name,path in cases.items():
  raw=json.loads(Path(str(path)+'.raw-ax.json').read_text());metrics=json.loads(Path(str(path)+'.metrics.json').read_text())
  cx=AXContext(standard_profile(helpers=False,data_tools=False).ax_config)
  cx.capture({'url':metrics['url'],'axtree_object':raw})
  nodes=cx.nodes
  def count(i):return 1+sum(count(k) for k in nodes[i]['children'])
  regions=[{'index':n['index'],'role':n['role'],'name':n['name'],'nodes':count(n['index'])} for n in nodes if n['role'] in ('main','banner','contentinfo','navigation','complementary','radiogroup','dialog','alertdialog','region','table','tabpanel')]
  controls={'button','link','combobox','checkbox','radio','textbox','searchbox','spinbutton','tab','slider','DisclosureTriangle','menuitem','switch'}
  ambiguous=Counter((n['role'],n['name']) for n in nodes if n['role'] in controls and n['name'])
  depths={}
  for n in nodes:
   d=0;p=n['parent']
   while p is not None:d+=1;p=nodes[p]['parent']
   depths[n['index']]=d
  comparisons={'semantic_nodes':len(nodes),'max_depth':max(depths.values()),'roles':dict(Counter(n['role'] for n in nodes)),
               'named_repeat_groups':sum(v>1 for v in ambiguous.values()),'max_control_label_repeat':max(ambiguous.values(),default=0),
               'unnamed_interactive':sum(n['role'] in controls and not n['name'] for n in nodes),'regions':regions}
  examples=[]
  for query in [['Lägg i kundvagn','Add to Cart','Add to cart'],['Internt lagringsutrymme','256GB','EU shoe size'],['specifikation','Specifications','Product facts'],['leverans','delivery']]:
   cx.reset_delivery()
   response=cx.search(query,verbose=False,repeat=True,limit=5)
   examples.append({'query':query,'result':response})
  # Meaningful relative positions, not just root size/depth.
  additions=[]
  for n in nodes:
   if n['role']=='button' and n['name'] in ('Lägg i kundvagn','Add to cart','Add to Cart'):
    chain=[];parent=n['parent']
    while parent is not None:
     p=nodes[parent];chain.append({'role':p['role'],'name':p['name'],'children':len(p['children'])});parent=p['parent']
    additions.append({'index':n['index'],'depth':depths[n['index']],'ancestors':chain})
  comparisons['add_button_locations']=additions
  comparisons['capture_metrics']=metrics
  comparisons['input_sha256']={suffix:hashlib.sha256(Path(str(path)+suffix).read_bytes()).hexdigest() for suffix in ('.raw-ax.json','.metrics.json')}
  results[name]=comparisons
  (out/(name+'.tool-examples.json')).write_text(json.dumps(examples,ensure_ascii=False,indent=2))
 (out/'analysis.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 (out/'source.py').write_bytes(Path(__file__).read_bytes())
 print('Saved offline comparisons and corrected multi-term tool examples; no browser or model calls.')
if __name__=='__main__':main()
