"""SEO utilities exposed by the API and CLI."""
import re
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser


def test_robots(robots_text, url, user_agent='*'):
    parser = RobotFileParser()
    parser.parse(robots_text.splitlines())
    return {'url': url, 'user_agent': user_agent, 'allowed': parser.can_fetch(user_agent, url), 'sitemaps': parser.site_maps() or []}


def fetch_and_test_robots(site_url, target_url=None, user_agent='*', timeout=15):
    """Fetch a site's robots.txt and test a target URL against it."""
    site_url = site_url.rstrip('/')
    robots_url = site_url + '/robots.txt'
    response = requests.get(robots_url, timeout=timeout, headers={'User-Agent': user_agent})
    response.raise_for_status()
    target = target_url or site_url + '/'
    result = test_robots(response.text, target, user_agent)
    result.update({'robots_url': robots_url, 'status_code': response.status_code})
    return result


def generate_sitemap(urls, base_url=None):
    root = ET.Element('urlset', {'xmlns': 'http://www.sitemaps.org/schemas/sitemap/0.9'})
    for item in urls:
        url = item.get('url') if isinstance(item, dict) else item
        if not url or (base_url and not url.startswith(base_url)):
            continue
        element = ET.SubElement(root, 'url')
        ET.SubElement(element, 'loc').text = url
        if isinstance(item, dict):
            if item.get('lastmod'):
                ET.SubElement(element, 'lastmod').text = str(item['lastmod'])
            if item.get('changefreq'):
                ET.SubElement(element, 'changefreq').text = str(item['changefreq'])
            if item.get('priority') is not None:
                ET.SubElement(element, 'priority').text = str(item['priority'])
    return ET.tostring(root, encoding='unicode')


def generate_sitemap_index(sitemaps):
    """Generate a standards-compliant sitemap index from sitemap URLs."""
    root = ET.Element('sitemapindex', {'xmlns': 'http://www.sitemaps.org/schemas/sitemap/0.9'})
    for item in sitemaps or []:
        loc = item.get('loc') if isinstance(item, dict) else item
        if not loc:
            continue
        node = ET.SubElement(root, 'sitemap')
        ET.SubElement(node, 'loc').text = str(loc)
        if isinstance(item, dict) and item.get('lastmod'):
            ET.SubElement(node, 'lastmod').text = str(item['lastmod'])
    return ET.tostring(root, encoding='unicode')


def rewrite_url(url, rules):
    for rule in rules or []:
        pattern, replacement = rule.get('pattern'), rule.get('replacement')
        if pattern and replacement is not None:
            url = re.sub(pattern, replacement, url)
    return url


def apply_cdn(url, cdn_host):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, cdn_host, parsed.path, parsed.params, parsed.query, parsed.fragment)) if cdn_host else url


def segment_urls(urls, expression):
    """Filter URL records by a small field:value expression."""
    if not expression:
        return urls
    if ':' not in expression:
        return []
    field, expected = expression.split(':', 1)
    field, expected = field.strip(), expected.strip().lower()
    return [row for row in urls if expected in str(row.get(field, '')).lower()]

def analyze_link_reclamation(rows, links):
    """Find broken/redirected targets and sources that need reclamation."""
    status = {r.get('url'): r.get('status_code') for r in rows}
    result = []
    for link in links or []:
        target = link.get('target_url')
        code = link.get('target_status', status.get(target))
        if code in (404, 410) or (isinstance(code, int) and 300 <= code < 400):
            result.append({'source_url': link.get('source_url'), 'target_url': target,
                           'status_code': code, 'anchor_text': link.get('anchor_text',''),
                           'action': 'replace_or_redirect'})
    return result

def redirect_map(rows):
    return [{'url': r.get('url'), 'status_code': r.get('status_code'),
             'redirects': r.get('redirects') or r.get('redirect_chain') or []}
            for r in rows or [] if r.get('status_code') in range(300, 400) or r.get('redirects')]

def sitemap_monitor(sitemap_urls, crawled_rows):
    crawled = {r.get('url') for r in crawled_rows or []}
    listed = {x.get('url') if isinstance(x, dict) else x for x in sitemap_urls or []}
    return {'listed': len(listed), 'crawled': len(crawled), 'missing_from_crawl': sorted(listed-crawled),
            'not_in_sitemap': sorted(crawled-listed), 'coverage_percent': round(len(listed & crawled)*100/max(len(listed),1),2)}

def indexability_simulator(row, robots_allowed=True, renderable=True):
    directives = str(row.get('robots') or row.get('directives') or '').lower()
    canonical = row.get('canonical_url')
    reasons = []
    if not robots_allowed: reasons.append('blocked_by_robots')
    if 'noindex' in directives: reasons.append('noindex')
    if not renderable or row.get('javascript_error'): reasons.append('not_renderable')
    if canonical and canonical != row.get('url'): reasons.append('canonical_to_other_url')
    return {'url': row.get('url'), 'indexable': not reasons, 'reasons': reasons,
            'canonical': canonical or row.get('url'), 'robots_allowed': robots_allowed, 'renderable': renderable}

def generate_special_sitemap(urls, kind='news'):
    namespaces = {'news':'http://www.google.com/schemas/sitemap-news/0.9',
                  'image':'http://www.google.com/schemas/sitemap-image/1.1',
                  'video':'http://www.google.com/schemas/sitemap-video/1.1'}
    root = ET.Element('urlset', {'xmlns':'http://www.sitemaps.org/schemas/sitemap/0.9',
                                 'xmlns:' + kind:namespaces[kind]})
    for row in urls or []:
        url = row.get('url') if isinstance(row,dict) else row
        if not url: continue
        node=ET.SubElement(root,'url'); ET.SubElement(node,'loc').text=url
        child=ET.SubElement(node,kind+':'+kind)
        if kind=='image': ET.SubElement(child,kind+':loc').text=row.get('image_url',url)
        elif kind=='video': ET.SubElement(child,kind+':content_loc').text=row.get('video_url',url)
        else: ET.SubElement(child,kind+':publication_date').text=str(row.get('lastmod',''))
    return ET.tostring(root,encoding='unicode')
