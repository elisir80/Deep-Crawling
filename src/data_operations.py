"""Native data-plane and operations tools for professional SEO deployments."""
import json
from datetime import datetime

def audit_replay(events, at=None):
    state={}
    for event in sorted(events or [],key=lambda x:x.get('timestamp','')):
        if at and event.get('timestamp','') > at: break
        state[event.get('key')]=event.get('value')
    return {'at':at or datetime.utcnow().isoformat()+'Z','state':state,'events_applied':len(state)}

def time_travel_compare(events, first_at, second_at):
    first=audit_replay(events,first_at)['state']; second=audit_replay(events,second_at)['state']
    return [{'key':key,'before':first.get(key),'after':second.get(key)} for key in sorted(set(first)|set(second)) if first.get(key)!=second.get(key)]

def data_lake_export(rows, fmt='jsonl'):
    if fmt=='csv':
        fields=sorted({key for row in rows or [] for key in row})
        return ','.join(fields)+'\n'+'\n'.join(','.join(str(row.get(f,'')).replace(',',' ') for f in fields) for row in rows or [])
    return '\n'.join(json.dumps(row,ensure_ascii=False,default=str) for row in rows or [])

def sql_like_query(rows, field, value):
    return [row for row in rows or [] if str(value).lower() in str(row.get(field,'')).lower()]

def sla_monitor(issues, thresholds=None):
    thresholds=thresholds or {'high_hours':24,'medium_hours':72}
    result=[]
    for issue in issues or []:
        age=float(issue.get('age_hours',0) or 0); severity=issue.get('severity','medium')
        limit=thresholds.get(severity+'_hours',thresholds['medium_hours'])
        result.append({**issue,'sla_breached':age>limit,'limit_hours':limit})
    return result

def remediation_queue(issues):
    priority={'critical':0,'high':1,'medium':2,'low':3}
    return sorted([{'id':i,'url':x.get('url'),'action':x.get('action') or x.get('issue'),
                    'priority':x.get('severity','medium'),'status':'queued'} for i,x in enumerate(issues or [],1)],
                  key=lambda x:priority.get(x['priority'],2))

def ai_cost_report(events):
    total=sum(float(x.get('cost',0) or 0) for x in events or [])
    tokens=sum(int(x.get('tokens',0) or 0) for x in events or [])
    return {'total_cost':round(total,6),'tokens':tokens,'events':len(events or [])}

def private_mode(config):
    return {'enabled':bool(config.get('private_ai',True)),'provider':config.get('provider','ollama'),
            'external_requests_allowed':bool(config.get('allow_external',False))}
