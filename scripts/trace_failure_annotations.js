// Derived reviewer notes never replace recorded grades, stop reasons or messages.
const failureAnnotationPanel=node('section','notice');failureAnnotationPanel.id='failure-annotation';failureAnnotationPanel.hidden=true;
el('notices').before(failureAnnotationPanel);
let failureAnnotationSignature=null;
let lastFailureAnnotations=null;
const knownFailureAnnotationIds=new Set();
const originalFailureMetadataRefresh=refreshCollections;
refreshCollections=async function(signal,isCurrent=()=>true){
 const previous=collectionState,own=collectionGeneration+1;
 await originalFailureMetadataRefresh(signal,isCurrent);
 if(collectionGeneration===own&&collectionState!==previous&&isCurrent()&&!signal?.aborted){
  lastFailureAnnotations=collectionState.failure_annotations??null;
  if(!lastFailureAnnotations?.error)knownFailureAnnotationIds.clear();
  for(const id of Object.keys(lastFailureAnnotations?.entries||{}))knownFailureAnnotationIds.add(id);
 }
};
function failureAnnotationFor(session){
 const bundle=lastFailureAnnotations,annotation=bundle?.entries?.[session?.id];
 if(bundle?.error&&knownFailureAnnotationIds.has(session?.id))return {binding_status:'invalid',error:bundle.error};
 if(annotation?.binding_status==='verified'&&!recordingLocations(session).includes(annotation.trace_directory+'/'))
  return {binding_status:'invalid',error:'Annotation targets a different recording directory.'};
 return annotation;
}
function renderFailureAnnotation(){
 const annotation=current?failureAnnotationFor(current):null;
 const error=annotation?.error;
 const signature=JSON.stringify([current?.id,annotation,error]);if(signature===failureAnnotationSignature)return;
 failureAnnotationSignature=signature;
 const open=failureAnnotationPanel.querySelector('details')?.open??false;
 failureAnnotationPanel.replaceChildren();failureAnnotationPanel.hidden=!annotation&&!error;
 if(failureAnnotationPanel.hidden)return;
 failureAnnotationPanel.append(node('b','',error?'Derived failure annotation unavailable':'Derived failure stage · '+annotation.label));
 if(error)failureAnnotationPanel.append(node('p','',error));
 else{
  failureAnnotationPanel.append(node('p','','Policy stop: '+annotation.policy_stop_reason.replaceAll('_',' ')+' · '+(annotation.answer_delivered?'Answer delivered':'No answer delivered')));
  failureAnnotationPanel.append(node('p','','Grading error: '+annotation.grading_error));
  if(annotation.policy_execution_error)failureAnnotationPanel.append(node('p','','Policy interruption: '+annotation.policy_execution_error));
  failureAnnotationPanel.append(node('p','',annotation.causal_scope));
 }
 failureAnnotationPanel.append(node('p','muted','Derived review annotation, not model input. Recorded grades and task verdicts are unchanged.'));
 if(!error){
  failureAnnotationPanel.append(node('p','muted','No native task verdict.'));
  const evidence=node('details');evidence.open=open;evidence.append(node('summary','','Bound evidence · original files unchanged'));
  evidence.append(contentView(JSON.stringify(annotation.evidence,null,2),current.id+':failure-annotation-evidence',[],0));
  failureAnnotationPanel.append(evidence);
 }
}
function renderSuiteFailureAnnotations(){
 const byId=new Map(sessions.map(session=>[session.id,session]));
 for(const row of document.querySelectorAll('#suite-view tbody tr[data-trace-id]')){
  const annotation=failureAnnotationFor(byId.get(row.dataset.traceId));
  const cell=row.children[4];let note=cell.querySelector('.failure-stage-note');
  if(!annotation){note?.remove();continue}
  if(!note){note=node('div','suite-note failure-stage-note');cell.append(note)}
  const text=annotation.binding_status==='verified'?'Derived: '+annotation.label:'Derived annotation unavailable';
  if(note.textContent!==text)note.textContent=text;
  const title=annotation.causal_scope||annotation.error||'';if(note.title!==title)note.title=title;
 }
}
