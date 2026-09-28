import gzip
import io
import json
import numpy as np
import pytest
from PIL import Image
from intent_browser.trace import Trace, json_default


@pytest.mark.parametrize('phase', ['transition', 'decision', 'batch_guard', 'background'])
@pytest.mark.parametrize('screenshot', [False, True])
def test_bulk_recording_preserves_old_decompressed_bytes_and_pixels(tmp_path, phase, screenshot):
    obs = {'screenshot': np.zeros((4, 6, 3), dtype=np.uint8) if screenshot else None,
           'axtree_object': {'nodes': [{'nodeId': '17', 'name': {'value': 'Ångström "room"\t\n😀'},
                                     'properties': [None, True, False, 3.5]}]},
           'extra': np.array([1, 2]), 'elapsed_time': np.array([.125]),
           'url': 'http://fixture.invalid/', 'empty': {}}
    baseline = io.BytesIO()
    with gzip.GzipFile(fileobj=baseline, mode='wb') as compressed:
        with io.TextIOWrapper(compressed, encoding='utf-8') as text:
            json.dump({k:v for k,v in obs.items() if k!='screenshot'}, text, default=json_default)
    trace = Trace(tmp_path, {'test': 'encoding_parity'})
    try:
        refs = trace.observation(3, obs, 'Exact AX\n\tbutton "Room"', phase=phase)
        assert gzip.decompress((trace.directory/refs['raw']).read_bytes()) == gzip.decompress(baseline.getvalue())
        assert (trace.directory/refs['text']).read_text() == 'Exact AX\n\tbutton "Room"'
        if screenshot:
            assert np.array_equal(np.array(Image.open(trace.directory/refs['screenshot'])), obs['screenshot'])
        else: assert refs['screenshot'] is None
        assert isinstance(obs['extra'], np.ndarray)  # Original capture not rewritten.
    finally: trace.finish({'stop_reason': 'test_complete'})
