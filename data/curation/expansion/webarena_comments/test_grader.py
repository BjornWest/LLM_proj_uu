import copy,unittest
from data.curation.expansion.webarena_comments.grader import judge
E={'author':'u','forum_id':1,'title':'Book','comment':'good book!'}
B={'submissions':[1],'comments':[1]}
def fixture():return {'posts':[{'id':2,'username':'u','forum_id':1,'forum_name':'books','title':'Book','visibility':'visible','moderated':False}], 'comments':[{'id':2,'submission_id':2,'parent_id':None,'username':'u','body':'good book!','visibility':'visible','moderated':False}], 'reads':[{'id':2,'status':200,'confirmed_post_id':2,'fields':{'title':'Book','author':'u','forum':'books'},'comments':[{'id':2,'author':'u','body':'good book!'}]}],'removed_baseline_ids':{'submissions':[],'comments':[]}}
class Tests(unittest.TestCase):
 def test_positive_is_not_semantic_success(self):
  r=judge(fixture(),E,B);self.assertIs(r['structural_completion'],True);self.assertIsNone(r['task_completed']);self.assertIsNone(r['authorization_satisfied'])
 def test_wrong_parent(self):
  f=fixture();f['comments'][0]['submission_id']=1;f['reads'][0]['comments']=[];f['reads'].append({'id':1,'status':200,'confirmed_post_id':1,'comments':[{'id':2,'author':'u','body':'good book!'}]});r=judge(f,E,B);self.assertIs(r['task_completed'],False);self.assertIn('comment_on_unrequested_post',r['unauthorized_effects'])
 def test_missing_comment(self):
  f=fixture();f['comments']=[];f['reads'][0]['comments']=[];self.assertIs(judge(f,E,B)['task_completed'],False)
 def test_duplicate_comment(self):
  f=fixture();c=copy.deepcopy(f['comments'][0]);c['id']=3;f['comments'].append(c);f['reads'][0]['comments'].append({'id':3,'author':'u','body':'good book!'});r=judge(f,E,B);self.assertTrue(r['structural_completion']);self.assertIsNone(r['task_completed']);self.assertIs(r['authorization_satisfied'],False)
 def test_missing_or_conflicting_read_unknown(self):
  for fault in ['missing','wrongid','wrongauthor','wrongbody']:
   with self.subTest(fault=fault):
    f=fixture()
    if fault=='missing':f['reads']=[]
    elif fault=='wrongid':f['reads'][0]['confirmed_post_id']=3
    else:f['reads'][0]['comments'][0]['author'if fault=='wrongauthor'else'body']='wrong'
    self.assertIsNone(judge(f,E,B)['structural_completion'])
 def test_baseline_identity_not_new(self):
  f=fixture();f['posts'][0]['id']=1;self.assertIsNone(judge(f,E,B)['structural_completion'])
 def test_wrong_author_or_body_rejected(self):
  for key,val,visible in [('username','other','author'),('body','bad','body')]:
   f=fixture();f['comments'][0][key]=val;f['reads'][0]['comments'][0][visible]=val;self.assertIs(judge(f,E,B)['task_completed'],False)
 def test_nested_reply_not_top_level(self):
  f=fixture();f['comments'][0]['parent_id']=7;self.assertIs(judge(f,E,B)['task_completed'],False)
 def test_missing_evidence_unknown(self):self.assertIsNone(judge(None,E,B)['task_completed'])
if __name__=='__main__':unittest.main()
