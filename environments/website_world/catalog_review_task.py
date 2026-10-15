"""Source-bound rating and attributed written-opinion summaries, without new prose."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json

from environments.product_world.product_package import load_document
from environments.product_world.review_population import summarize_ratings
from experiments.accepted_catalog_commerce import package_export
from .adapter import digest
from .feature_offer_task import FieldInventory, ROOT
from experiments import source_binding

VERSION = 'website-catalog-review-task-v1'
KIND = 'summarize_product_reviews'
COUNTS = ('positive','negative','neutral','mixed','not_assessed')


def context_matches(actual, requested):
    if type(actual) is not type(requested): return False
    if type(requested) is dict:
        return all(k in actual and context_matches(actual[k],v) for k,v in requested.items())
    return actual == requested


class ReviewInventory:
    def __init__(self, concept_id):
        self.fields = FieldInventory(concept_id)
        self.concept_id = concept_id
        self.source_hashes = deepcopy(self.fields.source_hashes)
        self.legacy = concept_id in package_export.PILOTS
        if self.legacy:
            path = ROOT/'environments/product_world/data/footwear_context_pilot/statements.json'
            self.source_hashes[str(path.relative_to(ROOT))] = sha256(path.read_bytes()).hexdigest()
            self.topics = [{'aspect':k,'context':deepcopy(v['context'])} for k,v in
                json.loads(path.read_text())['aspects'].items()
                if concept_id.split('.')[1] in v.get('concepts',[concept_id.split('.')[1]])]
        else:
            path = ROOT/'environments/product_world/data/product_width'/(concept_id+'.json')
            language = load_document(path).get('programs',{}).get('review',{}).get('language',[])
            self.topics = []
            for pool in language:
                m = pool.get('meaning',{})
                if m.get('kind') == 'customer_experience' and m.get('source') == 'first_hand':
                    topic = {'aspect':m['aspect'],'context':deepcopy(m['context'])}
                    if topic not in self.topics: self.topics.append(topic)
        self.check_sources()

    def check_sources(self):
        for name,expected in self.source_hashes.items():
            if sha256((ROOT/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Review declaration source changed: '+name)


def resolve(value, *, inventory, concept_ids):
    allowed = {'kind','concept_id','operation','subject_scope','product_index','sku_index','topic','min_assessed'}
    if type(value) is not dict or set(value)-allowed or value.get('kind') != KIND or value.get('concept_id') != inventory.concept_id or inventory.concept_id not in concept_ids:
        raise ValueError('Declare one accepted concept and review summary operation')
    operation = value.get('operation'); scope = value.get('subject_scope','product')
    if operation not in ('rating_summary','topic_counts') or scope not in ('product','sku'):
        raise ValueError('Use rating_summary/topic_counts and product/sku subject scope')
    result = {'kind':KIND,'concept_id':inventory.concept_id,'operation':operation,'subject_scope':scope,
              'product_index':value.get('product_index',0)}
    for field in ('product_index','sku_index'):
        if field == 'sku_index' and scope == 'product':
            if field in value: raise ValueError('Product scope cannot carry a SKU selector')
            continue
        result[field] = value.get(field,0)
        if type(result[field]) is not int or not 0 <= result[field] <= 10000:
            raise ValueError('Selectors are finite nonnegative identity indices, not outcome targets')
    if operation == 'rating_summary':
        if 'topic' in value or 'min_assessed' in value: raise ValueError('Ratings are not topic opinions')
    else:
        topic = value.get('topic')
        if type(topic) is not dict or set(topic) != {'aspect','context'} or type(topic['aspect']) is not str:
            raise ValueError('Declare an aspect and exact or object-subset context')
        json.dumps(topic,allow_nan=False)
        if not any(t['aspect'] == topic['aspect'] and context_matches(t['context'],topic['context']) for t in inventory.topics):
            raise ValueError('Topic/context is not an accepted first-hand declaration')
        result['topic'] = deepcopy(topic)
        result['min_assessed'] = value.get('min_assessed',1)
        if type(result['min_assessed']) is not int or not 1 <= result['min_assessed'] <= 1000:
            raise ValueError('Declare min_assessed1..1000')
    return result


def make(world, value, *, inventory):
    inventory.check_sources()
    spec = resolve(value,inventory=inventory,concept_ids=world['config']['concept_ids'])
    products = sorted((p['public'] for p in world['products'] if p['public']['concept_id'] == spec['concept_id']),key=lambda p:p['product_id'])
    if spec['product_index'] >= len(products): raise ValueError('Generated population has no requested product identity index')
    product = products[spec['product_index']]; subject = {'product_id':product['product_id'],'product_name':product['name']}
    name = product['name']
    if spec['subject_scope'] == 'sku':
        skus = sorted(product['skus'],key=lambda s:s['sku_id'])
        if spec['sku_index'] >= len(skus): raise ValueError('Manufactured menu has no requested SKU identity index')
        sku = skus[spec['sku_index']]
        item = next(p for p in world['products'] if p['public']['product_id'] == product['product_id'])
        subject.update(sku_id=sku['sku_id'],selection={k:deepcopy(sku[k]) for k in item['variant_fields']})
        name += ' in option '+json.dumps(subject['selection'],ensure_ascii=False,sort_keys=True)
    if spec['operation'] == 'rating_summary':
        instruction = ('Report the number of ratings, written comments and ratings without comments, the five star counts, '
            'and the mean star rating rounded to two decimal places (half up). Include ratings without comments. '
            'If there are no ratings, say the mean is undefined, not zero.')
    else:
        topic = spec['topic']
        instruction = ('Count positive (favorable), negative (unfavorable), neutral, mixed and not-assessed written comments '
            'about '+topic['aspect'].replace('_',' ')+' in context '+json.dumps(topic['context'],ensure_ascii=False,sort_keys=True)+'. '
            'Use only explicit first-hand reports in that context; other written comments count as not assessed. '
            'Combine opposite reports within one comment as mixed. Compare positive versus negative comment counts: more positive, '
            'more negative, or tied; say insufficient evidence if fewer than '+str(spec['min_assessed'])+' comments assess the topic. '
            'Neutral and mixed are separate and do not count toward either directional total; this is not a majority of all customers. '
            'Stars and private product properties do not establish a topic opinion.')
    message = ('Summarize the published customer-review corpus for '+name+'. '+instruction+
        ' Use the complete recorded corpus for this '+('model across all options' if spec['subject_scope']=='product' else 'exact option')+
        '; count each canonical review ID once even if the same review is syndicated on multiple sites. '
        'There is no date filter: source comments have no publication dates. Cite an actual review-page link. Do not place an order.')
    task = {**spec,'schema_version':VERSION,'world_id':world['world_id'],'world_sha256':digest(world),
        'subject':subject,'user_message':message,'memories':[],
        'source_sha256':deepcopy(inventory.source_hashes),'topics_are_attributed_opinions':True,
        'corpus_policy':'Complete native syndicated corpus; canonical review IDs once; no invented date coverage.'}
    task['task_id'] = 'review-summary-'+digest(task)[:24]
    return task


def _canonical(item):
    rows = {}; skus = {s['sku_id'] for s in item['public']['skus']}
    for row in item['reviews']:
        if type(row.get('review_id')) is not str or not row['review_id'] or row.get('sku_id') not in skus:
            raise ValueError('Review lacks canonical identity or manufactured subject')
        # Source duplicates do not earn extra votes; conflicting copies are invalid.
        if row['review_id'] in rows and row != rows[row['review_id']]: raise ValueError('Conflicting syndicated review copies')
        rows[row['review_id']] = deepcopy(row)
    return list(rows.values())


def reference(world, task, *, inventory):
    spec = {k:task[k] for k in ('kind','concept_id','operation','subject_scope','product_index','sku_index','topic','min_assessed') if k in task}
    if not source_binding.compatible(task, make(world,spec,inventory=inventory)): raise ValueError('Review task/world/source/prose binding changed')
    item = next(p for p in world['products'] if p['public']['product_id'] == task['subject']['product_id'])
    canonical = _canonical(item)
    if summarize_ratings(canonical) != item['rating_summary']: raise ValueError('Canonical corpus and recorded rating summary disagree')
    rows = [r for r in canonical if task['subject_scope']=='product' or r['sku_id']==task['subject']['sku_id']]
    result = {'schema_version':VERSION,'task_id':task['task_id'],'world_id':world['world_id'],
        'world_sha256':task['world_sha256'],'subject':deepcopy(task['subject']),'operation':task['operation'],
        'canonical_review_ids':sorted(r['review_id'] for r in rows), 'coverage':'complete_native_corpus_not_public_exposure'}
    if task['operation'] == 'rating_summary':
        summary = summarize_ratings(rows)
        mean = (str((Decimal(summary['rating_sum'])/summary['rating_count']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if rows else None)
        result.update(status='summary',summary={**summary,'mean_rounded':mean},rounding='two_decimal_half_up')
        return result
    counts = dict.fromkeys(COUNTS,0); records = []
    for row in rows:
        if not row['text'].strip(): continue  # rating-only reports are outside written-topic denominator
        presentation = row.get('presentation',{})
        if presentation.get('text') != row['text']: raise ValueError('Review text and composition disagree')
        statements = row.get('statements',row.get('evidence',{}).get('statements',[]))
        indices = [s['statement_index'] for s in presentation.get('segments',[])]
        if len(indices) != len(set(indices)) or any(type(i) is not int or not 0 <= i < len(statements) for i in indices):
            raise ValueError('Invalid rendered statement inventory')
        polarities = set()
        for index in indices:
            s = statements[index]; meaning = s.get('meaning')
            if inventory.legacy:
                aspect,context,polarity = meaning,s.get('context'),s.get('polarity')
                first_hand = type(context) is dict and context.get('source') == 'first_hand'
            else:
                if type(meaning) is not dict: continue
                aspect,context,polarity = meaning.get('aspect'),meaning.get('context'),meaning.get('polarity')
                first_hand = meaning.get('kind') == 'customer_experience' and meaning.get('source') == 'first_hand'
            if first_hand and aspect == task['topic']['aspect'] and context_matches(context,task['topic']['context']):
                if s.get('sku_id',row['sku_id']) != row['sku_id'] or polarity not in COUNTS[:-1]:
                    raise ValueError('Matched report has another subject or unknown polarity')
                polarities.add(polarity)
        classification = ('mixed' if 'mixed' in polarities or {'positive','negative'} <= polarities else
            'positive' if 'positive' in polarities else 'negative' if 'negative' in polarities else
            'neutral' if 'neutral' in polarities else 'not_assessed')
        counts[classification] += 1
        records.append({'review_id':row['review_id'],'sku_id':row['sku_id'],'classification':classification})
    assessed = sum(counts[k] for k in COUNTS[:-1])
    verdict = ('insufficient_evidence' if assessed < task['min_assessed'] else
        'more_positive' if counts['positive'] > counts['negative'] else
        'more_negative' if counts['negative'] > counts['positive'] else 'tie')
    result.update(status='summary',counts=counts,written_review_count=sum(counts.values()),assessed_count=assessed,
        verdict=verdict,review_classifications=records,directional_denominator=counts['positive']+counts['negative'])
    return result
