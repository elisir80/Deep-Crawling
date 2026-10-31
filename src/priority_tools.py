"""Local implementations for the next LibreCrawl audit priorities."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import re
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

def _cron_values(field, minimum, maximum):
    values=set()
    for token in str(field).split(','):
        token=token.strip()
        if token=='*': values.update(range(minimum,maximum+1)); continue
        if token.startswith('*/'):
            step=max(1,int(token[2:])); values.update(range(minimum,maximum+1,step)); continue
        if '-' in token:
            left,right=token.split('-',1); values.update(range(max(minimum,int(left)),min(maximum,int(right))+1)); continue
        if token: values.add(int(token))
    return values

def cron_next(expression, timezone='UTC', now=None):
    fields=str(expression).split()
    if len(fields)!=5: raise ValueError('cron expression must have 5 fields')
    tz=ZoneInfo(timezone) if ZoneInfo else None
    current=(now or datetime.now(tz)).replace(second=0,microsecond=0)
    if current.tzinfo is None and tz: current=current.replace(tzinfo=tz)
    minutes=_cron_values(fields[0],0,59); hours=_cron_values(fields[1],0,23); days=_cron_values(fields[2],1,31); months=_cron_values(fields[3],1,12); weekdays=_cron_values(fields[4],0,6)
    for _ in range(60*24*366):
        current += timedelta(minutes=1)
        if current.minute in minutes and current.hour in hours and current.day in days and current.month in months and current.weekday() in weekdays: return current.isoformat()
    raise ValueError('cron expression has no occurrence within one year')

def resource_audit(rows):
    totals=Counter(); sizes=defaultdict(int); errors=Counter(); pages=0
    for row in rows or []:
        pages+=1
        for resource in row.get('resources',[]) or []:
            kind=resource.get('type','unknown'); totals[kind]+=1; sizes[kind]+=int(resource.get('size',resource.get('bytes',0)) or 0)
            status=int(resource.get('status_code',resource.get('status',200)) or 200)
            if status>=400: errors[kind]+=1
    return {'pages':pages,'resource_count':sum(totals.values()),'by_type':[{'type':key,'count':totals[key],'bytes':sizes[key],'errors':errors[key]} for key in sorted(totals)],'total_bytes':sum(sizes.values()),'total_errors':sum(errors.values())}

def spa_detection(row):
    html=str(row.get('source_html') or row.get('rendered_html') or row.get('html') or '')
    script_count=len(re.findall(r'<script\b',html,re.I)); root=bool(re.search(r'id=["\'](?:root|app|__next|__nuxt)["\']',html,re.I)); sparse=re.sub(r'<[^>]+>',' ',html).strip()
    frameworks=[('__next','Next.js'),('__nuxt','Nuxt'),('ng-version','Angular'),('data-reactroot','React'),('webpack','Webpack')]
    framework=next((name for marker,name in frameworks if marker.lower() in html.lower()),None)
    detected=bool(framework or (root and script_count>=2 and len(sparse)<500))
    return {'url':row.get('url'),'spa_detected':detected,'framework':framework,'script_count':script_count,'text_length':len(sparse),'root_mount':root,'confidence':.9 if framework else (.7 if detected else .2)}

def duplicate_fingerprint(text, simhash=False):
    normalized=' '.join(str(text or '').lower().split()); md5=hashlib.md5(normalized.encode()).hexdigest()
    if not simhash: return {'md5':md5,'simhash':None}
    bits=[0]*64
    for token in normalized.split():
        digest=int(hashlib.md5(token.encode()).hexdigest()[:16],16)
        for index in range(64): bits[index] += 1 if digest & (1<<index) else -1
    value=sum((1<<index) for index,bit in enumerate(bits) if bit>=0)
    return {'md5':md5,'simhash':f'{value:016x}'}
