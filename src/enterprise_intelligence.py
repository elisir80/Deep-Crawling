"""Explainable enterprise SEO intelligence built from local snapshots."""
from collections import defaultdict
from datetime import datetime
import math

def causal_graph(events):
    nodes={}; edges=[]
    for event in events or []:
        for key in ('change','ranking','traffic','conversion'):
            value=event.get(key)
            if value is not None:
                node=f'{key}:{value}'; nodes[node]={'id':node,'type':key,'value':value}
        if event.get('change') and event.get('ranking'):
            edges.append({'from':f"change:{event['change']}",'to':f"ranking:{event['ranking']}",'relation':'preceded'})
        if event.get('ranking') and event.get('traffic'):
            edges.append({'from':f"ranking:{event['ranking']}",'to':f"traffic:{event['traffic']}",'relation':'correlated'})
        if event.get('traffic') and event.get('conversion'):
            edges.append({'from':f"traffic:{event['traffic']}",'to':f"conversion:{event['conversion']}",'relation':'correlated'})
    return {'nodes':list(nodes.values()),'edges':edges}

def anomaly_explainer(current, baseline, events=None):
    findings=[]
    for key,value in (current or {}).items():
        old=float((baseline or {}).get(key,value) or 0)
        try: delta=float(value)-old
        except (TypeError,ValueError): continue
        if abs(delta)>max(1,abs(old)*.2):
            causes=[event for event in events or [] if event.get('metric')==key or event.get('date')]
            findings.append({'metric':key,'delta':round(delta,4),'direction':'up' if delta>0 else 'down',
                             'possible_causes':causes,'confidence':round(min(1,abs(delta)/max(abs(old),1)),2)})
    return {'anomalies':findings,'root_cause_candidates':[x for f in findings for x in f['possible_causes']]}

def observability(samples):
    return {'series':samples or [],'latest':(samples or [{}])[-1],
            'alerts':[{'metric':key,'value':value,'severity':'warning'} for key,value in ((samples or [{}])[-1]).items()
                      if isinstance(value,(int,float)) and value<0]}

def intent_drift(previous, current):
    old={x.get('keyword'):x.get('intent') for x in previous or []}; changes=[]
    for item in current or []:
        if item.get('keyword') in old and old[item['keyword']] != item.get('intent'):
            changes.append({'keyword':item['keyword'],'before':old[item['keyword']],'after':item.get('intent')})
    return {'drifts':changes,'count':len(changes)}

def query_satisfaction(rows):
    output=[]
    for row in rows or []:
        ctr=float(row.get('ctr',0) or 0); position=float(row.get('position',100) or 100)
        bounce=float(row.get('bounce_rate',0) or 0); conversion=float(row.get('conversion_rate',0) or 0)
        score=max(0,min(100,ctr*100*.35+(1/min(position,100))*100*.25+(1-bounce)*100*.2+conversion*100*.2))
        output.append({'query':row.get('query'),'url':row.get('url'),'score':round(score,2)})
    return output

def zero_click_visibility(rows):
    return [{'query':row.get('query'),'zero_click':bool(row.get('featured_snippet') or row.get('paa') or row.get('ai_overview')),
             'visibility_score':sum(bool(row.get(key)) for key in ('featured_snippet','paa','ai_overview'))*33.33} for row in rows or []]

def misinformation_check(entity, claims, trusted_facts):
    facts={str(x).lower() for x in trusted_facts or []}
    conflicts=[claim for claim in claims or [] if str(claim).lower() not in facts]
    return {'entity':entity,'conflicts':conflicts,'risk':'high' if conflicts else 'low'}

def freshness_prediction(rows):
    result=[]
    for row in rows or []:
        age=float(row.get('age_days',0) or 0); traffic_delta=float(row.get('traffic_delta',0) or 0)
        probability=min(1,max(0,age/730 + max(0,-traffic_delta)/100))
        result.append({'url':row.get('url'),'decay_probability':round(probability,3),'action':'refresh' if probability>.5 else 'monitor'})
    return result
