"""Screaming-Frog parity helpers shared by the API and export layers.

These functions deliberately operate on crawl dictionaries, keeping the
feature set usable for saved crawls and avoiding a second crawler pipeline.
"""
import re
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.images = []
        self.headers = []
        self.cookies = []
        self._heading = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'a' and values.get('href'):
            self.links.append({'href': values['href'], 'rel': values.get('rel', ''), 'text': ''})
        elif tag == 'img':
            self.images.append({'src': values.get('src', ''), 'alt': values.get('alt'), 'width': values.get('width'), 'height': values.get('height')})
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._heading = tag
        elif tag in ('script', 'link', 'meta') and 'cookie' in str(values).lower():
            self.cookies.append(values)

    def handle_endtag(self, tag):
        if tag == self._heading:
            self._heading = None

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())
            if self.links and self._heading is None and len(self.links[-1].get('text', '')) < 200:
                self.links[-1]['text'] += data.strip()


def page_panels(row):
    """Return the lower-window style details for one crawled URL."""
    html = row.get('rendered_html') or row.get('source_html') or row.get('html') or ''
    parser = _Extractor()
    try:
        parser.feed(html)
    except Exception as error:
        parser_error = str(error)
    else:
        parser_error = None
    headers = row.get('http_headers') or row.get('headers') or {}
    return {
        'url': row.get('url'),
        'url_details': {key: row.get(key) for key in ('url', 'status_code', 'content_type', 'size', 'depth', 'indexable', 'canonical', 'redirect_url') if key in row},
        'inlinks': row.get('inlinks', []),
        'outlinks': parser.links or row.get('outlinks', []),
        'resources': row.get('resources', []),
        'serp_snippet': {'title': row.get('title', ''), 'description': row.get('meta_description', ''), 'url': row.get('url')},
        'http_headers': headers,
        'cookies': row.get('cookies', parser.cookies),
        'ngrams': ngrams(' '.join(parser.text), 2, 25),
        'images': parser.images,
        'render_debug': row.get('render_diagnostics', {}),
        'structured_data': row.get('structured_data') or row.get('json_ld', []),
        'lighthouse': row.get('lighthouse') or row.get('pagespeed') or {},
        'accessibility': row.get('accessibility') or {},
        'spelling_grammar': row.get('spelling_grammar') or row.get('grammar') or {},
        'duplicate_details': row.get('duplicate_details') or {'group': row.get('duplicate_group'), 'hash': row.get('content_hash')},
        'parser_error': parser_error,
    }


def ngrams(text, size=2, limit=100):
    words = re.findall(r"[\wÀ-ÿ]+", str(text or '').lower())
    counts = Counter(' '.join(words[index:index + size]) for index in range(max(0, len(words) - size + 1)))
    return [{'ngram': value, 'count': count} for value, count in counts.most_common(limit)]


def custom_extract(row, rules=None):
    """Extract CSS-like tags/attributes and simple text regexes from a row."""
    html = row.get('rendered_html') or row.get('source_html') or row.get('html') or ''
    output = {}
    for rule in rules or []:
        name = rule.get('name') or rule.get('selector') or 'extraction'
        selector = rule.get('selector', '')
        attribute = rule.get('attribute')
        if selector.startswith('#'):
            pattern = rf'<[^>]+id=["\']{re.escape(selector[1:])}["\'][^>]*>(.*?)</[^>]+>'
        elif selector.startswith('.'):
            pattern = rf'<[^>]+class=["\'][^"\']*\b{re.escape(selector[1:])}\b[^"\']*["\'][^>]*>(.*?)</[^>]+>'
        elif selector:
            pattern = rf'<{re.escape(selector)}\b[^>]*>(.*?)</{re.escape(selector)}>'
        else:
            pattern = None
        if pattern:
            matches = re.findall(pattern, html, re.I | re.S)
            output[name] = [re.sub(r'<[^>]+>', ' ', item).strip() for item in matches]
        elif rule.get('regex'):
            output[name] = re.findall(rule['regex'], html, re.I | re.S)
        else:
            output[name] = []
        if attribute and selector:
            tag = re.escape(selector.lstrip('#.'))
            output[name] = re.findall(rf'<{tag}\b[^>]*\b{re.escape(attribute)}=["\']([^"\']+)', html, re.I)
    return {'url': row.get('url'), 'extractions': output}


def custom_search(row, searches=None):
    html = row.get('rendered_html') or row.get('source_html') or row.get('html') or ''
    results = []
    for search in searches or []:
        pattern = search.get('regex') or re.escape(str(search.get('term', '')))
        found = bool(re.search(pattern, html, re.I | re.S))
        results.append({'name': search.get('name', search.get('term', 'search')), 'found': found, 'count': len(re.findall(pattern, html, re.I | re.S)) if found else 0})
    return {'url': row.get('url'), 'searches': results}


def link_positions(row):
    html = row.get('rendered_html') or row.get('source_html') or row.get('html') or ''
    results = []
    for match in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.I | re.S):
        attrs, text = match.groups()
        href = re.search(r'href=["\']([^"\']+)', attrs, re.I)
        results.append({'href': href.group(1) if href else '', 'text': re.sub(r'<[^>]+>', ' ', text).strip(), 'position': match.start(), 'context': html[max(0, match.start()-80):match.end()+80]})
    return {'url': row.get('url'), 'links': results}


def html_validation(row):
    html = row.get('rendered_html') or row.get('source_html') or row.get('html') or ''
    errors = []
    if not html.strip():
        errors.append({'rule': 'empty-document', 'message': 'HTML document is empty'})
    if html.count('<html') != html.count('</html>'):
        errors.append({'rule': 'html-balance', 'message': 'Unbalanced html element'})
    if html.count('<head') != html.count('</head>'):
        errors.append({'rule': 'head-balance', 'message': 'Unbalanced head element'})
    if html.count('<body') != html.count('</body>'):
        errors.append({'rule': 'body-balance', 'message': 'Unbalanced body element'})
    for tag in ('title', 'meta', 'link'):
        if re.search(rf'<{tag}\b[^>]*>', html, re.I) and not re.search(rf'</{tag}>', html, re.I) and tag == 'title':
            errors.append({'rule': 'unclosed-title', 'message': 'Title element is not closed'})
    return {'url': row.get('url'), 'valid': not errors, 'errors': errors}
