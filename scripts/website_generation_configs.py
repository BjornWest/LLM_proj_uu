"""Save, search and export versioned world/task generation configurations."""
import argparse
import json
from pathlib import Path
from environments.website_world.generation_configs import Library, unpack, DEFAULT_LIBRARY, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=DEFAULT_LIBRARY)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('save', help='Save a raw request or complete config')
    add.add_argument('name'); add.add_argument('--config', type=Path, required=True)
    add.add_argument('--execution', type=Path, help='Optional execution JSON override')
    add.add_argument('--tag', action='append', default=[]); add.add_argument('--notes', default='')
    find = commands.add_parser('list', help='Find configs by text or tag')
    find.add_argument('--query', default=''); find.add_argument('--tag'); find.add_argument('--history', action='store_true')
    show = commands.add_parser('show'); show.add_argument('selector')
    report = commands.add_parser('report', help='Render a searchable human HTML index')
    report.add_argument('--output', type=Path, required=True)
    export = commands.add_parser('export', help='Export a complete reusable config; refuses overwrite')
    export.add_argument('selector'); export.add_argument('--output', type=Path, required=True)
    export.add_argument('--seed', type=int); export.add_argument('--world-size', type=float)
    register = commands.add_parser('import-generation', help='Register existing artifacts without modifying them')
    register.add_argument('name'); register.add_argument('--generation', type=Path, required=True)
    register.add_argument('--run', type=Path, action='append', default=[])
    register.add_argument('--tag', action='append', default=[]); register.add_argument('--notes', default='')
    args=parser.parse_args(); library=Library(args.library)
    if args.command=='save':
        bundle=unpack(json.loads(args.config.read_text()))
        if args.execution is not None:bundle['execution']=json.loads(args.execution.read_text())
        result=library.put(args.name,**bundle,tags=args.tag,notes=args.notes)
    elif args.command=='list':
        result=[]
        for row in library.search(query=args.query,tag=args.tag,history=args.history):
            request=row['config']['request'];world=request.get('world',{})
            result.append({'name':row['name'],'version':row['version'],'config_sha256':row['config_sha256'],
                'tags':row['tags'],'seed':request['seed'],'controls':world.get('controls',{}),
                'concepts':len(world['concept_ids']) if 'concept_ids' in world else 'default slice',
                'task':request.get('task'),'notes':row['notes']})
    elif args.command=='show':result=library.get(args.selector)
    elif args.command=='report':
        from environments.website_world.generation_configs import render_report
        result=render_report(library,args.output)
    elif args.command=='export':
        result=library.get(args.selector);bundle=unpack(result)
        if args.seed is not None:bundle['request']['seed']=args.seed
        if args.world_size is not None:bundle['request'].setdefault('world',{}).setdefault('controls',{})['world_size']=args.world_size
        # Any override creates a distinct identity, while recording its parent.
        from environments.website_world.generation_configs import VERSION,digest
        result={'schema':VERSION,'config':bundle,'config_sha256':digest(bundle),
                'derived_from':{'name':result['name'],'version':result['version'],'config_sha256':result['config_sha256']}}
        save(args.output,result)
    else:
        record,evidence=library.import_generation(args.generation,args.name,run_directories=args.run,
                                                 tags=args.tag,notes=args.notes)
        result={'record':record,'provenance':evidence}
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
