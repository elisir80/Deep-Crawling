"""Next-level native graph, SERP and safe-change tools."""
from collections import Counter, defaultdict
import re

def serp_visual_diff(previous_html, current_html):
    old=re.sub(r'\s+',' ',str(previous_html or '')).strip(); new=re.sub(r'\s+',' ',str(current_html or '')).strip()
    common=sum(1 for token in set(old.split()) if token in new)
    similarity=common/max(len(set(old.split())|set(new.split())),1)
    return {'similarity_percent':round(similarity*100,2),'changed':old!=new,
            'added_tokens':sorted(set(new.split())-set(old.split()))[:100],
            'removed_tokens':sorted(set(old.split())-set(new.split()))[:100]}

def cannibalization_plan(rows):
    groups=defaultdict(list)
    for row in rows or []:
        for term in set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{4,}',str(row.get('title','')+' '+str(row.get('h1',''))).lower())):
            groups[term].append(row)
    return [{'keyword':term,'primary_url':max(items,key=lambda x:x.get('traffic',0) or 0).get('url'),
             'merge_or_redirect':[x.get('url') for x in items[1:]],'action':'consolidate'} for term,items in groups.items() if len(items)>1]

def topical_benchmark(site_topics, competitor_topics):
    ours=set(site_topics or []); competitor=set(competitor_topics or [])
    return {'shared':sorted(ours&competitor),'missing':sorted(competitor-ours),'unique':sorted(ours-competitor),
            'coverage_percent':round(len(ours&competitor)*100/max(len(competitor),1),2)}

def pagerank_recommendations(rows, links, limit=50):
    scores=Counter(link.get('target_url') for link in links or [])
    suggestions=[]
    for row in rows or []:
        url=row.get('url'); terms=set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{4,}',str(row.get('content_text') or '').lower()))
        for target in rows or []:
            if target.get('url')==url: continue
            overlap=len(terms & set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{4,}',str(target.get('title','')).lower())))
            if overlap and scores[target.get('url')]<2: suggestions.append({'source':url,'target':target.get('url'),'score':overlap})
    return sorted(suggestions,key=lambda x:x['score'],reverse=True)[:limit]

def link_attack_detector(links):
    by_source=Counter(x.get('source_url') for x in links or []); by_target=Counter(x.get('target_url') for x in links or [])
    return [{'type':'source_burst','source_url':source,'count':count,'risk':'high'} for source,count in by_source.items() if count>100] + \
           [{'type':'target_spike','target_url':target,'count':count,'risk':'medium'} for target,count in by_target.items() if count>100]

def rollback_guardrail(before, after, thresholds=None):
    thresholds=thresholds or {'max_removed_urls':0,'max_status_errors':0}
    old={x.get('url') if isinstance(x,dict) else x for x in before or []}
    new={x.get('url') if isinstance(x,dict) else x for x in after or []}
    removed=len(old-new); errors=sum(1 for row in after or [] if isinstance(row,dict) and row.get('status_code') in (0,404,500))
    approved=removed<=thresholds['max_removed_urls'] and errors<=thresholds['max_status_errors']
    return {'approved':approved,'rollback_required':not approved,'removed_urls':removed,'status_errors':errors}

def evidence_snapshot(data):
    import hashlib,json
    payload=json.dumps(data,sort_keys=True,default=str).encode()
    return {'payload':data,'sha256':hashlib.sha256(payload).hexdigest()}
