"""Local crawl analysis utilities for architecture and change detection."""
import math
import re
import requests
from collections import Counter


def orphan_pages(urls, links=None):
    links = links or []
    linked_targets = {link.get('target_url') for link in links if link.get('target_url')}
    return [url for url in urls if url.get('url') not in linked_targets and url.get('depth', 0) > 0]


def detect_changes(old_urls, new_urls):
    old = {row.get('url'): row for row in old_urls}
    new = {row.get('url'): row for row in new_urls}
    fields = ('status_code', 'title', 'meta_description', 'h1', 'canonical_url', 'robots', 'word_count')
    changes = []
    for url in sorted(set(old) | set(new)):
        if url not in old:
            changes.append({'url': url, 'type': 'added', 'changes': {}})
        elif url not in new:
            changes.append({'url': url, 'type': 'removed', 'changes': {}})
        else:
            diff = {field: {'old': old[url].get(field), 'new': new[url].get(field)}
                    for field in fields if old[url].get(field) != new[url].get(field)}
            if diff:
                changes.append({'url': url, 'type': 'changed', 'changes': diff})
    return changes


def semantic_search(urls, query, limit=20):
    """Rank pages using a small local TF-IDF cosine similarity index."""
    query_tokens = _tokens(query)
    def document_text(row):
        content_analysis = row.get('content_analysis') or {}
        content_text = row.get('content_text') or content_analysis.get('content_text', '')
        return ' '.join(str(row.get(field, '')) for field in ('title', 'meta_description', 'h1')) + ' ' + str(content_text)
    documents = [_tokens(document_text(row)) for row in urls]
    vocabulary = set(query_tokens)
    for document in documents:
        vocabulary.update(document)
    vocabulary = list(vocabulary)
    if not vocabulary:
        return []
    document_frequency = {term: sum(term in document for document in documents) for term in vocabulary}

    def vector(tokens):
        counts = Counter(tokens)
        # Keep a positive base weight for terms present in every document;
        # otherwise a one-page crawl makes every query score exactly zero.
        return {term: (counts[term] / max(len(tokens), 1)) * (1.0 + math.log((1 + len(documents)) / (1 + document_frequency[term]))) for term in vocabulary}
    q_vector = vector(query_tokens)
    q_norm = math.sqrt(sum(value * value for value in q_vector.values())) or 1
    ranked = []
    for row, document in zip(urls, documents):
        d_vector = vector(document)
        norm = math.sqrt(sum(value * value for value in d_vector.values())) or 1
        score = sum(q_vector[term] * d_vector[term] for term in vocabulary) / (q_norm * norm)
        if score > 0:
            ranked.append({'url': row.get('url'), 'score': round(score, 6), 'title': row.get('title', '')})
    return sorted(ranked, key=lambda item: item['score'], reverse=True)[:limit]


def embedding_search(urls, query, api_key, endpoint='https://api.openai.com/v1/embeddings', model='text-embedding-3-small', limit=20):
    """Rank crawl content with an OpenAI-compatible embeddings endpoint."""
    if not api_key:
        return {'success': False, 'error': 'api_key is required for embeddings'}
    texts = [' '.join(str(row.get(field, '')) for field in ('title', 'meta_description', 'h1', 'content_text'))[:12000] for row in urls]
    response = requests.post(endpoint, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                             json={'model': model, 'input': [query] + texts}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    vectors = [item['embedding'] for item in sorted(payload.get('data', []), key=lambda item: item.get('index', 0))]
    if len(vectors) != len(texts) + 1:
        return {'success': False, 'error': 'embedding provider returned an unexpected vector count'}
    query_vector = vectors[0]
    def cosine(vector):
        numerator = sum(a * b for a, b in zip(query_vector, vector))
        denom = math.sqrt(sum(a * a for a in query_vector)) * math.sqrt(sum(b * b for b in vector))
        return numerator / denom if denom else 0.0
    ranked = [{'url': row.get('url'), 'title': row.get('title', ''), 'score': round(cosine(vector), 6)}
              for row, vector in zip(urls, vectors[1:])]
    return {'success': True, 'results': sorted(ranked, key=lambda item: item['score'], reverse=True)[:limit], 'model': model}


def _tokens(value):
    return re.findall(r"[a-zà-ÿ0-9]{2,}", str(value).lower())
