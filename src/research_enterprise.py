"""Research-derived enterprise SEO utilities."""
from collections import defaultdict
import hashlib
import json
import threading
from datetime import datetime

REPORT_TASKS={}

CAPABILITY_MATRIX={
    'gsc_search_analytics': {'mode':'external_adapter','status':'available','endpoint':'/api/integrations/search-console'},
    'gsc_sites_sitemaps_url_inspection': {'mode':'external_adapter','status':'available','endpoint':'/api/integrations/search-console/resources'},
    'ga4_reports_sampling': {'mode':'external_adapter','status':'available','endpoint':'/api/integrations/ga4/report'},
    'bing_webmaster': {'mode':'external_adapter','status':'available','endpoint':'/api/integrations/bing-webmaster/operation'},
    'crawl_source_rendered_text_hreflang': {'mode':'native','status':'available','endpoint':'/api/crawls/<id>/report'},
    'ai_visibility_and_bot_analytics': {'mode':'native','status':'available','endpoint':'/api/seo/research/ai-visibility'},
    'rank_tracking_competitors': {'mode':'native','status':'available','endpoint':'/api/native-seo-tools/rank-tracker'},
    'lighthouse_core_web_vitals_regression': {'mode':'native','status':'available','endpoint':'/api/seo/realtime/lighthouse-regression'},
    'async_reports': {'mode':'native','status':'available','endpoint':'/api/seo/research/report-task'},
    'portfolio_workspace_patch_workflow': {'mode':'native_approval','status':'available','endpoint':'/api/seo/research/dashboard'},
}

def capability_matrix():
    return {'capabilities':CAPABILITY_MATRIX.copy(),'count':len(CAPABILITY_MATRIX),'all_available':all(item.get('status')=='available' for item in CAPABILITY_MATRIX.values())}

def page_inspect_history(snapshots, url=None):
    selected=[x for x in snapshots or [] if not url or x.get('url')==url]
    result=[]
    for item in selected:
        source=str(item.get('source_html',item.get('html',''))); rendered=str(item.get('rendered_html',''))
        result.append({'timestamp':item.get('timestamp'),'url':item.get('url'),'source_hash':hashlib.sha256(source.encode()).hexdigest(),'rendered_hash':hashlib.sha256(rendered.encode()).hexdigest(),'source_length':len(source),'rendered_length':len(rendered),'render_diff':source!=rendered})
    return {'url':url,'snapshots':result,'changed':sum(1 for a,b in zip(result,result[1:]) if a['source_hash']!=b['source_hash'] or a['rendered_hash']!=b['rendered_hash'])}

def portfolio_metrics(projects):
    totals=defaultdict(float)
    for project in projects or []:
        for key in ('traffic','revenue','conversions','impressions','clicks'): totals[key]+=float(project.get(key,0) or 0)
    return {'projects':len(projects or []),'totals':dict(totals),'domains':sorted({x.get('domain') for x in projects or [] if x.get('domain')}),'aggregated':True}

def ai_bot_analytics(logs):
    groups=defaultdict(lambda:{'requests':0,'errors':0,'bytes':0,'paths':set(),'status_codes':defaultdict(int)})
    for row in logs or []:
        user_agent=str(row.get('user_agent',''))
        bot=row.get('bot') or next((name for marker,name in [('GPTBot','GPTBot'),('ClaudeBot','ClaudeBot'),('PerplexityBot','PerplexityBot'),('Google-Extended','Google-Extended'),('Bytespider','Bytespider'),('Amazonbot','Amazonbot')] if marker.lower() in user_agent.lower()),'unknown')
        status=int(row.get('status_code',200) or 200); groups[bot]['requests']+=1; groups[bot]['errors']+=int(status>=400); groups[bot]['bytes']+=int(row.get('bytes',0) or 0); groups[bot]['status_codes'][str(status)]+=1
        if row.get('path') or row.get('url'): groups[bot]['paths'].add(row.get('path') or row.get('url'))
    return [{'bot':bot,'requests':data['requests'],'errors':data['errors'],'bytes':data['bytes'],'paths':sorted(data['paths']),'status_codes':dict(data['status_codes']),'error_rate':round(data['errors']/max(data['requests'],1),4)} for bot,data in groups.items()]

def ai_visibility_report(prompts, target_domain=None):
    """Measure locally supplied AI answer observations and citation ownership."""
    target=(target_domain or '').lower()
    rows=[]
    for prompt in prompts or []:
        citations=prompt.get('citations') or prompt.get('sources') or []
        urls=[str(x.get('url','') if isinstance(x,dict) else x) for x in citations]
        owned=[url for url in urls if target and target in url.lower()]
        competitors=sorted({url.split('/')[2] for url in urls if '://' in url and (not target or target not in url.lower())})
        rows.append({'prompt':prompt.get('prompt',''),'engine':prompt.get('engine','unknown'),'answered':bool(prompt.get('answer') or prompt.get('answered',False)),
                     'citation_count':len(urls),'owned_citations':len(owned),'competitor_domains':competitors,
                     'visibility':'owned' if owned else ('mentioned' if prompt.get('mentioned') else 'absent')})
    total=len(rows); owned=sum(1 for row in rows if row['owned_citations']); answered=sum(1 for row in rows if row['answered'])
    return {'target_domain':target_domain,'prompts':rows,'summary':{'prompts':total,'answered':answered,'answer_rate':round(answered/max(total,1),4),'owned_prompts':owned,'visibility_rate':round(owned/max(total,1),4),'citation_gap':[row['prompt'] for row in rows if not row['owned_citations']]}}

