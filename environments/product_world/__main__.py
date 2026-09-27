import argparse
import json
from pathlib import Path
from .generator import generate_catalog, summarize
from .config import defaults


def main():
    parser = argparse.ArgumentParser(description='Local catalog generator, independent of shopping tasks and layouts')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('defaults')
    gen = sub.add_parser('generate')
    gen.add_argument('--seed', type=int, default=0)
    gen.add_argument('--models', type=int, default=12)
    gen.add_argument('--config', type=Path)
    gen.add_argument('--output', type=Path)
    gen.add_argument('--public-only', action='store_true')
    gen.add_argument('--summary', action='store_true')
    world = sub.add_parser('world', help='Stores first, then shared products and store inventories')
    world.add_argument('--seed', type=int, default=0)
    world.add_argument('--stores', type=int, default=6)
    world.add_argument('--models-per-store', type=int, default=5)
    world.add_argument('--focus', default='footwear', help='Comma-separated family scope')
    world.add_argument('--config', type=Path)
    world.add_argument('--store-config', type=Path)
    world.add_argument('--output', type=Path)
    world.add_argument('--public-only', action='store_true')
    world.add_argument('--summary', action='store_true')
    scenario = sub.add_parser('scenario', help='Task and memories first, then stores and inventory')
    scenario.add_argument('--task-seed', type=int, default=0)
    scenario.add_argument('--world-seed', type=int, default=42)
    scenario.add_argument('--family', default='random')
    scenario.add_argument('--query', default='cheapest')
    scenario.add_argument('--world-preferences', default='auto', choices=('auto','none','reputation','domestic','reputation_domestic'))
    scenario.add_argument('--cookie-preferences', default='auto', choices=('auto','none','necessary_only','analytics_allowed','analytics_required'))
    scenario.add_argument('--target', choices=('category', 'model'), default='category')
    scenario.add_argument('--memory', default='auto')
    scenario.add_argument('--hidden', default='auto')
    scenario.add_argument('--stores', type=int, default=6)
    scenario.add_argument('--models-per-store', type=int, default=5)
    scenario.add_argument('--config', type=Path)
    scenario.add_argument('--store-config', type=Path)
    scenario.add_argument('--output', type=Path)
    scenario.add_argument('--destination-city', help='Bundled city ID or random; enables offline geography')
    scenario.add_argument('--destination-country', help='Country code; sample a city there if none is specified')
    scenario.add_argument('--location-config', type=Path)
    scenario.add_argument('--profile-weights', type=Path)
    task = sub.add_parser('task')
    task.add_argument('--catalog', required=True, type=Path)
    task.add_argument('--seed', type=int, default=0)
    task.add_argument('--family', default='random')
    task.add_argument('--query', default='cheapest')
    task.add_argument('--target', choices=('category', 'model'), default='model')
    task.add_argument('--memory', default='auto')
    task.add_argument('--hidden', default='auto')
    task.add_argument('--public-only', action='store_true')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=47401)
    args = parser.parse_args()
    try:
        if args.command == 'defaults': value = defaults()
        elif args.command == 'serve':
            from .preview import serve
            serve(args.port); return
        elif args.command == 'task':
            from .tasks import generate_task
            value = generate_task(json.loads(args.catalog.read_text()), seed=args.seed, family=args.family,
                                  query=args.query, target=args.target, memory=args.memory, hidden=args.hidden)
            if args.public_only: value = value['public']
        elif args.command == 'scenario':
            from .scenario import generate_scenario
            value = generate_scenario(
                {'seed': args.task_seed, 'family': args.family, 'query': args.query,
                 'target': args.target, 'memory': args.memory, 'hidden': args.hidden,
                 'destination_city': args.destination_city, 'destination_country': args.destination_country,
                 'world_preferences':args.world_preferences,'cookie_preferences':args.cookie_preferences},
                {'seed': args.world_seed, 'store_count': args.stores, 'models_per_store': args.models_per_store,
                 'config': json.loads(args.config.read_text()) if args.config else None,
                 'store_config': json.loads(args.store_config.read_text()) if args.store_config else None},
                {'config': json.loads(args.location_config.read_text()) if args.location_config else None,
                 'profile_weights': json.loads(args.profile_weights.read_text()) if args.profile_weights else None}
                if args.destination_city or args.destination_country else None)
        elif args.command == 'world':
            from .stores import generate_store_world, summarize_stores
            value = generate_store_world(args.seed, args.stores, args.models_per_store,
                [f.strip() for f in args.focus.split(',')],
                json.loads(args.config.read_text()) if args.config else None,
                json.loads(args.store_config.read_text()) if args.store_config else None)
            if args.summary: value = summarize_stores(value)
            elif args.public_only: value = value['public']
        else:
            value = generate_catalog(args.seed, args.models, json.loads(args.config.read_text()) if args.config else None)
            if args.summary: value = summarize(value)
            elif args.public_only: value = value['public']
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if getattr(args, 'output', None):
            with args.output.open('x') as f: f.write(text)
        else: print(text, end='')
    except (ValueError, OSError) as e: parser.error(str(e))


if __name__ == '__main__': main()
