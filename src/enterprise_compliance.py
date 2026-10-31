"""Explainable AI, reputation, local and commerce governance primitives."""
from collections import defaultdict
import re


def ai_approval_gate(item, trusted_facts=None, required_citations=1):
    """Return a deterministic publish decision; never publishes by itself."""
    trusted = {str(x).strip().lower() for x in (trusted_facts or [])}
    claims = [str(x) for x in item.get('claims', [])]
    unsupported = [x for x in claims if x.strip().lower() not in trusted]
    citations = item.get('citations') or []
    approved = bool(item.get('human_approved')) and not unsupported and len(citations) >= int(required_citations)
    return {'approved': approved, 'requires_human': True, 'unsupported_claims': unsupported,
            'citation_count': len(citations), 'provenance': item.get('provenance', 'unknown'),
            'decision': 'publish' if approved else 'hold'}


def authorship_provenance(items):
    return [{**item, 'author_type': item.get('author_type', 'human'),
             'traceable': bool(item.get('author') or item.get('source') or item.get('prompt_id')),
             'reviewed': bool(item.get('reviewed_by'))} for item in items or []]


def legal_content_scan(rows, copyrighted_terms=None):
    terms = [str(x).lower() for x in (copyrighted_terms or [])]
    findings = []
    for row in rows or []:
        text = str(row.get('content_text', '')).lower()
        matches = [term for term in terms if term and term in text]
        if row.get('copyright_risk') or row.get('missing_attribution') or matches:
            findings.append({'url': row.get('url'), 'copyright_matches': matches,
                             'missing_attribution': bool(row.get('missing_attribution')),
                             'severity': 'high' if row.get('copyright_risk') else 'medium'})
    return {'passed': not findings, 'findings': findings, 'evidence_required': True}


def brand_safety_scan(rows, blocked_terms=None):
    terms = [str(x).lower() for x in (blocked_terms or ['hate', 'fraud', 'malware'])]
    result = []
    for row in rows or []:
        text = str(row.get('text', row.get('content_text', ''))).lower()
        hits = sorted({term for term in terms if re.search(r'\b' + re.escape(term) + r'\b', text)})
        if hits:
            result.append({'id': row.get('id', row.get('url')), 'matches': hits, 'severity': 'high'})
    return {'safe': not result, 'findings': result}


def knowledge_panel_monitor(previous, current):
    fields = ('name', 'description', 'image', 'url', 'sameAs', 'type')
    changes = []
    for field in fields:
        if (previous or {}).get(field) != (current or {}).get(field):
            changes.append({'field': field, 'before': (previous or {}).get(field), 'after': (current or {}).get(field)})
    return {'changed': bool(changes), 'changes': changes, 'requires_review': bool(changes)}


def entity_reputation(rows, entity):
    mentions = [r for r in rows or [] if entity.lower() in str(r.get('text', '')).lower()]
    sentiment = sum(float(r.get('sentiment_score', 0) or 0) for r in mentions)
    return {'entity': entity, 'mentions': len(mentions), 'sentiment_score': round(sentiment, 4),
            'negative_ratio': round(sum(1 for r in mentions if float(r.get('sentiment_score', 0) or 0) < 0) / max(len(mentions), 1), 3)}


def local_competitor_monitor(previous, current):
    old = {x.get('business_id', x.get('name')): x for x in previous or []}
    actions = []
    for item in current or []:
        key = item.get('business_id', item.get('name'))
        if key not in old:
            actions.append({'business': key, 'action': 'new'})
        elif old[key].get('rank') != item.get('rank'):
            actions.append({'business': key, 'action': 'rank_change', 'from': old[key].get('rank'), 'to': item.get('rank')})
    return actions


def map_volatility(snapshots):
    grouped = defaultdict(list)
    for row in snapshots or []:
        grouped[row.get('keyword', '')].append(float(row.get('rank', 0) or 0))
    return [{'keyword': key, 'observations': len(values), 'volatility': round(max(values) - min(values), 3) if values else 0,
             'alert': bool(values and max(values) - min(values) >= 3)} for key, values in grouped.items()]


def marketplace_audit(products, required_fields=None):
    required_fields = required_fields or ['id', 'title', 'price', 'availability', 'url']
    result = []
    for product in products or []:
        missing = [field for field in required_fields if not product.get(field)]
        result.append({'id': product.get('id', product.get('url')), 'missing': missing,
                       'valid': not missing, 'repairable': bool(missing)})
    return {'valid': all(x['valid'] for x in result), 'products': result}


def feed_sitemap_canonical_graph(feed, sitemap, pages):
    feed_urls = {x.get('url') for x in feed or []}
    sitemap_urls = {x.get('url') if isinstance(x, dict) else x for x in sitemap or []}
    conflicts = []
    for page in pages or []:
        url = page.get('url')
        canonical = page.get('canonical', url)
        if url in sitemap_urls and canonical not in sitemap_urls:
            conflicts.append({'url': url, 'issue': 'sitemap_canonical_mismatch', 'canonical': canonical})
    return {'feed_only': sorted(feed_urls - sitemap_urls), 'sitemap_only': sorted(sitemap_urls - feed_urls),
            'conflicts': conflicts, 'passed': not conflicts}
