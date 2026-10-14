"""Model-free timing of ways to extract and process a token-budgeted AX overview.

Loads one prepared generated-world recipe in real Chromium (no model, no grading,
no purchases), visits representative pages and times, per page and repetition:

- native: BrowserGym's complete ``_get_obs`` (marking, DOMSnapshot, merged AX,
  extra properties, optional screenshot), public Playwright conversion or raw JSON;
- ax_marked / ax_unmarked: one raw-JSON ``Accessibility.getFullAXTree`` with or
  without BrowserGym BID marking;
- ax_depth_K: the same call limited to raw AX depth K (marked);
- bfs_rpc: node-by-node ``getChildAXNodes`` breadth-first until the budget fills;
- processing: the current AXContext capture + initial budgeted overview.

Run with PYTHONPATH set to the recipe's frozen source root so the world renders
with its pinned code. This script only measures; it changes no harness behavior.
"""
import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path


def ms(seconds):
    return round(seconds * 1000, 3)


def summarize(rows):
    out = {}
    for key in sorted({k for r in rows for k in r}):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if values:
            out[key] = {'median_ms': ms(statistics.median(values)), 'min_ms': ms(min(values)),
                        'max_ms': ms(max(values)), 'n': len(values)}
    return out


def bid_carriers(tree):
    """BrowserGym's roledescription/description BID carrier, as in the pipeline."""
    from browsergym.core.observation import extract_data_items_from_aria
    for node in tree['nodes']:
        items = []
        for i, prop in enumerate(node.get('properties', [])):
            if prop['name'] == 'roledescription':
                items, value = extract_data_items_from_aria(prop['value']['value'])
                prop['value']['value'] = value
                if value == '':
                    del node['properties'][i]
                break
        if 'description' in node:
            fallback, value = extract_data_items_from_aria(node['description']['value'])
            node['description']['value'] = value
            if value == '':
                del node['description']
            if not items:
                items = fallback
        if items:
            (node['browsergym_id'],) = items
    return tree


def raw_ax(page, env, *, mark, depth=None):
    from browsergym.core.observation import _pre_extract, _post_extract
    from intent_browser.cdp_json import send_json
    timing = {}
    start = time.perf_counter()
    if mark:
        _pre_extract(page, tags_to_mark=env.tags_to_mark)
        timing['mark'] = time.perf_counter() - start
    cdp = page.context.new_cdp_session(page)
    try:
        t = time.perf_counter()
        tree = send_json(cdp, 'Accessibility.getFullAXTree', {} if depth is None else {'depth': depth})
        timing['cdp'] = time.perf_counter() - t
    finally:
        t = time.perf_counter()
        cdp.detach()
        if mark:
            _post_extract(page)
        timing['cleanup'] = time.perf_counter() - t
    if mark:
        t = time.perf_counter()
        bid_carriers(tree)
        timing['bids'] = time.perf_counter() - t
    timing['total'] = time.perf_counter() - start
    return tree, timing


def observation_for(page, tree, goal):
    return {'url': page.url, 'axtree_object': tree, 'open_pages_urls': [page.url],
            'goal': goal, 'last_action_error': ''}


def process(config, obs, budget):
    """Current presentation: fresh AXContext (initial view), stage=False."""
    from intent_browser.ax_context import AXContext
    context = AXContext(config)
    t = time.perf_counter()
    context.capture(obs)
    captured = time.perf_counter()
    result = context.page_update(None, budget=budget, stage=False)
    done = time.perf_counter()
    return result, {'capture': captured - t, 'pack': done - captured, 'total': done - t,
                    'useful_nodes': len(context.nodes), 'items': len(result['items'])}


def useful_semantics(config, tree):
    """Indexed (useful) AX nodes without volatile BIDs, for marked/unmarked parity."""
    from intent_browser.ax_explorer import AXExplorer
    explorer = AXExplorer(config)
    explorer.capture({'url': 'about:parity', 'axtree_object': tree, 'open_pages_urls': []})
    return [(n['role'], n['name'], n['value'], json.dumps(n['properties'], sort_keys=True),
             n['parent'], tuple(n['children']), n['backend_identity']) for n in explorer.nodes]


SKIP_ROLES = ('none', 'LineBreak', 'InlineTextBox')


