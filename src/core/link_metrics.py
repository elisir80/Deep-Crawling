"""Local internal-link metrics, independent of third-party backlink APIs."""
from collections import Counter, defaultdict


def calculate_link_metrics(urls, links):
    inlinks = Counter()
    outlinks = Counter()
    sources = defaultdict(set)
    for link in links or []:
        source, target = link.get('source_url'), link.get('target_url')
        if source and target:
            outlinks[source] += 1
            inlinks[target] += 1
            sources[target].add(source)
    max_inlinks = max(inlinks.values(), default=1)
    metrics = []
    for row in urls or []:
        url = row.get('url')
        incoming, outgoing = inlinks[url], outlinks[url]
        depth = row.get('depth', 0) or 0
        score = round((incoming / max_inlinks) * 0.7 + (1 / (1 + depth)) * 0.3, 4)
        metrics.append({'url': url, 'inlinks': incoming, 'outlinks': outgoing,
                        'depth': depth, 'link_score': score,
                        'linked_from': sorted(sources.get(url, set()))})
    return sorted(metrics, key=lambda item: item['link_score'], reverse=True)

def backlink_quality_audit(links, known_domains=None):
    known=set(known_domains or []); result=[]
    for link in links or []:
        domain=link.get('target_domain') or ''
        toxic=bool(link.get('status_code') in (404,410) or link.get('nofollow') is False and domain in known)
        result.append({'source_url':link.get('source_url'),'target_url':link.get('target_url'),
                       'lost':link.get('target_status') in (404,410),'toxic':toxic,
                       'competitor':domain in known})
    return result
