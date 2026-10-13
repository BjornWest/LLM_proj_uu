"""Read-only address grade projection, preserving existing answer/cart viewers.

The registry explicitly pins saved task, capture and native grade artifacts.
This module displays those outputs; it never executes a grader or model.
"""
import hashlib
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from environments.website_world.adapter import digest
from scripts import trace_hub as base, trace_grades as legacy
from scripts import cart_state_trace_hub as cart_hub, cart_state_trace_grades as cart
from scripts import simulated_order_address_trace_grades as order_address

SCOPE = 'captured_address_state'


def read_grade(directory, entry):
    directory = Path(directory).resolve()
    try:
        for name, pin in entry['files'].items():
            path = Path(pin['path'])
            if cart.descriptor(path) != pin:
                raise ValueError('Saved address evidence changed: '+name)
        read = lambda name: cart.checked_json(entry['files'][name])
        grade, capsule, provenance, task = map(read, ('grade', 'capsule', 'provenance', 'task'))
        trace_hash = entry['files']['steps']['sha256']
        if (grade['schema_version'] != 'website-atomic-address-grade-v1'
                or capsule['episode_id'] != directory.name
                or capsule['main_trace_sha256'] != trace_hash
                or provenance['main_trace_sha256'] != trace_hash
                or capsule['task_sha256'] != digest(task)
                or grade['task_id'] != task['task_id']
                or read('policy_task')['task_id'] != task['task_id']):
            raise ValueError('Address task/trace identity differs')
        for name, phase in (('before', 'before_policy'), ('after', 'after_policy_before_context_close')):
            raw = read(name)
            if (raw != capsule[name] or raw['phase'] != phase
                    or provenance['captures'][name] != entry['files'][name]):
                raise ValueError('Address capture provenance differs')
        authority, approval = read('authority'), read('approval')
        if (authority['status'] != 'accepted_empty_set_proof'
                or authority['episode_id'] != directory.name
                or authority['main_trace_sha256'] != trace_hash
                or authority['captures'] != provenance['captures']
                or authority['failures'] != []
                or authority['native_effect_envelope'] != capsule['effect_journal']
                or authority['independent_acceptance'] != entry['files']['approval']
                or approval['status'] != 'accepted'
                or approval['source_sha256'] != authority['surface']['source_sha256']
                or approval['stdlib_source_sha256'] != authority['surface']['stdlib_source_sha256']):
            raise ValueError('Saved address authority binding differs')
        checks = {name: cart.boolean_status(component) for name, component in grade['components'].items()}
        verdict = cart.boolean_status({'status': grade['verdict']})
        if verdict is True and any(value is not True for value in checks.values()):
            raise ValueError('Passing native grade contradicts component results')
        if checks.get('policy_completion') is True and provenance['policy_completed'] is not True:
            raise ValueError('Native completion contradicts actual capture')
        rid = task['retailer_id']
        def state(phase):
            values = [json.loads(row['value']) for origin in capsule[phase]['storage_state']['origins']
                      for row in origin['localStorage'] if row['name'] == 'website-drafts.state.'+rid]
            if len(values) != 1:
                raise ValueError('Expected exactly one target retailer storage state')
            return values[0]
        before, after = state('before'), state('after')
        details = {
            'saved_address': {'expected': task['expected_address'], 'supplied': after['address'],
                              'explanation': 'Complete saved address identity, including optional apartment/unit. Country is implicit in this checkout.'},
            'remembered_address': {'expected': task['expected_address'], 'supplied': after['remembered'],
                                   'explanation': 'Locally remembered address after saving.'},
            'saved_valid_form': {'expected': 'valid', 'supplied': after.get('addressStatus'),
                                 'explanation': 'Checkout acknowledged a valid saved address.'},
            'preserved_state': {'expected': 'Cart, coupons, orders and protected address/instruction state unchanged.',
                                'supplied': grade['components'].get('preserved_state'),
                                'explanation': 'Native checks cover every retailer, preserving the cart and avoiding order placement.'},
            'forbidden_effects': {'expected': 'No generated commit effects.', 'supplied': capsule['effect_journal'],
                                  'explanation': 'Independently accepted scoped empty-set proof. Broader external effects are not certified.'},
            'policy_completion': {'expected': True, 'supplied': provenance['policy_completed'],
                                   'explanation': 'The policy finished; process completion alone is insufficient.'},
        }
        for field, value in grade['components'].get('saved_address', {}).get('checks', {}).items():
            key = 'address_'+field
            checks[key] = value
            expected = task['expected_address']
            pairs = {
                'recipient': (expected['recipient'], after['address'].get('name')),
                'building': (expected['street']+' '+expected['house_number'], after['address'].get('street')),
                'unit': (expected['unit'], after['address'].get('unit')),
                'postcode': (expected['postcode'], after['address'].get('postcode')),
                'city': (expected['city'], after['address'].get('city')),
                'country': (expected['country'], after['address'].get('country', task['implicit_country'])),
            }
            want, got = pairs[field]
            details[key] = {'expected': want, 'supplied': got, 'explanation': 'Saved native address-field comparison; display does not rerun grading.'}
        return dict(binding_status='verified', structured_claims_correct=verdict,
                    grading_scope=SCOPE, grading_version=grade['schema_version'],
                    native_verdict=grade['verdict'], requirements=checks, additional_checks={},
                    check_details=details, safe_success=None, full_response_evaluated=False,
                    claims={'task_id': task['task_id'], 'components': grade['components']},
                    oracle_answer={'expected_address': task['expected_address'], 'initial_address': before['address']},
                    derivations=[], source_artifact_sha256={p['path']:p['sha256'] for p in entry['files'].values()},
                    episode_artifact_sha256={}, extractor={'model':'not used','provider':'not used','version':'saved-address-state-view-v1'},
                    limitations=grade['limitations']+['Saved native output only; no model call or regrading. Broader external effects and response quality remain unclaimed.'],
                    artifact_filename='atomic-address-grade.private.json')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(binding_status='invalid', error=str(exc), grading_scope=SCOPE, structured_claims_correct=None)


