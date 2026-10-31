"""First-priority next-generation SEO decision tools."""
from collections import defaultdict
from statistics import mean
import hashlib
import json


def experiment_platform(name, control, variants, metric='conversions', direction='higher'):
    def avg(rows): return mean([float(r.get(metric, 0) or 0) for r in rows]) if rows else 0
    baseline = avg(control); result = []
    for variant, rows in (variants or {}).items():
        value = avg(rows); delta = value - baseline
        improvement = delta / max(abs(baseline), 1)
        winner = improvement > 0 if direction == 'higher' else improvement < 0
        result.append({'variant': variant, 'size': len(rows), 'average': round(value, 6),
                       'delta': round(delta, 6), 'improvement_percent': round(improvement * 100, 3), 'winner': winner})
    return {'name': name, 'metric': metric, 'control_size': len(control or []), 'control_average': round(baseline, 6),
            'variants': result, 'assignment': 'deterministic_snapshot', 'requires_significance_check': True}


def conversion_rank_tracker(rows):
    result = []
    for row in rows or []:
        position = float(row.get('position', 0) or 0); conversions = float(row.get('conversions', 0) or 0)
        revenue = float(row.get('revenue', 0) or 0); clicks = float(row.get('clicks', 0) or 0)
        result.append({**row, 'conversion_rate': round(conversions / max(clicks, 1), 6),
                       'revenue_per_rank': round(revenue / max(position, 1), 4),
                       'business_priority': round((conversions + revenue / 100) / max(position, 1), 4)})
    return sorted(result, key=lambda x: x['business_priority'], reverse=True)


def algorithm_forensics(updates, pages):
    affected = []
    for page in pages or []:
        before = float(page.get('before_position', page.get('position', 0)) or 0)
        after = float(page.get('after_position', page.get('position', 0)) or 0)
        delta = after - before
        if delta:
            affected.append({**page, 'position_delta': delta, 'direction': 'loss' if delta > 0 else 'gain'})
    return {'updates': updates or [], 'affected_pages': sorted(affected, key=lambda x: abs(x['position_delta']), reverse=True),
            'correlation_method': 'declared_update_window_snapshot', 'causal_claim': False}


def regression_gate(before, after, rules=None):
    rules = rules or {'max_new_errors': 0, 'max_status_5xx': 0, 'max_title_loss': 0}
    checks = {'new_errors': max(0, int(after.get('errors', 0) or 0) - int(before.get('errors', 0) or 0)),
              'status_5xx': int(after.get('status_5xx', 0) or 0),
              'title_loss': max(0, int(before.get('titles', 0) or 0) - int(after.get('titles', 0) or 0))}
    failures = [{'metric': key, 'actual': value, 'limit': rules.get('max_' + key, 0)} for key, value in checks.items()
                if value > rules.get('max_' + key, 0)]
    return {'passed': not failures, 'checks': checks, 'failures': failures, 'merge_allowed': not failures}


def remediation_plan(issues, approved=False):
    plans = []
    for index, issue in enumerate(issues or [], 1):
        plans.append({'id': index, 'url': issue.get('url'), 'issue': issue.get('issue', issue.get('type')),
                      'patch': issue.get('patch', {}), 'preview': {**issue, **issue.get('patch', {})},
                      'approved': bool(approved), 'executed': False, 'rollback_available': True})
    return {'plans': plans, 'approval_required': True, 'mode': 'preview_only'}


def content_roi(rows):
    result = []
    for row in rows or []:
        revenue = float(row.get('revenue', 0) or 0); cost = float(row.get('cost', row.get('editorial_cost', 0)) or 0)
        conversions = float(row.get('conversions', 0) or 0)
        result.append({**row, 'roi': round((revenue - cost) / max(cost, 1), 4),
                       'revenue_per_cost': round(revenue / max(cost, 1), 4),
                       'priority': 'high' if revenue > cost and conversions else 'normal'})
    return sorted(result, key=lambda x: x['roi'], reverse=True)


def competitor_intelligence(previous, current):
    old = {x.get('url'): x for x in previous or [] if x.get('url')}; events = []
    for row in current or []:
        url = row.get('url')
        if not url: continue
        if url not in old: events.append({'url': url, 'event': 'new_content'})
        else:
            changed = [field for field in ('title', 'schema', 'canonical', 'content_hash', 'backlinks') if old[url].get(field) != row.get(field)]
            if changed: events.append({'url': url, 'event': 'changed', 'fields': changed})
    return events


def citation_gap(prompts, owned_sources, citations):
    owned = {str(x).lower() for x in owned_sources or []}; result = []
    for prompt in prompts or []:
        seen = [str(x) for x in citations.get(prompt, [])] if isinstance(citations, dict) else []
        missing = [source for source in owned_sources or [] if str(source).lower() not in {x.lower() for x in seen}]
        result.append({'prompt': prompt, 'citations': seen, 'owned_citations': [x for x in seen if x.lower() in owned],
                       'citation_gap': missing, 'ownership_percent': round((len(seen) - len(missing)) * 100 / max(len(owned_sources or []), 1), 2)})
    return result
