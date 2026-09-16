"""Budget gates must precede volume access and any remote work."""
import importlib.util
from pathlib import Path
import pytest
pytest.importorskip('modal')

@pytest.mark.parametrize('name',['modal_inference','modal_grpo'])
def test_expired_probe_starts_nothing(name):
    path=Path(__file__).parents[1]/'scripts'/f'{name}.py'
    spec=importlib.util.spec_from_file_location(name+'_bounds_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(TimeoutError,match='Authorization window expired'):
        module.gpu_probe.get_raw_f()('expired',{},0)


def test_e2e_expired_window_starts_nothing(monkeypatch):
    scripts = Path(__file__).parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    import modal_e2e
    with pytest.raises(TimeoutError, match='Authorization window exhausted'):
        modal_e2e.gpu_probe.get_raw_f()('expired', {}, 0, 16)
