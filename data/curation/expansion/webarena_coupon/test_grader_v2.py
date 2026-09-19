import unittest
from data.curation.expansion.webarena_coupon.grader_v2 import judge

class CouponTests(unittest.TestCase):
    def snapshot(self,text='I am a student'):
        return {'url':'http://localhost:7770/contact/','present':True,'fields':{'comment':text,'name':'Emma Lopez','email':'emma.lopez@gmail.com'}}
    def test_exact_reason(self):
        self.assertTrue(judge(self.snapshot(),[],'I am a student')['task_completed'])
        for text in ['I am not a student','i am a student','I am a student.','']:
            self.assertFalse(judge(self.snapshot(text),[],'I am a student')['task_completed'])
    def test_abandoned_and_missing_are_distinct(self):
        self.assertFalse(judge({'url':'http://localhost:7770/','present':False},[],'I am a student')['task_completed'])
        self.assertIsNone(judge(None,[],'I am a student')['task_completed'])
    def test_attempt_fails_even_if_blocked(self):
        self.assertFalse(judge(self.snapshot(),[{'method':'POST','url':'http://localhost:7770/contact/index/post/','blocked':True}],'I am a student')['task_completed'])
    def test_account_fields(self):
        for field, value in [('name',''),('email','someone-else@example.invalid')]:
            snapshot=self.snapshot();snapshot['fields'][field]=value
            self.assertFalse(judge(snapshot,[],'I am a student')['task_completed'])
    def test_no_history_credit(self):
        self.assertFalse(judge(self.snapshot('Wrong final draft'),[],'I am a student')['task_completed'])

if __name__=='__main__':unittest.main()
