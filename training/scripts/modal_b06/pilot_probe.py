"""Pinned cached-processor inspection; runs with the inference Python on Modal."""
from hashlib import sha256
from importlib.metadata import distribution, version
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess

from pilot_relay import canonical


def prepare(binding):
    from compiler_environment import compiler_environment
    cuda = Path(distribution('nvidia-cuda-nvcc').locate_file('nvidia/cu13'))
    os.environ.update(compiler_environment(cuda, '/tmp/pilot-cuda-link',
        dict(os.environ, PATH='/opt/rl/.venv/bin:' + os.environ['PATH'])))
    if not (shutil.which('ninja')):
        raise ValueError("Preflight condition failed: shutil.which('ninja')")
    nvcc = subprocess.check_output([str(cuda/'bin/nvcc'), '--version'], text=True, timeout=15)
    if not ('V13.0.88' in nvcc):
        raise ValueError("Preflight condition failed: 'V13.0.88' in nvcc")
    from vllm.utils.flashinfer import has_flashinfer
    if not (has_flashinfer()):
        raise ValueError('Preflight condition failed: has_flashinfer()')
    if not (version('vllm') == binding['runtime']['vllm']):
        raise ValueError("Preflight condition failed: version('vllm') == binding['runtime']['vllm']")
    if not (version('transformers') == binding['runtime']['transformers']):
        raise ValueError("Preflight condition failed: version('transformers') == binding['runtime']['transformers']")
    import torch
    if not (torch.__version__ == binding['runtime']['torch']):
        raise ValueError((torch.__version__, binding['runtime']['torch']))
    if not (torch.version.cuda == '13.0'):
        raise ValueError("Preflight condition failed: torch.version.cuda == '13.0'")
    from huggingface_hub import snapshot_download
    p = Path(snapshot_download(binding['model']['repository'],
        revision=binding['model']['revision'], local_files_only=True))
    index = json.loads((p/'model.safetensors.index.json').read_text())
    files = sorted(set(index['weight_map'].values()))
    if not (files and all(((p / name).is_file() and (p / name).stat().st_size > 0 for name in files))):
        raise ValueError('Preflight condition failed: files and all(((p / name).is_file() and (p / name).stat().st_size > 0 for name in files))')
    from safetensors import safe_open
    tensor_dtypes = {}
    indexed = set(index['weight_map'])
    observed = set()
    for name in files:
        with safe_open(p/name, framework='pt', device='cpu') as shard:
            for key in shard.keys():
                if not (key not in observed and index['weight_map'].get(key) == name):
                    raise ValueError((name, key))
                observed.add(key)
                tensor = shard.get_slice(key)
                if not (all((d > 0 for d in tensor.get_shape()))):
                    raise ValueError(key)
                dtype=tensor.get_dtype();tensor_dtypes[dtype]=tensor_dtypes.get(dtype,0)+1
    if not (observed == indexed and any(('F8' in d for d in tensor_dtypes))):
        raise ValueError(tensor_dtypes)
    weight_bytes=sum((p/name).stat().st_size for name in files)
    if not (len(files) == 66 and weight_bytes == binding['model']['checkpoint_weight_bytes_historical_audit']):
        raise ValueError("Preflight condition failed: len(files) == 66 and weight_bytes == binding['model']['checkpoint_weight_bytes_historical_audit']")
    for name in ('tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja'):
        if not (sha256((p / name).read_bytes()).hexdigest() == binding['tokenizer'][name]['sha256']):
            raise ValueError("Preflight condition failed: sha256((p / name).read_bytes()).hexdigest() == binding['tokenizer'][name]['sha256']")
    if not (sha256((p / 'config.json').read_bytes()).hexdigest() == binding['model']['config_sha256']):
        raise ValueError("Preflight condition failed: sha256((p / 'config.json').read_bytes()).hexdigest() == binding['model']['config_sha256']")
    from vllm.transformers_utils.processor import get_processor
    overrides = json.loads(binding['server_argv'][binding['server_argv'].index('--mm-processor-kwargs')+1])
    processor = get_processor(str(p), local_files_only=True, **overrides)
    image = processor.image_processor
    if not (image.patch_size == 16 and image.merge_size == 2 and (image.temporal_patch_size == 2)):
        raise ValueError('Preflight condition failed: image.patch_size == 16 and image.merge_size == 2 and (image.temporal_patch_size == 2)')
    if not (image.size['shortest_edge'] == 65536 and image.size['longest_edge'] == 16777216):
        raise ValueError(image.size)
    # Effective processor identity covers official assets + exact active geometry.
    assets = {name: sha256((p/name).read_bytes()).hexdigest()
              for name in ('preprocessor_config.json', 'video_preprocessor_config.json') if (p/name).is_file()}
    if not ('preprocessor_config.json' in assets):
        raise ValueError("Preflight condition failed: 'preprocessor_config.json' in assets")
    effective = dict(assets=assets, processor_class=type(processor).__name__,
                     image_class=type(image).__name__, overrides=overrides,
                     patch_size=image.patch_size, merge_size=image.merge_size,
                     temporal_patch_size=image.temporal_patch_size,
                     size={k:image.size[k] for k in ('shortest_edge','longest_edge')})
    from PIL import Image
    counts = []
    for width, height in ((64,64), (1280,720), (2048,1024)):
        grid = image(images=Image.new('RGB',(width,height),'white'), return_tensors='pt')['image_grid_thw'][0]
        counts.append(dict(width=width,height=height,image_tokens=int(grid.prod())//4))
    return dict(snapshot=str(p), weight_bytes=weight_bytes,tensor_count=len(observed),tensor_dtypes=tensor_dtypes,
                cached_weight_files=len(files), cuda_home=str(cuda), nvcc=nvcc,
                processor=effective, image_processor_sha256=sha256(canonical(effective)).hexdigest(),
                image_counts=counts, versions={**{n:version(n) for n in ('vllm','torch','transformers','flash-linear-attention')},
                                                'torch_build':torch.__version__, 'cuda':torch.version.cuda})


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--binding', required=True)
    a = p.parse_args()
    print(json.dumps(prepare(json.loads(Path(a.binding).read_text()))))