def report_task(data, task_id=None, asynchronous=False):
    payload=json.dumps(data or {},sort_keys=True,default=str); task_id=task_id or hashlib.sha256(payload.encode()).hexdigest()[:16]
    task={'task_id':task_id,'status':'queued' if asynchronous else 'completed','result':None if asynchronous else (data or {}),'created_at':datetime.utcnow().isoformat()+'Z','async_compatible':True,'reproducible':True}
    REPORT_TASKS[task_id]=task
    if asynchronous:
        def complete():
            task['status']='running'
            task['result']=data or {}
            task['completed_at']=datetime.utcnow().isoformat()+'Z'
            task['status']='completed'
        threading.Thread(target=complete,daemon=True).start()
    return REPORT_TASKS[task_id]

def report_task_status(task_id):
    return REPORT_TASKS.get(task_id, {'task_id':task_id,'status':'not_found','result':None})

def data_quality_report(rows, expected_fields=None, sample_metadata=None):
    rows=list(rows or []); expected_fields=expected_fields or []
    missing=sum(1 for row in rows for field in expected_fields if row.get(field) in (None,'')); duplicates=len(rows)-len({json.dumps(row,sort_keys=True,default=str) for row in rows})
    metadata=sample_metadata or {}; sampled=bool(metadata.get('sampled')); loss=float(metadata.get('data_loss_percent',0) or 0)
    return {'row_count':len(rows),'missing_values':missing,'duplicate_rows':duplicates,'completeness':round(1-missing/max(len(rows)*max(len(expected_fields),1),1),4),'sampled':sampled,'data_loss_percent':loss,'confidence':'low' if sampled or loss>5 else 'high'}

def workspace_audit(events):
    return [{'timestamp':event.get('timestamp'),'actor':event.get('actor'),'action':event.get('action'),'resource':event.get('resource'),'allowed':bool(event.get('allowed',True))} for event in events or []]

def patch_automation(issues, approved=False):
    plans=[]
    for issue in issues or []:
        patch=issue.get('patch') or {}; plans.append({'url':issue.get('url'),'issue':issue.get('issue'),'patch':patch,'preview':{**issue,**patch},'approved':bool(approved),'executed':False,'rollback':issue.get('before',{})})
    return {'plans':plans,'mode':'preview_only','approval_required':True,'executed_count':0}

def patch_transition(plans, approved=False, rollback=False):
    if rollback:
        return {'status':'rollback_ready','plans':[{'url':x.get('url'),'rollback':x.get('rollback',{}),'executed':False} for x in plans or []],'external_deploy':False}
    status='approved' if approved else 'pending_approval'
    return {'status':status,'plans':[{'url':x.get('url'),'patch':x.get('patch',{}),'approved':bool(approved),'executed':False,'rollback':x.get('rollback',{})} for x in plans or []],'external_deploy':False}

def patch_apply_local(rows, plans, approved=False):
    """Apply approved field patches to an in-memory copy; never deploys externally."""
    if not approved:
        return {'status':'pending_approval','applied':False,'rows':rows or [],'changes':[],'external_deploy':False}
    by_url={row.get('url'):dict(row) for row in rows or []}; changes=[]
    for plan in plans or []:
        url=plan.get('url'); patch=plan.get('patch') or {}
        if url not in by_url: continue
        before={key:by_url[url].get(key) for key in patch}
        by_url[url].update(patch)
        changes.append({'url':url,'before':before,'after':{key:by_url[url].get(key) for key in patch}})
    return {'status':'applied_local','applied':True,'rows':list(by_url.values()),'changes':changes,'external_deploy':False}

def patch_rollback_local(rows, changes, approved=False):
    """Restore values from a local patch change-set after explicit approval."""
    if not approved:
        return {'status':'pending_approval','rolled_back':False,'rows':rows or [],'external_deploy':False}
    by_url={row.get('url'):dict(row) for row in rows or []}; restored=[]
    for change in changes or []:
        url=change.get('url')
        if url not in by_url: continue
        before=change.get('before') or {}
        current={key:by_url[url].get(key) for key in before}
        by_url[url].update(before)
        restored.append({'url':url,'from':current,'to':before})
    return {'status':'rolled_back_local','rolled_back':True,'rows':list(by_url.values()),'changes':restored,'external_deploy':False}

def portfolio_dashboard(projects, data_rows=None, bot_logs=None, report_tasks=None):
    return {'portfolio':portfolio_metrics(projects), 'data_quality':data_quality_report(data_rows or []), 'ai_bots':ai_bot_analytics(bot_logs or []), 'report_tasks':list(report_tasks or []), 'dashboard_mode':'local-aggregated'}
