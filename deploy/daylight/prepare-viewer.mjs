// Package a pinned shared viewer, failing closed when integration anchors change.
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('.',import.meta.url));
export async function prepareViewer(destination=path.join(root,'private-assets')){
  const provenance=JSON.parse(await readFile(path.join(root,'vendor/agent_trace/provenance.json'),'utf8'));
  let html=await readFile(path.join(root,'vendor/agent_trace/session_viewer.html'),'utf8');
  if(createHash('sha256').update(html).digest('hex')!==provenance.sha256)throw Error('Pinned shared viewer hash differs');
  const replace=(before,after)=>{if(html.split(before).length!==2)throw Error('Shared viewer anchor changed: '+before.slice(0,90));html=html.replace(before,after);};
  replace("if(!asset.url.startsWith('/artifacts/'))continue;",'if(!allowedViewerAsset(asset.url))continue;');
  replace("const line=node('div');line.append(a);box.append(line);","const line=node('details');line.append(node('summary','',asset.label),a);box.append(line);");
  replace("const response=await fetch('/api/sessions'+query);",'const response=await loadViewerIndex();');
  replace("const r=await fetch('/api/sessions/'+chosen.id+query);",'const r=await loadViewerSession(chosen.id);');
  replace("s.message_count+' events · '+s.decision_count+' decisions'","s.message_count+' recorded events'");
  replace("m.provenance==='actual_outbound_input'?'Captured outbound model input':'Selected context only — not the full model prompt'", "m.provenance==='actual_outbound_input'?'Captured outbound model input':m.provenance==='retained_request_input'?'Retained model request payload':'Selected context only — not the full model prompt'");
  replace("if(!messages.length)el('chat').append(node('p','muted','No recorded events match this filter. Missing model inputs and decisions are not inferred.'));", "if(!messages.length)el('chat').append(node('p','muted','No recorded events match this filter. Missing model inputs and decisions are not inferred.'));\nprojectExtension.update(current);");
  replace("el('count').textContent='';return}","el('count').textContent='';projectExtension.update(null);return}");
  replace('setInterval(async()=>{if(el(\'live\').checked&&!refreshing){refreshing=true;try{await refresh()}finally{refreshing=false}}},3000);refresh();', "const projectExtension=createBrowserExtension({jumpToMessage(id){el('filter').value='all';render();movePage(nearestIndex(id));}});\nel('live').checked=false;el('live').disabled=true;refresh();");
  replace('<input id="live" type="checkbox" checked> Live refresh','<input id="live" type="checkbox"> Saved trace');
  replace('Prompts, decisions and execution · local workspace','Recorded messages, tools and browser replay');
  replace('Agent / Session traces','Saved trace');
  replace('<div id="notices"></div>','<details id="recording-notes"><summary>Recording notes and limitations</summary><div id="notices"></div></details>');
  replace('<select id="parser" aria-label="Parsing mode">','<select id="parser" aria-label="Parsing mode" disabled>');
  const script=html.match(/<script>([\s\S]*?)<\/script>/),styles=[...html.matchAll(/<style>([\s\S]*?)<\/style>/g)];
  if(!script||!styles.length)throw Error('Shared viewer script/style missing');
  const js="import {createBrowserExtension,loadViewerIndex,loadViewerSession,allowedViewerAsset} from './trace-browser.js';\n"+script[1];
  html=html.replace(script[0],'<script type="module" src="/assets/trace-viewer.js"></script>').replace(/<style>[\s\S]*?<\/style>/g,'').replace('</title>','</title><link rel="stylesheet" href="/assets/trace-viewer.css"><link rel="stylesheet" href="/assets/tool-activity.css"><link rel="stylesheet" href="/assets/trace-browser.css">');
  await mkdir(destination,{recursive:true});
  for(const [name,body] of [['trace-viewer.html',html],['trace-viewer.js',js],['trace-viewer.css',styles.map(style=>style[1]).join('\n')],['trace-viewer-source.json',JSON.stringify(provenance,null,2)]])await writeFile(path.join(destination,name),body);
  for(const name of ['trace-browser.js','trace-browser.css'])await writeFile(path.join(destination,name),await readFile(path.join(root,'client',name)));
  return ['trace-viewer.html','trace-viewer.js','trace-viewer.css','trace-viewer-source.json','trace-browser.js','trace-browser.css'];
}
