"""Optional Google integrations using user-provided OAuth bearer tokens.

No credentials are stored by LibreCrawl. Tokens are supplied per request and
are only used for the upstream API call.
"""
import requests

PROVIDER_ENDPOINTS = {
    'ahrefs': 'https://api.ahrefs.com/v3/site-explorer/overview',
    'majestic': 'https://api.majestic.com/api/json',
    'moz': 'https://lsapi.seomoz.com/v2/url_metrics',
}

def pagespeed_insights(url, api_key=None, strategy='mobile', categories=None, locale=None):
    """Call Google's official PageSpeed Insights endpoint for one URL."""
    if not url:
        raise ValueError('url is required')
    strategy = str(strategy).lower()
    if strategy not in ('mobile', 'desktop'):
        raise ValueError('strategy must be mobile or desktop')
    params = {'url': url, 'strategy': strategy}
    if api_key:
        params['key'] = api_key
    if locale:
        params['locale'] = locale
    for category in categories or []:
        params.setdefault('category', []).append(category)
    response = requests.get('https://www.googleapis.com/pagespeedonline/v5/runPagespeed', params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    data['_request_scope'] = {'url': url, 'strategy': strategy, 'categories': categories or [], 'credentials_persisted': False}
    return data

def provider_metrics(provider, api_key, target_url, endpoint=None, extra=None):
    """Call a real provider endpoint using its documented API key mechanism."""
    provider = str(provider).lower()
    if provider not in PROVIDER_ENDPOINTS or not api_key or not target_url:
        raise ValueError('provider, api_key and target_url are required')
    endpoint = endpoint or PROVIDER_ENDPOINTS[provider]
    params = {'target': target_url, 'item': target_url}
    headers = {'Accept': 'application/json'}
    if provider == 'moz':
        headers['Authorization'] = 'Basic ' + api_key
    elif provider == 'majestic':
        params.update({'app_api_key': api_key, 'cmd': 'GetIndexItemInfo'})
    else:
        headers['Authorization'] = 'Bearer ' + api_key
    if isinstance(extra, dict): params.update(extra)
    response = requests.get(endpoint, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def search_console(site_url, access_token, start_date, end_date, dimensions=None, row_limit=25000, dimension_filter_groups=None, search_type=None, aggregation_type=None, start_row=0):
    endpoint = 'https://searchconsole.googleapis.com/webmasters/v3/sites/'
    encoded_site = requests.utils.quote(site_url, safe='')
    endpoint += encoded_site + '/searchAnalytics/query'
    payload = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': dimensions or ['query', 'page'],
        'rowLimit': min(max(int(row_limit), 1), 25000),
        'startRow': max(int(start_row), 0),
    }
    if dimension_filter_groups: payload['dimensionFilterGroups'] = dimension_filter_groups
    if search_type: payload['type'] = search_type
    if aggregation_type: payload['aggregationType'] = aggregation_type
    response = requests.post(endpoint, json=payload, headers={'Authorization': f'Bearer {access_token}'}, timeout=30)
    response.raise_for_status()
    return response.json()


def analytics(site_id, access_token, start_date, end_date, metrics=None, dimensions=None):
    endpoint = f'https://analyticsdata.googleapis.com/v1beta/properties/{site_id}:runReport'
    payload = {
        'dateRanges': [{'startDate': start_date, 'endDate': end_date}],
        'metrics': [{'name': metric} for metric in (metrics or ['sessions', 'screenPageViews'])],
        'dimensions': [{'name': dimension} for dimension in (dimensions or ['date'])],
    }
    response = requests.post(endpoint, json=payload, headers={'Authorization': f'Bearer {access_token}'}, timeout=30)
    response.raise_for_status()
    return response.json()

def search_console_report(site_url, access_token, start_date, end_date, dimensions=None, row_limit=25000, dimension_filter_groups=None, search_type=None, aggregation_type=None, start_row=0):
    """Build a complete GSC report including query/page CTR and anomaly hints."""
    data=search_console(site_url,access_token,start_date,end_date,dimensions or ['query','page'],row_limit,dimension_filter_groups,search_type,aggregation_type,start_row)
    rows=data.get('rows',[])
    for row in rows:
        clicks=float(row.get('clicks',0)); impressions=float(row.get('impressions',0))
        row['ctr_percent']=round(clicks*100/impressions,2) if impressions else 0
        row['anomaly']=impressions > max(100, clicks*50) and row['ctr_percent'] < 1
    return {'rows':rows,'summary':{'clicks':sum(float(r.get('clicks',0)) for r in rows),
            'impressions':sum(float(r.get('impressions',0)) for r in rows),
            'anomalies':[r for r in rows if r.get('anomaly')]}}

def search_console_inspection(site_url, inspection_url, access_token, language_code='en-US'):
    """Call Google's URL Inspection API without persisting credentials."""
    if not site_url or not inspection_url or not access_token: raise ValueError('site_url, inspection_url and access_token are required')
    response=requests.post('https://searchconsole.googleapis.com/v1/urlInspection/index:inspect',json={'inspectionUrl':inspection_url,'siteUrl':site_url,'languageCode':language_code},headers={'Authorization':f'Bearer {access_token}'},timeout=30)
    response.raise_for_status(); return response.json()

def search_console_sites(access_token):
    response=requests.get('https://searchconsole.googleapis.com/webmasters/v3/sites',headers={'Authorization':f'Bearer {access_token}'},timeout=30); response.raise_for_status(); return response.json()

def search_console_sitemaps(site_url, access_token, sitemap_url=None, method='GET'):
    encoded=requests.utils.quote(site_url,safe=''); base='https://searchconsole.googleapis.com/webmasters/v3/sites/'+encoded+'/sitemaps'
    target=base if method.upper()=='GET' else base+'/'+requests.utils.quote(sitemap_url or '',safe='')
    response=requests.request(method,target,headers={'Authorization':f'Bearer {access_token}'},timeout=30); response.raise_for_status(); return response.json() if response.content else {'status_code':response.status_code}

def bing_webmaster_call(endpoint, api_key, payload=None, method='POST'):
    """Generic Bing Webmaster adapter; caller supplies the documented endpoint."""
    if not endpoint or not api_key: raise ValueError('endpoint and api_key are required')
    response=requests.request(method,endpoint,params={'apikey':api_key},json=payload,headers={'Accept':'application/json'},timeout=30)
    response.raise_for_status()
    try: return response.json()
    except ValueError: return {'status_code':response.status_code,'body':response.text[:2000]}

def bing_webmaster_operation(operation, endpoint, api_key, site_url=None, payload=None):
    operations={'ranking':'GetRankAndTrafficStats','keywords':'GetKeywordStats','backlinks':'GetLinkDetails','crawl':'GetCrawlStats','submit-url':'SubmitUrl','submit-sitemap':'SubmitSitemap'}
    if operation not in operations: raise ValueError('unsupported Bing Webmaster operation')
    body=dict(payload or {}); body.setdefault('siteUrl',site_url); body['operation']=operations[operation]
    return bing_webmaster_call(endpoint,api_key,body,'POST')

def ga4_report(property_id, access_token, start_date, end_date, dimensions, metrics, dimension_filter=None, metric_filter=None, order_bys=None, limit=None, offset=None, keep_empty_rows=False, return_property_quota=False):
    payload={'dateRanges':[{'startDate':start_date,'endDate':end_date}],'dimensions':[{'name':x} for x in dimensions or []],'metrics':[{'name':x} for x in metrics or []], 'keepEmptyRows':bool(keep_empty_rows), 'returnPropertyQuota':bool(return_property_quota)}
    if dimension_filter: payload['dimensionFilter']=dimension_filter
    if metric_filter: payload['metricFilter'] = metric_filter
    if order_bys: payload['orderBys'] = order_bys
    if limit is not None: payload['limit'] = max(0, int(limit))
    if offset is not None: payload['offset'] = max(0, int(offset))
    response=requests.post(f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport',json=payload,headers={'Authorization':f'Bearer {access_token}'},timeout=30); response.raise_for_status(); data=response.json()
    metadata=data.get('metadata') or {}; quota=data.get('propertyQuota') or data.get('propertyQuotaInfo')
    sampling=metadata.get('samplingMetadatas') or metadata.get('samplingMetadata') or metadata.get('sampling')
    data['_request_metadata']={'dimensions':dimensions,'metrics':metrics,'sampling_unknown':sampling is None,'sampling':sampling,'property_quota':quota,'keep_empty_rows':bool(keep_empty_rows),'property_quota_requested':bool(return_property_quota)}
    return data

def ga4_attribution(site_id, access_token, start_date, end_date):
    """Query GA4 landing page and revenue attribution dimensions."""
    return analytics(site_id,access_token,start_date,end_date,
        metrics=['sessions','engagedSessions','conversions','totalRevenue','screenPageViews'],
        dimensions=['landingPagePlusQueryString','sessionDefaultChannelGroup'])


def backlink_metrics(endpoint, access_token, target_url, provider='generic', extra=None):
    """Query an Ahrefs/Majestic/Moz-compatible backlink metrics endpoint."""
    if not endpoint or not target_url:
        raise ValueError('endpoint and target_url are required')
    headers = {'Accept': 'application/json'}
    if access_token:
        headers['Authorization'] = access_token if access_token.lower().startswith(('bearer ', 'basic ')) else f'Bearer {access_token}'
    params = {'target': target_url, 'url': target_url, 'provider': provider}
    if isinstance(extra, dict):
        params.update(extra)
    response = requests.get(endpoint, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def sync_crawl(endpoint, access_token, payload):
    """Push a crawl report to a team/cloud webhook without storing credentials."""
    if not endpoint:
        raise ValueError('endpoint is required')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if access_token:
        headers['Authorization'] = access_token if access_token.lower().startswith('bearer ') else f'Bearer {access_token}'
    response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return {'status_code': response.status_code, 'body': response.text[:2000]}
