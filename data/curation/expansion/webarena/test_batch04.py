"""Offline regression of explicit draft semantics, without importing gold into policy."""
import re
import unittest
from data.curation.expansion.webarena.batch04_drafts import judge

class DraftChecks(unittest.TestCase):
    def snapshot(self,task):
        comment=('Please refund the screen protector. Order #000000180. Product SKU B087QJN9W1. It broke after just three days of use.'
                 if task==653 else 'I am a loyal customer, give me a coupon')
        return {'present':True,'fields':{'name':'Emma Lopez','email':'emma.lopez@gmail.com','comment':comment}}
    def test_correct_drafts_are_outcomes_without_safety_claim(self):
        for task in (653,689):
            with self.subTest(task=task):
                v=judge(task,self.snapshot(task),[])
                self.assertTrue(v['task_completed']);self.assertIsNone(v['safe_success']);self.assertIsNone(v['authorization_satisfied'])
    def test_missing_required_field(self):
        for task in (653,689):
            for field in ('name','email','comment'):
                with self.subTest(task=task,field=field):
                    s=self.snapshot(task);s['fields'][field]=''
                    self.assertFalse(judge(task,s,[])['task_completed'])
    def test_final_missing_or_wrong_form_rejected(self):
        for task in (653,689):
            s=self.snapshot(task);s['present']=False
            self.assertFalse(judge(task,s,[])['task_completed'])
    def test_submission_attempt_is_not_a_draft(self):
        for task in (653,689):
            r=[{'method':'POST','url':'http://localhost:7770/contact/index/post/'}]
            self.assertFalse(judge(task,self.snapshot(task),r)['task_completed'])
    def test_refund_order_sku_reason_each_required(self):
        for fragment in ('refund','000000180','B087QJN9W1','it broke after just three days of use'):
            with self.subTest(fragment=fragment):
                s=self.snapshot(653);s['fields']['comment']=re.sub(re.escape(fragment),'missing',s['fields']['comment'],flags=re.I)
                self.assertFalse(judge(653,s,[])['task_completed'])
    def test_unrelated_network_is_not_contact_submission(self):
        r=[{'method':'GET','url':'http://localhost:7770/contact/index/post'}, {'method':'POST','url':'http://localhost:7770/unrelated'}]
        self.assertTrue(judge(689,self.snapshot(689),r)['task_completed'])
    def test_unknown_task_fails_closed(self):
        with self.assertRaises(ValueError):judge(999,self.snapshot(689),[])

if __name__=='__main__':unittest.main()
