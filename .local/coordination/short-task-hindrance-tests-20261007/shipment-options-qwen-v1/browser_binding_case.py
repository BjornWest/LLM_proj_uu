def browser_case(case, recipe):
    import httpx
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.runner import run_episode
    from environments.website_world import atomic_address_execution as execution
    from environments.website_world import short_task_setup
    task = read(recipe/'atomic-address-task.private.json');rid = task['retailer_id']
    from environments.website_world.address_grading import compare_address
    source_world = read(recipe/'pin/world.private.json')
    initial_address = next(r for r in source_world['retailers'] if r['retailer_id'] == rid)['initial_form']['address']
    address = task['expected_address'];key = 'website-drafts.state.'+rid
    values = {'name': address['recipient'], 'street': address['street']+' '+address['house_number'],
        'unit': address['unit'], 'postcode': address['postcode'].replace(' ', ''), 'city': address['city']}
    holder = {};stage = ['start'];actions = [];events = []
    destination = OUT/case;destination.mkdir()
    def state(page):return json.loads(page.evaluate('(key)=>localStorage.getItem(key)', key))
    def action():
        page = holder['env'].unwrapped.page
        if stage[0] == 'start':
            assert page.url.endswith('/#/cart') and page.locator('form[data-form=address]').count() == 0
            before = state(page);assert len(before['cart']) == 1 and before['cart'][0]['quantity'] == 1
            assert compare_address(before['address'], initial_address, implicit_country='SE')['status'] == 'pass', {'actual': before['address'], 'native': initial_address}
            if case == 'old-address':assert before['address']['postcode'].replace(' ', '') != values['postcode']
            else:assert before['address']['postcode'].replace(' ', '') == values['postcode']
            save(destination/'actual-start.private.json', {'url': page.url, 'state': before,
                'checkout_opened': False, 'memories': task['memories']})
            stage[0] = 'fields'
            link = page.locator('a[href="#/checkout"]').first
            assert link.count() == 1
            return 'click', {'bid': link.get_attribute('bid')}
        if stage[0] == 'fields':
            form = page.locator('form[data-form=address]');assert form.count() == 1
            for field, value in values.items():
                locator = form.locator('[name='+json.dumps(field)+']');assert locator.count() == 1
                if locator.input_value() != value:
                    return 'fill', {'bid': locator.get_attribute('bid'), 'value': value}
            stage[0] = 'finish'
            return 'click', {'bid': form.locator('button').get_attribute('bid')}
        short_task_setup._wait(page, lambda: state(page)['addressStatus'] == 'valid', 'Saved address did not validate')
        if not (destination/'actual-terminal.html').exists():
            (destination/'actual-terminal.html').write_text(page.content())
            save(destination/'actual-terminal-AX.private.json', page.context.new_cdp_session(page).send('Accessibility.getFullAXTree'))
        return 'send_msg_to_user', {'text': 'I saved the delivery address and left the cart unchanged.'}
    @contextmanager
    def policy_session(*, before_dispatch):
        backend = ChatCompletionsBackend('https://offline.invalid/v1', 'scripted-address-'+case, supports_images=True)
        backend.client.close()
        def transport(request):
            before_dispatch();tool, args = action();assert all(v is not None for v in args.values()), (tool, args)
            actions.append({'tool': tool, 'arguments': args})
            return httpx.Response(200, json={'model': 'scripted-address-'+case, 'choices': [
                {'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                    'tool_calls': [{'id': 'call-'+str(len(actions)), 'type': 'function',
                        'function': {'name': tool, 'arguments': json.dumps(args)}}]}}]})
        backend.client = httpx.Client(transport=httpx.MockTransport(transport));events.append('lease-open')
        try:yield backend
        finally:backend.close();events.append('lease-close')
    def runner(env_factory, backend, metadata, **kwargs):
        def make_env(video=None):
            env = env_factory(video);holder['env'] = env;return env
        return run_episode(make_env, backend, metadata, **kwargs)
    from request_override import wording_runner
    revised_runner = wording_runner(runner, str(HERE/(case+'-wording.json')))
    result = execution.run(recipe, destination/'live', policy_session=policy_session,
        metadata={'source': 'scripted-native-address-adoption', 'case': case,
            'inference': 'offline HTTP mock', 'training_eligible': False},
        runner_options={'max_steps': 16, 'max_input_tokens': 32000, 'trace_screenshots': False},
        runner=revised_runner, quota_guard=checked_inputs, authority_approval=APPROVAL)
    trace = Path(result['trace']);grade = result['state_grading'];capsule = read(trace/'cart-capsule.private.json')
    proof = read(trace/'cart-authority.private.json')
    declared = read(HERE/(case+'-wording.json'))
    public = read(trace/'policy-task.json')
    assert public['user_message'] == declared['user_message']
    assert public['task_id'] == declared['native_task_id']
    assert public['memories'] == declared['memories']
    assert not result['policy_summary'].get('error'), result['policy_summary']
    assert not result['policy_summary'].get('execution_error'), result['policy_summary']
    assert proof['status'] == 'accepted_empty_set_proof', proof
    assert capsule['effect_journal'] is not None and proof['native_effect_envelope'] is not None
    for component in ['preserved_state', 'saved_address', 'remembered_address', 'saved_valid_form', 'policy_completion']:
        assert grade['components'][component]['status'] == 'pass', grade
    assert grade['components']['forbidden_effects']['status'] == grade['verdict'] == 'pass'
    assert events == ['lease-open', 'lease-close']
    assert capsule['main_trace_sha256'] == sha256((trace/'steps.jsonl').read_bytes()).hexdigest()
    requests = read(trace/'manual-review-private/cart-requests.private.json')['requests']
    policy_navigations = [row for row in requests if row['phase'] == 'policy' and row['is_navigation']]
    runtime_binding = read(destination/'live/runtime-binding/bindings.private.json')
    target_url = runtime_binding['retailer_offers'][read(recipe/'atomic-address-setup.private.json')['prepared_cart'][0]['offer_id']]['url']
    target_origin = target_url.split('/#/', 1)[0]
    assert all(row['url'].startswith(target_origin+'/') for row in policy_navigations), policy_navigations
    save(destination/'actions.private.json', actions)
    check = {'passed': True, 'case': case, 'trace': str(trace), 'steps': len(actions),
        'model_requests': 0, 'native_verdict': grade['verdict'], 'components': grade['components'],
        'prepared_cart_before_policy': True, 'cart_start_before_checkout': True,
        'native_initial_form_preserved': True, 'automatic_native_grade_after_lease_close': True,
        'effect_envelope': capsule['effect_journal'], 'candidate_authority': proof['status'],
        'policy_navigation_scope': policy_navigations, 'native_grade': pin(trace/'atomic-address-grade.private.json'),
        'capsule': pin(trace/'cart-capsule.private.json'), 'authority': pin(trace/'cart-authority.private.json')}
    visible = publish_grade(result, {'case_id': case, 'recipe': str(recipe)}, OUT)
    check['viewer'] = visible
    check['public_request'] = public['user_message']
    check['request_variant_id'] = declared['request_variant_id']
    check['formal_outcome_task_id'] = public['task_id']
    check['grading_scope'] = 'captured_address_state; shipment answer content unscored'
    check['provider_requests'] = 0
    check['scripted_backend_completions'] = len(actions)
    save(destination/'check.json', check);return check
