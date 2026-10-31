"""Native commerce, geo, AI citation and deployment validation tools."""
from collections import defaultdict
from urllib.parse import urlparse

def ai_citation_ownership(prompts, brand, citations=None):
    citations=citations or []
    result=[]
    for prompt in prompts or []:
        cited=[x for x in citations if x.get('prompt')==prompt]
        owned=sum(1 for x in cited if brand.lower() in str(x.get('source','')).lower())
        result.append({'prompt':prompt,'citations':len(cited),'owned_citations':owned,
                       'ownership_percent':round(owned*100/max(len(cited),1),2)})
    return result

def hallucination_monitor(responses, trusted_facts):
    facts={str(x).lower() for x in trusted_facts or []}; result=[]
    for response in responses or []:
        claims=response.get('claims',[])
        unsupported=[claim for claim in claims if str(claim).lower() not in facts]
        result.append({'provider':response.get('provider'),'unsupported_claims':unsupported,
                       'risk':'high' if unsupported else 'low'})
    return result

def margin_optimizer(products, sessions=1000):
    result=[]
    for product in products or []:
        margin=float(product.get('margin',product.get('price',0)-product.get('cost',0)) or 0)
        traffic=float(product.get('traffic',0) or 0); conversion=float(product.get('conversion_rate',0) or 0)
        value=traffic*conversion*margin/max(sessions,1)
        result.append({'url':product.get('url'),'margin':margin,'seo_value':round(value,4),
                       'priority':'high' if value>=0.1 else 'normal'})
    return sorted(result,key=lambda x:x['seo_value'],reverse=True)

def inventory_canonical(products):
    result=[]
    for item in products or []:
        stock=float(item.get('stock',0) or 0); canonical=item.get('canonical') or item.get('url')
        if stock<=0 and item.get('alternative_url'): canonical=item['alternative_url']
        result.append({'url':item.get('url'),'canonical':canonical,'in_stock':stock>0,'status':'index' if stock>0 else 'consolidate'})
    return result

def hreflang_deployment_check(rows):
    issues=[]
    for row in rows or []:
        links=row.get('hreflang') or []
        languages={x.get('lang') for x in links if isinstance(x,dict)}
        if row.get('required_languages') and not set(row['required_languages']).issubset(languages):
            issues.append({'url':row.get('url'),'missing':sorted(set(row['required_languages'])-languages)})
    return {'passed':not issues,'issues':issues}

def geo_test(urls, markets, expected_language=None):
    return [{'url':url,'market':market,'expected_language':expected_language,'status':'queued'} for market in markets or [] for url in urls or []]

def cdn_indexability_conflicts(rows):
    result=[]
    for row in rows or []:
        headers=row.get('http_headers') or {}; edge=row.get('edge_headers') or {}
        if headers.get('x-robots-tag') != edge.get('x-robots-tag') or headers.get('cache-control') != edge.get('cache-control'):
            result.append({'url':row.get('url'),'issue':'origin_edge_header_conflict','origin':headers,'edge':edge})
    return result
