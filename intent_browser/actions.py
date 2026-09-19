"""Accept one literal BrowserGym call; never evaluate model-provided Python."""

import ast
import inspect
from dataclasses import dataclass

from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.core.action import functions

from .search import validate_search_query


ACTION_NAMES = ("click", "fill", "check", "uncheck", "select_option", "press", "scroll", "noop", "send_msg_to_user")
VISION_ACTION_NAMES = ('scroll_into_view',)
NAVIGATION_NAMES = ("go_back", "go_forward", "reload", "goto")


def action_function(name):
    if name == 'scroll_into_view':
        from .vision import scroll_into_view
        return scroll_into_view
    if name == 'reload':
        from .navigation import reload
        return reload
    return getattr(functions, name)


DEFAULT_ACTION_TIMEOUT_MS = 5000


def validate_action_timeout(value):
    if type(value) is not int or not 100 <= value <= 60000:
        raise ValueError('action_timeout_ms must be an integer between 100 and 60000')
    return value


class BrowserActionSet(HighLevelActionSet):
    """Configure upstream fixed action deadlines without patching the package.

    Only explicit 500 ms keyword deadlines inside selected action functions are
    changed. Navigation keeps the environment deadline; helper/demo delays and
    wait_ms are untouched. The policy action signatures are unchanged.
    """
    def __init__(self, names, action_timeout_ms):
        self.names = tuple(names)
        self.action_timeout_ms = validate_action_timeout(action_timeout_ms)
        super().__init__(subsets=['custom'],
                         custom_actions=[action_function(name) for name in names],
                         multiaction=False, strict=True, retry_with_force=False)
        tree = ast.parse(self.python_includes)
        self.timeout_actions = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                changed = False
                for child in ast.walk(node):
                    if (isinstance(child, ast.keyword) and child.arg == 'timeout'
                            and isinstance(child.value, ast.Constant)
                            and type(child.value.value) is int and child.value.value == 500):
                        child.value = ast.Constant(self.action_timeout_ms)
                        changed = True
                if changed:
                    self.timeout_actions.append(node.name)
        # Version drift should not silently remove the expected click override.
        if 'click' in names and 'click' not in self.timeout_actions:
            raise ValueError('Upstream click timeout changed; review action configuration')
        if action_timeout_ms != 500:
            self.python_includes = ast.unparse(ast.fix_missing_locations(tree)) + '\n\n'

    def timeout_metadata(self):
        return {'action_timeout_ms': self.action_timeout_ms,
                'actions': self.timeout_actions,
                'scope': 'Explicit upstream 500ms action deadlines; navigation uses environment defaults',
                'retry_with_force': False}


def make_action_set(names=ACTION_NAMES, *, action_timeout_ms=DEFAULT_ACTION_TIMEOUT_MS):
    return BrowserActionSet(names, action_timeout_ms)


@dataclass
class Decision:
    name: str
    arguments: dict
    code: str


def parse_action(text: str) -> str:
    return parse_decision(text).code


def parse_decision(text: str, *, allow_search=False, allowed_names=ACTION_NAMES) -> Decision:
    if len(text) > 4096:
        raise ValueError("Action exceeds 4096 characters")
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    tree = ast.parse(text, mode="eval")
    call = tree.body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        raise ValueError("Expected exactly one action call")
    is_search = allow_search and call.func.id == "web_search"
    if (call.func.id not in allowed_names and not is_search) or any(k.arg is None for k in call.keywords):
        raise ValueError("Unsupported action")
    args = [ast.literal_eval(a) for a in call.args]
    kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    if len(kwargs) != len(call.keywords):
        raise ValueError("Duplicate keyword argument")
    function = validate_search_query if is_search else action_function(call.func.id)
    bound = inspect.signature(function).bind(*args, **kwargs)
    if is_search:
        validate_search_query(**bound.arguments)
    if call.func.id == "noop":
        wait = bound.arguments.get("wait_ms", 1000)
        if type(wait) not in (int, float) or not 0 <= wait <= 10000:
            raise ValueError("noop wait must be between 0 and 10000 ms")
    return Decision(call.func.id, dict(bound.arguments), ast.unparse(call))
