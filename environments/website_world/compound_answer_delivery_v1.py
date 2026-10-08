"""Prospective compound execution branch selection, without native grading.

Returned/saved/source/task bindings and actual successful cleanup are caller
obligations. This helper never authorizes a grade from an unbound JSON record.
It neither constructs a formatter nor synthesizes successful-schema claims.
"""

SCHEMA = 'connected-world-manual-v1'
SOURCE = 'BrowserGym chat from executed send_msg_to_user; no extraction or repair'
BUDGET_STOPS = frozenset(('max_steps', 'max_input_tokens'))


class UnsupportedDeliveredAnswer(ValueError):
    """There is delivered text, but no released extraction contract for it."""


def select_answer_path(natural, terminal):
    if type(natural) is not dict or type(terminal) is not dict:
        raise ValueError('Require actual recorded answer and terminal objects')
    fields = {'schema_version', 'source', 'text', 'assistant_messages', 'stop_reason',
              'initial_chat_messages_excluded', 'technical_error', 'correctness'}
    if not fields <= natural.keys(): raise ValueError('Incomplete executed-answer schema')
    if natural['schema_version'] != SCHEMA or natural['source'] != SOURCE or natural['correctness'] is not None:
        raise ValueError('Unknown recorded-answer source/schema or preasserted correctness')
    if (type(natural['initial_chat_messages_excluded']) is not int
            or natural['initial_chat_messages_excluded'] < 0):
        raise ValueError('Invalid excluded initial chat prefix')
    messages = natural['assistant_messages']
    if type(messages) is not list or any(type(value) is not str for value in messages):
        raise ValueError('Invalid executed assistant-message list')
    text = natural['text']
    if text is not None and type(text) is not str:
        raise ValueError('Invalid recorded final text')
    if text != (messages[-1] if messages else None):
        raise ValueError('Final text contradicts executed assistant messages')
    required = {'stop_reason', 'trace_complete', 'error', 'execution_error',
                'cleanup_errors', 'terminated', 'truncated'}
    if not required <= terminal.keys(): raise ValueError('Incomplete terminal recording')
    if (terminal['trace_complete'] is not True or terminal.get('recording_error')
            or terminal['error'] is not None or terminal['execution_error'] is not None
            or terminal['cleanup_errors'] != [] or type(terminal['cleanup_errors']) is not list
            or natural['technical_error'] is not None):
        raise ValueError('Execution/cleanup/recording failure cannot be a task verdict')
    stop = terminal['stop_reason']
    if type(stop) is not str or stop != natural['stop_reason']:
        raise ValueError('Recorded answer and terminal stop disagree')
    if stop not in BUDGET_STOPS | {'agent_finished'}:
        raise ValueError('Unsupported interrupted/environment terminal state')
    if terminal['terminated'] is not False or type(terminal['truncated']) is not bool:
        raise ValueError('Termination or malformed truncation state')
    # The actual runner deliberately sets summary.truncated=True for budget
    # stops. Environment truncation has its distinct stop_reason and rejects.
    if terminal['truncated'] is not (stop in BUDGET_STOPS):
        raise ValueError('Truncation flag contradicts the source-defined stop')
    if not any(value.strip() for value in messages):
        return 'missing_answer'
    if stop in BUDGET_STOPS:
        raise UnsupportedDeliveredAnswer('Nonempty delivered answer at budget cap is not absence')
    if text is None or not text.strip():
        raise UnsupportedDeliveredAnswer('Earlier nonempty reply with blank final text is not absence')
    return 'extract_completed_answer'