def lazy_overview(tree, tokenizer, budget, url):
    """Prototype: breadth-first over useful nodes, expanded on demand, stop at budget.

    Same node filter and item fields as AXContext's initial overview. Each item is
    tokenized once (additive estimate), then the final result is counted exactly.
    Refs here are placeholders; total_entries is unknown without a full walk.
    """
    start = time.perf_counter()
    raw = tree['nodes']
    by_id = {n['nodeId']: n for n in raw}

    def fields(node):
        role = str(node.get('role', {}).get('value', ''))
        name = str(node.get('name', {}).get('value', ''))
        value = str(node.get('value', {}).get('value', ''))
        props = {p['name']: p['value']['value'] for p in node.get('properties', [])
                 if isinstance(p.get('value'), dict) and 'value' in p['value']
                 and p.get('name') not in ('focusable', 'settable', 'editable')}
        return role, name, value, props

    def useful(node, parent_name):
        role, name, value, props = fields(node)
        if node.get('ignored', False) or role in SKIP_ROLES:
            return False
        if role == 'generic' and not name and not value and not props:
            return False
        if role == 'StaticText' and parent_name is not None and name and name in parent_name:
            return False
        return True

    def useful_children(raw_id, parent_name):
        out = []
        stack = list(reversed(by_id[raw_id].get('childIds', [])))
        seen = set()
        while stack:
            child = stack.pop()
            if child in seen or child not in by_id:
                continue
            seen.add(child)
            node = by_id[child]
            if useful(node, parent_name):
                out.append(child)
            else:
                stack.extend(reversed(node.get('childIds', [])))
        return out

    def clip(text, cap):
        ids = tokenizer.encode(text, add_special_tokens=False).ids
        if len(ids) <= cap:
            return text, False
        return tokenizer.decode(ids[:cap], skip_special_tokens=False) + '…', True

    root = raw[0]['nodeId']
    refs = {root: 'd1n0'}
    queue = [(root, None, 0)]
    envelope = {'tool': 'ax_changes', 'document': 'd1', 'url': url, 'roots': ['d1n0'],
                'initial_overview': True,
                'coverage': 'Structural overview; expand nodes or search for omitted content.',
                'offset': 0, 'total_entries': None, 'next_offset': None}
    used = len(tokenizer.encode(json.dumps(envelope, ensure_ascii=False, sort_keys=True),
                                add_special_tokens=False).ids)
    items = []
    while queue:
        raw_id, parent_ref, position = queue.pop(0)
        node = by_id[raw_id]
        role, name, value, props = fields(node)
        children = useful_children(raw_id, name)
        for i, child in enumerate(children):
            refs.setdefault(child, f'd1n{len(refs)}')
            queue.append((child, refs[raw_id], i))
        item = {'ref': refs[raw_id], 'role': role}
        if parent_ref is not None:
            item['parent'] = parent_ref
        item['position'] = position
        if node.get('browsergym_id') is not None:
            item['bid'] = node['browsergym_id']
        for key, text in (('name', name), ('value', value)):
            if text:
                item[key], short = clip(text, 60)
                if short:
                    item[key + '_partial'] = True
        if props:
            item['state'] = props
        if children:
            item['children'] = len(children)
        cost = len(tokenizer.encode(json.dumps(item, ensure_ascii=False, sort_keys=True),
                                    add_special_tokens=False).ids) + 1
        if used + cost > budget - 70:
            break
        used += cost
        items.append(item)
    result = {**envelope, 'items': items, 'next_offset': len(items) if queue else None,
              **({'budget_limited': True} if queue else {})}
    exact = len(tokenizer.encode(json.dumps(result, ensure_ascii=False, sort_keys=True),
                                 add_special_tokens=False).ids)
    while exact > budget and result['items']:
        result['items'].pop()
        exact = len(tokenizer.encode(json.dumps(result, ensure_ascii=False, sort_keys=True),
                                     add_special_tokens=False).ids)
    return result, {'total': time.perf_counter() - start, 'items': len(result['items']),
                    'exact_tokens': exact, 'estimated_tokens': used}


