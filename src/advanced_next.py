"""Second-generation native SEO intelligence and simulators."""
from collections import Counter, defaultdict
from datetime import datetime
import math
import re

def knowledge_graph(rows):
    nodes={}; edges=[]
    for row in rows or []:
        url=row.get('url'); nodes[url]={'id':url,'type':'Page','title':row.get('title','')}
        for entity in row.get('named_entities',[]) or []:
            entity_id='entity:'+str(entity).lower()
            nodes.setdefault(entity_id,{'id':entity_id,'type':'Entity','name':entity})
            edges.append({'from':url,'to':entity_id,'relation':'mentions'})
        for item in row.get('schema_org',[]) if isinstance(row.get('schema_org'),list) else []:
            if isinstance(item,dict) and item.get('@type'):
                entity_id='schema:'+str(item['@type'])
                nodes.setdefault(entity_id,{'id':entity_id,'type':'Schema','name':item['@type']})
                edges.append({'from':url,'to':entity_id,'relation':'typed_as'})
    return {'nodes':list(nodes.values()),'edges':edges}

def topic_gap(rows, target_terms):
    present=set()
    for row in rows or []: present |= set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}',str(row.get('content_text') or '').lower()))
    return [{'topic':term,'covered':term.lower() in present,'priority':'high' if term.lower() not in present else 'covered'} for term in target_terms or []]

def search_intent(keyword, serp_rows=None):
    words=set(re.findall(r'[a-zA-Z0-9À-ÿ]+',str(keyword).lower()))
    if words & {'buy','price','order','service','hire'}: intent='transactional'
    elif words & {'best','review','compare','vs','alternative'}: intent='commercial'
    elif words & {'login','official','brand','contact'}: intent='navigational'
    else: intent='informational'
    features=set(f for row in serp_rows or [] for f in row.get('features',[]))
    return {'keyword':keyword,'intent':intent,'serp_features':sorted(features),'confidence':.75 if words else 0}

def algorithm_update_detector(snapshots, threshold=20):
    if len(snapshots)<2: return {'detected':False,'volatility':0,'affected':[]}
    old=snapshots[-2]; new=snapshots[-1]
    changes=[]
    for key,value in new.items():
        if isinstance(value,(int,float)) and isinstance(old.get(key),(int,float)):
            delta=float(value)-float(old[key])
            if abs(delta)>=threshold: changes.append({'metric':key,'delta':round(delta,2)})
    volatility=round(sum(abs(x['delta']) for x in changes),2)
    return {'detected':bool(changes),'volatility':volatility,'affected':changes,'confidence':min(1,volatility/100)}

def causal_forecast(history, events=None, horizon=6):
    values=[float(x.get('value',0) or 0) for x in history or []]
    baseline=values[-1] if values else 0
    trend=(values[-1]-values[0])/max(len(values)-1,1) if values else 0
    event_penalty=sum(float(e.get('impact',0)) for e in events or [])
    values_out=[round(max(0,baseline+trend*i-event_penalty),2) for i in range(1,horizon+1)]
    return {'baseline':baseline,'trend':round(trend,3),'event_impact':event_penalty,'forecast':values_out,'assumptions':['linear trend','declared event impacts']}

def impact_simulator(rows, changes):
    simulated=[]
    for row in rows or []:
        copy=dict(row)
        for key,value in (changes or {}).items(): copy[key]=value
        score_before=(1 if row.get('title') else 0)+(1 if row.get('meta_description') else 0)+(1 if row.get('status_code')==200 else 0)
        score_after=(1 if copy.get('title') else 0)+(1 if copy.get('meta_description') else 0)+(1 if copy.get('status_code')==200 else 0)
        simulated.append({'url':row.get('url'),'before_score':score_before,'after_score':score_after,'delta':score_after-score_before,'changes':changes})
    return simulated

def disambiguate_topics(rows):
    counts=Counter(str(r.get('title','')).lower() for r in rows or [])
    return [{'topic':topic,'pages':count,'gap':'underserved' if count<2 else 'covered'} for topic,count in counts.items()]
