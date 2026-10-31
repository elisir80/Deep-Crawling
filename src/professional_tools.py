"""Professional SEO orchestration helpers: plugins, workflows, Discover/News."""
from datetime import datetime
import requests

SEO_TOOL_CATALOG = [
    'gsc-report','ga4-attribution','log-budget','serp-features','serp-volatility',
    'javascript-debug','entities','topical-map','semantic-score','eat','near-duplicates',
    'freshness','editorial-plan','prompt-visibility','brand-mentions','ai-crawler-policy',
    'crawl-space','pagination','product-feed','local-citations','hreflang-graph',
    'javascript-sitemap','staging-diff','redirect-plan','regression','incidents',
    'score','forecast','recommendations','changes','report','indexnow',
    'os-workflow','autonomous-agent','multi-site-twin','ecosystem-simulator','causal-impact',
    'update-clustering','serp-market','demand-warning','competitor-monitor','vulnerability-scan',
    'technical-debt','financial-risk','portfolio-forecast','budget-allocator','content-supply-chain',
    'ai-approval','authorship-provenance','legal-scan','brand-safety','knowledge-panel',
    'entity-reputation','review-response-plan','local-competitors','map-volatility','ecommerce-autopilot',
    'marketplace-audit','feed-canonical-graph','migration-rehearsal','disaster-recovery','rum-summary',
    'synthetic-monitor','privacy-analytics','accessibility-sustainability','edge-policy','cdn-purge-plan',
    'identity-policy','mask-fields','federated-aggregate','local-index','certify-plugin',
    'reproducible-report','knowledge-base','penalty-risk','procurement-questionnaire',
    'connector-readiness','connector-call','semantic-query','agent-sandbox-check','signed-bundle',
    'immutable-audit','sla-monitor','graphql-api','voice-assistant','plugin-security'
]

def capability_catalog():
    native = {'gsc-report','ga4-attribution','log-budget','serp-features','javascript-debug','entities',
              'semantic-query','local-index','mask-fields','federated-aggregate','reproducible-report'}
    simulation = {'autonomous-agent','ecosystem-simulator','migration-rehearsal','disaster-recovery',
                  'edge-policy','cdn-purge-plan','ecommerce-autopilot','agent-sandbox-check'}
    external = {'gsc-report','ga4-attribution','connector-readiness','serp-market','identity-policy'}
    return [{'tool': tool, 'mode': 'external-adapter' if tool in external else 'simulation' if tool in simulation else 'native',
             'human_approval_required': tool in simulation or tool in {'ai-approval','certify-plugin'}} for tool in SEO_TOOL_CATALOG]

def capability_audit():
    capabilities = capability_catalog()
    by_tool = {item['tool']: item for item in capabilities}
    requirements = {
        'operating_system': ['os-workflow', 'autonomous-agent', 'multi-site-twin', 'ecosystem-simulator', 'causal-impact'],
        'market_intelligence': ['update-clustering', 'serp-market', 'demand-warning', 'competitor-monitor'],
        'risk_and_planning': ['vulnerability-scan', 'technical-debt', 'financial-risk', 'portfolio-forecast', 'budget-allocator', 'content-supply-chain'],
        'ai_and_compliance': ['ai-approval', 'authorship-provenance', 'legal-scan', 'brand-safety', 'knowledge-panel', 'entity-reputation'],
        'local_and_commerce': ['review-response-plan', 'local-competitors', 'map-volatility', 'ecommerce-autopilot', 'marketplace-audit', 'feed-canonical-graph'],
        'resilience': ['migration-rehearsal', 'disaster-recovery', 'rum-summary', 'synthetic-monitor', 'privacy-analytics', 'accessibility-sustainability', 'edge-policy'],
        'governance_and_data': ['identity-policy', 'mask-fields', 'federated-aggregate', 'local-index', 'certify-plugin', 'reproducible-report', 'knowledge-base', 'immutable-audit', 'sla-monitor', 'plugin-security'],
        'runtime_adapters': ['connector-readiness', 'connector-call', 'semantic-query', 'agent-sandbox-check', 'signed-bundle', 'graphql-api', 'voice-assistant']
    }
    result = []
    for area, tools in requirements.items():
        missing = [tool for tool in tools if tool not in by_tool]
        modes = sorted({by_tool[tool]['mode'] for tool in tools if tool in by_tool})
        result.append({'area': area, 'required': tools, 'missing': missing, 'complete': not missing, 'modes': modes})
    return {'areas': result, 'all_catalogued': all(area['complete'] for area in result),
            'native_count': sum(item['mode'] == 'native' for item in capabilities),
            'simulation_count': sum(item['mode'] == 'simulation' for item in capabilities),
            'external_adapter_count': sum(item['mode'] == 'external-adapter' for item in capabilities)}

def discover_news_audit(rows):
    result=[]
    for row in rows or []:
        news=bool(row.get('news_keywords') or row.get('news_sitemap') or row.get('publication_date'))
        result.append({'url':row.get('url'),'news_detected':news,
                       'has_date':bool(row.get('publication_date') or row.get('lastmod')),
                       'issues':[] if not news or row.get('publication_date') else ['missing_publication_date']})
    return result

def register_plugin(plugin_id, name, hooks=None):
    return {'id':plugin_id,'name':name,'hooks':hooks or [],'enabled':True,'registered_at':datetime.utcnow().isoformat()+'Z'}

def workflow_payload(provider, title, description, url=None, labels=None):
    payload={'title':title,'description':description,'labels':labels or [],'url':url}
    if provider=='github': return {'title':title,'body':description,'labels':labels or []}
    if provider=='jira': return {'fields':{'summary':title,'description':description,'labels':labels or []}}
    if provider=='trello': return {'name':title,'desc':description,'url':url}
    return payload

def send_workflow(provider, endpoint, title, description, url=None, token=None, labels=None):
    if not endpoint: raise ValueError('endpoint is required')
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']=token if token.lower().startswith('bearer ') else 'Bearer '+token
    response=requests.post(endpoint,json=workflow_payload(provider,title,description,url,labels),headers=headers,timeout=30)
    return {'sent':response.ok,'status_code':response.status_code,'body':response.text[:1000]}
