"""Unified deterministic enterprise tools over caller-supplied local data."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib, json, re
import requests

ENTERPRISE_NEXT_CAPABILITIES={
    'log_file_analyzer':('/api/enterprise-next/log-analyzer','native'), 'crux_rum':('/api/enterprise-next/crux','external_adapter+native'),
    'migration_assistant':('/api/enterprise-next/migration','native'), 'security_scanner':('/api/enterprise-next/security','native'),
    'content_governance':('/api/enterprise-next/content-governance','native'), 'serp_volatility':('/api/enterprise-next/serp-volatility','native'),
    'brand_reputation':('/api/enterprise-next/brand-monitor','native'), 'rich_results':('/api/enterprise-next/rich-results','native'),
    'crawl_replay':('/api/enterprise-next/crawl-replay','native'), 'data_warehouse':('/api/enterprise-next/warehouse-query','native'),
    'product_intelligence':('/api/enterprise-next/product-intelligence','native'), 'issue_prioritization':('/api/enterprise-next/prioritize','native')}

def enterprise_next_capabilities():
    return {'capabilities':[{'name':key,'endpoint':value[0],'mode':value[1],'status':'available'} for key,value in ENTERPRISE_NEXT_CAPABILITIES.items()],'count':len(ENTERPRISE_NEXT_CAPABILITIES),'all_available':True}
from urllib.parse import urlparse

def parse_log_lines(lines, format='auto'):
    """Parse common/combined Apache-Nginx lines and JSON CDN records."""
    parsed=[]; pattern=re.compile(r'^(?P<ip>\S+) \S+ \S+ \[(?P<date>[^]]+)\] "(?P<method>\S+) (?P<url>\S+)(?: HTTP/[^\"]+)?" (?P<status>\d{3}) (?P<size>\S+)(?: "(?P<referer>[^\"]*)" "(?P<ua>[^\"]*)")?')
    for line in lines or []:
        if isinstance(line,dict): parsed.append(line); continue
        text=str(line).strip()
        try:
            obj=json.loads(text)
            if isinstance(obj,dict):
                parsed.append({'url':obj.get('url') or obj.get('path') or obj.get('request_uri'),'status':obj.get('status') or obj.get('status_code',200),'bytes':obj.get('bytes') or obj.get('body_bytes_sent',0),'user_agent':obj.get('user_agent') or obj.get('ua',''),'bot':obj.get('bot') or obj.get('bot_name')})
                continue
        except (TypeError,ValueError): pass
        match=pattern.match(text)
        if match:
            item=match.groupdict(); ua=item.pop('ua') or ''; item.update({'status':int(item.pop('status')),'bytes':0 if item['size']=='-' else int(item.pop('size')),'user_agent':ua})
            parsed.append(item)
    for row in parsed:
        ua=str(row.get('user_agent') or ''); row.setdefault('bot',next((name for marker,name in [('Googlebot','Googlebot'),('bingbot','Bingbot'),('GPTBot','GPTBot'),('ClaudeBot','ClaudeBot'),('PerplexityBot','PerplexityBot')] if marker.lower() in ua.lower()),'unknown'))
    return parsed

def log_analyzer(records, crawled_urls=None):
    known=set(crawled_urls or []); bots=Counter(); dirs=defaultdict(lambda:{'requests':0,'errors_5xx':0,'waste':0,'unique':set()}); waste=[]
    for row in records or []:
        url=str(row.get('url','')); status=int(row.get('status',row.get('status_code',200)) or 200); bot=row.get('bot') or row.get('bot_name') or 'unknown'; bots[bot]+=1
        path=urlparse(url).path or (url.split('?',1)[0] or '/')
        bucket=dirs[path]; bucket['requests']+=1; bucket['unique'].add(url); bucket['errors_5xx']+=int(status>=500)
        is_waste=status>=400 or status in (301,302,307,308) or '?' in url or (url and url not in known)
        bucket['waste']+=int(is_waste); waste.append(url) if is_waste else None
    return {'requests':len(records or []),'bots':dict(bots),'directories':[{'directory':'/'+key.strip('/').split('/')[0] if key.strip('/') else '/','requests':v['requests'],'unique_urls':len(v['unique']),'errors_5xx':v['errors_5xx'],'waste':v['waste']} for key,v in sorted(dirs.items())],'wasted_requests':len(waste),'unknown_urls':sorted({r.get('url') for r in records or [] if r.get('url') and r.get('url') not in known})}

def rum_compare(samples, lighthouse=None):
    fields=('lcp','inp','cls','ttfb','fcp'); groups=defaultdict(list)
    for row in samples or []: groups[(row.get('country','unknown'),row.get('device','unknown'),row.get('template','unknown'))].append(row)
    segments=[]
    for key,items in groups.items():
        metrics={field:round(sum(float(x.get(field,0) or 0) for x in items)/max(len(items),1),4) for field in fields}
        segments.append({'country':key[0],'device':key[1],'template':key[2],'samples':len(items),'metrics':metrics})
    return {'segments':segments,'sample_count':len(samples or []),'source':'real_user_measurement','lighthouse':lighthouse or {},'comparison_available':bool(lighthouse)}

def crux_query(origin=None, url=None, api_key=None, form_factor=None):
    """Optional official CrUX adapter; credentials are request-scoped only."""
    if not api_key or not (origin or url): raise ValueError('api_key and origin or url are required')
    payload={'formFactor':form_factor} if form_factor else {}
    if origin: payload['origin']=origin
    if url: payload['url']=url
    response=requests.post('https://chromeuxreport.googleapis.com/v1/records:queryRecord',params={'key':api_key},json=payload,timeout=30); response.raise_for_status(); data=response.json(); data['_source']='CrUX API'; data['_request_scope']={'origin':origin,'url':url,'form_factor':form_factor}; return data

def migration_assistant(before, after, redirects=None, traffic=None):
    old={x.get('url'):x for x in before or [] if x.get('url')}; new={x.get('url'):x for x in after or [] if x.get('url')}; redirects=redirects or {}; missing=sorted(set(old)-set(new)); chains=[]; loops=[]
    for source,target in redirects.items():
        seen=set(); current=source
        while current in redirects and current not in seen: seen.add(current); current=redirects[current]
        if current in seen: loops.append(source)
        if len(seen)>1: chains.append({'source':source,'hops':len(seen),'final':current})
    lost=sum(float((traffic or {}).get(url,0) or 0) for url in missing if url not in redirects)
    return {'old_urls':len(old),'new_urls':len(new),'missing_urls':missing,'redirects':redirects,'chains':chains,'loops':loops,'estimated_traffic_at_risk':lost,'passed':not [x for x in missing if x not in redirects] and not loops}

def security_scan(rows):
    findings=[]
    for row in rows or []:
        html=str(row.get('source_html') or row.get('html') or ''); headers={str(k).lower():str(v) for k,v in (row.get('headers') or row.get('http_headers') or {}).items()}; scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)
        if row.get('status_code') in (301,302) and row.get('redirect_final_url') and row.get('url') and row['redirect_final_url'] != row['url']: findings.append({'url':row.get('url'),'type':'redirect_hijacking','severity':'high'})
        if re.search(r'(eval\s*\(|base64_decode|document\.write\s*\()',html,re.I): findings.append({'url':row.get('url'),'type':'suspicious_script','severity':'high'})
        source_text=' '.join(str(row.get('source_text') or html).lower().split()); rendered_text=' '.join(str(row.get('rendered_text') or row.get('extracted_text') or source_text).lower().split())
        if source_text and rendered_text and source_text != rendered_text and (max(len(source_text),1)/max(len(rendered_text),1) > 2 or max(len(rendered_text),1)/max(len(source_text),1) > 2): findings.append({'url':row.get('url'),'type':'possible_cloaking','severity':'high'})
        if re.search(r'(crypto(miner|night)|shell_exec|passthru\s*\(|<iframe[^>]+display\s*:\s*none)',html,re.I): findings.append({'url':row.get('url'),'type':'possible_malware','severity':'critical'})
        if row.get('indexable',row.get('robots','').lower() not in ('noindex','noindex, nofollow')) and row.get('environment')=='staging': findings.append({'url':row.get('url'),'type':'staging_indexable','severity':'high'})
        for header in ('content-security-policy','strict-transport-security','x-content-type-options'):
            if header not in headers: findings.append({'url':row.get('url'),'type':'missing_'+header,'severity':'medium'})
        if any('http://' in script for script in scripts) and str(row.get('url','')).startswith('https://'): findings.append({'url':row.get('url'),'type':'mixed_content','severity':'medium'})
    return {'findings':findings,'high':sum(x['severity']=='high' for x in findings),'passed':not findings}

def content_governance(rows, approvals=None, previous=None):
    approvals=approvals or {}; result=[]; now=datetime.utcnow(); old={x.get('url'):x for x in previous or []}
    for row in rows or []:
        updated=row.get('updated_at'); age=None
        if updated:
            try: age=(now-datetime.fromisoformat(str(updated).replace('Z','+00:00')).replace(tzinfo=None)).days
            except ValueError: pass
        before=old.get(row.get('url'),{}); changed=[field for field in ('title','meta_description','content_text','canonical') if before.get(field)!=row.get(field)]
        result.append({**row,'owner':row.get('owner'),'age_days':age,'approval_status':approvals.get(row.get('url'),'pending'),'decay':bool(age is not None and age>365),'changed_fields':changed})
    return {'items':result,'owners':sorted({x.get('owner') for x in result if x.get('owner')}),'pending':sum(x['approval_status']=='pending' for x in result),'changed_pages':sum(bool(x['changed_fields']) for x in result)}

def serp_volatility(rows, update_dates=None):
    groups=defaultdict(list)
    for row in rows or []: groups[(row.get('keyword'),row.get('country','global'),row.get('device','desktop'))].append(row)
    result=[]
    for key,items in groups.items():
        positions=[float(x.get('position',100) or 100) for x in sorted(items,key=lambda x:x.get('date',x.get('captured_at','')))]; change=(max(positions)-min(positions)) if positions else 0
        dates=[str(x.get('date',x.get('captured_at','')))[:10] for x in items]; correlated=any(date in set(update_dates or []) for date in dates)
        result.append({'keyword':key[0],'country':key[1],'device':key[2],'volatility':round(change,2),'lost':positions[-1]>positions[0] if positions else False,'gained':positions[-1]<positions[0] if positions else False,'update_correlation':correlated})
    return {'rows':result,'volatile_keywords':sum(x['volatility']>=5 for x in result)}

def brand_monitor(mentions, reviews=None):
    sentiment=Counter(); unlinked=[]
    for row in mentions or []:
        sentiment[str(row.get('sentiment','neutral'))]+=1
        if not row.get('linked') and row.get('brand'): unlinked.append(row)
    branded=sum(1 for row in mentions or [] if row.get('branded',row.get('brand') is not None)); knowledge=sum(1 for row in mentions or [] if row.get('knowledge_panel') or row.get('knowledge_graph'))
    return {'mentions':len(mentions or []),'sentiment':dict(sentiment),'unlinked_mentions':unlinked,'reviews':reviews or [],'review_count':len(reviews or []),'branded_mentions':branded,'knowledge_panel_observations':knowledge}

def rich_results_bulk(rows):
    results=[]
    for row in rows or []:
        schema=row.get('json_ld') or row.get('schema') or []; schema=[schema] if isinstance(schema,dict) else schema; types=[x.get('@type') for x in schema if isinstance(x,dict)]; errors=[]
        if not schema: errors.append('missing_jsonld')
        for item in schema:
            if not isinstance(item,dict): continue
            kind=item.get('@type'); required={'Product':['name','offers'],'Article':['headline','author','datePublished'],'BreadcrumbList':['itemListElement']}.get(kind,[])
            errors.extend(f'{kind}.{field}_missing' for field in required if not item.get(field))
        results.append({'url':row.get('url'),'types':types,'eligible':bool(types and not errors),'errors':sorted(set(errors))})
    return {'rows':results,'eligible':sum(x['eligible'] for x in results),'invalid':sum(not x['eligible'] for x in results)}

def crawl_replay(events, url=None):
    selected=[x for x in events or [] if not url or x.get('url')==url]; network=sum(len(x.get('network',[]) or []) for x in selected); console=sum(len(x.get('console_errors',[]) or []) for x in selected); blocked=sum(len(x.get('blocked_requests',[]) or []) for x in selected)
    return {'url':url,'events':selected,'event_count':len(selected),'replayable':bool(selected),'network_requests':network,'console_errors':console,'blocked_requests':blocked,'hydration_mismatches':[x for x in selected if x.get('source_hash') and x.get('dom_hash') and x['source_hash']!=x['dom_hash']]}

def warehouse_export(rows, format='json'):
    if format=='json': return json.dumps(rows or [],sort_keys=True,default=str)
    if format=='csv':
        keys=sorted({key for row in rows or [] for key in row}); return ','.join(keys)+'\n'+'\n'.join(','.join(str(row.get(k,'')) for k in keys) for row in rows or [])
    raise ValueError('format must be json or csv')

def warehouse_query(rows, query):
    """Safe SQL-like SELECT over in-memory rows; no SQL engine or writes."""
    match=re.match(r'^\s*select\s+(.+?)\s+from\s+rows(?:\s+where\s+([A-Za-z_][\w]*)\s*(=|like)\s*["\']?([^"\']+?)["\']?\s*)?$',str(query or ''),re.I)
    if not match: raise ValueError('supported syntax: SELECT field[,field] FROM rows [WHERE field = value|LIKE value]')
    selected=[x.strip() for x in match.group(1).split(',')]; field,operator,value=match.group(2),match.group(3),match.group(4)
    result=[]
    for row in rows or []:
        if field:
            actual=str(row.get(field,'')); wanted=str(value).strip()
            if operator.lower()=='=' and actual.lower()!=wanted.lower(): continue
            if operator.lower()=='like' and wanted.lower().replace('%','') not in actual.lower(): continue
        result.append({key:row.get(key) for key in selected} if selected!=['*'] else dict(row))
    return {'query':query,'rows':result,'count':len(result),'read_only':True}

def product_intelligence(products, feed_items=None):
    findings=[]; feed_items=feed_items or []; catalog_ids={str(p.get('id')) for p in products or [] if p.get('id')}; feed_ids=[str(p.get('id')) for p in feed_items if p.get('id')]
    for p in products or []:
        if not p.get('stock',p.get('inventory',1)): findings.append({'url':p.get('url'),'type':'stockout','severity':'high'})
        if p.get('variant_count',0) and not p.get('canonical'): findings.append({'url':p.get('url'),'type':'variant_canonical_missing','severity':'medium'})
        if not p.get('price'): findings.append({'url':p.get('url'),'type':'price_missing','severity':'medium'})
        if not p.get('product_schema'): findings.append({'url':p.get('url'),'type':'product_schema_missing','severity':'medium'})
        indexable=p.get('indexable',p.get('robots','').lower() not in ('noindex','noindex, nofollow'))
        if p.get('stock',p.get('inventory',1)) and not indexable: findings.append({'url':p.get('url'),'type':'in_stock_not_indexable','severity':'high'})
    if feed_items:
        for item in feed_items:
            if not item.get('id'): findings.append({'url':item.get('url'),'type':'feed_id_missing','severity':'high'})
            if not item.get('url'): findings.append({'id':item.get('id'),'type':'feed_url_missing','severity':'high'})
            if item.get('availability') not in (None,'in_stock','out_of_stock','preorder'): findings.append({'id':item.get('id'),'type':'feed_availability_invalid','severity':'medium'})
        for duplicate in sorted(x for x,c in Counter(feed_ids).items() if c>1): findings.append({'id':duplicate,'type':'feed_duplicate_id','severity':'high'})
        for missing in sorted(catalog_ids-set(feed_ids)): findings.append({'id':missing,'type':'catalog_missing_from_feed','severity':'medium'})
    return {'products':len(products or []),'feed_items':len(feed_items),'findings':findings,'stockouts':sum(x['type']=='stockout' for x in findings),'feed_consistent':not any(x['type'].startswith('feed_') or x['type']=='catalog_missing_from_feed' for x in findings)}

def prioritize(issues, revenue=None):
    revenue=revenue or {}; result=[]
    for issue in issues or []:
        impact=float(issue.get('impact',issue.get('traffic_loss',0)) or 0)+float(revenue.get(issue.get('url'),0) or 0); difficulty=float(issue.get('difficulty',3) or 3); risk=float(issue.get('risk',1) or 1); score=round((impact+1)*risk/max(difficulty,1),4)
        level='critical' if score>=100 else 'high' if score>=25 else 'normal'; reason=[]
        if impact: reason.append('business_impact');
        if risk>1: reason.append('risk');
        if difficulty<=2: reason.append('easy_fix')
        result.append({**issue,'impact_score':score,'priority':level,'rationale':reason or ['low_signal']})
    ordered=sorted(result,key=lambda x:x['impact_score'],reverse=True); by_template=defaultdict(lambda:{'issues':0,'score':0.0})
    for item in ordered:
        template=item.get('template','unknown'); by_template[template]['issues']+=1; by_template[template]['score']+=item['impact_score']
    return {'issues':ordered,'templates':[{'template':key,'issues':value['issues'],'score':round(value['score'],4)} for key,value in sorted(by_template.items(),key=lambda pair:pair[1]['score'],reverse=True)],'count':len(ordered)}