class AddressStateHub(cart_hub.CartStateHub):
    def __init__(self, registry, *args, **kwargs):
        super().__init__(registry, *args, **kwargs)
        self.suites = cart_hub.StateSuiteCatalog(self.registry, grade_reader=self.suite_grade)
        self.addresses = json.loads(Path(registry).read_text()).get('address_grades', {})
        self.version = hashlib.sha256((self.version+Path(__file__).read_text()+json.dumps(self.addresses, sort_keys=True)).encode()).hexdigest()

    def suite_grade(self, directory):
        try:
            grade = self.address_grade(directory)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return {'binding_status': 'invalid', 'grading_scope': SCOPE,
                    'structured_claims_correct': None, 'error': 'Address grade unavailable: ' + str(exc)}
        return grade if grade is not None else cart.read_grade(directory)

    def address_grade(self, directory):
        # New episode grades are registered after native grading; never cache
        # the registry mapping for the lifetime of the shared viewer server.
        data = json.loads(self.registry.read_text())
        key = str(Path(directory).resolve())
        entry = data.get('order_address_grades', {}).get(key)
        if entry is not None:
            return order_address.read_grade(directory, entry)
        entry = data.get('address_grades', {}).get(key)
        if entry is not None:
            return read_grade(directory, entry)
        directory = Path(directory).resolve()
        failure = directory / 'grading-system-failure.json'
        if failure.is_file():
            record = json.loads(failure.read_text())
            return {'binding_status': 'invalid', 'grading_scope': SCOPE,
                    'structured_claims_correct': None, 'artifact_filename': failure.name,
                    'error': 'System failure: automatic grading unavailable because browser setup failed. ' + record.get('cause', '')}
        if (directory / 'atomic-address-grade.private.json').is_file():
            return {'binding_status': 'invalid', 'grading_scope': SCOPE,
                    'structured_claims_correct': None,
                    'error': 'System failure: native address grade has no viewer evidence binding'}
        return None

    def revision(self, directory, key):
        original = super().revision(directory, key)
        grade = self.address_grade(directory)
        entry = json.loads(self.registry.read_text()).get('address_grades', {}).get(str(Path(directory).resolve()))
        return hashlib.sha256(json.dumps([original, entry, grade], sort_keys=True).encode()).hexdigest() if grade else original

    def project_grade(self, group, directory):
        grade = self.address_grade(directory)
        if grade is None:
            return cart.project_grade(group, directory)
        result = _bind(legacy.project_grade, read_grade=lambda _: grade)(group, directory)
        old = result['evaluation_label']
        label = 'address checks '+('unavailable' if grade['binding_status'] != 'verified' else
                                   'passed' if grade['structured_claims_correct'] is True else
                                   'failed' if grade['structured_claims_correct'] is False else 'inconclusive')
        result['title'] = result['title'].replace(old, label)
        result['evaluation_label'] = label
        for note in result['messages']:
            if note['id'] == result['id']+':derived-answer-grade':
                note['title'] = 'Address state grading — not model input'
        return result

    def load(self, entry):
        return _bind(base.Hub.load, project_grade=self.project_grade)(self, entry)


def viewer_html():
    html = cart_hub.viewer_html().decode()
    html = html.replace("grade?.grading_scope==='captured_cart_state'",
                        "['captured_cart_state','captured_address_state'].includes(grade?.grading_scope)")
    html = html.replace('Saved native cart allocation, policy completion and scoped generated-commit authority.',
                        'Saved native address/cart checks. Each grade states its scoring scope and evidence limits.')
    html = html.replace('Native cart components and bound evidence hashes', 'Native state components and bound evidence hashes')
    return html.encode()


def serve(registry, port):
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('127.0.0.1', port),
        base.make_handler(registry, hub_class=AddressStateHub, html_factory=viewer_html))
    print(f'Trace hub: http://localhost:{server.server_port}/#latest', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
