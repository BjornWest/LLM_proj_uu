"""Load pinned TRL chat utilities on CPU; omit model/multimodal-only imports."""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sys
from types import ModuleType
import urllib.request

COMMIT = "a04ffd337108285002df29d9ae73ef7e855e03f1"
SHA = "0152999b59e2210fc125703f85d33f459f74fbb72ba61494d5f38d6cb04455e2"
BASE = f"https://raw.githubusercontent.com/huggingface/trl/{COMMIT}/trl/"


def load_chat_utils():
    root = Path(".cache/trl-chat-source")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "chat_template_utils.py"
    if not path.exists():
        path.write_bytes(urllib.request.urlopen(BASE + path.name, timeout=30).read())
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == SHA
    tree = ast.parse(source)
    names = {node.right.value for node in ast.walk(tree) if isinstance(node, ast.BinOp)
             and isinstance(node.left, ast.Name) and node.left.id == "_CHAT_TEMPLATES_DIR"
             and isinstance(node.right, ast.Constant)}
    def fetch(name):
        dest = root / "chat_templates" / name
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            dest.write_bytes(urllib.request.urlopen(BASE + "chat_templates/" + name, timeout=30).read())
        return name, hashlib.sha256(dest.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(pool.map(fetch, sorted(names)))
    filtered = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module == "transformers":
                node.names = [n for n in node.names if n.name != "PreTrainedModel"]
        filtered.append(node)
    tree.body = filtered
    module = ModuleType("audited_trl_chat_utils")
    module.__file__ = str(path)
    module.PreTrainedModel = object
    sys.modules[module.__name__] = module
    exec(compile(tree, str(path), "exec"), module.__dict__)
    module.source_hashes = {"chat_template_utils.py": SHA, **hashes}
    return module
