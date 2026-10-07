"""Locked private generated-world receipt store; no browser-state authority.

Product owns record.make and its native revalidation. This store commits only
that maker's detached result and preserves every successful checkout.
"""
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock

VERSION='website-simulated-order-store-v1'


def _digest(value):
    # Existing Website/native record bindings use spaced sorted JSON.
    return sha256(json.dumps(value,sort_keys=True,
                             ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class OrderStore:
    def __init__(self,baskets,*,runtime_id,record_maker=None,precommit=None):
        if type(runtime_id) is not str or not runtime_id:
            raise ValueError('Order store requires an explicit runtime identity')
        if record_maker is None:
            from .simulated_order_record import make
            record_maker=make
        if not callable(record_maker):raise ValueError('Attach the native order record maker')
        if precommit is not None and not callable(precommit):raise ValueError('Order precommit must be callable')
        self._baskets,self._maker=baskets,record_maker
        self._precommit=precommit
        self._runtime_id=runtime_id
        self._lock=RLock()
        self._receipts={}
        self._records=[]
        self._events=[]
        self._episode_binding=None
        self._sealed=False

    def bind_episode(self,binding):
        """Trusted caller only; bind capture identity before any commit.

        This does not confer source-union or browser/capture acceptance.
        """
        if type(binding) is not dict or not binding or not binding.get('episode_id'):
            raise ValueError('Bind the actual episode/source/capture identity')
        value=deepcopy(binding);_digest(value)
        with self._lock:
            if self._sealed:raise ValueError('Order store is sealed after episode cleanup')
            if self._records:raise ValueError('Cannot rebind an order store after completion')
            if self._episode_binding is not None and self._episode_binding!=value:
                raise ValueError('Order store episode identity is immutable')
            self._episode_binding=value

    def commit(self,retailer_id,submission):
        if retailer_id not in self._baskets.adapter.retailers:
            raise ValueError('Unknown retailer order scope')
        if type(submission) is not dict or type(submission.get('idempotency_key')) is not str or not submission['idempotency_key']:
            raise ValueError('Submission requires a nonempty idempotency key')
        request=deepcopy(submission)
        try:identity=_digest(request)
        except (TypeError,ValueError) as error:raise ValueError('Supply a finite JSON order submission') from error
        key=(retailer_id,request['idempotency_key'])
        with self._lock:
            if self._sealed:raise ValueError('Order store is sealed after episode cleanup')
            old=self._receipts.get(key)
            if old is not None:
                if old['submission_sha256']!=identity:
                    raise ValueError('Idempotency key was already used with another submission')
                return deepcopy(old['record'])
            # Allocate only successful commits; the native maker must reject
            # stale/defaulted quotes and all browser-provided price machinery.
            sequence=len(self._records)+1
            order_id='SIM-'+_digest([self._runtime_id,retailer_id,sequence])[:24]
            record=self._maker(self._baskets,retailer_id,deepcopy(request),order_id=order_id)
            if type(record) is not dict:raise ValueError('Native order maker returned no record')
            record=deepcopy(record);record_digest=_digest(record)
            if self._precommit is not None:self._precommit(retailer_id,deepcopy(record))
            event={'sequence':sequence,'order_id':order_id,'retailer_id':retailer_id,
                   'submission_sha256':identity,'record_sha256':record_digest}
            # Receipt, event and idempotency binding become visible together.
            self._records.append(record)
            self._events.append(event)
            self._receipts[key]={'submission_sha256':identity,'record':record}
            return deepcopy(record)

    def seal(self,expected_snapshot):
        """Trusted cleanup only: freeze commits and reject terminal ledger drift.

        The lock orders this against in-flight commits. A failed comparison
        retains the actual complete ledger and leaves the store closed; it never
        repairs the saved capture or confers effect-journal authority.
        """
        with self._lock:
            if self._sealed:raise ValueError('Order store has already been sealed')
            self._sealed=True
            if self.snapshot()!=expected_snapshot:
                raise ValueError('Order ledger changed after the terminal capture')

    def snapshot(self):
        """Read-only detached full ledger for trusted capture/grading, never HTTP."""
        with self._lock:
            world=self._baskets.adapter.world
            value={'schema':VERSION,'runtime_id':self._runtime_id,
                   'world_id':world['world_id'],'world_sha256':_digest(world),
                   'plan_id':self._baskets.plan_id,'domain_id':self._baskets.domain_id,
                   'episode_binding':deepcopy(self._episode_binding),
                   'orders':deepcopy(self._records),'events':deepcopy(self._events)}
            value['snapshot_sha256']=_digest(value)
            return value
