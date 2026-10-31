"""Native technical SEO parsers and time-series helpers."""
import json
import re
from collections import Counter
from datetime import datetime

AI_BOTS = ('GPTBot','ClaudeBot','PerplexityBot','Google-Extended','Applebot-Extended','anthropic-ai')

def schema_audit(row):
    schemas=row.get('schema_org') or row.get('json_ld') or []
    if isinstance(schemas,str):
        try: schemas=json.loads(schemas)
        except Exception: schemas=[]
    if isinstance(schemas,dict): schemas=[schemas]
    types=[]
    for item in schemas:
        if isinstance(item,dict):
            value=item.get('@type')
            types.extend(value if isinstance(value,list) else [value] if value else [])
    return {'types':sorted(set(types)), 'valid': bool(types), 'rich_result_eligible': bool(types),
            'issues': [] if types else ['No JSON-LD schema type detected']}

def record_cwv(url, metrics, snapshot=None):
    snapshot=snapshot or datetime.utcnow().isoformat()+'Z'
    result={'url':url,'snapshot':snapshot}
    for key in ('lcp','inp','cls','ttfb','fcp'):
        if key in metrics: result[key]=float(metrics[key])
    result['passed']=(result.get('lcp',0)<=2.5 and result.get('inp',0)<=200 and result.get('cls',0)<=0.1)
    return result

def cwv_history(records):
    grouped={}
    for row in records or []: grouped.setdefault(row.get('url'),[]).append(row)
    return [{'url':url,'snapshots':sorted(rows,key=lambda x:x.get('snapshot','')),'latest':sorted(rows,key=lambda x:x.get('snapshot',''))[-1]} for url,rows in grouped.items()]

def parse_access_log(lines):
    records=[]; counts=Counter()
    pattern=re.compile(r'(?P<ip>\S+) \S+ \S+ \[[^]]+\] "(?P<method>\S+) (?P<url>\S+)[^\"]*" (?P<status>\d{3}) (?P<size>\S+) "[^"]*" "(?P<ua>[^"]*)"')
    for line in lines or []:
        match=pattern.search(line)
        if not match: continue
        item=match.groupdict(); ua=item['ua']; item['status']=int(item['status']); item['size']=int(item['size']) if item['size'].isdigit() else 0
        bot=next((name for name in AI_BOTS if name.lower() in ua.lower()), None)
        item['bot_type']='ai' if bot else ('googlebot' if 'googlebot' in ua.lower() else 'other')
        item['bot_name']=bot or ('Googlebot' if item['bot_type']=='googlebot' else None)
        records.append(item); counts[item['bot_name'] or item['bot_type']]+=1
    return {'records':records,'summary':dict(counts)}
