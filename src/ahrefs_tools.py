"""Local, index-independent equivalents of common Ahrefs workflows."""
from collections import Counter, defaultdict
from urllib.parse import urlparse
import re

def _domain(url): return (urlparse(url).hostname or '').lower()
def _words(row):
    text = ' '.join(str(row.get(k) or '') for k in ('title','h1','meta_description','content_text'))
    return set(re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", text.lower()))

def batch_analysis(rows):
    return [{'url': r.get('url'), 'domain': _domain(r.get('url','')), 'status_code': r.get('status_code'),
             'title': r.get('title',''), 'word_count': r.get('word_count',0),
             'inlinks': r.get('inlinks', r.get('internal_links',0)),
             'outlinks': r.get('outlinks', r.get('external_links',0))} for r in rows]

def domain_comparison(datasets):
    result = []
    for name, rows in datasets.items():
        words = set(); urls = set(); links = 0
        for row in rows:
            urls.add(row.get('url')); words |= _words(row); links += int(row.get('internal_links') or 0)
        result.append({'name': name, 'urls': len(urls), 'unique_terms': len(words), 'internal_links': links})
    return result

def content_gap(datasets, min_count=1):
    terms = defaultdict(set)
    for name, rows in datasets.items():
        for row in rows:
            for word in _words(row): terms[word].add(name)
    return [{'term': term, 'domains': sorted(names), 'missing_from': sorted(set(datasets)-names)}
            for term, names in terms.items() if len(names) >= min_count]

def link_intersect(link_sets):
    counts = Counter(target for links in link_sets.values() for target in {l.get('target_url') for l in links})
    return [{'target_url': url, 'sources': sorted(name for name, links in link_sets.items()
             if url in {l.get('target_url') for l in links}), 'count': count}
            for url, count in counts.most_common() if count >= 2]

def keyword_opportunities(rows, limit=100):
    counts = Counter(word for row in rows for word in _words(row))
    return [{'keyword': word, 'frequency': count} for word, count in counts.most_common(limit)]
