"""Exact private imports, no bytecode/native-module replacement."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import pytest
from scripts.load_suite_inspection import load_recording

ROOT=Path(__file__).resolve().parents[1]/'training/browser_training'

def pins(root):
    return {str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest()
        for p in [*root.glob('*.py'),*(root/'assets').glob('*.js')]}


def test_real_package_imports_under_private_name_and_leaves_native_modules():
    import training.browser_training.native_suite_recording as native
    before=dict(sys.modules)
    module,absolute=load_recording(ROOT,pins(ROOT))
    assert module.__name__.startswith('_suite_inspection_')
    assert module is not native and module.package_pins()==absolute
    assert sys.modules['training.browser_training.native_suite_recording'] is native
    assert all(sys.modules[k] is v for k,v in before.items())
    module.release_package()


def test_bad_bytes_are_rejected_before_any_import():
    expected=pins(ROOT);expected['native_suite_recording.py']='0'*64
    before=set(sys.modules)
    with pytest.raises(ValueError,match='pin changed'):load_recording(ROOT,expected)
    assert set(sys.modules)==before


def test_undeclared_or_missing_asset_inventory_rejects():
    expected=pins(ROOT);expected.pop('assets/native_fact_probe.js')
    with pytest.raises(ValueError,match='inventory'):load_recording(ROOT,expected)


def test_symlink_root_cannot_redirect_package(tmp_path):
    link=tmp_path/'alias';link.symlink_to(ROOT,target_is_directory=True)
    with pytest.raises(ValueError,match='real inspection'):load_recording(link,pins(ROOT))



def test_release_does_not_accumulate_finders_or_modules():
    before=list(sys.meta_path);modules=set(sys.modules)
    for _ in range(5):
        module,_=load_recording(ROOT,pins(ROOT))
        module.release_package();module.release_package()
    assert sys.meta_path==before
    assert not any(k not in modules and k.startswith('_suite_inspection_') for k in sys.modules)
