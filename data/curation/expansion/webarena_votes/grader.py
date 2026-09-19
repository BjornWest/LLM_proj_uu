"""Derived authenticated final server/DB vote agreement; original native grade separate."""
from html.parser import HTMLParser
class Votes(HTMLParser):
 def __init__(self):super().__init__();self.forms=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='form' and a.get('data-vote-route-value')=='submission_vote':self.forms.append({'id':a.get('data-vote-id-value'),'choice':a.get('data-vote-choice-value'),'action':a.get('action')})
def parse_votes(html):p=Votes();p.feed(html);return p.forms
def judge(evidence,target,username):
 r={'task_completed':None,'source_target_upvoted':None,'authorization_satisfied':None,'reason':'Final independent evidence unavailable'}
 if evidence is None:return r
 if evidence.get('status')!=200:return {**r,'reason':'Final forum read failed'}
 forms=evidence['forms'];db=evidence['db'];votes=db['vote']
 if not forms or forms[0]['id']!=str(target) or len(db['ui_newest'])!=1 or db['ui_newest'][0]['id']!=target:return {**r,'reason':'Original target differs from current site New order'}
 selected=[f for f in forms if f['id']==str(target)]
 if len(selected)!=1 or selected[0]['choice'] not in ('-1','0','1') or len(votes)>1:return {**r,'reason':'Missing or ambiguous vote evidence'}
 if votes and (votes[0]['username']!=username or type(votes[0]['upvote'])is not bool):return {**r,'reason':'Unexpected vote owner/type'}
 db_choice=0 if not votes else 1 if votes[0]['upvote'] else -1
 if int(selected[0]['choice'])!=db_choice:return {**r,'reason':'Authenticated HTML and database disagree'}
 latest=db.get('timestamp_newest',[]);target_rows=db.get('target',[])
 if len(latest)!=1 or len(target_rows)!=1:return {**r,'reason':'Creation-time comparison unavailable'}
 agrees=target_rows[0]['timestamp']==latest[0]['timestamp']
 return {**r,'task_completed':(db_choice==1) if agrees else None,'source_target_upvoted':db_choice==1,'reason':'Independent final vote verified; original newest goal ambiguous' if not agrees else 'Independent final vote and newest target verified','final_choice':db_choice,'chronological_target_agreement':agrees}
