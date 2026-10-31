"""Local governance, search-index and reproducible-report primitives."""
import hashlib
import json
import re
from collections import defaultdict


def identity_policy(config):
    return {'sso_enabled': bool(config.get('sso_provider')), 'scim_enabled': bool(config.get('scim_endpoint')),
            'provider': config.get('sso_provider'), 'scim_endpoint': config.get('scim_endpoint'),
            'mfa_required': bool(config.get('mfa_required', True)), 'status': 'configured' if config.get('sso_provider') else 'local-only'}


def mask_fields(rows, fields=None):
    fields = set(fields or ['email', 'ip', 'user_id', 'cookie_id'])
    result = []
    for row in rows or []:
        result.append({key: ('[REDACTED]' if key in fields else value) for key, value in row.items()})
    return result


def federated_aggregate(partitions, metric='value'):
    totals = defaultdict(float)
    counts = defaultdict(int)
    for partition in partitions or []:
        for row in partition.get('rows', []):
            key = row.get('dimension', 'all')
            totals[key] += float(row.get(metric, 0) or 0)
            counts[key] += 1
    return {'aggregated': [{'dimension': key, 'value': round(value, 4), 'count': counts[key]} for key, value in totals.items()],
            'raw_rows_retained': False, 'privacy_mode': 'federated'}


def local_index(rows, query=None):
    index = defaultdict(set)
    for row in rows or []:
        text = ' '.join(str(row.get(field, '')) for field in ('url', 'title', 'content_text')).lower()
        for token in re.findall(r'[\w-]{2,}', text):
            index[token].add(row.get('url'))
    if query is None:
        return {'documents': len({url for urls in index.values() for url in urls}), 'terms': len(index), 'mode': 'self-hosted-local'}
    tokens = re.findall(r'[\w-]{2,}', str(query).lower())
    matches = set.intersection(*(index.get(token, set()) for token in tokens)) if tokens else set()
    return {'query': query, 'urls': sorted(matches), 'mode': 'self-hosted-local'}


def certify_plugin(plugin, trusted_scopes=None):
    trusted_scopes = set(trusted_scopes or ['read', 'analyze'])
    scopes = set(plugin.get('scopes', []))
    signature = str(plugin.get('signature', ''))
    digest = hashlib.sha256(json.dumps(plugin, sort_keys=True, default=str).encode()).hexdigest()
    return {'id': plugin.get('id'), 'certificate': digest, 'signed': bool(signature),
            'scopes_allowed': scopes <= trusted_scopes, 'sandboxed': True,
            'status': 'certified' if signature and scopes <= trusted_scopes else 'rejected'}


def reproducible_report(report, inputs=None, model=None):
    payload = {'report': report, 'inputs': inputs or {}, 'model': model or 'deterministic-local'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return {'report': report, 'inputs_hash': hashlib.sha256(json.dumps(inputs or {}, sort_keys=True, default=str).encode()).hexdigest(),
            'report_hash': digest, 'model': payload['model'], 'reproducible': True, 'evidence_required': True}


def knowledge_base(decisions, query=None):
    if query is None:
        return {'entries': len(decisions or []), 'topics': sorted({str(x.get('topic')) for x in decisions or [] if x.get('topic')})}
    terms = set(str(query).lower().split())
    return [x for x in decisions or [] if terms & set(str(x.get('topic', '')).lower().split()) or terms & set(str(x.get('decision', '')).lower().split())]


def penalty_risk(rows):
    result = []
    for row in rows or []:
        signals = [key for key in ('manual_action', 'spam_signal', 'cloaking', 'unnatural_links') if row.get(key)]
        result.append({**row, 'risk_signals': signals, 'risk': 'high' if len(signals) >= 2 else 'medium' if signals else 'low'})
    return sorted(result, key=lambda x: len(x['risk_signals']), reverse=True)


def procurement_questionnaire(config):
    checks = {'encryption_at_rest': bool(config.get('encryption_key')), 'sso': bool(config.get('sso_provider')),
              'scim': bool(config.get('scim_endpoint')), 'audit_logs': bool(config.get('audit_logs', True)),
              'backup': bool(config.get('backup_region')), 'data_residency': bool(config.get('residency'))}
    return {'checks': checks, 'passed': all(checks.values()), 'evidence_required': [key for key, value in checks.items() if not value]}


def review_response_plan(reviews, approved=False):
    result = []
    for review in reviews or []:
        rating = int(review.get('rating', 3) or 3)
        result.append({'id': review.get('id'), 'response': ('Thank you for your feedback; we are reviewing it.' if rating >= 3 else 'We are sorry your experience fell short; our team will investigate and contact you.'),
                       'approved': bool(approved), 'requires_human_approval': True})
    return result


def ecommerce_autopilot(products, approved=False):
    result = []
    for product in products or []:
        stock = float(product.get('stock', 0) or 0)
        margin = float(product.get('margin', 0) or 0)
        action = 'keep_indexable' if stock > 0 and margin > 0 else 'consolidate_or_noindex'
        result.append({'url': product.get('url'), 'action': action, 'stock': stock, 'margin': margin,
                       'approved': bool(approved), 'executed': False})
    return {'items': result, 'approval_required': True, 'mode': 'recommendation_only'}
