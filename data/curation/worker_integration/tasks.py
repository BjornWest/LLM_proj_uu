"""Single task factory consumed by local suites and private worker dispatch."""
from .bindings import contract_for, load_registry


def make_task(task_id, *, runtime_context, revision):
    registry = load_registry(runtime_context.registry_path)
    matches = [row for row in registry['tasks'] if row['id'] == task_id]
    if len(matches) != 1 or matches[0]['revision'] != revision:
        raise ValueError('Unknown task or task revision')
    row = matches[0]
    contract = contract_for(runtime_context.project_root, row)
    if row['family'].startswith('tricky.'):
        from .tricky import TrickyTask
        return TrickyTask(row, contract, runtime_context)
    from .webarena import WebArenaTask
    return WebArenaTask(row, contract, runtime_context)
