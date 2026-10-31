"""Native, deterministic resilience and observability tools.

Network execution is intentionally out of scope here: these functions build
rehearsals, policies and measurements from supplied snapshots and never deploy
or purge production without a separate approved integration.
"""
from statistics import mean


def migration_rehearsal(before, after, redirects=None):
    old = {x.get('url'): x for x in before or [] if x.get('url')}
    new = {x.get('url'): x for x in after or [] if x.get('url')}
    redirects = redirects or {}
    missing = sorted(set(old) - set(new) - set(redirects))
    changed = [{'url': url, 'status_changed': old[url].get('status_code') != new[url].get('status_code'),
                'canonical_changed': old[url].get('canonical') != new[url].get('canonical')}
               for url in sorted(set(old) & set(new))
               if old[url].get('status_code') != new[url].get('status_code') or old[url].get('canonical') != new[url].get('canonical')]
    return {'missing_urls': missing, 'changed_urls': changed, 'redirects': redirects,
            'passed': not missing and not any(x['status_changed'] for x in changed),
            'mode': 'rehearsal_only'}


def disaster_recovery_snapshot(project, events=None):
    events = events or []
    return {'project': project, 'event_count': len(events), 'last_event': events[-1] if events else None,
            'restore_ready': bool(project), 'restore_mode': 'deterministic_replay', 'approval_required': True}


def rum_summary(samples):
    fields = ('lcp', 'inp', 'cls', 'ttfb')
    result = {}
    for field in fields:
        values = [float(x.get(field, 0) or 0) for x in samples or [] if x.get(field) is not None]
        result[field] = {'count': len(values), 'average': round(mean(values), 3) if values else None,
                         'p75': round(sorted(values)[max(0, int(len(values) * .75) - 1)], 3) if values else None}
    return {'samples': len(samples or []), 'metrics': result, 'source': 'real_user_measurement'}


def synthetic_monitor(probes, thresholds=None):
    thresholds = thresholds or {'status_code': 399, 'latency_ms': 3000}
    results = []
    for probe in probes or []:
        failed = int(probe.get('status_code', 200) or 200) > int(thresholds.get('status_code', 399)) or float(probe.get('latency_ms', 0) or 0) > float(thresholds.get('latency_ms', 3000))
        results.append({**probe, 'passed': not failed, 'severity': 'critical' if failed else 'normal'})
    return {'probes': results, 'passed': all(x['passed'] for x in results)}


def privacy_safe_analytics(events, dimensions=None):
    dimensions = dimensions or ['country', 'device', 'event']
    clean = []
    for event in events or []:
        clean.append({key: event.get(key) for key in dimensions if key in event})
    return {'events': clean, 'removed_fields': ['ip', 'email', 'user_id', 'cookie_id'], 'mode': 'aggregated_no_direct_identifiers'}


def accessibility_sustainability(row, bytes_per_page=0):
    accessibility = row.get('accessibility') or {}
    issues = int(accessibility.get('missing_alt', 0) or 0) + int(accessibility.get('contrast_errors', 0) or 0) + int(accessibility.get('missing_labels', 0) or 0)
    bytes_value = float(bytes_per_page or row.get('bytes', 0) or 0)
    carbon = round(bytes_value / 1_000_000 * .2, 4)
    return {'accessibility_issues': issues, 'accessibility_passed': issues == 0,
            'estimated_carbon_grams': carbon, 'sustainability_band': 'A' if carbon < .2 else 'B' if carbon < .5 else 'C'}


def edge_policy_simulator(rows, policy=None):
    policy = policy or {}
    result = []
    for row in rows or []:
        headers = dict(row.get('headers') or {})
        headers.update(policy.get('headers', {}))
        action = policy.get('action', 'pass')
        result.append({'url': row.get('url'), 'action': action, 'headers': headers,
                       'indexable': headers.get('x-robots-tag', '').lower() not in ('noindex', 'noindex, nofollow')})
    return {'mode': 'simulation', 'requires_approval': True, 'results': result}


def cdn_purge_plan(changes, approved=False):
    return {'approved': bool(approved), 'executed': False,
            'urls': sorted({x.get('url') for x in changes or [] if x.get('url')}),
            'action': 'purge-ready' if approved else 'pending-approval'}
