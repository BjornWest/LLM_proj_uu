"""Load an optional pinned inspection package without replacing native modules.

The suite caller pins this stdlib-only loader before importing it. This loader
checks all inspection bytes before executing any of them and ignores .pyc caches.
Each case uses a fresh private package; native training/environment imports retain
that case's frozen root. No mutable overlay or served-asset change is installed.
"""
from hashlib import sha256
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import types
import uuid


class CheckedSourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, name, root, pins):
        self.name, self.root, self.pins = name, root, pins

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.name + '.'):
            return None
        relative = Path(*fullname[len(self.name) + 1:].split('.'))
        source = self.root / relative.with_suffix('.py')
        package = False
        if not source.is_file():
            source = self.root / relative / '__init__.py'
            package = True
        if str(source) not in self.pins:
            raise ModuleNotFoundError('Undeclared inspection module: ' + fullname)
        spec = importlib.util.spec_from_loader(fullname, self, is_package=package)
        spec.origin = str(source)
        if package:
            spec.submodule_search_locations = [str(source.parent)]
        return spec

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path = Path(module.__spec__.origin)
        raw = path.read_bytes()
        if path.resolve() != path or sha256(raw).hexdigest() != self.pins[str(path)]:
            raise ValueError('Inspection source changed before import: ' + str(path))
        module.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), module.__dict__)


def load_recording(package_root, expected_sources):
    """Return (module, absolute pins); inputs use package-relative filenames.

    The returned module exports recording_runner and compile_suite_task lives
    beside it. Missing/changed files reject here; the optional caller can record
    that error and continue its original runner, without retrying an episode.
    """
    supplied = Path(package_root).absolute()
    root = supplied.resolve()
    if supplied != root or not isinstance(expected_sources, dict) or not expected_sources:
        raise ValueError('Require a real inspection package root and exact source pins')
    actual = {str(p.relative_to(root)) for p in root.glob('*.py')}
    actual.update(str(p.relative_to(root)) for p in (root/'assets').glob('*.js'))
    if actual != set(expected_sources):
        raise ValueError('Inspection module/asset inventory differs from approved package')
    pins = {}
    for relative, digest in expected_sources.items():
        path = root / relative
        if path.resolve() != path or not path.is_relative_to(root):
            raise ValueError('Nonlocal/symlink inspection source: ' + relative)
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Inspection source pin changed: ' + relative)
        pins[str(path)] = digest
    name = '_suite_inspection_' + uuid.uuid4().hex
    finder = CheckedSourceFinder(name, root, pins)
    package = types.ModuleType(name)
    package.__path__ = [str(root)]
    package.__package__ = name
    package.__file__ = str(root/'__init__.py')
    sys.modules[name] = package
    sys.meta_path.insert(0, finder)
    def release():
        """Release this case's private imports after all recording/compilation use."""
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for key in list(sys.modules):
            if key == name or key.startswith(name+'.'):
                del sys.modules[key]
    try:
        import importlib
        module = importlib.import_module(name+'.native_suite_recording')
        module.release_package = release
        # Evaluated assets are hashed as bytes before provider construction.
        if module.package_pins() != pins:
            raise ValueError('Inspection closure changed during imports')
        return module, pins
    except BaseException:
        release()
        raise