def resolve_bids(page, tree, items_backend_ids):
    """Timing proxy: resolve BIDs for delivered elements only (preview_bids path)."""
    from intent_browser.preview_bids import assign_preview_bids
    nodes = [n for n in tree['nodes'] if n.get('backendDOMNodeId') in items_backend_ids]
    cdp = page.context.new_cdp_session(page)
    t = time.perf_counter()
    try:
        bids = assign_preview_bids(page, cdp, nodes)
    finally:
        cdp.detach()
    return {'total': time.perf_counter() - t, 'candidates': len(nodes), 'assigned': len(bids)}


def bfs_rpc(page, env, tokenizer, budget):
    """Node-by-node fetch: marked page, getChildAXNodes per expanded node."""
    from browsergym.core.observation import _pre_extract, _post_extract
    start = time.perf_counter()
    _pre_extract(page, tags_to_mark=env.tags_to_mark)
    cdp = page.context.new_cdp_session(page)
    calls = fetched = useful = tokens = 0
    try:
        cdp.send('Accessibility.enable')
        root = cdp.send('Accessibility.getRootAXNode')['node']
        queue = [root]
        while queue and tokens < budget:
            node = queue.pop(0)
            role = node.get('role', {}).get('value', '')
            name = node.get('name', {}).get('value', '')
            if not node.get('ignored') and role not in ('none', 'LineBreak', 'InlineTextBox', 'generic', 'RootWebArea'):
                useful += 1
                entry = json.dumps({'role': role, 'name': name[:240]}, ensure_ascii=False)
                tokens += len(tokenizer.encode(entry, add_special_tokens=False).ids) + 8
            if node.get('childIds'):
                calls += 1
                children = cdp.send('Accessibility.getChildAXNodes', {'id': node['nodeId']})['nodes']
                fetched += len(children)
                queue.extend(children)
    finally:
        cdp.detach()
        _post_extract(page)
    return {'total': time.perf_counter() - start, 'rpc_calls': calls, 'fetched_nodes': fetched,
            'useful_nodes': useful, 'approx_tokens': tokens}


