"""Backport the engine-removal part of upstream PR #54939 to pinned vLLM 0.28.

Only changes the unload endpoint; native engine/cache management remains intact.
"""
import hashlib

SHA256 = '1c9edb5bb1ed3127cf022bb9675fc859dce7d75fc67ba6f24afd1dbb64280c64'
OLD = '''            # Safe to delete now since we hold the lock
            del self.lora_requests[lora_name]'''
NEW = '''            # Backport upstream #54939: remove engine weights before the public name.
            # False is valid when the worker LRU has already evicted this adapter.
            try:
                await self.engine_client.remove_lora(self.lora_requests[lora_name].lora_int_id)
            except Exception as exc:
                return create_error_response(
                    message=f"Failed to remove LoRA adapter '{lora_name}': {exc}",
                    err_type="InternalServerError",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            # Safe to delete now since we hold the lock
            del self.lora_requests[lora_name]'''


def patched_source(source):
    original = source.replace(NEW, OLD)
    if hashlib.sha256(original.encode()).hexdigest() != SHA256 or original.count(OLD) != 1:
        raise ValueError('Unknown vLLM serving source; re-audit unload before patching')
    return original.replace(OLD, NEW)
