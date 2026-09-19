"""Bounded independent subprocess cases; no browser/service access in this module."""
import json,os,re,signal,subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def run_cases(cases,workers,output,command_for_case,timeout=300):
 if type(workers)is not int or not 1<=workers<=4:raise ValueError('workers must be 1–4')
 if len(set(cases))!=len(cases):raise ValueError('Duplicate cases would share output paths')
 if not all(isinstance(c,str) and re.fullmatch('[a-z][a-z0-9-]*',c) for c in cases):raise ValueError('Invalid case path component')
 root=Path(output);root.mkdir(parents=True,exist_ok=False)
 def one(case):
  dest=root/case
  # Child owns exclusive creation of its output; parent records process logs alongside.
  try:
   proc=subprocess.Popen(command_for_case(case,dest),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
   try:stdout,stderr=proc.communicate(timeout=timeout)
   except subprocess.TimeoutExpired:
    os.killpg(proc.pid,signal.SIGTERM)
    try:stdout,stderr=proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
     os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate()
    (root/(case+'.stdout.txt')).write_text(stdout);(root/(case+'.stderr.txt')).write_text(stderr)
    return {'case':case,'returncode':proc.returncode,'report':None,'error':'Child timeout; isolated process group terminated'}
   (root/(case+'.stdout.txt')).write_text(stdout);(root/(case+'.stderr.txt')).write_text(stderr)
   report=dest/'report.json'
   return {'case':case,'returncode':proc.returncode,'report_path':str(report),'report':json.loads(report.read_text()) if report.exists() else None,'error':None if proc.returncode==0 and report.exists() else 'Child failed or no report'}
  except (subprocess.TimeoutExpired,OSError,ValueError) as e:
   return {'case':case,'returncode':None,'report':None,'error':repr(e)}
 with ThreadPoolExecutor(max_workers=workers)as executor:return list(executor.map(one,cases))
