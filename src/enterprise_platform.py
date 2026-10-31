"""Enterprise platform primitives with safe, dependency-light local defaults."""
import hashlib
import json
from datetime import datetime

def event_append(stream, event, previous_hash=''):
    payload=json.dumps({'stream':stream,'event':event,'previous_hash':previous_hash},sort_keys=True,default=str).encode()
    return {'stream':stream,'event':event,'previous_hash':previous_hash,
            'hash':hashlib.sha256(payload).hexdigest(),'timestamp':datetime.utcnow().isoformat()+'Z'}

def event_replay(events):
    state={}
    for item in sorted(events or [],key=lambda x:x.get('timestamp','')):
        event=item.get('event',{})
        if event.get('op')=='delete': state.pop(event.get('key'),None)
        elif event.get('key'): state[event['key']]=event.get('value')
    return state

def compliance_policy(data, retention_days=365, residency='EU'):
    return {'retention_days':int(retention_days),'residency':residency,'encryption_required':True,
            'audit_log_required':True,'passed':bool(data.get('encrypted') and data.get('audit_log'))}

def ai_registry(models):
    return [{'id':model.get('id'),'provider':model.get('provider','ollama'),'local':model.get('local',True),
             'enabled':model.get('enabled',True),'capabilities':model.get('capabilities',[])} for model in models or []]

def plugin_security(plugin, trusted_keys=None):
    trusted=set(trusted_keys or [])
    signature=plugin.get('signature','')
    return {'id':plugin.get('id'),'signed':signature in trusted if trusted else bool(signature),
            'scopes':plugin.get('scopes',[]),'allowed':set(plugin.get('scopes',[])) <= set(plugin.get('allowed_scopes',plugin.get('scopes',[]))),
            'dependencies':plugin.get('dependencies',[]),'risk':'high' if not signature else 'low'}

def stream_event(event, backend='local'):
    return {'backend':backend,'event':event,'status':'queued','topic':event.get('type','seo.events')}

def voice_command(transcript):
    text=str(transcript or '').lower()
    action='search' if 'cerca' in text or 'search' in text else 'report' if 'report' in text else 'audit'
    return {'transcript':transcript,'intent':action,'requires_approval':action in ('deploy','rollback')}

def agent_plan(goal, agents=None):
    agents=agents or ['crawler','analyst','editor']
    return {'goal':goal,'steps':[{'agent':agent,'action':'analyze','status':'proposed'} for agent in agents],
            'approval_required':True,'status':'pending_human_approval'}
