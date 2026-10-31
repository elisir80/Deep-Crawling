"""Native SERP feature tracking and rendered JavaScript SEO diagnostics."""
from collections import Counter
import re

def serp_features(snapshot):
    text=' '.join(str(snapshot.get(k) or '') for k in ('html','text','snippet')).lower()
    features=[]
    for name,patterns in {'featured_snippet':('featured snippet','answer box'),'people_also_ask':('people also ask','related questions'),
        'video':('<video','youtube.com','video result'),'images':('image pack','images result','<img'),
        'shopping':('shopping results','product listing'),'local_pack':('local pack','maps results')}.items():
        if any(pattern in text for pattern in patterns): features.append(name)
    return {'features':features,'feature_count':len(features)}

def feature_volatility(previous, current):
    old={r.get('keyword'):set(r.get('features',[])) for r in previous or []}
    changes=[]
    for row in current or []:
        before=old.get(row.get('keyword'),set()); after=set(row.get('features',[]))
        if before != after: changes.append({'keyword':row.get('keyword'),'added':sorted(after-before),'removed':sorted(before-after)})
    return {'changes':changes,'volatile_keywords':len(changes)}

def js_seo_debug(rendered):
    html=rendered.get('html','') if isinstance(rendered,dict) else str(rendered or '')
    source=rendered.get('source_html','') if isinstance(rendered,dict) else ''
    rendered_links=set(re.findall(r"<a[^>]+href=['\"]([^'\"]+)",html,re.I))
    source_links=set(re.findall(r"<a[^>]+href=['\"]([^'\"]+)",source,re.I))
    visible_text=re.sub(r'<script.*?</script>|<style.*?</style>','',html,flags=re.I|re.S)
    visible_text=re.sub(r'<[^>]+>',' ',visible_text)
    hidden=len(re.findall(r"(?:display\\s*:\\s*none|visibility\\s*:\\s*hidden|aria-hidden=['\"]true)",html,re.I))
    hydration=bool(re.search(r'__next|__nuxt|reactroot|data-reactroot|ng-version',html,re.I))
    return {'rendered_links':sorted(rendered_links),'source_links':sorted(source_links),
            'links_added_after_render':sorted(rendered_links-source_links),
            'links_missing_after_render':sorted(source_links-rendered_links),
            'visible_text_length':len(re.sub(r'\\s+',' ',visible_text).strip()),'hidden_elements':hidden,
            'hydration_detected':hydration,'javascript_risk':bool(rendered_links-source_links) or hidden>10}
