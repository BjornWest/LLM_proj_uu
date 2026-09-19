"""V2 additionally rejects nonfatal native action errors as site-readiness evidence."""
from .evidence import assess as assess_v1

def assess(stage,entries,error=None,action_error_count=0):
 result=assess_v1(stage,entries,error)
 result['action_error_count']=action_error_count
 if type(action_error_count)is not int or action_error_count<0:
  result['preflight_status']='unknown';result['dependency_errors'].append({'native_action_error_count_invalid':True})
 elif action_error_count:
  result['preflight_status']='unknown';result['dependency_errors'].append({'native_action_errors':action_error_count})
 return result
