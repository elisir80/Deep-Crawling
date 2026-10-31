"""
Main web crawler orchestrator with smooth rate limiting and modular architecture.
Refactored for better code practices and maintainability.
"""
import requests
import os
import json
import socket
import ssl
import threading
import time
import asyncio
import re
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from urllib.robotparser import RobotFileParser
import nest_asyncio


def classify_fetch_error(exc_or_msg):
    """Classify a failed-fetch error into a coarse error_type.

    Accepts either an exception (walks the cause chain to handle
    requests/urllib3 wrappers) or a raw error string (from Playwright).
    Falls back to message inspection.

    Returns one of: 'dns_not_found', 'timeout', 'connection_refused',
    'ssl_error', 'connection_error'.
    """
    if isinstance(exc_or_msg, BaseException):
        seen = set()
        cur = exc_or_msg
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if isinstance(cur, socket.gaierror):
                return 'dns_not_found'
            if isinstance(cur, ssl.SSLError) or isinstance(cur, requests.exceptions.SSLError):
                return 'ssl_error'
            if isinstance(cur, ConnectionRefusedError):
                return 'connection_refused'
            if isinstance(cur, (socket.timeout, requests.exceptions.Timeout)):
                return 'timeout'
            cur = getattr(cur, '__cause__', None) or getattr(cur, '__context__', None)

    msg = str(exc_or_msg).lower()
    dns_markers = (
        'getaddrinfo failed',
        'name or service not known',
        'name resolution',
        'nodename nor servname',
        'no address associated',
        'name does not resolve',
        'temporary failure in name resolution',
        'name_not_resolved',
        'err_name_not_resolved',
        'nxdomain',
    )
    if any(m in msg for m in dns_markers):
        return 'dns_not_found'
    if 'timed out' in msg or 'timeout' in msg:
        return 'timeout'
    if 'refused' in msg or 'err_connection_refused' in msg:
        return 'connection_refused'
    if 'ssl' in msg or 'certificate' in msg or 'err_cert' in msg or 'tls' in msg:
        return 'ssl_error'
    return 'connection_error'

from src.core.rate_limiter import RateLimiter
from src.core.seo_extractor import SEOExtractor
from src.core.link_manager import LinkManager
from src.core.js_renderer import JavaScriptRenderer
from src.core.sitemap_parser import SitemapParser
from src.core.issue_detector import IssueDetector
from src.core.memory_monitor import MemoryMonitor
from src.core.memory_profiler import UserMemoryTracker


