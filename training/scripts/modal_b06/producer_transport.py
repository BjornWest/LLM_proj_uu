"""Additive replay transport/proof helpers. No allocation or model dispatch."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import urllib.error
import urllib.request

WIRE_FUNCTION_SHA256 = 'f21b9f8becf3a8713ad3bcf59d610cc59f97406a5d17b6396013191dd5ad2de3'
COUNTER_SOURCE_SHA256 = '3b89ffe833520c9ec94cf290e30d3aa127241c1ed904754e73c3d4141ea9f29b'


def wire_bytes(value):
    """Match frozen httpx0.28.1 JSON bytes, retaining nested schema insertion order."""
    return json.dumps(value,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def function_sha(source, name):
    functions=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(functions)!=1:raise ValueError('Missing or ambiguous function '+name)
    return sha256(ast.get_source_segment(source,functions[0]).encode('utf-8')).hexdigest()


def verify_serializer_binding(counter_source):
    source=Path(counter_source).read_bytes()
    if sha256(source).hexdigest()!=COUNTER_SOURCE_SHA256:raise ValueError('Released counter source changed')
    if function_sha(source.decode('utf-8'),'wire_bytes')!=WIRE_FUNCTION_SHA256:raise ValueError('Released serializer changed')
    if function_sha(Path(__file__).read_text(),'wire_bytes')!=WIRE_FUNCTION_SHA256:raise ValueError('Producer serializer changed')
    return dict(counter_source_sha256=COUNTER_SOURCE_SHA256,counter_wire_function_sha256=WIRE_FUNCTION_SHA256)


def http(origin, path, body=None, timeout=600, error_path=None, expect_json=True):
    request=urllib.request.Request(origin+path,data=None if body is None else wire_bytes(body),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read()
            if not expect_json:
                if response.status!=200:raise ValueError('Health response was not HTTP200')
                return dict(status=response.status,body_bytes=len(raw))
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        details=dict(status=exc.code,path=path,body=exc.read(1024*1024).decode('utf-8',errors='replace'))
        if error_path is not None:Path(error_path).write_text(json.dumps(details,indent=2)+'\n')
        raise RuntimeError('Inference HTTP error '+json.dumps(details)) from exc


def projection_binding(relay_source, counter_source):
    """Freeze reviewed implementation fingerprints before any allocation/dispatch."""
    serializer=verify_serializer_binding(counter_source)
    relay=Path(relay_source).read_bytes()
    relay_hash=sha256(relay).hexdigest()
    if relay_hash!='74d209d90fdc07687205f1b06fe8cc74bea29395962fb403948078a5018517e3' or function_sha(relay.decode('utf-8'),'tokenize_payload')!='6b4dc9a1ab5b10217a6b475f2aa3989941e41f5f5a080a9873f970fb51380955':
        raise ValueError('Reviewed relay projection changed before allocation')
    return dict(**serializer,tokenize_projection_source_sha256=relay_hash,
        tokenize_projection_function_sha256=function_sha(relay.decode('utf-8'),'tokenize_payload'),
        relay_source_sha256=relay_hash)

