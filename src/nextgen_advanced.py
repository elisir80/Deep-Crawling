"""Advanced next-generation SEO analysis over local snapshots."""
from collections import defaultdict
import hashlib
import json


def serp_screenshot_archive(snapshots, pixel_threshold=0):
    archive = []
    for snapshot in snapshots or []:
        html = str(snapshot.get('html', snapshot.get('content', '')))
        digest = hashlib.sha256(html.encode()).hexdigest()
        archive.append({'id': snapshot.get('id', snapshot.get('timestamp')), 'query': snapshot.get('query'),
                        'market': snapshot.get('market'), 'hash': digest, 'html': html,
                        'pixel_diff_percent': float(snapshot.get('pixel_diff_percent', 0) or 0)})
    diffs = []
    for previous, current in zip(archive, archive[1:]):
        diffs.append({'from': previous['id'], 'to': current['id'], 'changed': previous['hash'] != current['hash'],
                      'pixel_diff_percent': current['pixel_diff_percent'],
                      'alert': current['pixel_diff_percent'] > float(pixel_threshold)})
    return {'snapshots': archive, 'diffs': diffs, 'archive_mode': 'content_hash_plus_visual_metadata'}


def intent_drift_detector(previous, current):
    old = {str(x.get('keyword')): x.get('intent') for x in previous or []}
    changes = []
    for row in current or []:
        keyword = str(row.get('keyword'))
        if keyword in old and old[keyword] != row.get('intent'):
            changes.append({'keyword': keyword, 'before': old[keyword], 'after': row.get('intent'), 'drift': True})
    return {'changed': len(changes), 'drifts': changes, 'method': 'snapshot_intent_comparison'}


def large_migration_rehearsal(before, after, redirects=None, batch_size=10000):
    redirects = redirects or {}; old = {x.get('url'): x for x in before or [] if x.get('url')}; new = {x.get('url'): x for x in after or [] if x.get('url')}
    missing = [url for url in old if url not in new and url not in redirects]
    redirect_errors = [{'url': url, 'target': target, 'issue': 'self_redirect' if url == target else 'ok'} for url, target in redirects.items()]
    batches = max(1, (max(len(old), len(new)) + int(batch_size) - 1) // int(batch_size))
    return {'url_count_before': len(old), 'url_count_after': len(new), 'missing_count': len(missing),
            'missing_sample': missing[:100], 'redirects_checked': len(redirects), 'redirect_errors': [x for x in redirect_errors if x['issue'] != 'ok'],
            'batches': batches, 'passed': not missing and not [x for x in redirect_errors if x['issue'] != 'ok'], 'mode': 'rehearsal_only'}


def knowledge_graph_conflicts(rows):
    result = []
    for row in rows or []:
        sources = {name: set(row.get(name, []) or []) for name in ('schema_entities', 'content_entities', 'wikidata_entities', 'knowledge_graph_entities')}
        values = set().union(*sources.values())
        conflicts = sorted(value for value in values if sum(value in source for source in sources.values()) == 1)
        if conflicts: result.append({'entity': row.get('entity', row.get('url')), 'conflicts': conflicts, 'sources': {key: sorted(value) for key, value in sources.items()}})
    return {'conflicts': result, 'passed': not result}


def crawl_budget_optimizer(urls, budget=100, learning_rate=.1, iterations=3):
    scores = {row.get('url'): float(row.get('priority', 0) or 0) + float(row.get('change_rate', 0) or 0) * 10 for row in urls or [] if row.get('url')}
    for _ in range(max(0, int(iterations))):
        for row in urls or []:
            url = row.get('url')
            if url in scores:
                reward = float(row.get('observed_value', row.get('traffic', 0)) or 0)
                scores[url] += float(learning_rate) * reward / max(sum(scores.values()), 1)
    queue = sorted(scores, key=scores.get, reverse=True)[:int(budget)]
    return {'budget': int(budget), 'queue': queue, 'scores': [{'url': url, 'score': round(scores[url], 6)} for url in queue],
            'policy': 'adaptive_local_bandit', 'iterations': int(iterations), 'external_training': False}
