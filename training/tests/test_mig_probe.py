"""A physical MIG-capable GPU is not sufficient to start the two-slice tests."""
import importlib.util
from pathlib import Path
import pytest

pytest.importorskip('modal')
spec = importlib.util.spec_from_file_location('modal_mig_probe_test', Path(__file__).parents[1] / 'scripts/modal_mig_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
XML = '<nvidia_smi_log><gpu><product_name>RTX PRO 6000</product_name><mig_mode><current_mig>{}</current_mig></mig_mode></gpu></nvidia_smi_log>'
TWO = 'MIG 2g.48gb (UUID: MIG-one)\nMIG 2g.48gb (UUID: MIG-two)'


@pytest.mark.parametrize('mode,listing', [('Disabled', ''), ('N/A', TWO),
    ('Enabled', 'MIG 2g.48gb (UUID: MIG-one)'),
    ('Enabled', 'MIG 2g.48gb (UUID: MIG-one)\nMIG 2g.48gb (UUID: MIG-one)')])
def test_unavailable_mig_aborts(mode, listing):
    report = probe.classify(XML.format(mode), listing, '0')
    assert report['status'] == 'ABORT_MIG_UNAVAILABLE'
    assert not report['two_mig_devices_exposed']


def test_two_slices_require_cuda_validation():
    report = probe.classify(XML.format('Enabled'), TWO, '0')
    assert report['status'] == 'NEEDS_CUDA_CHECK'
    assert report['mig_uuids'] == ['MIG-one', 'MIG-two']
