"""Native migration, regression, alerting and experimentation utilities."""
from datetime import datetime
import requests

def staging_diff(staging, production):
    prod={r.get('url'):r for r in production or []}; stage={r.get('url'):r for r in staging or []}
    changes=[]
    for url in sorted(set(prod)|set(stage)):
        if url not in prod: changes.append({'url':url,'type':'new_in_staging'})
        elif url not in stage: changes.append({'url':url,'type':'missing_in_staging'})
        else:
            diff={key:{'production':prod[url].get(key),'staging':stage[url].get(key)}
                  for key in ('status_code','title','meta_description','canonical_url','robots','schema_org')
                  if prod[url].get(key)!=stage[url].get(key)}
            if diff: changes.append({'url':url,'type':'changed','fields':diff})
    return changes

def redirect_plan(old_urls, new_urls):
    new=set(new_urls or []); return [{'old_url':url,'action':'redirect','target':min(new,key=lambda x:abs(len(x)-len(url))) if new else None}
        for url in old_urls or [] if url not in new]

def regression_tests(rows, rules=None):
    rules=rules or {'max_404':0,'min_title_rate':.9,'min_indexable_rate':.9}
    total=max(len(rows or []),1); failures=[]
    if sum(1 for r in rows or [] if r.get('status_code') in (404,410)) > rules['max_404']: failures.append('too_many_404')
    if sum(1 for r in rows or [] if r.get('title'))/total < rules['min_title_rate']: failures.append('title_coverage')
    if sum(1 for r in rows or [] if 'noindex' not in str(r.get('robots','')).lower())/total < rules['min_indexable_rate']: failures.append('indexability')
    return {'passed':not failures,'failures':failures,'tested_urls':len(rows or [])}

def incidents(previous, current):
    old={r.get('url'):r for r in previous or []}; alerts=[]
    for row in current or []:
        before=old.get(row.get('url'))
        if before and before.get('status_code')==200 and row.get('status_code') in (0,404,500):
            alerts.append({'url':row.get('url'),'type':'availability_drop','severity':'critical'})
        if before and float(row.get('position',0) or 0) and float(row.get('position',0)) > float(before.get('position',0) or 0)+10:
            alerts.append({'url':row.get('url'),'type':'ranking_drop','severity':'high'})
    return alerts

def experiment_variant(url, title, variant, metric='ctr'):
    return {'url':url,'variant':variant,'title':title,'metric':metric,'status':'draft','created_at':datetime.utcnow().isoformat()+'Z'}

def send_alert(channel, target, message, token=None):
    if channel=='webhook':
        response=requests.post(target,json={'text':message},timeout=15)
        return {'sent':response.ok,'status_code':response.status_code}
    if channel=='telegram':
        response=requests.post('https://api.telegram.org/bot'+str(token)+'/sendMessage',json={'chat_id':target,'text':message},timeout=15)
        return {'sent':response.ok,'status_code':response.status_code}
    return {'sent':False,'error':'Use the existing email service for email alerts or a webhook for Slack/Jira/Trello/GitHub'}
