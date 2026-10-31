"""Native AEO visibility, AI crawler policy and crawl-space diagnostics."""
from collections import Counter
from urllib.parse import parse_qs, urlparse
import re

AI_BOTS=('GPTBot','ClaudeBot','PerplexityBot','Google-Extended','anthropic-ai')

def prompt_visibility(prompt, responses, brand_terms):
    terms={str(x).lower() for x in brand_terms or []}
    rows=[]
    for response in responses or []:
        text=str(response.get('text',response)).lower()
        mentions=sorted(term for term in terms if term in text)
        citations=response.get('citations',[]) if isinstance(response,dict) else []
        rows.append({'provider':response.get('provider','unknown') if isinstance(response,dict) else 'unknown',
                     'mentions':mentions,'mentioned':bool(mentions),'citations':citations,
                     'visibility_score':round((50 if mentions else 0)+(50 if citations else 0),2)})
    return {'prompt':prompt,'providers':rows,'visibility_percent':round(sum(r['visibility_score'] for r in rows)/max(len(rows),1),2)}

def brand_mentions(documents, brand_terms):
    result=[]
    for doc in documents or []:
        text=str(doc.get('text','')); found=sorted(term for term in brand_terms or [] if term.lower() in text.lower())
        if found: result.append({'url':doc.get('url'),'mentions':found,'sentiment':'neutral','link_present':bool(doc.get('link'))})
    return result

def ai_crawler_policy(robots_text, allowed_bots=None):
    allowed=set(allowed_bots or AI_BOTS); policies={}
    for bot in AI_BOTS:
        block=bool(re.search(r'User-agent:\\s*'+re.escape(bot)+r'\\s*\\n(?:Disallow:\\s*([^\\n]*)\\n?)+',robots_text or '',re.I))
        policies[bot]={'allowed':not block,'configured':bot in (robots_text or '')}
    return {'policies':policies,'recommended_user_agents':sorted(allowed)}

def crawl_space_audit(urls):
    params=Counter(); patterns=Counter(); traps=[]
    for url in urls or []:
        parsed=urlparse(url); query=parse_qs(parsed.query)
        for key in query: params[key]+=1
        path=re.sub(r'/\\d+','/:id',parsed.path); path=re.sub(r'/[^/]{20,}','/:slug',path); patterns[path]+=1
        if len(query)>3 or len(parsed.path.split('/'))>12: traps.append({'url':url,'reason':'high_parameter_or_depth'})
    return {'parameter_frequency':dict(params),'path_patterns':patterns.most_common(100),'crawl_traps':traps,
            'faceted_parameters':[key for key,count in params.items() if count>10]}

def pagination_audit(rows):
    result=[]
    for row in rows or []:
        url=row.get('url',''); has_next=bool(row.get('next') or row.get('pagination_next'))
        if re.search(r'[?&]page=|/page/\d+',url,re.I) and not has_next:
            result.append({'url':url,'issue':'paginated_url_without_next_link'})
    return result
