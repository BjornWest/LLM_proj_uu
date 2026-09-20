"""Bounded policy presentation of public browser evidence, never a verifier.

Raw captures remain separate trace artifacts. Prioritize events, remove exact
repeated generic text within a source/window, and report every selection omission.
This changes context selection, not browser execution or the recorded observations.
"""
from copy import deepcopy
import json
import re

IMPORTANT = {'page_announcement','invalid','submit','control_state','input','change',
             'navigation','page_opened','page_closed','frame_detached','dialog_opened','dialog_closed','capture_gap'}


def size(value): return len(json.dumps(value,ensure_ascii=False,sort_keys=True))


class CompactFeedback:
    def __init__(self,max_chars=6000,max_events=10,max_generic=3):
        if max_chars<2400 or max_events<1 or max_generic<0:raise ValueError('Invalid feedback limits')
        self.max_chars,self.max_events,self.max_generic=max_chars,max_events,max_generic

    def describe(self):
        return {'version':'compact-feedback-v1','max_chars':self.max_chars,
                'max_events':self.max_events,'max_generic_text_events':self.max_generic,
                'raw_capture':'retained separately; not replayed to policy',
                'selection':'important events first, exact generic duplicates removed within source/window; bounded AX changes'}

    def __call__(self,value,*,kind):
        if kind in ('search_result','ax_result','delegation_result','helper_result'):return deepcopy(value)  # separate result budgets
        counts={'raw_events':0,'capture_omitted':0,'focus_suppressed':0,'generic_duplicates':0,
                'selection_omitted':0,'truncated_fields':0,'ax_lines_omitted':0}
        def clip(text,limit):
            if isinstance(text,str) and len(text)>limit:
                counts['truncated_fields']+=1;return text[:limit]+'…'
            return text
        out={'scope':'Historical public page evidence; not proof of success. Use current observation IDs.',
             'selection':counts}
        if kind=='browser_update':
            out['kind']='browser_update';groups=[('between_actions',value.get('events',[]))]
            counts['capture_omitted']+=value.get('omitted',0)
            warnings=list(value.get('capture_warnings',[]))
        else:
            out['execution']=value.get('execution');out['error']=clip((value.get('error') or '').split('\n')[0],320) or None
            if 'timeout_context' in value:
                out['timeout_context']=deepcopy(value['timeout_context'])
            for key in ('tool','url_before','url_after'):
                if key in value:out[key]=clip(value[key],500)
            groups=[('between_decision_and_action',value.get('between_decision_and_action',{}).get('events',[])),
                    ('action_window',value.get('page_events',[]))]
            counts['capture_omitted']+=value.get('page_events_omitted',0)+value.get('between_decision_and_action',{}).get('omitted',0)
            warnings=list(value.get('event_capture',{}).get('warnings',[]))
            warnings+=value.get('between_decision_and_action',{}).get('capture_warnings',[])
            for key,label in [('added_or_changed','added'),('removed_or_changed','removed')]:
                lines=value.get(key,[]);kept=[]
                for line in lines:
                    if len(kept)<4 and not re.fullmatch(r"\s*(?:strong|list|listitem|paragraph|generic|Section|group|LabelText) ''\s*",line):
                        kept.append(clip(line,180))
                    else:counts['ax_lines_omitted']+=1
                if kept:out[key]=kept
                counts['ax_lines_omitted']+=value.get('omitted_lines',{}).get(label,0)
        warnings=list(dict.fromkeys(str(w) for w in warnings))
        if warnings:out['capture_warnings']=[clip(w,120) for w in warnings[:4]]
        if len(warnings)>4:out['warnings_omitted']=len(warnings)-4
        seen=set();candidates=[]
        for group,events in groups:
            for event in events:
                counts['raw_events']+=1;k=event.get('kind')
                if k=='focus':counts['focus_suppressed']+=1;continue
                if k=='text_appeared':
                    identity=tuple(event.get(x) for x in ('page','frame','document_id','window','text'))+(group,)
                    if identity in seen:counts['generic_duplicates']+=1;continue
                    seen.add(identity)
                compact={'kind':k,'phase':group}
                for key in ('batch_call','sequence','page','frame','text','label','checked','value','attribute','previous','url','dialog_type','count'):
                    if key in event and event[key] not in ('',None):
                        compact[key]=clip(event[key],300 if key in ('text','url') else 180)
                if event.get('truncated'):compact['capture_truncated']=True
                priority=0 if k in IMPORTANT else 1
                candidates.append((priority,len(candidates),compact))
        selected=[];generic=0
        # Prioritize semantic events and recent generic changes; present selected events chronologically.
        for priority,order,event in sorted(candidates,key=lambda x:(x[0],x[1] if x[0]==0 else -x[1])):
            if len(selected)>=self.max_events or (priority==1 and generic>=self.max_generic):
                counts['selection_omitted']+=1;continue
            if priority==1:generic+=1
            selected.append((priority,order,event))
        def render():out['events']=[e for _,_,e in sorted(selected,key=lambda x:x[1])]
        render()
        while size(out)>self.max_chars and selected:
            # Drop low-priority generic text first (oldest), then newest semantic events; report omissions.
            victim=max(range(len(selected)),key=lambda i:(selected[i][0],-selected[i][1] if selected[i][0] else selected[i][1]))
            selected.pop(victim);counts['selection_omitted']+=1;render()
        while size(out)>self.max_chars and (out.get('removed_or_changed') or out.get('added_or_changed')):
            target=out.get('removed_or_changed') or out['added_or_changed'];target.pop();counts['ax_lines_omitted']+=1
        if size(out)>self.max_chars:raise ValueError('Feedback envelope exceeds configured budget')
        return out
