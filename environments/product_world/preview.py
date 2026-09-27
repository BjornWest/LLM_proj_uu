"""Privileged local catalog inspector. Does not host any retailer or commerce API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from .config import defaults
from .generator import generate_catalog, summarize
from .tasks import generate_task
from .stores import generate_store_world, summarize_stores, generate_world_task, store_defaults
from .scenario import sample_task, generate_scenario


class Handler(BaseHTTPRequestHandler):
    planner = None
    def respond(self, code, data, mime='application/json; charset=utf-8'):
        value = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(value)))
        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(value)

    def do_GET(self):
        if self.path == '/': self.respond(200, Path(__file__).with_name('preview.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/defaults': self.respond(200, defaults())
        elif self.path == '/api/store-defaults': self.respond(200, store_defaults())
        elif self.path == '/api/geography':
            from .geography import network
            from .locations import location_defaults
            from .merchant_profiles import PROFILES
            self.respond(200, {'network':network(),'defaults':location_defaults(),'profiles':PROFILES})
        else: self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path not in ('/api/generate', '/api/task', '/api/world', '/api/world-task', '/api/scenario-task', '/api/scenario', '/api/location-quotes', '/api/reference-outcome'):
            self.respond(404, {'error': 'Not found'}); return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 100000: raise ValueError('Expected a JSON request of at most 100000 bytes')
            args = json.loads(self.rfile.read(length))
            if not isinstance(args, dict): raise ValueError('Expected an object')
            if self.path == '/api/reference-outcome':
                from .outcomes import evaluate
                scenario=generate_scenario(**args)
                self.respond(200,{'world_sha256':scenario['bundle']['world_sha256'],**evaluate(scenario)});return
            if self.path == '/api/location-quotes':
                from .locations import quote
                if set(args)-{'task_options','world_options','location_options','offer_id','quantity'}:
                    raise ValueError('Unknown quote parameter')
                scenario = generate_scenario(**{k:v for k,v in args.items() if k in ('task_options','world_options','location_options')})
                if 'locations' not in scenario:raise ValueError('Quotes require a geographic scenario')
                world, loc = scenario['bundle'],scenario['locations']
                offer_id=args.get('offer_id'); quantity=args.get('quantity',1)
                delivery=quote(world,loc,offer_id,quantity=quantity)
                merchant=next(m for m in loc['public']['merchants'] if m['retailer_id']==delivery['retailer_id'])
                branches=[{'branch':b,'pickup':quote(world,loc,offer_id,method='pickup',branch_id=b['branch_id'],quantity=quantity),
                           'inspect':quote(world,loc,offer_id,method='inspect',branch_id=b['branch_id'],quantity=quantity)} for b in merchant['branches']]
                branches.sort(key=lambda row: (row['pickup']['travel']['driving']['distance_km'] is None,
                    row['pickup']['travel']['driving']['distance_km'] or 0, row['branch']['branch_id']))
                self.respond(200,{'delivery':delivery,'branches':branches,'world_sha256':world['world_sha256']});return
            if self.path == '/api/scenario-task':
                self.respond(200, sample_task(**args)); return
            if self.path == '/api/scenario':
                result = generate_scenario(**args)
                if self.planner is not None and 'locations' in result:
                    from .travel import export_travel_planner
                    export = export_travel_planner(result['bundle'], result['locations'])
                    result['travel_planner_url'] = self.planner.register(export)
                self.respond(200, result); return
            if self.path in ('/api/world', '/api/world-task'):
                world_keys = {'seed', 'store_count', 'models_per_store', 'focus_families', 'config', 'store_config'}
                task_keys = {'task_seed', 'family', 'query', 'target', 'memory', 'hidden'} if self.path == '/api/world-task' else set()
                if set(args) - world_keys - task_keys: raise ValueError('Unknown parameter')
                world = generate_store_world(**{k: v for k, v in args.items() if k in world_keys})
                if self.path == '/api/world':
                    self.respond(200, {'bundle': world, 'summary': summarize_stores(world)})
                else:
                    self.respond(200, generate_world_task(world, seed=args.get('task_seed', 0),
                        **{k: v for k, v in args.items() if k in task_keys and k != 'task_seed'}))
                return
            allowed = {'seed', 'model_count', 'config'} | ({'task_seed', 'family', 'query', 'target', 'memory', 'hidden'} if self.path == '/api/task' else set())
            if set(args) - allowed: raise ValueError('Unknown parameter')
            catalog = generate_catalog(**{k: v for k, v in args.items() if k in ('seed', 'model_count', 'config')})
            if self.path == '/api/generate': self.respond(200, {'bundle': catalog, 'summary': summarize(catalog)})
            else:
                task = generate_task(catalog, seed=args.get('task_seed', 0), **{k: v for k, v in args.items() if k in ('family', 'query', 'target', 'memory', 'hidden')})
                self.respond(200, task)
        except (ValueError, TypeError, KeyError) as e: self.respond(400, {'error': str(e)})


def serve(port=47401):
    from environments.travel_planner.runtime import Runtime
    with Runtime() as planner:
        Handler.planner = planner
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        print(f'Catalog authoring: http://localhost:{server.server_port}/', flush=True)
        try:server.serve_forever()
        finally:server.server_close()
