"""Realtime enterprise SEO analytics and safe deployment primitives."""
from collections import Counter, defaultdict
from datetime import datetime
import math
import re

def update_heatmap(before, after, dimension='url'):
    old={row.get(dimension) or row.get('url'):row for row in before or []}
    cells=[]
    for row in after or []:
        key=row.get(dimension) or row.get('url'); prev=old.get(key,{})
        rank_delta=float(row.get('position',0) or 0)-float(prev.get('position',0) or 0)
        traffic_delta=float(row.get('traffic',0) or 0)-float(prev.get('traffic',0) or 0)
        cells.append({'key':key,'rank_delta':rank_delta,'traffic_delta':traffic_delta,
                      'impact':'negative' if rank_delta>0 or traffic_delta<0 else 'positive'})
    return {'dimension':dimension,'cells':cells,'affected':sum(x['impact']=='negative' for x in cells)}

def causal_attribution(touchpoints, revenue_field='revenue'):
    totals=defaultdict(float)
    for row in touchpoints or []:
        channel=row.get('channel','unknown'); totals[channel]+=float(row.get(revenue_field,0) or 0)
    total=sum(totals.values())
    return [{'channel':channel,'revenue':round(value,2),'share_percent':round(value*100/max(total,1),2)} for channel,value in totals.items()]

def ranking_experiment(name, control, variants, metric='position'):
    def average(rows): return sum(float(x.get(metric,0) or 0) for x in rows)/max(len(rows),1)
    control_avg=average(control)
    return {'name':name,'metric':metric,'control':{'size':len(control),'average':control_avg},
            'variants':[{'name':key,'size':len(value),'average':average(value),'delta':average(value)-control_avg}
                        for key,value in (variants or {}).items()],'status':'running'}

def serp_replay(previous, current, pixels=None):
    old=set(previous or []); new=set(current or [])
    return {'added':sorted(new-old),'removed':sorted(old-new),'pixel_diff_percent':float(pixels or 0),
            'changed':bool(old!=new or pixels)}

def adaptive_scheduler(urls, changes=None, budget=100):
    changes=changes or {}; ranked=[]
    for row in urls or []:
        url=row.get('url') if isinstance(row,dict) else row
        score=float(changes.get(url,row.get('priority',0) if isinstance(row,dict) else 0) or 0)
        if isinstance(row,dict):
            score += 10 if row.get('status_code') in (0,500,404) else 0
            score += 5 if row.get('lastmod') else 0
        ranked.append((score,url))
    return {'budget':int(budget),'selected':[url for _,url in sorted(ranked,reverse=True)[:int(budget)]],
            'priority_order':[{'url':url,'score':score} for score,url in sorted(ranked,reverse=True)]}

def demand_graph(keywords, markets):
    graph=[]
    for market in markets or ['global']:
        for item in keywords or []:
            volume=float(item.get('volume',0) if isinstance(item,dict) else 0)
            term=item.get('keyword',item) if isinstance(item,dict) else item
            graph.append({'keyword':term,'market':market,'volume':volume,'emerging':bool(item.get('growth',0)>20) if isinstance(item,dict) else False})
    return graph

def market_gap(datasets):
    all_terms=set().union(*(set(data.get('terms',[])) for data in datasets.values()))
    return [{'market':market,'missing_terms':sorted(all_terms-set(data.get('terms',[])))} for market,data in datasets.items()]

def entity_conflicts(row):
    schema=set(row.get('schema_entities',[]) or []); content=set(row.get('content_entities',[]) or []); kg=set(row.get('knowledge_graph_entities',[]) or [])
    return {'conflicts':sorted((schema|content|kg)- (schema&content&kg)),'consistent':not bool((schema|content|kg)-(schema&content&kg))}

def authority_decay(history, threshold=.2):
    if len(history)<2:return {'decayed':False,'delta':0}
    delta=float(history[-1])-float(history[0]); return {'decayed':delta < -abs(history[0])*threshold,'delta':delta}

def content_revenue(rows):
    return [{'url':row.get('url'),'revenue':float(row.get('revenue',0) or 0),'sessions':row.get('sessions',0),
             'revenue_per_session':round(float(row.get('revenue',0) or 0)/max(float(row.get('sessions',0) or 0),1),4)} for row in rows or []]

def safe_deploy(changes, approvals=0, required=1):
    return {'status':'approved' if approvals>=required else 'pending_approval','changes':changes,'rollback_available':True}
