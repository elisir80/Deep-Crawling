"""Native scoring, forecasting, recommendations, monitoring and IndexNow."""
from datetime import datetime
import json
import requests

def seo_score(rows, issues=None):
    rows=rows or []; issues=issues or []
    if not rows: return {'score':0,'components':{}}
    healthy=sum(1 for r in rows if r.get('status_code')==200)/len(rows)
    titles=sum(1 for r in rows if r.get('title'))/len(rows)
    descriptions=sum(1 for r in rows if r.get('meta_description'))/len(rows)
    indexable=sum(1 for r in rows if 'noindex' not in str(r.get('robots','')).lower())/len(rows)
    penalty=min(30,len(issues)*1.5)
    score=round(max(0,(healthy*.3+titles*.2+descriptions*.2+indexable*.3)*100-penalty),2)
    return {'score':score,'components':{'health':round(healthy*100,2),'titles':round(titles*100,2),'descriptions':round(descriptions*100,2),'indexability':round(indexable*100,2)},'issue_penalty':penalty}

def forecast(history, horizon=6):
    values=[float(x.get('value',x.get('visits',0)) or 0) for x in history or []]
    base=values[-1] if values else 0
    trend=(values[-1]-values[0])/max(len(values)-1,1) if values else 0
    return {'horizon':horizon,'scenarios':{name:[round(max(0,base+(trend*factor)*i),2) for i in range(1,horizon+1)]
            for name,factor in (('conservative',.5),('realistic',1),('aggressive',1.5))}}

def budget_forecast(history, monthly_budget=0, horizon=6):
    result=forecast(history,horizon)
    return {'monthly_budget':float(monthly_budget),'forecast':result,'expected_value':{
        key:[round(value+float(monthly_budget)*{'conservative':.5,'realistic':1,'aggressive':1.5}[key],2) for value in values]
        for key,values in result['scenarios'].items()}}

def recommendations(rows, issues=None):
    output=[]; issues=issues or []
    for row in rows or []:
        if not row.get('title'): output.append({'url':row.get('url'),'action':'Add a unique title','impact':'high','difficulty':'easy'})
        if not row.get('meta_description'): output.append({'url':row.get('url'),'action':'Add a meta description','impact':'medium','difficulty':'easy'})
        if row.get('status_code') in (404,410): output.append({'url':row.get('url'),'action':'Reclaim or redirect broken URL','impact':'high','difficulty':'medium'})
    for issue in issues:
        output.append({'url':issue.get('url'),'action':issue.get('issue','Resolve SEO issue'),'impact':'medium','difficulty':'medium'})
    return output

def changes(previous, current, fields=None):
    fields=fields or ('status_code','title','meta_description','canonical_url','robots','schema_org','content_text')
    old={r.get('url'):r for r in previous or []}; result=[]
    for row in current or []:
        before=old.get(row.get('url'))
        if not before: result.append({'url':row.get('url'),'type':'added'}); continue
        diff={key:{'old':before.get(key),'new':row.get(key)} for key in fields if before.get(key)!=row.get(key)}
        if diff: result.append({'url':row.get('url'),'type':'changed','fields':diff})
    result.extend({'url':url,'type':'removed'} for url in set(old)-{r.get('url') for r in current or []})
    return result

def white_label_report(project, rows, issues=None):
    return {'project':project or {},'generated_at':datetime.utcnow().isoformat()+'Z',
            'summary':seo_score(rows,issues),'recommendations':recommendations(rows,issues),'urls':rows or [],'issues':issues or []}

def submit_indexnow(host, key, urls, endpoint='https://api.indexnow.org/indexnow', key_location=None):
    if not host or not key or not urls: raise ValueError('host, key and urls are required')
    payload={'host':host,'key':key,'urlList':list(urls)}
    if key_location: payload['keyLocation']=key_location
    response=requests.post(endpoint,json=payload,headers={'Content-Type':'application/json; charset=utf-8'},timeout=30)
    return {'status_code':response.status_code,'accepted':response.status_code in (200,202),'body':response.text[:1000]}
