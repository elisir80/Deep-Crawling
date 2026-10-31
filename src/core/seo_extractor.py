"""SEO data extraction from HTML content"""
import re
import json
from urllib.parse import urljoin, urlparse
from lxml import html as lxml_html


class SEOExtractor:
    """Extracts SEO-related data from HTML content"""

    @staticmethod
    def extract_basic_seo_data(soup, result):
        """Extract basic SEO data (title, headings, meta description, etc.)"""
        # Extract title
        title_tag = soup.find('title')
        result['title'] = title_tag.get_text().strip() if title_tag else ''

        # Extract meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        result['meta_description'] = meta_desc.get('content', '').strip() if meta_desc else ''

        # Extract headings
        h1_tag = soup.find('h1')
        result['h1'] = h1_tag.get_text().strip() if h1_tag else ''

        h2_tags = soup.find_all('h2')
        result['h2'] = [h2.get_text().strip() for h2 in h2_tags[:10]]

        h3_tags = soup.find_all('h3')
        result['h3'] = [h3.get_text().strip() for h3 in h3_tags[:10]]

        # Count words
        text_content = soup.get_text()
        words = re.findall(r'\b\w+\b', text_content)
        result['word_count'] = len(words)

        # Extract language
        html_tag = soup.find('html')
        result['lang'] = html_tag.get('lang', '') if html_tag else ''

        # Extract charset
        charset_meta = soup.find('meta', attrs={'charset': True})
        if charset_meta:
            result['charset'] = charset_meta.get('charset', '')
        else:
            content_type_meta = soup.find('meta', attrs={'http-equiv': 'Content-Type'})
            if content_type_meta:
                content = content_type_meta.get('content', '')
                charset_match = re.search(r'charset=([^;]+)', content)
                result['charset'] = charset_match.group(1) if charset_match else ''

    @staticmethod
    def extract_meta_tags(soup, result):
        """Extract all meta tags"""
        meta_tags = soup.find_all('meta')

        for meta in meta_tags:
            name = meta.get('name', '').lower()
            content = meta.get('content', '')

            if name:
                result['meta_tags'][name] = content

                # Extract specific important meta tags
                if name == 'viewport':
                    result['viewport'] = content
                elif name == 'robots':
                    result['robots'] = content
                elif name == 'author':
                    result['author'] = content
                elif name == 'keywords':
                    result['keywords'] = content
                elif name == 'generator':
                    result['generator'] = content
                elif name == 'theme-color':
                    result['theme_color'] = content

        # Extract canonical URL
        canonical = soup.find('link', attrs={'rel': 'canonical'})
        canonical_href = canonical.get('href', '').strip() if canonical else ''
        result['canonical_url'] = urljoin(result.get('url', ''), canonical_href) if canonical_href else ''

        # Keep directives structured as well as preserving the original robots
        # value. This makes noindex/nofollow checks available to reports and
        # custom exports without reparsing the HTML later.
        robots = (result.get('robots') or '').lower()
        result['directives'] = {
            'noindex': 'noindex' in robots,
            'nofollow': 'nofollow' in robots,
            'noarchive': 'noarchive' in robots,
            'nosnippet': 'nosnippet' in robots,
            'none': 'none' in robots,
        }

    @staticmethod
    def extract_custom(html_content, result, rules):
        """Run configured CSS, XPath and regex extraction rules.

        Rules are dictionaries with: name, type (css/xpath/regex), query,
        attribute (optional), and multiple (optional). Failures are isolated
        per rule so one invalid selector cannot fail a crawl.
        """
        extracted = {}
        if not rules:
            result['custom_extractions'] = extracted
            return

        try:
            document = lxml_html.fromstring(html_content)
        except (TypeError, ValueError, Exception):
            result['custom_extractions'] = extracted
            return

        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            name = str(rule.get('name') or f'rule_{index + 1}')
            kind = str(rule.get('type', 'css')).lower()
            query = str(rule.get('query', ''))
            attribute = rule.get('attribute')
            multiple = bool(rule.get('multiple', True))
            values = []
            try:
                if kind == 'regex':
                    import re
                    matches = re.findall(query, html_content, re.IGNORECASE | re.DOTALL)
                    values = [m if isinstance(m, str) else list(m) for m in matches]
                else:
                    nodes = document.cssselect(query) if kind == 'css' else document.xpath(query)
                    if not isinstance(nodes, list):
                        nodes = [nodes]
                    for node in nodes:
                        if isinstance(node, str):
                            value = node
                        elif attribute:
                            value = node.get(attribute, '')
                        else:
                            value = ' '.join(node.text_content().split())
                        if value != '':
                            values.append(value)
                extracted[name] = values if multiple else (values[0] if values else '')
            except Exception as error:
                extracted[name] = {'error': str(error), 'values': []}
        result['custom_extractions'] = extracted

    @staticmethod
    def extract_custom_search(html_content, result, searches):
        """Evaluate configured text/regex searches and return match evidence."""
        findings = {}
        for index, search in enumerate(searches or []):
            if not isinstance(search, dict):
                continue
            name = str(search.get('name') or f'search_{index + 1}')
            query = str(search.get('query', ''))
            kind = str(search.get('type', 'text')).lower()
            if not query:
                continue
            try:
                if kind == 'regex':
                    import re
                    matches = re.findall(query, html_content, re.IGNORECASE | re.DOTALL)
                    findings[name] = {'matched': bool(matches), 'count': len(matches), 'matches': matches[:20]}
                else:
                    haystack = html_content.lower() if search.get('case_insensitive', True) else html_content
                    needle = query.lower() if search.get('case_insensitive', True) else query
                    findings[name] = {'matched': needle in haystack, 'count': haystack.count(needle)}
            except Exception as error:
                findings[name] = {'matched': False, 'count': 0, 'error': str(error)}
        result['custom_search'] = findings

    @staticmethod
    def extract_accessibility(soup, result):
        """Collect lightweight WCAG-oriented findings for each HTML page."""
        findings = []
        images = soup.find_all('img')
        missing_alt = sum(1 for image in images if image.get('alt') is None)
        empty_alt = sum(1 for image in images if image.get('alt') == '')
        if missing_alt:
            findings.append({'rule': 'image-alt-missing', 'count': missing_alt, 'severity': 'error'})
        if empty_alt:
            findings.append({'rule': 'image-alt-empty', 'count': empty_alt, 'severity': 'warning'})
        if not soup.find('html', attrs={'lang': True}):
            findings.append({'rule': 'html-lang-missing', 'count': 1, 'severity': 'error'})

        headings = [int(tag.name[1:]) for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])]
        skipped = sum(1 for previous, current in zip(headings, headings[1:]) if current > previous + 1)
        if skipped:
            findings.append({'rule': 'heading-level-skipped', 'count': skipped, 'severity': 'warning'})

        empty_links = sum(1 for link in soup.find_all('a') if not link.get_text(' ', strip=True) and not link.find('img', alt=True))
        if empty_links:
            findings.append({'rule': 'link-name-empty', 'count': empty_links, 'severity': 'warning'})

        controls = soup.find_all(['input', 'select', 'textarea'])
        unlabeled = 0
        for control in controls:
            if control.get('type') == 'hidden':
                continue
            control_id = control.get('id')
            if not control_id or not soup.find('label', attrs={'for': control_id}):
                unlabeled += 1
        if unlabeled:
            findings.append({'rule': 'form-control-label-missing', 'count': unlabeled, 'severity': 'warning'})

        skip_links = [link for link in soup.find_all('a', href=True) if link.get('href','').startswith('#') and link.get_text(' ', strip=True)]
        if not skip_links:
            findings.append({'rule': 'skip-link-missing', 'count': 1, 'severity': 'warning'})
        for table in soup.find_all('table'):
            headers = table.find_all('th')
            if not headers:
                findings.append({'rule': 'table-header-missing', 'count': 1, 'severity': 'error'})
            elif not any(header.get('scope') or header.get('id') for header in headers):
                findings.append({'rule': 'table-header-scope-missing', 'count': 1, 'severity': 'warning'})

        ids = [element.get('id') for element in soup.find_all(id=True)]
        duplicate_ids = len(ids) - len(set(ids))
        if duplicate_ids:
            findings.append({'rule': 'duplicate-id', 'count': duplicate_ids, 'severity': 'error'})
        penalty = sum((3 if finding.get('severity') == 'error' else 1) * int(finding.get('count', 1)) for finding in findings)
        result['accessibility'] = {'passed': not findings, 'score': max(0, 100 - penalty), 'findings': findings}

    @staticmethod
    def validate_html(html_content, result):
        """Perform a deterministic structural HTML validation pass."""
        errors = []
        try:
            document = lxml_html.fromstring(html_content)
            if document.tag.lower() != 'html':
                errors.append({'rule': 'html-root', 'message': 'Document root is not html'})
            if not document.xpath('//head'):
                errors.append({'rule': 'head-missing', 'message': 'Document has no head element'})
            if not document.xpath('//body'):
                errors.append({'rule': 'body-missing', 'message': 'Document has no body element'})
            ids = document.xpath('//*[@id]/@id')
            duplicates = sorted({value for value in ids if ids.count(value) > 1})
            for value in duplicates:
                errors.append({'rule': 'duplicate-id', 'message': f'Duplicate id: {value}'})
        except Exception as error:
            errors.append({'rule': 'parse-error', 'message': str(error)})
        result['html_validation'] = {'valid': not errors, 'errors': errors}

    @staticmethod
    def extract_opengraph_tags(soup, result):
        """Extract OpenGraph meta tags"""
        og_metas = soup.find_all('meta', attrs={'property': re.compile(r'^og:')})

        for meta in og_metas:
            property_name = meta.get('property', '')
            content = meta.get('content', '')
            if property_name:
                key = property_name.replace('og:', '')
                result['og_tags'][key] = content

    @staticmethod
    def extract_twitter_tags(soup, result):
        """Extract Twitter Card meta tags"""
        twitter_metas = soup.find_all('meta', attrs={'name': re.compile(r'^twitter:')})

        for meta in twitter_metas:
            name = meta.get('name', '')
            content = meta.get('content', '')
            if name:
                key = name.replace('twitter:', '')
                result['twitter_tags'][key] = content

    @staticmethod
    def extract_json_ld(soup, result):
        """Extract JSON-LD structured data"""
        json_ld_scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})

        for script in json_ld_scripts:
            try:
                json_data = json.loads(script.string)
                result['json_ld'].append(json_data)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

    @staticmethod
    def extract_analytics_tracking(soup, html_content, result):
        """Detect analytics and tracking scripts"""
        # Google Analytics patterns
        ga_patterns = [
            r'gtag\(',
            r'ga\(',
            r'GoogleAnalyticsObject',
            r'google-analytics\.com',
            r'googletagmanager\.com'
        ]

        # GA4 ID pattern
        ga4_match = re.search(r'G-[A-Z0-9]{10}', html_content)
        if ga4_match:
            result['analytics']['ga4_id'] = ga4_match.group()
            result['analytics']['gtag'] = True

        # GTM ID pattern
        gtm_match = re.search(r'GTM-[A-Z0-9]+', html_content)
        if gtm_match:
            result['analytics']['gtm_id'] = gtm_match.group()

        # Check for various analytics
        for pattern in ga_patterns:
            if re.search(pattern, html_content, re.IGNORECASE):
                result['analytics']['google_analytics'] = True
                break

        # Facebook Pixel
        if re.search(r'fbq\(|facebook\.com/tr', html_content, re.IGNORECASE):
            result['analytics']['facebook_pixel'] = True

        # Hotjar
        if re.search(r'hotjar\.com|hj\(', html_content, re.IGNORECASE):
            result['analytics']['hotjar'] = True

        # Mixpanel
        if re.search(r'mixpanel\.com|mixpanel\.track', html_content, re.IGNORECASE):
            result['analytics']['mixpanel'] = True

    @staticmethod
    def extract_images(soup, base_url, result):
        """Extract image information"""
        images = soup.find_all('img')

        for img in images:
            src = img.get('src', '')
            alt = img.get('alt', '')

            if src:
                # Convert relative URLs to absolute
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    parsed_base = urlparse(base_url)
                    src = f"{parsed_base.scheme}://{parsed_base.netloc}{src}"
                elif not src.startswith(('http://', 'https://')):
                    src = urljoin(base_url, src)

                result['images'].append({
                    'src': src,
                    'alt': alt,
                    'width': img.get('width', ''),
                    'height': img.get('height', '')
                })

    @staticmethod
    def extract_resources(soup, base_url, result):
        """Extract linked page resources with their element and attributes."""
        resources = []
        selectors = [
            ('script', 'src', 'script'),
            ('link', 'href', 'link'),
            ('img', 'src', 'image'),
            ('iframe', 'src', 'iframe'),
            ('video', 'src', 'video'),
            ('audio', 'src', 'audio'),
            ('source', 'src', 'source'),
            ('object', 'data', 'object'),
        ]
        for tag_name, attribute, resource_type in selectors:
            for element in soup.find_all(tag_name):
                raw_url = element.get(attribute, '').strip()
                if not raw_url or raw_url.startswith(('data:', 'javascript:', '#')):
                    continue
                resources.append({
                    'url': urljoin(base_url, raw_url),
                    'type': resource_type,
                    'attribute': attribute,
                    'media': element.get('media', ''),
                    'async': bool(element.has_attr('async')),
                    'defer': bool(element.has_attr('defer')),
                    'loading': element.get('loading', ''),
                })
        result['resources'] = resources

    @staticmethod
    def extract_advanced_directives(soup, base_url, result):
        """Extract pagination, AMP, refresh and responsive image directives."""
        result['pagination'] = {
            'next': '',
            'prev': ''
        }
        for relation in ('next', 'prev'):
            link = soup.find('link', attrs={'rel': lambda value: value and relation in value})
            if link and link.get('href'):
                result['pagination'][relation] = urljoin(base_url, link['href'])

        amp = soup.find('link', attrs={'rel': 'amphtml'})
        result['amp_url'] = urljoin(base_url, amp['href']) if amp and amp.get('href') else ''
        mobile = soup.find('link', attrs={'rel': lambda value: value and 'alternate' in value, 'media': True})
        result['mobile_alternate'] = urljoin(base_url, mobile['href']) if mobile and mobile.get('href') else ''
        refresh = soup.find('meta', attrs={'http-equiv': lambda value: value and value.lower() == 'refresh'})
        result['meta_refresh'] = refresh.get('content', '') if refresh else ''

        result['srcset'] = []
        for image in soup.find_all(['img', 'source']):
            value = image.get('srcset', '').strip()
            if value:
                candidates = []
                for candidate in value.split(','):
                    parts = candidate.strip().split(None, 1)
                    if parts:
                        candidates.append({'url': urljoin(base_url, parts[0]), 'descriptor': parts[1] if len(parts) > 1 else ''})
                result['srcset'].extend(candidates)

    @staticmethod
    def extract_link_counts(soup, result, base_domain):
        """Count internal vs external links"""
        links = soup.find_all('a', href=True)

        for link in links:
            href = link.get('href', '')
            if href and not href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
                absolute_url = urljoin(result['url'], href)
                parsed_url = urlparse(absolute_url)

                # Handle www vs non-www domains
                url_domain_clean = parsed_url.netloc.replace('www.', '', 1)
                base_domain_clean = base_domain.replace('www.', '', 1)

                if url_domain_clean == base_domain_clean:
                    result['internal_links'] += 1
                else:
                    result['external_links'] += 1

    @staticmethod
    def extract_hreflang(soup, result):
        """Extract hreflang links"""
        hreflang_links = soup.find_all('link', attrs={'rel': 'alternate', 'hreflang': True})

        for link in hreflang_links:
            hreflang = link.get('hreflang', '')
            href = link.get('href', '')
            if hreflang and href:
                result['hreflang'].append({
                    'lang': hreflang,
                    'url': urljoin(result.get('url', ''), href)
                })

    @staticmethod
    def extract_schema_org(soup, result):
        """Extract Schema.org microdata"""
        schema_items = soup.find_all(attrs={'itemtype': True})

        for item in schema_items:
            itemtype = item.get('itemtype', '')
            if itemtype:
                result['schema_org'].append({
                    'type': itemtype,
                    'properties': SEOExtractor._extract_microdata_properties(item)
                })

    @staticmethod
    def _extract_microdata_properties(element):
        """Extract microdata properties from an element"""
        properties = {}

        # Find all elements with itemprop
        prop_elements = element.find_all(attrs={'itemprop': True})

        for prop_elem in prop_elements:
            prop_name = prop_elem.get('itemprop', '')

            # Get content based on element type
            if prop_elem.name in ['meta']:
                content = prop_elem.get('content', '')
            elif prop_elem.name in ['img']:
                content = prop_elem.get('src', '')
            elif prop_elem.name in ['a']:
                content = prop_elem.get('href', '')
            else:
                content = prop_elem.get_text().strip()

            if prop_name and content:
                properties[prop_name] = content

        return properties

    @staticmethod
    def create_empty_result(url, depth, status_code=0, error=None, error_type=None):
        """Create an empty result structure.

        error_type: optional classification when status_code is 0 (no HTTP
        response). Values: 'dns_not_found', 'connection_refused', 'timeout',
        'ssl_error', 'connection_error', 'file_too_large', or None.
        """
        return {
            'url': url,
            'status_code': status_code,
            'error_type': error_type,
            'content_type': '',
            'size': 0,
            'is_internal': False,
            'depth': depth,
            'title': '',
            'meta_description': '',
            'h1': '',
            'h2': [],
            'h3': [],
            'word_count': 0,
            'meta_tags': {},
            'og_tags': {},
            'twitter_tags': {},
            'canonical_url': '',
            'lang': '',
            'charset': '',
            'viewport': '',
            'robots': '',
            'author': '',
            'keywords': '',
            'generator': '',
            'theme_color': '',
            'json_ld': [],
            'analytics': {
                'google_analytics': False,
                'gtag': False,
                'ga4_id': '',
                'gtm_id': '',
                'facebook_pixel': False,
                'hotjar': False,
                'mixpanel': False
            },
            'images': [],
            'resources': [],
            'external_links': 0,
            'internal_links': 0,
            'response_time': 0,
            'redirects': [],
            'redirect_final_url': '',
            'redirect_hops': 0,
            'hreflang': [],
            'schema_org': [],
            'directives': {
                'noindex': False,
                'nofollow': False,
                'noarchive': False,
                'nosnippet': False,
                'none': False
            },
            'custom_extractions': {},
            'accessibility': {'passed': True, 'findings': []},
            'pagination': {'next': '', 'prev': ''},
            'amp_url': '',
            'meta_refresh': '',
            'srcset': [],
            'html_validation': {'valid': True, 'errors': []},
            'content_analysis': {},
            'linked_from': [],
            'error': error
        }
