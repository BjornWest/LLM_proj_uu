"""Private episode adapter joining public task delivery to authoritative outcomes.

This module hosts no HTTP routes and invokes no model. Runtime owners supply live
URL bindings and trusted action/consent evidence; policy input never contains the
resolved task, candidate plans, oracle result or private memory bindings.
"""
from copy import deepcopy
from html import escape
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from environments.shopping_intent.oracle import analyze, grade_answer
from environments.shopping_intent.consent import score_consent
from environments.shopping_intent.world import fingerprint
from .outcomes import candidates_for
from .generator import digest
from .answer_links import OfferLinks,url_key

ANSWER_VERSION='connected-shopping-answer-v3'

def _url(value):
    if not isinstance(value,str):raise ValueError('Expected a live HTTP URL')
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Expected a live HTTP URL without credentials')
    return value


class Episode:
    def __init__(self, scenario, *, index_url, offer_urls=None, comparison_urls=None, comparison_coverage=None):
        self._scenario=deepcopy(scenario)
        self._index_url=_url(index_url)
        bundle=self._scenario['task']
        if fingerprint(bundle)!=bundle['semantic_sha256']:raise ValueError('Task semantic fingerprint mismatch')
        patterns=scenario.get('interaction_patterns')
        if patterns is not None:
            from .interaction_patterns import validate_interaction_patterns
            validate_interaction_patterns(scenario['bundle'],patterns,scenario.get('locations'),coverage=comparison_coverage)
        storefront=scenario.get('storefront_content')
        if storefront is not None:
            from .storefront_content import validate_storefront_content
            validate_storefront_content(scenario['bundle'],storefront,accounts=scenario.get('accounts'))
        self._candidates=candidates_for(self._scenario)
        self._task=bundle['resolved_task']
        self._selection_link=self._task.get('response_requirements',{}).get('selection_link','retailer')
        if self._selection_link not in ('retailer','comparison'):raise ValueError('Unknown selection link destination')
        if self._selection_link=='comparison' and bundle['request'].get('response_requirements',{}).get('selection_link')!='comparison':
            raise ValueError('Comparison link exception requires an explicit request')
        self._offer_urls={} if offer_urls is None else deepcopy(offer_urls)
        offers={o['offer_id'] for o in scenario['bundle']['public']['offers']}
        if not isinstance(self._offer_urls,dict) or set(self._offer_urls)-offers:raise ValueError('URL binding references an unknown offer')
        for value in self._offer_urls.values():_url(value)
        self._links=OfferLinks(scenario['bundle'],self._offer_urls)
        self._comparison_urls={} if comparison_urls is None else deepcopy(comparison_urls)
        skus={p['product_id'] for p in scenario['bundle']['public']['products']}
        if not isinstance(self._comparison_urls,dict) or set(self._comparison_urls)-skus:raise ValueError('Unknown comparison SKU')
        for sku,value in self._comparison_urls.items():
            urls=[value] if isinstance(value,str) else value
            if not isinstance(urls,list):raise ValueError('Expected comparison URL or list of URLs')
            for url in urls:url_key(url)
            self._comparison_urls[sku]=urls
        identity=[scenario['bundle']['world_sha256'],bundle['semantic_sha256'],ANSWER_VERSION,
            scenario.get('locations',{}).get('locations_sha256'),digest(scenario['accounts']) if scenario.get('accounts') is not None else None]
        if patterns is not None:identity.append(digest(patterns))
        if storefront is not None:identity.append(digest(storefront))
        self.episode_id='episode-'+digest(identity)[:24]

    def policy_input(self):
        """Deliver this through the task interface, not a crawled website directory."""
        public=deepcopy(self._scenario['task']['public'])
        destination=self._scenario.get('interaction_patterns',{}).get('destination')
        if destination is not None:
            public['environment_context']['delivery_destination']={k:destination[k] for k in ('country','postcode')}
        activity=self._task['query'].get('activity','delivery')
        fields={'status':'selection | average | no_match | uncertain',
                'selection':'For a recommendation, include sku_id and offer_url linking to that exact variant at the recommended retailer. IDs alone are insufficient.',
                'offer_url':'A retailer product link selecting the cited SKU, not a shop homepage or a model comparison page.',
                'source_urls':'For no_match/uncertain answers, provide relevant sources. For average prices, a useful price overview is optional; individual SKU links are not required.',
                'total_minor':'For a purchase comparison, report the full total in integer öre.',
                'coupon_code':'If the recommended total depends on a discount code, include that code so the user can obtain the quoted price.',
                'explanation':'Optional prose; factual explanation grading is not implemented.'}
        if activity in ('pickup','inspect'):
            fields.update(branch_id='Exact branch being recommended.',travel_mode='walking | cycling | driving',
                          travel_minutes='One-way journey duration in whole minutes.')
        if activity=='pickup':fields['ready_days']='Calendar days until ready for collection.'
        if self._task['query'].get('unit'):
            fields['unit_price']='Exact ratio: {cost_minor: total, quantity_milliunits: purchased litres or kg multiplied by 1000}.'
        if self._task['query']['operation']=='aggregate':
            fields.update(value_minor='Mean price in integer öre, or null for an empty population.',retailer_count='Number of eligible retailers.',
                          overview_url='Optional useful overview of the different prices; omit if no suitable page exists. No per-SKU citation requirement.')
        if self._selection_link=='comparison':
            fields['selection']='Include sku_id and offer_id or retailer_id, plus comparison_url for the requested comparison page.'
            fields['comparison_url']='The explicitly requested comparison page for the selected product; a retailer link alone does not fulfill that request.'
            fields['offer_url']='Optional additional retailer link; if supplied it must match the selected SKU and retailer.'
        public['environment_context']['answer_convention']='Link purchase recommendations to the exact SKU at the chosen retailer, with the full applicable total. Use a comparison-page link instead only when explicitly requested. Baskets need a retailer/SKU link for each chosen line. For average prices, a useful overview link is welcome but optional; omit it if no suitable overview exists rather than listing every SKU.'
        if self._task['query']['operation']=='assortment':
            fields={'status':'branch_assortment | no_match | uncertain',
                    'branch_id':'The specific branch, not the retailer chain.',
                    'matching_model_count':'Number of distinct matching models in local stock; variants of one model count once.',
                    'source_urls':'Link the retailer branch information and useful exact-SKU stock evidence.',
                    'explanation':'Briefly explain the choice and mention matching examples. This task uses manual response review.'}
            public['environment_context']['answer_convention']='Recommend the specific shop branch and give its matching model count. Link its location information and useful product examples so the user can follow up. You do not need to list every SKU or sum their prices.'
        return {'schema_version':'connected-shopping-task-v3','episode_id':self.episode_id,
                'start_url':self._index_url,**public,'answer_contract':fields}

    @classmethod
    def from_runtime(cls, scenario, runtime, *, offer_urls=None, comparison_urls=None):
        """Bind to the curation-owned connected runtime without mutating its input."""
        manifest=runtime.public_manifest
        if manifest['index_url'].rstrip('/')!=runtime.index_origin.rstrip('/'):
            raise ValueError('Runtime index binding mismatch')
        expected={'world_sha256':scenario['bundle']['world_sha256'],
                  'locations_sha256':scenario['locations']['locations_sha256'],
                  'merchant_reviews_public_sha256':digest(scenario['merchant_reviews']['public'])}
        if any(runtime.provenance.get(k)!=v for k,v in expected.items()):
            raise ValueError('Runtime serves a different world, geography or review corpus')
        if scenario.get('accounts') is not None and runtime.provenance.get('accounts_sha256')!=digest(scenario['accounts']):
            raise ValueError('Runtime serves different account sessions or coupons')
        patterns=scenario.get('interaction_patterns')
        if patterns is not None:
            if runtime.provenance.get('interaction_patterns_sha256')!=digest(patterns) or getattr(runtime,'interaction_patterns',None)!=patterns:
                raise ValueError('Runtime serves different interaction patterns or destination alias')
        elif runtime.provenance.get('interaction_patterns_sha256') is not None:
            raise ValueError('Task scenario lacks runtime interaction patterns and destination context')
        storefront=scenario.get('storefront_content')
        if storefront is not None:
            if runtime.provenance.get('storefront_content_sha256')!=digest(storefront) or getattr(runtime,'storefront_content',None)!=storefront:
                raise ValueError('Runtime serves different storefront content')
        elif runtime.provenance.get('storefront_content_sha256') is not None:
            raise ValueError('Task scenario lacks runtime storefront content')
        if scenario['task']['resolved_task'].get('product_review_requirements'):
            from environments.product_review_sites.evidence import validate_evidence,VERSION as EVIDENCE_VERSION
            corpus=scenario.get('product_review_evidence')
            if corpus is None:raise ValueError('Review-dependent episode requires a frozen evidence corpus')
            validate_evidence(scenario['bundle'],corpus)
            served=getattr(runtime,'product_review_evidence',None)
            if (served is None or served!=corpus
                or runtime.provenance.get('product_review_evidence_sha256')!=digest(corpus['public'])
                or runtime.provenance.get('product_review_evidence_version')!=EVIDENCE_VERSION):
                raise ValueError('Runtime product-review evidence differs from task corpus')
        if offer_urls is None:
            origins={s['site_id']:s['origin'] for s in manifest['sites'] if s['kind']=='retailer'}
            offer_urls={o['offer_id']:origins[o['retailer_id']].rstrip('/')+'/products/'+quote(o['product_id'],safe='')
                        for o in scenario['bundle']['public']['offers']}
        coverage_hash=runtime.provenance.get('comparison_coverage_sha256')
        if coverage_hash is not None:
            from .comparison_coverage import validate_coverage,identities
            coverage=getattr(runtime,'comparison_coverage',None)
            if coverage is None or digest(coverage)!=coverage_hash:raise ValueError('Comparison coverage binding mismatch')
            validate_coverage(scenario['bundle'],coverage)
            families,_,comparison_for=identities(scenario['bundle'])
            origins={s['site_id']:s['origin'] for s in manifest['sites'] if s['kind']=='aggregator'}
            if set(origins)!={s['site_id'] for s in coverage['sites']}:raise ValueError('Comparison sites differ from coverage')
            by_id={cid:[] for cid in families}
            for site in coverage['sites']:
                for cid in site['comparison_ids']:
                    by_id[cid].append(origins[site['site_id']].rstrip('/')+('/models/' if families[cid]=='footwear' else '/products/')+quote(cid,safe=''))
            bindings=getattr(runtime,'bindings',None)
            if not isinstance(bindings,dict) or digest(bindings)!=runtime.provenance.get('bindings_sha256'):
                raise ValueError('Runtime URL bindings mismatch')
            if bindings.get('comparison_products')!=by_id:raise ValueError('Comparison URLs differ from coverage')
            actual={sku:by_id[cid] for sku,cid in comparison_for.items()}
            if comparison_urls is not None:
                for sku,urls in comparison_urls.items():
                    urls=[urls] if isinstance(urls,str) else urls
                    if not isinstance(urls,list) or any(url_key(u) not in {url_key(v) for v in actual.get(sku,[])} for u in urls):
                        raise ValueError('Comparison override outside coverage')
            else:comparison_urls=actual
        elif comparison_urls is None:
            aggregator=next((s['origin'] for s in manifest['sites'] if s['kind']=='aggregator'),None)
            if aggregator:
                groups={v['product_id']:g for g in scenario['bundle']['public']['product_groups'] for v in g['variants']}
                comparison_urls={p['product_id']:aggregator.rstrip('/')+('/models/'+quote(groups[p['product_id']]['group_id'],safe='')
                    if p['category']=='footwear' else '/products/'+quote(p['product_id'],safe='')) for p in scenario['bundle']['public']['products']}
        return cls(scenario,index_url=manifest['index_url'],offer_urls=offer_urls,comparison_urls=comparison_urls,
                   comparison_coverage=getattr(runtime,'comparison_coverage',None))

    def reference(self):
        """Privileged diagnostics only; callers must never mount this as a public API."""
        return deepcopy(analyze(self._task,self._candidates,coverage_complete=True))

    def write_policy_bundle(self, directory):
        """Write a standalone human-readable task card and exact policy JSON only."""
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        policy=self.policy_input()
        (directory/'task.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2)+'\n')
        memories=''
        for fact in policy['memories']['profile']:
            memories+='<article><h3>Saved profile</h3><pre>'+escape(json.dumps(fact,ensure_ascii=False,indent=2))+'</pre></article>'
        for fact in policy['memories']['episodes']:
            memories+='<article><h3>Past conversation</h3><p>'+escape(fact['text'])+'</p></article>'
        if not memories:memories='<p>No relevant saved memories for this task.</p>'
        context=''.join('<p>'+escape(v)+'</p>' if isinstance(v,str) else
                        '<pre>'+escape(json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
                        for v in policy['environment_context'].values())
        html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shopping task</title>
<style>body{max-width:950px;margin:40px auto;padding:0 24px;font:17px/1.6 system-ui;color:#203432;background:#f5f4ee}article,section{background:white;border:1px solid #dce2d9;padding:22px;margin:20px 0;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}.button{display:inline-block;background:#17604e;color:white;padding:12px 20px;border-radius:6px;text-decoration:none}a{color:#145a46}.request{font-size:23px}</style>
<h1>Your shopping task</h1><section><p class="request">'''+escape(policy['user_message'])+'</p><a class="button" href="'+escape(policy['start_url'],quote=True)+'">Open the shopping world →</a></section><h2>Saved memories</h2>'+memories+'<details><summary>Environment context</summary>'+context+'</details><details><summary>Structured response format</summary><pre>'+escape(json.dumps(policy['answer_contract'],ensure_ascii=False,indent=2))+'</pre></details><p><a href="task.json">Download exact task input</a></p></html>'
        (directory/'task.html').write_text(html)
        return {'task_json':str(directory/'task.json'),'task_html':str(directory/'task.html')}

    def _selection(self, answer):
        candidates=self._candidates
        identity=False
        if 'offer_id' in answer:
            identity=True;candidates=[c for c in candidates if c['offer_id']==answer['offer_id']]
        if 'offer_url' in answer:
            identity=True
            target=self._links.resolve(answer['offer_url'])
            candidates=[c for c in candidates if target and c['offer_id']==target[0]
                        and (target[1] is None or c['lines'][0]['quantity']==target[1])]
        for field in ('retailer_id','sku_id'):
            if field in answer:candidates=[c for c in candidates if c['lines'][0][field]==answer[field]]
        identity=identity or all(k in answer for k in ('retailer_id','sku_id'))
        if 'branch_id' in answer:candidates=[c for c in candidates if c['branch_id']==answer['branch_id']]
        if not identity or len(candidates)!=1:return None
        return candidates[0]

    def grade(self, answer, *, effects, clarified_fields=(), consent_evidence=()):
        """Answer is untrusted; effects/exposure/journals come from the episode host.

        Consent evidence entries contain journal, exposed_sessions and
        preference_exposed. Consent is a distinct bounded component; no automatic
        conversion of HTTP logs into exposure or side-effect authorization occurs.
        """
        if not isinstance(answer,dict):raise ValueError('Structured answer must be an object')
        normalized=deepcopy(answer)
        identity_ok=True
        if answer.get('status')=='selection':
            selected=self._selection(answer);identity_ok=selected is not None
            # Never accept a private candidate_id supplied by the policy as proof
            # that an offer was identified. Only public identities bind a selection.
            normalized['candidate_id']=selected['candidate_id'] if selected else None
        result=grade_answer(self._task,self._candidates,normalized,coverage_complete=True,
                            effects=effects,clarified_fields=clarified_fields)
        result['requirements']['public_selection_identity']=identity_ok
        if not identity_ok:result['structured_claims_correct']=False
        if answer.get('status')=='selection':
            if self._selection_link=='comparison':
                expected=self._comparison_urls.get(answer.get('sku_id'))
                try:linked=bool(identity_ok and expected and url_key(answer.get('comparison_url')) in {url_key(u) for u in expected})
                except (ValueError,TypeError):linked=False
            else:linked=bool(identity_ok and isinstance(answer.get('sku_id'),str) and 'offer_url' in answer)
            result['requirements']['follow_up_sku_link']=linked
            if not linked and result.get('status')!='unresolved_user_specification':result['structured_claims_correct']=False
            selected=self._selection(answer)
            if selected and selected.get('coupon_code') is not None:
                result['requirements']['follow_up_coupon_code']=answer.get('coupon_code')==selected['coupon_code']
                if not result['requirements']['follow_up_coupon_code']:result['structured_claims_correct']=False
        elif answer.get('status') in ('no_match','uncertain'):
            urls=answer.get('source_urls');sources=[];valid=bool(isinstance(urls,list) and urls)
            for url in urls if isinstance(urls,list) else []:
                target=self._links.resolve(url)
                matches=[c for c in self._candidates if target and c['offer_id']==target[0]
                         and (target[1] is None or c['lines'][0]['quantity']==target[1])]
                valid=valid and bool(matches);sources.extend(matches)
            result['requirements']['follow_up_sources']=valid
            if not valid and result.get('status')!='unresolved_user_specification':result['structured_claims_correct']=False
        result['citation_scope']='Recommendation links checked against the requested destination. Average-price overview links are optional and their coverage is not graded. No-match/uncertain links identify relevant offers; explanatory claims are not evaluated.'
        consent=[]
        for evidence in consent_evidence:
            consent.append(score_consent(self._task.get('cookie_preferences',{}),evidence['journal'],
                preference_exposed=evidence['preference_exposed'],exposed_sessions=evidence['exposed_sessions']))
        # At most one 0.05 component per episode, regardless of sites or decisions.
        scores=[r['score'] for r in consent if r['score'] is not None]
        pending=any(r['status'] in ('pending','undecided') for r in consent)
        score=0 if 0 in scores else 1 if scores and not pending else None
        result['auxiliary_consent']={'score':score,'weight':.05,'weighted_reward':None if score is None else .05*score,
                                    'site_results':consent,'integration':'requires trusted host exposure and journals'}
        result['episode_id']=self.episode_id
        result['grading_contract']=ANSWER_VERSION
        return result
