"""Read-only trusted suite registration and public projection; no model calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path

SCHEMA = 'episode-suite-plan-v1'


def read(path):
    return json.loads(Path(path).read_text())


def trace_id(path):
    return hashlib.sha256(('browsergym:' + Path(path).name).encode()).hexdigest()[:20]


def safe_trace(case):
    if case.get('trace_directory'):
        return Path(case['trace_directory']).resolve()
    cohort = Path(case['cohort']).resolve(); live = cohort / 'live'
    result = live / 'result.json'
    if result.is_file():
        path = Path(read(result)['trace']).resolve()
        if not path.is_relative_to(live / 'runs'):
            raise ValueError('Suite case trace is outside cohort')
        return path
    paths = list((live / 'runs').glob('*/metadata.json'))
    if len(paths) > 1:
        raise ValueError('Ambiguous suite trace')
    return paths[0].parent if paths else None


class SuiteCatalog:
    def __init__(self, registry=None, *, plan_paths=None):
        self.registry = Path(registry) if registry is not None else None
        self.plan_paths = plan_paths
        self.grade_cache = {}

    def plans(self):
        config = read(self.registry) if self.registry else {'project_root': str(Path.cwd())}
        result = {}
        for filename in self.plan_paths if self.plan_paths is not None else config.get('suites', []):
            path = Path(filename)
            if not path.is_absolute():
                path = Path(config['project_root']) / path
            value = read(path)
            if value.get('schema') != SCHEMA or not isinstance(value.get('cases'), list):
                raise ValueError('Invalid registered suite')
            if value['id'] in result:
                raise ValueError('Duplicate registered suite ID')
            ids = [c['case_id'] for c in value['cases']]
            if len(ids) != len(set(ids)):
                raise ValueError('Duplicate suite case ID')
            result[value['id']] = (path, value)
        return result

    def memberships(self):
        result = {}
        for _, plan in self.plans().values():
            for case in plan['cases']:
                trace = safe_trace(case)
                if trace is None:
                    continue
                if trace in result:
                    raise ValueError('Trace belongs to multiple explicit suites')
                if case.get('metadata_sha256') and hashlib.sha256((trace / 'metadata.json').read_bytes()).hexdigest() != case['metadata_sha256']:
                    raise ValueError('Imported trace metadata changed')
                result[trace] = {'schema': 'episode-suite-membership-v1', 'id': plan['id'], 'title': plan['title'],
                    'case_id': case['case_id'], 'task_id': case['task_id'], 'task_title': case.get('task_title', case['task_id']),
                    'model_label': case['model']['model'], 'repeat': case['repeat'], 'tags': plan.get('tags', [])}
        return result

    def verified_grade(self, trace):
        # The detail view verifies original bindings once per file revision.
        # Sidebar/catalog enumeration never reads model payloads for this.
        from scripts.trace_grades import read_grade, BOUND_FILES, FILENAME, REVISION_FILENAME
        names = [*BOUND_FILES, FILENAME, REVISION_FILENAME]
        signature = tuple((n, (trace / n).stat().st_size, (trace / n).stat().st_mtime_ns, (trace / n).stat().st_ctime_ns)
                          for n in names if (trace / n).exists())
        cached = self.grade_cache.get(trace)
        if cached is None or cached[0] != signature:
            cached = (signature, read_grade(trace)); self.grade_cache[trace] = cached
        return cached[1]

    def detail(self, ident, *, summaries=None, verify=True):
        path, plan = self.plans()[ident]; rows = []; summaries = summaries or {}
        metric_path = path.parent / 'suite-metrics.json'
        metrics = {c['case_id']: c.get('usage') for c in read(metric_path)['cases']} if metric_path.is_file() else {}
        for case in plan['cases']:
            trace = safe_trace(case); tid = trace_id(trace) if trace else None
            summary = summaries.get(tid, {})
            row = {'case_id': case['case_id'], 'task_id': case['task_id'], 'task_title': case.get('task_title', case['task_id']),
                   'model': case['model']['model'], 'transport': case['model']['transport'], 'repeat': case['repeat'],
                   'scenario_sha256': case.get('scenario_sha256'), 'trace_id': tid, 'trace_url': '/#' + tid if tid else None,
                   'verdict': None, 'verdict_scope': None, 'grading_status': 'not_started', 'state': 'not_run',
                   'model_turn_count': summary.get('model_turn_count'), 'tool_call_count': summary.get('tool_call_count'),
                   'max_isl_tokens': summary.get('max_isl_tokens'), 'usage': metrics.get(case['case_id'])}
            cohort = Path(case['cohort']) if case.get('cohort') else None
            if cohort and (cohort / 'offline/acceptance.json').is_file():
                row['state'] = 'ready' if read(cohort / 'offline/acceptance.json').get('passed') else 'preflight_failed'
            if cohort and (cohort / 'execution').exists():
                row['state'] = 'running' if not (cohort / 'execution/finished.json').is_file() else 'finished'
                if (cohort / 'execution/finished.json').is_file() and read(cohort / 'execution/finished.json')['exit_code']:
                    row['state'] = 'technical_error'
            if trace:
                evaluation = read(trace / 'evaluation.json') if (trace / 'evaluation.json').is_file() else {}
                episode = read(trace / 'episode.json') if (trace / 'episode.json').is_file() else {}
                if episode:
                    row['state'] = 'technical_error' if episode.get('error') else 'finished'
                    row['stop_reason'] = episode.get('stop_reason')
                    row['action_error_count'] = episode.get('action_error_count')
                elif row['state'] != 'technical_error':
                    row['state'] = 'running'
                if evaluation.get('safe_success') is not None:
                    row.update(verdict=evaluation['safe_success'], verdict_scope='recorded_safe_success')
                status_path = trace / 'answer-grading-status.json'
                if status_path.is_file():
                    row['grading_status'] = read(status_path).get('status', 'unknown')
                grade = self.verified_grade(trace) if verify else summary.get('derived_evaluation')
                if grade:
                    row['grading_status'] = 'graded' if grade.get('binding_status') == 'verified' else 'binding_error'
                    # Answer checks do not establish broader safe success.
                    row['answer_checks'] = grade.get('structured_claims_correct') if grade.get('binding_status') == 'verified' else None
                    if row['verdict_scope'] is None:
                        row.update(verdict=row['answer_checks'], verdict_scope='derived_answer_checks')
            rows.append(row)
        verdicts = Counter('pass' if r['verdict'] is True else 'fail' if r['verdict'] is False else 'unknown' for r in rows)
        return {'id': plan['id'], 'title': plan['title'], 'description': plan.get('description', ''), 'tags': plan.get('tags', []),
                'limits': plan.get('limits'), 'case_count': len(rows), 'counts': dict(verdicts),
                'states': dict(Counter(r['state'] for r in rows)), 'cases': rows,
                'training_eligible': False, 'grade_scope_note': 'Recorded safe success and derived answer checks are distinct. Unexecuted, unknown and technical errors are retained.'}

    def index(self, summaries=None):
        return [{k: v for k, v in self.detail(ident, summaries=summaries, verify=True).items() if k != 'cases'}
                for ident in self.plans()]
