"""Additive approved capsule projection; raw null-authority files stay immutable."""
from copy import deepcopy
from pathlib import Path
import json

from .adapter import digest
from .catalog_cart_authority import AuthorityError, file_hash
from .catalog_cart_execution import save_new
from .simulated_order_authority_v1 import OrderCommitAuthority, NATIVE_AUTHORITY
from .simulated_order_capture import OrderCapture

VERSION = 'website-generated-order-projection-v1'


def _null_authority_interval(raw):
    """Locate the top-level null token without rewriting any other JSON bytes."""
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()
    def whitespace(position):
        while position < len(text) and text[position] in ' \t\r\n': position += 1
        return position
    position = whitespace(0)
    if text[position:position+1] != '{': raise AuthorityError('Raw capsule is not a JSON object')
    position += 1; seen = set(); interval = None
    while True:
        position = whitespace(position)
        if text[position:position+1] == '}':
            position = whitespace(position+1)
            if position != len(text): raise AuthorityError('Trailing raw capsule bytes')
            break
        key, position = decoder.raw_decode(text, position)
        if type(key) is not str or key in seen: raise AuthorityError('Ambiguous raw capsule key')
        seen.add(key);position = whitespace(position)
        if text[position:position+1] != ':': raise AuthorityError('Malformed raw capsule field')
        start = whitespace(position+1)
        value, end = decoder.raw_decode(text, start)
        if key == 'effect_journal':
            if value is not None or text[start:end] != 'null': raise AuthorityError('Raw authority must be null')
            interval = (len(text[:start].encode('utf-8')), len(text[:end].encode('utf-8')))
        position = whitespace(end)
        if text[position:position+1] == ',':position += 1;continue
        if text[position:position+1] != '}':raise AuthorityError('Malformed raw capsule separator')
    if interval is None: raise AuthorityError('Missing raw capsule authority field')
    return interval


def project_capsule(authority, *, raw_path, output):
    """Require this actual sealed authority, not a supplied proof dictionary.

    No approval produces no projection. A foreign/missing acceptance remains
    inconclusive; callers must not substitute an old empty-journal approval.
    """
    if type(authority) is not OrderCommitAuthority or not authority.sealed or authority.receipt is None:
        raise AuthorityError('Projection requires the actual sealed authority instance')
    OrderCommitAuthority._assert_helper(authority)
    authority._check_files()
    if authority.receipt_sha256 != digest(authority.receipt) or authority._surface() != authority.initial:
        raise AuthorityError('Actual sealed authority receipt/source bindings changed')
    proof = authority.receipt
    raw_path, output = Path(raw_path).resolve(), Path(output).resolve()
    descriptor = proof['raw_capsule']
    if descriptor != {'path': str(raw_path), 'sha256': file_hash(raw_path)}:
        raise AuthorityError('Projection raw capsule differs from its actual authority receipt')
    original_bytes = raw_path.read_bytes()
    raw = json.loads(original_bytes)
    if raw['effect_journal'] is not None:
        raise AuthorityError('Preserve the original null-authority capsule')
    envelope = proof['native_effect_envelope']
    if envelope is None:
        return None
    if (proof['status'] != 'accepted_generated_order_journal' or envelope != {
            'authority': NATIVE_AUTHORITY, 'complete': True, 'events': proof['events']}):
        raise AuthorityError('Missing accepted exact generated-order journal')
    if output == raw_path or not output.is_relative_to(raw_path.parent):
        raise AuthorityError('Write the approved projection separately within the actual trace')
    projected = deepcopy(raw)
    projected['effect_journal'] = deepcopy(envelope)
    inverse = deepcopy(projected); inverse['effect_journal'] = None
    if inverse != raw or digest(inverse) != digest(raw):
        raise AuthorityError('Projection changed fields beyond explicit authority')
    start, end = _null_authority_interval(original_bytes)
    replacement = json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
    projected_bytes = original_bytes[:start] + replacement + original_bytes[end:]
    inverse_bytes = projected_bytes[:start] + b'null' + projected_bytes[start+len(replacement):]
    if inverse_bytes != original_bytes or json.loads(projected_bytes) != projected:
        raise AuthorityError('Approved authority does not have a byte-exact raw inverse')
    with output.open('xb') as stream: stream.write(projected_bytes)
    # Preserve original file bytes, not only its parsed JSON representation.
    if file_hash(raw_path) != descriptor['sha256']:
        raise AuthorityError('Projection modified original capsule bytes')
    save_new(output.with_suffix('.binding.json'), {
        'schema': VERSION, 'raw_capsule': deepcopy(descriptor),
        'approved_capsule': {'path': str(output), 'sha256': file_hash(output)},
        'independent_acceptance': deepcopy(proof['independent_acceptance']),
        'permitted_delta': ['effect_journal'], 'semantic_inverse_sha256': digest(inverse),
        'raw_bytes_preserved': True, 'byte_inverse_sha256': file_hash(raw_path),
        'authority_utf8_byte_interval': [start, start+len(replacement)],
    })
    return projected


def forbidden_order_effects(authority):
    """Separate non-order diagnostic; never borrows the historical empty proof.

    A task-specific native grader must adopt this boundary before dispatch.
    Returning None means coverage is inconclusive, not that no orders occurred.
    """
    if type(authority) is not OrderCommitAuthority or authority.receipt is None or not authority.sealed:
        raise AuthorityError('Require actual order-capable authority for forbidden-effect checks')
    OrderCommitAuthority._assert_helper(authority)
    authority._check_files()
    if authority.receipt_sha256 != digest(authority.receipt) or authority._surface() != authority.initial:
        raise AuthorityError('Actual sealed authority receipt/source bindings changed')
    proof = authority.receipt
    if proof['native_effect_envelope'] is None:
        return None
    events = deepcopy(proof['events'])
    return {'authority': NATIVE_AUTHORITY, 'complete': True, 'events': events,
            'forbidden_order_commits': events, 'verdict': 'fail' if events else 'pass'}


class AuthorityOrderCapture(OrderCapture):
    """Prospective wrapper for the reviewed ordinary setup/capture lifecycle.

    Construction must occur before attaching grading/provider dispatch, with
    the actual reviewed runner's cleanup state. Installation into execution is
    a separate write-window/runtime acceptance, not enabled by importing this.
    """
    def __init__(self, runtime, task, *, source_files, retained_sources, inputs,
                 cleanup_state, approval=None):
        super().__init__(runtime, task, source_files=source_files)
        self.authority = OrderCommitAuthority(runtime, self, retained_sources=retained_sources,
                                              inputs=inputs, cleanup_state=cleanup_state)
        self.approval = deepcopy(approval)

    def before(self, env, trace):
        result = super().before(env, trace)
        self.authority.checkpoint('before_policy', trace)
        return result

    def after(self, env, trace, outcome):
        result = super().after(env, trace, outcome)
        self.authority.checkpoint('after_policy_before_context_close', trace)
        return result

    def seal(self, returned_trace, summary):
        raw, completed = super().seal(returned_trace, summary)
        proof = self.authority.seal(returned_trace, summary, raw, approval=self.approval)
        path = Path(returned_trace).resolve()
        save_new(path/'order-authority-candidate.private.json', proof)
        projected = project_capsule(self.authority, raw_path=path/'order-capsule.private.json',
                                    output=path/'order-capsule-approved.private.json')
        return (raw if projected is None else projected), completed
