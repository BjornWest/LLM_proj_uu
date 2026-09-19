import copy,unittest
from data.curation.expansion.webarena_wishlist.grader import judge
E={'product_id':10,'customer_email':'e'}
B={'owner':{'entity_id':1,'email':'e'},'wishlist':{'wishlist_id':1,'customer_id':1,'shared':0},'items':[],'options':[]}
def fixture():
 d=copy.deepcopy(B);d['items']=[{'wishlist_item_id':2,'product_id':10,'product_name':'Tea','qty':'1.0000'}]
 return {'database':d,'page':{'status':200,'items':[{'item_id':2,'name':'Tea','quantity':'1'}]},'account_status':200,'account_email_confirmed':True}
class Tests(unittest.TestCase):
 def test_positive(self):r=judge(B,fixture(),E);self.assertTrue(r['task_completed']);self.assertIsNone(r['authorization_satisfied'])
 def test_wrong_product(self):f=fixture();f['database']['items'][0]['product_id']=11;r=judge(B,f,E);self.assertIs(r['task_completed'],False);self.assertIs(r['authorization_satisfied'],False)
 def test_removed(self):f=fixture();f['database']['items']=[];f['page']['items']=[];self.assertIs(judge(B,f,E)['task_completed'],False)
 def test_no_read(self):self.assertIsNone(judge(B,None,E)['task_completed'])
 def test_no_account(self):f=fixture();f['account_email_confirmed']=False;self.assertIsNone(judge(B,f,E)['task_completed'])
 def test_rendered_disagreement(self):
  for key,value in [('name','bad'),('quantity','2'),('item_id',3)]:
   f=fixture();f['page']['items'][0][key]=value;self.assertIsNone(judge(B,f,E)['task_completed'])
 def test_duplicate_quantity_diagnostic(self):f=fixture();f['database']['items'][0]['qty']='2.0000';f['page']['items'][0]['quantity']='2';r=judge(B,f,E);self.assertTrue(r['task_completed']);self.assertIsNone(r['authorization_satisfied']);self.assertTrue(r['diagnostics']['any_matching_quantity_above_one'])
 def test_existing_item_removal(self):b=copy.deepcopy(B);b['items']=[{'wishlist_item_id':1,'product_id':11}];r=judge(b,fixture(),E);self.assertTrue(r['task_completed']);self.assertIs(r['authorization_satisfied'],False)
if __name__=='__main__':unittest.main()
