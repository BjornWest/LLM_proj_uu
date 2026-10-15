"""Declared customer-experience passage lookup; instance prose belongs to its author."""
from copy import deepcopy

from .adapter import digest
from . import catalog_review_task as reviews
from experiments import source_binding

VERSION = 'website-review-passage-task-v1'
KIND = 'find_customer_review_passage'


def resolve(spec, *, inventory, concept_ids):
    allowed = {'kind', 'concept_id', 'product_index', 'topic', 'polarity', 'public_request'}
    if (type(spec) is not dict or set(spec) - allowed
            or not {'kind', 'concept_id', 'topic', 'public_request'} <= set(spec)
            or spec['kind'] != KIND or type(spec['public_request']) is not str
            or not spec['public_request'].strip()
            or spec.get('polarity') not in (None, 'positive', 'negative', 'neutral', 'mixed')):
        raise ValueError('Declare a topic and authored request for one customer-review passage')
    parent = reviews.resolve({'kind': reviews.KIND, 'concept_id': spec['concept_id'],
        'subject_scope': 'product', 'operation': 'topic_counts', 'topic': spec['topic'],
        'product_index': spec.get('product_index', 0)}, inventory=inventory, concept_ids=concept_ids)
    return {'kind': KIND, 'concept_id': parent['concept_id'], 'product_index': parent['product_index'],
            'topic': deepcopy(parent['topic']), 'polarity': spec.get('polarity'),
            'public_request': spec['public_request']}


def make(world, spec, *, inventory):
    selection = resolve(spec, inventory=inventory, concept_ids=world['config']['concept_ids'])
    parent = reviews.make(world, {'kind': reviews.KIND, 'concept_id': selection['concept_id'],
        'operation': 'topic_counts', 'subject_scope': 'product',
        'product_index': selection['product_index'], 'topic': selection['topic']}, inventory=inventory)
    task = {'schema_version': VERSION, 'kind': KIND, 'spec': selection,
        'world_id': world['world_id'], 'world_sha256': digest(world),
        'subject': deepcopy(parent['subject']), 'native_review_task': parent,
        'user_message': selection['public_request'], 'memories': [],
        'required_obligations': [{'role_id': 'customer_review_passage',
            'product_id': parent['subject']['product_id'], 'topic': deepcopy(selection['topic']),
            'polarity': selection['polarity'], 'grain': 'rendered_first_hand_customer_statement',
            'source_family': 'product_reviews'}],
        'public_request_suitability': 'Requires author/Product review against topic, quotation and link intent before readiness'}
    task['task_id'] = 'review-passage-' + digest(task)[:24]
    return task


def reference(world, task, *, inventory):
    if not source_binding.compatible(task, make(world, task['spec'], inventory=inventory)):
        raise ValueError('Review passage task/source/subject/request binding changed')
    parent = reviews.reference(world, task['native_review_task'], inventory=inventory)
    product = next(p for p in world['products'] if p['public']['product_id'] == task['subject']['product_id'])
    records = []
    for row in reviews._canonical(product):
        if not row['text'].strip():
            continue
        statements = row.get('statements', row.get('evidence', {}).get('statements', []))
        # The unchanged parent reference has checked rendered indices, text and
        # canonical subjects. Unrendered private statements earn no credit.
        for segment in row['presentation']['segments']:
            index = segment['statement_index']; s = statements[index]
            meaning = s.get('meaning')
            if inventory.legacy:
                aspect, context, polarity = meaning, s.get('context'), s.get('polarity')
                first_hand = type(context) is dict and context.get('source') == 'first_hand'
            else:
                if type(meaning) is not dict:
                    continue
                aspect, context, polarity = meaning.get('aspect'), meaning.get('context'), meaning.get('polarity')
                first_hand = meaning.get('kind') == 'customer_experience' and meaning.get('source') == 'first_hand'
            topic = task['spec']['topic']
            if (not first_hand or aspect != topic['aspect']
                    or not reviews.context_matches(context, topic['context'])
                    or polarity not in reviews.COUNTS[:-1]
                    or task['spec']['polarity'] is not None and polarity != task['spec']['polarity']):
                continue
            text = s.get('text')
            if type(text) is not str or not text.strip() or text not in row['text']:
                raise ValueError('Eligible statement lacks its literal published text')
            records.append({'review_id': row['review_id'], 'sku_id': row['sku_id'],
                'statement_index': index, 'text': text, 'polarity': polarity,
                'aspect': aspect, 'context': deepcopy(context)})
    return {'schema_version': VERSION, 'task_id': task['task_id'], 'world_sha256': task['world_sha256'],
        'subject': deepcopy(task['subject']), 'status': 'passage' if records else 'no_matching_passage',
        'matching_statements': records, 'native_review_reference': parent,
        'scope': 'One literal rendered first-hand passage and its actual reader-note link; no counts, paraphrase assessment or observed reading inferred'}
