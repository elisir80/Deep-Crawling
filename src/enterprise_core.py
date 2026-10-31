"""Enterprise governance, digital twin and explainable SEO operations."""
import hashlib
import json
from datetime import datetime

def digital_twin(rows, proposed_changes=None):
    proposed_changes=proposed_changes or {}
    before={r.get('url'):dict(r) for r in rows or []}
    after={url:{**row,**proposed_changes.get(url,{})} for url,row in before.items()}
    diffs=[]
    for url in before:
        changed={k:{'before':before[url].get(k),'after':after[url].get(k)} for k in set(before[url])|set(after[url])
                 if before[url].get(k)!=after[url].get(k)}
        if changed: diffs.append({'url':url,'changes':changed,'risk':'high' if 'status_code' in changed else 'medium'})
    return {'before':before,'after':after,'diffs':diffs,'rollback':before}

def rollback_patch(snapshot):
    return {'status':'rollback-ready','created_at':datetime.utcnow().isoformat()+'Z','patch':snapshot.get('rollback',{})}

def explain(metric, value, inputs, formula):
    return {'metric':metric,'value':value,'formula':formula,'inputs':inputs,'confidence':0.8,'explanation':'Computed from the supplied crawl and measurement inputs.'}

def lineage(metric, source, transformations=None, quality=1.0):
    return {'metric':metric,'source':source,'transformations':transformations or [],'quality':max(0,min(1,float(quality))),
            'recorded_at':datetime.utcnow().isoformat()+'Z'}

def immutable_audit(event, previous_hash=''):
    payload=json.dumps({'event':event,'previous_hash':previous_hash},sort_keys=True,default=str).encode()
    return {'event':event,'previous_hash':previous_hash,'hash':hashlib.sha256(payload).hexdigest(),
            'timestamp':datetime.utcnow().isoformat()+'Z'}

def ownership(url, owner, team=None, sla_hours=72):
    return {'url':url,'owner':owner,'team':team,'sla_hours':int(sla_hours),'status':'assigned'}

def permission_matrix(subject, properties, role='analyst'):
    actions={'viewer':['read'],'analyst':['read','analyze'],'editor':['read','analyze','propose'],'admin':['read','analyze','propose','deploy']}
    return {'subject':subject,'role':role,'properties':properties,'permissions':actions.get(role,[])}
