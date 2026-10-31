"""Operational tools for outreach, security, localization and incidents."""
from collections import defaultdict
import re


def digital_pr_opportunities(prospects, campaign=None):
    campaign = campaign or {}
    result = []
    for prospect in prospects or []:
        authority = float(prospect.get('authority', 0) or 0); relevance = float(prospect.get('relevance', 0) or 0)
        audience = float(prospect.get('audience', prospect.get('traffic', 0)) or 0); cost = float(prospect.get('cost', 1) or 1)
        score = (authority * .4 + relevance * .35 + min(audience / 1000, 100) * .25) / cost
        result.append({**prospect, 'opportunity_score': round(score, 4), 'recommended': score >= float(campaign.get('threshold', 10))})
    return {'campaign': campaign, 'prospects': sorted(result, key=lambda x: x['opportunity_score'], reverse=True), 'approval_required': True}


def seo_security_scan(rows):
    rules = ('cloaking', 'malware', 'redirect_hijack', 'suspicious_script', 'mixed_content', 'indexation_tamper')
    findings = []
    for row in rows or []:
        hits = [rule for rule in rules if row.get(rule)]
        if hits: findings.append({'url': row.get('url'), 'rules': hits, 'severity': 'critical' if any(x in hits for x in ('malware', 'redirect_hijack')) else 'high'})
    return {'passed': not findings, 'findings': findings, 'remediation': 'approval_required'}


def multilingual_quality(rows, required_languages=None):
    required_languages = required_languages or []
    result = []
    for row in rows or []:
        text = str(row.get('content_text', '')); language = row.get('language')
        missing = [lang for lang in required_languages if lang not in (row.get('available_languages') or [language])]
        issues = []
        if not text.strip(): issues.append('empty_content')
        if row.get('intent') and row.get('translated_intent') and row['intent'] != row['translated_intent']: issues.append('intent_mismatch')
        result.append({**row, 'missing_languages': missing, 'issues': issues, 'quality_score': max(0, 100 - len(missing) * 20 - len(issues) * 25)})
    return result


def marketplace_monitor(rows, channels=None):
    channels = channels or ['amazon', 'ebay', 'youtube', 'google-shopping']
    result = []
    for row in rows or []:
        for channel in channels:
            channel_data = row.get(channel) or {}
            issues = [field for field in ('title', 'price', 'availability', 'url') if not channel_data.get(field)]
            result.append({'product': row.get('id', row.get('url')), 'channel': channel, 'issues': issues, 'valid': not issues})
    return {'channels': channels, 'items': result, 'passed': all(item['valid'] for item in result)}


def incident_response(incidents, thresholds=None):
    thresholds = thresholds or {'critical': 1, 'high': 3}
    result = []
    for incident in incidents or []:
        severity = incident.get('severity', 'medium'); count = int(incident.get('count', 1) or 1)
        trigger = count >= int(thresholds.get(severity, 999999))
        result.append({**incident, 'triggered': trigger, 'actions': ['alert', 'assign_owner', 'prepare_rollback'] if trigger else [], 'requires_approval': True})
    return {'incidents': result, 'active': sum(item['triggered'] for item in result)}


def seo_copilot_memory(decisions, query=None, approved_only=True):
    entries = [item for item in decisions or [] if not approved_only or item.get('approved')]
    if query:
        terms = set(re.findall(r'[\w-]{2,}', str(query).lower()))
        entries = [item for item in entries if terms & set(re.findall(r'[\w-]{2,}', str(item).lower()))]
    return {'query': query, 'entries': entries, 'count': len(entries), 'learns_only_from_approved': approved_only}
