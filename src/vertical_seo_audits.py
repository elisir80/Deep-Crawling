"""Native vertical SEO audits for local, ecommerce, international and programmatic sites."""
from collections import Counter
from urllib.parse import urlparse
import re

def image_audit(rows):
    issues=[]
    for row in rows or []:
        for image in row.get('images',[]) or []:
            if isinstance(image,str): image={'src':image}
            if not image.get('alt'): issues.append({'url':row.get('url'),'src':image.get('src'),'issue':'missing_alt'})
            if image.get('bytes',0) and image['bytes'] > 300000: issues.append({'url':row.get('url'),'src':image.get('src'),'issue':'large_image'})
    return issues

def accessibility_seo_audit(rows):
    result=[]
    for row in rows or []:
        findings=row.get('accessibility') or []
        if isinstance(findings,dict): findings=[findings]
        result.append({'url':row.get('url'),'score':row.get('accessibility_score',100-len(findings)*10),
                       'issues':findings,'seo_risk':len(findings)>0})
    return result

def local_audit(rows):
    result=[]
    for row in rows or []:
        text=' '.join(str(row.get(k) or '') for k in ('content_text','json_ld','schema_org'))
        nap={key: bool(re.search(pattern,text,re.I)) for key,pattern in
             {'name':r'localbusiness|organization','address':r'address|street|city|postal',
              'phone':r'\+?\d[\d ()-]{7,}'}.items()}
        result.append({'url':row.get('url'),'nap':nap,'localbusiness_schema':nap['name'],
                       'issues':[key for key,value in nap.items() if not value]})
    return result

def ecommerce_audit(rows):
    result=[]
    for row in rows or []:
        schema=str(row.get('schema_org') or row.get('json_ld') or '')
        product='Product' in schema or bool(re.search(r'/product|/shop|/p/',row.get('url',''),re.I))
        issues=[] if not product else [x for x,ok in
          (('price',bool(re.search(r'price|offers',schema,re.I))),('availability',bool(re.search(r'availability|stock',schema,re.I)))) if not ok]
        result.append({'url':row.get('url'),'product_detected':product,'issues':issues})
    return result

def international_audit(rows):
    hreflang={}
    for row in rows or []:
        links=row.get('hreflang') or row.get('alternates') or []
        hreflang[row.get('url')]=links if isinstance(links,list) else [links]
    return [{'url':url,'alternate_count':len(links),'issues':['missing_hreflang'] if not links else []} for url,links in hreflang.items()]

def programmatic_audit(rows):
    by_pattern=Counter()
    for row in rows or []:
        path=urlparse(row.get('url','')).path
        pattern=re.sub(r'/\\d+','/:id',path)
        pattern=re.sub(r'/[^/]{20,}','/:slug',pattern)
        by_pattern[pattern]+=1
    return [{'pattern':pattern,'pages':count,'risk':'thin-template' if count>20 else 'normal'} for pattern,count in by_pattern.items()]

def competitor_content(rows, competitor_rows):
    def terms(data): return set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}', ' '.join(str(x.get(k) or '') for x in data for k in ('title','h1','content_text')).lower()))
    ours, theirs=terms(rows),terms(competitor_rows)
    return {'shared_terms':sorted(ours & theirs),'competitor_only_terms':sorted(theirs-ours),'ours_only_terms':sorted(ours-theirs),
            'coverage_percent':round(len(ours & theirs)*100/max(len(theirs),1),2)}

def product_feed_audit(feed_items, crawl_rows=None):
    crawled={r.get('url') for r in crawl_rows or []}; result=[]
    for item in feed_items or []:
        url=item.get('link') or item.get('url'); issues=[key for key in ('id','title','price','availability','image_link') if not item.get(key)]
        if url and crawled and url not in crawled: issues.append('not_in_crawl')
        result.append({'url':url,'id':item.get('id'),'issues':issues,'valid':not issues})
    return result

def local_citations(citations):
    fields=('name','address','phone'); normalized=[]
    baseline={key:str(citations[0].get(key,'')).strip().lower() for key in fields} if citations else {}
    for item in citations or []:
        values={key:str(item.get(key,'')).strip().lower() for key in fields}
        normalized.append({'source':item.get('source'),'consistent':values == baseline,
                           'missing':[k for k in fields if not item.get(k)]})
    return normalized

def hreflang_graph(rows):
    graph=[]; seen=set()
    for row in rows or []:
        links=row.get('hreflang') or []
        for link in links if isinstance(links,list) else []:
            if isinstance(link,dict):
                key=(row.get('url'),link.get('lang') or link.get('hreflang'),link.get('href'))
                graph.append({'source':row.get('url'),'lang':key[1],'target':key[2],'return_link':False})
                seen.add((key[2],key[1],row.get('url')))
    for item in graph: item['return_link']=(item['target'],item['lang'],item['source']) in seen
    return {'links':graph,'issues':[x for x in graph if not x['return_link']]}

def javascript_sitemap_discovery(rendered_pages):
    discovered=[]
    for page in rendered_pages or []:
        for url in re.findall(r"(?:href|src)=['\"]([^'\"]+)",str(page.get('html','')),re.I):
            if url.startswith(('http://','https://','/')): discovered.append({'source':page.get('url'),'url':url,'rendered':True})
    return discovered

def multi_location_dashboard(locations):
    return [{'location':item.get('name') or item.get('id'),'citations':item.get('citations',0),
             'pages':len(item.get('rows',[])),'issues':sum(len(x.get('issues',[])) for x in item.get('audit',[]))}
            for item in locations or []]
