"""Native server log and crawl-budget analytics."""
from collections import Counter, defaultdict

def crawl_budget(log_report, crawled_urls=None):
    records=log_report.get('records',[]) if isinstance(log_report,dict) else []
    google=[r for r in records if r.get('bot_name') in ('Googlebot','Googlebot-Image','Googlebot Smartphone')]
    crawled=set(r.get('url') for r in google)
    known=set(r.get('url') for r in (crawled_urls or []))
    status=Counter(str(r.get('status')) for r in google)
    waste=[r for r in google if r.get('status') in (404,410,301,302) or any(x in (r.get('url') or '') for x in ('?sort=','?filter=','?page='))]
    return {'googlebot_requests':len(google),'unique_urls':len(crawled),'known_crawl_urls':len(known),
            'status_codes':dict(status),'wasted_requests':len(waste),
            'waste_rate_percent':round(len(waste)*100/max(len(google),1),2),
            'unknown_urls':sorted(crawled-known)}

def bot_frequency(log_report):
    records=log_report.get('records',[]) if isinstance(log_report,dict) else []
    counts=Counter(r.get('bot_name') or r.get('bot_type') for r in records)
    return [{'bot':bot,'requests':count} for bot,count in counts.most_common()]
