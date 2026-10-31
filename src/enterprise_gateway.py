"""Small dependency-light enterprise gateway primitives."""
import hashlib
import json
from datetime import datetime
import requests

def graphql_query(query, variables=None, context=None):
    context=context or {}
    if 'health' in query: data={'health':{'status':'ok','version':'1.0'}}
    elif 'projects' in query: data={'projects':context.get('projects',[])}
    elif 'tools' in query:
        from src.professional_tools import SEO_TOOL_CATALOG
        data={'tools':SEO_TOOL_CATALOG}
    else: data={'message':'Supported fields: health, projects, tools'}
    return {'data':data,'variables':variables or {}}

def webhook_event(event_type, payload):
    return {'id':hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()[:16],
            'type':event_type,'payload':payload,'created_at':datetime.utcnow().isoformat()+'Z'}

def publish_webhook(endpoint, event, token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']=token if token.lower().startswith('bearer ') else 'Bearer '+token
    response=requests.post(endpoint,json=event,headers=headers,timeout=15)
    return {'sent':response.ok,'status_code':response.status_code}

def enterprise_security(config):
    return {'on_premise':bool(config.get('on_premise',True)),'encryption_at_rest':bool(config.get('encryption_key')),
            'sso':bool(config.get('sso_provider')),'scim':bool(config.get('scim_endpoint')),
            'backup_region':config.get('backup_region','local'),'key_configured':bool(config.get('encryption_key'))}
