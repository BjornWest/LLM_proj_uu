"""Opt-in trace hub for source-bound cart state views; legacy viewer untouched."""
from hashlib import sha256
import json
from pathlib import Path

from experiments.accepted_catalog_commerce.execution import _bind
from scripts import trace_hub as base, trace_suites
from scripts import cart_state_trace_grades as state


class StateSuiteCatalog(trace_suites.SuiteCatalog):
    def verified_grade(self, trace):
        # State evidence includes nested raw captures and external approvals;
        # the legacy cache's top-level file signature cannot validate these.
        return state.read_grade(trace)

    def detail(self, ident, *, summaries=None, verify=True):
        result = super().detail(ident, summaries=summaries, verify=verify)
        for row, case in zip(result['cases'], self.plans()[ident][1]['cases']):
            trace = trace_suites.safe_trace(case)
            grade = self.verified_grade(trace) if trace else None
            if grade and grade.get('grading_scope') == state.SCOPE:
                row['state_checks'] = row.pop('answer_checks', None)
                if row['verdict_scope'] == 'derived_answer_checks':
                    row['verdict_scope'] = 'derived_captured_cart_state'
        result['grade_scope_note'] += ' Captured cart state is separate from answer checks and broader safety.'
        return result


class CartStateHub(base.Hub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suites = StateSuiteCatalog(self.registry)
        self.version = sha256((self.version+state.VERSION).encode()+Path(__file__).read_bytes()
                             +Path(state.__file__).read_bytes()).hexdigest()

    def revision(self, directory, key):
        original = super().revision(directory, key)
        view = directory/state.legacy.FILENAME
        signature = []
        try:
            payload = json.loads(view.read_text())
            if payload.get('grading_scope') == state.SCOPE:
                # Reading the selected trace's evidence only. Reverify on every
                # selected revision; do not silently trust a cached pass.
                grade = state.read_grade(directory)
                signature = [grade.get('binding_status'), grade.get('error')]
        except (OSError, ValueError, AttributeError):
            pass
        return sha256(json.dumps([original, signature], sort_keys=True).encode()).hexdigest()

    def load(self, entry):
        return _bind(base.Hub.load, project_grade=state.project_grade)(self, entry)


def handler(registry):
    return base.make_handler(registry, hub_class=CartStateHub,
                             html_factory=viewer_html)


def viewer_html():
    """Keep the shared UI, with state-specific text only for the opt-in scope."""
    html = base.viewer_html(preview=True).decode()
    replacements = {
        "const grade=current?.derived_evaluation;":
            "const grade=current?.derived_evaluation;const cartState=grade?.grading_scope==='captured_cart_state';",
        "'Post-run answer checks: '+verdict":
            "(cartState?'Captured-state checks: ':'Post-run answer checks: ')+verdict",
        "'These checks grade the final answer and covered state changes after browsing finishes. They are not model input.'":
            "(cartState?'Saved native cart allocation, policy completion and scoped generated-commit authority. No answer extraction or observed commit journal.':'These checks grade the final answer and covered state changes after browsing finishes. They are not model input.')",
        "'Browser-phase outcome (before answer grading)'":
            "(cartState?'Original browser-phase outcome (preserved)':'Browser-phase outcome (before answer grading)')",
        "'. This earlier record is preserved separately; it does not mean the answer checks above are missing or failed.'":
            "(cartState?'. Original manual evaluation is preserved; native state checks are shown separately.':'. This earlier record is preserved separately; it does not mean the answer checks above are missing or failed.')",
        "`Extractor: ${grade.extractor.model} · ${grade.extractor.provider} · ${grade.extractor.version}`":
            "(cartState?'Deterministic saved-state projection; no extractor or inference.':`Extractor: ${grade.extractor.model} · ${grade.extractor.provider} · ${grade.extractor.version}`)",
        "'Extracted claims, URL derivations and evidence hashes'":
            "(cartState?'Native cart components and bound evidence hashes':'Extracted claims, URL derivations and evidence hashes')",
    }
    for before, after in replacements.items():
        if html.count(before) != 1:
            raise ValueError('State viewer integration anchor changed: '+before)
        html = html.replace(before, after)
    return html.encode()
