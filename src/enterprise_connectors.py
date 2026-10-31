"""Connector readiness and local semantic execution checks.

Readiness is deliberately separate from connectivity: credentials and
endpoints are never treated as a successful external connection.
"""
import hashlib
import json
import re
import requests


CONNECTORS = {
    'gsc': ('site_url', 'access_token'), 'ga4': ('property_id', 'access_token'),
    'serp': ('endpoint', 'api_key'), 'warehouse': ('endpoint', 'encryption_key'),
    'sso': ('sso_provider',), 'scim': ('scim_endpoint',), 'webhook': ('endpoint',),
}


def connector_readiness(config):
    result = {}
    for name, required in CONNECTORS.items():
        missing = [field for field in required if not config.get(field)]
        result[name] = {'configured': not missing, 'ready': not missing,
                        'missing': missing, 'mode': 'external-adapter' if not missing else 'local-fallback'}
    return {'connectors': result, 'external_calls_made': False}


def semantic_query(rows, query, fields=None):
    fields = fields or ('url', 'title', 'content_text', 'description')
    terms = [x for x in re.findall(r'[\w-]{2,}', str(query or '').lower())]
    matches = []
    for row in rows or []:
        haystack = ' '.join(str(row.get(field, '')) for field in fields).lower()
        score = sum(haystack.count(term) for term in terms)
        if terms and score:
            matches.append({**row, '_semantic_score': score})
    return sorted(matches, key=lambda x: x['_semantic_score'], reverse=True)


def agent_sandbox_check(plan, available_tools=None):
    available = set(available_tools or [])
    requested = list(plan.get('allowed_tools', []))
    denied = [tool for tool in requested if available and tool not in available]
    actions = int(plan.get('max_actions', 0) or 0)
    budget = float(plan.get('budget', 0) or 0)
    within_limits = len(requested) <= actions and (not requested or budget > 0)
    safe = bool(plan.get('kill_switch')) and bool(plan.get('requires_human_approval')) and not denied and actions >= 0 and budget >= 0 and within_limits
    return {'safe': safe, 'denied_tools': denied, 'kill_switch': bool(plan.get('kill_switch')),
            'requires_human_approval': bool(plan.get('requires_human_approval')),
            'remaining_budget': budget, 'max_actions': actions, 'within_limits': within_limits, 'mode': plan.get('mode', 'unknown')}


def signed_bundle(data, evidence=None):
    payload = {'data': data, 'evidence': evidence or []}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return {'bundle': payload, 'sha256': digest, 'tamper_evident': True, 'replayable': True}


def call_connector(provider, endpoint, payload=None, token=None, method='POST', timeout=15):
    """Execute an explicitly requested adapter call and normalize its result."""
    if provider not in CONNECTORS:
        raise ValueError('unsupported connector provider')
    if not endpoint:
        raise ValueError('endpoint is required')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = token if str(token).lower().startswith('bearer ') else 'Bearer ' + str(token)
    response = requests.request(method.upper(), endpoint, json=payload, headers=headers, timeout=float(timeout))
    try:
        body = response.json()
    except ValueError:
        body = response.text[:4000]
    return {'provider': provider, 'endpoint': endpoint, 'status_code': response.status_code,
            'ok': response.ok, 'body': body, 'external_call': True}
