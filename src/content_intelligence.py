"""Native entity, topical, authorship and content intelligence."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import re

def entities(rows):
    output=[]
    for row in rows or []:
        schema=row.get('schema_org') or row.get('json_ld') or []
        types=[]
        if isinstance(schema,dict): schema=[schema]
        for item in schema if isinstance(schema,list) else []:
            if isinstance(item,dict) and item.get('@type'): types += item['@type'] if isinstance(item['@type'],list) else [item['@type']]
        terms=re.findall(r'\\b[A-Z][a-zA-ZÀ-ÿ]{2,}(?:\\s+[A-Z][a-zA-ZÀ-ÿ]{2,})*',str(row.get('content_text') or row.get('title') or ''))
        output.append({'url':row.get('url'),'schema_types':sorted(set(types)),'named_entities':sorted(set(terms))})
    return output

def topical_map(rows):
    topics=defaultdict(list)
    for row in rows or []:
        words=re.findall(r'[a-zA-ZÀ-ÿ0-9]{4,}',str(row.get('content_text') or row.get('title') or '').lower())
        for word in set(words): topics[word].append(row.get('url'))
    return [{'topic':topic,'pages':sorted(set(pages)),'authority':min(100,len(set(pages))*10)} for topic,pages in sorted(topics.items(),key=lambda x:len(set(x[1])),reverse=True)[:100]]

def semantic_score(row, target_terms):
    text=set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}',str(row.get('content_text') or '').lower()))
    terms=set(str(x).lower() for x in target_terms or [])
    return {'url':row.get('url'),'score':round(len(text&terms)*100/max(len(terms),1),2),'missing_terms':sorted(terms-text)}

def eat_audit(rows):
    result=[]
    for row in rows or []:
        text=str(row.get('content_text') or '') + ' ' + str(row.get('schema_org') or '')
        signals={'author':bool(re.search(r'author|written by|about the author',text,re.I)),
                 'experience':bool(re.search(r'experience|case study|tested',text,re.I)),
                 'citations':bool(row.get('external_links') or re.search(r'https?://',text)),
                 'organization':bool(re.search(r'organization|publisher|localbusiness',text,re.I))}
        result.append({'url':row.get('url'),'signals':signals,'score':round(sum(signals.values())*25,2)})
    return result

def near_duplicates(rows, threshold=0.85):
    def words(row): return set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}',str(row.get('content_text') or '').lower()))
    result=[]
    for i,left in enumerate(rows or []):
        for right in (rows or [])[i+1:]:
            a,b=words(left),words(right); similarity=len(a&b)/max(len(a|b),1)
            if similarity >= threshold: result.append({'urls':[left.get('url'),right.get('url')],'similarity':round(similarity,4)})
    return result

def freshness(rows, now=None):
    now=now or datetime.utcnow().date()
    result=[]
    for row in rows or []:
        value=row.get('lastmod') or row.get('published_at') or row.get('crawled_at')
        age=None
        if value:
            try: age=(now-datetime.fromisoformat(str(value)[:10]).date()).days
            except Exception: pass
        result.append({'url':row.get('url'),'age_days':age,'status':'stale' if age is not None and age>365 else 'fresh'})
    return result

def editorial_plan(rows, cadence_days=14):
    stale=[item for item in freshness(rows) if item['status']=='stale']
    return [{'url':item['url'],'due_in_days':index*cadence_days,'action':'refresh_content'} for index,item in enumerate(stale)]

def citation_fact_audit(rows):
    result=[]
    for row in rows or []:
        text=str(row.get('content_text') or '')
        citations=re.findall(r"https?://[^\s<>\"']+",text)
        claims=re.findall(r'\\b(?:according to|study|research|data shows|source)\\b',text,re.I)
        result.append({'url':row.get('url'),'citations':citations,'verifiable_claims':len(claims),
                       'citation_coverage':bool(citations) if claims else True})
    return result

def schema_graph(rows):
    nodes=[]; edges=[]
    for row in rows or []:
        for item in row.get('schema_org',[]) if isinstance(row.get('schema_org'),list) else []:
            if isinstance(item,dict):
                node=item.get('@id') or row.get('url'); node_type=item.get('@type')
                nodes.append({'id':node,'type':node_type,'url':row.get('url')})
                for key,value in item.items():
                    if key.startswith('@') or not isinstance(value,dict): continue
                    edges.append({'from':node,'property':key,'to':value.get('@id') or value.get('name')})
    return {'nodes':nodes,'edges':edges}
