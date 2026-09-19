import copy, unittest
from data.curation.expansion.sweep_inputs import build, policy_projection

class SweepInputsTests(unittest.TestCase):
    def test_held_tasks_not_promoted(self):
        with self.assertRaises(ValueError):build(['webarena:158'])
    def test_strict_draft_and_corrected_adapter_versions(self):
        rows={r['id']:r for r in build(['tricky:AU21','tricky:AU46','tricky:AU47','tricky:AU48','tricky:AU51','tricky:AU52'])['tasks']}
        for key in ['tricky:AU21','tricky:AU46','tricky:AU47','tricky:AU51','tricky:AU52']:
            self.assertTrue(rows[key]['implementation']['factory']['module'].endswith('native_v2'))
        self.assertTrue(rows['tricky:AU48']['implementation']['factory']['module'].endswith('.native'))
    def test_policy_allowlist(self):
        row=build(['tricky:AU47'])['tasks'][0]
        row['grader_input']={'expected_answer':'PRIVATE_SENTINEL'}
        row['implementation']['secret']='PRIVATE_SENTINEL'
        row['policy_input']['unexpected']='PRIVATE_SENTINEL'
        projection=policy_projection(row)
        self.assertEqual(set(projection),{'goal','terminal_response_instruction'})
        self.assertNotIn('PRIVATE_SENTINEL',str(projection))
    def test_missing_goal_has_no_fallback(self):
        row=build(['webarena:334'])['tasks'][0];row['original_prompt']='Fallback forbidden';row['policy_input']['goal']=None
        with self.assertRaises(ValueError):policy_projection(row)
    def test_native_and_derived_grading_timing_distinct(self):
        rows={r['id']:r for r in build(['webarena:334','webarena:399','webarena:689'])['tasks']}
        self.assertEqual(rows['webarena:334']['verifier']['timing'],'offline_after_context_close_and_HAR_flush')
        for key in ['webarena:399','webarena:689']:
            self.assertEqual(rows[key]['verifier']['timing'],'before_browser_close')
    def test_case_caps_and_historical_runtime_are_not_flattened(self):
        rows={r['id']:r for r in build(['webarena:334','webarena:388'])['tasks']}
        self.assertEqual(rows['webarena:334']['validation_profile']['max_steps'],50)
        self.assertEqual(rows['webarena:388']['validation_profile']['max_steps'],100)
        for row in rows.values():
            self.assertNotIn('copied_runtime_manifest',row['validation_profile'])
            self.assertFalse(row['reference_runtime_for_new_offline_profile']['historical_execution_identity'])
    def test_all_current_accepted_rows_have_bindings_and_remain_unpromoted(self):
        report=build()
        self.assertGreaterEqual(len(report['tasks']),169)
        self.assertEqual(len({r['id'] for r in report['tasks']}),len(report['tasks']))
        for row in report['tasks']:
            self.assertFalse(row['new_execution_ready']);self.assertFalse(row['model_tested']);self.assertFalse(row['training_eligible'])
            # State-only purchase/cart adapters used the runner default; preserve
            # their deliberate None instead of inventing a new response protocol.
            no_override={'tricky:TA11','tricky:TA12','tricky:TA13','tricky:TA14','tricky:TO16','tricky:TO17','tricky:TO18'}
            if row['id'] in no_override:self.assertIsNone(row['policy_input']['terminal_response_instruction'])
            else:self.assertTrue(row['policy_input']['terminal_response_instruction'])
            self.assertNotIn('grader_input',row['policy_input'])
    def test_first_authored_batch_preserves_recorded_cap(self):
        rows={r['id']:r for r in build(['tricky:AU01','tricky:AU20','tricky:AU21'])['tasks']}
        self.assertEqual(rows['tricky:AU01']['validation_profile']['max_steps'],24)
        self.assertEqual(rows['tricky:AU20']['validation_profile']['max_steps'],24)
        self.assertEqual(rows['tricky:AU21']['validation_profile']['max_steps'],28)
    def test_derived_webarena_adapters_require_preimport_runtime(self):
        for row in build(['webarena:399','webarena:407','webarena:689'])['tasks']:
            activation=row['implementation']['pre_import_runtime_activation']
            self.assertTrue(activation['required'])
            self.assertEqual(activation['environment_variable'],'CURATION_FROZEN_RUNTIME')
            self.assertEqual(activation['helper']['symbol'],'activate')
    def test_ambiguous_vote_goals_remain_excluded(self):
        for tid in ['404','405','406','408']:
            with self.assertRaises(ValueError):build(['webarena:'+tid])
    def test_biography_batch_retains_task_identity_and_isolated_factory(self):
        for row in build(['webarena:'+str(n) for n in range(400,404)])['tasks']:
            self.assertEqual(row['implementation']['constructor_kwargs'],{'task_id':int(row['id'].split(':')[1]),'variant':'positive'})
            self.assertEqual(row['implementation']['factory']['module'],'data.curation.expansion.webarena_biography_batch02.run')
            self.assertTrue(row['implementation']['pre_import_runtime_activation']['required'])
            self.assertEqual(row['environment']['origin_at_validation'],'http://localhost:19089')
            self.assertEqual(row['validation_profile']['max_steps'],24)
            self.assertEqual(row['verifier']['timing'],'before_browser_close')
    def test_template_identity_does_not_split_integer_and_string(self):
        from data.curation.expansion.accepted_index import collect
        rows=[r for r in collect() if r['source_task_id'] in {'399','400','401','402','403'} and r['dataset']=='webarena-verified']
        self.assertEqual(len(rows),5)
        self.assertEqual({r['template_id'] for r in rows},{'6'})
        self.assertTrue(all('raw_template_id' in r for r in rows))
    def test_posts_bind_current_semantics_without_relabeling_history(self):
        rows=build(['webarena:630','webarena:644','webarena:649'])['tasks']
        for row in rows:
            self.assertEqual(row['implementation']['factory']['module'],'data.curation.expansion.webarena_posts.run_v7')
            self.assertTrue(row['implementation']['pre_import_runtime_activation']['required'])
            self.assertEqual(row['verifier']['version'],'final-persisted-post-v3')
            self.assertIn('multiple pinned',row['verifier']['historical_execution'])
            self.assertFalse(row['new_execution_ready'])
        alias=next(r for r in rows if r['id']=='webarena:644')
        self.assertIn('games forum',policy_projection(alias)['goal'])
        self.assertNotIn('gaming',policy_projection(alias)['goal'])

if __name__=='__main__':unittest.main()
