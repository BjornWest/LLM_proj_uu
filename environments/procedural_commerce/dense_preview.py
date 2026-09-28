"""Local R13 preview: existing generated catalog plus authored footwear controls."""
import argparse
import json
import signal
import threading
from pathlib import Path
from .generator import generate_world
from .product_fixture import footwear_fixture
from .runtime import Runtime, _write_manifest
from .presentation import SHOWCASE


def fixture(scale='large'):
    world=generate_world(7,scale)
    shoes,groups=footwear_fixture()
    ids={v['product_id'] for g in groups for v in g['variants']}
    for field in ('products','offers','aggregator_claims'):
        world[field].extend(p for p in shoes[field] if p['product_id'] in ids)
    world['private_provenance']['authored_fixture']='dense-existing-catalog-and-footwear-v1'
    return world,groups


def make_runtime(scale='large',flow='express',**overrides):
    world,groups=fixture(scale)
    config=dict(retailer_designs={**SHOWCASE,'nordhem':'dense-storefront'},
        presentation_options={'nordhem':{'nav_expanded':False,'image_count':2,'title_style':'descriptive'}},
        checkout_flows={s:flow for s in SHOWCASE},
        checkout_shells={s:'storefront' for s in SHOWCASE},
        cart_navigation={s:'inline' for s in SHOWCASE},
        product_groups=groups,product_control_styles={'nordhem':{'size_eu':'select','colour':'radio'}})
    config.update(overrides)
    return Runtime(world,**config)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scale',choices=('small','large'),default='large')
    args=parser.parse_args()
    if args.output.exists():parser.error('--output must be a fresh directory')
    stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
    with make_runtime(args.scale) as runtime:
        manifest=_write_manifest(args.output,runtime,7,args.scale)
        print(json.dumps({'manifest':str(manifest),'origins':runtime.origins,'shoe':runtime.origins['nordhem']+'/products/shoe-42-black','catalog_products':len(runtime._world['products'])}),flush=True)
        stopped.wait()


if __name__=='__main__':main()
