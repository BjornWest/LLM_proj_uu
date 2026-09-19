// Presentation metadata is separate from task contracts, execution mode and grades.
import {createHash} from 'node:crypto';
import sites from '../../../config/team_sites.json' with {type:'json'};
import expanded from '../../../config/expanded_team_tasks.json' with {type:'json'};
const siteRevision=createHash('sha256').update(JSON.stringify(sites)).digest('hex');
const insist=(ok,message)=>{if(!ok)throw Object.assign(Error(message),{status:400});};
export function interactionKind(value) {
  const kind=value??null;
  insist(kind===null||kind==='task'||kind==='ask','Invalid interaction kind');
  return kind;
}
export function siteForTask(id) {
  const added=expanded.tasks.find(task=>task.id===id);
  if(added)return {site_id:added.site_id,site_name:added.site_name,collection:added.collection,
    collection_name:added.collection_name,site_registry_revision:expanded.catalog_sha256};
  const matches=sites.sites.filter(site=>site.tasks.includes(id));
  if(sites.schema_version!==1||matches.length!==1)throw Error('Task has no unique reviewed site mapping');
  return {site_id:matches[0].id,site_name:matches[0].name,collection:matches[0].collection,
    collection_name:matches[0].collection_name,site_registry_revision:siteRevision};
}
export function recordedActivity(record) {
  return Object.fromEntries(['interaction_kind','site_id','site_name','collection','collection_name','task_id','task_name','task_revision','condition',
    'site_registry_revision','activity_metadata_source'].map(key=>[key,record[key]??null]));
}
export function validateSite(body,site) {
  for(const field of ['site_id','collection'])
    insist(body[field]===undefined||body[field]===site[field],'Site metadata differs from the server registry');
}
