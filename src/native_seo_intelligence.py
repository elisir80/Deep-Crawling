"""Native SEO intelligence derived only from LibreCrawl crawl data."""
from collections import Counter
from datetime import datetime
import math
import re
from urllib.parse import urlparse

CTR = {1: .285, 2: .155, 3: .11, 4: .08, 5: .06, 6: .045, 7: .035, 8: .03, 9: .025, 10: .02}

def _words(row):
    text = ' '.join(str(row.get(k) or '') for k in ('title','h1','meta_description','content_text'))
    return set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}', text.lower()))

def keyword_index(rows):
    counts = Counter(word for row in rows for word in _words(row))
    return [{'keyword': word, 'documents': count,
             'difficulty': round(min(100, 12 + math.log1p(count) * 14), 2),
             'opportunity': round(min(100, 100 / (1 + math.log1p(count))), 2)}
            for word, count in counts.most_common()]

def authority_score(rows, links=None):
    rows = rows or []
    links = links or []
    domains = {urlparse(str(r.get('url') or '')).hostname for r in rows if r.get('url')}
    internal = sum(int(r.get('internal_links') or 0) for r in rows)
    external = sum(int(r.get('external_links') or 0) for r in rows)
    referring = len({urlparse(str(l.get('source_url') or '')).hostname for l in links if l.get('source_url')})
    quality = sum(1 for r in rows if r.get('status_code') == 200 and r.get('title') and r.get('meta_description'))
    score = min(100, 20 * math.log1p(referring or len(domains)) + 8 * math.log1p(internal) + 4 * math.log1p(external) + 0.25 * quality)
    return {'score': round(score, 2), 'label': 'native-authority', 'pages': len(rows),
            'referring_sources': referring, 'internal_links': internal, 'external_links': external,
            'note': 'Local estimate, not Ahrefs DR/UR.'}

def traffic_estimate(rankings):
    total = 0.0
    items = []
    for item in rankings or []:
        position = max(1, int(item.get('position', 100)))
        volume = max(0, float(item.get('search_volume', item.get('volume', 0)) or 0))
        value = volume * CTR.get(position, 0.01 if position <= 20 else 0.001)
        total += value
        items.append({**item, 'estimated_monthly_visits': round(value, 2)})
    return {'estimated_monthly_visits': round(total, 2), 'keywords': items,
            'note': 'Estimate based on supplied volumes and CTR model.'}

def record_ranking(rows, rankings, snapshot=None):
    snapshot = snapshot or datetime.utcnow().isoformat() + 'Z'
    return [{'snapshot': snapshot, 'url': row.get('url'), 'keyword': row.get('keyword'),
             'position': row.get('position'), 'source': row.get('source', 'imported')}
            for row in (rankings or [])]

def ai_prompt_for_seo(authority, keywords, traffic):
    return ('Analyze this native LibreCrawl SEO dataset. Return prioritized actions, '
            'uncertainty and assumptions as JSON. Dataset=' +
            str({'authority': authority, 'keywords': keywords[:100], 'traffic': traffic}))
