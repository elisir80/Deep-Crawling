"""Operational SEO forecasting, capacity and ROI tools."""
from collections import Counter
import math

def googlebot_prediction(rows, horizon_days=7):
    result=[]
    for row in rows or []:
        freshness=float(row.get('change_frequency',row.get('changes',0)) or 0)
        priority=float(row.get('priority',0) or 0)
        links=float(row.get('internal_links',0) or 0)
        probability=min(1,max(0,.1+freshness*.1+priority*.05+math.log1p(links)*.03))
        result.append({'url':row.get('url'),'visit_probability':round(probability,3),
                       'predicted_visits':round(probability*horizon_days,2)})
    return sorted(result,key=lambda x:x['visit_probability'],reverse=True)

def crawl_budget_cost(rows, cost_per_request=.001, cpu_seconds_per_request=.2):
    requests=len(rows or []); bytes_total=sum(int(x.get('size',0) or 0) for x in rows or [])
    return {'requests':requests,'bytes':bytes_total,'estimated_cost':round(requests*float(cost_per_request),6),
            'estimated_cpu_seconds':round(requests*float(cpu_seconds_per_request),3)}

def adaptive_recrawl(rows, budget=100):
    scored=[]
    for row in rows or []:
        score=float(row.get('priority',0) or 0)+float(row.get('decay_probability',0) or 0)*100
        if row.get('status_code') in (0,404,500): score+=50
        scored.append((score,row.get('url')))
    return {'budget':budget,'queue':[url for score,url in sorted(scored,reverse=True)[:int(budget)]],
            'scores':[{'url':url,'score':score} for score,url in sorted(scored,reverse=True)]}

def content_capacity(items, people=1, days=30):
    capacity=max(0,int(people))*max(0,int(days))
    planned=sum(int(x.get('effort_days',1) or 1) for x in items or [])
    return {'capacity_days':capacity,'planned_days':planned,'remaining_days':capacity-planned,
            'overloaded':planned>capacity}

def seo_roi(investments):
    result=[]
    for item in investments or []:
        cost=float(item.get('cost',0) or 0); revenue=float(item.get('revenue',0) or 0)
        result.append({**item,'roi':round((revenue-cost)/max(cost,1),4),'payback_ratio':round(revenue/max(cost,1),4)})
    return sorted(result,key=lambda x:x['roi'],reverse=True)

def multi_touch_attribution(touchpoints):
    grouped=Counter()
    for journey in touchpoints or []:
        points=journey.get('touchpoints',[]); revenue=float(journey.get('revenue',0) or 0)
        if not points: continue
        share=revenue/len(points)
        for point in points: grouped[point]+=share
    total=sum(grouped.values())
    return [{'channel':key,'revenue':round(value,2),'share_percent':round(value*100/max(total,1),2)} for key,value in grouped.items()]

def executive_report(metrics):
    return {'headline': 'SEO performance summary','metrics':metrics or [],
            'actions':[x for x in metrics or [] if x.get('status') in ('critical','warning')],
            'evidence_required':True}
