import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image
from intent_browser.trace import Trace
from intent_browser.observation_writer import ObservationWriter, write_payload


def observation():
    return {'screenshot': np.zeros((5, 8, 3), dtype=np.uint8),
            'axtree_object': {'nodes': [{'name': {'value': 'original'}}]},
            'extra': np.array([2, 3])}


def test_queued_snapshot_is_frozen_and_text_immediate(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def held(*args):
        entered.set()
        assert release.wait(5)
        return write_payload(*args)
    trace = Trace(tmp_path, {}, async_recording=True)
    try:
        with patch('intent_browser.observation_writer.write_payload', held):
            obs = observation()
            refs = trace.observation(0, obs, 'policy text')
            assert entered.wait(2)
            assert (trace.directory / refs['text']).read_text() == 'policy text'
            assert not (trace.directory / refs['raw']).exists()
            obs['axtree_object']['nodes'][0]['name']['value'] = 'mutated'
            obs['extra'][0] = 999
            obs['screenshot'][:] = 255
            release.set()
            trace.flush_observations()
        raw = json.loads(gzip.decompress((trace.directory / refs['raw']).read_bytes()))
        assert raw['axtree_object']['nodes'][0]['name']['value'] == 'original'
        assert raw['extra'] == [2, 3]
        assert np.array(Image.open(trace.directory / refs['screenshot'])).max() == 0
    finally:
        release.set()
        trace.finish({'stop_reason': 'test'})
    assert json.loads((trace.directory / 'episode.json').read_text())['trace_complete']
    assert trace.writer.metrics[0]['thread_id'] != threading.get_ident()


@pytest.mark.parametrize('async_recording', [False, True])
def test_finish_flushes_all_phases(tmp_path, async_recording):
    trace = Trace(tmp_path, {}, async_recording=async_recording)
    refs = [trace.observation(i, observation(), f'text {i}', phase=phase)
            for i, phase in enumerate(('transition','decision','background','batch_guard'))]
    trace.finish({'stop_reason': 'test'})
    for ref in refs:
        for name in ref.values():
            assert (trace.directory/name).is_file()
    if async_recording:
        assert [m['stem'] for m in trace.writer.metrics] == ['observation-000','decision-observation-001','background-observation-002','batch_guard-observation-003']


def test_queue_backpressure_and_single_large_payload(tmp_path):
    entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
    def held(*args):
        entered.set()
        assert release.wait(5)
        return write_payload(*args)
    writer = ObservationWriter(tmp_path, max_pending=1, max_bytes=1024)
    try:
        with patch('intent_browser.observation_writer.write_payload', held), ThreadPoolExecutor(1) as pool:
            writer.submit('first','{}',None)
            assert entered.wait(2)
            def second():
                writer.submit('second','{}',None)
                second_done.set()
            future = pool.submit(second)
            assert not second_done.wait(.05)
            release.set()
            future.result(timeout=3)
        writer.submit('oversized', 'x'*2048, None)
        assert (tmp_path/'oversized.json.gz').exists()
        assert writer.high_water_jobs == 1
        assert writer.high_water_bytes <= 1024
    finally:
        release.set(); writer.close()


def test_failed_write_is_visible_and_trace_not_complete(tmp_path):
    trace = Trace(tmp_path, {}, async_recording=True)
    with patch('intent_browser.observation_writer.write_payload', side_effect=OSError('disk full')):
        trace.observation(0, observation(), 'text')
        with pytest.raises(RuntimeError, match='Trace incomplete'):
            trace.finish({'stop_reason':'agent_finished'})
    result = json.loads((trace.directory/'episode.json').read_text())
    assert result['trace_complete'] is False
    assert 'recording_error' in result
    assert trace.events.closed and trace.lifecycle.closed
    with pytest.raises(RuntimeError): trace.observation(1, observation(), 'text')


def test_atomic_failure_leaves_no_partial_files(tmp_path):
    def fail(*a,**kw): raise OSError('disk full')
    with patch('intent_browser.observation_writer.gzip.open',side_effect=fail):
        with pytest.raises(OSError):write_payload(tmp_path,'x','{}',None)
    assert list(tmp_path.iterdir()) == []


def test_publisher_defers_pending_png_until_atomic_publication(tmp_path):
    from intent_browser.team_worker import Publisher
    trace = Trace(tmp_path, {})
    publisher = Publisher(object(), {'id':'job','lease':'lease'}, tmp_path)
    publisher.directory = trace.directory
    uploaded = []
    publisher.upload = lambda name, data: uploaded.append(name)
    (trace.directory/'observation-000.txt').write_text('AX')
    trace.append({'step':0,'action':"click('1')",'observation':{
        'text':'observation-000.txt','screenshot':'observation-000.png'}})
    assert publisher.project()['steps'] == []
    assert uploaded == []
    (trace.directory/'observation-000.png').write_bytes(b'complete-image')
    result = publisher.project()
    assert len(result['steps']) == 1
    assert result['image'] == 'observation-000.png'
    assert uploaded == ['observation-000.txt','observation-000.png']
    trace.finish({'stop_reason':'test'})
