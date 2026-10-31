"""Local rendering queue, CMS adapters and SEO contract testing."""
from datetime import datetime
import requests

def render_queue(urls, workers=2, user_agent='Googlebot'):
    return {'workers':max(1,int(workers)),'user_agent':user_agent,
            'jobs':[{'id':i+1,'url':url,'status':'queued'} for i,url in enumerate(urls or [])]}

def cms_request(provider, endpoint, token, method='GET', payload=None):
    if provider not in ('wordpress','shopify','magento','webflow'): raise ValueError('unsupported CMS provider')
    headers={'Accept':'application/json'}
    if token: headers['Authorization']=token if token.lower().startswith('bearer ') else 'Bearer '+token
    response=requests.request(method,endpoint,json=payload,headers=headers,timeout=30)
    return {'provider':provider,'status_code':response.status_code,'ok':response.ok,'body':response.text[:2000]}

def preview_fix(row, changes):
    before=dict(row); after={**row,**changes}
    return {'id':row.get('url'),'status':'preview','before':before,'after':after,'rollback':before}

def contract_test(name, actual, expected):
    failures=[]
    for key,value in (expected or {}).items():
        if actual.get(key)!=value: failures.append({'field':key,'expected':value,'actual':actual.get(key)})
    return {'contract':name,'passed':not failures,'failures':failures}

def security_privacy_audit(row):
    headers=row.get('http_headers') or {}; text=str(row.get('html',''))
    return {'https':str(row.get('url','')).startswith('https://'),
            'hsts':bool(headers.get('strict-transport-security')),
            'csp':bool(headers.get('content-security-policy')),
            'privacy_risk':bool('analytics' in text.lower() and 'consent' not in text.lower())}
