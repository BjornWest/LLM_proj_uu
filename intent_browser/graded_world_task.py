"""Generated listed-offer episodes with opt-in, separate natural-answer grading."""
import json

from .connected_world_task import ConnectedWorldTask, checked_files
from .evaluation import Evaluation
from .trace import write_json


class GradedWorldTask(ConnectedWorldTask):
    def __init__(self, *args, answer_grader, answer_extractor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.answer_grader = answer_grader
        self.answer_extractor = answer_extractor

    def prepare(self, trace):
        result = super().prepare(trace)
        private = trace.directory/'manual-review-private'
        write_json(private/'answer-response-contract.json', self.answer_grader.contract)
        result.update(grading='listed_offer_extraction' if self.answer_extractor else 'listed_offer_pending_extraction',
                      response_contract_artifact='manual-review-private/answer-response-contract.json')
        return result

    def evaluate(self, env, trace, outcome):
        manual = super().evaluate(env, trace, outcome)
        natural = json.loads((trace.directory/'natural-answer.json').read_text())
        if self.answer_extractor is None:
            return Evaluation('listed-offer-answer', self.answer_grader.contract['version'], trust='pending-extraction',
                              evidence=manual.evidence, limitations=['A dedicated answer extractor was not configured; outcome remains unknown.'])
        if outcome.get('error') or outcome['stop_reason'] != 'agent_finished' or not natural['text']:
            return manual
        try:
            checked_files(self.files)
            grade = self.answer_extractor(self.answer_grader, self.public, natural['text'], trace.directory/'answer-extraction')
            checked_files(self.files)
            write_json(trace.directory/'answer-grade.json', grade)
            return Evaluation('listed-offer-answer', grade['grading_version'], trust='model-extracted-native-checked',
                              task_completed=grade['structured_claims_correct'], evidence=['natural-answer.json',
                              'answer-extraction/claims.json', 'answer-grade.json'], limitations=grade['limitations'])
        except Exception as exc:
            write_json(trace.directory/'answer-grading-error.json', {'type': type(exc).__name__, 'message': str(exc), 'automatic_retries': 0})
            return Evaluation('listed-offer-answer', self.answer_grader.contract['version'], trust='extraction-failed',
                              evidence=['natural-answer.json', 'answer-grading-error.json'],
                              limitations=['Extraction failed; task correctness remains unknown. Original browsing outcome is preserved.'])
