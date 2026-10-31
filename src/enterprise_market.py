"""Deterministic market, risk and content-supply primitives for enterprise SEO.

These tools do not pretend to have an external search index: they analyse the
snapshots supplied by the project and expose assumptions in every result.
"""
from collections import defaultdict
from statistics import mean


def update_clustering(updates, threshold=0.15):
    """Cluster update observations by date/label and report affected markets."""
    groups = defaultdict(list)
    for item in updates or []:
        key = item.get('cluster') or item.get('date') or item.get('label') or 'unknown'
        groups[str(key)].append(item)
    result = []
    for key, rows in groups.items():
        impacts = [float(r.get('impact', r.get('ranking_change', 0)) or 0) for r in rows]
        result.append({'cluster': key, 'observations': len(rows),
                       'mean_impact': round(mean(impacts), 4) if impacts else 0,
                       'max_impact': round(max(impacts, default=0), 4),
                       'markets': sorted({str(r.get('market')) for r in rows if r.get('market')}),
                       'significant': bool(impacts and max(abs(x) for x in impacts) >= float(threshold)),
                       'evidence': rows})
    return sorted(result, key=lambda x: abs(x['mean_impact']), reverse=True)


def serp_market_intelligence(snapshots, dimensions=('market', 'device')):
    """Aggregate supplied SERP snapshots without claiming live SERP coverage."""
    buckets = defaultdict(list)
    for row in snapshots or []:
        key = tuple(row.get(d, 'unknown') for d in dimensions)
        buckets[key].append(row)
    result = []
    for key, rows in buckets.items():
        positions = [float(r.get('position', 0) or 0) for r in rows if r.get('position') is not None]
        result.append({'dimensions': dict(zip(dimensions, key)), 'results': len(rows),
                       'average_position': round(mean(positions), 2) if positions else None,
                       'visibility': round(sum(float(r.get('visibility', r.get('share', 0)) or 0) for r in rows), 4),
                       'features': sorted({str(f) for r in rows for f in (r.get('features') or [])}),
                       'source': 'project_snapshot'})
    return result


def demand_early_warning(keywords, growth_threshold=0.25):
    result = []
    for row in keywords or []:
        current = float(row.get('current', row.get('volume', 0)) or 0)
        previous = float(row.get('previous', row.get('previous_volume', 0)) or 0)
        growth = (current - previous) / max(abs(previous), 1)
        result.append({**row, 'growth_rate': round(growth, 4),
                       'early_warning': growth >= float(growth_threshold),
                       'priority': 'high' if growth >= float(growth_threshold) else 'normal'})
    return sorted(result, key=lambda x: x['growth_rate'], reverse=True)


def competitor_action_monitor(previous, current):
    """Detect competitor URL/template/schema/content changes between snapshots."""
    old = {r.get('url'): r for r in previous or [] if r.get('url')}
    actions = []
    for row in current or []:
        url = row.get('url')
        if not url:
            continue
        if url not in old:
            actions.append({'url': url, 'action': 'new_url', 'fields': list(row)})
            continue
        changed = [field for field in ('title', 'content_hash', 'status_code', 'canonical', 'schema', 'links')
                   if old[url].get(field) != row.get(field)]
        if changed:
            actions.append({'url': url, 'action': 'changed', 'fields': changed})
    current_urls = {r.get('url') for r in current or []}
    actions.extend({'url': url, 'action': 'removed', 'fields': []}
                   for url in old if url not in current_urls)
    return actions


def vulnerability_scan(rows):
    findings = []
    for row in rows or []:
        url = row.get('url')
        checks = [('exposed_admin', row.get('admin_exposed')), ('indexable_error', row.get('status_code') in (500, 503)),
                  ('mixed_content', row.get('mixed_content')), ('open_redirect', row.get('open_redirect')),
                  ('sensitive_data', row.get('sensitive_data'))]
        for name, hit in checks:
            if hit:
                findings.append({'url': url, 'rule': name, 'severity': 'high' if name in ('exposed_admin', 'sensitive_data') else 'medium'})
    return {'findings': findings, 'count': len(findings), 'passed': not findings}


def technical_debt(rows):
    result = []
    weights = {'status_code': 20, 'missing_title': 8, 'missing_description': 5, 'noindex': 10,
               'slow': 8, 'orphan': 12, 'broken_links': 10}
    for row in rows or []:
        score = sum(weight for field, weight in weights.items() if row.get(field) or (field == 'status_code' and row.get(field) not in (None, 200)))
        result.append({**row, 'debt_score': score, 'debt_level': 'high' if score >= 20 else 'medium' if score >= 8 else 'low'})
    return sorted(result, key=lambda x: x['debt_score'], reverse=True)


def financial_risk(rows, revenue_field='revenue'):
    result = []
    for row in rows or []:
        revenue = float(row.get(revenue_field, 0) or 0)
        probability = min(1, max(0, float(row.get('probability', row.get('risk_probability', .1)) or 0)))
        result.append({**row, 'revenue_at_risk': round(revenue * probability, 2),
                       'risk_score': round(probability * (1 + revenue / max(1000, revenue)), 4)})
    return sorted(result, key=lambda x: x['revenue_at_risk'], reverse=True)


def portfolio_forecast(series, horizon=6, growth_rate=0.05):
    values = [float((x.get('value', 0) if isinstance(x, dict) else x) or 0) for x in series or []]
    last = values[-1] if values else 0
    forecast = [round(last * (1 + float(growth_rate)) ** i, 2) for i in range(1, int(horizon) + 1)]
    return {'history': values, 'forecast': forecast, 'assumption': {'growth_rate': growth_rate, 'method': 'deterministic_scenario'}}


def budget_allocator(workstreams, budget):
    rows = []
    total = sum(max(float(x.get('impact', 0) or 0), 0) for x in workstreams or []) or 1
    for item in workstreams or []:
        impact = max(float(item.get('impact', 0) or 0), 0)
        allocation = float(budget) * impact / total
        rows.append({**item, 'allocation': round(allocation, 2), 'marginal_impact': round(impact / max(float(item.get('cost', 1) or 1), 1), 4)})
    return sorted(rows, key=lambda x: x['marginal_impact'], reverse=True)


def content_supply_chain(items, stages=None):
    stages = stages or ['brief', 'draft', 'review', 'approved', 'published']
    result = []
    for item in items or []:
        stage = item.get('stage', 'brief')
        index = stages.index(stage) if stage in stages else 0
        result.append({**item, 'stage': stage, 'stage_index': index,
                       'next_stage': stages[min(index + 1, len(stages) - 1)],
                       'blocked': bool(item.get('blocked') or item.get('approval_required') and not item.get('approved')),
                       'provenance': item.get('provenance', 'project_record')})
    return {'stages': stages, 'items': result, 'counts': {stage: sum(x['stage'] == stage for x in result) for stage in stages}}
