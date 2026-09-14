"""Accept one literal BrowserGym call; never evaluate model-provided Python."""

import ast
import inspect
from dataclasses import dataclass

from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.core.action import functions

from .search import validate_search_query


ACTION_NAMES = ("click", "fill", "check", "uncheck", "select_option", "press", "scroll", "noop", "send_msg_to_user")


def make_action_set():
    return HighLevelActionSet(
        subsets=["custom"],
        custom_actions=[getattr(functions, name) for name in ACTION_NAMES],
        multiaction=False,
        strict=True,
    )


@dataclass
class Decision:
    name: str
    arguments: dict
    code: str


def parse_action(text: str) -> str:
    return parse_decision(text).code


def parse_decision(text: str, *, allow_search=False) -> Decision:
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
    if (call.func.id not in ACTION_NAMES and not is_search) or any(k.arg is None for k in call.keywords):
        raise ValueError("Unsupported action")
    args = [ast.literal_eval(a) for a in call.args]
    kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    if len(kwargs) != len(call.keywords):
        raise ValueError("Duplicate keyword argument")
    function = validate_search_query if is_search else getattr(functions, call.func.id)
    bound = inspect.signature(function).bind(*args, **kwargs)
    if is_search:
        validate_search_query(**bound.arguments)
    if call.func.id == "noop":
        wait = bound.arguments.get("wait_ms", 1000)
        if type(wait) not in (int, float) or not 0 <= wait <= 10000:
            raise ValueError("noop wait must be between 0 and 10000 ms")
    return Decision(call.func.id, dict(bound.arguments), ast.unparse(call))