class WebCrawler:
    """
    Main web crawler with smooth rate limiting and comprehensive SEO analysis.
    Uses modular architecture with separate components for different responsibilities.
    """

    def __init__(self, crawl_id=None, resume_from_db=False):
        # HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Deep Crawling/1.0 (Web Crawler)'
        })

        # Base URL tracking
        self.base_url = None
        self.base_domain = None

        # Component instances (initialized on demand)
        self.rate_limiter = None
        self.link_manager = None
        self.js_renderer = None
        self.sitemap_parser = None
        self.issue_detector = None
        self.seo_extractor = SEOExtractor()
        self.memory_monitor = MemoryMonitor()
        self.user_memory = UserMemoryTracker()

        # Demo mode state
        self._demo_limit_reached = False

        # Results storage
        self.crawl_results = []
        self.duplicate_groups = []
        self.results_lock = threading.Lock()

        # State flags
        self.is_running = False
        self.is_paused = False
        self.is_running_pagespeed = False

        # Configuration
        self.config = self._get_default_config()

        # Statistics
        self.stats = {
            'discovered': 0,
            'crawled': 0,
            'depth': 0,
            'speed': 0.0,
            'start_time': None
        }

        # Thread reference
        self.crawl_thread = None

        # Robots.txt cache
        self._robots_cache = {}
        self._hsts_hosts = set()

        # Image status cache (avoids re-checking the same image URL across pages)
        self._image_status_cache = {}

        # Database persistence
        self.crawl_id = crawl_id
        self.resume_mode = resume_from_db
        self.auto_save_interval = 30  # seconds
        self.batch_save_size = 50  # URLs before triggering save
        self.last_save_time = time.time()
        self.unsaved_urls = []
        self.unsaved_links = []
        self.unsaved_issues = []
        self.auto_save_thread = None
        self.db_save_enabled = False  # Only enable when crawl_id is set

        # Enable nested asyncio for thread compatibility
        nest_asyncio.apply()

    def _get_default_config(self):
        """Get default configuration"""
        return {
            'max_depth': 3,
            'max_urls': 1000,
            'delay': 1.0,
            'follow_redirects': True,
            'crawl_external': False,
            'crawl_all_subdomains': False,
            'crawl_outside_start_folder': True,
            'respect_hsts': False,
            'respect_noindex': False,
            'respect_nofollow': False,
            'respect_canonical': False,
            'respect_next_prev': False,
            'follow_canonical': False,
            'follow_redirect_chains': True,
            'follow_meta_refresh': True,
            'crawl_fragments': False,
            'retry_5xx': True,
            'retry_5xx_attempts': 2,
            'user_agent': 'Deep Crawling/1.0 (Web Crawler)',
            'timeout': 10,
            'retries': 3,
            'accept_language': 'en-US,en;q=0.9',
            'respect_robots': True,
            'allow_cookies': True,
            'include_extensions': ['html', 'htm', 'php', 'asp', 'aspx', 'jsp'],
            'exclude_extensions': ['pdf', 'doc', 'docx', 'zip', 'exe', 'dmg'],
            'include_patterns': [],
            'exclude_patterns': [],
            'max_file_size': 50 * 1024 * 1024,
            'concurrency': 5,
            'memory_limit': 512 * 1024 * 1024,
            'log_level': 'INFO',
            'enable_proxy': False,
            'proxy_url': None,
            'proxy_username': '',
            'proxy_password': '',
            'proxy_no_proxy': '',
            'trusted_certificates': True,
            'storage_mode': 'full',
            'crawl_retention_days': 90,
            'custom_headers': {},
            'auth_username': '',
            'auth_password': '',
            'auth_bearer_token': '',
            'cookie_header': '',
            'cookie_storage': False,
            'discover_sitemaps': True,
            'enable_pagespeed': False,
            'enable_javascript': False,
            'js_wait_time': 3,
            'js_timeout': 30,
            'js_browser': 'chromium',
            'js_headless': True,
            'js_user_agent': 'Deep Crawling/1.0 (Web Crawler with JavaScript)',
            'js_viewport_width': 1920,
            'js_viewport_height': 1080,
            'js_max_concurrent_pages': 3,
            'js_screenshots': False,
            'js_screenshot_dir': 'data/screenshots',
            'js_archive': False,
            'js_archive_dir': 'data/rendered',
            'js_flatten_shadow_dom': False,
            'js_flatten_iframes': False,
            'js_custom_script': '',
            'max_redirects': 10,
            'max_url_length': 2048,
            'max_query_strings': 20,
            'max_folder_depth': 20,
            'max_links_per_url': 0,
            'max_urls_per_depth': 0,
            'max_urls_per_subdomain': 0,
            'issue_exclusion_patterns': [
                # WordPress admin & system paths
                '/wp-admin/*', '/wp-content/plugins/*', '/wp-content/themes/*', '/wp-content/uploads/*',
                '/wp-includes/*', '/wp-login.php', '/wp-cron.php', '/xmlrpc.php',
                '/wp-json/*', '/wp-activate.php', '/wp-signup.php', '/wp-trackback.php',

                # Auth & user management pages
                '/login*', '/signin*', '/sign-in*', '/log-in*', '/auth/*', '/authenticate/*',
                '/register*', '/signup*', '/sign-up*', '/registration/*',
                '/logout*', '/signout*', '/sign-out*', '/log-out*',
                '/forgot-password*', '/reset-password*', '/password-reset*', '/recover-password*',
                '/change-password*', '/account/password/*', '/user/password/*',
                '/activate/*', '/verification/*', '/verify/*', '/confirm/*',

                # Admin panels & dashboards
                '/admin/*', '/administrator/*', '/_admin/*', '/backend/*', '/dashboard/*',
                '/cpanel/*', '/phpmyadmin/*', '/pma/*', '/webmail/*', '/plesk/*',
                '/control-panel/*', '/manage/*', '/manager/*',

                # E-commerce checkout & cart
                '/checkout/*', '/cart/*', '/basket/*', '/payment/*', '/billing/*',
                '/order/*', '/orders/*', '/purchase/*',

                # User account pages
                '/account/*', '/profile/*', '/settings/*', '/preferences/*',
                '/my-account/*', '/user/*', '/member/*', '/members/*',

                # CGI & server scripts
                '/cgi-bin/*', '/cgi/*', '/fcgi-bin/*',

                # Version control & config
                '/.git/*', '/.svn/*', '/.hg/*', '/.bzr/*', '/.cvs/*',
                '/.env', '/.env.*', '/.htaccess', '/.htpasswd',
                '/web.config', '/app.config', '/composer.json', '/package.json',

                # Development & build artifacts
                '/node_modules/*', '/vendor/*', '/bower_components/*', '/jspm_packages/*',
                '/includes/*', '/lib/*', '/libs/*', '/src/*', '/dist/*', '/build/*', '/builds/*',
                '/_next/*', '/.next/*', '/out/*', '/_nuxt/*', '/.nuxt/*',

                # Testing & development
                '/test/*', '/tests/*', '/spec/*', '/specs/*', '/__tests__/*',
                '/debug/*', '/dev/*', '/development/*', '/staging/*',

                # API internal endpoints
                '/api/internal/*', '/api/admin/*', '/api/private/*',

                # System & internal
                '/private/*', '/system/*', '/core/*', '/internal/*',
                '/tmp/*', '/temp/*', '/cache/*', '/logs/*', '/log/*',
                '/backup/*', '/backups/*', '/old/*', '/archive/*', '/archives/*',
                '/config/*', '/configs/*', '/configuration/*',

                # Media upload forms
                '/upload/*', '/uploads/*', '/uploader/*', '/file-upload/*',

                # Search & filtering (often noisy for SEO)
                '/search*', '*/search/*', '?s=*', '?search=*',
                '*/filter/*', '?filter=*', '*/sort/*', '?sort=*',

                # Printer-friendly & special views
                '/print/*', '?print=*', '/preview/*', '?preview=*',
                '/embed/*', '?embed=*', '/amp/*', '/amp',

                # Feed URLs
                '/feed/*', '/feeds/*', '/rss/*', '*.rss', '/atom/*', '*.atom',

                # Common file types to exclude from issues
                '*.json', '*.xml', '*.yaml', '*.yml', '*.toml', '*.ini', '*.conf',
                '*.log', '*.txt', '*.csv', '*.sql', '*.db',
                '*.bak', '*.backup', '*.old', '*.orig', '*.tmp', '*.swp',
                '*.map', '*.min.js', '*.min.css'
            ]
        }

    def start_crawl(self, url, user_id=None, session_id=None, crawl_mode='spider', seed_urls=None):
        """Start crawling from a spider URL, URL list, or XML sitemap."""
        if self.is_running:
            return False, "Crawl already in progress"

        try:
            # Validate and normalize the primary URL. For list/sitemap modes it
            # is used to establish the base domain and persistence metadata.
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            parsed = urlparse(url)
            self.base_url = f"{parsed.scheme}://{parsed.netloc}"
            self.base_domain = parsed.netloc

            # Create database crawl record if session_id provided
            if session_id:
                from src.crawl_db import create_crawl
                self.crawl_id = create_crawl(
                    user_id=user_id,
                    session_id=session_id,
                    base_url=self.base_url,
                    base_domain=self.base_domain,
                    config_snapshot=self.config
                )
                if self.crawl_id:
                    self.db_save_enabled = True
                    print(f"Database persistence enabled for crawl {self.crawl_id}")

            # Initialize components
            self._initialize_components()

            # Reset state
            self._reset_state()

            # Seed the queue according to the selected crawl mode.
            if crawl_mode == 'sitemap':
                sitemap_url = (seed_urls or [url])[0]
                if not sitemap_url.startswith(('http://', 'https://')):
                    sitemap_url = 'https://' + sitemap_url
                seed_urls = self.sitemap_parser._parse_sitemap(sitemap_url)
            elif crawl_mode == 'list':
                seed_urls = seed_urls or [url]
            else:
                seed_urls = [url]

            added = 0
            for seed_url in seed_urls:
                if not seed_url or not isinstance(seed_url, str):
                    continue
                if not seed_url.startswith(('http://', 'https://')):
                    seed_url = 'https://' + seed_url
                if self._should_crawl_url(seed_url):
                    self.link_manager.add_url(seed_url.strip(), 0)
                    added += 1
            self.stats['discovered'] = self.link_manager.get_stats()['discovered']
            if not added:
                return False, 'No valid seed URLs were supplied'

            # Spider mode may additionally discover declared sitemaps.
            if crawl_mode == 'spider' and self.config.get('discover_sitemaps', True):
                print(f"Starting sitemap discovery for {url}")
                self._discover_and_add_sitemap_urls(url)
                print(f"Sitemap discovery completed. Total discovered URLs: {self.stats['discovered']}")

            # Start auto-save thread if DB enabled
            if self.db_save_enabled:
                self._start_auto_save_thread()

            # Start crawling in separate thread
            self.is_running = True
            self.crawl_thread = threading.Thread(target=self._crawl_worker)
            self.crawl_thread.start()

            return True, "Crawl started successfully"

        except Exception as e:
            return False, f"Error starting crawl: {str(e)}"

    def _initialize_components(self):
        """Initialize all crawler components"""
        # Calculate requests per second from delay
        if self.config['delay'] > 0:
            requests_per_second = 1.0 / self.config['delay']
        else:
            # If delay is 0, set high rate but still smooth
            requests_per_second = 100.0

        self.rate_limiter = RateLimiter(requests_per_second)
        self.link_manager = LinkManager(self.base_domain)
        self.sitemap_parser = SitemapParser(
            self.session,
            self.base_domain,
            self.config['timeout'],
            request_wait=self._wait_for_request_slot,
        )
        self.issue_detector = IssueDetector(self.config.get('issue_exclusion_patterns', []))

        # Initialize JS renderer if needed
        if self.config.get('enable_javascript', False):
            self.js_renderer = JavaScriptRenderer(self.config)

    def _reset_state(self):
        """Reset crawler state"""
        if self.link_manager:
            self.link_manager.reset()
        if self.issue_detector:
            self.issue_detector.reset()

        self.crawl_results.clear()
        self.duplicate_groups = []
        self.stats = {
            'discovered': 0,
            'crawled': 0,
            'depth': 0,
            'speed': 0.0,
            'start_time': time.time()
        }

        # Start memory monitoring
        self.memory_monitor.start_monitoring()
        self.user_memory.reset()
        self._demo_limit_reached = False

    def _discover_and_add_sitemap_urls(self, base_url):
        """Discover sitemaps and add URLs to crawl queue"""
        sitemap_urls = self.sitemap_parser.discover_sitemaps(base_url)

        added_count = 0
        filtered_count = 0

        for url in sitemap_urls:
            if self._should_crawl_url(url):
                self.link_manager.add_url(url, 0)
                added_count += 1
            else:
                filtered_count += 1

        self.stats['discovered'] = self.link_manager.get_stats()['discovered']
        print(f"Sitemap processing: {added_count} added, {filtered_count} filtered")

    def stop_crawl(self):
        """Stop the current crawl"""
        self.is_running = False
        self.is_paused = False
        self.is_running_pagespeed = False

        if self.crawl_thread and self.crawl_thread.is_alive():
            self.crawl_thread.join(timeout=5)

        # Save final data to database
        if self.db_save_enabled and self.crawl_id:
            self._save_batch_to_db(force=True)
            from src.crawl_db import set_crawl_status
            set_crawl_status(self.crawl_id, 'stopped')

        # Clean up JavaScript resources if enabled
        if self.js_renderer:
            asyncio.run(self.js_renderer.cleanup())
            self.js_renderer = None

        return True, "Crawl and PageSpeed analysis stopped"

    def pause_crawl(self):
        """Pause the current crawl"""
        if not self.is_running:
            return False, "No crawl in progress"
        self.is_paused = True

        # Save checkpoint when pausing
        if self.db_save_enabled and self.crawl_id:
            self._save_batch_to_db(force=True)
            self._save_queue_checkpoint()
            from src.crawl_db import set_crawl_status
            set_crawl_status(self.crawl_id, 'paused')

        return True, "Crawl paused"

    def resume_crawl(self):
        """Resume the paused crawl"""
        if not self.is_running:
            return False, "No crawl in progress"
        if not self.is_paused:
            return False, "Crawl is not paused"
        self.is_paused = False

        # Update status in database
        if self.db_save_enabled and self.crawl_id:
            from src.crawl_db import set_crawl_status
            set_crawl_status(self.crawl_id, 'running')

        return True, "Crawl resumed"

    def resume_from_database(self, crawl_id, user_id=None, session_id=None):
        """Resume a previously interrupted crawl from database"""
        if self.is_running:
            return False, "Crawl already in progress"

        try:
            from src.crawl_db import get_resume_data, load_crawled_urls, set_crawl_status
            from collections import deque

            # Load crawl data
            crawl_data = get_resume_data(crawl_id)

            if not crawl_data:
                return False, "Cannot resume this crawl - not found"

            if crawl_data['status'] not in ['paused', 'failed', 'running', 'stopped']:
                return False, f"Cannot resume crawl with status: {crawl_data['status']}"

            # Verify user owns this crawl (if not guest)
            if user_id and crawl_data.get('user_id') != user_id:
                return False, "Unauthorized - you don't own this crawl"

            # Restore basic state
            self.crawl_id = crawl_id
            self.base_url = crawl_data['base_url']
            self.base_domain = crawl_data['base_domain']
            # Preserve demo keys across config restore
            demo_mode = self.config.get('demo_mode', False)
            demo_limit = self.config.get('demo_memory_limit_bytes', 0)
            self.config = crawl_data.get('config_snapshot', self._get_default_config())
            if demo_mode:
                self.config['demo_mode'] = True
                self.config['demo_memory_limit_bytes'] = demo_limit
            self.db_save_enabled = True

            # Initialize components
            self._initialize_components()

            # Load already crawled URLs from database
            from src.crawl_db import load_crawl_links, load_crawl_issues

            print(f"Loading crawled data from database...")
            self.crawl_results = load_crawled_urls(crawl_id)

            # Mark all crawled URLs as discovered to prevent re-discovery
            for url_data in self.crawl_results:
                url = url_data.get('url')
                if url:
                    self.link_manager.all_discovered_urls.add(url)

            # Load links and restore to link manager
            loaded_links = load_crawl_links(crawl_id)
            if loaded_links:
                self.link_manager.all_links = loaded_links
                # Rebuild links_set for duplicate detection
                for link in loaded_links:
                    link_key = f"{link['source_url']}|{link['target_url']}"
                    self.link_manager.links_set.add(link_key)

            # Load issues and restore to issue detector
            loaded_issues = load_crawl_issues(crawl_id)
            if loaded_issues:
                self.issue_detector.detected_issues = loaded_issues

            print(f"Loaded {len(self.crawl_results)} URLs, {len(loaded_links)} links, {len(loaded_issues)} issues from database")

            # Account for loaded data in per-user memory tracker
            self.user_memory.reset()
            self._demo_limit_reached = False
            for url_data in self.crawl_results:
                self.user_memory.track_url(url_data)
            if loaded_links:
                self.user_memory.track_links(loaded_links)
            if loaded_issues:
                self.user_memory.track_issues(loaded_issues)
            print(f"User memory tracker: {self.user_memory.total_mb:.0f}MB from loaded data")

            # Restore statistics
            self.stats['crawled'] = len(self.crawl_results)
            self.stats['discovered'] = crawl_data.get('urls_discovered', 0)
            self.stats['depth'] = crawl_data.get('max_depth_reached', 0)
            self.stats['start_time'] = time.time()  # New start time for resume

            # Restore queue state from checkpoint
            checkpoint = crawl_data.get('resume_checkpoint', {})
            if checkpoint:
                # Restore discovered URLs queue
                if 'discovered_urls' in checkpoint:
                    discovered_list = checkpoint['discovered_urls']
                    self.link_manager.discovered_urls = deque(discovered_list)

                # Restore visited URLs set
                if 'visited_urls' in checkpoint:
                    self.link_manager.visited_urls = set(checkpoint['visited_urls'])

                print(f"Restored queue: {len(self.link_manager.discovered_urls)} pending, "
                      f"{len(self.link_manager.visited_urls)} visited")

            # If queue is empty (no checkpoint or crawl crashed early), rebuild queue from links
            if not self.link_manager.discovered_urls:
                print("Queue is empty - rebuilding from discovered links")

                # Get all URLs from loaded links that haven't been crawled yet
                crawled_urls = set(url_data.get('url') for url_data in self.crawl_results)

                # Add any linked URLs that haven't been crawled yet
                added_count = 0
                for link in loaded_links:
                    target_url = link.get('target_url')
                    if target_url and target_url not in crawled_urls and link.get('is_internal'):
                        self.link_manager.add_url(target_url, link.get('depth', 1))
                        added_count += 1

                print(f"Added {added_count} pending URLs to queue from links")

                # If still empty, crawl is complete
                if not self.link_manager.discovered_urls:
                    print("No pending URLs found - crawl was already complete")

                self.stats['discovered'] = len(self.link_manager.all_discovered_urls)

            # Update status to running
            set_crawl_status(crawl_id, 'running')

            # Start auto-save thread
            self._start_auto_save_thread()

            # Start crawling
            self.is_running = True
            self.crawl_thread = threading.Thread(target=self._crawl_worker)
            self.crawl_thread.start()

            return True, f"Resumed crawl from {self.stats['crawled']} URLs"

        except Exception as e:
            print(f"Error resuming crawl: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Error resuming crawl: {str(e)}"

    def get_status(self):
        """Get current crawl status and results"""
        if self._demo_limit_reached and not self.is_running:
            status = 'demo_stopped'
        elif not self.is_running and self.stats['crawled'] > 0:
            status = 'completed'
        elif not self.is_running and self.stats['crawled'] == 0:
            status = 'idle'
        else:
            status = 'running'

        # Calculate speed
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            self.stats['speed'] = round(self.stats['crawled'] / max(elapsed, 1), 2)

        # Get link manager stats
        link_stats = self.link_manager.get_stats() if self.link_manager else {'discovered': 0}

        # Update link statuses before returning (ensures all crawled URLs have their status)
        if self.link_manager:
            self.link_manager.update_link_statuses(self.crawl_results)

        # Update memory stats
        self.memory_monitor.update()

        # Per-user data sizes from incremental tracker (O(1), no recursion)
        data_sizes = self.user_memory.get_stats()

        print(f"get_status called - crawl_results length: {len(self.crawl_results)}, status: {status}, crawled: {self.stats['crawled']}")

        return {
            'status': status,
            'stats': {
                **self.stats,
                'discovered': link_stats['discovered']
            },
            'urls': self.crawl_results.copy(),
            'links': self.link_manager.all_links.copy() if self.link_manager else [],
            'issues': self.issue_detector.get_issues() if self.issue_detector else [],
            'duplicate_groups': self.duplicate_groups,
            'progress': min(100, (self.stats['crawled'] / max(link_stats['discovered'], 1)) * 100),
            'is_running_pagespeed': self.is_running_pagespeed,
            'memory': self.memory_monitor.get_stats(),
            'memory_data': data_sizes,
            'demo_stopped': self._demo_limit_reached,
            'demo_mode': self.config.get('demo_mode', False)
        }

    def _save_batch_to_db(self, force=False):
        """Save batched data to database"""
        if not self.db_save_enabled or not self.crawl_id:
            return

        from src.crawl_db import save_url_batch, save_links_batch, save_issues_batch, update_crawl_stats

        try:
            # Save URLs
            if self.unsaved_urls:
                urls_to_save = self.unsaved_urls
                if self.config.get('storage_mode', 'full') == 'summary':
                    heavy_fields = {'source_html', 'rendered_html', 'extracted_text', 'screenshot_path', 'rendered_archive_path', 'javascript_errors', 'render_diagnostics', 'pdf_text'}
                    urls_to_save = [{key: value for key, value in row.items() if key not in heavy_fields} for row in self.unsaved_urls]
                save_url_batch(self.crawl_id, urls_to_save)
                self.unsaved_urls.clear()

            # Save links
            if self.unsaved_links:
                save_links_batch(self.crawl_id, self.unsaved_links)
                self.unsaved_links.clear()

            # Save issues
            if self.unsaved_issues:
                save_issues_batch(self.crawl_id, self.unsaved_issues)
                self.unsaved_issues.clear()

            # Update statistics
            memory_stats = self.memory_monitor.get_stats()
            update_crawl_stats(
                self.crawl_id,
                discovered=self.stats['discovered'],
                crawled=self.stats['crawled'],
                max_depth=self.stats['depth'],
                peak_memory_mb=memory_stats.get('peak_mb', 0),
                estimated_size_mb=memory_stats.get('estimated_crawl_mb', 0)
            )
            self._save_cookie_storage()

            self.last_save_time = time.time()
            print(f"Saved batch to database for crawl {self.crawl_id}")

        except Exception as e:
            print(f"Error saving batch to database: {e}")
            import traceback
            traceback.print_exc()

    def _save_queue_checkpoint(self):
        """Save current queue state for crash recovery"""
        if not self.db_save_enabled or not self.crawl_id or not self.link_manager:
            return

        from src.crawl_db import save_checkpoint

        try:
            # Get discovered URLs from link manager
            discovered_urls = []
            if hasattr(self.link_manager, 'discovered_urls'):
                discovered_urls = list(self.link_manager.discovered_urls)[:1000]  # Limit to prevent huge checkpoints

            # Get visited URLs
            visited_urls = []
            if hasattr(self.link_manager, 'visited_urls'):
                visited_urls = list(self.link_manager.visited_urls)

            checkpoint = {
                'discovered_urls': discovered_urls,
                'visited_urls': visited_urls,
                'pending_count': self.link_manager.get_stats().get('pending', 0)
            }

            save_checkpoint(self.crawl_id, checkpoint)
            print(f"Saved queue checkpoint for crawl {self.crawl_id}")

        except Exception as e:
            print(f"Error saving checkpoint: {e}")

    def _start_auto_save_thread(self):
        """Background thread for periodic saves"""
        def auto_save_worker():
            while self.is_running:
                time.sleep(5)  # Check every 5 seconds
                if time.time() - self.last_save_time >= self.auto_save_interval:
                    self._save_batch_to_db()
                    self._save_queue_checkpoint()

        self.auto_save_thread = threading.Thread(target=auto_save_worker, daemon=True)
        self.auto_save_thread.start()
        print("Auto-save thread started")

    def update_config(self, new_config):
        """Update crawler configuration"""
        self.config.update(new_config)

        # Update session headers
        self.session.headers.update({
            'User-Agent': self.config['user_agent'],
            'Accept-Language': self.config['accept_language']
        })
        try:
            self.session.max_redirects = max(0, int(self.config.get('max_redirects', 10)))
        except (TypeError, ValueError):
            self.session.max_redirects = 10

        # Add custom headers
        if self.config['custom_headers']:
            self.session.headers.update(self.config['custom_headers'])

        # Configure proxy if enabled
        if self.config['enable_proxy'] and self.config['proxy_url']:
            proxy_url = self.config['proxy_url']
            proxy_username = self.config.get('proxy_username', '')
            proxy_password = self.config.get('proxy_password', '')
            if proxy_username and '@' not in proxy_url.split('://', 1)[-1].split('/', 1)[0]:
                from urllib.parse import quote
                scheme, rest = proxy_url.split('://', 1)
                proxy_url = f'{scheme}://{quote(proxy_username)}:{quote(proxy_password)}@{rest}'
            self.session.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
        else:
            self.session.proxies = {}
        self.session.trust_env = True
        no_proxy = self.config.get('proxy_no_proxy', '').strip()
        if no_proxy:
            self.session.trust_env = False
            self.session.proxies['no_proxy'] = no_proxy
        self.session.verify = bool(self.config.get('trusted_certificates', True))

        username = self.config.get('auth_username', '')
        password = self.config.get('auth_password', '')
        self.session.auth = (username, password) if username else None
        bearer = self.config.get('auth_bearer_token', '').strip()
        if bearer:
            self.session.headers['Authorization'] = bearer if bearer.lower().startswith('bearer ') else f'Bearer {bearer}'
        else:
            self.session.headers.pop('Authorization', None)
        cookie_header = self.config.get('cookie_header', '').strip()
        if cookie_header:
            self.session.headers['Cookie'] = cookie_header
        else:
            self.session.headers.pop('Cookie', None)
        self._load_cookie_storage()

        # Update rate limiter if it exists
        if self.rate_limiter:
            if self.config['delay'] > 0:
                self.rate_limiter.update_rate(1.0 / self.config['delay'])
            else:
                self.rate_limiter.update_rate(100.0)

    def _cookie_storage_path(self):
        if not self.crawl_id or not self.config.get('cookie_storage', False):
            return None
        return os.path.join('data', 'cookies', f'{self.crawl_id}.json')

    def _load_cookie_storage(self):
        path = self._cookie_storage_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding='utf-8') as source:
                for cookie in json.load(source):
                    self.session.cookies.set(cookie['name'], cookie.get('value', ''), domain=cookie.get('domain'), path=cookie.get('path', '/'))
        except Exception as error:
            print(f'Cookie storage load skipped: {error}')

    def _save_cookie_storage(self):
        path = self._cookie_storage_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cookies = [{'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain, 'path': cookie.path} for cookie in self.session.cookies]
            with open(path, 'w', encoding='utf-8') as target:
                json.dump(cookies, target, ensure_ascii=False)
        except Exception as error:
            print(f'Cookie storage save skipped: {error}')

    def _crawl_worker(self):
        """Main crawling worker with smooth rate limiting"""
        # Use async approach if JavaScript rendering is enabled
        if self.config.get('enable_javascript', False):
            print("Initializing JavaScript rendering...")
            asyncio.run(self._crawl_async_with_js())
            return

        # Traditional HTTP crawling with smooth rate limiting
        max_workers = self.config.get('concurrency', 5)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            active_futures = {}

            while self.is_running:
                try:
                    # Check if paused
                    if self.is_paused:
                        time.sleep(1)
                        continue

                    # Submit new tasks - fill ALL available slots, apply rate limiting per task
                    while (len(active_futures) < max_workers and
                           self.stats['crawled'] < self.config['max_urls']):

                        url_info = self.link_manager.get_next_url()
                        if not url_info:
                            break

                        current_url, depth = url_info

                        # Skip if depth exceeded
                        if depth > self.config['max_depth']:
                            continue

                        # Submit crawl task immediately - rate limiting happens inside the worker
                        print(f"Submitting task for: {current_url}")
                        future = executor.submit(self._crawl_url, current_url, depth)
                        active_futures[future] = current_url

                    # Process completed tasks
                    completed_futures = []
                    for future in list(active_futures.keys()):
                        if future.done():
                            completed_futures.append(future)
                            try:
                                result = future.result()
                                if result:
                                    with self.results_lock:
                                        self.crawl_results.append(result)
                                        self.stats['crawled'] += 1
                                        self.stats['depth'] = max(self.stats['depth'], result.get('depth', 0))
                                        print(f"Added URL to results: {result['url']} - Total in results: {len(self.crawl_results)}")

                                    # Track per-user memory
                                    self.user_memory.track_url(result)

                                    # Detect issues
                                    issues_before = len(self.issue_detector.detected_issues)
                                    self.issue_detector.detect_issues(result)
                                    issues_after = len(self.issue_detector.detected_issues)

                                    # Track + batch new issues
                                    if issues_after > issues_before:
                                        new_issues = self.issue_detector.detected_issues[issues_before:issues_after]
                                        self.user_memory.track_issues(new_issues)
                                        if self.db_save_enabled:
                                            self.unsaved_issues.extend(new_issues)
                            except Exception as e:
                                print(f"Error in crawl task: {e}")

                    # Remove completed futures
                    for future in completed_futures:
                        del active_futures[future]

                    # Demo mode: check per-user memory limit
                    if self.config.get('demo_mode') and self.user_memory.total_bytes >= self.config.get('demo_memory_limit_bytes', 0):
                        print(f"DEMO MODE: Per-user memory limit reached ({self.user_memory.total_mb:.0f}MB)")
                        self._demo_limit_reached = True
                        break

                    # Check for completion
                    if self.stats['crawled'] >= self.config['max_urls']:
                        print(f"Reached maximum URLs limit ({self.config['max_urls']})")
                        break

                    # Check if no more work
                    link_stats = self.link_manager.get_stats()
                    if link_stats['pending'] == 0 and len(active_futures) == 0:
                        print("No more URLs to crawl")
                        break

                    # Tiny sleep only to yield CPU
                    time.sleep(0.001)

                except Exception as e:
                    print(f"Error in crawl worker: {e}")
                    time.sleep(1)

        # Skip post-processing if demo limit was hit — no further memory use
        if not self._demo_limit_reached:
            # Run PageSpeed analysis if enabled
            if self.config.get('enable_pagespeed', False):
                print("Running PageSpeed analysis...")
                self.is_running_pagespeed = True
                self._run_pagespeed_analysis()
                self.is_running_pagespeed = False

            # Update all linked_from fields before completing
            self._update_all_linked_from()

            # Run duplication detection on all crawled content
            if self.issue_detector and self.config.get('enable_duplication_check', True):
                print("Running duplication detection...")
                duplication_threshold = self.config.get('duplication_threshold', 0.85)
                self.duplicate_groups = self.issue_detector.build_duplicate_groups(self.crawl_results, duplication_threshold)
                self.issue_detector.detect_duplication_issues(self.crawl_results, duplication_threshold)
                print(f"Duplication detection complete. Total issues: {len(self.issue_detector.get_issues())}")

        # Save final data and set appropriate status
        if self.db_save_enabled and self.crawl_id:
            self._save_batch_to_db(force=True)
            from src.crawl_db import set_crawl_status
            if self._demo_limit_reached:
                set_crawl_status(self.crawl_id, 'demo_stopped')
            else:
                set_crawl_status(self.crawl_id, 'completed')

        # Mark crawl as complete
        self.is_running = False
        if self._demo_limit_reached:
            print(f"Crawl stopped (demo limit). User memory: {self.user_memory.total_mb:.0f}MB. Crawled: {self.stats['crawled']}")
        else:
            print(f"Crawl completed. Discovered: {self.stats['discovered']}, Crawled: {self.stats['crawled']}")

    def _crawl_url(self, url, depth):
        """Crawl a single URL"""
        # Use JavaScript rendering if enabled
        if self.config.get('enable_javascript', False):
            return asyncio.run(self._crawl_url_with_javascript(url, depth))
        else:
            return self._crawl_url_with_requests(url, depth)

    def _crawl_url_with_requests(self, url, depth):
        """Crawl a single URL using traditional HTTP requests"""
        print(f"Starting crawl of {url}")
        retries = self.config.get('retries', 3)
        start_time = time.time()

        try:
            # Check file size if configured
            if self.config.get('max_file_size', 0) > 0:
                try:
                    self._wait_for_request_slot()
                    head_response = self.session.head(
                        url,
                        timeout=self.config['timeout'],
                        allow_redirects=self.config['follow_redirects']
                    )
                    if head_response.status_code == 429:
                        self._defer_after_rate_limit(head_response, 0)
                    content_length = head_response.headers.get('content-length')
                    if content_length and int(content_length) > self.config['max_file_size']:
                        return self.seo_extractor.create_empty_result(
                            url, depth, 0,
                            f'File too large: {content_length} bytes',
                            error_type='file_too_large'
                        )
                except:
                    pass  # Continue if HEAD request fails

            # Fetch the page with retries
            response = None
            for attempt in range(retries + 1):
                try:
                    self._wait_for_request_slot()
                    response = self.session.get(
                        url,
                        timeout=self.config['timeout'],
                        allow_redirects=self.config['follow_redirects']
                    )
                    if response.status_code == 429 and attempt < retries:
                        self._defer_after_rate_limit(response, attempt)
                        continue
                    if (response.status_code >= 500 and self.config.get('retry_5xx', True)
                            and attempt < int(self.config.get('retry_5xx_attempts', 2))):
                        time.sleep(min(2 ** attempt, 5))
                        continue
                    break
                except Exception as e:
                    if attempt >= retries:
                        raise e
                    time.sleep(1)

            # Determine if URL is internal
            is_internal = self.link_manager.is_internal(url)

            # Create result structure
            result = {
                'url': url,
                'status_code': response.status_code,
                'error_type': None,
                'content_type': response.headers.get('content-type', '').split(';')[0],
                'media_type': response.headers.get('content-type', '').split(';')[0],
                'media_metadata': {},
                'size': len(response.content),
                'is_internal': is_internal,
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
                'external_links': 0,
                'internal_links': 0,
                'response_time': 0,
                'http_headers': dict(response.headers),
                'cookies': [
                    {'name': cookie.name, 'value': cookie.value,
                     'domain': cookie.domain, 'path': cookie.path}
                    for cookie in response.cookies
                ],
                'security': {
                    'https': urlparse(url).scheme == 'https',
                    'hsts': bool(response.headers.get('strict-transport-security')),
                    'hsts_header': response.headers.get('strict-transport-security', '')
                },
                'redirects': [],
                'hreflang': [],
                'schema_org': [],
                'linked_from': []
            }
            snapshot_limit = int(self.config.get('html_snapshot_limit', 500000) or 500000)
            result['source_html'] = response.text[:snapshot_limit]
            result['rendered_html'] = ''
            result['extracted_text'] = ''
            result['snapshot_type'] = 'source'
            result['snapshot_captured_at'] = datetime.utcnow().isoformat() + 'Z'
            if result['security']['hsts']:
                self._hsts_hosts.add(urlparse(url).netloc.lower())

            result['redirects'] = [
                {'from': hop.url, 'to': hop.headers.get('location', ''),
                 'status_code': hop.status_code}
                for hop in response.history
            ]
            if response.history:
                result['redirect_final_url'] = response.url
                result['redirect_hops'] = len(response.history)
                max_redirects = self.config.get('max_redirects', 0)
                if max_redirects and len(response.history) > max_redirects:
                    result['error_type'] = 'max_redirects_exceeded'
                    result['error'] = f'Maximum redirects exceeded: {len(response.history)} > {max_redirects}'

            # Only parse HTML content
            if 'text/html' in response.headers.get('content-type', ''):
                soup = BeautifulSoup(response.content, 'html.parser')

                # Extract comprehensive data using SEO extractor
                self.seo_extractor.extract_basic_seo_data(soup, result)
                self.seo_extractor.extract_meta_tags(soup, result)
                self.seo_extractor.extract_opengraph_tags(soup, result)
                self.seo_extractor.extract_twitter_tags(soup, result)
                self.seo_extractor.extract_json_ld(soup, result)
                self.seo_extractor.extract_analytics_tracking(soup, response.text, result)
                self.seo_extractor.extract_images(soup, url, result)
                self.seo_extractor.extract_resources(soup, url, result)
                self.seo_extractor.extract_advanced_directives(soup, url, result)
                self._enqueue_special_directives(result, depth)
                self.seo_extractor.extract_link_counts(soup, result, self.base_domain)
                self.seo_extractor.extract_hreflang(soup, result)
                self.seo_extractor.extract_schema_org(soup, result)
                self.seo_extractor.extract_accessibility(soup, result)
                self.seo_extractor.validate_html(response.text, result)
                from src.core.content_analysis import analyze_content
                result['content_analysis'] = analyze_content(soup, self.config.get('content_area_selector', ''))
                result['extracted_text'] = (result.get('content_analysis') or {}).get('content_text', '')
                self.seo_extractor.extract_custom(
                    response.text, result, self.config.get('custom_extractions', [])
                )
                self.seo_extractor.extract_custom_search(
                    response.text, result, self.config.get('custom_searches', [])
                )

                # Collect all links
                links_before = len(self.link_manager.all_links)
                self.link_manager.collect_all_links(soup, url, self.crawl_results)
                links_after = len(self.link_manager.all_links)

                # Track + batch new links
                if links_after > links_before:
                    new_links = self.link_manager.all_links[links_before:links_after]

                    # HEAD-check image URLs for broken image detection
                    image_links = [l for l in new_links if l.get('placement') == 'image']
                    if image_links:
                        self._check_image_statuses(image_links)
                        broken = [l for l in image_links
                                  if l.get('target_status') is not None
                                  and (l['target_status'] >= 400 or l['target_status'] == 0)]
                        if broken:
                            result['broken_images'] = [
                                {'url': l['target_url'], 'status': l['target_status']}
                                for l in broken
                            ]

                    self.user_memory.track_links(new_links)
                    if self.db_save_enabled:
                        self.unsaved_links.extend(new_links)

                # Extract links for further crawling
                should_extract = (
                    (is_internal and depth < self.config['max_depth']) or
                    (self.config['crawl_external'] and depth < self.config['max_depth'])
                )

                if should_extract and not self._should_skip_discovery(result):
                    self.link_manager.extract_links(
                        soup, url, depth + 1, self._should_crawl_url,
                        self.config.get('max_links_per_url', 0)
                    )

            elif (response.headers.get('content-type', '').lower().startswith('application/pdf') or
                  urlparse(url).path.lower().endswith('.pdf')):
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(BytesIO(response.content))
                    text = '\n'.join((page.extract_text() or '') for page in reader.pages)
                    result['pdf_pages'] = len(reader.pages)
                    result['pdf_text'] = text[:500000]
                    result['pdf_metadata'] = dict(reader.metadata or {})
                    result['word_count'] = len(re.findall(r'\b\w+\b', text))
                except Exception as pdf_error:
                    result['pdf_error'] = str(pdf_error)
            elif (response.headers.get('content-type', '').lower().startswith(('application/x-shockwave-flash', 'application/vnd.adobe.flash.movie')) or
                  urlparse(url).path.lower().endswith('.swf')):
                result['media_type'] = 'swf'
                result['media_metadata'] = {'format': 'SWF', 'bytes': len(response.content)}
                result['swf_detected'] = True
            elif response.headers.get('content-type', '').lower().startswith(('image/', 'video/', 'audio/')):
                result['media_metadata'] = {
                    'format': result['content_type'],
                    'bytes': len(response.content),
                    'magic_bytes': response.content[:12].hex()
                }

            # Populate linked_from after all link collection is complete
            result['linked_from'] = self.link_manager.get_source_pages(url)
            result['response_time'] = round((time.time() - start_time) * 1000, 2)

            # Add to unsaved batch if DB persistence enabled
            if self.db_save_enabled:
                self.unsaved_urls.append(result)
                # Trigger batch save if threshold reached
                if len(self.unsaved_urls) >= self.batch_save_size:
                    self._save_batch_to_db()

            return result

        except Exception as e:
            return self.seo_extractor.create_empty_result(
                url, depth, 0, str(e),
                error_type=classify_fetch_error(e)
            )

    def _wait_for_request_slot(self):
        """Apply the configured crawl delay to every outbound HTTP request."""
        if self.rate_limiter:
            self.rate_limiter.acquire()

    def _defer_after_rate_limit(self, response, attempt):
        """Honor Retry-After or apply a conservative shared 429 cooldown."""
        retry_after = response.headers.get('retry-after', '').strip()
        try:
            cooldown = float(retry_after)
        except (TypeError, ValueError):
            cooldown = min(10 * (2 ** attempt), 60)
        cooldown = max(1, min(cooldown, 120))
        if self.rate_limiter:
            self.rate_limiter.defer(cooldown)
        print(f"Rate limited (429), pausing all workers for {cooldown:.1f} seconds...")

    async def _crawl_url_with_javascript(self, url, depth):
        """Crawl a single URL using JavaScript rendering"""
        start_time = time.time()

        try:
            # Render page with JavaScript
            html_content, status_code, error, screenshot_path, js_errors, archive_path, render_diagnostics = await self.js_renderer.render_page(url)

            if error:
                return self.seo_extractor.create_empty_result(
                    url, depth, status_code, error,
                    error_type=classify_fetch_error(error) if status_code == 0 else None
                )

            # Determine if URL is internal
            is_internal = self.link_manager.is_internal(url)

            # Create result structure
            result = {
                'url': url,
                'status_code': status_code,
                'error_type': None,
                'content_type': 'text/html',
                'size': len(html_content.encode('utf-8')),
                'is_internal': is_internal,
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
                'external_links': 0,
                'internal_links': 0,
                'response_time': 0,
                'redirects': [],
                'hreflang': [],
                'schema_org': [],
                'linked_from': [],
                'javascript_rendered': True
                , 'screenshot_path': screenshot_path
                , 'javascript_errors': js_errors
                , 'rendered_archive_path': archive_path
                , 'render_diagnostics': render_diagnostics
            }
            snapshot_limit = int(self.config.get('html_snapshot_limit', 500000) or 500000)
            result['source_html'] = ''
            result['rendered_html'] = html_content[:snapshot_limit]
            result['extracted_text'] = ''
            result['snapshot_type'] = 'rendered'
            result['snapshot_captured_at'] = datetime.utcnow().isoformat() + 'Z'

            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract comprehensive data
            self.seo_extractor.extract_basic_seo_data(soup, result)
            self.seo_extractor.extract_meta_tags(soup, result)
            self.seo_extractor.extract_opengraph_tags(soup, result)
            self.seo_extractor.extract_twitter_tags(soup, result)
            self.seo_extractor.extract_json_ld(soup, result)
            self.seo_extractor.extract_analytics_tracking(soup, html_content, result)
            self.seo_extractor.extract_images(soup, url, result)
            self.seo_extractor.extract_resources(soup, url, result)
            self.seo_extractor.extract_advanced_directives(soup, url, result)
            self._enqueue_special_directives(result, depth)
            self.seo_extractor.extract_link_counts(soup, result, self.base_domain)
            self.seo_extractor.extract_hreflang(soup, result)
            self.seo_extractor.extract_schema_org(soup, result)
            self.seo_extractor.extract_accessibility(soup, result)
            self.seo_extractor.validate_html(html_content, result)
            from src.core.content_analysis import analyze_content
            result['content_analysis'] = analyze_content(soup, self.config.get('content_area_selector', ''))
            result['extracted_text'] = (result.get('content_analysis') or {}).get('content_text', '')
            self.seo_extractor.extract_custom(
                html_content, result, self.config.get('custom_extractions', [])
            )
            self.seo_extractor.extract_custom_search(
                html_content, result, self.config.get('custom_searches', [])
            )

            # Collect all links
            links_before = len(self.link_manager.all_links)
            self.link_manager.collect_all_links(soup, url, self.crawl_results)
            links_after = len(self.link_manager.all_links)

            # Track + batch new links
            if links_after > links_before:
                new_links = self.link_manager.all_links[links_before:links_after]

                # HEAD-check image URLs for broken image detection
                image_links = [l for l in new_links if l.get('placement') == 'image']
                if image_links:
                    self._check_image_statuses(image_links)
                    broken = [l for l in image_links
                              if l.get('target_status') is not None
                              and (l['target_status'] >= 400 or l['target_status'] == 0)]
                    if broken:
                        result['broken_images'] = [
                            {'url': l['target_url'], 'status': l['target_status']}
                            for l in broken
                        ]

                self.user_memory.track_links(new_links)
                if self.db_save_enabled:
                    self.unsaved_links.extend(new_links)

            # Extract links for further crawling
            should_extract = (
                (is_internal and depth < self.config['max_depth']) or
                (self.config['crawl_external'] and depth < self.config['max_depth'])
            )

            if should_extract and not self._should_skip_discovery(result):
                self.link_manager.extract_links(soup, url, depth + 1, self._should_crawl_url)

            # Populate linked_from after all link collection is complete
            result['linked_from'] = self.link_manager.get_source_pages(url)
            result['response_time'] = round((time.time() - start_time) * 1000, 2)

            # Add to unsaved batch if DB persistence enabled
            if self.db_save_enabled:
                self.unsaved_urls.append(result)
                # Trigger batch save if threshold reached
                if len(self.unsaved_urls) >= self.batch_save_size:
                    self._save_batch_to_db()

            return result

        except Exception as e:
            return self.seo_extractor.create_empty_result(
                url, depth, 0, f'JavaScript rendering error: {str(e)}',
                error_type=classify_fetch_error(e)
            )

    async def _crawl_async_with_js(self):
        """Async crawling loop for JavaScript rendering"""
        try:
            # Initialize JavaScript renderer
            await self.js_renderer.initialize()

            max_workers = self.config.get('js_max_concurrent_pages', 3)
            active_tasks = set()

            while self.is_running and self.stats['crawled'] < self.config['max_urls']:
                # Check if paused
                if self.is_paused:
                    await asyncio.sleep(1)
                    continue

                # Submit new tasks - fill ALL available slots
                while len(active_tasks) < max_workers:
                    url_info = self.link_manager.get_next_url()
                    if not url_info:
                        break

                    current_url, depth = url_info

                    if depth <= self.config['max_depth']:
                        # SMOOTH RATE LIMITING: Only apply if delay > 0
                        if self.config.get('delay', 0) > 0:
                            self.rate_limiter.acquire()

                        # Create task
                        task = asyncio.create_task(self._crawl_url_with_javascript(current_url, depth))
                        active_tasks.add(task)

                # Process completed tasks
                if active_tasks:
                    done, active_tasks = await asyncio.wait(active_tasks, timeout=0.01, return_when=asyncio.FIRST_COMPLETED)

                    for task in done:
                        try:
                            result = await task
                            if result:
                                with self.results_lock:
                                    self.crawl_results.append(result)
                                    self.stats['crawled'] += 1
                                    self.stats['depth'] = max(self.stats['depth'], result.get('depth', 0))
                                    print(f"Added URL to results (JS): {result['url']} - Total in results: {len(self.crawl_results)}")

                                # Track per-user memory
                                self.user_memory.track_url(result)

                                # Detect issues
                                issues_before = len(self.issue_detector.detected_issues)
                                self.issue_detector.detect_issues(result)
                                issues_after = len(self.issue_detector.detected_issues)

                                # Track + batch new issues
                                if issues_after > issues_before:
                                    new_issues = self.issue_detector.detected_issues[issues_before:issues_after]
                                    self.user_memory.track_issues(new_issues)
                                    if self.db_save_enabled:
                                        self.unsaved_issues.extend(new_issues)
                        except Exception as e:
                            print(f"Error in async crawl task: {e}")

                # Demo mode: check per-user memory limit
                if self.config.get('demo_mode') and self.user_memory.total_bytes >= self.config.get('demo_memory_limit_bytes', 0):
                    print(f"DEMO MODE: Per-user memory limit reached ({self.user_memory.total_mb:.0f}MB)")
                    self._demo_limit_reached = True
                    break

                # Check completion
                link_stats = self.link_manager.get_stats()
                if link_stats['pending'] == 0 and len(active_tasks) == 0:
                    print("No more URLs to crawl")
                    break

                await asyncio.sleep(0.001)

            # Skip post-processing if demo limit was hit
            if not self._demo_limit_reached:
                # Run PageSpeed if enabled
                if self.config.get('enable_pagespeed', False):
                    self.is_running_pagespeed = True
                    self._run_pagespeed_analysis()
                    self.is_running_pagespeed = False

        finally:
            if not self._demo_limit_reached:
                # Update all linked_from fields before completing
                self._update_all_linked_from()

                # Run duplication detection on all crawled content
                if self.issue_detector and self.config.get('enable_duplication_check', True):
                    print("Running duplication detection...")
                    duplication_threshold = self.config.get('duplication_threshold', 0.85)
                    self.duplicate_groups = self.issue_detector.build_duplicate_groups(self.crawl_results, duplication_threshold)
                    self.issue_detector.detect_duplication_issues(self.crawl_results, duplication_threshold)
                    print(f"Duplication detection complete. Total issues: {len(self.issue_detector.get_issues())}")

            # Save final data and set appropriate status
            if self.db_save_enabled and self.crawl_id:
                self._save_batch_to_db(force=True)
                from src.crawl_db import set_crawl_status
                if self._demo_limit_reached:
                    set_crawl_status(self.crawl_id, 'demo_stopped')
                else:
                    set_crawl_status(self.crawl_id, 'completed')

            # Clean up
            await self.js_renderer.cleanup()
            self.is_running = False
            print(f"Crawl completed. Discovered: {self.stats['discovered']}, Crawled: {self.stats['crawled']}")

    def _update_all_linked_from(self):
        """Update linked_from field for all crawled URLs based on collected source_pages data"""
        print("Updating linked_from data for all URLs...")
        updated_count = 0

        for result in self.crawl_results:
            url = result['url']
            sources = self.link_manager.get_source_pages(url)
            if sources:
                result['linked_from'] = sources
                updated_count += 1

        print(f"Updated linked_from data for {updated_count} URLs")

    def _check_image_statuses(self, image_links):
        """HEAD-check image URLs to detect broken images.

        Uses a per-crawl cache so the same image URL is only checked once
        even if it appears on many pages.  Runs up to 5 checks in parallel,
        capped at 50 images per page to avoid blocking the crawl.
        """
        to_check = []
        for link in image_links:
            url = link['target_url']
            cached = self._image_status_cache.get(url)
            if cached is not None:
                link['target_status'] = cached
            elif link.get('target_status') is None:
                to_check.append(link)

        if not to_check:
            return

        def _head_check(link):
            url = link['target_url']
            try:
                self._wait_for_request_slot()
                resp = self.session.head(url, timeout=5, allow_redirects=True)
                if resp.status_code == 429:
                    self._defer_after_rate_limit(resp, 0)
                link['target_status'] = resp.status_code
            except Exception:
                link['target_status'] = 0
            self._image_status_cache[url] = link['target_status']

        batch = to_check[:50]
        with ThreadPoolExecutor(max_workers=min(5, len(batch))) as pool:
            pool.map(_head_check, batch)

    def _should_skip_discovery(self, result):
        directives = result.get('directives') or {}
        robots = str(result.get('robots', '')).lower()
        return ((self.config.get('respect_noindex') and (directives.get('noindex') or 'noindex' in robots)) or
                (self.config.get('respect_nofollow') and (directives.get('nofollow') or 'nofollow' in robots)))

    def _enqueue_special_directives(self, result, depth):
        if (self.config.get('respect_canonical') or self.config.get('follow_canonical')) and result.get('canonical_url'):
            self.link_manager.enqueue_url(result['canonical_url'], depth + 1, self._should_crawl_url)
        if self.config.get('follow_meta_refresh') and result.get('meta_refresh'):
            refresh = str(result['meta_refresh'])
            match = re.search(r'url\s*=\s*(.+)$', refresh, re.I)
            if match:
                target = urljoin(result.get('url', ''), match.group(1).strip(' \t\"\''))
                self.link_manager.enqueue_url(target, depth + 1, self._should_crawl_url)
        if self.config.get('respect_next_prev'):
            pagination = result.get('pagination') or {}
            for target in (pagination.get('next'), pagination.get('prev')):
                if target:
                    self.link_manager.enqueue_url(target, depth + 1, self._should_crawl_url)

    def _should_crawl_url(self, url, candidate_depth=None):
        """Check if URL should be crawled based on settings"""
        parsed = urlparse(url)

        if parsed.fragment and not self.config.get('crawl_fragments', False):
            return False

        # Check external domain policy
        if not self.config['crawl_external']:
            host = parsed.netloc.lower().split(':', 1)[0]
            base_host = self.base_domain.lower().split(':', 1)[0]
            subdomain_internal = self.config.get('crawl_all_subdomains') and host.endswith('.' + base_host)
            if not subdomain_internal and not self.link_manager.is_internal(url):
                return False

        if not self.config.get('crawl_outside_start_folder', True) and self.base_url:
            start_path = urlparse(self.base_url).path.rstrip('/') or '/'
            candidate_path = parsed.path.rstrip('/') or '/'
            if not (candidate_path == start_path.rstrip('/') or candidate_path.startswith(start_path.rstrip('/') + '/')):
                return False
        if self.config.get('respect_hsts') and parsed.scheme == 'http' and parsed.netloc.lower() in self._hsts_hosts:
            return False

        if self.config.get('max_url_length', 0) and len(url) > self.config['max_url_length']:
            return False
        if self.config.get('max_query_strings', 0) and len(parsed.query.split('&')) > self.config['max_query_strings']:
            return False
        if self.config.get('max_folder_depth', 0):
            folder_depth = len([part for part in parsed.path.split('/') if part])
            if folder_depth > self.config['max_folder_depth']:
                return False

        # Apply crawl quotas before enqueueing a URL. Include both already
        # crawled results and queued discoveries so concurrent workers cannot
        # substantially exceed the configured limits.
        if self.config.get('max_urls_per_depth', 0) and candidate_depth is not None:
            depth_count = sum(1 for row in self.crawl_results if row.get('depth') == candidate_depth)
            depth_count += sum(1 for queued_url, queued_depth in self.link_manager.discovered_urls if queued_depth == candidate_depth)
            if depth_count >= self.config['max_urls_per_depth']:
                return False
        if self.config.get('max_urls_per_subdomain', 0):
            candidate_host = parsed.netloc.lower().split(':', 1)[0]
            subdomain_count = sum(1 for row in self.crawl_results if urlparse(row.get('url', '')).netloc.lower().split(':', 1)[0] == candidate_host)
            subdomain_count += sum(1 for queued_url, _ in self.link_manager.discovered_urls if urlparse(queued_url).netloc.lower().split(':', 1)[0] == candidate_host)
            if subdomain_count >= self.config['max_urls_per_subdomain']:
                return False

        # Check robots.txt
        if self.config['respect_robots']:
            if not self._check_robots_txt(url):
                return False

        # Check file extensions
        path = parsed.path.lower()
        if '.' in path:
            extension = path.split('.')[-1]

            if extension in self.config['exclude_extensions']:
                return False

            if self.config['include_extensions'] and extension not in self.config['include_extensions']:
                return False

        # Check URL patterns
        if self.config['exclude_patterns']:
            for pattern in self.config['exclude_patterns']:
                if pattern and re.search(pattern, url):
                    return False

        if self.config['include_patterns']:
            pattern_match = False
            for pattern in self.config['include_patterns']:
                if pattern and re.search(pattern, url):
                    pattern_match = True
                    break
            if not pattern_match:
                return False

        return True

    def _check_robots_txt(self, url):
        """Check if URL is allowed by robots.txt"""
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            if robots_url not in self._robots_cache:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                try:
                    # Fetch robots.txt with our session (proper User-Agent)
                    # instead of rp.read() which uses urllib with Python's
                    # default UA — many servers return 403 for that, causing
                    # RobotFileParser to set disallow_all=True and block everything.
                    self._wait_for_request_slot()
                    response = self.session.get(robots_url, timeout=10)
                    if response.status_code == 429:
                        self._defer_after_rate_limit(response, 0)
                    if response.status_code in (401, 403):
                        rp.disallow_all = True
                    elif response.status_code >= 400:
                        rp.allow_all = True
                    else:
                        rp.parse(response.text.splitlines())
                    self._robots_cache[robots_url] = rp
                except:
                    return True

            rp = self._robots_cache[robots_url]
            user_agent = self.config.get('user_agent', '*')
            return rp.can_fetch(user_agent, url)

        except Exception:
            return True

    def _run_pagespeed_analysis(self):
        """Run PageSpeed analysis on selected pages"""
        try:
            selected_pages = self._select_pages_for_pagespeed()

            if not selected_pages:
                print("No suitable pages found for PageSpeed analysis")
                return

            print(f"Running PageSpeed analysis on {len(selected_pages)} pages...")

            pagespeed_results = []
            for i, page_url in enumerate(selected_pages):
                if not self.is_running:
                    print("PageSpeed analysis cancelled")
                    return

                print(f"Analyzing page {i+1}/{len(selected_pages)}: {page_url}")

                # Mobile analysis
                mobile_result = self._call_pagespeed_api(page_url, 'mobile')
                time.sleep(2)

                if not self.is_running:
                    return

                # Desktop analysis
                desktop_result = self._call_pagespeed_api(page_url, 'desktop')

                pagespeed_results.append({
                    'url': page_url,
                    'mobile': mobile_result,
                    'desktop': desktop_result,
                    'analysis_date': time.strftime('%Y-%m-%d %H:%M:%S')
                })

                if i < len(selected_pages) - 1:
                    time.sleep(3)

            self.stats['pagespeed_results'] = pagespeed_results
            print(f"PageSpeed analysis completed for {len(pagespeed_results)} pages")

        except Exception as e:
            print(f"Error running PageSpeed analysis: {e}")

    def _select_pages_for_pagespeed(self):
        """Select homepage and 2 category pages for PageSpeed analysis"""
        selected_pages = []

        # Find homepage
        homepage = None
        min_path_length = float('inf')

        for result in self.crawl_results:
            if result.get('status_code') == 200 and result.get('is_internal'):
                url = result['url']
                parsed = urlparse(url)
                path = parsed.path.rstrip('/')

                if path == '' or path == '/':
                    homepage = url
                    break
                elif len(path) < min_path_length:
                    homepage = url
                    min_path_length = len(path)

        if homepage:
            selected_pages.append(homepage)

        # Find category pages
        category_pages = []
        for result in self.crawl_results:
            if result.get('status_code') == 200 and result.get('is_internal'):
                url = result['url']
                parsed = urlparse(url)
                path = parsed.path.strip('/')

                if path and '/' not in path and url != homepage:
                    category_pages.append(url)

        selected_pages.extend(category_pages[:2])
        return selected_pages

    def _call_pagespeed_api(self, url, strategy='mobile', retries=3):
        """Call Google PageSpeed Insights API"""
        import random

        try:
            api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
            params = {
                'url': url,
                'strategy': strategy,
                'category': 'performance'
            }

            if self.config.get('google_api_key'):
                params['key'] = self.config['google_api_key']

            for attempt in range(retries + 1):
                try:
                    response = requests.get(api_url, params=params, timeout=60)

                    if response.status_code == 200:
                        data = response.json()
                        lighthouse_result = data.get('lighthouseResult', {})
                        audits = lighthouse_result.get('audits', {})
                        categories = lighthouse_result.get('categories', {})

                        performance_score = None
                        if 'performance' in categories:
                            score = categories['performance'].get('score')
                            if score is not None:
                                performance_score = int(score * 100)

                        metrics = {}

                        if 'first-contentful-paint' in audits:
                            fcp = audits['first-contentful-paint'].get('numericValue')
                            metrics['first_contentful_paint'] = round(fcp / 1000, 2) if fcp else None

                        if 'largest-contentful-paint' in audits:
                            lcp = audits['largest-contentful-paint'].get('numericValue')
                            metrics['largest_contentful_paint'] = round(lcp / 1000, 2) if lcp else None

                        if 'cumulative-layout-shift' in audits:
                            cls = audits['cumulative-layout-shift'].get('numericValue')
                            metrics['cumulative_layout_shift'] = round(cls, 3) if cls else None

                        if 'max-potential-fid' in audits:
                            fid = audits['max-potential-fid'].get('numericValue')
                            metrics['first_input_delay'] = round(fid, 2) if fid else None

                        if 'speed-index' in audits:
                            si = audits['speed-index'].get('numericValue')
                            metrics['speed_index'] = round(si / 1000, 2) if si else None

                        if 'interactive' in audits:
                            tti = audits['interactive'].get('numericValue')
                            metrics['time_to_interactive'] = round(tti / 1000, 2) if tti else None

                        return {
                            'success': True,
                            'performance_score': performance_score,
                            'metrics': metrics,
                            'strategy': strategy
                        }

                    elif response.status_code == 429:
                        if attempt < retries:
                            delay = (2 ** attempt) * random.uniform(0.5, 1.5)
                            print(f"Rate limited, retrying in {delay:.1f} seconds...")
                            time.sleep(delay)
                            continue

                    return {
                        'success': False,
                        'error': f"API returned status {response.status_code}",
                        'strategy': strategy
                    }

                except requests.exceptions.RequestException as e:
                    if attempt < retries:
                        time.sleep(3)
                        continue
                    return {
                        'success': False,
                        'error': f"Network error: {str(e)}",
                        'strategy': strategy
                    }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'strategy': strategy
            }
