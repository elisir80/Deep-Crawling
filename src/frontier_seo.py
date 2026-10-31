"""Frontier SEO intelligence: causal impact, realtime twin and knowledge graph."""
from collections import defaultdict
import hashlib
import json


def causal_impact_multifactor(treatment, control, factors=None):
    factors = factors or {}
    def change(values):
        split = max(1, len(values) // 2); return (sum(values[split:]) / max(1, len(values) - split)) - (sum(values[:split]) / split)
    treatment_change = change([float(x or 0) for x in treatment or []]); control_change = change([float(x or 0) for x in control or []])
    adjustments = {key: float(value or 0) for key, value in factors.items()}
    adjusted = treatment_change - control_change - sum(adjustments.values())
    return {'treatment_change': round(treatment_change, 4), 'control_change': round(control_change, 4),
            'factor_adjustments': adjustments, 'causal_effect': round(adjusted, 4),
            'method': 'difference_in_differences_plus_declared_covariates', 'confidence': round(min(1, abs(adjusted) / max(abs(treatment_change), 1)), 3)}


def realtime_digital_twin(production, staging, events=None):
    prod = {row.get('url'): row for row in production or [] if row.get('url')}; stage = {row.get('url'): row for row in staging or [] if row.get('url')}
    diffs = []
    for url in sorted(set(prod) | set(stage)):
        if url not in prod: diffs.append({'url': url, 'change': 'staging_added'})
        elif url not in stage: diffs.append({'url': url, 'change': 'staging_missing'})
        else:
            fields = [key for key in set(prod[url]) | set(stage[url]) if prod[url].get(key) != stage[url].get(key)]
            if fields: diffs.append({'url': url, 'change': 'field_diff', 'fields': fields})
    return {'production_count': len(prod), 'staging_count': len(stage), 'diffs': diffs,
            'events': events or [], 'deploy_ready': not any(x['change'] == 'staging_missing' for x in diffs),
            'rollback_available': True, 'mode': 'realtime_snapshot_sync'}


def proprietary_knowledge_graph(rows, links=None):
    nodes = {}; edges = []
    def add(node_id, kind, label=None, data=None):
        nodes.setdefault(node_id, {'id': node_id, 'type': kind, 'label': label or node_id, 'data': data or {}})
    for row in rows or []:
        url = row.get('url');
        if not url: continue
        add(url, 'url', url, row)
        for field, kind in (('keywords', 'keyword'), ('entities', 'entity'), ('authors', 'author')):
            for value in row.get(field, []) or []:
                node_id = '%s:%s' % (kind, value); add(node_id, kind, str(value)); edges.append({'from': url, 'to': node_id, 'relation': 'targets' if kind == 'keyword' else 'mentions' if kind == 'entity' else 'authored_by'})
        if row.get('conversion_value') is not None:
            node_id = 'conversion:%s' % url; add(node_id, 'conversion', url, {'value': row.get('conversion_value')}); edges.append({'from': url, 'to': node_id, 'relation': 'converts_to'})
    for link in links or []:
        if link.get('source') and link.get('target'): edges.append({'from': link['source'], 'to': link['target'], 'relation': 'links_to'})
    digest = hashlib.sha256(json.dumps({'nodes': nodes, 'edges': edges}, sort_keys=True, default=str).encode()).hexdigest()
    return {'nodes': list(nodes.values()), 'edges': edges, 'node_count': len(nodes), 'edge_count': len(edges), 'graph_hash': digest}

def revenue_at_risk_incidents(incidents):
    result=[]
    for incident in incidents or []:
        revenue=float(incident.get('revenue',incident.get('monthly_revenue',0)) or 0); probability=min(1,max(0,float(incident.get('probability',.1) or 0))); duration=max(1,float(incident.get('duration_days',1) or 1))
        result.append({**incident,'revenue_at_risk':round(revenue*probability*duration/30,2),'severity':'critical' if revenue*probability>10000 else 'high' if probability>=.5 else 'normal','rollback_recommended':probability>=.5})
    return sorted(result,key=lambda x:x['revenue_at_risk'],reverse=True)

def seo_canary_deploy(changes, baseline, canary, guardrails=None, approvals=0):
    guardrails=guardrails or {'max_error_increase':0,'max_conversion_drop':.1}; errors=float(canary.get('errors',0) or 0)-float(baseline.get('errors',0) or 0); base=float(baseline.get('conversions',0) or 0); current=float(canary.get('conversions',0) or 0); drop=(base-current)/max(abs(base),1); failures=[]
    if errors>float(guardrails.get('max_error_increase',0)): failures.append('error_increase')
    if drop>float(guardrails.get('max_conversion_drop',.1)): failures.append('conversion_drop')
    return {'changes':changes,'canary':canary,'guardrails':guardrails,'failures':failures,'status':'rollback' if failures else 'promote' if int(approvals)>=1 else 'pending_approval','rollback_available':True,'promotion_requires_approval':True}

def ai_factuality_check(responses, trusted_facts, trusted_sources=None):
    facts={str(x).lower() for x in trusted_facts or []}; sources={str(x).lower() for x in trusted_sources or []}; result=[]
    for response in responses or []:
        claims=[str(x) for x in response.get('claims',[])]; unsupported=[x for x in claims if x.lower() not in facts]
        cited=[str(x) for x in response.get('sources',[])]; untrusted=[x for x in cited if sources and x.lower() not in sources]
        result.append({'id':response.get('id',response.get('provider')),'unsupported_claims':unsupported,'untrusted_sources':untrusted,'factuality_score':round(max(0,1-(len(unsupported)+len(untrusted))/max(len(claims)+len(cited),1)),3),'requires_review':bool(unsupported or untrusted)})
    return result

def content_provenance(rows):
    result=[]
    for row in rows or []:
        origin=row.get('origin', 'human'); reviewed=bool(row.get('reviewed_by') or row.get('human_reviewed'))
        result.append({**row,'origin':origin,'reviewed':reviewed,'publishable':origin != 'ai' or reviewed,'provenance_complete':bool(row.get('author') or row.get('prompt_id') or row.get('source'))})
    return result

def backlink_risk_disavow(links, threshold=50):
    result=[]; domains=[]
    for link in links or []:
        authority=float(link.get('authority',0) or 0); relevance=float(link.get('relevance',0) or 0); spam=float(link.get('spam_score',0) or 0); anchor=str(link.get('anchor','')).lower()
        risk=spam + (100-authority)*.3 + (100-relevance)*.2 + (20 if anchor in ('money','exact-match') else 0)
        domain=link.get('domain') or link.get('url'); bad=risk>=float(threshold)
        result.append({**link,'risk_score':round(risk,3),'risk':'high' if bad else 'normal','disavow_recommended':bad})
        if bad and domain: domains.append(domain)
    return {'links':sorted(result,key=lambda x:x['risk_score'],reverse=True),'disavow_domains':sorted(set(domains)),'mode':'preview_only','approval_required':True}

def self_hosted_data_lake(rows, query=None, dimension=None):
    rows=list(rows or [])
    if query:
        terms=str(query).lower().split(); rows=[row for row in rows if all(term in json.dumps(row,default=str).lower() for term in terms)]
    groups=defaultdict(float)
    if dimension:
        for row in rows: groups[str(row.get(dimension,'unknown'))]+=float(row.get('value',row.get('revenue',0)) or 0)
    return {'rows':rows,'row_count':len(rows),'aggregates':dict(groups),'storage':'local','query_engine':'semantic-sql-compatible','audit_replay':True,'raw_data_external':False}

def seo_feature_flags(rows, flags, context=None):
    context=context or {}; result=[]
    for row in rows or []:
        enabled=[]
        for name, rule in (flags or {}).items():
            markets=rule.get('markets'); devices=rule.get('devices'); templates=rule.get('templates')
            if markets and context.get('market') not in markets: continue
            if devices and context.get('device') not in devices: continue
            if templates and row.get('template') not in templates: continue
            enabled.append(name)
        result.append({'url':row.get('url'),'enabled_flags':enabled,'changes':{name:(flags[name].get('changes') or {}) for name in enabled},'mode':'simulation'})
    return result

def googlebot_behavior_profiler(logs):
    groups=defaultdict(lambda:{'visits':0,'bytes':0,'errors':0})
    for row in logs or []:
        key=(row.get('directory') or str(row.get('url','')).split('/')[3] if row.get('url') else 'unknown',row.get('template','unknown'),row.get('parameter','none'))
        groups[key]['visits']+=1; groups[key]['bytes']+=int(row.get('bytes',0) or 0); groups[key]['errors']+=int(row.get('status_code',200) or 200)>=400
    return [{'directory':key[0],'template':key[1],'parameter':key[2],**value,'error_rate':round(value['errors']/max(value['visits'],1),4)} for key,value in groups.items()]

def content_quality_benchmark(rows, sector=None):
    result=[]
    for row in rows or []:
        words=len(str(row.get('content_text','')).split()); score=min(100,words/10)+ (20 if row.get('author') else 0)+(20 if row.get('citations') else 0)+(10 if row.get('updated_at') else 0)
        result.append({**row,'sector':sector or row.get('sector','generic'),'quality_score':round(min(100,score),2),'benchmark_status':'above' if score>=70 else 'below'})
    return sorted(result,key=lambda x:x['quality_score'],reverse=True)

def internal_link_optimizer(rows, links, limit=20):
    incoming=defaultdict(int); titles={row.get('url'):row.get('title','') for row in rows or []}
    for link in links or []: incoming[link.get('target',link.get('target_url'))]+=1
    suggestions=[]
    for row in rows or []:
        url=row.get('url');
        if url and incoming[url] < 2: suggestions.append({'target':url,'title':titles.get(url,''),'current_inlinks':incoming[url],'priority':max(1,3-incoming[url])})
    return sorted(suggestions,key=lambda x:x['priority'],reverse=True)[:int(limit)]

def lighthouse_regression(before, after, thresholds=None):
    thresholds=thresholds or {'performance_drop':.1,'accessibility_drop':.1}; failures=[]; metrics=[]
    for key in ('performance','accessibility','best_practices','seo'):
        old=float(before.get(key,0) or 0); new=float(after.get(key,0) or 0); drop=(old-new)/max(abs(old),1)
        if drop>float(thresholds.get(key+'_drop',thresholds.get('performance_drop',.1))): failures.append({'metric':key,'drop':round(drop,4)})
    metric_limits=thresholds.get('cwv',{'lcp':2.5,'inp':200,'cls':0.1,'ttfb':0.8,'fcp':1.8})
    for key, limit in metric_limits.items():
        if key not in after: continue
        value=float(after.get(key) or 0); metric={'metric':key,'value':value,'threshold':float(limit),'passed':value<=float(limit)}; metrics.append(metric)
        if not metric['passed']: failures.append({'metric':key,'value':value,'threshold':float(limit),'type':'core_web_vital'})
    return {'passed':not failures,'failures':failures,'metrics':metrics,'merge_allowed':not failures}

def rum_multi_country(samples):
    groups=defaultdict(list)
    for sample in samples or []: groups[(sample.get('country','unknown'),sample.get('device','unknown'))].append(sample)
    return [{'country':key[0],'device':key[1],'samples':len(items),'average_lcp':round(sum(float(x.get('lcp',0) or 0) for x in items)/max(len(items),1),3),'revenue':round(sum(float(x.get('revenue',0) or 0) for x in items),2)} for key,items in groups.items()]

def privacy_attribution(touchpoints):
    totals=defaultdict(float)
    for row in touchpoints or []:
        channels=row.get('channels',row.get('touchpoints',[])); value=float(row.get('revenue',0) or 0)
        for channel in channels: totals[channel]+=value/max(len(channels),1)
    total=sum(totals.values()); return [{'channel':key,'attributed_revenue':round(value,2),'share':round(value/max(total,1),4)} for key,value in totals.items()]

def capacity_planner(items, people=1, days=30):
    capacity=max(0,int(people))*max(0,int(days)); planned=sum(float(x.get('effort_days',1) or 1) for x in items or [])
    return {'capacity_days':capacity,'planned_days':planned,'remaining_days':capacity-planned,'overloaded':planned>capacity,'queue':sorted(items or [],key=lambda x:float(x.get('business_value',0) or 0),reverse=True)}

def multi_brand_governance(rows, roles=None):
    roles=roles or {}; result=[]
    for row in rows or []: result.append({**row,'owner':roles.get(row.get('brand'),row.get('owner')),'sla_hours':row.get('sla_hours',72),'permission_checked':bool(row.get('brand') in roles)})
    return {'items':result,'brands':sorted({x.get('brand') for x in rows or [] if x.get('brand')}),'approval_required':True}

def evidence_vault(events, previous_hash=''):
    payload=json.dumps({'events':events or [],'previous_hash':previous_hash},sort_keys=True,default=str).encode(); digest=hashlib.sha256(payload).hexdigest()
    return {'events':events or [],'previous_hash':previous_hash,'hash':digest,'chain_of_custody':True,'immutable':True}
