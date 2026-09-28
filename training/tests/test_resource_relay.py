import importlib.util
import os
from pathlib import Path

import pytest

from browser_training.monitoring_files import atomic_json
from browser_training.resource_monitor import ResourceSampler
from browser_training.runtime_metrics import RuntimeMetrics

spec=importlib.util.spec_from_file_location('relay',Path(__file__).resolve().parents[1]/'scripts/relay_resource_sample.py')
relay=importlib.util.module_from_spec(spec);spec.loader.exec_module(relay)


def test_actual_rsync_delivery_and_duplicate_import(tmp_path):
    monitor=RuntimeMetrics(tmp_path/'receiver',run_id='relay',synthetic=True)
    event=ResourceSampler(role='rollout',root_pid=os.getpid()).sample()
    source=tmp_path/'sender.json'
    atomic_json(source,dict(run_id='relay',synthetic=True,event=event))
    target=monitor.directory/'resources';target.mkdir()
    for _ in range(2):
        result=relay.relay(source,monitor.directory/'snapshot.json',str(target))
        assert result['transport']=='rsync-local'
        assert monitor.emit_snapshot()['watermark']==1
    assert monitor.emit_snapshot()['telemetry']['rollout/ram_gib']['value']>0


def test_ssh_argv_is_bounded_and_rejects_option_injection():
    args=relay.command('/tmp/sample.json','/srv/a directory/resources','user@host.example')
    assert '--protect-args' in args and 'ssh -oBatchMode=yes -oConnectTimeout=5' in args
    assert args[-1]=='user@host.example:/srv/a directory/resources/'
    with pytest.raises(ValueError,match='plain SSH'):
        relay.command('/tmp/a','/tmp/b','-oProxyCommand=bad')
