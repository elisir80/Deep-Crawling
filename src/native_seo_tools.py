"""Native SEO tools operating on LibreCrawl data, with no third-party index."""
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

def _tokens(text):
    return set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}', str(text or '').lower()))

def serp_analyze(html, target_domain=None):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(); self.title=[]; self.links=[]; self.text=[]; self.in_title=False
        def handle_starttag(self, tag, attrs):
            attrs=dict(attrs)
            if tag == 'title': self.in_title=True
            if tag == 'a' and attrs.get('href'): self.links.append({'href':attrs['href'], 'text':''})
            if tag in ('h1','h2','h3','p','li'): self.text.append({'tag':tag,'text':''})
        def handle_endtag(self, tag):
            if tag == 'title': self.in_title=False
        def handle_data(self, data):
            if self.in_title: self.title.append(data)
            if self.links: self.links[-1]['text'] += data.strip()
            if self.text: self.text[-1]['text'] += data.strip()
    parser=Parser(); parser.feed(html or '')
    domain=(target_domain or '').lower()
    results=[]
    for link in parser.links:
        host=urlparse(link['href']).hostname or ''
        if not domain or domain in host.lower(): results.append(link)
    text=' '.join(x['text'] for x in parser.text)
    return {'title':' '.join(parser.title).strip(), 'results':results[:100],
            'featured_snippet': bool(re.search(r'(featured snippet|answer box)', text, re.I)),
            'people_also_ask': re.findall(r'[^.?!]{0,80}\\?', text)[:20],
            'result_count':len(results), 'external_result_count':len(parser.links)-len(results)}

def cluster_keywords(keywords):
    groups=defaultdict(list)
    for item in keywords:
        term=item.get('keyword',item) if isinstance(item,dict) else item
        words=_tokens(term); intent='informational'
        if words & {'buy','price','deal','shop','service','hire'}: intent='transactional'
        elif words & {'best','compare','review','top','alternative'}: intent='commercial'
        elif words & {'login','official','brand','contact'}: intent='navigational'
        groups[intent].append({'keyword':term,'tokens':sorted(words)})
    return [{'intent':key,'keywords':value,'count':len(value)} for key,value in groups.items()]

def cannibalization(rows):
    by_term=defaultdict(list)
    for row in rows:
        terms=_tokens(' '.join(str(row.get(k) or '') for k in ('title','h1','meta_description')))
        for term in terms: by_term[term].append(row.get('url'))
    return [{'keyword':term,'urls':sorted(set(urls)),'severity':'high' if len(set(urls))>2 else 'medium'}
            for term,urls in by_term.items() if len(set(urls))>1]

def internal_link_suggestions(rows, links, limit=50):
    pages={row.get('url'): _tokens(' '.join(str(row.get(k) or '') for k in ('title','h1','content_text'))) for row in rows}
    incoming=Counter(link.get('target_url') for link in links)
    suggestions=[]
    for source, source_words in pages.items():
        for target, target_words in pages.items():
            if source == target or not target_words: continue
            overlap=len(source_words & target_words)
            if overlap and incoming[target] < 2:
                suggestions.append({'source_url':source,'target_url':target,'score':overlap,'suggested_anchor': ' '.join(sorted(source_words & target_words)[:5])})
    return sorted(suggestions,key=lambda x:x['score'],reverse=True)[:limit]

def content_decay(previous, current):
    old={r.get('url'):r for r in previous}; changed=[]
    for row in current:
        before=old.get(row.get('url'))
        if not before: continue
        old_words=before.get('word_count') or len(_tokens(before.get('content_text')))
        new_words=row.get('word_count') or len(_tokens(row.get('content_text')))
        if old_words and new_words < old_words * .8:
            changed.append({'url':row.get('url'),'previous_words':old_words,'current_words':new_words,'loss_percent':round((old_words-new_words)*100/old_words,2)})
    return changed

def content_brief(keyword, rows, questions=None):
    terms=Counter(word for row in rows for word in _tokens(row.get('content_text') or row.get('title')))
    return {'keyword':keyword,'recommended_intent':'informational','terms':[x for x,_ in terms.most_common(30)],
            'questions':questions or [],'recommended_sections':['Overview','Key considerations','How to choose','FAQ']}

def rank_snapshot(keyword, url, position, country='global', device='desktop', features=None, competitor=None):
    return {'keyword':keyword,'url':url,'position':int(position),'country':country,'device':device,
            'serp_features':features or [],'competitor':competitor,'captured_at':datetime.utcnow().isoformat()+'Z'}

def rank_tracker_report(snapshots, keyword=None, country=None, device=None):
    """Aggregate local rank history without claiming access to a search index."""
    rows=[row for row in (snapshots or []) if (not keyword or row.get('keyword')==keyword)
          and (not country or row.get('country')==country) and (not device or row.get('device')==device)]
    groups=defaultdict(list)
    competitors=defaultdict(list)
    for row in rows:
        key=(row.get('keyword',''),row.get('country','global'),row.get('device','desktop'))
        if row.get('competitor') or row.get('domain'):
            competitors[key].append(row)
        else:
            groups[key].append(row)
    result=[]
    for key, items in groups.items():
        ordered=sorted(items,key=lambda x:x.get('captured_at',''))
        first=float(ordered[0].get('position',100) or 100); last=float(ordered[-1].get('position',100) or 100)
        features=sorted({feature for item in ordered for feature in (item.get('serp_features') or [])})
        result.append({'keyword':key[0],'country':key[1],'device':key[2],'url':ordered[-1].get('url'),
                       'snapshots':len(ordered),'first_position':first,'last_position':last,
                       'position_change':round(first-last,2),'serp_features':features,
                       'ai_overview': 'ai_overview' in features or 'ai-overview' in features})
    competitor_rows=[]
    for key, items in competitors.items():
        ordered=sorted(items,key=lambda x:x.get('captured_at',''))
        competitor_rows.append({'keyword':key[0],'country':key[1],'device':key[2],
                                'competitor':ordered[-1].get('competitor') or ordered[-1].get('domain'),
                                'last_position':float(ordered[-1].get('position',100) or 100),'snapshots':len(ordered)})
    return {'filters':{'keyword':keyword,'country':country,'device':device},'rows':result,'competitors':competitor_rows,'count':len(result)}