def native(env, *, screenshots, raw):
    from intent_browser.cdp_json import capture_json
    t = time.perf_counter()
    base = env.unwrapped
    if raw:
        obs = capture_json(base._get_obs, screenshots=screenshots)
    else:
        if screenshots:
            obs = base._get_obs()
        else:
            import browsergym.core.env as genv
            original = genv.extract_screenshot
            genv.extract_screenshot = lambda page: None
            try:
                obs = base._get_obs()
            finally:
                genv.extract_screenshot = original
    return obs, {'total': time.perf_counter() - t, 'raw_nodes': len(obs['axtree_object']['nodes'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recipe', required=True)
    parser.add_argument('--kind', required=True)
    parser.add_argument('--urls', required=True, help='JSON list of page URLs to visit')
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--budgets', default='512,1000,2000,4000')
    parser.add_argument('--depths', default='3,4,6,8,12,16')
    args = parser.parse_args()
    budgets = [int(b) for b in args.budgets.split(',')]
    depths = [int(d) for d in args.depths.split(',')]
    urls = json.loads(Path(args.urls).read_text())
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)

    from environments.website_world.saved_answer_registry import saved_episode
    import intent_browser
    from tokenizers import Tokenizer
    from intent_browser.standard_profile import tokenizer_path
    tokenizer = Tokenizer.from_file(tokenizer_path())
    report = {'schema': 'overview-extraction-benchmark-v1', 'recipe': args.recipe, 'kind': args.kind,
              'intent_browser': intent_browser.__file__, 'python': sys.version, 'machine': platform.platform(),
              'cpu_affinity': sorted(os.sched_getaffinity(0)), 'repeats': args.repeats,
              'scope': 'Model-free, single episode, sequential; component timings, not whole-turn latency.',
              'pages': []}
    Episode = saved_episode(args.kind)
    with Episode(Path(args.recipe)) as episode:
        config = episode.profile.ax_config
        env = episode.task.make_env(None)
        try:
            obs, _ = env.reset(seed=0)
            goal = obs.get('goal', '')
            page = env.unwrapped.page
            report['start_url'] = page.url
            for url in urls:
                page.goto(url)
                page.wait_for_load_state('domcontentloaded')
                time.sleep(0.5)  # let the SPA route render; this wait is not timed
                record = {'url': page.url, 'rows': {}}
                rows = {}
                def add(name, value):
                    rows.setdefault(name, []).append(value)
                for repeat in range(args.repeats):
                    # Rotate order so no strategy always runs first after navigation.
                    order = ['native_public_shot', 'native_raw_noshot', 'ax_marked', 'ax_unmarked', 'depths', 'bfs']
                    order = order[repeat % len(order):] + order[:repeat % len(order)]
                    for step in order:
                        if step == 'native_public_shot':
                            _, timing = native(env, screenshots=True, raw=False)
                            add(step, timing)
                        elif step == 'native_raw_noshot':
                            _, timing = native(env, screenshots=False, raw=True)
                            add(step, timing)
                        elif step == 'ax_marked':
                            tree, timing = raw_ax(page, env.unwrapped, mark=True)
                            timing['raw_nodes'] = len(tree['nodes'])
                            add(step, timing)
                            for budget in budgets:
                                result, ptiming = process(config, observation_for(page, tree, goal), budget)
                                add(f'process_{budget}', ptiming)
                                if repeat == 0:
                                    record.setdefault('overview_items', {})[budget] = {
                                        'items': len(result['items']), 'complete': result.get('next_offset') is None,
                                        'tokens': len(tokenizer.encode(json.dumps(result, ensure_ascii=False, sort_keys=True), add_special_tokens=False).ids)}
                        elif step == 'ax_unmarked':
                            tree, timing = raw_ax(page, env.unwrapped, mark=False)
                            add(step, timing)
                            for budget in budgets:
                                result, ltiming = lazy_overview(tree, tokenizer, budget, page.url)
                                add(f'lazy_{budget}', ltiming)
                                if repeat == 0 and budget == 1000:
                                    current, _ = process(config, observation_for(page, tree, goal), budget)
                                    strip = lambda item: {k: v for k, v in item.items() if k not in ('ref', 'parent')}
                                    record['lazy_matches_current_1000'] = {
                                        'lazy_items': len(result['items']), 'current_items': len(current['items']),
                                        'prefix_equal': [strip(i) for i in result['items']] ==
                                            [strip(i) for i in current['items'][:len(result['items'])]]}
                            for depth in (6, 8):
                                dtree, dtiming = raw_ax(page, env.unwrapped, mark=False, depth=depth)
                                dtiming['raw_nodes'] = len(dtree['nodes'])
                                add(f'ax_unmarked_depth_{depth}', dtiming)
                            backend = {n.get('backendDOMNodeId') for n in tree['nodes'][:200]}
                            add('resolve_bids_200', resolve_bids(page, tree, backend))
                            if repeat == 0:
                                marked, _ = raw_ax(page, env.unwrapped, mark=True)
                                a, b = useful_semantics(config, marked), useful_semantics(config, tree)
                                record['marked_unmarked_useful_equal'] = a == b
                                record['marked_unmarked_useful_counts'] = [len(a), len(b)]
                                if a != b:
                                    import difflib
                                    sa, sb = [repr(x[:4]) for x in a], [repr(x[:4]) for x in b]
                                    record['marked_unmarked_diff'] = [line for line in difflib.unified_diff(sa, sb, 'marked', 'unmarked', n=1, lineterm='')][:40]
                        elif step == 'depths':
                            for depth in depths:
                                tree, timing = raw_ax(page, env.unwrapped, mark=True, depth=depth)
                                timing['raw_nodes'] = len(tree['nodes'])
                                add(f'ax_depth_{depth}', timing)
                                if repeat == 0:
                                    result, _ = process(config, observation_for(page, tree, goal), 1000)
                                    record.setdefault('depth_overview_1000', {})[depth] = {
                                        'raw_nodes': len(tree['nodes']), 'items': len(result['items']),
                                        'budget_filled': result.get('budget_limited', False)}
                        elif step == 'bfs':
                            for budget in (1000,):
                                add(f'bfs_rpc_{budget}', bfs_rpc(page, env.unwrapped, tokenizer, budget))
                record['summary'] = {name: summarize(values) for name, values in rows.items()}
                report['pages'].append(record)
                print(json.dumps({'url': record['url'],
                    **{name: s.get('total', {}).get('median_ms') for name, s in record['summary'].items()}}), flush=True)
        finally:
            env.close()
    (out / 'report.json').write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
