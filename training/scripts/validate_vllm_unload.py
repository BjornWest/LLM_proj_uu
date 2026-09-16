#!/usr/bin/env python3
"""CPU-only native vLLM endpoint test with a simulated engine/cache; no models."""
import asyncio
from collections import defaultdict
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from browser_training.vllm_compat import NEW, OLD, SHA256, patched_source


async def main():
    import vllm.entrypoints.openai.models.serving as installed
    from vllm.entrypoints.serve.lora.protocol import UnloadLoRAAdapterRequest
    source=Path(installed.__file__).read_text().replace(NEW,OLD)
    assert hashlib.sha256(source.encode()).hexdigest()==SHA256
    results=[]
    for patched, behavior in [(False,True),(True,True),(True,False),(True,RuntimeError('engine unavailable'))]:
        module=ModuleType('vllm.entrypoints.openai.models._unload_probe')
        module.__package__='vllm.entrypoints.openai.models'
        exec(compile(patched_source(source) if patched else source, '<audited-unload-probe>', 'exec'),module.__dict__)
        server=module.OpenAIServingModels.__new__(module.OpenAIServingModels)
        remove=AsyncMock(side_effect=behavior if isinstance(behavior,Exception) else None,
                         return_value=behavior if not isinstance(behavior,Exception) else None)
        server.engine_client=SimpleNamespace(remove_lora=remove)
        server.lora_resolver_lock=defaultdict(asyncio.Lock)
        server.lora_requests={'policy-v1':SimpleNamespace(lora_int_id=17)}
        answer=await server.unload_lora_adapter(UnloadLoRAAdapterRequest(lora_name='policy-v1'))
        if patched:
            remove.assert_awaited_once_with(17)
            if isinstance(behavior,Exception):
                assert 'policy-v1' in server.lora_requests and not isinstance(answer,str)
            else:
                assert 'policy-v1' not in server.lora_requests and isinstance(answer,str)
        else:
            remove.assert_not_awaited()
            assert 'policy-v1' not in server.lora_requests
        results.append({'patched':patched,'engine_behavior':str(behavior),'engine_remove_calls':remove.await_count,
                        'name_retained':'policy-v1' in server.lora_requests})
    report={'status':'PASS','scope':'Actual Python endpoint, simulated engine; no GPU/cache allocation',
        'original_sha256':SHA256,'patched_sha256':hashlib.sha256(patched_source(source).encode()).hexdigest(),
        'cases':results}
    Path('research').mkdir(exist_ok=True)
    Path('research/vllm-unload-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': asyncio.run(main())
