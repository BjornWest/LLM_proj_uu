"""Runtime admission changes: drain rather than cancel admitted work."""
from pathlib import Path
import sys
import threading
import time
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_training.capacity_control import EpisodeCapacityController, ParkingConfig, CapacitySnapshot, TurnCancelled


def controller():
    c=EpisodeCapacityController(ParkingConfig(max_active_episodes=3,max_generation_requests=3),
        limits_ceiling={'max_active_episodes':7,'max_generation_requests':8})
    c.observe(CapacitySnapshot(time.monotonic(),0,0,0,.2,0));return c


def test_lowering_targets_drains_inflight_and_retains_parked_lifecycle():
    c=controller()
    for i in range(3):c.register_episode(str(i));c.acquire_turn(str(i),'r'+str(i),timeout=1)
    before=c.status()['episodes'];changed=c.update_limits(max_active_episodes=1,max_generation_requests=1,expected_revision=0)
    assert changed['active_episodes']==3 and changed['generation_requests']==3
    assert c.status()['episodes']==before
    with pytest.raises(ValueError):c.register_episode('new')
    for i in range(3):c.release_turn(str(i),'r'+str(i));c.finish_episode(str(i))
    c.register_episode('new');assert c.limits()['active_episodes']==1


def test_raise_wakes_waiter_with_same_policy_request_state():
    c=controller();c.update_limits(max_active_episodes=3,max_generation_requests=1,expected_revision=0)
    c.register_episode('first');c.register_episode('second');c.acquire_turn('first','r1',timeout=1)
    done=[]
    t=threading.Thread(target=lambda:done.append(c.acquire_turn('second','r2',timeout=2)),daemon=True);t.start()
    end=time.monotonic()+1
    while not c.status()['episodes']['second']['waiting'] and time.monotonic()<end:time.sleep(.01)
    assert not done
    c.update_limits(max_active_episodes=4,max_generation_requests=2,expected_revision=1)
    t.join(1);assert not t.is_alive() and done==['r2']
    assert c.status()['episodes']['first']['request_id']=='r1'
    c.release_turn('first','r1');c.release_turn('second','r2');c.close()


def test_stale_revision_invalid_bool_or_ceiling_changes_are_atomic():
    c=controller();c.update_limits(max_active_episodes=4,max_generation_requests=4,expected_revision=0)
    before=c.limits()
    for kwargs in ({'expected_revision':0},{'max_active_episodes':8},{'max_generation_requests':9},
                   {'max_generation_requests':True},{'max_active_episodes':0},{'expected_revision':True}):
        request={'max_active_episodes':4,'max_generation_requests':4,'expected_revision':1,**kwargs}
        with pytest.raises(ValueError):c.update_limits(**request)
        assert c.limits()==before
    c.close()
    with pytest.raises(TurnCancelled):c.update_limits(max_active_episodes=4,max_generation_requests=4,expected_revision=1)


def test_default_ceiling_does_not_invent_unqualified_resource_capacity():
    c=EpisodeCapacityController(ParkingConfig(max_active_episodes=2,max_generation_requests=2))
    with pytest.raises(ValueError):c.update_limits(max_active_episodes=3,max_generation_requests=3,expected_revision=0)
    assert c.limits()['revision']==0
